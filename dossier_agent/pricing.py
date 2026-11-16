import os

# model_version -> (input $/1M, output+thinking $/1M, source).
# The API reports the model that actually answered (model_version): a request
# for gemini-3.7-flash through the Gemini API is answered by gemini-3.8-flash.
API_PRICES = {
    "gemini-3.8-flash": (0.75, 3.75, "Gemini API paid tier, aistudio.google.com/docs/pricing, "
                                      "2026-11-11; $1.50/$7.50 from 2027-01-01"),
    "gemini-3.6-flash": (0.75, 3.75, "Gemini API paid tier, aistudio.google.com/docs/pricing, "
                                      "2026-11-11; $1.50/$7.50 from 2027-01-01"),
}
VERTEX_PRICES = {
    "gemini-3.5-flash": (1.50, 9.00, "Vertex AI, location global, official "
                                      "cloud.google.com/vertex-ai/generative-ai/pricing, 2026-11-09 "
                                      "(non-global: $1.65/$9.90)"),
    "gemini-3.7-flash": (0.75, 3.75, "Vertex AI Model Garden description, 2026-11-09: introductory "
                                      "price through the end of 2026; NOT checked on the pricing page"),
}
# a model missing from the table is priced as the most expensive known one,
# so the cost hard stop never under-counts
FALLBACK_PRICE = max((p for t in (API_PRICES, VERTEX_PRICES) for p in t.values()),
                     key=lambda p: p[1])
PRICE_SEARCH_PER_1000 = 14.0       # Google Search grounding after the free 5,000/month


def use_vertex() -> bool:
    """Same rule as google-genai: GOOGLE_GENAI_USE_ENTERPRISE wins over
    GOOGLE_GENAI_USE_VERTEXAI; unset = Gemini API (API key)."""
    for name in ("GOOGLE_GENAI_USE_ENTERPRISE", "GOOGLE_GENAI_USE_VERTEXAI"):
        value = os.environ.get(name)
        if value is not None:
            return value.lower() in ("true", "1")
    return False


def price_table(vertex: bool | None = None) -> dict:
    """Prices of the backend in use (or the one asked for)."""
    return VERTEX_PRICES if (use_vertex() if vertex is None else vertex) else API_PRICES


def price_entry(model: str | None, vertex: bool | None = None) -> tuple[float, float, str]:
    return price_table(vertex).get(model or "", FALLBACK_PRICE[:2] + (
        f"unknown model {model!r}: priced as the most expensive known model",))


def price_for(model: str | None, vertex: bool | None = None) -> tuple[float, float]:
    price_in, price_out, _ = price_entry(model, vertex)
    return price_in, price_out


def token_cost(model: str | None, input_tokens: int, output_tokens: int,
               thinking_tokens: int, vertex: bool | None = None) -> float:
    price_in, price_out = price_for(model, vertex)
    return (input_tokens * price_in + (output_tokens + thinking_tokens) * price_out) / 1e6
