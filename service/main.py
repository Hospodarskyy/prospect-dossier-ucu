"""HTTP service: POST /run processes at most one request from inbox/.

One call:
1. stale files in processing/ (a cut-off run) count as a failed attempt;
2. the first file in inbox/ is claimed (inbox/ -> processing/);
3. the ADK pipeline runs once, with RunConfig(max_llm_calls) and a timeout;
4. the file goes to processed/ or failed/, or back to inbox/ for one retry;
5. one JSON log line per run with run_id.

Run:  uvicorn service.main:app --port 8080   (or the Docker image, see README)
then put a request file into data/storage/inbox/ and  curl -X POST localhost:8080/run
"""
import asyncio
import json
import os
import pathlib
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI

# read the agent's .env; variables already set (e.g. docker --env-file) take precedence
load_dotenv(pathlib.Path(__file__).resolve().parent.parent / "dossier_agent" / ".env")

from dossier_agent.limits import Limits  # noqa: E402
from dossier_agent.outbox import AGENT_NAME, build_result, outbox_prefix, write_outbox  # noqa: E402
from dossier_agent.storage import Storage, get_storage  # noqa: E402

from .queue import (  # noqa: E402
    FAILED, PROCESSED, claim, finish, next_inbox_key, request_text, retry_or_fail, stale_claims,
)
from .runner import run_agent  # noqa: E402

LIMITS = Limits.from_env()
# the agent stops itself at TIME_LIMIT_SECONDS; the extra minute lets it write
# result.json before this timeout cuts the run off
RUN_TIMEOUT_SECONDS = float(os.getenv("RUN_TIMEOUT_SECONDS", LIMITS.seconds + 60))
STALE_AFTER_SECONDS = float(os.getenv("STALE_AFTER_SECONDS", RUN_TIMEOUT_SECONDS + 120))
TRIGGER = "inbox"


def _iso(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


def _failed_result(run_id: str, started_at: str, errors: list[dict], usage: dict | None) -> dict:
    return build_result(agent=AGENT_NAME, run_id=run_id, trigger=TRIGGER, started_at=started_at,
                        status="failed", pending_human=[], errors=errors, usage=usage, data=None)


def _write_failed(storage: Storage, result: dict, state: dict | None = None) -> str:
    """result.json for a failed run, with trace.json if the run got that far."""
    prefix = outbox_prefix(result["started_at"], result["run_id"])
    extra = None
    if state and state.get("trace"):
        extra = {"trace.json": json.dumps({"run_id": result["run_id"], "iterations": state["trace"]},
                                          indent=2, ensure_ascii=False, default=str)}
    write_outbox(prefix, None, result, storage, extra_files=extra)
    return prefix


def _log(**fields) -> None:
    """One structured JSON line on stdout."""
    print(json.dumps({"severity": fields.pop("severity", "INFO"), **fields},
                     ensure_ascii=False, default=str), flush=True)


async def handle_run(storage: Storage, *, run=run_agent,
                     timeout_seconds: float = RUN_TIMEOUT_SECONDS,
                     max_llm_calls: int = LIMITS.max_llm_calls,
                     stale_after_seconds: float = STALE_AFTER_SECONDS,
                     now: datetime | None = None) -> dict:
    """One POST /run. Dependencies are parameters, so tests run without ADK
    or the network."""
    clock = lambda: now or datetime.now(timezone.utc)   # noqa: E731
    response = {"recovered": []}

    # 1. runs that were cut off (timeout, instance stopped): a failed attempt
    for stale in stale_claims(storage, stale_after_seconds, clock()):
        run_id = str(uuid.uuid4())
        folder, key = retry_or_fail(storage, stale, run_id, clock())
        response["recovered"].append({"file": stale.name, "moved_to": key})
        if folder == FAILED:
            result = _failed_result(run_id, _iso(clock()), [{
                "source": "service", "message": "the run was cut off (stale in processing/)"}], None)
            _write_failed(storage, result)
        _log(message="stale run recovered", file=stale.name, moved_to=key, run_id=run_id)

    # 2. claim the next request
    inbox_key = next_inbox_key(storage)
    if inbox_key is None:
        return {**response, "status": "idle"}
    claimed = claim(storage, inbox_key, clock())
    if claimed is None:
        return {**response, "status": "busy"}         # another run took this file
    run_id, started_at = str(uuid.uuid4()), _iso(clock())
    response.update(file=claimed.name, run_id=run_id)

    # 3. run the agent (a file that is not a JSON object cannot run at all)
    if claimed.request is None:
        state, error = {}, None
        result = _failed_result(run_id, started_at, [{
            "source": "input", "message": "request file is not a JSON object"}], None)
    else:
        outcome = await run(request_text(claimed.request), run_id=run_id, started_at=started_at,
                            trigger=TRIGGER, timeout_seconds=timeout_seconds,
                            max_llm_calls=max_llm_calls)
        state, error = outcome.state, outcome.error
        result = state.get("result") if isinstance(state.get("result"), dict) else None
        if state.get("input_error"):
            result = _failed_result(run_id, started_at, [{
                "source": "input", "message": str(state["input_error"])}], state.get("usage"))

    # 4. where the file goes
    prefix = state.get("outbox_prefix")
    if result is not None:
        folder = PROCESSED if result["status"] in ("ok", "partial") else FAILED
        if result["status"] == "failed" and not prefix:
            prefix = _write_failed(storage, result)      # input errors: the agent wrote nothing
        moved_to = finish(storage, claimed, folder, run_id, clock())
    else:
        # technical failure: exception, timeout, or no result at all
        error = error or "the run finished without a result"
        folder, moved_to = retry_or_fail(storage, claimed, run_id, clock())
        if folder == FAILED:
            result = _failed_result(run_id, started_at, [{"source": "service", "message": error}],
                                    state.get("usage"))
            prefix = _write_failed(storage, result, state)

    response.update(status=result["status"] if result else "retry", moved_to=moved_to,
                    error=error, outbox=prefix)
    blocked = ((result or {}).get("usage") or {}).get("blocked_pages") or 0
    severity = ("ERROR" if error or (result and result["status"] == "failed")
                else "WARNING" if blocked else "INFO")
    _log(severity=severity, blocked_pages=blocked,
         message="run finished", run_id=run_id, file=claimed.name, status=response["status"],
         moved_to=moved_to, error=error, usage=state.get("usage"))
    return response


app = FastAPI(title="Prospect Dossier")
_lock = asyncio.Lock()     # one run at a time


@app.post("/run")
async def run_endpoint() -> dict:
    async with _lock:
        return await handle_run(get_storage())


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
