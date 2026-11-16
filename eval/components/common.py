"""Shared helpers of the component evaluation: loading the collected runs,
metric formulas and Markdown tables. No model calls, no network."""
import json
import pathlib
import re
from dataclasses import dataclass, field

EVAL_DIR = pathlib.Path(__file__).resolve().parent.parent
ROOT = EVAL_DIR.parent
RUNS_DIR = EVAL_DIR / "runs"
DATA_DIR = EVAL_DIR / "data"
RESULTS_DIR = EVAL_DIR / "results"

# research section name -> dossier section name
RESEARCH_TO_DOSSIER = {
    "snapshot": "Snapshot",
    "recent news": "Recent news",
    "tech signals": "Tech signals",
    "key people": "Key people",
    "business pains": "Likely pains",
    "likely pains": "Likely pains",
}
FACT_SECTIONS = ["Snapshot", "Recent news", "Tech signals", "Key people", "Likely pains"]
URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def read_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_companies(path: pathlib.Path | None = None) -> list[dict]:
    return read_json(path or DATA_DIR / "companies.json")["companies"]


@dataclass
class Run:
    """One collected run of eval/runs/<id>/ with its spec from companies.json."""
    id: str
    spec: dict
    result: dict = field(default_factory=dict)
    report: str | None = None
    trace: dict = field(default_factory=dict)
    calls: dict = field(default_factory=dict)
    memory: dict | None = None

    @property
    def kind(self) -> str:
        return self.spec.get("kind", "real")

    @property
    def data(self) -> dict:
        return self.result.get("data") if isinstance(self.result.get("data"), dict) else {}

    @property
    def usage(self) -> dict:
        return self.result.get("usage") if isinstance(self.result.get("usage"), dict) else {}

    @property
    def iterations(self) -> list[dict]:
        return self.trace.get("iterations") or []

    @property
    def run_date(self) -> str:
        return str(self.result.get("started_at") or "")[:10]


def load_runs(runs_dir: pathlib.Path | None = None,
              companies: list[dict] | None = None) -> list[Run]:
    """The runs of every company that has a folder in runs_dir, in the order
    of companies.json."""
    runs_dir = runs_dir or RUNS_DIR
    runs = []
    for spec in companies if companies is not None else load_companies():
        folder = runs_dir / spec["id"]
        if not folder.is_dir():
            continue
        report = folder / "report.md"
        runs.append(Run(
            id=spec["id"], spec=spec,
            result=read_json(folder / "result.json") or {},
            report=report.read_text(encoding="utf-8") if report.exists() else None,
            trace=read_json(folder / "trace.json") or {},
            calls=read_json(folder / "calls.json") or {},
            memory=read_json(folder / "memory.json"),
        ))
    return runs


# --------------------------------------------------------------------------
# metric formulas
# --------------------------------------------------------------------------
def ratio(num: float, den: float) -> float | None:
    return round(num / den, 3) if den else None


def mean(values) -> float | None:
    values = [v for v in values if isinstance(v, (int, float))]
    return round(sum(values) / len(values), 3) if values else None


def prf(tp: int, fp: int, fn: int) -> dict:
    """Precision, recall, F1 (None where undefined) and the counts."""
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    f1 = (round(2 * precision * recall / (precision + recall), 3)
          if precision is not None and recall is not None and precision + recall else None)
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


# --------------------------------------------------------------------------
# dossier Markdown
# --------------------------------------------------------------------------
def dossier_sections(md: str) -> dict[str, list[str]]:
    """section name -> its bullet lines ("- ..."), in the order of the file."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in (md or "").splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
        elif current and line.strip().startswith("- "):
            sections[current].append(line.strip())
    return sections


def is_pending(line: str) -> bool:
    return line.startswith("- [Pending]")


def extract_urls(text: str) -> list[str]:
    return [u.rstrip(").,;]") for u in URL_RE.findall(text or "")]


def strip_urls(text: str) -> str:
    """The claim text of a bullet: without '- ', URLs and empty brackets."""
    text = URL_RE.sub("", text or "")
    text = re.sub(r"\(\s*\)", "", text)
    return text.lstrip("- ").strip()


# --------------------------------------------------------------------------
# Markdown output
# --------------------------------------------------------------------------
def fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".") if value != int(value) else f"{value:.0f}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def md_table(rows: list[dict], columns: list[str] | None = None) -> str:
    if not rows:
        return "_no rows_"
    columns = columns or list(rows[0])
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(fmt(r.get(c)) for c in columns) + " |" for r in rows]
    return "\n".join(lines)


def component(name: str, purpose: str, metrics: dict, rows: list[dict] | None = None,
              notes: list[str] | None = None, columns: list[str] | None = None) -> dict:
    """The result of one component evaluation."""
    return {"name": name, "purpose": purpose, "metrics": metrics, "rows": rows or [],
            "columns": columns, "notes": notes or []}


def render(result: dict) -> str:
    out = [f"## {result['name']}", "", result["purpose"], "",
           md_table([{"metric": k, "value": v} for k, v in result["metrics"].items()],
                    ["metric", "value"])]
    if result["rows"]:
        out += ["", md_table(result["rows"], result.get("columns"))]
    if result["notes"]:
        out += [""] + [f"- {n}" for n in result["notes"]]
    return "\n".join(out) + "\n"
