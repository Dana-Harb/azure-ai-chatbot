import azure.functions as func
import json
import logging
import base64
from session_store import create_session, get_session, update_session, clear_session
from rag_pipeline import generate_response_with_context, index_all_blobs_stream
from speech_interface import listen, synthesize_text_to_audio

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

exit_keywords = ["exit", "quit", "bye"]
history_command = "/history"
clear_command = "/clear"
restart_command = "/restart"


try:
    logging.info("Indexing all documents from Blob Storage (if not already indexed)...")
    index_all_blobs_stream()
    logging.info("Blob indexing completed.")
except Exception as e:
    logging.error(f"Blob indexing failed at startup: {str(e)}")

@app.route(route="chat", methods=["POST"])
def chat(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        input_type = req_body.get("input_type", "text")  
        message = req_body.get("message", "").strip()
        audio_base64 = req_body.get("audio_base64")
        session_id = req_body.get("session_id")

 
        if not session_id:
            session_id = create_session()


        user_text = None

        if input_type == "speech" and audio_base64:
            try:
                audio_bytes = base64.b64decode(audio_base64)
                user_text = listen(audio_bytes)
                logging.info(f"Recognized speech: {user_text}")
            except Exception as e:
                logging.warning(f"STT failed: {str(e)}")
                return func.HttpResponse(
                    json.dumps({"error": "Could not process audio.", "session_id": session_id}),
                    status_code=400,
                    mimetype="application/json"
                )
        elif input_type == "text" and message:
            user_text = message
        else:
            return func.HttpResponse(
                json.dumps({"error": "Please provide a valid message or audio.", "session_id": session_id}),
                status_code=400,
                mimetype="application/json"
            )


        user_lower = user_text.lower()
        if user_lower in exit_keywords:
            clear_session(session_id)
            return func.HttpResponse(
                json.dumps({"reply": "Chatbot: Goodbye!", "session_id": session_id}),
                status_code=200,
                mimetype="application/json"
            )
        elif user_lower == history_command:
            session = get_session(session_id)
            conversation = [
                f"{msg['role'].capitalize()}: {msg['content']}"
                for msg in session.get("history", [])
                if msg["role"] != "system"
            ]
            return func.HttpResponse(
                json.dumps({"reply": "\n".join(conversation), "session_id": session_id}),
                status_code=200,
                mimetype="application/json"
            )
        elif user_lower == clear_command:
            clear_session(session_id)
            return func.HttpResponse(
                json.dumps({"reply": "Chatbot: Conversation cleared.", "session_id": session_id}),
                status_code=200,
                mimetype="application/json"
            )
        elif user_lower == restart_command:
            session_id = create_session()
            return func.HttpResponse(
                json.dumps({"reply": "Chatbot: Session restarted.", "session_id": session_id}),
                status_code=200,
                mimetype="application/json"
            )


        rag_response = generate_response_with_context(user_text)
        ai_reply = rag_response["answer"]
        references = rag_response.get("references", [])

        # Update session history
        update_session(session_id, user_text, ai_reply)


        audio_response_base64 = None
        try:
            audio_bytes = synthesize_text_to_audio(ai_reply)
            if audio_bytes:
                audio_response_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        except Exception as e:
            logging.warning(f"TTS failed: {str(e)}")


        return func.HttpResponse(
            json.dumps({
                "reply": ai_reply,
                "audio_base64": audio_response_base64,
                "references": references,
                "session_id": session_id
            }),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
