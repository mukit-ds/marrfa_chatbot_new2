import os
import tempfile
import hashlib
import pymongo
import json
import base64
from datetime import datetime
from typing import List, Dict, Any, Optional
import io
import time
import asyncio
from functools import lru_cache
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

from .schemas import ChatRequest, ChatResponse, Property, LoginRequest, SignupRequest
from .intent_classifier import classify_intent
from .property_search import handle_property_query
from .company_kb import handle_company_query
from .file_processor import process_uploaded_file, analyze_files_with_ai
from .audio_transcription import transcribe_audio
from .auth import hash_password, check_and_update_limit, handle_signup, handle_login
from .parser import parse_query_to_filters

load_dotenv()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MongoDB Setup ---
MONGO_URI = os.getenv("MONGO_URI")
mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client["marrfa_db"]
usage_col = db["anonymous_usage"]
users_col = db["users"]

# --- OpenAI Client ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# --- File Processing Configuration ---
SUPPORTED_EXTENSIONS = {
    'image': ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp'],
    'document': ['pdf', 'docx', 'txt', 'csv', 'xlsx', 'pptx'],
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# --- Caching Setup ---
QUERY_CACHE = {}
CACHE_TIMEOUT = 300  # 5 minutes
PROPERTY_CACHE = {}
PROPERTY_CACHE_TIMEOUT = 60  # 1 minute for property searches


def get_cache_key(query_text: str, intent: str, filters: Dict = None) -> str:
    """Generate a cache key for queries."""
    key_data = f"{query_text}:{intent}"
    if filters:
        # Sort filters for consistent keys
        key_data += f":{json.dumps({k: filters[k] for k in sorted(filters.keys()) if filters[k] is not None}, sort_keys=True)}"
    return hashlib.md5(key_data.encode()).hexdigest()


def clear_old_cache():
    """Clear old cache entries."""
    current_time = time.time()
    keys_to_delete = []

    # Clear QUERY_CACHE
    for key, (timestamp, _) in QUERY_CACHE.items():
        if current_time - timestamp > CACHE_TIMEOUT:
            keys_to_delete.append(key)
    for key in keys_to_delete:
        del QUERY_CACHE[key]

    # Clear PROPERTY_CACHE
    keys_to_delete = []
    for key, (timestamp, _) in PROPERTY_CACHE.items():
        if current_time - timestamp > PROPERTY_CACHE_TIMEOUT:
            keys_to_delete.append(key)
    for key in keys_to_delete:
        del PROPERTY_CACHE[key]


# --- Optimized Functions with Caching ---
@lru_cache(maxsize=500)
def classify_intent_cached(query: str) -> Dict[str, Any]:
    """Cached version of intent classification."""
    return classify_intent(query, client)


@lru_cache(maxsize=1000)
def parse_query_to_filters_cached(query: str) -> Dict:
    """Cached version of parser."""
    return parse_query_to_filters(query)


def get_greeting_response(intent_result: Dict[str, Any]) -> str:
    """Generate appropriate greeting response based on intent classification method."""
    method = intent_result.get("method", "")

    if method == "listening_check":
        return "Yes, I'm listening! 👋 I'm Marrfa AI, ready to help you with Dubai properties and Marrfa company information. What would you like to know?"
    elif method == "chatbot_self":
        return "Yes, I'm here and ready to assist! I'm Marrfa AI, specialized in Dubai real estate and Marrfa company information. How can I help you today?"
    elif method == "empty_query":
        return "Hello! 👋 I noticed you sent a short message. I'm Marrfa AI, here to help with Dubai properties and Marrfa company details. What would you like to know?"
    else:
        return (
            "Hello! 👋 I'm Marrfa AI. "
            "You can ask me about Marrfa (team, CEO, policies, terms) "
            "or search for properties in Dubai. You can also upload files for analysis."
        )


# --- API Endpoints ---
@app.post("/api/signup")
async def signup(req: SignupRequest):
    return handle_signup(req.username, req.email, req.phone, req.password, users_col)


@app.post("/api/login")
async def login(req: LoginRequest):
    return handle_login(req.identifier, req.password, users_col)


@app.post("/api/chat")
async def chat(request: Request):
    """Handle chat requests with optional file uploads."""
    start_time = time.time()

    # Clear old cache periodically
    if len(QUERY_CACHE) > 1000 or len(PROPERTY_CACHE) > 500:
        clear_old_cache()

    # Check if the request is multipart/form-data (for file uploads)
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        # Handle form data with files
        form = await request.form()
        query = form.get("query", "")
        session_id = form.get("session_id")
        is_logged_in = form.get("is_logged_in", "false").lower() == "true"

        # Process uploaded files if any
        files = []
        for key in form:
            if key.startswith("file") or key == "files":
                files.append(form[key])
    else:
        # Handle JSON data
        try:
            body = await request.json()
            query = body.get("query", "")
            session_id = body.get("session_id")
            is_logged_in = body.get("is_logged_in", False)
            files = body.get("files", [])
        except Exception as e:
            print(f"Error parsing JSON: {e}")
            # If JSON parsing fails, try to get the raw body
            body = await request.body()
            try:
                data = json.loads(body.decode("utf-8"))
                query = data.get("query", "")
                session_id = data.get("session_id")
                is_logged_in = data.get("is_logged_in", False)
                files = data.get("files", [])
            except:
                query = ""
                session_id = None
                is_logged_in = False
                files = []

    print(f"Received chat request: query='{query}', session_id='{session_id}', is_logged_in={is_logged_in}")

    # Check Usage Limit
    if not is_logged_in:
        if not check_and_update_limit(session_id, usage_col):
            print("User reached limit")
            return ChatResponse(
                reply="🔒 You've reached the 3-query limit. Please log in to continue.",
                filters_used={"error": "LIMIT"}
            )

    query_text = (query or "").strip()
    print(f"Query text: '{query_text}' - Processing time: {time.time() - start_time:.2f}s")

    # Check cache first (only for non-file queries)
    if not files:
        cache_key = get_cache_key(query_text, "intent_only")
        if cache_key in QUERY_CACHE:
            timestamp, cached_result = QUERY_CACHE[cache_key]
            if time.time() - timestamp < CACHE_TIMEOUT:
                print(f"Cache hit for: {query_text}")
                return cached_result

    # Classify intent (using cached version)
    intent_result = classify_intent_cached(query_text)
    intent = intent_result["intent"]

    print(f"Intent result: {intent_result} - Time: {time.time() - start_time:.2f}s")

    # 1️⃣ Greeting (fast path)
    if intent == "GREETING":
        greeting_reply = get_greeting_response(intent_result)
        response = ChatResponse(
            reply=greeting_reply,
            filters_used={"intent": "GREETING", "method": intent_result["method"]}
        )
        if not files:
            QUERY_CACHE[cache_key] = (time.time(), response)
        return response

    # Process uploaded files if any
    file_contents = []
    if files:
        print(f"Processing {len(files)} files")
        for file in files:
            if not is_logged_in:
                return ChatResponse(
                    reply="Please log in to upload and analyze files.",
                    filters_used={"error": "AUTH_REQUIRED"}
                )

            # Check file size
            if hasattr(file, 'read'):
                file_bytes = await file.read()
                filename = file.filename
            else:
                # Handle files sent as JSON (base64 encoded)
                file_bytes = base64.b64decode(file.get("content", ""))
                filename = file.get("name", "unknown")

            if len(file_bytes) > MAX_FILE_SIZE:
                return ChatResponse(
                    reply=f"File '{filename}' is too large. Maximum size is 10MB.",
                    filters_used={"error": "FILE_TOO_LARGE"}
                )

            # Process file
            file_info = process_uploaded_file(file_bytes, filename)
            if file_info["error"]:
                return ChatResponse(
                    reply=f"Error processing '{filename}': {file_info['error']}",
                    filters_used={"error": "FILE_PROCESSING_ERROR"}
                )

            file_contents.append(file_info["text_content"])

    # If files were uploaded, analyze them
    if file_contents:
        print("Analyzing uploaded files")
        analysis_result = analyze_files_with_ai(file_contents, query_text, client)
        response = ChatResponse(
            reply=analysis_result,
            filters_used={"intent": "FILE_ANALYSIS", "files_count": len(files)}
        )
        # Don't cache file analysis results
        return response

    # No files, proceed with normal chat routing based on intent
    if intent == "PROPERTY":
        print("Handling PROPERTY intent")
        try:
            # Check for property query cache
            filters = parse_query_to_filters_cached(query_text)
            property_cache_key = get_cache_key(query_text, "PROPERTY", filters)

            if property_cache_key in PROPERTY_CACHE:
                timestamp, cached_result = PROPERTY_CACHE[property_cache_key]
                if time.time() - timestamp < PROPERTY_CACHE_TIMEOUT:
                    print(f"Property cache hit for: {query_text}")
                    return cached_result

            # Run property search
            result = handle_property_query(query_text)

            response = ChatResponse(
            reply=result["reply"],
            properties=result["properties"],
            total=result["total"],
            page=1,
            per_page=10,
            filters_used=result["filters"],
            properties_full=result.get("properties_full")  # ✅ ADD
)




            # Cache successful property queries (only if we found properties)
            if result["total"] > 0:
                PROPERTY_CACHE[property_cache_key] = (time.time(), response)

            # Also cache in general query cache
            if not files:
                general_cache_key = get_cache_key(query_text, "intent_only")
                QUERY_CACHE[general_cache_key] = (time.time(), response)

            print(f"Property search completed in {time.time() - start_time:.2f}s")
            return response

        except Exception as e:
            print(f"Property search error: {e}")
            import traceback
            traceback.print_exc()
            return ChatResponse(
                reply="I'm having trouble searching for properties right now. Please try again later.",
                properties=[],
                total=0,
                page=1,
                per_page=10,
                filters_used={"intent": "PROPERTY", "error": str(e)}
            )

    elif intent == "COMPANY":
        print("Handling COMPANY intent")
        try:
            # Check for company query cache
            company_cache_key = get_cache_key(query_text, "COMPANY")
            if company_cache_key in QUERY_CACHE:
                timestamp, cached_result = QUERY_CACHE[company_cache_key]
                if time.time() - timestamp < CACHE_TIMEOUT:
                    print(f"Company cache hit for: {query_text}")
                    return cached_result

            result = handle_company_query(query_text)
            response = ChatResponse(
                reply=result["reply"],
                properties=[],
                total=0,
                page=1,
                per_page=10,
                filters_used=result["filters"]
            )

            # Cache company queries (they're usually static)
            QUERY_CACHE[company_cache_key] = (time.time(), response)

            print(f"Company KB completed in {time.time() - start_time:.2f}s")
            return response

        except Exception as e:
            print(f"Company KB error: {e}")
            import traceback
            traceback.print_exc()
            return ChatResponse(
                reply="I'm having trouble accessing company information right now. Please try again later.",
                properties=[],
                total=0,
                page=1,
                per_page=10,
                filters_used={"intent": "COMPANY", "error": str(e)}
            )

    # 5️⃣ Out of context
    print("Handling OUT_OF_CONTEXT intent")
    response = ChatResponse(
        reply="I'm trained specifically on Marrfa Real Estate. Please ask about Marrfa or properties in Dubai.",
        properties=[],
        total=0,
        page=1,
        per_page=10,
        filters_used={"intent": "OUT_OF_CONTEXT", "method": intent_result["method"]},
    )
    if not files:
        cache_key = get_cache_key(query_text, "intent_only")
        QUERY_CACHE[cache_key] = (time.time(), response)
    return response


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """Transcribe audio using OpenAI Whisper."""
    return await transcribe_audio(file, client)


# --- Cache Management Endpoints ---
@app.post("/api/clear-cache")
async def clear_cache():
    """Clear the query cache."""
    global QUERY_CACHE, PROPERTY_CACHE
    old_query_size = len(QUERY_CACHE)
    old_property_size = len(PROPERTY_CACHE)
    QUERY_CACHE = {}
    PROPERTY_CACHE = {}
    return {
        "message": f"Cache cleared. Removed {old_query_size} query entries and {old_property_size} property entries.",
        "old_query_size": old_query_size,
        "old_property_size": old_property_size
    }


@app.get("/api/cache-stats")
async def cache_stats():
    """Get cache statistics."""
    return {
        "query_cache_size": len(QUERY_CACHE),
        "property_cache_size": len(PROPERTY_CACHE),
        "query_cache_timeout": CACHE_TIMEOUT,
        "property_cache_timeout": PROPERTY_CACHE_TIMEOUT
    }


# --- Health & Debug Endpoints ---
@app.get("/health")
async def health():
    from .company_kb import get_faiss_kb
    kb = get_faiss_kb()
    return {
        "status": "ok",
        "kb_ready": bool(kb),
        "kb_error": getattr(kb, 'faiss_kb_error', None),
        "file_analysis_enabled": True,
        "max_file_size_mb": MAX_FILE_SIZE / 1024 / 1024,
        "openai_client": bool(client),
        "caching_enabled": True,
        "query_cache_size": len(QUERY_CACHE),
        "property_cache_size": len(PROPERTY_CACHE)
    }


@app.get("/api/debug-kb")
async def debug_kb():
    from .company_kb import get_faiss_kb
    kb = get_faiss_kb()
    if not kb:
        return {"kb": "FAISS", "error": getattr(kb, 'faiss_kb_error', None)}

    titles = {}
    for c in kb.chunk_by_id.values():
        titles[c["title"]] = titles.get(c["title"], 0) + 1

    return {
        "kb": "FAISS",
        "kb_dir": kb.out_dir,
        "total_chunks": len(kb.chunk_by_id),
        "titles": titles,
    }


@app.get("/api/supported-files")
async def get_supported_files():
    return {
        "supported_extensions": SUPPORTED_EXTENSIONS,
        "max_file_size_mb": MAX_FILE_SIZE / 1024 / 1024,
    }


@app.get("/api/debug-intent")
async def debug_intent(query: str = ""):
    """Debug endpoint to test intent classification"""
    if not query:
        return {"error": "No query provided"}

    intent_result = classify_intent_cached(query)

    return {
        "query": query,
        "intent": intent_result["intent"],
        "method": intent_result["method"]
    }


@app.get("/api/test-property-search")
async def test_property_search(query: str = "properties in dubai"):
    """Test endpoint for property search"""
    try:
        result = handle_property_query(query)
        return {
            "query": query,
            "result": result,
            "status": "success"
        }
    except Exception as e:
        return {
            "query": query,
            "error": str(e),
            "status": "error"
        }


@app.get("/api/debug-kb-chunks")
async def debug_kb_chunks():
    """Debug endpoint to see what chunks are in the knowledge base"""
    from .company_kb import get_faiss_kb
    kb = get_faiss_kb()
    if not kb:
        return {"error": "Knowledge base not loaded"}

    # Return first 10 chunks for debugging
    chunks = list(kb.chunk_by_id.values())[:10]

    return {
        "total_chunks": len(kb.chunk_by_id),
        "sample_chunks": chunks,
        "enabled": kb.enabled
    }


@app.get("/api/debug-query")
async def debug_query(query: str = "Who is the ceo?"):
    """Debug endpoint to test knowledge base queries"""
    from .company_kb import get_faiss_kb
    kb = get_faiss_kb()
    if not kb:
        return {"error": "Knowledge base not loaded"}

    # Test the query
    results = kb.query(query, top_k=10, similarity_threshold=0.1)

    # Test the answer
    answer = kb.answer(query, top_k=12)

    return {
        "query": query,
        "results": results,
        "answer": answer,
        "total_chunks": len(kb.chunk_by_id)
    }


# --- Startup Event ---
@app.on_event("startup")
async def startup_event():
    """Initialize caches and warm up frequently used queries."""
    print("Starting up Marrfa AI Chatbot...")

    # Warm up the intent classifier cache with common queries
    warm_up_queries = [
        "hello",
        "hi",
        "properties in dubai",
        "show me apartments",
        "who is the ceo of marrfa",
        "about marrfa",
        "thank you",
        "help"
    ]

    for query in warm_up_queries:
        try:
            classify_intent_cached(query)
        except:
            pass

    print(f"Warmed up intent classifier with {len(warm_up_queries)} queries")
    print(f"Cache initialized: query_cache={len(QUERY_CACHE)}, property_cache={len(PROPERTY_CACHE)}")
