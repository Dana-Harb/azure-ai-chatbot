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
    # IMPORTANT: Azure expects strings here, not objects.
    # The server chooses the concrete PCM16 rate; your client can still stream 24kHz PCM16.
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
            # Keeping additional_headers as requested
            ws = await websockets.connect(ws_url, additional_headers=headers)
            logger.info("Connected to GPT-Realtime websocket")
            return ws
        except InvalidStatusCode as e:
            if e.status_code == 429 and attempt < max_retries:
                wait = 2  # simple fixed backoff
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

    # Use try/finally so cleanup happens once and only once
    try:
        # Connect upstream
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
                            audio_b64 = base64.b64encode(msg["bytes"]).decode("utf-8")
                            await gpt_ws.send(json.dumps({
                                "type": "input_audio_buffer.append",
                                "audio": audio_b64
                            }))
                        elif "text" in msg and msg["text"]:
                            try:
                                payload = json.loads(msg["text"])
                                if payload.get("type") == "commit":
                                    await gpt_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                                elif payload.get("type") == "input_text":
                                    await gpt_ws.send(json.dumps(payload))
                                else:
                                    # Fallback as input_text if unknown
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
            try:
                while not cancel.is_set():
                    msg = await gpt_ws.recv()
                    if isinstance(msg, (bytes, bytearray)):
                        if ws_is_connected(websocket):
                            audio_b64 = base64.b64encode(msg).decode("utf-8")
                            await websocket.send_text(json.dumps({"audioChunk": audio_b64, "transcript": None}))
                    else:
                        # JSON or plain text from GPT
                        try:
                            data = json.loads(msg)
                            audio_b64 = data.get("audio")
                            transcript = data.get("transcript") or data.get("text")
                            if ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({"audioChunk": audio_b64, "transcript": transcript}))
                        except json.JSONDecodeError:
                            if ws_is_connected(websocket):
                                await websocket.send_text(json.dumps({"audioChunk": None, "transcript": msg}))
            except (ConnectionClosedOK, ConnectionClosedError):
                cancel.set()
            except Exception as e:
                logger.error(f"GPT->Frontend error: {e}")
                cancel.set()

        # Run both directions
        t_send = asyncio.create_task(forward_frontend())
        t_recv = asyncio.create_task(forward_gpt())
        done, pending = await asyncio.wait({t_send, t_recv}, return_when=asyncio.FIRST_COMPLETED)

        # Cancel the other task
        for t in pending:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    finally:
        cancel.set()
        # Close upstream ws
        try:
            if gpt_ws and not getattr(gpt_ws, "closed", False):
                await gpt_ws.close()
        except Exception:
            pass
        # Close frontend ws once
        try:
            if ws_is_connected(websocket):
                await websocket.close()
        except Exception:
            pass
        logger.info("Live chat session ended")