import azure.functions as func
import json
import logging
import base64
from session_store import (
    create_session, get_session, update_session, clear_session, 
    authenticate_user, get_latest_user_session, get_user_by_username,
    create_user, get_user_sessions, container
)
from rag_pipeline import generate_response_with_context, index_all_blobs_stream
from speech_interface import listen, synthesize_text_to_audio

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# Index documents at startup
try:
    logging.info("Indexing all documents from Blob Storage...")
    index_all_blobs_stream()
    logging.info("Blob indexing completed.")
except Exception as e:
    logging.error(f"Blob indexing failed at startup: {str(e)}")

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
            existing_session = get_latest_user_session(user["id"])
            
            if existing_session:
                session_id = existing_session["session_id"]
                message = "Resumed existing session"
            else:
                # Create new session associated with this user
                session_id = create_session(user_id=user["id"])
                message = "Created new session"
            
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "userId": user["id"],
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

    session_id = None
    user_id = None
    
    try:
        req_body = req.get_json()
        input_type = req_body.get("input_type", "text")
        message = req_body.get("message", "").strip()
        audio_base64 = req_body.get("audio_base64")
        session_id = req_body.get("session_id")
        user_id = req_body.get("user_id")  # Get user_id from frontend

        # Verify session ownership if both session_id and user_id are provided
        if session_id and user_id:
            session = get_session(session_id)
            if session.get("user_id") and session["user_id"] != user_id:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Session does not belong to this user",
                        "session_id": session_id
                    }),
                    status_code=403,
                    mimetype="application/json",
                    headers={"Access-Control-Allow-Origin": "*"},
                )

        if not session_id:
            # Create new session, associate with user if provided
            session_id = create_session(user_id=user_id)

        user_text = None
        recognized_text = None

        # Speech input
        if input_type == "speech" and audio_base64:
            try:
                logging.info("Processing speech input...")
                audio_bytes = base64.b64decode(audio_base64)
                logging.info(f"Audio data size: {len(audio_bytes)} bytes")
                
                recognized_text = listen(audio_bytes)
                user_text = recognized_text
                logging.info(f"Recognized text: {recognized_text}")
            except Exception as e:
                logging.error(f"STT processing failed: {str(e)}")
                user_text = "[Speech recognition failed]"
                recognized_text = user_text

        # Text input
        elif input_type == "text" and message:
            user_text = message
        else:
            user_text = "[No input provided]"
            recognized_text = user_text

        # Generate RAG response
        rag_response = generate_response_with_context(user_text)
        ai_reply = rag_response.get("answer", "I couldn't generate a response.")
        references = rag_response.get("references", [])

        # Update session history with user context
        update_session(session_id, user_text, ai_reply, user_id=user_id)

        # TTS - Only generate audio if we have a meaningful response
        audio_response_base64 = None
        if ai_reply and not ai_reply.startswith("I couldn't"):
            try:
                audio_bytes = synthesize_text_to_audio(ai_reply)
                if audio_bytes:
                    audio_response_base64 = base64.b64encode(audio_bytes).decode("utf-8")
                    logging.info("TTS audio generated successfully")
            except Exception as e:
                logging.warning(f"TTS failed: {str(e)}")

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
        logging.error(f"Unexpected error in chat endpoint: {str(e)}")
        return func.HttpResponse(
            json.dumps({
                "error": "Internal server error",
                "session_id": session_id
            }),
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
        
        # Create session for the new user
        session_id = create_session(user_id=user["id"])
        
        return func.HttpResponse(
            json.dumps({
                "success": True,
                "userId": user["id"],
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

@app.route(route="admin/users", methods=["GET", "OPTIONS"])
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

        # Get all users from Cosmos DB
        query = "SELECT * FROM c WHERE c.type = 'user'"
        users = list(container.query_items(query, enable_cross_partition_query=True))
        
        # Remove password from response
        users_response = []
        for user in users:
            users_response.append({
                "id": user["id"],
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

@app.route(route="admin/sessions", methods=["GET", "OPTIONS"])
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

        # Get all sessions from Cosmos DB
        query = "SELECT * FROM c WHERE c.type != 'user' OR NOT IS_DEFINED(c.type)"
        sessions = list(container.query_items(query, enable_cross_partition_query=True))
        
        # Enrich session data with user information
        sessions_response = []
        for session in sessions:
            user_info = {}
            if session.get("user_id"):
                # Get user info for this session
                user_query = f"SELECT * FROM c WHERE c.id = '{session['user_id']}' AND c.type = 'user'"
                users = list(container.query_items(user_query, enable_cross_partition_query=True))
                if users:
                    user = users[0]
                    user_info = {
                        "user_id": user["id"],
                        "username": user["username"],
                        "role": user["role"]
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

@app.route(route="admin/sessions/{user_id}", methods=["GET", "OPTIONS"])
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

@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint"""
    return func.HttpResponse(
        json.dumps({"status": "healthy", "message": "Function app is running"}),
        status_code=200,
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )