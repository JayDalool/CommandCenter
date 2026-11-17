"""Team lead permissions: how much each project's lead may approve without Jay (Jay, 2026-11-17).

Jay sets one level per project (Settings › Team lead permissions, PUT /api/lead-authority/projects/{key} with
Developer Unlock). Each level includes the ones before it:

  none           Jay approves every merge and every live deploy (and every plan the flow sends to him).
  low_risk       ccd merges a reviewed tests/docs PR by itself (merge_policy.ALLOW, CC-025). Only a project that
                 has low-risk paths can take it.
  merge          ccd merges every reviewed PR whose approval covers its head, with CI not failing.
  merge_deploy   and a live deploy the agent asks for is approved on the spot (the release window still applies).
  all            and the plan and UI approvals the flow would send to Jay. He only hears about feature and product
                 questions (the lead asks him with `pipeline_cli ask`) and anything below.

Whatever the level, these still reach Jay: a ticket flagged needs-Jay or needs-legal, a LEGAL ticket, the labels
`product-decision`, `ambiguous`, `legal` and `gate:plan`, a merge Jay asked to accept himself (owner:accept), an
auto-merge the classifier held, and any PR touching the rails (agent rules, CI, policy/; Command Center's own code,
D-007). With "keep sensitive work" on (the default) so do SECURITY tickets and the labels in SENSITIVE_LABELS.

Choosing a level takes effect at once: nothing else has to be switched on. The kill switches still win: config.json
`auto_merge: false` and the stop file (<CCD_STATE_DIR>/auto-merge.stop) stop every merge ccd would make.

A project with no stored level uses the registry's: `low_risk` for a "low-risk" project (Command Center), else
`none`. Stored in <CCD_STATE_DIR>/lead-authority.json (0600), written atomically. Only Jay changes it.
"""
import json
import os
import re
import tempfile
import time

LEVELS = ("none", "low_risk", "merge", "merge_deploy", "all")
LABELS = {"none": "None", "low_risk": "Merge low-risk", "merge": "Merge all", "merge_deploy": "Merge and deploy",
          "all": "All"}
# What each permission needs, as the lowest level that grants it.
NEEDS = {"merge_low_risk": "low_risk", "merge": "merge", "deploy": "merge_deploy", "plan": "all", "ui": "all"}
# Jay's, whatever the level: the questions only he can answer.
ALWAYS_JAY_LABELS = frozenset({"product-decision", "ambiguous", "legal", "gate:plan"})
# Jay's while "keep sensitive work" is on: hard to undo when wrong (a leak, lost data, money).
SENSITIVE_LABELS = frozenset({"security", "migration", "destructive", "financial", "personal-data", "privacy", "auth"})
KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class AuthorityError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def rank(level):
    return LEVELS.index(level) if level in LEVELS else 0


def grants(level, what):
    """True when `level` includes the permission `what` (a key of NEEDS)."""
    return rank(level) >= rank(NEEDS[what])


def _flags(ticket):
    return {f.replace(":", "_").replace("-", "_") for f in ticket.get("flags") or ()}


def jay_reasons(ticket, keep_sensitive=True, confirmed=()):
    """Why this ticket's approvals stay Jay's whatever the lead's level. [] when the lead may take them."""
    out = []
    flags = _flags(ticket)
    labels = set(ticket.get("labels") or ())
    if "needs_jay" in flags:
        out.append("the ticket is flagged needs Jay")
    if "needs_legal" in flags:
        out.append("the ticket is flagged needs legal")
    if ticket.get("type") == "LEGAL":
        out.append("the ticket type is LEGAL")
    hit = sorted(labels & ALWAYS_JAY_LABELS)
    if hit:
        out.append("the ticket has labels only Jay decides: " + ", ".join(hit))
    if "owner:accept" in (confirmed or ()):
        out.append("Jay asked to accept this ticket himself")
    if keep_sensitive:
        if ticket.get("type") == "SECURITY":
            out.append("the ticket type is SECURITY")
        hit = sorted(labels & SENSITIVE_LABELS)
        if hit:
            out.append("the ticket has sensitive labels: " + ", ".join(hit))
    return out


def default_level(project):
    from . import registry
    return "low_risk" if registry.pipeline_of(project).get("merge") == "low-risk" else "none"


class LeadAuthority:
    def __init__(self, path):
        self.path = str(path)
        self.levels = {}    # project → {"level", "keepSensitive", "at", "by"}
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            for k, v in (raw.get("projects") or {}).items():
                if isinstance(k, str) and KEY_RE.match(k) and isinstance(v, dict) and v.get("level") in LEVELS:
                    self.levels[k] = {"level": v["level"], "keepSensitive": v.get("keepSensitive") is not False,
                                      "at": v.get("at"), "by": v.get("by")}
        except (OSError, ValueError, AttributeError):
            pass    # unreadable: every project falls back to the registry's level, the stricter reading

    def level(self, project):
        row = self.levels.get(project)
        return row["level"] if row else default_level(project)

    def keeps_sensitive(self, project):
        row = self.levels.get(project)
        return True if row is None else row["keepSensitive"]

    def may(self, project, what, ticket=None, confirmed=()):
        """True when the project's lead may take `what` (a key of NEEDS) for this ticket without Jay."""
        if not grants(self.level(project), what):
            return False
        return not (ticket is not None and jay_reasons(ticket, self.keeps_sensitive(project), confirmed))

    def set(self, project, level, keep_sensitive=None, by="jay", now=None):
        if not isinstance(project, str) or not KEY_RE.match(project):
            raise AuthorityError(400, "unknown project")
        if level not in LEVELS:
            raise AuthorityError(400, f"level must be one of {', '.join(LEVELS)}")
        if keep_sensitive is not None and not isinstance(keep_sensitive, bool):
            raise AuthorityError(400, "keepSensitive must be true or false")
        keep = self.keeps_sensitive(project) if keep_sensitive is None else keep_sensitive
        self.levels[project] = {"level": level, "keepSensitive": keep, "at": time.time() if now is None else now,
                                "by": by}
        self._save()

    def _save(self):
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".lead-authority-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"projects": self.levels}, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def public(self, project):
        row = self.levels.get(project) or {}
        level = self.level(project)
        return {"level": level, "keepSensitive": self.keeps_sensitive(project), "default": not row,
                "since": row.get("at"), "permissions": {k: grants(level, k) for k in NEEDS}}
