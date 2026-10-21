"""Run the pytest suite and write a markdown report (no API key needed).

    .venv/bin/python scripts/test_report.py                 # writes docs/test-report.md
    .venv/bin/python scripts/test_report.py --out other.md
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

AREAS = {
    "test_verification": "Identity verification",
    "test_case_resolver": "Case matching",
    "test_facts": "Fact, date and amount checks",
    "test_guidance": "FAQ guideline templates",
    "test_emotion": "Emotion, persuasion ladder, scope",
    "test_consent": "Representative and authorization",
    "test_workflow": "End-to-end workflow",
    "test_ui_suggestions": "UI suggested replies",
}


def rule_comments(path: Path) -> dict[str, str]:
    """test name -> the '# covers ...' comment on its def line, if any."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"def (test_\w+)\(.*#\s*(.+)$", line)
        if m:
            out[m.group(1)] = m.group(2).removeprefix("covers ").strip()
    return out


def docstrings(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name: (ast.get_docstring(n) or "").split("\n")[0]
            for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "test-report.md"))
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "junit.xml"
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", f"--junitxml={xml_path}"],
                              cwd=ROOT, capture_output=True, text=True)
        suite = ET.parse(xml_path).getroot()
        suite = suite.find("testsuite") if suite.tag == "testsuites" else suite

    groups: dict[str, list[tuple[str, str, float, str]]] = defaultdict(list)
    for case in suite.iter("testcase"):
        module = case.get("classname", "").split(".")[-1]
        status = "pass"
        detail = ""
        for tag in ("failure", "error"):
            node = case.find(tag)
            if node is not None:
                status, detail = "fail", (node.get("message") or "").splitlines()[0][:160]
        if case.find("skipped") is not None:
            status = "skip"
        groups[module].append((case.get("name", ""), status, float(case.get("time", 0)), detail))

    total = sum(len(v) for v in groups.values())
    failed = sum(1 for v in groups.values() for _, s, _, _ in v if s == "fail")
    passed = sum(1 for v in groups.values() for _, s, _, _ in v if s == "pass")
    secs = float(suite.get("time", 0))

    lines = [
        "# Test report",
        "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M} · **{passed}/{total} passed**"
        + (f" · **{failed} failed**" if failed else "") + f" · {secs:.2f}s",
        "",
        "Unit and workflow tests run against a scripted `FakeLLM` (no API key, deterministic). Real-model",
        "conversations are covered separately by `scripts/run_scenarios.py` (see `scenario-report.md`).",
        "The rule column refers to the numbered rules in [`SPEC.md`](SPEC.md).",
        "",
        "| Area | Tests | Result |",
        "|---|---|---|",
    ]
    order = [m for m in AREAS if m in groups] + [m for m in groups if m not in AREAS]
    for module in order:
        cases = groups[module]
        ok = sum(1 for _, s, _, _ in cases if s == "pass")
        lines.append(f"| {AREAS.get(module, module)} (`{module}.py`) | {len(cases)} | "
                     f"{'PASS' if ok == len(cases) else 'FAIL'} {ok}/{len(cases)} |")

    for module in order:
        path = ROOT / "tests" / f"{module}.py"
        rules = rule_comments(path) if path.exists() else {}
        docs = docstrings(path) if path.exists() else {}
        lines += ["", f"## {AREAS.get(module, module)}", "", f"`tests/{module}.py`", "",
                  "| Result | Test | Rule / note |", "|---|---|---|"]
        for name, status, _, detail in groups[module]:
            base = name.split("[")[0]
            note = rules.get(base) or docs.get(base, "")
            mark = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}[status]
            label = name.removeprefix("test_").replace("_", " ")
            lines.append(f"| {mark} | {label} | {note}{' — ' + detail if detail else ''} |")

    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{passed}/{total} passed{f', {failed} failed' if failed else ''} -> {args.out}")
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
