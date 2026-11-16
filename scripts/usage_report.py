"""Token, search and cost report for adk web sessions (read-only, no LLM).

Reads dossier_agent/.adk/session.db (written by `adk web`) and sums the
usage_metadata of every model call per agent, plus the real Google Search
queries from grounding_metadata.web_search_queries.

    python -m scripts.usage_report            # the latest session
    python -m scripts.usage_report -n 3       # the 3 latest sessions
    python -m scripts.usage_report --session <id>

Prices per model_version reported by the API (dossier_agent/pricing.py:
Gemini API or Vertex AI table, from GOOGLE_GENAI_USE_VERTEXAI). Output price
includes thinking tokens. Google Search grounding: 5,000 free requests per
month, then $14 per 1,000. Update pricing.py when the model or the prices change.
"""
import argparse
import json
import pathlib
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

DB = pathlib.Path(__file__).resolve().parent.parent / "dossier_agent" / ".adk" / "session.db"

from dossier_agent.pricing import (  # noqa: E402
    API_PRICES, PRICE_SEARCH_PER_1000, VERTEX_PRICES, price_entry, price_table,
)


def _entry(model: str) -> tuple[float, float, str]:
    """Price of the backend in use; a model known only to the other backend
    (an old session, or --price-as) is priced from that backend's table."""
    if model in price_table():
        return price_entry(model)
    for vertex in (False, True):
        if model in price_table(vertex):
            return price_entry(model, vertex)
    return price_entry(model)


def load_sessions(db: pathlib.Path, n: int, session: str | None) -> list[tuple[str, float]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    if session:
        rows = con.execute("select session_id, min(timestamp) from events where session_id=? "
                           "group by session_id", (session,)).fetchall()
    else:
        rows = con.execute("select session_id, min(timestamp) from events group by session_id "
                           "order by min(timestamp) desc limit ?", (n,)).fetchall()
    con.close()
    return rows


def session_usage(db: pathlib.Path, session_id: str, price_as: str | None = None) -> dict:
    """Per-agent totals: calls, input, output, thinking tokens, searches."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    agents = defaultdict(lambda: {"calls": 0, "input": 0, "output": 0, "thinking": 0,
                                  "searches": 0, "grounded": 0, "usd": 0.0, "models": set()})
    for (data,) in con.execute("select event_data from events where session_id=? "
                               "order by timestamp", (session_id,)):
        event = json.loads(data)
        author = event.get("author") or "?"
        usage = event.get("usage_metadata")
        if usage:
            a = agents[author]
            a["calls"] += 1
            a["input"] += usage.get("prompt_token_count") or 0
            a["output"] += usage.get("candidates_token_count") or 0
            a["thinking"] += usage.get("thoughts_token_count") or 0
            model = price_as or event.get("model_version") or "unknown"
            a["models"].add(model)
            price_in, price_out, _ = _entry(model)
            a["usd"] += ((usage.get("prompt_token_count") or 0) * price_in
                         + ((usage.get("candidates_token_count") or 0)
                            + (usage.get("thoughts_token_count") or 0)) * price_out) / 1e6
        grounding = event.get("grounding_metadata")
        if grounding is not None:
            agents[author]["grounded"] += 1
            agents[author]["searches"] += len(grounding.get("web_search_queries") or [])
    con.close()
    return {k: v for k, v in agents.items() if v["calls"] or v["searches"]}


def cost(a: dict) -> float:
    return a["usd"]


def report(session_id: str, started: float, agents: dict) -> str:
    when = datetime.fromtimestamp(started, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"session {session_id}  ({when})",
             f"{'agent':<12}{'calls':>6}{'input':>9}{'output':>8}{'thinking':>9}{'search':>7}{'tokens $':>10}"]
    total = defaultdict(int)
    unknown = False
    for name, a in sorted(agents.items(), key=lambda kv: -cost(kv[1])):
        # the researcher searched but the event has no grounding_metadata: count unknown
        no_data = name == "researcher" and a["calls"] and not a["grounded"]
        unknown |= bool(no_data)
        searches = "?" if no_data else a["searches"]
        lines.append(f"{name:<12}{a['calls']:>6}{a['input']:>9}{a['output']:>8}{a['thinking']:>9}"
                     f"{searches:>7}{cost(a):>10.4f}")
        for k, v in a.items():
            if k == "models":
                total.setdefault("models_set", set()).update(v)
            else:
                total[k] += v
    tokens_usd = total["usd"]
    models = sorted(total.get("models_set", set()))
    lines.append("models: " + ", ".join(
        f"{m} (${_entry(m)[0]}/${_entry(m)[1]} per 1M; {_entry(m)[2]})"
        for m in models))
    search_usd = total["searches"] * PRICE_SEARCH_PER_1000 / 1000
    lines.insert(-1, f"{'TOTAL':<12}{total['calls']:>6}{total['input']:>9}{total['output']:>8}"
                 f"{total['thinking']:>9}{total['searches']:>7}{tokens_usd:>10.4f}")
    if unknown:
        lines.append("searches: no grounding_metadata saved for the researcher, real count unknown")
    lines.append(f"cost: tokens ${tokens_usd:.4f}; searches ${search_usd:.4f} if paid "
                 f"($0 within the free 5,000/month); total ${tokens_usd + search_usd:.4f} "
                 f"(limit $0.40)")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", type=int, default=1, help="number of latest sessions")
    parser.add_argument("--session", help="one session id")
    parser.add_argument("--db", type=pathlib.Path, default=DB)
    parser.add_argument("--price-as", choices=sorted(set(API_PRICES) | set(VERTEX_PRICES)),
                        help="price every call as this model (what-if)")
    args = parser.parse_args()
    for session_id, started in load_sessions(args.db, args.n, args.session):
        print(report(session_id, started, session_usage(args.db, session_id, args.price_as)))
        print()


if __name__ == "__main__":
    main()
