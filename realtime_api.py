import os
import json
import base64
import asyncio
import logging
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError, InvalidStatusCode
from starlette.websockets import WebSocketState

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("realtime_api")

# ---------- Environment ----------
load_dotenv()
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
def build_session_update():
    # Azure expects string values for audio formats
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": "You are a helpful assistant that speaks clearly and naturally.",
            "voice": "alloy",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {"type": "server_vad"},
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
        "drop_audio": False,            # when True, don't forward audio to client
        "current_response_id": None,    # ID of the in-flight response (for cancel)
    }

    try:
        # Connect upstream + session setup
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
                            # Raw PCM16 audio chunk from browser worklet
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
                                    # Finalize user's utterance and start model response
                                    await gpt_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                                    await gpt_ws.send(json.dumps({"type": "response.create"}))

                                elif ptype == "input_text":
                                    await gpt_ws.send(json.dumps(payload))

                                elif ptype == "stop":
                                    # Interrupt current bot speech
                                    state["drop_audio"] = True
                                    # Ask client to flush any queued audio immediately
                                    if ws_is_connected(websocket):
                                        await websocket.send_text(json.dumps({"event": "flush_audio"}))
                                    # Try to cancel the exact response if we have the id
                                    try:
                                        rid = state.get("current_response_id")
                                        if rid:
                                            await gpt_ws.send(json.dumps({"type": "response.cancel", "response_id": rid}))
                                        # Fallback generic cancel as well
                                        await gpt_ws.send(json.dumps({"type": "response.cancel"}))
                                    except Exception:
                                        pass
                                    # Also clear any pending input so next question starts clean
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
            user_tr = ""
            bot_tr = ""
            try:
                while not cancel.is_set():
                    raw = await gpt_ws.recv()

                    # Binary (rare) -> forward as base64 if not dropping
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

                    # Track response id for precise cancel
                    if etype in ("response.created", "response.started"):
                        rid = data.get("id") or (data.get("response") or {}).get("id")
                        if rid:
                            state["current_response_id"] = rid

                    # Audio streaming: start/end + deltas
                    if etype in ("response.output_audio.delta", "response.audio.delta"):
                        if not state["model_speaking"]:
                            state["model_speaking"] = True
                            state["drop_audio"] = False
                            if ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({"event": "model_speech_start"}))
                        if not state["drop_audio"]:
                            delta_b64 = data.get("delta")
                            if delta_b64 and ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({"audioChunk": delta_b64}))

                    # Bot text deltas
                    elif etype in ("response.output_text.delta", "response.text.delta"):
                        delta_txt = data.get("delta", "")
                        if delta_txt:
                            bot_tr += delta_txt
                            if ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({"transcript": bot_tr, "who": "bot"}))

                    # User transcription deltas
                    elif etype in ("response.input_audio_transcription.delta", "input_audio_transcription.delta"):
                        delta_txt = data.get("delta", "")
                        if delta_txt and ws_is_connected(websocket):
                            user_tr += delta_txt
                            await websocket.send_text(json.dumps({"transcript": user_tr, "who": "user"}))

                    # Final user transcription
                    elif etype in ("response.input_audio_transcription.completed", "input_audio_transcription.completed"):
                        final_txt = (data.get("transcript") or data.get("text") or "").strip()
                        if final_txt and ws_is_connected(websocket):
                            user_tr = final_txt
                            await websocket.send_text(json.dumps({"transcript": user_tr, "who": "user"}))

                    # Response canceled or errored
                    elif etype in ("response.canceled", "response.error"):
                        if ws_is_connected(websocket):
                            # Tell client to flush any queued audio and end speaking
                            await websocket.send_text(json.dumps({"event": "flush_audio"}))
                            await websocket.send_text(json.dumps({"event": "model_speech_end"}))
                        state["model_speaking"] = False
                        state["drop_audio"] = True
                        state["current_response_id"] = None

                    # Response completed
                    elif etype in ("response.completed", "response.output_audio.done"):
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

                    # Generic passthrough
                    else:
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