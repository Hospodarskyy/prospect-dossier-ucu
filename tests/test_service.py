"""Offline tests for the service: storage operations, inbox queue, POST /run flow.

The agent run is replaced by a fake; no ADK call, no network.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from dossier_agent import storage
from dossier_agent.outbox import build_result
from service import queue
from service.main import handle_run
from service.runner import RunOutcome

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
REQ = {"company": "Plausible Analytics", "domain": "plausible.io"}


# --------------------------------------------------------------------------
# storage: new operations
# --------------------------------------------------------------------------
def test_local_list_delete_and_create_if_absent(tmp_path):
    s = storage.LocalStorage(tmp_path)
    assert s.list_keys("inbox/") == []
    assert s.write_text_if_absent("inbox/a.json", "1") is True
    assert s.write_text_if_absent("inbox/a.json", "2") is False      # exists: unchanged
    assert s.read_text("inbox/a.json") == "1"
    s.write_text("inbox/sub/b.json", "x")
    s.write_text("inboxes/c.json", "x")                               # not under inbox/
    assert s.list_keys("inbox") == ["inbox/a.json", "inbox/sub/b.json"]
    s.delete("inbox/a.json")
    s.delete("inbox/missing.json")                                    # no error
    assert s.list_keys("inbox/") == ["inbox/sub/b.json"]


@pytest.mark.parametrize("prefix", ["", "/", "../x/", "a//b/"])
def test_list_rejects_bad_prefix(tmp_path, prefix):
    with pytest.raises(ValueError):
        storage.LocalStorage(tmp_path).list_keys(prefix)


# --------------------------------------------------------------------------
# queue
# --------------------------------------------------------------------------
@pytest.fixture
def s(tmp_path):
    return storage.LocalStorage(tmp_path)


def test_next_inbox_key_is_first_top_level_file(s):
    s.write_text("inbox/b.json", "{}")
    s.write_text("inbox/a.json", "{}")
    s.write_text("inbox/archive/0.json", "{}")
    assert queue.next_inbox_key(s) == "inbox/a.json"


def test_claim_moves_to_processing_with_service_fields(s):
    s.write_text("inbox/plausible.io.json", json.dumps(REQ))
    c = queue.claim(s, "inbox/plausible.io.json", NOW)
    assert c.key == "processing/plausible.io.json" and c.attempts == 0 and c.request == REQ
    assert s.read_text("inbox/plausible.io.json") is None
    data = json.loads(s.read_text(c.key))
    assert data["_attempts"] == 0 and data["_claimed_at"] == "2026-11-09T12:00:00+00:00"
    assert json.loads(queue.request_text({**data})) == REQ           # service fields stripped


def test_claim_lost_race_leaves_inbox_file(s):
    s.write_text("inbox/a.json", json.dumps(REQ))
    s.write_text("processing/a.json", "{}")                           # another run has it
    assert queue.claim(s, "inbox/a.json", NOW) is None
    assert s.read_text("inbox/a.json") is not None


def test_claim_non_json_file(s):
    s.write_text("inbox/bad.json", "not json")
    c = queue.claim(s, "inbox/bad.json", NOW)
    assert c.request is None and s.read_text(c.key) == "not json"


def test_finish_uses_dated_run_folder(s):
    s.write_text("inbox/a.json", json.dumps(REQ))
    c = queue.claim(s, "inbox/a.json", NOW)
    key = queue.finish(s, c, queue.PROCESSED, "run-1", NOW)
    assert key == "processed/2026-11-09/run-1__a.json"
    assert s.read_text(c.key) is None and json.loads(s.read_text(key))["company"] == REQ["company"]


def test_retry_then_fail(s):
    s.write_text("inbox/a.json", json.dumps(REQ))
    c = queue.claim(s, "inbox/a.json", NOW)
    folder, key = queue.retry_or_fail(s, c, "run-1", NOW)
    assert (folder, key) == (queue.INBOX, "inbox/a.json")
    assert json.loads(s.read_text(key))["_attempts"] == 1
    c2 = queue.claim(s, "inbox/a.json", NOW)
    assert c2.attempts == 1
    folder, key = queue.retry_or_fail(s, c2, "run-2", NOW)
    assert folder == queue.FAILED and key == "failed/2026-11-09/run-2__a.json"
    assert s.list_keys("inbox/") == [] and s.list_keys("processing/") == []


def test_stale_claims(s):
    s.write_text("processing/old.json", json.dumps({**REQ, "_attempts": 1,
                 "_claimed_at": (NOW - timedelta(seconds=800)).isoformat()}))
    s.write_text("processing/fresh.json", json.dumps({**REQ, "_claimed_at": NOW.isoformat()}))
    s.write_text("processing/no-time.json", json.dumps(REQ))
    stale = {c.name: c for c in queue.stale_claims(s, 720, NOW)}
    assert set(stale) == {"old.json", "no-time.json"}
    assert stale["old.json"].attempts == 1 and stale["old.json"].request == REQ


# --------------------------------------------------------------------------
# handle_run (POST /run) with a fake agent
# --------------------------------------------------------------------------
def _ok_result(run_id, status="ok"):
    return build_result(agent="prospect-dossier", run_id=run_id, trigger="inbox",
                        started_at="2026-11-09T12:00:00+00:00", status=status, pending_human=[],
                        errors=[], usage={"cost_usd": 0.3},
                        data={"company": "Plausible Analytics", "domain": "plausible.io",
                              "iterations": 1, "judge_status": "pass", "facts_count": 3,
                              "unsourced_count": 0, "news": [], "pains": [], "seller": "Metacortex",
                              "seller_cases": [],
                              "previous_dossier_date": None})


class Fakes:
    """A fake agent run (scripted)."""

    def __init__(self, storage_, behaviour):
        self.storage, self.behaviour, self.runs = storage_, behaviour, []

    async def run(self, text, *, run_id, started_at, trigger, timeout_seconds, max_llm_calls):
        self.runs.append({"text": text, "run_id": run_id, "trigger": trigger,
                          "max_llm_calls": max_llm_calls})
        kind = self.behaviour
        if kind in ("ok", "partial", "hard_stop_failed"):
            status = {"ok": "ok", "partial": "partial", "hard_stop_failed": "failed"}[kind]
            prefix = f"outbox/2026-11-09/{run_id}"
            if status != "failed":
                self.storage.write_text(f"{prefix}/report.md", "# Plausible")
            result = _ok_result(run_id, status)
            self.storage.write_text(f"{prefix}/result.json", json.dumps(result))
            return RunOutcome({"result": result, "outbox_prefix": prefix,
                               "usage": {"cost_usd": 0.3}}, None)
        if kind == "input_error":
            return RunOutcome({"input_error": "domain is required"}, None)
        if kind == "timeout":
            return RunOutcome({"usage": {"cost_usd": 0.2}}, "timeout: the run took longer than 600 s")
        if kind == "no_result":
            return RunOutcome({}, None)
        raise AssertionError(kind)


def _handle(s, fakes):
    return asyncio.run(handle_run(s, run=fakes.run, timeout_seconds=600,
                                  max_llm_calls=50, stale_after_seconds=720, now=NOW))


def test_idle_when_inbox_is_empty(s):
    fakes = Fakes(s, "ok")
    assert _handle(s, fakes) == {"recovered": [], "status": "idle"}
    assert fakes.runs == []


def test_ok_run_goes_to_processed(s):
    s.write_text("inbox/plausible.io.json", json.dumps(REQ))
    fakes = Fakes(s, "ok")
    out = _handle(s, fakes)
    assert out["status"] == "ok" and out["moved_to"].startswith("processed/2026-11-09/")
    assert json.loads(fakes.runs[0]["text"]) == REQ               # no service fields for the agent
    assert fakes.runs[0]["trigger"] == "inbox" and fakes.runs[0]["max_llm_calls"] == 50
    assert s.list_keys("inbox/") == [] and s.list_keys("processing/") == []


def test_partial_run_also_goes_to_processed(s):
    s.write_text("inbox/a.json", json.dumps(REQ))
    out = _handle(s, Fakes(s, "partial"))
    assert out["status"] == "partial" and out["moved_to"].startswith("processed/")


def test_hard_stop_without_dossier_goes_to_failed_without_retry(s):
    s.write_text("inbox/a.json", json.dumps(REQ))
    fakes = Fakes(s, "hard_stop_failed")
    out = _handle(s, fakes)
    assert out["status"] == "failed" and out["moved_to"].startswith("failed/")
    assert s.list_keys("inbox/") == []                            # no retry


def test_input_error_goes_to_failed_and_writes_result(s):
    s.write_text("inbox/a.json", json.dumps({"company": "X"}))
    fakes = Fakes(s, "input_error")
    out = _handle(s, fakes)
    assert out["status"] == "failed" and out["moved_to"].startswith("failed/")
    result = json.loads(s.read_text(f"{out['outbox']}/result.json"))
    assert result["errors"] == [{"source": "input", "message": "domain is required"}]
    assert result["trigger"] == "inbox" and result["data"] is None


def test_non_json_file_fails_without_running_the_agent(s):
    s.write_text("inbox/bad.json", "{oops")
    fakes = Fakes(s, "ok")
    out = _handle(s, fakes)
    assert fakes.runs == [] and out["status"] == "failed"
    assert json.loads(s.read_text(f"{out['outbox']}/result.json"))["errors"][0]["source"] == "input"


@pytest.mark.parametrize("behaviour", ["timeout", "no_result"])
def test_technical_failure_retries_once_then_fails(s, behaviour):
    s.write_text("inbox/a.json", json.dumps(REQ))
    fakes = Fakes(s, behaviour)

    first = _handle(s, fakes)
    assert first["status"] == "retry" and first["moved_to"] == "inbox/a.json"

    second = _handle(s, fakes)
    assert second["status"] == "failed" and second["moved_to"].startswith("failed/")
    result = json.loads(s.read_text(f"{second['outbox']}/result.json"))
    assert result["status"] == "failed" and result["errors"][0]["source"] == "service"
    assert s.list_keys("inbox/") == [] and s.list_keys("processing/") == []


def test_stale_processing_file_is_recovered_first(s):
    s.write_text("processing/old.json", json.dumps(
        {**REQ, "_attempts": 0, "_claimed_at": (NOW - timedelta(hours=1)).isoformat()}))
    fakes = Fakes(s, "ok")
    out = _handle(s, fakes)
    # recovered back to inbox, then picked up and processed in the same call
    assert out["recovered"] == [{"file": "old.json", "moved_to": "inbox/old.json"}]
    assert out["status"] == "ok" and out["file"] == "old.json"


def test_stale_file_on_second_attempt_fails(s):
    s.write_text("processing/old.json", json.dumps(
        {**REQ, "_attempts": 1, "_claimed_at": (NOW - timedelta(hours=1)).isoformat()}))
    fakes = Fakes(s, "ok")
    out = _handle(s, fakes)
    assert out["recovered"][0]["moved_to"].startswith("failed/")
    assert out["status"] == "idle"
    result_key = [k for k in s.list_keys("outbox/") if k.endswith("result.json")][0]
    assert json.loads(s.read_text(result_key))["status"] == "failed"


# --------------------------------------------------------------------------
# the real run_agent with ADK, on paths that never call the model
# --------------------------------------------------------------------------
from service.runner import run_agent  # noqa: E402


def _run_real(text):
    return asyncio.run(run_agent(text, run_id="run-x", started_at="2026-11-09T12:00:00+00:00",
                                 trigger="inbox", timeout_seconds=30, max_llm_calls=50))


def test_real_runner_invalid_input_stops_before_the_model():
    outcome = _run_real(json.dumps({"company": "X"}))
    assert outcome.error is None
    assert outcome.state["input_error"] == "domain is required"
    assert outcome.state["run_id"] == "run-x" and outcome.state["trigger"] == "inbox"
    assert "usage" not in outcome.state or outcome.state["usage"]["llm_calls"] == 0


def test_real_runner_passes_every_event_to_on_event():
    seen = []
    outcome = asyncio.run(run_agent(json.dumps({"company": "X"}), run_id="run-x",
                                    started_at="2026-11-09T12:00:00+00:00", trigger="manual",
                                    timeout_seconds=30, max_llm_calls=50,
                                    on_event=lambda e: seen.append(e.author)))
    assert outcome.error is None and outcome.state["input_error"] == "domain is required"
    assert seen == ["dossier_pipeline"]          # the "Invalid request" message


def test_real_runner_on_event_may_be_async():
    seen = []

    async def collect(event):
        seen.append(event.author)

    asyncio.run(run_agent(json.dumps({"company": "X"}), run_id="run-x",
                          started_at="2026-11-09T12:00:00+00:00", trigger="manual",
                          timeout_seconds=30, max_llm_calls=50, on_event=collect))
    assert seen == ["dossier_pipeline"]


def test_real_runner_missing_case_file_is_a_technical_error(tmp_storage):
    (tmp_storage.root / "config/seller_cases.md").unlink()
    outcome = _run_real(json.dumps(REQ))
    assert outcome.error.startswith("ConfigError:")
    assert "result" not in outcome.state


# --------------------------------------------------------------------------
# HTTP endpoints (FastAPI test client, empty inbox: no agent run)
# --------------------------------------------------------------------------
def test_http_run_with_empty_inbox_and_health():
    from fastapi.testclient import TestClient
    from service.main import app
    client = TestClient(app)
    assert client.get("/health").json() == {"ok": True}
    response = client.post("/run")
    assert response.status_code == 200 and response.json() == {"recovered": [], "status": "idle"}
