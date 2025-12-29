from typing import Dict, Any, Optional, FrozenSet
import re
from functools import lru_cache
from openai import OpenAI

# =======================
# GREETINGS
# =======================
GREETING_PATTERNS = frozenset({
    "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
    "how are you", "what's up", "yo", "hiya", "hola", "namaste"
})

SHORT_GREETINGS = frozenset({"?", "??", "!", "..."})

# =======================
# PROPERTY KEYWORDS
# =======================
PROPERTY_BASIC = frozenset({
    "property", "properties",
    "real", "estate",
    "apartment", "apartments",
    "villa", "villas",
    "house", "houses",
    "home", "homes",
    "flat", "flats",
    "plot", "plots",
    "townhouse", "townhouses",
    "penthouse", "penthouses",
    "studio", "studios",
    "duplex", "duplexes",
    "agent", "agents",
    "agency", "agencies",
    "broker", "brokers",
})

PROPERTY_ACTION = frozenset({
    "buy", "purchase", "rent", "lease", "sale", "sell", "suggest", "recommend", "show"
})

PROPERTY_LOCATIONS = frozenset({
    "dubai", "marina", "business bay", "jumeirah", "palm", "creek", "hills"
})

# =======================
# COMPANY KEYWORDS
# =======================
COMPANY_KEYWORDS = frozenset({
    "marrfa", "marfa", "company", "team", "about", "history",
    "ceo", "owner", "founder", "director", "management", "leadership"
})

# =======================
# REGEX PATTERNS
# =======================

PRICE_PATTERN = re.compile(
    r"(\d+(\.\d+)?\s*(m|million|aed))",
    re.IGNORECASE
)

LEADERSHIP_PATTERN = re.compile(
    r"(who|what)\s+(is|are)\s+(the\s+)?"
    r"(your\s+|their\s+|this\s+|marrfa'?s\s+)?"
    r"(ceo|owner|founder|director|head|boss|leader)",
    re.IGNORECASE
)

BUILT_BY_PATTERN = re.compile(
    r"(who|what)\s+(built|created|made|developed)\s+(this|it|marrfa|chatbot|system)",
    re.IGNORECASE
)

SHORT_QUERY_PATTERN = re.compile(r"^\s*(\S\s*){0,2}\s*$")

# =======================
# HELPERS
# =======================

def _contains_any(text: str, keywords: FrozenSet[str]) -> bool:
    words = set(text.split())
    for w in words:
        if w in keywords:
            return True
        if w.endswith("s") and w[:-1] in keywords:
            return True
        if w.endswith("ies") and (w[:-3] + "y") in keywords:
            return True
    return False


# =======================
# MAIN CLASSIFIER
# =======================

def classify_intent(query: str, client: Optional[OpenAI] = None) -> Dict[str, Any]:
    q = query.lower().strip()
    words = q.split()

    # 1️⃣ Empty / greeting
    if not q or q in SHORT_GREETINGS or SHORT_QUERY_PATTERN.match(q):
        return {"intent": "GREETING", "method": "empty"}

    if any(g in q for g in GREETING_PATTERNS):
        return {"intent": "GREETING", "method": "greeting"}

    # 2️⃣ COMPANY – leadership
    if LEADERSHIP_PATTERN.search(q):
        return {"intent": "COMPANY", "method": "leadership"}

    if BUILT_BY_PATTERN.search(q):
        return {"intent": "COMPANY", "method": "built_by"}

    # 3️⃣ PROPERTY – strong override
    has_property_word = _contains_any(q, PROPERTY_BASIC)
    has_action = _contains_any(q, PROPERTY_ACTION)
    has_location = _contains_any(q, PROPERTY_LOCATIONS)
    has_price = bool(PRICE_PATTERN.search(q))

    if has_property_word or has_price or has_location:
        return {"intent": "PROPERTY", "method": "property_override"}

    # 4️⃣ COMPANY – general
    if _contains_any(q, COMPANY_KEYWORDS):
        return {"intent": "COMPANY", "method": "company_keyword"}

    # 5️⃣ Fallback to OpenAI (rare)
    if client and len(words) <= 6:
        try:
            resp = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Classify as GREETING, PROPERTY, COMPANY, or OUT_OF_CONTEXT"},
                    {"role": "user", "content": query}
                ],
                temperature=0,
                max_tokens=5
            )
            intent = resp.choices[0].message.content.strip().upper()
            if intent in {"GREETING", "PROPERTY", "COMPANY", "OUT_OF_CONTEXT"}:
                return {"intent": intent, "method": "openai"}
        except Exception:
            pass

    return {"intent": "OUT_OF_CONTEXT", "method": "default"}


# =======================
# CACHED VERSION
# =======================

@lru_cache(maxsize=500)
def classify_intent_cached(query: str) -> Dict[str, Any]:
    return classify_intent(query)
