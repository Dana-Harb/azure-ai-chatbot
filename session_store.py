import os
import uuid
import bcrypt
from datetime import datetime
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
    "You are an expert barista with deep knowledge of coffee, brewing methods, beans, and recipes. "
        "You have access to reference documents which may contain information relevant to the user's query. "
        "Your goal is to provide the best answer possible: "
        "- If the documents contain relevant information, use it. "
        "- Supplement with your own knowledge if it adds value. "
        "- Cite sources used, either from the documents or external knowledge. "
        "- Provide references if the information comes from the documents. "
        "- Provide a link to you knowlede if a relaible resource is available"
        "- Answer in the same language as the query (Arabic or English). "
        "- Do not fabricate references."
)

# Initialize default users
def get_user_by_username(username: str):
    """Get user by username"""
    query = f"SELECT * FROM c WHERE c.username = '{username}' AND c.type = 'user'"
    users = list(container.query_items(query, enable_cross_partition_query=True))
    return users[0] if users else None

def initialize_default_users():
    """Create default admin and client users if they don't exist"""
    try:
        # Check if admin exists
        admin_query = "SELECT * FROM c WHERE c.username = 'admin' AND c.type = 'user'"
        admin_exists = list(container.query_items(admin_query, enable_cross_partition_query=True))
        
        if not admin_exists:
            create_user("admin", "admin123", "admin")
            print("Created default admin user")
        
        # Check if client exists
        client_query = "SELECT * FROM c WHERE c.username = 'client' AND c.type = 'user'"
        client_exists = list(container.query_items(client_query, enable_cross_partition_query=True))
        
        if not client_exists:
            create_user("client", "client123", "client")
            print("Created default client user")
            
    except Exception as e:
        print(f"Error initializing users: {e}")

# User management functions
def create_user(username: str, password: str, role: str):
    """Create a new user with hashed password"""
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    user_data = {
        "id": str(uuid.uuid4()),
        "username": username,
        "password": hashed_password,
        "role": role,
        "type": "user",
        "created_at": datetime.utcnow().isoformat()
    }
    
    container.upsert_item(user_data)
    return user_data

def authenticate_user(username: str, password: str):
    """Authenticate user credentials"""
    query = f"SELECT * FROM c WHERE c.username = '{username}' AND c.type = 'user'"
    users = list(container.query_items(query, enable_cross_partition_query=True))
    
    if not users:
        return None
    
    user = users[0]
    if bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
        # Return user data without password
        return {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "created_at": user.get("created_at")
        }
    
    return None

def get_user_sessions(user_id: str):
    """Get all sessions for a specific user"""
    query = f"SELECT * FROM c WHERE c.user_id = '{user_id}' AND (c.type != 'user' OR NOT IS_DEFINED(c.type))"
    sessions = list(container.query_items(query, enable_cross_partition_query=True))
    return sessions

def get_latest_user_session(user_id: str):
    """Get the most recent session for a user"""
    query = f"SELECT TOP 1 * FROM c WHERE c.user_id = '{user_id}' AND (c.type != 'user' OR NOT IS_DEFINED(c.type)) ORDER BY c._ts DESC"
    sessions = list(container.query_items(query, enable_cross_partition_query=True))
    return sessions[0] if sessions else None

# Enhanced session functions with user association
def create_session(system_prompt=None, user_id=None):
    """Create a new session, optionally associated with a user"""
    session_id = str(uuid.uuid4())
    if not system_prompt:
        system_prompt = DEFAULT_SYSTEM_PROMPT
    
    session_data = {
        "id": session_id,
        "session_id": session_id,
        "history": [{"role": "system", "content": system_prompt}],
        "system_prompt": system_prompt,
        "summary": "",
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Associate with user if provided
    if user_id:
        session_data["user_id"] = user_id
    
    container.upsert_item(session_data)
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

def update_session(session_id, user_message, bot_response, user_id=None, client_openai=None, deployment=None):
    session = get_session(session_id)
    history = session.get("history", [])
    summary = session.get("summary", "")
    
    # Add user_id to session if provided and not already set
    if user_id and "user_id" not in session:
        session["user_id"] = user_id

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

# Initialize default users when this module is imported
initialize_default_users()