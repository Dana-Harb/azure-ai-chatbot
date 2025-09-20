import azure.functions as func
import json
import logging
import base64
from session_store import create_session, get_session, update_session, clear_session
from rag_pipeline import generate_response_with_context, index_all_blobs_stream
from speech_interface import listen, synthesize_text_to_audio

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# Index documents at startup
try:
    logging.info("Indexing all documents from Blob Storage...")
    index_all_blobs_stream()
    logging.info("Blob indexing completed.")
except Exception as e:
    logging.error(f"Blob indexing failed at startup: {str(e)}")

@app.route(route="chat", methods=["POST", "OPTIONS"])
def chat(req: func.HttpRequest) -> func.HttpResponse:
    # Handle CORS preflight
    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    session_id = None
    try:
        req_body = req.get_json()
        input_type = req_body.get("input_type", "text")
        message = req_body.get("message", "").strip()
        audio_base64 = req_body.get("audio_base64")
        session_id = req_body.get("session_id")

        if not session_id:
            session_id = create_session()

        user_text = None
        recognized_text = None

        # Speech input
        if input_type == "speech" and audio_base64:
            try:
                logging.info("Processing speech input...")
                audio_bytes = base64.b64decode(audio_base64)
                logging.info(f"Audio data size: {len(audio_bytes)} bytes")
                
                recognized_text = listen(audio_bytes)
                user_text = recognized_text
                logging.info(f"Recognized text: {recognized_text}")
            except Exception as e:
                logging.error(f"STT processing failed: {str(e)}")
                user_text = "[Speech recognition failed]"
                recognized_text = user_text

        # Text input
        elif input_type == "text" and message:
            user_text = message
        else:
            user_text = "[No input provided]"
            recognized_text = user_text

        # Generate RAG response
        rag_response = generate_response_with_context(user_text)
        ai_reply = rag_response.get("answer", "I couldn't generate a response.")
        references = rag_response.get("references", [])

        # Update session history
        update_session(session_id, user_text, ai_reply)

        # TTS - Only generate audio if we have a meaningful response
        audio_response_base64 = None
        if ai_reply and not ai_reply.startswith("I couldn't"):
            try:
                audio_bytes = synthesize_text_to_audio(ai_reply)
                if audio_bytes:
                    audio_response_base64 = base64.b64encode(audio_bytes).decode("utf-8")
                    logging.info("TTS audio generated successfully")
            except Exception as e:
                logging.warning(f"TTS failed: {str(e)}")

        return func.HttpResponse(
            json.dumps({
                "reply": ai_reply,
                "recognized_text": recognized_text,
                "audio_base64": audio_response_base64,
                "references": references,
                "session_id": session_id
            }),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except Exception as e:
        logging.error(f"Unexpected error in chat endpoint: {str(e)}")
        return func.HttpResponse(
            json.dumps({
                "error": "Internal server error",
                "session_id": session_id
            }),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )