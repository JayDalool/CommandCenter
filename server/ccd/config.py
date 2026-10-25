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
  CCD_AUTO_MERGE_STOP  kill-switch file (default: <CCD_STATE_DIR>/auto-merge.stop): while it exists ccd merges nothing
"""
import json
import os
from pathlib import Path

from . import github, registry

LEGACY = Path(os.environ.get("CCBOARD_HOME", Path.home() / "command-center"))
CONFIG_PATH = Path(os.environ.get("CCD_CONFIG", LEGACY / "board" / "config.json"))
STATE_DIR = Path(os.environ.get("CCD_STATE_DIR", LEGACY / "state"))
DATA_DIR = Path(os.environ.get("CCD_DATA_DIR", LEGACY / "data"))
HANDOFF_DIR = Path(os.environ.get("CCD_HANDOFF", LEGACY / "handoff"))
TOKEN_PATH = Path(os.environ.get("CCD_TOKEN_FILE", Path.home() / ".config" / "command-center" / "ccd.token"))
DEV_TOKEN_PATH = Path(os.environ.get("CCD_DEV_TOKEN_FILE",
                                   Path.home() / ".config" / "command-center" / "developer.token"))
SHARE_DIR = Path(os.environ.get("CCD_SHARE_DIR", Path.home() / ".local" / "share" / "command-center"))
ATTACH_DIR = SHARE_DIR / "attachments"
LAUNCHER_DIR = Path(os.environ.get("CCD_LAUNCHER_DIR", SHARE_DIR / "launcher"))
HERDR_SOCKET = Path(os.environ.get("CCD_HERDR_SOCKET", Path.home() / ".config" / "herdr" / "herdr.sock"))

# While this file exists ccd's auto-merge does nothing (CC-025). Checked right before every merge.
AUTO_MERGE_STOP = Path(os.environ.get("CCD_AUTO_MERGE_STOP", STATE_DIR / "auto-merge.stop"))

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
    # Identity comes from the project registry; only the key is named here.
    "task_projects": [{"key": "commandcenter"}],
    # Workspace uploads and attachments, per file.
    "upload_max_mb": 50,
    # Remove a DONE ticket's clean, fully pushed worktree after ccd's git poll (ccd/worktree_cleanup.py).
    # false = never remove anything.
    "worktree_cleanup": True,
    # ccd may merge low-risk reviewed PRs itself (CC-025). Off until Jay sets it true; read at start.
    # A project must also say pipeline merge "low-risk" in ccd/registry.py.
    "auto_merge": False,
    # Onboarding groundwork (ccd/onboarding.py; D-024 proposed): agent registration records, drafts, validation,
    # read-only APIs and the shadow budget report. Off until Jay sets it true; read at start. Records only: it grants
    # nothing, issues no credential and starts no agent.
    "onboarding_groundwork": False,
    # Phase 2 shadow identity record (ccd/identity.py resolve(); Jay 2026-10-25): one identity_observations row per
    # write saying who it proves to be and why Phase 2 would refuse it. Off until Jay sets it true; read at start.
    # Records only: it refuses nothing, with or without this flag.
    "phase2_identity_shadow": False,
    # Phase 2 shadow node keys (ccd/nodekeys.py; Jay 2026-10-25): a node's Ed25519 key at enrolment and a check of
    # each heartbeat's signature, recorded with the reasons Phase 2 would refuse it. Off until Jay sets it true; read
    # at start. Records only: it refuses nothing.
    "phase2_node_shadow": False,
}

# The only project fields that may leave the server.
PUBLIC_PROJECT_FIELDS = ("key", "name", "repo", "path", "branch", "model", "effort", "links", "index", "prefix",
                         "legacy_prefixes", "github")


def load(path=None):
    cfg = json.loads(json.dumps(DEFAULTS))  # never hand out the module's own lists
    p = Path(path) if path else CONFIG_PATH
    if p.exists():
        cfg.update(json.loads(p.read_text()))
    for proj in cfg["projects"] + list(cfg.get("task_projects") or []):
        # Identity — display name, ticket prefix, retired prefixes — comes from
        # the one project registry, so the config file cannot drift from it. A
        # config "prefix" that disagrees is a loud error; see ccd/registry.py.
        key = proj["key"]
        proj["prefix"] = registry.check(key, proj.get("prefix"), registry.legacy_of(key))
        proj["legacy_prefixes"] = list(registry.legacy_of(key))
        if registry.project(key):
            proj["name"] = registry.name_of(key)
            slug = registry.github_of(key)
            given = github.normalize(proj.get("repo")) if proj.get("repo") else None
            if proj.get("repo") and (given or "").lower() != slug.lower():
                raise registry.RegistryError(
                    f"{key}'s repository is {slug} in the project registry; config.json says {proj.get('repo')!r}.")
            proj["repo"] = slug
        else:
            proj.setdefault("name", key)
        proj["github"] = github.identity(github.normalize(proj.get("repo") or "") or "")
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
