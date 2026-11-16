import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .pricing import token_cost

_REPORTED_SEARCHES_RE = re.compile(r"Searches performed:\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class Limits:
    max_llm_calls: int = 50
    cost_usd: float = 0.40
    seconds: int = 540
    max_searches: int = 15
    soft_cost_share: float = 0.7

    @classmethod
    def from_env(cls) -> "Limits":
        return cls(
            max_llm_calls=int(os.getenv("MAX_LLM_CALLS", cls.max_llm_calls)),
            cost_usd=float(os.getenv("COST_LIMIT_USD", cls.cost_usd)),
            seconds=int(os.getenv("TIME_LIMIT_SECONDS", cls.seconds)),
            max_searches=int(os.getenv("MAX_SEARCHES", cls.max_searches)),
            soft_cost_share=float(os.getenv("SOFT_BUDGET_SHARE", cls.soft_cost_share)),
        )


def new_usage() -> dict:
    return {
        "llm_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "thinking_tokens": 0,
        "searches": 0,
        "searches_source": "none",   # grounding | model_reported | mixed | none
        "cost_usd": 0.0,             # tokens only; searches are free within 5,000/month
        "hard_stop": None,           # llm_calls | cost | time
        "research_stop": None,       # searches | budget
    }


def reported_searches(text: str) -> int | None:
    """The researcher's own 'Searches performed: N' line (cumulative over
    iterations, because it keeps its previous notes)."""
    m = _REPORTED_SEARCHES_RE.search(text or "")
    return int(m.group(1)) if m else None


def add_response(usage: dict, *, model: str | None, input_tokens: int, output_tokens: int,
                 thinking_tokens: int, grounding_queries: list | None = None,
                 response_text: str = "", is_researcher: bool = False) -> dict:
    """Return a new usage dict with one model response added.

    Searches: the real queries from grounding_metadata when present;
    otherwise the number the researcher reported itself (cumulative, so it
    raises the total to at least that number)."""
    u = dict(usage)
    u["input_tokens"] += input_tokens
    u["output_tokens"] += output_tokens
    u["thinking_tokens"] += thinking_tokens
    u["cost_usd"] = round(u["cost_usd"] + token_cost(model, input_tokens, output_tokens,
                                                     thinking_tokens), 6)
    if is_researcher:
        if grounding_queries is not None:
            u["searches"] += len(grounding_queries)
            source = "grounding"
        else:
            reported = reported_searches(response_text)
            if reported is None:
                return u
            u["searches"] = max(u["searches"], reported)
            source = "model_reported"
        previous = u["searches_source"]
        u["searches_source"] = source if previous in ("none", source) else "mixed"
    return u


def elapsed_seconds(started_at: str | None, now: datetime | None = None) -> float:
    if not started_at:
        return 0.0
    try:
        start = datetime.fromisoformat(started_at)
    except ValueError:
        return 0.0
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    # never negative, even if the clock that wrote started_at is ahead
    return max(0.0, ((now or datetime.now(timezone.utc)) - start).total_seconds())


def hard_stop_reason(usage: dict, limits: Limits, elapsed: float) -> str | None:
    """Checked before every model call: the next call is not allowed if a
    limit is already reached."""
    if usage["llm_calls"] >= limits.max_llm_calls:
        return "llm_calls"
    if usage["cost_usd"] >= limits.cost_usd:
        return "cost"
    if elapsed >= limits.seconds:
        return "time"
    return None


def research_stop_reason(usage: dict, limits: Limits) -> str | None:
    """Checked after each research iteration: no new iteration starts."""
    if usage["searches"] >= limits.max_searches:
        return "searches"
    if usage["cost_usd"] >= limits.cost_usd * limits.soft_cost_share:
        return "budget"
    return None


STOP_MESSAGES = {
    "llm_calls": "model call limit reached",
    "cost": "cost limit reached",
    "time": "time limit reached",
    "searches": "search limit reached",
    "budget": "budget share for research used up, the rest is kept for the writer",
}


def describe(reason: str, limits: Limits) -> str:
    detail = {
        "llm_calls": f"{limits.max_llm_calls} calls",
        "cost": f"${limits.cost_usd:.2f}",
        "time": f"{limits.seconds} s",
        "searches": f"{limits.max_searches} searches",
        "budget": f"{int(limits.soft_cost_share * 100)}% of ${limits.cost_usd:.2f}",
    }[reason]
    return f"{STOP_MESSAGES[reason]} ({detail})"
