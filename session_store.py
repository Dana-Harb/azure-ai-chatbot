import os
import uuid
from dotenv import load_dotenv
from azure.cosmos import CosmosClient
import tiktoken


load_dotenv() 
COSMOS_URI = os.getenv("COSMOS_URI")
COSMOS_KEY = os.getenv("COSMOS_KEY")
COSMOS_DB_NAME = os.getenv("COSMOS_DB_NAME")
COSMOS_CONTAINER_NAME = os.getenv("COSMOS_CONTAINER_NAME")


client = CosmosClient(url=COSMOS_URI, credential=COSMOS_KEY)
database = client.get_database_client(COSMOS_DB_NAME)
container = database.get_container_client(COSMOS_CONTAINER_NAME)


MAX_TOKENS = 2000          
SUMMARY_TRIGGER = 10 
DEFAULT_SYSTEM_PROMPT = (
    "You are an expert barista with deep knowledge of coffee. "
    "Answer questions related to coffee, brewing, beans, or recipes. "
    "If the question is unrelated to coffee, politely decline to answer."
)


def create_session(system_prompt=None):
    session_id = str(uuid.uuid4())
    if not system_prompt:
        system_prompt = DEFAULT_SYSTEM_PROMPT
    container.upsert_item({
        "id": session_id,
        "session_id": session_id,
        "history": [{"role": "system", "content": system_prompt}],
        "system_prompt": system_prompt,
        "summary": ""
    })
    return session_id

def get_session(session_id):
    try:
        item = container.read_item(item=session_id, partition_key=session_id)
        if "system_prompt" not in item:
            item["system_prompt"] = DEFAULT_SYSTEM_PROMPT
        return item
    except:
        return {
            "id": session_id,
            "session_id": session_id,
            "history": [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}],
            "system_prompt": DEFAULT_SYSTEM_PROMPT,
            "summary": ""
        }
    
def clear_session(session_id):
    session = get_session(session_id)
    session["history"] = [{"role": "system", "content": session.get("system_prompt", DEFAULT_SYSTEM_PROMPT)}]
    session["summary"] = ""
    container.upsert_item(session)

def count_tokens(messages):
    encoding = tiktoken.encoding_for_model("gpt-4o")
    text = "".join([msg["content"] for msg in messages])
    return len(encoding.encode(text))

def summarize_messages(messages, client_openai=None, deployment=None):
    if not client_openai or not deployment or len(messages) < SUMMARY_TRIGGER:
        return messages, ""

    
    system_prompt = messages[0] if messages and messages[0]["role"] == "system" else {"role": "system", "content": DEFAULT_SYSTEM_PROMPT}

    
    half_index = (len(messages) - 1) // 2
    old_messages = messages[1:1+half_index]   
    recent_messages = messages[1+half_index:] 

    
    summary_prompt = [
        {"role": "system", "content": "Summarize the following conversation keeping important details."},
        *old_messages
    ]

    try:
        completion = client_openai.chat.completions.create(
            model=deployment,
            messages=summary_prompt,
            max_tokens=500,
            temperature=0.7
        )
        summary_text = completion.choices[0].message.content.strip()
    except Exception as e:
        print("Error generating summary:", e)
        summary_text = ""

    
    summarized_messages = [system_prompt]  

    if summary_text:
        summarized_messages.append(
            {"role": "assistant", "content": f"(Summary of earlier conversation: {summary_text})"}
        )

    summarized_messages.extend(recent_messages)

    return summarized_messages, summary_text



def update_session(session_id, user_message, bot_response, client_openai=None, deployment=None):
    session = get_session(session_id)
    history = session.get("history", [])
    summary = session.get("summary", "")

    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": bot_response})

   
    if client_openai and deployment and len(history) >= SUMMARY_TRIGGER:
        history, summary_text = summarize_messages(history, client_openai, deployment)
        if summary_text:
            summary = (summary + "\n" + summary_text).strip()
        print("Summary triggered. Generated summary:", summary_text)

    session["history"] = history
    session["summary"] = summary
    container.upsert_item(session)
    return history
