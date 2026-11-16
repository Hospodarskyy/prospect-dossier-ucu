"""Evaluate every component of the pipeline (free: no model calls, no network).

Reads the collected runs (eval/runs/, made by eval.collect_runs), the
labelled sets (eval/data/) and the latest judge eval (eval/results/judge_*.json),
prints the metrics and writes eval/results/summary.json and summary.md.

Run from the repo root:
  python -m eval.eval_components
  python -m eval.eval_components --only writer researcher
"""
import argparse
import json
from datetime import datetime, timezone

from dotenv import load_dotenv

from eval.components.common import RESULTS_DIR, ROOT, load_runs, render

load_dotenv(ROOT / "dossier_agent" / ".env")     # same MODEL etc. as the agent import expects

from eval.components import MODULES  # noqa: E402


def run_all(only: list[str] | None = None) -> list[dict]:
    runs = load_runs()
    return [module.evaluate(runs) for name, module in MODULES.items()
            if not only or name in only]


def summary_markdown(results: list[dict], runs_count: int) -> str:
    head = (f"# Component evaluation\n\nGenerated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} "
            f"UTC by `python -m eval.eval_components` from {runs_count} collected runs "
            "(eval/runs/) and the labelled sets in eval/data/.\n\n")
    return head + "\n".join(render(r) for r in results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", choices=list(MODULES), help="components to run")
    args = parser.parse_args()
    results = run_all(args.only)
    text = summary_markdown(results, len(load_runs()))
    print(text)
    if not args.only:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / "summary.md").write_text(text, encoding="utf-8")
        (RESULTS_DIR / "summary.json").write_text(
            json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"Saved to {RESULTS_DIR / 'summary.md'} and summary.json")


if __name__ == "__main__":
    main()
