import streamlit as st
import requests
import uuid
import time
from streamlit_mic_recorder import mic_recorder
import re
from typing import Optional, List, Dict, Any
import concurrent.futures
import asyncio
import os


def get_secret(key: str, default=None):
    # 1) Prefer environment variables (Render/local)
    val = os.getenv(key)
    if val and str(val).strip():
        return val

    # 2) Try Streamlit secrets ONLY if they exist
    try:
        secrets = st.secrets  # may raise if missing
        return secrets.get(key, default)
    except Exception:
        return default

BASE_API = get_secret("BASE_API", "https://marrfa-chatbot-new2.onrender.com/api")


st.set_page_config(page_title="Marrfa AI", page_icon="🏙️", layout="wide")

# --- Initialize Session State ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_data" not in st.session_state:
    st.session_state.user_data = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_uuid" not in st.session_state:
    st.session_state.user_uuid = str(uuid.uuid4())
if "uploaded_files" not in st.session_state:
    st.session_state.uploaded_files = []
if "is_processing" not in st.session_state:
    st.session_state.is_processing = False
if "last_request_time" not in st.session_state:
    st.session_state.last_request_time = 0

# --- Optimized CSS Styling (minimal) ---
st.markdown("""
    <style>
      .block-container { 
          max-width: 1200px; 
          padding-bottom: 10rem; 
          padding-top: 1rem;
      }

      /* Optimized chat message styling */
      .stChatMessage {
          animation: fadeIn 0.3s ease-in;
      }

      @keyframes fadeIn {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
      }

      /* Optimized Property Card */
      .prop-card {
          background-color: #ffffff;
          border: 1px solid #e0e0e0;
          border-radius: 12px;
          overflow: hidden;
          height: 420px;  /* Reduced slightly */
          margin-bottom: 10px;
          display: flex;
          flex-direction: column;
      }
      .prop-card:hover {
          transform: translateY(-3px);
          box-shadow: 0 5px 15px rgba(0,0,0,0.08);
          transition: transform 0.2s ease, box-shadow 0.2s ease;
      }
      .prop-img {
          width: 100%;
          height: 160px;  /* Reduced from 180px */
          object-fit: cover;
          background-color: #f5f5f5;
      }
      .prop-content { 
          padding: 12px;  /* Reduced from 16px */
          flex-grow: 1; 
          display: flex; 
          flex-direction: column; 
      }
      .prop-title {
          font-size: 0.95rem;  /* Slightly smaller */
          font-weight: 700; 
          color: #1a1a1a;
          height: 40px;  /* Reduced from 48px */
          overflow: hidden; 
          margin-bottom: 6px; 
          line-height: 1.3;
      }
      .prop-details { 
          font-size: 0.85rem;  /* Slightly smaller */
          color: #666; 
          margin-bottom: 3px; 
          display: flex; 
          align-items: center; 
      }
      .prop-price { 
          font-size: 1rem;  /* Slightly smaller */
          font-weight: 700; 
          color: #0046be; 
          margin: 8px 0;  /* Reduced margin */
      }

      /* Fixed Input Dock */
      .footer-container {
          position: fixed;
          bottom: 0;
          left: 0;
          right: 0;
          background: white;
          padding: 15px 0;  /* Reduced padding */
          border-top: 1px solid #eee;
          z-index: 999;
          box-shadow: 0 -2px 10px rgba(0,0,0,0.05);
      }

      /* Loading spinner */
      .stSpinner > div {
          border-color: #0046be transparent transparent transparent !important;
      }

      /* Optimize scroll performance */
      [data-testid="stVerticalBlock"] {
          will-change: transform;
      }

      /* Reduce motion for better performance */
      @media (prefers-reduced-motion: reduce) {
          .prop-card:hover, .stChatMessage {
              animation: none;
              transition: none;
          }
      }
    </style>
""", unsafe_allow_html=True)

# --- Pre-compiled regex patterns for performance ---
NON_ENGLISH_SCRIPTS = re.compile(
    r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0400-\u04FF\u0500-\u052F\u0900-\u097F]')
BASIC_ENGLISH_PATTERN = re.compile(r'^[a-zA-Z0-9\s\.,\?!\-\'"]+$')

# Pre-compiled sets for fast lookup
COMMON_ENGLISH_WORDS = {
    'the', 'be', 'to', 'of', 'and', 'a', 'in', 'that', 'have', 'i',
    'it', 'for', 'not', 'on', 'with', 'he', 'as', 'you', 'do', 'at',
    'this', 'but', 'his', 'by', 'from', 'they', 'we', 'say', 'her', 'she',
    'or', 'an', 'will', 'my', 'one', 'all', 'would', 'there', 'their',
    'what', 'so', 'up', 'out', 'if', 'about', 'who', 'get', 'which',
    'go', 'me', 'when', 'make', 'can', 'like', 'time', 'no', 'just',
    'him', 'know', 'take', 'people', 'into', 'year', 'your', 'good',
    'some', 'could', 'them', 'see', 'other', 'than', 'then', 'now',
    'look', 'only', 'come', 'its', 'over', 'think', 'also', 'back',
    'after', 'use', 'two', 'how', 'our', 'work', 'first', 'well',
    'way', 'even', 'new', 'want', 'because', 'any', 'these', 'give',
    'day', 'most', 'us'
}

ESTATE_WORDS = {
    'property', 'properties', 'real estate', 'dubai', 'apartment', 'villa',
    'price', 'location', 'bedroom', 'bathroom', 'square', 'feet', 'meter',
    'view', 'pool', 'gym', 'parking', 'balcony', 'kitchen', 'living', 'room',
    'for sale', 'for rent', 'buy', 'rent', 'lease', 'agent', 'developer',
    'project', 'community', 'neighborhood', 'amenities', 'facilities',
    'marrfa', 'house', 'home', 'investment', 'luxury', 'modern', 'new'
}


# --- Optimized helper functions ---
def is_likely_english_fast(text: str) -> bool:
    """Fast check if text is likely English."""
    if not text or not text.strip():
        return False

    text = text.strip()
    text_lower = text.lower()

    # Very short text is acceptable
    if len(text) < 3:
        return True

    # Check for non-English scripts (fast regex)
    if NON_ENGLISH_SCRIPTS.search(text):
        return False

    # Check basic English pattern
    if BASIC_ENGLISH_PATTERN.match(text):
        return True

    # Fast word set intersection
    words = set(text_lower.split())
    if words & COMMON_ENGLISH_WORDS:
        return True
    if words & ESTATE_WORDS:
        return True

    # ASCII ratio check (optimized)
    ascii_count = 0
    for char in text:
        if ord(char) < 128:
            ascii_count += 1
        if ascii_count / len(text) > 0.8:  # Early exit
            return True

    return False


def prepare_files_for_upload(files) -> List[tuple]:
    """Optimized file preparation."""
    if not files:
        return []

    request_files = []
    for file in files:
        # Use file name directly, don't read entire file unless needed
        request_files.append(("files", (file.name, file.getvalue(), file.type)))
    return request_files


def format_property_price(price_from: Optional[float]) -> str:
    """Fast price formatting."""
    if price_from:
        return f"{price_from:,.0f}"
    return "On Request"


# --- Sidebar: Login/Signup Logic (optimized) ---
with st.sidebar:
    st.title("👤 Marrfa Account")
    if not st.session_state.authenticated:
        t1, t2 = st.tabs(["Login", "Sign Up"])
        with t1:
            lid = st.text_input("Username/Email", key="l_id")
            lpw = st.text_input("Password", type="password", key="l_pw")
            if st.button("Log In", use_container_width=True):
                with st.spinner("Logging in..."):
                    try:
                        res = requests.post(f"{BASE_API}/login",
                                            json={"identifier": lid, "password": lpw},
                                            timeout=5)
                        if res.status_code == 200:
                            st.session_state.authenticated = True
                            st.session_state.user_data = res.json()["user"]
                            st.rerun()
                        else:
                            st.error("Invalid credentials.")
                    except requests.exceptions.Timeout:
                        st.error("Login timed out. Please try again.")
                    except Exception as e:
                        st.error(f"Login error: {str(e)}")

        with t2:
            sun = st.text_input("Username", key="s_un")
            sem = st.text_input("Email", key="s_em")
            spw = st.text_input("Password", type="password", key="s_pw")
            if st.button("Create Account", use_container_width=True):
                with st.spinner("Creating account..."):
                    try:
                        res = requests.post(f"{BASE_API}/signup",
                                            json={"username": sun, "email": sem, "phone": "N/A", "password": spw},
                                            timeout=5)
                        if res.status_code == 200:
                            st.success("Account created! Please log in.")
                        else:
                            st.error("Account creation failed.")
                    except requests.exceptions.Timeout:
                        st.error("Request timed out. Please try again.")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
    else:
        st.write(f"Logged in as: **{st.session_state.user_data['username']}**")
        if st.button("Log Out", use_container_width=True, type="primary"):
            st.session_state.authenticated = False
            st.session_state.user_data = None
            st.session_state.messages = []  # Clear chat on logout
            st.rerun()


# --- Optimized send_message function ---
def send_message(text: str, files=None):
    """Send a message to the chatbot with optional files."""
    if not text and not files:
        return

    # Rate limiting: prevent rapid requests
    current_time = time.time()
    if current_time - st.session_state.last_request_time < 1.0:  # 1 second cooldown
        st.warning("Please wait a moment before sending another message.")
        return

    # Check if text is likely English (fast check)
    if text and not is_likely_english_fast(text):
        st.session_state.messages.append({
            "role": "assistant",
            "content": "I apologize, but I'm having trouble understanding that. I can only understand and respond to English. Could you please repeat your question in English about Marrfa properties?"
        })
        return

    # Add user message immediately for instant feedback
    user_content = text if text else "📎 Uploaded file"
    if files:
        file_names = ", ".join([f.name for f in files[:2]])  # Limit to 2 names
        if len(files) > 2:
            file_names += f" and {len(files) - 2} more"
        user_content = f"📎 {file_names}" + (f": {text}" if text else "")

    st.session_state.messages.append({"role": "user", "content": user_content})
    st.session_state.last_request_time = current_time
    st.session_state.is_processing = True

    try:
        # Prepare data
        data = {
            "query": text,
            "session_id": st.session_state.user_uuid,
            "is_logged_in": st.session_state.authenticated
        }

        # Prepare files (optimized)
        request_files = prepare_files_for_upload(files) if files else []

        # Determine timeout
        timeout = 25 if files else 15  # Longer timeout for files

        # Show loading indicator in a separate container
        with st.spinner("Thinking..."):
            start_time = time.time()

            if request_files:
                # Send with files
                response = requests.post(
                    f"{BASE_API}/chat",
                    data=data,
                    files=request_files,
                    timeout=timeout
                )
            else:
                # Send without files
                response = requests.post(
                    f"{BASE_API}/chat",
                    json=data,
                    timeout=timeout
                )

            processing_time = time.time() - start_time

            if response.status_code == 200:
                result = response.json()

                # Add assistant response
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": result["reply"],
                    "properties": result.get("properties", []),
                    "processing_time": processing_time
                })

                # Track uploaded files
                if files:
                    for file in files:
                        st.session_state.uploaded_files.append(file.name)

                # Log performance (optional)
                if processing_time > 3.0:
                    print(f"Slow response: {processing_time:.2f}s for query: {text[:50]}...")

            elif response.status_code == 429:
                st.error("Too many requests. Please wait a moment and try again.")
            else:
                st.error(f"Server error: {response.status_code}")

    except requests.exceptions.Timeout:
        st.error("Request timed out. The server is taking too long to respond.")
        # Add a helpful message
        st.session_state.messages.append({
            "role": "assistant",
            "content": "I'm experiencing high demand right now. Please try your request again in a moment."
        })
    except requests.exceptions.ConnectionError:
        st.error("Connection error. Please check your internet connection.")
    except Exception as e:
        st.error(f"Error: {str(e)}")
    finally:
        st.session_state.is_processing = False


# --- Optimized Chat Display ---
chat_container = st.container()
with chat_container:
    # Only render visible messages for performance
    total_messages = len(st.session_state.messages)
    visible_start = max(0, total_messages - 20)  # Show last 20 messages

    for idx, m in enumerate(st.session_state.messages[visible_start:], start=visible_start):
        with st.chat_message(m["role"]):
            st.write(m["content"])

            if m["role"] == "assistant" and m.get("properties"):
                properties = m["properties"]
                num_properties = len(properties)

                if num_properties > 0:
                    # Use grid layout for better performance
                    cols = st.columns(3)

                    for i, p in enumerate(properties):
                        col_idx = i % 3
                        with cols[col_idx]:
                            # Fast price formatting
                            p_from = format_property_price(p.get('price_from'))
                            img_url = p.get("cover_image") or "https://via.placeholder.com/400x300?text=Marrfa"

                            # Use markdown with minimal HTML for better performance
                            st.markdown(f"""
                            <div class="prop-card">
                                <img src="{img_url}" class="prop-img" loading="lazy" alt="{p['title']}">
                                <div class="prop-content">
                                    <div class="prop-title">{p['title']}</div>
                                    <div class="prop-details">📍 {p.get('location', 'Dubai')}</div>
                                    <div class="prop-price">{p_from} {p.get('currency', 'AED')}</div>
                                    <div class="prop-details">🗓️ {p.get('completion_year', 'TBD')}</div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)

                            if p.get("listing_url"):
                                st.link_button("View details", p["listing_url"], use_container_width=True)

# --- Gemini-style Chat Input with File Upload (optimized) ---
st.markdown('<div class="footer-container">', unsafe_allow_html=True)

# Create columns for the input area
col_input, col_mic = st.columns([5, 1])

with col_input:
    # Optimized chat input with debouncing
    chat_data = st.chat_input(
        "Ask about properties, Marrfa company info, or upload files...",
        accept_file=True,
        file_type=["pdf", "txt", "docx", "doc", "png", "jpg", "jpeg", "csv", "xlsx", "pptx"],
        key="chat_input",
        disabled=st.session_state.is_processing  # Disable while processing
    )

with col_mic:
    # Voice recording button with status
    if st.session_state.is_processing:
        st.button("⏳", disabled=True, help="Processing...", use_container_width=True)
    else:
        audio = mic_recorder(
            start_prompt="🎤",
            stop_prompt="⏹️",
            just_once=True,
            key="mic",
            use_container_width=True
        )

st.markdown('</div>', unsafe_allow_html=True)

# --- Process Chat Input (optimized) ---
if chat_data and not st.session_state.is_processing:
    # Extract text and files from chat_data
    user_text = chat_data.text
    uploaded_files = chat_data.files if hasattr(chat_data, 'files') else []

    # Check authentication for file uploads
    if uploaded_files and not st.session_state.authenticated:
        st.warning("Please log in to upload files.")
        # Still send text if there is any
        if user_text:
            send_message(user_text)
    else:
        send_message(user_text, uploaded_files)

    # Use experimental_rerun for better performance
    st.rerun()

# --- Process Voice Input (optimized) ---
if audio and audio.get("bytes") and not st.session_state.is_processing:
    try:
        # Show processing indicator
        with st.spinner("Transcribing..."):
            # Send audio to backend for transcription
            files = {"file": ("audio.wav", audio["bytes"], "audio/wav")}
            response = requests.post(f"{BASE_API}/transcribe",
                                     files=files,
                                     timeout=10)  # Shorter timeout for audio

            if response.status_code == 200:
                result = response.json()
                transcript = result.get("text", "")
                error_msg = result.get("error", "")

                if error_msg:
                    st.error(f"Transcription error: {error_msg}")
                elif transcript:
                    # Fast English check
                    if not is_likely_english_fast(transcript):
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": "I apologize, but I'm having trouble understanding that. I can only understand and respond to English. Could you please repeat your question in English about Marrfa properties?"
                        })
                    else:
                        send_message(transcript)
                else:
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": "I couldn't detect any speech. Could you please speak clearly in English about Marrfa properties?"
                    })
            else:
                st.error("Voice transcription service unavailable")

    except requests.exceptions.Timeout:
        st.error("Voice transcription timed out. Please try again.")
    except Exception as e:
        st.error(f"Voice transcription failed: {str(e)}")
    finally:
        st.rerun()

# --- Display Recently Analyzed Files (optimized) ---
if st.session_state.uploaded_files:
    with st.expander("📁 Recently Uploaded Files", expanded=False):
        # Show only unique recent files
        unique_files = []
        seen = set()
        for file_name in reversed(st.session_state.uploaded_files):
            if file_name not in seen:
                seen.add(file_name)
                unique_files.append(file_name)
            if len(unique_files) >= 5:
                break

        for file_name in unique_files:
            st.text(f"• {file_name}")

# --- Performance optimization: Clear old messages if too many ---
if len(st.session_state.messages) > 50:
    # Keep last 30 messages for performance
    st.session_state.messages = st.session_state.messages[-30:]

    # Optional: Show notification
    if not st.session_state.get("cleared_notice_shown", False):
        st.session_state.messages.append({
            "role": "assistant",
            "content": "💾 I've cleared some older messages to keep the chat running smoothly."
        })
        st.session_state.cleared_notice_shown = True

# --- Optional: Add a clear chat button in sidebar ---
with st.sidebar:
    st.markdown("---")
    if st.button("🧹 Clear Chat", use_container_width=True, type="secondary"):
        st.session_state.messages = []
        st.session_state.uploaded_files = []
        st.success("Chat cleared!")
        st.rerun()

    # Show performance stats (optional)
    if st.session_state.get("is_processing", False):
        st.caption("⏳ Processing...")

    # Show message count
    message_count = len(st.session_state.messages)
    if message_count > 0:

        st.caption(f"💬 {message_count} messages in chat")

