"""The project registry: the ONE place a project's identity lives.

A project's ticket prefix decides the keys of every ticket it will ever own, so
it cannot be guessed, derived from a directory name, or written down twice. It
is declared here, once, and every other layer reads it from here:

    tasks.py    allocates keys from the prefix; refuses an unregistered project
    config.py   fills in name and prefix for the board's project list
    model.py    strips and extracts task IDs from PR and issue titles
    daemon.py   validates a dispatch target
    the UI      receives `prefix` per project in /api/state and /api/tasks

Three kinds of prefix, deliberately separate:

  prefix       the live one. New keys use it, and only it (GauzeMate → GZ-027)
  legacy       a prefix this project once minted keys with. Those keys keep
               working — they are looked up, resolved and shown as history —
               but nothing new is ever minted with them (GM-014 stays GM-014)
  board_ids    IDs that only ever lived outside ccd: the legacy board's
               INDEX.md tables and GitHub issue titles. Recognised when reading
               those sources, never a ticket key (GYST-VN-009, VN-073)

Adding a project means adding a row here with a stable prefix. A project with
no row and no explicit prefix in config.json can hold no tickets at all —
better a loud refusal than a ticket key nobody meant.

Prefixes are never recycled: a prefix in `legacy` can never become another
project's live prefix, and the schema enforces it (tasks.py migration 2).
"""
import re

# key → identity. `name` is the display name; config.json may override it.
# `prefix` and `legacy` are authoritative and config.json may not disagree.
PROJECTS = {
    "samvision":     {"name": "SamVision",        "prefix": "SV",   "legacy": ()},
    "gauzemate":     {"name": "GauzeMate",        "prefix": "GZ",   "legacy": ("GM",)},
    "mfe":           {"name": "MyFamilyExpenses", "prefix": "MFE",  "legacy": ()},
    "commandcenter": {"name": "Command Center",   "prefix": "CC",   "legacy": ()},
    "gyst":          {"name": "GYST / LifeOps",   "prefix": "GYST", "legacy": ()},
}

# IDs that appear only in sources outside ccd (INDEX.md rows, issue titles).
# They are not ticket prefixes and never mint a key; the importer keeps them as
# `legacy` ticket_links.
BOARD_ID_PREFIXES = ("GYST-VN", "VN", "OPS")

# A live prefix: letters and digits, short enough to read in a table.
PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")
# A retired or external prefix may carry the hyphen a hand-written ID had.
WIDE_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{0,8}(?:-[A-Z0-9]{1,8})?$")


class RegistryError(Exception):
    pass


def project(key):
    return PROJECTS.get(key)


def name_of(key):
    return (PROJECTS.get(key) or {}).get("name") or key


def prefix_of(key):
    """The live prefix of a registered project, or None."""
    return (PROJECTS.get(key) or {}).get("prefix")


def legacy_of(key):
    return tuple((PROJECTS.get(key) or {}).get("legacy") or ())


def prefixes():
    """live prefix → project key."""
    return {p["prefix"]: k for k, p in PROJECTS.items()}


def legacy_prefixes():
    """retired prefix → project key. Resolvable, never minted."""
    out = {}
    for key, p in PROJECTS.items():
        for old in p.get("legacy") or ():
            out[old] = key
    return out


def all_prefixes():
    """every prefix that can start a ticket key → (project key, is_legacy)."""
    out = {pre: (key, False) for pre, key in prefixes().items()}
    out.update({pre: (key, True) for pre, key in legacy_prefixes().items()})
    return out


def board_id_prefixes():
    """Every prefix that can start an ID in a PR title, issue title or INDEX.md row."""
    return tuple(sorted(set(prefixes()) | set(legacy_prefixes()) | set(BOARD_ID_PREFIXES),
                        key=lambda p: (-len(p), p)))


def board_id_pattern():
    """`(SV|GZ|GM|GYST-VN|…)` — longest alternative first, so GYST-VN beats GYST."""
    return "(?:" + "|".join(re.escape(p) for p in board_id_prefixes()) + ")"


def resolve_prefix(prefix):
    """(project key, is_legacy) for a prefix, case-insensitively. None if unknown."""
    wanted = (prefix or "").upper()
    for known, (key, legacy) in all_prefixes().items():
        if known.upper() == wanted:
            return known, key, legacy
    return None


def check(key, prefix=None, legacy=()):
    """Validate a prefix for `key`, against the registry. Returns the prefix to use.

    A registered project's prefix comes from the registry; config.json may
    repeat it but not contradict it. An unregistered project must declare one.
    """
    known = PROJECTS.get(key)
    if known:
        if prefix and prefix != known["prefix"]:
            raise RegistryError(
                f"{key}'s ticket prefix is {known['prefix']} in the project registry; config.json says {prefix}. "
                f"Change registry.py (and retire the old prefix), not the config.")
        return known["prefix"]
    if not prefix:
        raise RegistryError(
            f"project {key} has no entry in the project registry and no 'prefix' in its config, so it can hold no "
            f"tickets. Add it to ccd/registry.py with a stable prefix.")
    if not PREFIX_RE.match(prefix):
        raise RegistryError(f"bad ticket prefix {prefix!r} for {key}: {PREFIX_RE.pattern}")
    taken = all_prefixes().get(prefix)
    if taken and taken[0] != key:
        raise RegistryError(f"ticket prefix {prefix} belongs to {taken[0]}"
                            f"{' as a retired prefix' if taken[1] else ''}; prefixes are never recycled")
    for old in legacy or ():
        if not WIDE_PREFIX_RE.match(old):
            raise RegistryError(f"bad legacy prefix {old!r} for {key}")
    return prefix


def rows():
    """The registry as data, for docs and the UI."""
    return [{"key": k, "name": p["name"], "prefix": p["prefix"], "legacy": list(p.get("legacy") or ()),
             "example": f"{p['prefix']}-012"} for k, p in sorted(PROJECTS.items())]
