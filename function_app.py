import azure.functions as func
import os
import json
import logging
from openai import AzureOpenAI

# Initialize Function App
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# Load environment variables
endpoint = os.environ["ENDPOINT_URL"]
deployment = os.environ["DEPLOYMENT_NAME"]
api_key = os.environ["AZURE_OPENAI_API_KEY"]

# Initialize Azure OpenAI client
client = AzureOpenAI(
    azure_endpoint=endpoint,
    api_key=api_key,
    api_version="2025-01-01-preview",
)

# In-memory conversation history
conversation_history = []
exit_keywords = ["exit", "quit", "bye"]

@app.route(route="chat", methods=["POST"])
def chat(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        user_input = req_body.get("message", "").strip()

        if not user_input:
            return func.HttpResponse(
                json.dumps({"reply": "Please provide a message."}),
                status_code=400,
                mimetype="application/json"
            )

        # Exit keywords reset conversation
        if user_input.lower() in exit_keywords:
            conversation_history.clear()
            return func.HttpResponse(
                json.dumps({"reply": "Chatbot: Goodbye!"}),
                status_code=200,
                mimetype="application/json"
            )

        # Append user message
        conversation_history.append({"role": "user", "content": user_input})

        # Build messages
        messages = [{"role": "system", "content": "You are a helpful AI assistant."}]
        messages.extend(conversation_history)

        # Call Azure OpenAI
        completion = client.chat.completions.create(
            model=deployment,
            messages=messages,
            max_tokens=500,
            temperature=0.7
        )

        ai_reply = completion.choices[0].message.content.strip()
        conversation_history.append({"role": "assistant", "content": ai_reply})

        return func.HttpResponse(
            json.dumps({"reply": ai_reply}),
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
