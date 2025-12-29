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
    bedrooms = filters.get("unit_bedrooms", "")
    property_type = filters.get("unit_types", [])
    price_from = filters.get("unit_price_from")
    price_to = filters.get("unit_price_to")
    developer = filters.get("developer_name_nlp", [])

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

        # ✅ Normalized data (chatbot cards)
        raw_props = search_properties(filters)
        props = [Property(**p) for p in raw_props]

        total = len(props)
        show_count = min(10, total)

        reply = generate_professional_reply(query_text, filters, props, total, show_count)

        if total == 0:
            reply = (
                "Sorry, I couldn't find any properties matching your criteria. 😔\n\n"
                "Try adjusting your search filters like location, budget, or property type."
            )

        return {
            "reply": reply,
            "properties": props[:show_count],     # chatbot view
            "properties_full": raw_full,           # ✅ RAW Marrfa API objects
            "total": total,
            "filters": {**filters, "intent": "PROPERTY"},
        }

    except Exception as e:
        return {
            "reply": (
                "Sorry, I couldn't find any properties matching your criteria. 😔\n\n"
                "Try adjusting your search filters like location, budget, or property type."
            ),
            "properties": [],
            "properties_full": [],
            "total": 0,
            "filters": {"intent": "PROPERTY", "error": str(e)},
        }
