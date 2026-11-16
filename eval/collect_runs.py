"""Collect the end-to-end eval runs (PAID: one dossier each, about $0.10-0.15).

Runs every company of eval/data/companies.json through the same run_agent as
the service, in a separate storage (eval/storage), and copies each run to
eval/runs/<id>/:
  result.json, report.md, trace.json   the run output (as in the outbox)
  calls.json                           request, writer tool calls with their
                                       arguments and answers, agent timeline
  memory.json                          the memory record saved by the run

The metrics are computed later and for free by eval/eval_components.py.

Run from the repo root:
  python -m eval.collect_runs                 # all companies
  python -m eval.collect_runs --only zorblax  # some of them
"""
import argparse
import asyncio
import json
import os
import pathlib
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
STORAGE = EVAL_DIR / "storage"            # not in git: rebuilt by every collection
RUNS_DIR = EVAL_DIR / "runs"
SEED_DIR = EVAL_DIR / "data" / "seed"
COMPANIES = EVAL_DIR / "data" / "companies.json"
CASES_FILE = ROOT / "demo-data" / "config" / "seller_cases.md"

# before the agent is imported: storage and MODEL are read from the environment
os.environ["STORAGE_ROOT"] = str(STORAGE)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "dossier_agent" / ".env")

from dossier_agent.limits import Limits  # noqa: E402
from dossier_agent.memory import DOSSIER_DIR  # noqa: E402
from service.runner import run_agent  # noqa: E402

WRITER_TOOLS = ("load_seller_cases", "check_dossier_format")


def load_companies(only: list[str] | None = None) -> list[dict]:
    companies = json.loads(COMPANIES.read_text(encoding="utf-8"))["companies"]
    if only:
        unknown = set(only) - {c["id"] for c in companies}
        if unknown:
            sys.exit(f"unknown company id(s): {', '.join(sorted(unknown))}")
        companies = [c for c in companies if c["id"] in only]
    return companies


def prepare_storage(companies: list[dict]) -> None:
    """Seller file, and for each domain either the seed memory or none."""
    (STORAGE / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy(CASES_FILE, STORAGE / "config" / "seller_cases.md")
    memory_dir = STORAGE / DOSSIER_DIR
    memory_dir.mkdir(parents=True, exist_ok=True)
    for company in companies:
        domain = company["request"]["domain"]
        target = memory_dir / f"{domain}.json"
        target.unlink(missing_ok=True)
        if company.get("seed_memory"):
            shutil.copy(SEED_DIR / DOSSIER_DIR / f"{domain}.json", target)


def _short_response(name: str, response) -> dict:
    response = response if isinstance(response, dict) else {}
    if name == "load_seller_cases":
        return {"case_ids": [c.get("id") for c in response.get("cases") or [] if isinstance(c, dict)]}
    if name == "check_dossier_format":
        return {"success": response.get("success"), "message": response.get("message")}
    return {}


class Recorder:
    """on_event callback: writer tool calls and the timeline of agents."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.calls: list[dict] = []
        self.timeline: list[dict] = []

    def __call__(self, event) -> None:
        t = round(time.monotonic() - self.started, 1)
        author = event.author or ""
        if not self.timeline or self.timeline[-1]["author"] != author:
            self.timeline.append({"t": t, "author": author})
        for call in event.get_function_calls() or []:
            if call.name in WRITER_TOOLS:
                args = dict(call.args or {})
                if call.name == "check_dossier_format":
                    args = {"md_words": len(str(args.get("md") or "").split())}
                self.calls.append({"t": t, "type": "call", "name": call.name, "args": args})
        for response in event.get_function_responses() or []:
            if response.name in WRITER_TOOLS:
                self.calls.append({"t": t, "type": "response", "name": response.name,
                                   **_short_response(response.name, response.response)})


async def collect_one(company: dict, limits: Limits) -> dict:
    recorder = Recorder()
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{company['id']}] started")
    outcome = await run_agent(
        json.dumps(company["request"]), run_id=run_id, started_at=started_at, trigger="manual",
        timeout_seconds=limits.seconds + 60, max_llm_calls=limits.max_llm_calls,
        on_event=recorder)

    target = RUNS_DIR / company["id"]
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    prefix = outcome.state.get("outbox_prefix")
    if prefix:
        for name in ("result.json", "report.md", "trace.json"):
            source = STORAGE / prefix / name
            if source.exists():
                shutil.copy(source, target / name)
    memory = STORAGE / DOSSIER_DIR / f"{company['request']['domain']}.json"
    if memory.exists():
        shutil.copy(memory, target / "memory.json")
    (target / "calls.json").write_text(json.dumps({
        "company_id": company["id"],
        "request": company["request"],
        "run_id": run_id,
        "error": outcome.error,
        "input_error": outcome.state.get("input_error") or None,
        "calls": recorder.calls,
        "timeline": recorder.timeline,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    result = outcome.state.get("result") or {}
    usage = result.get("usage") or {}
    summary = {"id": company["id"], "status": result.get("status", "no result"),
               "iterations": (result.get("data") or {}).get("iterations"),
               "cost_usd": usage.get("cost_usd"), "seconds": usage.get("elapsed_seconds"),
               "error": outcome.error}
    print(f"[{company['id']}] {json.dumps(summary)}")
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", help="company ids from eval/data/companies.json")
    parser.add_argument("--parallel", type=int, default=2, help="runs at the same time")
    args = parser.parse_args()

    companies = load_companies(args.only)
    prepare_storage(companies)
    limits = Limits.from_env()
    semaphore = asyncio.Semaphore(max(args.parallel, 1))

    async def guarded(company):
        async with semaphore:
            return await collect_one(company, limits)

    summaries = await asyncio.gather(*(guarded(c) for c in companies))
    total = sum(s["cost_usd"] or 0 for s in summaries)
    print(f"\n{len(summaries)} runs, total ${total:.3f}. Next: python -m eval.eval_components")


if __name__ == "__main__":
    asyncio.run(main())
