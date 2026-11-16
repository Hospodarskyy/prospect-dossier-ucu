"""Compare two component-eval summaries (eval/results/summary.json).

    python .claude/skills/run-eval/compare.py eval/results/summary_before.json eval/results/summary.json

Prints, per component, every metric whose value changed and every table row
that changed (rows are matched by their first column). Says nothing about
whether a change is good: some metrics are better when lower (misquote rate,
dead links, cost, time), so the reader judges each one by its name.
"""
import json
import sys


def load(path: str) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return {c["name"]: c for c in json.load(f)}


def rows_by_key(component: dict) -> dict[str, dict]:
    key = (component.get("columns") or ["input"])[0]
    return {str(r.get(key, i)): r for i, r in enumerate(component.get("rows") or [])}


def compare(before: dict[str, dict], after: dict[str, dict]) -> list[str]:
    lines = []
    for name in list(before) + [n for n in after if n not in before]:
        b, a = before.get(name), after.get(name)
        if b is None or a is None:
            lines.append(f"## {name}: {'new component' if b is None else 'component removed'}")
            continue
        changes = []
        for metric in list(b["metrics"]) + [m for m in a["metrics"] if m not in b["metrics"]]:
            old, new = b["metrics"].get(metric), a["metrics"].get(metric)
            if old != new:
                changes.append(f"- {metric}: {old} -> {new}")
        rb, ra = rows_by_key(b), rows_by_key(a)
        for key in list(rb) + [k for k in ra if k not in rb]:
            old, new = rb.get(key), ra.get(key)
            if old == new:
                continue
            if old is None or new is None:
                changes.append(f"- row {key!r}: {'added' if old is None else 'removed'}")
                continue
            diff = [f"{col}: {old.get(col)} -> {new.get(col)}"
                    for col in list(old) + [c for c in new if c not in old]
                    if old.get(col) != new.get(col)]
            changes.append(f"- row {key!r}: " + "; ".join(diff))
        if changes:
            lines += [f"## {name}"] + changes
    return lines or ["No change in any metric or row."]


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print("\n".join(compare(load(sys.argv[1]), load(sys.argv[2]))))


if __name__ == "__main__":
    main()
