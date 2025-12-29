from typing import Dict, List, Any
from .schemas import Property
from .parser import parse_query_to_filters
from .marrfa_client import search_properties, search_properties_raw
import re


def analyze_query_context(query: str) -> Dict[str, Any]:
    """Analyze the query for specific patterns and context."""
    query_lower = query.lower().strip()

    context = {
        "is_question": query_lower.endswith('?'),
        "is_polite": any(word in query_lower for word in
                         ["please", "could you", "would you", "can you", "may i", "would it be possible"]),
        "is_direct": any(word in query_lower for word in
                         ["show me", "give me", "find me", "search for", "look for", "get"]),
        "is_recommendation": any(word in query_lower for word in
                                 ["recommend", "suggest", "advise", "what would you suggest"]),
        "is_inquiry": any(word in query_lower for word in
                          ["how many", "what kind of", "what types of", "what are the", "do you have"]),
        "is_best_related": any(word in query_lower for word in
                               ["best", "top", "premium", "luxury", "exclusive", "featured", "high-end"]),
        "mentions_marrfa": any(word in query_lower for word in
                               ["marrfa", "marfa", "marrfa's", "marfa's"]),
        "is_broad_query": len(query_lower.split()) <= 4 and "properties" in query_lower,
        "mentions_all": any(word in query_lower for word in
                            ["all", "every", "each", "maximum", "max", "as many as", "show all"]),
    }

    return context


def generate_professional_reply(query: str, filters: Dict, properties: List[Property], total: int,
                                show_count: int) -> str:
    """Generate a professional, contextual reply based on the query and results."""

    if total == 0:
        return None

    context = analyze_query_context(query)

    location = filters.get("search_query", "Dubai").title()
    query_lower = query.lower()

    if ("how many" in query_lower and "property" in query_lower and context["mentions_marrfa"]):
        return f"Marrfa currently has {total} properties listed in {location}. Here are the top {show_count}:"

    if context["mentions_all"]:
        return f"Here are {show_count} of the {total} available properties in {location}:"

    if context["is_recommendation"]:
        return f"Based on current market analysis, I recommend these {show_count} premium properties in {location}:"

    if context["is_best_related"]:
        return f"Here are the {show_count} best properties in {location}, selected for their premium features:"

    return f"The {location} market offers {total} premium properties. Here are the top {show_count} selections:"


def handle_property_query(query_text: str) -> Dict[str, Any]:
    """
    Handle property search queries.
    """

    # ============================================================
    # ✅ Minimal FIX: Agency/agent recommendation should NOT return properties
    # ============================================================
    q = (query_text or "").lower().strip()
    agency_terms = [
        "real estate agency", "real-estate agency",
        "real state agency",     # common typo
        "estate agency",
        "agency", "agent", "agents",
        "broker", "brokers",
        "real estate agent", "real state agent"
    ]
    recommend_terms = ["suggest", "recommend", "best", "top", "good"]

    if any(t in q for t in agency_terms) and any(t in q for t in recommend_terms):
        return {
            "reply": (
                "If you're looking for a **reliable real estate agency in Dubai**, I can help you through **Marrfa**.\n\n"
                "To recommend the best option for you, tell me:\n"
                "1) Budget (e.g., under 1M AED / around 5M AED)\n"
                "2) Property type (villa / apartment / townhouse)\n"
                "3) Preferred area (Dubai Marina, Business Bay, JVC, etc.)\n"
                "4) Bedrooms (optional)\n\n"
                "Then I’ll suggest the best matching listings and guide you like an agent would.\n\n"
                "Tip: When choosing any agency, check RERA registration, area specialization, and recent deal history."
            ),
            "properties": [],
            "properties_full": [],
            "total": 0,
            "filters": {"intent": "PROPERTY", "agency_recommendation": True},
        }

    filters = parse_query_to_filters(query_text)

    # Currency handling
    if filters.get("foreign_currency"):
        amount = filters.get("amount")
        currency = filters.get("currency")

        if currency == "USD":
            aed_amount = float(amount) * 3.67
            return {
                "reply": (
                    f"⚠️ **Currency Conversion Required**\n\n"
                    f"You specified {amount} {currency}. "
                    f"Approximately {amount} {currency} ≈ **{aed_amount:,.0f} AED**.\n\n"
                    f"Please search using AED amounts."
                ),
                "properties": [],
                "properties_full": [],
                "total": 0,
                "filters": {**filters, "intent": "PROPERTY", "currency_warning": True},
            }

    filters.setdefault("search_query", "dubai")
    filters.update({
        "page": 1,
        "per_page": 15,
    })

    try:
        # ✅ RAW data (ALL fields)
        raw_full = search_properties_raw(filters)

        # ✅ Ensure properties_full is a LIST (items) not a wrapper dict
        if isinstance(raw_full, dict) and "items" in raw_full:
            raw_items = raw_full.get("items") or []
        elif isinstance(raw_full, list):
            raw_items = raw_full
        else:
            raw_items = []

        # ✅ Normalized data (chatbot cards)
        raw_props = search_properties(filters)  # expected list[dict]
        props_models = [Property(**p) for p in raw_props]

        total = len(props_models)
        show_count = min(15, total)

        reply = generate_professional_reply(query_text, filters, props_models, total, show_count)

        if total == 0:
            reply = (
                "Sorry, I couldn't find any properties matching your criteria. 😔\n\n"
                "Try adjusting your search filters like location, budget, or property type."
            )

        # ============================================================
        # ✅ Critical FIX: ChatResponse expects dicts, not Property objects
        # ============================================================
        props_dicts = [p.model_dump() for p in props_models[:show_count]]

        return {
            "reply": reply,
            "properties": props_dicts,             # ✅ dicts (fixes Pydantic error)
            "properties_full": raw_items[:show_count],  # ✅ list of raw property dicts
            "total": total,
            "filters": {**filters, "intent": "PROPERTY"},
        }

    except Exception as e:
        return {
            "reply": (
                "I'm having trouble searching for properties right now. Please try again later."
            ),
            "properties": [],
            "properties_full": [],
            "total": 0,
            "filters": {"intent": "PROPERTY", "error": str(e)},
        }
