import os
from openai import AzureOpenAI
from dotenv import load_dotenv
from session_store import create_session, get_session, update_session, clear_session

load_dotenv()

endpoint = os.getenv("ENDPOINT_URL")
deployment = os.getenv("DEPLOYMENT_NAME")
subscription_key = os.getenv("AZURE_OPENAI_API_KEY")

client = AzureOpenAI(
    azure_endpoint=endpoint,
    api_key=subscription_key,
    api_version="2025-01-01-preview"
)

exit_list = ["exit", "quit", "bye"]
history_command = "/history"
clear_command = "/clear"
restart_command = "/restart"

print("Welcome! I'm your AI assistant. Type 'exit' to quit.\n")


session_id = create_session()

while True:
    try:
        user_input = input("You: ").strip()
        lower_input = user_input.lower()


        if lower_input in exit_list:
            clear_session(session_id)
            print("Chatbot: Goodbye! Have a great day!")
            break


        elif lower_input == history_command:
            session = get_session(session_id)
            conversation = [
                f"{msg['role'].capitalize()}: {msg['content']}"
                for msg in session.get("history", [])
                if msg["role"] != "system"
            ]
            print("\n".join(conversation) + "\n")
            continue


        elif lower_input == clear_command:
            clear_session(session_id)
            print("Chatbot: Conversation cleared.\n")
            continue

        # Handle /restart        elif lower_input == restart_command:
            session_id = create_session()
            print("Chatbot: Session restarted.\n")
            continue


        session = get_session(session_id)
        history = session.get("history", [])


        messages_to_send = history + [{"role": "user", "content": user_input}]

        completion = client.chat.completions.create(
            model=deployment,
            messages=messages_to_send,
            max_tokens=500,
            temperature=0.7
        )

        ai_reply = completion.choices[0].message.content.strip()

   
        update_session(session_id, user_input, ai_reply, client_openai=client, deployment=deployment)

        print(f"Chatbot: {ai_reply}\n")

    except Exception as e:
        print(f"Error: {str(e)}\n")
