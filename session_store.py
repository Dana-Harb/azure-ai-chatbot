
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
SUMMARY_TRIGGER = 20       
DEFAULT_SYSTEM_PROMPT = "You are an AI assistant that helps people find information."


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
    if len(messages) < SUMMARY_TRIGGER or not client_openai or not deployment:
        return messages, ""

    old_messages = messages[:-len(messages)//2]
    recent_messages = messages[-len(messages)//2:]

    summary_prompt = [
        {"role": "system", "content": "Summarize the following conversation keeping important details."},
        *old_messages
    ]

    completion = client_openai.chat.completions.create(
        model=deployment,
        messages=summary_prompt,
        max_tokens=500,
        temperature=0.7
    )

    summary_text = completion.choices[0].message.content.strip()
    summarized_messages = [{"role": "system", "content": summary_text}]
    summarized_messages.extend(recent_messages)
    return summarized_messages, summary_text

def update_session(session_id, user_message, bot_response, client_openai=None, deployment=None):
    session = get_session(session_id)
    history = session.get("history", [])
    summary = session.get("summary", "")

    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": bot_response})

   
    if client_openai and deployment and count_tokens(history) > MAX_TOKENS:
        history, summary_text = summarize_messages(history, client_openai, deployment)
        summary = (summary + "\n" + summary_text).strip()

    session["history"] = history
    session["summary"] = summary
    container.upsert_item(session)
    return history
