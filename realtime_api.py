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

# Optional: if True, barge in on ANY user speech while bot is speaking (ignores keywords)
CANCEL_ON_ANY_USER_SPEECH = False

def build_session_update():
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],  # ensure both
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
            "tool_choice": "auto"
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

    # Track current response and drop state for precise cancel + stop streaming
    state = {
        "model_speaking": False,
        "drop_audio": False,            # when True, do not forward bot audio to frontend
        "current_response_id": None,    # track current response to cancel precisely
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

        # Debounce for server-side barge-in
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
                        # Mic audio bytes from client
                        if "bytes" in msg and msg["bytes"]:
                            # Only forward audio upstream if not dropping
                            if not state["drop_audio"]:
                                audio_b64 = base64.b64encode(msg["bytes"]).decode("utf-8")
                                await gpt_ws.send(json.dumps({
                                    "type": "input_audio_buffer.append",
                                    "audio": audio_b64
                                }))

                        # Text payload from client (commands, etc.)
                        elif "text" in msg and msg["text"]:
                            try:
                                payload = json.loads(msg["text"])
                                ptype = payload.get("type")

                                if ptype == "commit":
                                    await gpt_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                                    # Force both modalities for each reply
                                    await gpt_ws.send(json.dumps({
                                        "type": "response.create",
                                        "response": { "modalities": ["text", "audio"] }
                                    }))

                                elif ptype == "input_text":
                                    await gpt_ws.send(json.dumps(payload))

                                elif ptype == "stop":
                                    # Client requested stop -> immediately flush and cancel
                                    state["drop_audio"] = True
                                    if ws_is_connected(websocket):
                                        await websocket.send_text(json.dumps({"event": "flush_audio"}))
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
                                    # Fallback: treat as plain input_text
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
                        if ws_is_connected(websocket):
                            await websocket.send_text(json.dumps({"transcript": str(raw), "who": "bot"}))
                        continue

                    etype = data.get("type")

                    # Track current response id
                    if etype in ("response.created", "response.started"):
                        rid = data.get("id") or (data.get("response") or {}).get("id")
                        if rid:
                            state["current_response_id"] = rid
                        # SEND A CLEAR BOUNDARY TO FRONTEND AND RESET LOCAL BUFFER
                        bot_tr = ""
                        user_tr = ""
                        if ws_is_connected(websocket):
                            await websocket.send_text(json.dumps({
                                "event": "new_response",
                                "response_id": rid
                            }))

                    # Bot audio deltas (output)
                    if etype in ("response.output_audio.delta", "response.audio.delta"):
                        if not state["model_speaking"]:
                            state["model_speaking"] = True
                            state["drop_audio"] = False
                            last_stop_at = 0.0  # reset debounce on new speech
                            if ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({"event": "model_speech_start"}))
                        if not state["drop_audio"]:
                            delta_b64 = data.get("delta")
                            if delta_b64 and ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({"audioChunk": delta_b64}))

                    # Bot text deltas (handle multiple possible event names)
                    elif etype in ("response.output_text.delta", "response.text.delta", "response.content_part.added", "response.content_part.delta", "response.refusal.delta"):
                        # Try to extract text from typical fields
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

                    # Final text done events (optional)
                    elif etype in ("response.output_text.done", "response.text.done"):
                        # Some providers send a final text chunk here
                        final_delta = data.get("text") or data.get("delta") or ""
                        if isinstance(final_delta, str) and final_delta:
                            bot_tr += final_delta
                            if ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({"transcript": bot_tr, "who": "bot"}))

                    # User transcription deltas from audio (input)
                    elif etype in ("response.input_audio_transcription.delta", "input_audio_transcription.delta"):
                        delta_txt = data.get("delta", "")
                        if delta_txt and ws_is_connected(websocket):
                            user_tr += delta_txt
                            await websocket.send_text(json.dumps({"transcript": user_tr, "who": "user"}))

                        # Server-side barge-in (detect stop in audio transcription)
                        if delta_txt and state["model_speaking"]:
                            now = time.monotonic()
                            if (now - last_stop_at) > STOP_DEBOUNCE_SEC:
                                # Decide whether to cancel based on config/keywords
                                if CANCEL_ON_ANY_USER_SPEECH:
                                    should_cancel = bool(delta_txt.strip())
                                else:
                                    should_cancel = is_stop_phrase(delta_txt) or is_stop_phrase(user_tr)

                                if should_cancel:
                                    last_stop_at = now
                                    # Immediately stop sending/playing audio
                                    state["drop_audio"] = True
                                    if ws_is_connected(websocket):
                                        # Notify frontend to cut any scheduled audio now
                                        await websocket.send_text(json.dumps({"event": "flush_audio"}))
                                        # Optionally reflect interruption in UI transcript quickly
                                        await websocket.send_text(json.dumps({"transcript": "[stopped]", "who": "bot"}))
                                    # Ask model to cancel current response
                                    try:
                                        rid = state.get("current_response_id")
                                        if rid:
                                            await gpt_ws.send(json.dumps({"type": "response.cancel", "response_id": rid}))
                                        await gpt_ws.send(json.dumps({"type": "response.cancel"}))
                                    except Exception:
                                        pass
                                    # Clear any buffered user audio
                                    try:
                                        await gpt_ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
                                    except Exception:
                                        pass

                    # User transcription completed
                    elif etype in ("response.input_audio_transcription.completed", "input_audio_transcription.completed"):
                        final_txt = (data.get("transcript") or data.get("text") or "").strip()
                        if final_txt and ws_is_connected(websocket):
                            user_tr = final_txt
                            await websocket.send_text(json.dumps({"transcript": user_tr, "who": "user"}))
                        # Also check stop on completion (backup)
                        if final_txt and state["model_speaking"]:
                            now = time.monotonic()
                            if (now - last_stop_at) > STOP_DEBOUNCE_SEC and is_stop_phrase(final_txt):
                                last_stop_at = now
                                state["drop_audio"] = True
                                if ws_is_connected(websocket):
                                    await websocket.send_text(json.dumps({"event": "flush_audio"}))
                                    await websocket.send_text(json.dumps({"transcript": "[stopped]", "who": "bot"}))
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

                    # Model cancellation / error acknowledgement
                    elif etype in ("response.canceled", "response.error"):
                        if ws_is_connected(websocket):
                            await websocket.send_text(json.dumps({"event": "flush_audio"}))
                            await websocket.send_text(json.dumps({"event": "model_speech_end"}))
                        state["model_speaking"] = False
                        state["drop_audio"] = True
                        state["current_response_id"] = None

                    # Model finished speaking
                    elif etype in ("response.completed", "response.output_audio.done"):
                        # Fallback: if we never saw any text deltas, try to extract final text from response payload
                        try:
                            if not bot_tr:
                                resp = data.get("response") or {}
                                final_txt = None
                                # Common shapes: {"output_text":"..."}, or {"content":[{"type":"output_text","text":"..."}]}
                                if isinstance(resp.get("output_text"), str) and resp.get("output_text").strip():
                                    final_txt = resp.get("output_text").strip()
                                elif isinstance(resp.get("content"), list):
                                    for part in resp.get("content", []):
                                        if isinstance(part, dict):
                                            txt = part.get("text") or part.get("output_text")
                                            if isinstance(txt, str) and txt.strip():
                                                final_txt = (final_txt + " " + txt.strip()) if final_txt else txt.strip()
                                if final_txt and ws_is_connected(websocket):
                                    bot_tr = final_txt
                                    await websocket.send_text(json.dumps({"transcript": bot_tr, "who": "bot"}))
                        except Exception as e:
                            logger.debug(f"final text extraction failed: {e}")

                        if ws_is_connected(websocket):
                            await websocket.send_text(json.dumps({"event": "model_speech_end"}))
                        state["model_speaking"] = False
                        state["drop_audio"] = False
                        state["current_response_id"] = None
                        bot_tr = ""
                        try:
                            await gpt_ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
                        except Exception:
                            pass

                    # Function/tool call requested
                    elif etype in (
                        "response.function_call_arguments.done",
                    ):
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
                                parsed_args = (
                                    json.loads(fn_args)
                                    if isinstance(fn_args, str)
                                    else fn_args
                                )
                            except Exception:
                                parsed_args = fn_args
                            # UPDATED: execute via realtime_api_tool.execute_function
                            result = execute_function(fn_name, parsed_args)
                            # Send function result back to the model
                            await gpt_ws.send(json.dumps({
                                "type": "response.function_call_result",
                                "call_id": call_id,
                                "output": result,
                            }))

                            # IMPORTANT: ask the model to continue and speak the answer; force both modalities
                            await gpt_ws.send(json.dumps({
                                "type": "response.create",
                                "response": { "modalities": ["text", "audio"] }
                            }))
                            # send result to frontend for optional display
                            if ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({
                                    "event": "tool_result",
                                    "function": fn_name,
                                    "arguments": parsed_args,
                                    "result": result
                                }))

                    else:
                        # Fallback: pass through audio/text if present
                        audio_b64 = data.get("audio")
                        transcript = data.get("transcript") or data.get("text")
                        if ws_is_connected(websocket) and (audio_b64 or transcript):
                            await websocket.send_text(json.dumps({
                                "audioChunk": audio_b64,
                                "transcript": transcript,
                                "who": "bot"
                            }))

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