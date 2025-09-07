import azure.functions as func
import os
import json
import logging
from session_store import create_session, get_session, update_session, clear_session
from rag_pipeline import generate_response_with_context 

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

exit_keywords = ["exit", "quit", "bye"]
history_command = "/history"
clear_command = "/clear"
restart_command = "/restart"

@app.route(route="chat", methods=["POST"])
def chat(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        user_input = req_body.get("message", "").strip()
        session_id = req_body.get("session_id")

        if not user_input:
            return func.HttpResponse(
                json.dumps({"reply": "Please provide a message."}),
                status_code=400,
                mimetype="application/json"
            )

        if not session_id:
            session_id = create_session()

        # Handle exit/commands
        if user_input.lower() in exit_keywords:
            clear_session(session_id)
            return func.HttpResponse(
                json.dumps({"reply": "Chatbot: Goodbye!", "session_id": session_id}),
                status_code=200,
                mimetype="application/json"
            )
        elif user_input.lower() == history_command:
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
        elif user_input.lower() == clear_command:
            clear_session(session_id)
            return func.HttpResponse(
                json.dumps({"reply": "Chatbot: Conversation cleared.", "session_id": session_id}),
                status_code=200,
                mimetype="application/json"
            )
        elif user_input.lower() == restart_command:
            session_id = create_session()
            return func.HttpResponse(
                json.dumps({"reply": f"Chatbot: Session restarted.", "session_id": session_id}),
                status_code=200,
                mimetype="application/json"
            )


        rag_response = generate_response_with_context(user_input)
        ai_reply = rag_response["answer"]
        references = rag_response.get("references", [])

       
        update_session(session_id, user_input, ai_reply)

        
        return func.HttpResponse(
            json.dumps({"reply": ai_reply, "references": references, "session_id": session_id}),
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
