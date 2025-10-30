from dotenv import load_dotenv
load_dotenv()
import os
import json
import base64
import asyncio
import logging
import websockets
import re
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError, InvalidStatusCode
from starlette.websockets import WebSocketState

from realtime_api_tool import realtime_func_definitions, execute_function

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("realtime_api")

# ---------- Environment ----------
GPT_REALTIME_API_KEY = os.getenv("GPT_REALTIME_API_KEY")
GPT_REALTIME_URI = os.getenv("GPT_REALTIME_URI")

if not GPT_REALTIME_API_KEY or not GPT_REALTIME_URI:
    raise RuntimeError("Missing GPT_REALTIME_API_KEY or GPT_REALTIME_URI in .env")

# Convert HTTPS endpoint to WSS (for realtime streaming)
if GPT_REALTIME_URI.startswith("https://"):
    GPT_REALTIME_URI = GPT_REALTIME_URI.replace("https://", "wss://")

# ---------- FastAPI ----------
app = FastAPI(title="Azure GPT Realtime Chat", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# ---------- Helpers ----------
STOP_RE = re.compile(r"\b(stop|cancel|pause|hold on|wait|quiet|be quiet|silence|shut up)\b", re.I)
def is_stop_phrase(s: str) -> bool:
    if not s:
        return False
    t = s.strip().lower()
    if t in ("st", "sto", "stop", "stop.", "stop!"):
        return True
    return bool(STOP_RE.search(s))

# If True, cancel on any user speech while bot is speaking
CANCEL_ON_ANY_USER_SPEECH = False

def build_session_update():
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": (
                "You are a coffee-only expert assistant. "
                "Stay within coffee: beans, processing, roasting, grinding, extraction theory, brewing methods/recipes, "
                "espresso, water chemistry, equipment setup/maintenance, tasting. "
                "Decline non-coffee topics briefly."
            ),
            "voice": "alloy",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {"type": "server_vad"},
            "tools": realtime_func_definitions(),
            "tool_choice": "auto",
        },
    }

def ws_is_connected(ws: WebSocket) -> bool:
    return ws.application_state == WebSocketState.CONNECTED

async def connect_to_gpt_realtime(ws_url: str, max_retries: int = 3):
    headers = {"api-key": GPT_REALTIME_API_KEY}
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Connecting to GPT-Realtime (attempt {attempt}/{max_retries})")
            ws = await websockets.connect(ws_url, additional_headers=headers)
            logger.info("Connected to GPT-Realtime websocket")
            return ws
        except InvalidStatusCode as e:
            if e.status_code == 429 and attempt < max_retries:
                wait = 2
                logger.info(f"Rate limited (429). Retrying in {wait}s...")
                await asyncio.sleep(wait)
                continue
            raise
        except Exception:
            raise
    raise RuntimeError("Could not connect to GPT-Realtime after retries")

# ---------- WebSocket Bridge ----------
@app.websocket("/ws/livechat")
async def livechat_socket(websocket: WebSocket):
    await websocket.accept()
    logger.info("Frontend connected")

    gpt_ws = None
    cancel = asyncio.Event()

    # Track current response and drop state
    state = {
        "model_speaking": False,
        "drop_audio": False,   # when True, do not forward bot audio
        "drop_text": False,    # when True, do not forward bot text
        "current_response_id": None,
    }

    try:
        try:
            gpt_ws = await connect_to_gpt_realtime(GPT_REALTIME_URI)
            await gpt_ws.send(json.dumps(build_session_update()))
            logger.info("Session update sent")
        except Exception as e:
            logger.error(f"Upstream connect/session failed: {e}")
            if ws_is_connected(websocket):
                try:
                    await websocket.send_text(json.dumps({"error": "GPT connection failed"}))
                except Exception:
                    pass
            return

        last_stop_at = 0.0
        STOP_DEBOUNCE_SEC = 0.6

        # Frontend -> GPT
        async def forward_frontend():
            try:
                while not cancel.is_set():
                    msg = await websocket.receive()
                    t = msg.get("type")

                    if t == "websocket.disconnect":
                        cancel.set()
                        break

                    if t == "websocket.receive":
                        if "bytes" in msg and msg["bytes"]:
                            if not state["drop_audio"]:
                                audio_b64 = base64.b64encode(msg["bytes"]).decode("utf-8")
                                await gpt_ws.send(json.dumps({
                                    "type": "input_audio_buffer.append",
                                    "audio": audio_b64
                                }))

                        elif "text" in msg and msg["text"]:
                            try:
                                payload = json.loads(msg["text"])
                                ptype = payload.get("type")

                                if ptype == "commit":
                                    await gpt_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                                    await gpt_ws.send(json.dumps({
                                        "type": "response.create",
                                        "response": {"modalities": ["text", "audio"]}
                                    }))

                                elif ptype == "input_text":
                                    await gpt_ws.send(json.dumps(payload))

                                elif ptype == "stop":
                                    # Immediate stop: block audio + text, notify UI, cancel upstream
                                    state["drop_audio"] = True
                                    state["drop_text"] = True
                                    if ws_is_connected(websocket):
                                        await websocket.send_text(json.dumps({"event": "flush_audio"}))
                                        await websocket.send_text(json.dumps({"event": "model_speech_end"}))
                                    state["model_speaking"] = False
                                    try:
                                        rid = state.get("current_response_id")
                                        if rid:
                                            await gpt_ws.send(json.dumps({"type": "response.cancel", "response_id": rid}))
                                        await gpt_ws.send(json.dumps({"type": "response.cancel"}))
                                    except Exception:
                                        pass
                                    try:
                                        await gpt_ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
                                    except Exception:
                                        pass

                                else:
                                    await gpt_ws.send(json.dumps({"type": "input_text", "text": msg["text"]}))
                            except Exception:
                                await gpt_ws.send(json.dumps({"type": "input_text", "text": msg["text"]}))
            except WebSocketDisconnect:
                cancel.set()
            except Exception as e:
                logger.error(f"Frontend->GPT error: {e}")
                cancel.set()

        # GPT -> Frontend
        async def forward_gpt():
            nonlocal last_stop_at
            user_tr = ""
            bot_tr = ""
            try:
                while not cancel.is_set():
                    raw = await gpt_ws.recv()

                    # Raw audio bytes from model
                    if isinstance(raw, (bytes, bytearray)):
                        if ws_is_connected(websocket) and not state["drop_audio"]:
                            b64 = base64.b64encode(raw).decode("utf-8")
                            await websocket.send_text(json.dumps({"audioChunk": b64}))
                        continue

                    # JSON events
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        if ws_is_connected(websocket) and not state["drop_text"]:
                            await websocket.send_text(json.dumps({"transcript": str(raw), "who": "bot"}))
                        continue

                    etype = data.get("type")

                    # Response boundary
                    if etype in ("response.created", "response.started"):
                        rid = data.get("id") or (data.get("response") or {}).get("id")
                        state["current_response_id"] = rid
                        # Reset accumulators and drop flags
                        bot_tr = ""
                        user_tr = ""
                        state["drop_audio"] = False
                        state["drop_text"] = False
                        if ws_is_connected(websocket):
                            await websocket.send_text(json.dumps({
                                "event": "new_response",
                                "response_id": rid
                            }))

                    # Audio deltas
                    if etype in ("response.output_audio.delta", "response.audio.delta"):
                        if not state["model_speaking"]:
                            state["model_speaking"] = True
                            state["drop_audio"] = False
                            last_stop_at = 0.0
                            if ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({"event": "model_speech_start"}))
                        if not state["drop_audio"]:
                            delta_b64 = data.get("delta")
                            if delta_b64 and ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({"audioChunk": delta_b64}))

                    # Text deltas (various shapes)
                    elif etype in ("response.output_text.delta", "response.text.delta", "response.content_part.added", "response.content_part.delta", "response.refusal.delta"):
                        if state["drop_text"]:
                            continue
                        delta_txt = ""
                        if "delta" in data and isinstance(data["delta"], str):
                            delta_txt = data["delta"]
                        elif "delta" in data and isinstance(data["delta"], dict) and "text" in data["delta"]:
                            delta_txt = data["delta"]["text"]
                        elif "text" in data and isinstance(data["text"], str):
                            delta_txt = data["text"]
                        if delta_txt:
                            bot_tr += delta_txt
                            if ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({"transcript": bot_tr, "who": "bot"}))

                    # Final text done
                    elif etype in ("response.output_text.done", "response.text.done"):
                        if state["drop_text"]:
                            continue
                        final_delta = data.get("text") or data.get("delta") or ""
                        if isinstance(final_delta, str) and final_delta:
                            bot_tr += final_delta
                            if ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({"transcript": bot_tr, "who": "bot"}))

                    # User transcription (input)
                    elif etype in ("response.input_audio_transcription.delta", "input_audio_transcription.delta"):
                        delta_txt = data.get("delta", "")
                        if delta_txt and ws_is_connected(websocket):
                            user_tr += delta_txt
                            await websocket.send_text(json.dumps({"transcript": user_tr, "who": "user"}))

                        # Server-side barge-in detection
                        if delta_txt and state["model_speaking"]:
                            now = time.monotonic()
                            if (now - last_stop_at) > STOP_DEBOUNCE_SEC:
                                should_cancel = bool(delta_txt.strip()) if CANCEL_ON_ANY_USER_SPEECH else (is_stop_phrase(delta_txt) or is_stop_phrase(user_tr))
                                if should_cancel:
                                    last_stop_at = now
                                    state["drop_audio"] = True
                                    state["drop_text"] = True
                                    if ws_is_connected(websocket):
                                        await websocket.send_text(json.dumps({"event": "flush_audio"}))
                                        await websocket.send_text(json.dumps({"event": "model_speech_end"}))
                                    state["model_speaking"] = False
                                    try:
                                        rid = state.get("current_response_id")
                                        if rid:
                                            await gpt_ws.send(json.dumps({"type": "response.cancel", "response_id": rid}))
                                        await gpt_ws.send(json.dumps({"type": "response.cancel"}))
                                    except Exception:
                                        pass
                                    try:
                                        await gpt_ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
                                    except Exception:
                                        pass

                    elif etype in ("response.input_audio_transcription.completed", "input_audio_transcription.completed"):
                        final_txt = (data.get("transcript") or data.get("text") or "").strip()
                        if final_txt and ws_is_connected(websocket):
                            user_tr = final_txt
                            await websocket.send_text(json.dumps({"transcript": user_tr, "who": "user"}))
                        if final_txt and state["model_speaking"]:
                            now = time.monotonic()
                            if (now - last_stop_at) > STOP_DEBOUNCE_SEC and is_stop_phrase(final_txt):
                                last_stop_at = now
                                state["drop_audio"] = True
                                state["drop_text"] = True
                                if ws_is_connected(websocket):
                                    await websocket.send_text(json.dumps({"event": "flush_audio"}))
                                    await websocket.send_text(json.dumps({"event": "model_speech_end"}))
                                state["model_speaking"] = False
                                try:
                                    rid = state.get("current_response_id")
                                    if rid:
                                        await gpt_ws.send(json.dumps({"type": "response.cancel", "response_id": rid}))
                                    await gpt_ws.send(json.dumps({"type": "response.cancel"}))
                                except Exception:
                                    pass
                                try:
                                    await gpt_ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
                                except Exception:
                                    pass

                    # Cancel/Errors
                    elif etype in ("response.canceled", "response.error"):
                        if ws_is_connected(websocket):
                            await websocket.send_text(json.dumps({"event": "flush_audio"}))
                            await websocket.send_text(json.dumps({"event": "model_speech_end"}))
                        state["model_speaking"] = False
                        state["drop_audio"] = True
                        state["drop_text"] = True
                        state["current_response_id"] = None

                    # Completed speaking
                    elif etype in ("response.completed", "response.output_audio.done"):
                        if ws_is_connected(websocket):
                            await websocket.send_text(json.dumps({"event": "model_speech_end"}))
                        state["model_speaking"] = False
                        state["drop_audio"] = False
                        state["drop_text"] = False
                        state["current_response_id"] = None
                        bot_tr = ""
                        try:
                            await gpt_ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
                        except Exception:
                            pass

                    # Tool call
                    elif etype in ("response.function_call_arguments.done",):
                        fn_name = (
                            data.get("name")
                            or (data.get("function_call", {}) or {}).get("name")
                            or (data.get("tool", {}) or {}).get("name")
                        )
                        fn_args = (
                            data.get("arguments")
                            or (data.get("function_call", {}) or {}).get("arguments")
                            or (data.get("tool", {}) or {}).get("parameters")
                        )
                        call_id = (
                            data.get("call_id")
                            or data.get("id")
                            or (data.get("function_call", {}) or {}).get("call_id")
                            or (data.get("tool", {}) or {}).get("id")
                        )
                        logger.info(f"Function/tool call requested: {fn_name} args: {fn_args}")
                        if fn_name and fn_args is not None:
                            try:
                                parsed_args = json.loads(fn_args) if isinstance(fn_args, str) else fn_args
                            except Exception:
                                parsed_args = fn_args
                            result = execute_function(fn_name, parsed_args)
                            await gpt_ws.send(json.dumps({
                                "type": "response.function_call_result",
                                "call_id": call_id,
                                "output": result,
                            }))
                            await gpt_ws.send(json.dumps({
                                "type": "response.create",
                                "response": {"modalities": ["text", "audio"]}
                            }))
                            if ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({
                                    "event": "tool_result",
                                    "function": fn_name,
                                    "arguments": parsed_args,
                                    "result": result
                                }))

                    else:
                        # Respect drop flags in fallback
                        audio_b64 = data.get("audio")
                        transcript = data.get("transcript") or data.get("text")
                        if ws_is_connected(websocket):
                            if audio_b64 and not state["drop_audio"]:
                                await websocket.send_text(json.dumps({"audioChunk": audio_b64}))
                            if transcript and not state["drop_text"]:
                                await websocket.send_text(json.dumps({"transcript": transcript, "who": "bot"}))

            except (ConnectionClosedOK, ConnectionClosedError):
                cancel.set()
            except Exception as e:
                logger.error(f"GPT->Frontend error: {e}")
                cancel.set()

        t_send = asyncio.create_task(forward_frontend())
        t_recv = asyncio.create_task(forward_gpt())
        done, pending = await asyncio.wait({t_send, t_recv}, return_when=asyncio.FIRST_COMPLETED)

        for t in pending:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    finally:
        cancel.set()
        try:
            if gpt_ws and not getattr(gpt_ws, "closed", False):
                await gpt_ws.close()
        except Exception:
            pass
        try:
            if ws_is_connected(websocket):
                await websocket.close()
        except Exception:
            pass
        logger.info("Live chat session ended")