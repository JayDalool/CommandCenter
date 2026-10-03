"""ccd configuration: where things live, and the project list.

Nothing here is ever sent to a client. The projects file also holds the ntfy
URL, which must never be printed or served, so ccd copies only the project
fields it needs into its state (see `public_project`).

  CCD_CONFIG     projects file   (default: the legacy board's config.json, so
                                  there is one project list during migration)
  CCD_STATE_DIR  ccd.db          (default: ~/command-center/state) — operational, prunable
  CCD_DATA_DIR   tasks.db        (default: ~/command-center/data)  — product data, never pruned
  CCD_HANDOFF    handoff notes   (default: ~/command-center/handoff)
  CCD_PORT       loopback port   (default: 7777; the host is never configurable)
"""
import json
import os
from pathlib import Path

LEGACY = Path(os.environ.get("CCBOARD_HOME", Path.home() / "command-center"))
CONFIG_PATH = Path(os.environ.get("CCD_CONFIG", LEGACY / "board" / "config.json"))
STATE_DIR = Path(os.environ.get("CCD_STATE_DIR", LEGACY / "state"))
DATA_DIR = Path(os.environ.get("CCD_DATA_DIR", LEGACY / "data"))
HANDOFF_DIR = Path(os.environ.get("CCD_HANDOFF", LEGACY / "handoff"))
TOKEN_PATH = Path(os.environ.get("CCD_TOKEN_FILE", Path.home() / ".config" / "command-center" / "ccd.token"))
HERDR_SOCKET = Path(os.environ.get("CCD_HERDR_SOCKET", Path.home() / ".config" / "herdr" / "herdr.sock"))

HOST = "127.0.0.1"  # owner decision 6: loopback only. Deliberately not configurable.
PORT = int(os.environ.get("CCD_PORT", "7777"))

DEFAULTS = {
    "stale_pr_hours": 48,
    "stuck_minutes": 10,
    "worktree_limit": 6,
    "disk_warn_percent": 78,
    "swap_warn_percent": 60,
    "backup_status_glob": "",
    "projects": [],
    # Poll intervals, seconds. GitHub data changes in minutes, not seconds.
    "github_seconds": 120,
    "host_seconds": 120,
    "git_seconds": 300,
    "reconcile_seconds": 30,
    "retention_days": 30,
    # Ticket projects beyond the board's own list (they have no repo to poll).
    "task_projects": [{"key": "commandcenter", "name": "Command Center", "prefix": "CC"}],
}

# The only project fields that may leave the server.
PUBLIC_PROJECT_FIELDS = ("key", "name", "repo", "path", "branch", "model", "effort", "links", "index", "prefix")


def load(path=None):
    cfg = dict(DEFAULTS)
    p = Path(path) if path else CONFIG_PATH
    if p.exists():
        cfg.update(json.loads(p.read_text()))
    for proj in cfg["projects"]:
        proj.setdefault("branch", "main")
        proj.setdefault("session", proj["key"])
        proj.setdefault("ui_tests", "docs/jay/UI_TESTS.md")
        proj.setdefault("actions", "docs/jay/MY_ACTIONS.md")
        proj.setdefault("links", [])
        proj.setdefault("commands", [])
        proj.setdefault("index", "")
        proj.setdefault("path", "")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return cfg


def task_projects(cfg):
    """Every project that can hold tickets: the board's projects plus `task_projects`."""
    seen = {p["key"] for p in cfg["projects"]}
    return list(cfg["projects"]) + [p for p in cfg.get("task_projects") or [] if p["key"] not in seen]


def public_project(p):
    return {k: p.get(k) for k in PUBLIC_PROJECT_FIELDS}
