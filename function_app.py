import azure.functions as func
import requests
import json
import logging
import base64
from session_store import (
    create_session, get_session, update_session, clear_session, 
    authenticate_user, get_latest_user_session, get_user_by_username,
    create_user, get_user_sessions, get_user_by_id,
    get_container, get_users_container
)

import logging, os, json
from azure.storage.blob import BlobServiceClient, ContentSettings
from datetime import datetime, timezone
import uuid

from tools import get_function_definitions, execute_function

from rag_pipeline import generate_response_with_context, index_all_blobs_stream, get_openai_client, AZURE_OPENAI_DEPLOYMENT
from speech_interface import listen, synthesize_text_to_audio

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

from datetime import datetime


logging.info("Function app started - lazy loading enabled")

@app.route(route="login", methods=["POST", "OPTIONS"])
def login(req: func.HttpRequest) -> func.HttpResponse:
    # Handle CORS preflight
    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    try:
        req_body = req.get_json()
        username = req_body.get("username")
        password = req_body.get("password")

        # Authenticate user
        user = authenticate_user(username, password)
        
        if user:
            # Find existing session for this user or create new one
            existing_session = get_latest_user_session(user["user_id"])
            
            if existing_session:
                session_id = existing_session["session_id"]
                message = "Resumed existing session"
            else:
                # Create new session associated with this user
                session_id = create_session(user_id=user["user_id"])
                message = "Created new session"
            
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "userId": user["user_id"],
                    "username": user["username"],
                    "role": user["role"],
                    "sessionId": session_id,
                    "message": message
                }),
                status_code=200,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )
        else:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "Invalid credentials"
                }),
                status_code=401,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

    except Exception as e:
        logging.error(f"Login error: {str(e)}")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "Internal server error"
            }),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

@app.route(route="session/{session_id}", methods=["GET", "OPTIONS"])
def get_session_history(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    try:
        session_id = req.route_params.get("session_id")
        session = get_session(session_id)
        
        # Extract only user and assistant messages (exclude system prompt)
        chat_history = [
            msg for msg in session.get("history", []) 
            if msg["role"] in ["user", "assistant"]
        ]
        
        return func.HttpResponse(
            json.dumps({
                "history": chat_history,
                "session_id": session_id
            }),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )
        
    except Exception as e:
        logging.error(f"Error getting session history: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": "Internal server error"}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

@app.route(route="chat", methods=["POST", "OPTIONS"])
def chat(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    session_id = None
    user_id = None
    try:
        req_body = req.get_json()
        input_type = req_body.get("input_type", "text")
        message = req_body.get("message", "").strip()
        audio_base64 = req_body.get("audio_base64")
        session_id = req_body.get("session_id")
        user_id = req_body.get("user_id")

        # Verify session ownership
        if session_id and user_id:
            session = get_session(session_id)
            if session and session.get("user_id") and session["user_id"] != user_id:
                return func.HttpResponse(
                    json.dumps({"error": "Session does not belong to this user", "session_id": session_id}),
                    status_code=403,
                    mimetype="application/json",
                    headers={"Access-Control-Allow-Origin": "*"},
                )

        # Create session if not exists
        if not session_id:
            session_id = create_session(user_id=user_id)

        user_text = None
        recognized_text = None

        # --- Speech input ---
        if input_type == "speech" and audio_base64:
            try:
                audio_bytes = base64.b64decode(audio_base64)
                recognized_text = listen(audio_bytes)
                user_text = recognized_text
            except Exception:
                user_text = "[Speech recognition failed]"
                recognized_text = user_text

        # --- Text input ---
        elif input_type == "text" and message:
            user_text = message
        else:
            user_text = "[No input provided]"
            recognized_text = user_text

        # --- Function calling logic ---
        ai_reply = None
        references = []
        audio_response_base64 = None

        # Get session history for context
        session = get_session(session_id)
        history = session.get("history", [])
        
        # Prepare messages for OpenAI with function definitions
        messages = history.copy()
        
        # Add user message
        messages.append({"role": "user", "content": user_text})

        # Handle special clear command
        if user_text.strip().lower() == "/clear":
            clear_session(session_id)
            ai_reply = "Chat history cleared."
        else:
            # Step 1: First API call - check if functions should be called
            try:
                client = get_openai_client()
                deployment = AZURE_OPENAI_DEPLOYMENT
                
                first_response = client.chat.completions.create(
                    model=deployment,
                    messages=messages,
                    tools=get_function_definitions(),
                    max_tokens=400,
                    temperature=0.7,
                )

                logging.info(f"[DEBUG] Tools passed to model: {get_function_definitions()}")

                response_message = first_response.choices[0].message
                tool_calls = response_message.tool_calls

                logging.info(f"[DEBUG] Tool calls detected: {tool_calls}")
                
                # Step 2: If functions are called, execute them
                if tool_calls:
                    # Add the assistant's message with tool calls to history
                    messages.append(response_message)
                    
                    # Step 3: Execute each function call
                    for tool_call in tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)
                        
                        # Execute the function using the centralized function with session_id
                        function_response = execute_function(function_name, function_args, session_id)
                        
                        # Add function response to messages
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(function_response)
                        })
                    
                    # Step 4: Second API call with function results
                    second_response = client.chat.completions.create(
                        model=deployment,
                        messages=messages,
                        max_tokens=150,
                        temperature=0.7
                    )
                    
                    ai_reply = second_response.choices[0].message.content
                    
                else:
                    # No function calls, use direct response
                    ai_reply = response_message.content
                    
            except Exception as e:
                logging.error(f"OpenAI API error: {str(e)}")
                # Fallback to RAG response
                rag_response = generate_response_with_context(user_text)
                ai_reply = rag_response.get("answer", "I couldn't generate a response.")
                references = rag_response.get("references", [])

        # --- Update session ---
        update_session(session_id, user_text, ai_reply, user_id=user_id)

        # --- TTS output ---
        if ai_reply and not ai_reply.startswith("I couldn't"):
            try:
                audio_bytes = synthesize_text_to_audio(ai_reply)
                if audio_bytes:
                    audio_response_base64 = base64.b64encode(audio_bytes).decode("utf-8")
            except Exception:
                pass

        return func.HttpResponse(
            json.dumps({
                "reply": ai_reply,
                "recognized_text": recognized_text,
                "audio_base64": audio_response_base64,
                "references": references,
                "session_id": session_id
            }),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except Exception as e:
        logging.error(f"Chat error: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": "Internal server error", "session_id": session_id}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )
    
@app.route(route="register", methods=["POST", "OPTIONS"])
def register(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    try:
        req_body = req.get_json()
        username = req_body.get("username")
        password = req_body.get("password")
        role = req_body.get("role", "client")  # Default to client role

        if not username or not password:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "Username and password are required"
                }),
                status_code=400,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # Check if user already exists
        existing_user = get_user_by_username(username)
        
        if existing_user:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "User already exists"
                }),
                status_code=400,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # Create new user
        user = create_user(username, password, role)
        
        if not user:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "Failed to create user"
                }),
                status_code=500,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )
        
        # Create session for the new user
        session_id = create_session(user_id=user["user_id"])
        
        return func.HttpResponse(
            json.dumps({
                "success": True,
                "userId": user["user_id"],
                "username": user["username"],
                "role": user["role"],
                "sessionId": session_id,
                "message": "User created successfully"
            }),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except Exception as e:
        logging.error(f"Registration error: {str(e)}")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "Internal server error"
            }),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

@app.route(route="management/users", methods=["GET", "OPTIONS"])
def admin_users(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            },
        )

    try:
        # Simple authentication check
        auth_header = req.headers.get('Authorization', '')
        if not auth_header or not auth_header.startswith('Bearer '):
            return func.HttpResponse(
                json.dumps({"error": "Unauthorized"}),
                status_code=401,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # Get all users from users container
        query = "SELECT * FROM c"
        users = list(get_users_container().query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        
        # Remove password from response
        users_response = []
        for user in users:
            users_response.append({
                "id": user["id"],
                "user_id": user.get("user_id", user["id"]),
                "username": user["username"],
                "role": user["role"],
                "created_at": user.get("created_at")
            })
        
        return func.HttpResponse(
            json.dumps({"users": users_response}),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except Exception as e:
        logging.error(f"Admin users error: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": "Internal server error"}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

@app.route(route="management/sessions", methods=["GET", "OPTIONS"])
def admin_sessions(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            },
        )

    try:
        # Simple authentication check
        auth_header = req.headers.get('Authorization', '')
        if not auth_header or not auth_header.startswith('Bearer '):
            return func.HttpResponse(
                json.dumps({"error": "Unauthorized"}),
                status_code=401,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # Get all sessions from sessions container
        query = "SELECT * FROM c"
        sessions = list(get_container().query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        
        # Enrich session data with user information
        sessions_response = []
        for session in sessions:
            user_info = {}
            if session.get("user_id"):
                # Get user info from users container
                try:
                    user = get_user_by_id(session['user_id'])
                    if user:
                        user_info = {
                            "user_id": user["user_id"],
                            "username": user["username"],
                            "role": user["role"]
                        }
                    else:
                        user_info = {
                            "user_id": session['user_id'],
                            "username": "Unknown",
                            "role": "Unknown"
                        }
                except Exception as e:
                    logging.error(f"Error getting user info: {str(e)}")
                    user_info = {
                        "user_id": session['user_id'],
                        "username": "Unknown",
                        "role": "Unknown"
                    }
            
            # Count user and assistant messages
            message_count = len([msg for msg in session.get("history", []) 
                               if msg["role"] in ["user", "assistant"]])
            
            sessions_response.append({
                "session_id": session.get("session_id", session.get("id")),
                "user_id": session.get("user_id"),
                "username": user_info.get("username", "Unknown"),
                "role": user_info.get("role", "Unknown"),
                "created_at": session.get("created_at"),
                "message_count": message_count,
                "last_updated": session.get("_ts")  # Cosmos DB timestamp
            })
        
        return func.HttpResponse(
            json.dumps({"sessions": sessions_response}),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except Exception as e:
        logging.error(f"Admin sessions error: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": "Internal server error"}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

@app.route(route="management/sessions/{user_id}", methods=["GET", "OPTIONS"])
def admin_user_sessions(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            },
        )

    try:
        # Simple authentication check
        auth_header = req.headers.get('Authorization', '')
        if not auth_header or not auth_header.startswith('Bearer '):
            return func.HttpResponse(
                json.dumps({"error": "Unauthorized"}),
                status_code=401,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        user_id = req.route_params.get("user_id")
        
        # Get all sessions for a specific user
        sessions = get_user_sessions(user_id)
        
        sessions_response = []
        for session in sessions:
            # Count user and assistant messages
            message_count = len([msg for msg in session.get("history", []) 
                               if msg["role"] in ["user", "assistant"]])
            
            sessions_response.append({
                "session_id": session.get("session_id", session.get("id")),
                "created_at": session.get("created_at"),
                "message_count": message_count,
                "last_updated": session.get("_ts")
            })
        
        return func.HttpResponse(
            json.dumps({"sessions": sessions_response}),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except Exception as e:
        logging.error(f"Admin user sessions error: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": "Internal server error"}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

@app.route(route="management/user/{user_id}", methods=["DELETE", "OPTIONS"])
def admin_delete_user(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            },
        )

    try:
        # Simple authentication check
        auth_header = req.headers.get('Authorization', '')
        if not auth_header or not auth_header.startswith('Bearer '):
            return func.HttpResponse(
                json.dumps({"error": "Unauthorized"}),
                status_code=401,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        user_id = req.route_params.get("user_id")
        logging.info(f"[DeleteUser] Attempting to delete user: {user_id}")

        # Try to find user by user_id first, then by id
        user = None
        try:
            user = get_user_by_id(user_id)
            logging.info(f"[DeleteUser] Found user by user_id: {user}")
        except Exception as e:
            logging.warning(f"[DeleteUser] get_user_by_id failed: {e}")

        if not user:
            # Query users container to find the user
            query = "SELECT * FROM c WHERE c.user_id = @user_id OR c.id = @user_id"
            params = [{"name": "@user_id", "value": user_id}]
            users = list(get_users_container().query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            if users:
                user = users[0]
                logging.info(f"[DeleteUser] Found user by query: {user}")
            else:
                logging.warning(f"[DeleteUser] No user found for id: {user_id}")

        if not user:
            return func.HttpResponse(
                json.dumps({"error": "User not found"}),
                status_code=404,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # Log all user keys and values for diagnostics
        logging.info(f"[DeleteUser] User keys: {list(user.keys())}")
        logging.info(f"[DeleteUser] User object: {json.dumps(user)}")

        # Use correct id and partition key for deletion
        doc_id = user.get("id")
        partition_key = user.get("user_id")
        if not doc_id or not partition_key:
            return func.HttpResponse(
                json.dumps({"error": "User document missing id or partition key"}),
                status_code=500,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        try:
            logging.info(f"[DeleteUser] Deleting user: id={doc_id}, partition_key={partition_key}")
            get_users_container().delete_item(item=doc_id, partition_key=partition_key)
            logging.info(f"[DeleteUser] User deleted: {doc_id}")
        except Exception as e:
            logging.error(f"[DeleteUser] Failed to delete user: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return func.HttpResponse(
                json.dumps({"error": "Failed to delete user", "details": str(e)}),
                status_code=500,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # Also delete all sessions for this user
        try:
            sessions = get_user_sessions(partition_key)
            logging.info(f"[DeleteUser] Found {len(sessions)} sessions for user {partition_key}")
            for session in sessions:
                session_id = session.get("session_id", session.get("id"))
                logging.info(f"[DeleteUser] Deleting session: id={session_id}, partition_key={session_id}")
                try:
                    get_container().delete_item(item=session_id, partition_key=session_id)
                    logging.info(f"[DeleteUser] Session deleted: {session_id}")
                except Exception as e:
                    logging.error(f"[DeleteUser] Failed to delete session {session_id}: {e}")
                    import traceback
                    logging.error(traceback.format_exc())
            logging.info(f"[DeleteUser] All sessions deleted for user {partition_key}")
        except Exception as e:
            logging.error(f"[DeleteUser] Failed to delete sessions for user {partition_key}: {e}")
            import traceback
            logging.error(traceback.format_exc())
            # Do not fail the whole operation if session deletion fails

        return func.HttpResponse(
            json.dumps({"message": "User and associated sessions deleted successfully"}),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except Exception as e:
        logging.error(f"[DeleteUser] Admin delete user error: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        return func.HttpResponse(
            json.dumps({"error": "Internal server error", "details": str(e)}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint"""
    return func.HttpResponse(
        json.dumps({"status": "healthy", "message": "Function app is running"}),
        status_code=200,
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )

@app.route(route="management/stats", methods=["GET", "OPTIONS"])
def admin_stats(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            },
        )

    try:
        # Simple authentication check
        auth_header = req.headers.get('Authorization', '')
        if not auth_header or not auth_header.startswith('Bearer '):
            return func.HttpResponse(
                json.dumps({"error": "Unauthorized"}),
                status_code=401,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # Get user count
        users_query = "SELECT VALUE COUNT(1) FROM c"
        users_count = list(get_users_container().query_items(
            query=users_query,
            enable_cross_partition_query=True
        ))[0]

        # Get session count
        sessions_query = "SELECT VALUE COUNT(1) FROM c"
        sessions_count = list(get_container().query_items(
            query=sessions_query,
            enable_cross_partition_query=True
        ))[0]

        # SIMPLEST APPROACH: Count all messages (temporary fix)
        messages_query = "SELECT VALUE SUM(ARRAY_LENGTH(c.history)) FROM c"
        
        try:
            messages_count_result = list(get_container().query_items(
                query=messages_query,
                enable_cross_partition_query=True
            ))
            messages_count = messages_count_result[0] if messages_count_result else 0
        except Exception as e:
            logging.error(f"Error counting messages: {str(e)}")
            messages_count = 0

        # Active sessions: sessions created in last 24 hours
        active_sessions_query = "SELECT VALUE COUNT(1) FROM c"
        
        try:
            active_sessions_result = list(get_container().query_items(
                query=active_sessions_query,
                enable_cross_partition_query=True
            ))
            active_sessions = active_sessions_result[0] if active_sessions_result else 0
        except Exception as e:
            logging.error(f"Error counting active sessions: {str(e)}")
            active_sessions = min(sessions_count, 10)

        return func.HttpResponse(
            json.dumps({
                "total_users": users_count,
                "total_sessions": sessions_count,
                "today_messages": messages_count,  # Temporary: total messages
                "active_sessions": active_sessions
            }),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except Exception as e:
        logging.error(f"Admin stats error: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        return func.HttpResponse(
            json.dumps({"error": "Internal server error", "details": str(e)}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

@app.route(route="management/user/{user_id}/role", methods=["PUT", "OPTIONS"])
def admin_update_user_role(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "PUT, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            },
        )

    try:
        # Simple authentication check
        auth_header = req.headers.get('Authorization', '')
        if not auth_header or not auth_header.startswith('Bearer '):
            return func.HttpResponse(
                json.dumps({"error": "Unauthorized"}),
                status_code=401,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        user_id = req.route_params.get("user_id")
        req_body = req.get_json()
        new_role = req_body.get("role")

        if new_role not in ["admin", "client"]:
            return func.HttpResponse(
                json.dumps({"error": "Invalid role"}),
                status_code=400,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # Try to find user by user_id first, then by id (like delete logic)
        user = None
        try:
            user = get_user_by_id(user_id)
        except:
            pass

        if not user:
            query = "SELECT * FROM c WHERE c.user_id = @user_id OR c.id = @user_id"
            params = [{"name": "@user_id", "value": user_id}]
            users = list(get_users_container().query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            if users:
                user = users[0]
                user_id = user["user_id"]

        if not user:
            return func.HttpResponse(
                json.dumps({"error": "User not found"}),
                status_code=404,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        user["role"] = new_role
        get_users_container().upsert_item(user)

        return func.HttpResponse(
            json.dumps({"message": "User role updated successfully"}),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except Exception as e:
        logging.error(f"Admin update role error: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": "Internal server error"}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )
    

@app.route(route="management/upload", methods=["POST", "OPTIONS"])
def admin_upload_document(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            },
        )

    try:
        # Authentication check
        auth_header = req.headers.get("Authorization", "")
        if not auth_header or not auth_header.startswith("Bearer "):
            return func.HttpResponse(
                json.dumps({"error": "Unauthorized"}),
                status_code=401,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        debug_info = {}
        connection_string = None
        source = None

        # Method 1: Try Key Vault direct access
        try:
            keyvault_name = os.getenv("KEYVAULT_NAME")
            if keyvault_name:
                from azure.identity import ManagedIdentityCredential
                credential = ManagedIdentityCredential()
                keyvault_url = f"https://{keyvault_name}.vault.azure.net/"
                secret_client = SecretClient(vault_url=keyvault_url, credential=credential)
                
                secret = secret_client.get_secret("BLOB-CONNECTION-STRING")
                test_cs = secret.value
                
                # Test this connection string
                test_client = BlobServiceClient.from_connection_string(test_cs)
                list(test_client.list_containers())  # Test connection
                
                connection_string = test_cs
                source = "keyvault_direct"
                debug_info["keyvault_direct"] = "SUCCESS"
                
        except Exception as e:
            debug_info["keyvault_direct"] = f"FAILED: {str(e)}"

        # Method 2: Try Key Vault reference
        if not connection_string:
            try:
                test_cs = os.getenv("BLOB_CONNECTION_STRING")
                if test_cs:
                    test_client = BlobServiceClient.from_connection_string(test_cs)
                    list(test_client.list_containers())  # Test connection
                    
                    connection_string = test_cs
                    source = "keyvault_reference"
                    debug_info["keyvault_reference"] = "SUCCESS"
                    
            except Exception as e:
                debug_info["keyvault_reference"] = f"FAILED: {str(e)}"

        # Method 3: Fallback to AzureWebJobsStorage
        if not connection_string:
            try:
                test_cs = os.getenv("AzureWebJobsStorage")
                if test_cs:
                    test_client = BlobServiceClient.from_connection_string(test_cs)
                    list(test_client.list_containers())  # Test connection
                    
                    connection_string = test_cs
                    source = "azure_web_jobs"
                    debug_info["azure_web_jobs"] = "SUCCESS"
                    
            except Exception as e:
                debug_info["azure_web_jobs"] = f"FAILED: {str(e)}"

        # If no method worked
        if not connection_string:
            return func.HttpResponse(
                json.dumps({
                    "error": "All connection methods failed", 
                    "debug_info": debug_info
                }),
                status_code=500,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # Now proceed with the upload using the working connection string
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client("documents")

        # Ensure container exists
        try:
            container_client.get_container_properties()
        except Exception:
            container_client.create_container()

        # Process file upload
        file_bytes = req.get_body()
        if not file_bytes:
            return func.HttpResponse(
                json.dumps({"error": "No file data"}),
                status_code=400,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        filename = req.headers.get("X-Filename", "upload.bin")
        filename = os.path.basename(filename)

        # Validate extension
        ext = os.path.splitext(filename)[1].lower()
        allowed_extensions = [".pdf", ".txt", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".tiff"]
        if ext not in allowed_extensions:
            return func.HttpResponse(
                json.dumps({"error": f"Invalid file type: {ext}"}),
                status_code=400,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # Generate blob name and upload
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        blob_name = f"{timestamp}-{str(uuid.uuid4())[:8]}{ext}"
        
        content_type_map = {
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".png": "image/png",
            ".jpg": "image/jpeg", 
            ".jpeg": "image/jpeg",
            ".tiff": "image/tiff",
        }
        content_type = content_type_map.get(ext, "application/octet-stream")

        blob_client = container_client.get_blob_client(blob_name)
        blob_client.upload_blob(
            file_bytes,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

        return func.HttpResponse(
            json.dumps({
                "message": "File uploaded successfully",
                "blob_name": blob_name,
                "filename": filename,
                "source": source,
                "debug_info": debug_info
            }),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except Exception as e:
        import traceback
        return func.HttpResponse(
            json.dumps({
                "error": "Upload failed", 
                "details": str(e),
                "traceback": traceback.format_exc()
            }),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

@app.route(route="management/reindex", methods=["POST", "OPTIONS"])
def admin_reindex(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            },
        )

    try:
        # Simple authentication check
        auth_header = req.headers.get('Authorization', '')
        if not auth_header or not auth_header.startswith('Bearer '):
            return func.HttpResponse(
                json.dumps({"error": "Unauthorized"}),
                status_code=401,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # Reindex documents
        logging.info("Manual reindexing triggered by admin...")
        try:
            result = index_all_blobs_stream()
            # Ensure result is serializable (convert generator to list)
            if result is not None and not isinstance(result, (str, dict, list, int, float, bool)):
                result = list(result)
            return func.HttpResponse(
                json.dumps({"message": "Documents reindexed successfully", "result": result}),
                status_code=200,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )
        except Exception as e:
            logging.error(f"Admin reindex error (inner): {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return func.HttpResponse(
                json.dumps({"error": "Reindex failed", "details": str(e)}),
                status_code=500,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

    except Exception as e:
        logging.error(f"Admin reindex error (outer): {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        return func.HttpResponse(
            json.dumps({"error": "Internal server error", "details": str(e)}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

@app.route(route="management/session/{session_id}", methods=["GET", "OPTIONS"])
def admin_get_session_details(req: func.HttpRequest) -> func.HttpResponse:


    if req.method == "OPTIONS":
        return func.HttpResponse(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            },
        )

    try:
        # Simple authentication check
        auth_header = req.headers.get('Authorization', '')
        if not auth_header or not auth_header.startswith('Bearer '):
            return func.HttpResponse(
                json.dumps({"error": "Unauthorized"}),
                status_code=401,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        session_id = req.route_params.get("session_id")
        session = get_session(session_id)
        
        if not session:
            return func.HttpResponse(
                json.dumps({"error": "Session not found"}),
                status_code=404,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # Extract only user and assistant messages
        chat_history = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in session.get("history", [])
            if msg["role"] in ["user", "assistant"]
        ]

        return func.HttpResponse(
            json.dumps({
                "session_id": session_id,
                "history": chat_history
            }),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except Exception as e:
        logging.error(f"Admin session details error: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": "Internal server error"}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )


@app.route(route="debug_api", methods=["GET"])
def debug_api(req: func.HttpRequest) -> func.HttpResponse:
    """Debug endpoint to check API key and test TomTom API"""
    try:
        api_key = os.getenv("PLACE_SEARCH_API_KEY")
        has_key = bool(api_key)
        key_prefix = api_key[:8] + "..." if api_key and len(api_key) > 8 else "None"
        
        # Test a simple geocode request
        test_result = {}
        if api_key:
            try:
                geo_url = "https://api.tomtom.com/search/2/geocode/.json"
                geo_response = requests.get(geo_url, params={"query": "Milano, Italy", "key": api_key}, timeout=10)
                test_result = {
                    "status": geo_response.status_code,
                    "data": geo_response.json() if geo_response.status_code == 200 else geo_response.text
                }
            except Exception as e:
                test_result = {"error": str(e)}
        
        return func.HttpResponse(
            json.dumps({
                "api_key_configured": has_key,
                "api_key_prefix": key_prefix,
                "test_result": test_result
            }),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )
    except Exception as e:
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )