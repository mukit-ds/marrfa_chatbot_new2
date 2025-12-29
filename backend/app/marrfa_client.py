# backend/app/marrfa_client.py
import json
import time
import hashlib
import requests
from typing import Dict, Any, List, Optional, Tuple
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://apiv2.marrfa.com/properties"

# --- Global session for connection reuse ---
_http_session = None


def get_http_session() -> requests.Session:
    """Get or create a requests session with retry strategy."""
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()

        retry_strategy = Retry(
            total=2,  # keep small for speed
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )

        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20,
            pool_block=False
        )

        _http_session.mount("http://", adapter)
        _http_session.mount("https://", adapter)

    return _http_session


# --- Simple caching for identical requests ---
_property_cache: Dict[str, Tuple[float, List[dict]]] = {}
_property_cache_raw: Dict[str, Tuple[float, List[dict]]] = {}
_CACHE_TIMEOUT = 60  # 1 minute cache


def clear_old_cache() -> None:
    """Clear old cache entries."""
    current_time = time.time()

    # normalized cache
    keys_to_delete = []
    for key, (timestamp, _) in _property_cache.items():
        if current_time - timestamp > _CACHE_TIMEOUT:
            keys_to_delete.append(key)
    for key in keys_to_delete:
        del _property_cache[key]

    # raw cache
    keys_to_delete = []
    for key, (timestamp, _) in _property_cache_raw.items():
        if current_time - timestamp > _CACHE_TIMEOUT:
            keys_to_delete.append(key)
    for key in keys_to_delete:
        del _property_cache_raw[key]


def get_cache_key(filters: Dict[str, Any]) -> str:
    """Create a hash key for caching."""
    sorted_filters = json.dumps(
        {k: filters[k] for k in sorted(filters.keys()) if filters[k] is not None},
        sort_keys=True
    )
    return hashlib.md5(sorted_filters.encode("utf-8")).hexdigest()


def _maybe_csv(value: Any) -> Any:
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(v) for v in value)
    return value


def _extract_url(x: Any) -> Optional[str]:
    """
    Marrfa image fields can be:
    - plain string URL
    - JSON string like '{"url":"https://.."}'
    - dict like {"url":"https://..."}
    - list of strings
    - list of dicts [{"url":"https://..."}]
    """
    if not x:
        return None

    # string
    if isinstance(x, str):
        s = x.strip()
        if s.startswith(("http://", "https://")):
            return s

        # sometimes it's a JSON string containing url
        if s.startswith("{") and ("url" in s or "http" in s):
            try:
                obj = json.loads(s)
                if isinstance(obj, dict):
                    for key in ["url", "image", "src"]:
                        v = obj.get(key)
                        if isinstance(v, str) and v.startswith(("http://", "https://")):
                            return v
            except Exception:
                return None

        return None

    # dict
    if isinstance(x, dict):
        for key in ["url", "image", "src"]:
            v = x.get(key)
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                return v
        return None

    # list
    if isinstance(x, list) and x:
        return _extract_url(x[0])

    return None


def _build_params(filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build request params (keep it fast and stable).
    """
    params: Dict[str, Any] = {}

    def set_if_present(key: str):
        if key in filters and filters[key] is not None:
            params[key] = _maybe_csv(filters[key])

    # essential keys
    essential_keys = [
        "search_query",
        "unit_types",
        "unit_bedrooms",
        "unit_price_from",
        "unit_price_to",
        "page",
        "per_page",
    ]

    for k in essential_keys:
        set_if_present(k)

    # keep any extra filters too (safe)
    for k, v in filters.items():
        if k not in params and v is not None:
            params[k] = _maybe_csv(v)

    return params


def _fetch_items(filters: Dict[str, Any]) -> List[dict]:
    """
    Fetch RAW items from Marrfa API (no trimming).
    """
    if len(_property_cache_raw) > 200:
        clear_old_cache()

    cache_key = get_cache_key(filters)
    if cache_key in _property_cache_raw:
        ts, cached = _property_cache_raw[cache_key]
        if time.time() - ts < _CACHE_TIMEOUT:
            return cached

    params = _build_params(filters)

    try:
        session = get_http_session()
        resp = session.get(BASE_URL, params=params, timeout=12)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[marrfa_client] Error fetching RAW properties: {e}")
        return []

    items = data.get("items") or data.get("data") or []
    if not isinstance(items, list):
        items = []

    _property_cache_raw[cache_key] = (time.time(), items)
    return items


def search_properties_raw(filters: Dict[str, Any]) -> List[dict]:
    """
    ✅ Returns RAW Marrfa API objects (ALL fields).
    Use this for `properties_full`.
    """
    return _fetch_items(filters)


def search_properties(filters: Dict[str, Any]) -> List[dict]:
    """
    Returns NORMALIZED properties for Streamlit/chatbot cards:
    id, title, location, price_from, price_to, currency,
    completion_year, cover_image, images, listing_url

    ✅ Backward-compatible: keeps your current UI working.
    """
    if len(_property_cache) > 200:
        clear_old_cache()

    cache_key = get_cache_key(filters)
    if cache_key in _property_cache:
        ts, cached = _property_cache[cache_key]
        if time.time() - ts < _CACHE_TIMEOUT:
            return cached

    items = _fetch_items(filters)

    properties: List[dict] = []
    for p in items:
        try:
            property_id = p.get("id")

            # Prices
            price_from = (
                p.get("min_price_aed")
                or p.get("min_price")
                or p.get("price_from")
                or None
            )
            price_to = (
                p.get("max_price_aed")
                or p.get("max_price")
                or p.get("price_to")
                or None
            )

            # Completion year
            completion_year = None
            dt = p.get("completion_datetime") or p.get("completion_date") or ""
            if isinstance(dt, str) and len(dt) >= 4:
                completion_year = dt[:4]
            if not completion_year:
                completion_year = str(p.get("completion_year") or "")

            # Cover image
            cover_url = None
            for key in ["cover_image", "cover_image_url", "thumbnail", "thumbnail_url"]:
                if key in p and p[key]:
                    url = _extract_url(p[key])
                    if url:
                        cover_url = url
                        break

            # Listing URL
            listing_url = None
            if property_id is not None:
                listing_url = f"https://www.marrfa.com/propertylisting/{property_id}"

            location = p.get("area") or p.get("location") or "Dubai"
            currency = p.get("price_currency") or p.get("currency") or "AED"

            properties.append(
                {
                    "id": property_id,
                    "title": p.get("name") or p.get("title") or "Untitled property",
                    "location": location,
                    "price_from": price_from,
                    "price_to": price_to,
                    "currency": currency,
                    "completion_year": completion_year if completion_year else None,
                    "cover_image": cover_url,
                    "images": None,  # keep lightweight; full images in raw
                    "listing_url": listing_url,
                }
            )
        except Exception:
            # skip bad records safely
            continue

    _property_cache[cache_key] = (time.time(), properties)
    return properties


def quick_search(
    location: str = "dubai",
    property_type: Optional[str] = None,
    bedrooms: Optional[str] = None,
    max_price: Optional[int] = None
) -> List[dict]:
    """
    Quick helper for simple queries (returns normalized objects).
    """
    filters: Dict[str, Any] = {"search_query": location}

    if property_type:
        filters["unit_types"] = [property_type]
    if bedrooms:
        filters["unit_bedrooms"] = bedrooms
    if max_price:
        filters["unit_price_to"] = max_price

    filters["page"] = 1
    filters["per_page"] = 10

    return search_properties(filters)
