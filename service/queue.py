"""Inbox queue on storage (no LLM, no ADK): inbox/ -> processing/ -> processed/ | failed/.

A request file is the agent input ({"company", "domain", "context"}). While
it is processed, two service fields are added to it: "_attempts" (failed
technical attempts so far) and "_claimed_at" (ISO time). They live in the file
itself, so no separate state is needed; parse_request ignores them.

Rules:
- only technical failures are retried (exception, timeout, model API down):
  attempts + 1 and back to inbox/; after MAX_ATTEMPTS -> failed/;
- a run that returned a dossier (ok / partial) -> processed/, no retry;
- invalid input or a hard stop before any dossier -> failed/ at once;
- a file left in processing/ longer than the stale timeout counts as a
  failed technical attempt (the run was cut off).
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from dossier_agent.storage import Storage

INBOX, PROCESSING, PROCESSED, FAILED = "inbox/", "processing/", "processed/", "failed/"
MAX_ATTEMPTS = 2
SERVICE_FIELDS = ("_attempts", "_claimed_at")


@dataclass
class Claim:
    name: str                 # file name, e.g. "plausible.io.json"
    key: str                  # processing/<name>
    request: dict | None      # parsed JSON without service fields; None if not a JSON object
    raw: str                  # original file text
    attempts: int             # failed technical attempts before this one


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _name(key: str) -> str:
    return key.rsplit("/", 1)[-1]


def _parse(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def request_text(request: dict) -> str:
    """The message for the agent: the request without service fields."""
    return json.dumps({k: v for k, v in request.items() if k not in SERVICE_FIELDS},
                      ensure_ascii=False)


def next_inbox_key(storage: Storage) -> str | None:
    """The first file in inbox/ by name (top level only)."""
    keys = [k for k in storage.list_keys(INBOX) if "/" not in k[len(INBOX):]]
    return keys[0] if keys else None


def claim(storage: Storage, inbox_key: str, now: datetime | None = None) -> Claim | None:
    """Move a file from inbox/ to processing/. None if another run took it
    first (the processing/ file already exists) or it disappeared."""
    raw = storage.read_text(inbox_key)
    if raw is None:
        return None
    name = _name(inbox_key)
    data = _parse(raw)
    attempts = int(data.get("_attempts", 0)) if data else 0
    if data is not None:
        content = json.dumps({**data, "_attempts": attempts,
                              "_claimed_at": _now(now).isoformat(timespec="seconds")},
                             ensure_ascii=False, indent=2)
    else:
        content = raw            # not JSON: keep as is, it goes to failed/ right away
    key = PROCESSING + name
    if not storage.write_text_if_absent(key, content):
        return None
    storage.delete(inbox_key)
    request = {k: v for k, v in data.items() if k not in SERVICE_FIELDS} if data else None
    return Claim(name=name, key=key, request=request, raw=raw, attempts=attempts)


def finish(storage: Storage, claim_: Claim, folder: str, run_id: str,
           now: datetime | None = None) -> str:
    """Move the claimed file to processed/ or failed/ under
    <folder>/<YYYY-MM-DD>/<run_id>__<name>, so repeated requests for the same
    company never overwrite each other. Returns the new key."""
    assert folder in (PROCESSED, FAILED)
    text = storage.read_text(claim_.key)
    key = f"{folder}{_now(now).date().isoformat()}/{run_id}__{claim_.name}"
    storage.write_text(key, text if text is not None else claim_.raw)
    storage.delete(claim_.key)
    return key


def retry_or_fail(storage: Storage, claim_: Claim, run_id: str,
                  now: datetime | None = None) -> tuple[str, str]:
    """A technical failure: back to inbox/ with attempts + 1, or to failed/
    after MAX_ATTEMPTS. Returns (folder, new key)."""
    attempts = claim_.attempts + 1
    if attempts >= MAX_ATTEMPTS or claim_.request is None:
        return FAILED, finish(storage, claim_, FAILED, run_id, now)
    content = json.dumps({**claim_.request, "_attempts": attempts}, ensure_ascii=False, indent=2)
    key = INBOX + claim_.name
    storage.write_text(key, content)
    storage.delete(claim_.key)
    return INBOX, key


def stale_claims(storage: Storage, stale_after_seconds: float,
                 now: datetime | None = None) -> list[Claim]:
    """Files in processing/ claimed longer ago than stale_after_seconds (or
    with no readable claim time): their run was cut off."""
    result = []
    for key in storage.list_keys(PROCESSING):
        raw = storage.read_text(key)
        if raw is None:
            continue
        data = _parse(raw)
        claimed = None
        if data and isinstance(data.get("_claimed_at"), str):
            try:
                claimed = datetime.fromisoformat(data["_claimed_at"])
            except ValueError:
                claimed = None
        if claimed is not None:
            if claimed.tzinfo is None:
                claimed = claimed.replace(tzinfo=timezone.utc)
            if (_now(now) - claimed).total_seconds() < stale_after_seconds:
                continue
        request = {k: v for k, v in data.items() if k not in SERVICE_FIELDS} if data else None
        result.append(Claim(name=_name(key), key=key, request=request, raw=raw,
                            attempts=int(data.get("_attempts", 0)) if data else 0))
    return result
