import os
from openai import AzureOpenAI
from dotenv import load_dotenv


load_dotenv()

endpoint = os.getenv("ENDPOINT_URL")
deployment = os.getenv("DEPLOYMENT_NAME")
subscription_key = os.getenv("AZURE_OPENAI_API_KEY")

client = AzureOpenAI(
    azure_endpoint=endpoint,
    api_key=subscription_key,
    api_version="2025-01-01-preview"
)

messages = [{"role": "system", "content": "You are an AI assistant that helps people find information."}]

print("Welcome! I'm your AI assistant. Type 'exit' to quit.\n")


exit_list = ["exit", "quit", "bye"]

while True:
    try:
        user_input = input("You: ").strip().lower() 
        if user_input in exit_list:
            print("Chatbot: Goodbye! Have a great day!")
            break

        messages.append({"role": "user", "content": user_input})

        completion = client.chat.completions.create(
            model=deployment,
            messages=messages,
            max_tokens=500,
            temperature=0.7
        )

        ai_reply = completion.choices[0].message.content.strip()
        messages.append({"role": "assistant", "content": ai_reply})

        print(f"Chatbot: {ai_reply}\n")

    except Exception as e:
        print(f"Error: {str(e)}\n")

