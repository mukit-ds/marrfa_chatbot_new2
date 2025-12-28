
from typing import Dict, List, Any
from .schemas import Property
from .parser import parse_query_to_filters
from .marrfa_client import search_properties
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

    # If no properties found, return None
    if total == 0:
        return None

    context = analyze_query_context(query)

    # Extract key filters for personalized response
    location = filters.get("search_query", "Dubai").title()
    bedrooms = filters.get("unit_bedrooms", "")
    property_type = filters.get("unit_types", [])
    price_from = filters.get("unit_price_from")
    price_to = filters.get("unit_price_to")
    developer = filters.get("developer_name_nlp", [])

    query_lower = query.lower()

    

    # Special handling for specific query patterns

    # 1. "How many properties does Marrfa have?"
    if ("how many" in query_lower and any(word in query_lower for word in ["property", "properties"]) and
            any(word in query_lower for word in ["marrfa", "marfa"])):
        if total > 0:
            if show_count >= total:
                return f"Marrfa currently has {total} properties listed in {location}. Here are all their premium offerings:"
            else:
                return f"Marrfa currently has {total} properties listed in {location}. Here are the top {show_count} of their premium offerings:"

    # 2. For queries asking for all/maximum properties
    if context["mentions_all"]:
        if show_count >= total:
            return f"Here are all {total} properties matching your criteria in {location}:"
        else:
            return f"Here are the maximum {show_count} properties I can display from the {total} available in {location}:"

    # 3. "Show me properties in [Location]"
    if ("show me" in query_lower and "properties" in query_lower):
        if location.lower() != "dubai":
            if show_count >= total:
                return f"Here are all the available properties in {location}, showcasing premium real estate in this sought-after area:"
            else:
                return f"Here are {show_count} of the available properties in {location}, showcasing premium real estate in this sought-after area:"

    # 4. "Could you recommend some villas?"
    if context["is_recommendation"] and property_type:
        type_name = property_type[0].lower() if property_type else "properties"
        if show_count >= total:
            return f"Based on market trends and availability, here are all {total} {type_name} in {location}:"
        else:
            return f"Based on market trends and availability, here are my top {show_count} recommendations for {type_name} in {location}:"

    # 5. "Show me the best property Marrfa has"
    if ("best" in query_lower and context["mentions_marrfa"]):
        if show_count >= total:
            return f"Here are all of Marrfa's premium properties, showcasing their commitment to excellence in {location} real estate:"
        else:
            return f"Here are Marrfa's top {show_count} premium properties, showcasing their commitment to excellence in {location} real estate:"

    # 6. General property listings
    if total == 0:
        if context["mentions_marrfa"]:
            return f"Currently, Marrfa doesn't have properties matching your specific criteria in {location}. However, their portfolio in this area is regularly updated with new premium developments."
        elif price_from or price_to:
            return f"Properties within your specified price range are currently limited in {location}. The market in this area features premium real estate with competitive pricing."
        elif bedrooms:
            return f"While {bedrooms} properties are in high demand, availability in {location} is currently limited. Consider expanding your search criteria."
        else:
            return f"The {location} property market is dynamic. While no listings match your current criteria, new premium properties are regularly added to the market."

    # 7. For specific developer queries
    if developer and context["mentions_marrfa"]:
        dev_name = developer[0] if developer else "Marrfa"
        if show_count >= total:
            return f"{dev_name}'s complete portfolio in {location} includes all {total} premium properties. Here are their offerings:"
        else:
            return f"{dev_name}'s current portfolio in {location} includes {total} premium properties. Here are their top {show_count} standout offerings:"

    # 8. For price-specific queries
    if price_from or price_to:
        price_context = ""
        if price_from and price_to:
            price_context = f" within the AED {price_from:,} - {price_to:,} range"
        elif price_from:
            price_context = f" starting from AED {price_from:,}"
        elif price_to:
            price_context = f" up to AED {price_to:,}"

        if show_count >= total:
            return f"The {location} market offers all {total} premium properties{price_context}. Here are the listings:"
        else:
            return f"The {location} market offers {total} premium properties{price_context}. Here are the top {show_count} selections:"

    # 9. For bedroom-specific queries
    if bedrooms:
        if "studio" in bedrooms.lower():
            if show_count >= total:
                return f"Here are all {total} studio apartments in {location}, excellent investment opportunities:"
            else:
                return f"Studio apartments in {location} are excellent investment opportunities. Here are {show_count} premium studio options:"
        else:
            if show_count >= total:
                return f"Here are all {total} premium {bedrooms.lower()} properties in {location}:"
            else:
                return f"{location} offers {total} premium {bedrooms.lower()} properties. Here are the top {show_count} standout options:"

    # 10. For property type-specific queries
    if property_type:
        type_name = property_type[0]
        if show_count >= total:
            return f"The {location} {type_name.lower()} market features all {total} premium options. Here are the listings:"
        else:
            return f"The {location} {type_name.lower()} market features {total} premium options. Here are the top {show_count} listings:"

    # 11. Context-based general responses
    if context["is_question"]:
        if context["is_polite"]:
            if show_count >= total:
                return f"Certainly. The {location} property market currently features all {total} premium listings:"
            else:
                return f"Certainly. The {location} property market currently features {total} premium listings. Here are the top {show_count} most noteworthy options:"
        else:
            if show_count >= total:
                return f"In {location}, here are all {total} premium properties available:"
            else:
                return f"In {location}, there are {total} premium properties available. Here are the top {show_count} investment opportunities:"

    elif context["is_direct"]:
        if show_count >= total:
            return f"Here are all {total} properties in {location}, selected for their value and market position:"
        else:
            return f"Here are {show_count} premium properties in {location}, selected for their value and market position:"

    elif context["is_recommendation"]:
        if show_count >= total:
            return f"Based on current market analysis, here are all {total} properties in {location}:"
        else:
            return f"Based on current market analysis, I recommend these {show_count} premium properties in {location}:"

    elif context["is_best_related"]:
        if show_count >= total:
            return f"Here are all the best properties in {location}, selected for their premium features and market appeal:"
        else:
            return f"Here are the {show_count} best properties in {location}, selected for their premium features and market appeal:"

    elif context["mentions_marrfa"]:
        if total <= 3:
            return f"Marrfa offers {total} exclusive properties in {location}, each representing premium real estate opportunities:"
        else:
            if show_count >= total:
                return f"Marrfa's complete portfolio in {location} includes all {total} premium properties:"
            else:
                return f"Marrfa's portfolio in {location} includes {total} premium properties. Here are their top {show_count} featured listings:"

    elif context["is_broad_query"]:
        if show_count >= total:
            return f"The {location} property market is vibrant with all {total} premium options:"
        else:
            return f"The {location} property market is vibrant with {total} premium options. Here are the top {show_count} standout listings:"

    # Default professional response
    if total <= 5:
        if show_count >= total:
            return f"Here are all {total} premium properties in {location}, representing excellent opportunities in the local market:"
        else:
            return f"Currently, {location} features {total} premium properties. Here are the top {show_count} representing excellent opportunities:"
    elif total <= 15:
        if show_count >= total:
            return f"Here are all {total} premium options in the {location} property market:"
        else:
            return f"The {location} property market offers {total} premium options. Here are the top {show_count} most compelling listings:"
    else:
        if show_count >= total:
            return f"Here are all {total} premium properties available in {location}, presenting diverse real estate opportunities:"
        else:
            return f"With {total} premium properties available, {location} presents diverse real estate opportunities. Here are the top {show_count} selections:"


def handle_property_query(query_text: str) -> Dict[str, Any]:
    """
    Handle property search queries.
    """
    filters = parse_query_to_filters(query_text)

    # Check for foreign currency first
    if filters.get("foreign_currency"):
        amount = filters.get("amount")
        currency = filters.get("currency")

        if currency == "USD":
            aed_amount = float(amount) * 3.67
            return {
                "reply": f"⚠️ **Currency Conversion Required**\n\nYou specified {amount} {currency}. For accurate property search in Dubai, please convert to AED (United Arab Emirates Dirhams).\n\nApproximately {amount} {currency} ≈ **{aed_amount:,.0f} AED**\n\nPlease search using AED amounts for best results.",
                "properties": [],
                "total": 0,
                "filters": {**filters, "intent": "PROPERTY", "currency_warning": True},
            }
        else:
            return {
                "reply": f"⚠️ **Currency Conversion Required**\n\nYou specified {amount} {currency}. For property search in Dubai, please use AED (United Arab Emirates Dirhams).\n\nPlease convert {amount} {currency} to AED and search again for accurate results.",
                "properties": [],
                "total": 0,
                "filters": {**filters, "intent": "PROPERTY", "currency_warning": True},
            }

    filters.setdefault("search_query", "dubai")
    filters.update({
        "page": 1,
        "per_page": 15,
    })

    try:
        raw_props = search_properties(filters)
        props = [Property(**p) for p in raw_props]
        total = len(props)
        show_count = min(10, total)

        # Generate reply
        reply = generate_professional_reply(query_text, filters, props, total, show_count)

        # If generate_professional_reply returns None (no properties found), use gentle message
        if total == 0:
            reply = "Sorry, I couldn't find any properties matching your criteria. 😔\n\nTry adjusting your search filters like location, budget, or property type."

        return {
        "reply": reply,
        "properties": props[:show_count],
        "properties_full": raw_props,  # ✅ ADD THIS
        "total": total,
        "filters": {**filters, "intent": "PROPERTY"},
}


    except Exception as e:
        # If search fails, use gentle message
        error_reply = "Sorry, I couldn't find any properties matching your criteria. 😔\n\nTry adjusting your search filters like location, budget, or property type."

        return {
            "reply": error_reply,
            "properties": [],
            "total": 0,
            "filters": {"intent": "PROPERTY", "error": str(e)},
        }
