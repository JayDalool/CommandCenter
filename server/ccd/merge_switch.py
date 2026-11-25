"""Jay's per-repository auto-merge switch, set from Settings › Auto-merge (Jay, 2026-11-25).

CC-057 made config.json `auto_merge` a list of project keys, read once at start. Jay asked to turn auto-merge on and
off per repository "very simply from the settings", so this file stores that switch and it takes effect at once:

  a project switched in Settings   → the switch decides (on or off), whatever config.json says
  a project never switched there   → config.json `auto_merge` decides, as before

The switch only says whether ccd may merge a project's PRs by itself. What may be merged is still decided by
merge_policy.classify (small, allow-listed, nothing on the deny list, fresh review and green named checks at the
exact head) and the stop files still stop everything. A project that cannot auto-merge at all (an `owner` project,
no allowlist, paused, a client's) cannot be switched on (Daemon.auto_merge_set says why).

Stored in <CCD_STATE_DIR>/auto-merge.json (0600), written atomically. Fails closed: a file that exists but cannot be
read or parsed switches every project OFF (not back to config.json) and says so, so a damaged file never turns a
project on.
"""
import json
import os
import re
import tempfile
import time

KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class MergeSwitchError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class MergeSwitch:
    def __init__(self, path):
        self.path = str(path)
        self.projects = {}      # project → {"on": bool, "at": epoch s, "by": actor}
        self.problem = None     # why the file was not believed; then every project is off
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            self.problem = "auto-merge.json could not be read or parsed; auto-merge is off for every project"
            return
        rows = raw.get("projects") if isinstance(raw, dict) else None
        if not isinstance(rows, dict) or any(not isinstance(k, str) or not KEY_RE.match(k) or not isinstance(v, dict)
                                             or not isinstance(v.get("on"), bool) for k, v in rows.items()):
            # Never the file's text in the message: it is arbitrary state (as config.auto_merge_projects).
            self.problem = "auto-merge.json is not in the expected shape; auto-merge is off for every project"
            return
        self.projects = {k: {"on": v["on"], "at": v.get("at"), "by": v.get("by")} for k, v in rows.items()}

    def get(self, project):
        """{"on", "at", "by"} when Jay switched the project in Settings, else None (config.json decides)."""
        row = self.projects.get(project)
        return dict(row) if row else None

    def effective(self, project, config_list):
        """On or off for one project: the Settings switch when there is one, else membership of config `auto_merge`.
        A file that was not believed means off for everyone."""
        if self.problem:
            return False
        row = self.projects.get(project)
        return row["on"] if row else project in (config_list or ())

    def set(self, project, on, by="jay", now=None, known=()):
        """Switch one project. `known`: every project key; when the file was not believed, the others are written
        as off, so repairing the file by pressing one switch never hands the rest back to config.json."""
        if not isinstance(project, str) or not KEY_RE.match(project):
            raise MergeSwitchError(400, "unknown project")
        if not isinstance(on, bool):
            raise MergeSwitchError(400, "on must be true or false")
        at = int(time.time() if now is None else now)
        rows = {k: {"on": False, "at": at, "by": by} for k in known if k != project} if self.problem else dict(self.projects)
        rows[project] = {"on": on, "at": at, "by": by}
        self._save(rows)
        self.projects = rows
        # Jay just wrote a good file over the damaged one: believe it from now on.
        self.problem = None

    def _save(self, rows):
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".auto-merge-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"projects": rows}, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
