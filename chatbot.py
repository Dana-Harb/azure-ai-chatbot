from dotenv import load_dotenv
from session_store import create_session, get_session, update_session, clear_session
from rag_pipeline import generate_response_with_context 

load_dotenv()

session_id = create_session()
print(f"Session started: {session_id}\n")

exit_list = ["exit", "quit", "bye"]
history_command = "/history"
clear_command = "/clear"
restart_command = "/restart"

print("Welcome! I'm your barista assistant ☕. Type 'exit' to quit.\n")

while True:
    try:
        user_input = input("You: ").strip()
        if user_input.lower() in exit_list:
            print("Chatbot: Goodbye! Enjoy your coffee!")
            break

        if user_input.lower() == history_command:
            session = get_session(session_id)
            for msg in session.get("history", []):
                if msg["role"] != "system":
                    print(f"{msg['role'].capitalize()}: {msg['content']}\n")
            continue
        elif user_input.lower() == clear_command:
            clear_session(session_id)
            print("Chatbot: Conversation cleared.\n")
            continue
        elif user_input.lower() == restart_command:
            session_id = create_session()
            print(f"Chatbot: Session restarted. New session: {session_id}\n")
            continue

       
        rag_response = generate_response_with_context(user_input)
        ai_reply = rag_response["answer"]
        refs = rag_response["references"]

       
        if refs:
            print(f"Chatbot: {ai_reply}\n(References: {refs})\n")
        else:
            print(f"Chatbot: {ai_reply}\n")

        
        update_session(session_id, user_input, ai_reply)

    except Exception as e:
        print(f"Error: {str(e)}\n")
