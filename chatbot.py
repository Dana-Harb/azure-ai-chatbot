# chatbot.py
from dotenv import load_dotenv
from session_store import create_session, get_session, update_session, clear_session
from rag_pipeline import index_all_blobs_stream, generate_response_with_context
from speech_interface import listen, speak

load_dotenv()


print("Indexing all documents from Blob Storage (if not already indexed)...")
index_all_blobs_stream()
print("Indexing completed.\n")


session_id = create_session()
print(f"Session started: {session_id}\n")

exit_list = ["exit", "quit", "bye"]
history_command = "/history"
clear_command = "/clear"
restart_command = "/restart"

print("Welcome! I'm your barista assistant ☕. Type 'exit' to quit.\n")


def get_user_input():
    """
    Per-turn input selection: user chooses text or speech input.
    """
    while True:
        mode = input("Input method for this turn (text/speech): ").strip().lower()
        if mode == "speech":
            text = listen()
            if text:
                print(f"You said: {text}")
                return text
            else:
                print("[Speech] Could not recognize, try again.")
        elif mode == "text":
            text = input("You: ").strip()
            if text:
                return text
        else:
            print("Invalid option. Please type 'text' or 'speech'.")

def output_bot_response(response):
    """
    Outputs bot response in both text and speech.
    """
    print(f"Chatbot: {response}")
    speak(response)


while True:
    try:
        user_input = get_user_input()
        if not user_input:
            continue


        if user_input.lower() in exit_list:
            output_bot_response("Goodbye! Enjoy your coffee!")
            break

        elif user_input.lower() == history_command:
            session = get_session(session_id)
            for msg in session.get("history", []):
                if msg["role"] != "system":
                    print(f"{msg['role'].capitalize()}: {msg['content']}\n")
            continue

        elif user_input.lower() == clear_command:
            clear_session(session_id)
            output_bot_response("Conversation cleared.\n")
            continue

        elif user_input.lower() == restart_command:
            session_id = create_session()
            output_bot_response(f"Session restarted. New session: {session_id}\n")
            continue


        rag_response = generate_response_with_context(user_input)
        ai_reply = rag_response["answer"]
        refs = rag_response.get("references", [])

        if refs:
            output_bot_response(f"{ai_reply}\n(References: {refs})\n")
        else:
            output_bot_response(ai_reply)


        update_session(session_id, user_input, ai_reply)

    except Exception as e:
        print(f"Error: {str(e)}\n")
