# backend/app/schemas.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class Property(BaseModel):
    title: str
    location: Optional[str] = None
    price_from: Optional[float] = None
    price_to: Optional[float] = None
    currency: Optional[str] = None
    cover_image: Optional[str] = None
    images: Optional[List[str]] = None
    completion_year: Optional[str] = None
    listing_url: Optional[str] = None

class ChatRequest(BaseModel):
    query: str = ""
    session_id: Optional[str] = None
    is_logged_in: bool = False
    page: int = 1
    per_page: int = 10
    # Search filters
    areas: Optional[List[int]] = None
    unit_types: Optional[List[str]] = None
    unit_bedrooms: Optional[str] = None
    status: Optional[List[str]] = None
    sale_status: Optional[List[str]] = None

class ChatResponse(BaseModel):
    reply: str
    properties: List[Property] = []
    total: int = 0
    page: int = 1
    per_page: int = 10
    filters_used: Dict[str, Any] = {}

    # ✅ ADD THIS
    properties_full: Optional[List[Dict[str, Any]]] = None


# --- Authentication Models ---
class LoginRequest(BaseModel):
    identifier: str
    password: str

class SignupRequest(BaseModel):
    username: str
    email: str
    phone: str
    password: str
