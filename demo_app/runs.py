"""Saved runs for the Streamlit demo: read outbox folders (no model, no network).

A run folder holds result.json (always), report.md (when a dossier was
written) and trace.json (runs since 2026-11-11): outbox/<date>/<run_id>/, or
eval/runs/<company id>/ for the runs of the evaluation.
"""
import json
import pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class RunInfo:
    path: pathlib.Path          # .../<date>/<run_id>
    source: str                 # "local" (data/storage), "demo" (demo-data/runs) or "eval" (eval/runs)
    run_id: str
    started_at: str
    status: str
    company: str
    domain: str
    cost_usd: float | None

    def label(self) -> str:
        when = self.started_at[:16].replace("T", " ") or "?"
        name = self.company or self.domain or self.run_id[:8]
        cost = f"${self.cost_usd:.3f}" if isinstance(self.cost_usd, (int, float)) else "$ n/a"
        return f"{when} · {name} · {self.status} · {cost} · {self.source}"


def read_json(path: pathlib.Path):
    """Parsed JSON, or None if the file is missing or broken."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _info(folder: pathlib.Path, source: str, result: dict) -> RunInfo:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    return RunInfo(
        path=folder,
        source=source,
        run_id=str(result.get("run_id") or folder.name),
        started_at=str(result.get("started_at") or ""),
        status=str(result.get("status") or "unknown"),
        company=str(data.get("company") or ""),
        domain=str(data.get("domain") or ""),
        cost_usd=usage.get("cost_usd"),
    )


def list_runs(sources: list[tuple[str, pathlib.Path]]) -> list[RunInfo]:
    """All runs under the given (source name, outbox folder) pairs, newest
    first. A run found in several sources is listed once, from the first."""
    runs, seen = [], set()
    for source, outbox in sources:
        if not outbox.is_dir():
            continue
        for result_path in sorted(outbox.rglob("result.json")):
            result = read_json(result_path)
            if not isinstance(result, dict):
                continue
            info = _info(result_path.parent, source, result)
            if info.run_id in seen:
                continue
            seen.add(info.run_id)
            runs.append(info)
    return sorted(runs, key=lambda r: r.started_at, reverse=True)


def load_run(folder: pathlib.Path) -> dict:
    """{"result": dict | None, "report": str | None, "trace": dict | None}"""
    try:
        report = (folder / "report.md").read_text(encoding="utf-8")
    except OSError:
        report = None
    result = read_json(folder / "result.json")
    trace = read_json(folder / "trace.json")
    return {
        "result": result if isinstance(result, dict) else None,
        "report": report,
        "trace": trace if isinstance(trace, dict) else None,
    }
