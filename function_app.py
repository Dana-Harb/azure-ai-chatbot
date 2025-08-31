import azure.functions as func
import os
import json
import logging
from openai import AzureOpenAI
from session_store import create_session, get_session, update_session, clear_session


app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


endpoint = os.environ["ENDPOINT_URL"]
deployment = os.environ["DEPLOYMENT_NAME"]
api_key = os.environ["AZURE_OPENAI_API_KEY"]


client = AzureOpenAI(
    azure_endpoint=endpoint,
    api_key=api_key,
    api_version="2025-01-01-preview",
)

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

        # Exit keywords reset conversation
        if user_input.lower() in exit_keywords:
            clear_session(session_id)
            return func.HttpResponse(
                json.dumps({"reply": "Chatbot: Goodbye!", "session_id": session_id}),
                status_code=200,
                mimetype="application/json"
            )

        
        if user_input.lower() == history_command:
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

        
        session = get_session(session_id)
        history = session.get("history", [])

        
        messages = history + [{"role": "user", "content": user_input}]

        
        completion = client.chat.completions.create(
            model=deployment,
            messages=messages,
            max_tokens=500,
            temperature=0.7
        )

        ai_reply = completion.choices[0].message.content.strip()

        
        update_session(session_id, user_input, ai_reply, client_openai=client, deployment=deployment)

        return func.HttpResponse(
            json.dumps({"reply": ai_reply, "session_id": session_id}),
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
