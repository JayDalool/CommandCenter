"""UI test runs: what each project's /ui-test run found, and Jay's decision on every finding.

A run is a folder the coordinator writes (skills/ui-test/SKILL.md):

    <UI_TEST_DIR>/<project>/<YYYY-MM-DD-HHMM>/report.md       first line "Status: working|complete"
    <UI_TEST_DIR>/<project>/<YYYY-MM-DD-HHMM>/findings.json   {"summary": {...}, "findings": [...]}

findings.json is model output: it is validated field by field and anything off-shape is dropped, never trusted.
Jay's decisions live beside it in decisions.json, which only ccd writes: {finding id: {decision, ticket, at}}.
"""
import json
import os
import re
import time
from pathlib import Path

from .config import LEGACY

UI_TEST_DIR = Path(os.environ.get("CCD_UI_TEST_DIR", LEGACY / "ui-tests"))

KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
RUN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{4}$")
ID_RE = re.compile(r"^F\d{1,3}$")
SEVERITIES = ("showstopper", "major", "minor")
DECISIONS = ("fix", "skip")
REPORT_MAX = 64 * 1024
FINDINGS_MAX = 256 * 1024
MAX_FINDINGS = 50
STATUS_RE = re.compile(r"^\s*Status:\s*(working|complete)\b", re.IGNORECASE)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _text(v, limit):
    return CONTROL_RE.sub(" ", v).strip()[:limit] if isinstance(v, str) else ""


def clean_findings(raw):
    """findings.json → {summary, findings}: only the documented fields, bounded; bad entries are dropped."""
    data = raw if isinstance(raw, dict) else {}
    s = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    summary = {k: s[k] for k in ("features", "passed", "failed")
               if isinstance(s.get(k), int) and not isinstance(s.get(k), bool) and 0 <= s[k] <= 10000}
    out, seen = [], set()
    for f in (data.get("findings") if isinstance(data.get("findings"), list) else [])[:MAX_FINDINGS]:
        if not isinstance(f, dict) or not ID_RE.match(str(f.get("id") or "")) or f["id"] in seen:
            continue
        sev = f.get("severity") if f.get("severity") in SEVERITIES else None
        title = _text(f.get("title"), 200)
        if not sev or not title:
            continue
        seen.add(f["id"])
        steps = [_text(x, 300) for x in (f.get("steps") if isinstance(f.get("steps"), list) else [])[:20]]
        out.append({"id": f["id"], "severity": sev, "title": title, "feature": _text(f.get("feature"), 200),
                    "steps": [x for x in steps if x], "expected": _text(f.get("expected"), 1000),
                    "actual": _text(f.get("actual"), 1000), "evidence": _text(f.get("evidence"), 1000)})
    order = {s_: i for i, s_ in enumerate(SEVERITIES)}
    out.sort(key=lambda f: (order[f["severity"]], int(f["id"][1:])))
    return {"summary": summary, "findings": out}


class UiTests:
    def __init__(self, root):
        self.root = Path(root)

    def _project_dir(self, project):
        if not KEY_RE.match(project or ""):
            return None
        return self.root / project

    def _run_dir(self, project, run):
        d = self._project_dir(project)
        if d is None or not RUN_RE.match(run or ""):
            return None
        return d / run

    @staticmethod
    def _read(path, limit):
        try:
            if path.is_symlink() or not path.is_file():
                return None
            with open(path, "rb") as fh:
                raw = fh.read(limit + 1)
        except OSError:
            return None
        return raw[:limit].decode("utf-8", "replace"), len(raw) > limit

    def runs(self, project):
        d = self._project_dir(project)
        try:
            return sorted((p.name for p in d.iterdir() if p.is_dir() and not p.is_symlink() and RUN_RE.match(p.name)),
                          reverse=True) if d else []
        except OSError:
            return []

    def run(self, project, run):
        """One run: {run, status, report, summary, findings (each with Jay's decision)} or None."""
        d = self._run_dir(project, run)
        if d is None or not d.is_dir():
            return None
        rep = self._read(d / "report.md", REPORT_MAX)
        text = (rep[0] + ("\n[…truncated]" if rep[1] else "")) if rep else ""
        m = STATUS_RE.match(text.splitlines()[0]) if text else None
        found = self._read(d / "findings.json", FINDINGS_MAX)
        try:
            data = clean_findings(json.loads(found[0])) if found and not found[1] else clean_findings({})
        except ValueError:
            data = clean_findings({})
        decided = self.decisions(project, run)
        for f in data["findings"]:
            f["decision"] = decided.get(f["id"])
        return {"run": run, "status": m.group(1).lower() if m else None, "report": text, **data}

    def latest(self, project):
        runs = self.runs(project)
        return self.run(project, runs[0]) if runs else None

    def decisions(self, project, run):
        d = self._run_dir(project, run)
        if d is None:
            return {}
        try:
            data = json.loads((d / "decisions.json").read_text())
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in data.items() if ID_RE.match(k) and isinstance(v, dict)} if isinstance(data, dict) else {}

    def decide(self, project, run, finding_id, decision, ticket=None, now=None):
        d = self._run_dir(project, run)
        if d is None or decision not in DECISIONS or not ID_RE.match(finding_id or ""):
            raise ValueError("bad run, finding or decision")
        data = self.decisions(project, run)
        data[finding_id] = {"decision": decision, "ticket": ticket, "at": now or time.time()}
        tmp = d / "decisions.json.tmp"
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(d / "decisions.json")
        return data[finding_id]
