"""PREVIEW of a one-time import of existing tasks into tasks.db. Read-only.

Sources, per project:

    docs/tasks/INDEX.md   table rows (SamVision)              → tickets, keeping their IDs
    docs/tasks/*.md       one file per task (GYST)            → tickets, new keys, legacy ID kept as a link
    GitHub issues         open issues, from ccd's cached poll → merged into the matching ticket, or new
    docs/jay/MY_ACTIONS.md open checkbox lines                → a needs:jay flag on the ticket they name,
                                                                or a new OWNER_ACTION ticket
    handoff notes         ~/command-center/handoff/*.md       → skipped: context, not tasks

preview() writes nothing. It says what an import WOULD do, sorted into
would_create / would_update / existing / ambiguous / duplicates / skipped.
apply() runs the same preview and creates every would_create ticket, one
transaction per project. Every created ticket gets a provenance link
(legacy / import_source / <stable source id>), and a source whose link already
exists is reported as `existing`, so a second apply creates nothing.
Closed historical work (DONE / DENIED / CANCELLED) is created archived.
GitHub issues are never closed or edited by this module.
"""
import hashlib
import os
import re
import time
from pathlib import Path

from . import registry
from . import tasks as T
from .config import HANDOFF_DIR

STATUS_WORDS = {s: s for s in T.ALL_STATUSES}
STATUS_WORDS.update({"IN PROGRESS": "IN_PROGRESS", "READY": "READY_TO_IMPLEMENT", "REVIEW": "IN_REVIEW",
                     "ACTIVE": "IN_PROGRESS", "TODO": "PROPOSED", "OPEN": "PROPOSED"})
PRIORITY_MAP = {"P0": "URGENT", "P1": "HIGH", "P2": "MEDIUM", "P3": "LOW"}
LABEL_STATUS = {"status:in-progress": "IN_PROGRESS", "status:review": "IN_REVIEW", "status:ready": "READY_TO_IMPLEMENT",
                "status:blocked": "BLOCKED"}
LABEL_FLAGS = {"needs:jay": "needs_jay", "needs:legal": "needs_legal", "needs:ui-review": "needs_ui_review",
               "needs:deploy": "needs_deploy"}
SKIP_FILES = {"README.md", "INDEX.md", "QUEUE.md", "TEMPLATE.md"}


def _status_of(text):
    """'VERIFYING (#88 merged …)' → ('VERIFYING', note). Unknown words → (None, text)."""
    raw = (text or "").strip().strip("`*").strip()
    up = raw.upper()
    for word in sorted(STATUS_WORDS, key=len, reverse=True):
        if up.startswith(word):
            return STATUS_WORDS[word], raw[len(word):].strip(" .:-—()`")
    return None, raw


def _flags_from_note(status, note):
    low = (note or "").lower()
    flags = []
    if "needs jay" in low or "drill pending" in low or "jay's authorization" in low:
        flags.append("needs_jay")
    if status == "BLOCKED" and "legal" in low:
        flags.append("needs_legal")
    return flags


def index_rows(path):
    """Rows of a docs/tasks/INDEX.md table: | ID | Task | Priority | Status | Dependency | PR | Last reviewed |."""
    try:
        text = Path(path).read_text(errors="replace")
    except OSError as e:
        return None, str(e)
    rows = []
    for n, line in enumerate(text.splitlines(), 1):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not re.match(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+$", cells[0]):
            continue
        rows.append({"id": cells[0], "title": cells[1].replace("`", ""), "priority": cells[2], "status": cells[3],
                     "dependency": cells[4], "pr": cells[5] if len(cells) > 5 else "", "line": n})
    return rows, None


def task_files(directory):
    """One task per file: `UI-3-projects.md` → id UI-3, title from the first heading, status from '**Status:**'."""
    out, skipped = [], []
    try:
        files = sorted(p for p in Path(directory).glob("*.md") if p.is_file())
    except OSError:
        return [], []
    for f in files:
        if f.name in SKIP_FILES:
            skipped.append({"ref": f.name, "reason": "index or readme, not a task"})
            continue
        m = re.match(r"^((?:[A-Z]+[0-9]*)(?:-(?:[A-Z]+[0-9]*|\d+))*?)-[a-z]", f.name)
        text = f.read_text(errors="replace")
        head = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("#")), f.stem)
        status_line = next((l for l in text.splitlines()[:30] if re.search(r"\*\*Status:?\*\*|^Status:", l)), "")
        status_txt = re.sub(r".*Status:?\**:?\s*", "", status_line) if status_line else ""
        out.append({"id": m.group(1) if m else None, "file": f.name, "title": re.sub(r"^[A-Z0-9-]+\s*[—:-]\s*", "", head),
                    "status": status_txt})
    return out, skipped


def actions_lines(path):
    """Open `- [ ] <id> · <what> · <link>` lines of MY_ACTIONS.md."""
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return []
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        m = re.match(r"\s*[-*] \[ \]\s*(.+)$", line)
        if not m:
            continue
        parts = [p.strip() for p in m.group(1).split("·")]
        out.append({"id": parts[0] if len(parts) > 1 else None, "what": parts[1] if len(parts) > 1 else parts[0],
                    "link": parts[2] if len(parts) > 2 else None, "line": n})
    return out


def _norm(title):
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _action_id(project, a):
    """Stable id of a MY_ACTIONS line: its wording, not its line number."""
    text = _norm(f"{a['id'] or ''} {a['what']}")
    return f"my_actions:{project}:{hashlib.sha1(text.encode()).hexdigest()[:12]}"


def preview(projects, gh_data, store, handoff_dir=None):
    """What an import would do, without doing any of it."""
    started = time.time()
    tprojects = {p["key"]: p for p in store.projects()}
    sources, create, update, ambiguous, duplicates, skipped, existing = [], [], [], [], [], [], []
    next_num = {k: v["nextNumber"] for k, v in tprojects.items()}

    for p in projects:
        key = p["key"]
        tp = tprojects.get(key)
        if not tp:
            skipped.append({"project": key, "source": "config", "ref": key, "reason": "project has no ticket prefix"})
            continue
        prefix = tp["prefix"]
        # A historical ID keeps its own prefix: GauzeMate's GM-014 imports as
        # GM-014, not as a renumbered GZ key. Only NEW keys use the live prefix.
        legacy = [a for a in tp.get("legacyPrefixes") or registry.legacy_of(key)]
        accepted = [prefix] + list(legacy)
        prx = "(?:" + "|".join(re.escape(x) for x in sorted(accepted, key=len, reverse=True)) + ")"
        cands = {}  # proposed key → candidate
        by_legacy = {}

        def imported(src_id, ref):
            """A source an earlier import already turned into a ticket (found by its provenance link)."""
            k = store.ticket_by_link("legacy", "import_source", src_id)
            if k:
                existing.append({"project": key, "key": k, "source": src_id, "ref": ref,
                                 "reason": "already imported (provenance link present)"})
            return k

        def stub(k):
            """An already-imported ticket later sources may still attach to, never re-create."""
            cur = store.get(k)
            return cands.setdefault(k, {"proposedKey": k, "existing": True, "project": key, "title": cur["title"],
                                        "flags": [], "links": [], "sources": []})

        def add(cand, source_ref):
            k = cand["proposedKey"]
            if k in cands:
                prev = cands[k]
                # A stub with no sources is an existing ticket this source only
                # updates, not two sources describing one new ticket.
                if prev["sources"]:
                    duplicates.append({"project": key, "key": k, "sources": prev["sources"] + [source_ref],
                                       "resolution": f"merged into one ticket; {prev['sources'][0]['kind']} wins on "
                                                     "title and status, flags and links are combined"})
                prev["sources"].append(source_ref)
                prev["flags"] = sorted(set(prev["flags"]) | set(cand["flags"]))
                prev["links"] += [l for l in cand["links"] if l not in prev["links"]]
                return prev
            cands[k] = cand
            return cand

        # Numbers already used by an ID in any source are reserved first, so a new
        # key can never collide with one (GauzeMate's MY_ACTIONS uses GM-001…GM-014).
        reserved = set()
        idrx = re.compile(rf"(?<![A-Za-z0-9]){prx}-(\d{{1,6}})(?![0-9])")
        if p.get("index") and p.get("path"):
            for r in index_rows(os.path.join(p["path"], p["index"]))[0] or []:
                reserved |= {int(x) for x in idrx.findall(r["id"])}
        for it in (gh_data.get(key) or {}).get("issues") or [] if isinstance((gh_data.get(key) or {}).get("issues"), list) else []:
            reserved |= {int(x) for x in idrx.findall(it.get("title", ""))}
        if p.get("path"):
            for a in actions_lines(os.path.join(p["path"], p.get("actions") or "docs/jay/MY_ACTIONS.md")):
                reserved |= {int(x) for x in idrx.findall(a["id"] or "")}

        # New keys go after the highest ID any source has used: a gap in an old
        # numbering may be a task that was deleted, and its number stays retired.
        next_num[key] = max(next_num[key], max(reserved, default=0) + 1)

        def new_key():
            n = next_num[key]
            while n in reserved or store.exists(f"{prefix}-{n:03d}"):
                n += 1
            next_num[key] = n + 1
            return f"{prefix}-{n:03d}", n

        # 1. INDEX.md
        if p.get("index") and p.get("path"):
            ipath = os.path.join(p["path"], p["index"])
            rows, err = index_rows(ipath)
            sources.append({"project": key, "kind": "index", "ref": p["index"], "count": len(rows or []), "error": err})
            for r in rows or []:
                m = re.match(rf"^({prx})-(\d+)$", r["id"])
                status, note = _status_of(r["status"])
                src = {"kind": "index", "ref": f"{p['index']}:{r['line']}",
                       "id": f"index:{p['index']}#{r['id']}"}
                if not m:
                    ambiguous.append({"project": key, "source": "index", "ref": r["id"], "title": r["title"],
                                      "reason": f"ID does not use the {' or '.join(accepted)} prefix",
                                      "suggestion": f"new {prefix} key with {r['id']} kept as a legacy link"})
                    continue
                if status is None:
                    ambiguous.append({"project": key, "source": "index", "ref": r["id"], "title": r["title"],
                                      "reason": f"status '{r['status'][:60]}' is not a pipeline status",
                                      "suggestion": "import as PROPOSED and review"})
                    continue
                k = f"{m.group(1)}-{int(m.group(2)):03d}"
                links = []
                for num in re.findall(r"#(\d+)", r["pr"] + " " + note):
                    if p.get("repo"):
                        links.append({"provider": "github", "kind": "pr", "ref": f"{p['repo']}#{num}"})
                        break  # the first PR named is the ticket's PR; the rest stay in the note
                deps = re.findall(rf"{prx}-\d+", r["dependency"])
                add({"proposedKey": k, "number": int(m.group(2)), "keepsId": True, "project": key, "title": r["title"][:300],
                     "status": status, "priority": PRIORITY_MAP.get(r["priority"].upper(), "NO_PRIORITY"),
                     "type": None, "flags": _flags_from_note(status, note), "links": links, "blockedBy": deps,
                     "note": note[:300], "sources": [src]}, src)

        # 2. one file per task (no index)
        tdir = os.path.join(p.get("path") or "", "docs", "tasks")
        if p.get("path") and not p.get("index") and os.path.isdir(tdir):
            files, skip = task_files(tdir)
            sources.append({"project": key, "kind": "task_files", "ref": "docs/tasks/*.md", "count": len(files),
                            "error": None})
            for s in skip:
                skipped.append(dict(s, project=key, source="task_files"))
            for f in files:
                src = {"kind": "task_file", "ref": f"docs/tasks/{f['file']}", "id": f"task_file:docs/tasks/{f['file']}"}
                status, note = _status_of(f["status"])
                if not f["id"]:
                    ambiguous.append({"project": key, "source": "task_file", "ref": f["file"], "title": f["title"],
                                      "reason": "no task ID in the file name", "suggestion": "import with a new key"})
                    continue
                if status is None:
                    ambiguous.append({"project": key, "source": "task_file", "ref": f["id"], "title": f["title"],
                                      "reason": "no Status line" if not f["status"] else
                                      f"status '{f['status'][:60]}' is not a pipeline status",
                                      "suggestion": "import as PROPOSED and review"})
                    continue
                done = imported(src["id"], src["ref"])
                if done:
                    by_legacy[f["id"]] = stub(done)
                    continue
                k, n = new_key()
                cand = add({"proposedKey": k, "number": n, "keepsId": False, "project": key, "title": f["title"][:300],
                            "status": status, "priority": "NO_PRIORITY", "type": None,
                            "flags": _flags_from_note(status, note),
                            "links": [{"provider": "legacy", "kind": "legacy_id", "ref": f["id"]}],
                            "blockedBy": [], "note": note[:300], "sources": [src]}, src)
                by_legacy[f["id"]] = cand

        # 3. GitHub issues (cached; this never calls GitHub)
        issues = (gh_data.get(key) or {}).get("issues")
        if isinstance(issues, list):
            sources.append({"project": key, "kind": "github_issues", "ref": p.get("repo"), "count": len(issues),
                            "error": None})
            by_title = {_norm(c["title"]): c for c in cands.values()}
            for it in issues:
                labels = [l["name"] if isinstance(l, dict) else l for l in it.get("labels", [])]
                src = {"kind": "github_issue", "ref": f"{p.get('repo')}#{it['number']}",
                       "id": f"github_issue:{p.get('repo')}#{it['number']}"}
                if imported(src["id"], src["ref"]):
                    continue
                link = {"provider": "github", "kind": "issue", "ref": src["ref"], "url": it.get("url")}
                flags = [LABEL_FLAGS[l] for l in labels if l in LABEL_FLAGS]
                status = next((LABEL_STATUS[l] for l in labels if l in LABEL_STATUS), "PROPOSED")
                prio = next((PRIORITY_MAP[l.split(":", 1)[1].upper()] for l in labels
                             if l.startswith("priority:") and l.split(":", 1)[1].upper() in PRIORITY_MAP), "NO_PRIORITY")
                lead = re.match(r"^\s*([A-Z]{1,4}-?\d+)\s*[·—:-]\s*", it.get("title", ""))
                named = [k for k in store.find_keys(it.get("title", "")) if k.rsplit("-", 1)[0] in accepted]
                legacy = re.findall(r"\b((?:VN|UI|[A-Z]{1,4})-?\d+)\b", it.get("title", ""))
                if named:
                    k = named[0]
                    if k in cands:
                        add({"proposedKey": k, "flags": flags, "links": [link], "sources": [src]}, src)
                    else:
                        add({"proposedKey": k, "number": int(k.split("-")[-1]), "keepsId": True, "project": key,
                             "title": re.sub(r"^\s*[A-Z]+-\d+\s*[—:-]\s*", "", it["title"])[:300], "status": status,
                             "priority": prio, "type": "BUG" if "bug" in labels else None, "flags": flags,
                             "links": [link], "blockedBy": [], "note": "", "sources": [src]}, src)
                    continue
                twin = by_title.get(_norm(re.sub(r"^\s*[A-Z0-9-]+\s*[—:-]\s*", "", it.get("title", ""))))
                lg = next((by_legacy[x] for x in legacy if x in by_legacy), None)
                if twin or lg:
                    hit = twin or lg
                    ambiguous.append({"project": key, "source": "github_issue", "ref": src["ref"], "title": it["title"],
                                      "reason": f"looks like {hit['proposedKey']} but names no ticket key",
                                      "suggestion": f"link to {hit['proposedKey']}"})
                    continue
                k, n = new_key()
                links = [link] + ([{"provider": "legacy", "kind": "legacy_id", "ref": lead.group(1)}] if lead else [])
                add({"proposedKey": k, "number": n, "keepsId": False, "project": key,
                     "title": (it["title"][lead.end():] if lead else it["title"])[:300],
                     "status": status, "priority": prio, "type": "BUG" if "bug" in labels else None,
                     "flags": flags, "links": links, "blockedBy": [], "note": "", "sources": [src]}, src)
        else:
            sources.append({"project": key, "kind": "github_issues", "ref": p.get("repo"), "count": 0,
                            "error": "no cached GitHub data yet"})

        # 4. MY_ACTIONS.md
        if p.get("path"):
            apath = os.path.join(p["path"], p.get("actions") or "docs/jay/MY_ACTIONS.md")
            lines = actions_lines(apath)
            sources.append({"project": key, "kind": "my_actions", "ref": p.get("actions") or "docs/jay/MY_ACTIONS.md",
                            "count": len(lines), "error": None})
            for a in lines:
                src = {"kind": "my_actions", "ref": f"MY_ACTIONS.md:{a['line']}", "id": _action_id(key, a)}
                tid = (a["id"] or "").strip()
                m = re.match(rf"^({prx})-(\d+)$", tid)
                k = f"{m.group(1)}-{int(m.group(2)):03d}" if m else None
                if k and k in cands:
                    add({"proposedKey": k, "flags": ["needs_jay"], "links": [], "sources": [src]}, src)
                    continue
                if k and store.exists(k):
                    cands.setdefault(k, {"proposedKey": k, "existing": True, "project": key, "flags": [],
                                         "links": [], "sources": []})
                    add({"proposedKey": k, "flags": ["needs_jay"], "links": [], "sources": [src]}, src)
                    continue
                if imported(src["id"], src["ref"]):
                    continue
                if k:
                    kk, n, keeps = k, int(m.group(2)), True
                else:
                    (kk, n), keeps = new_key(), False
                link = [{"provider": "legacy", "kind": "legacy_id", "ref": tid}] if tid and not k else []
                add({"proposedKey": kk, "number": n, "keepsId": keeps, "project": key, "title": a["what"][:300],
                     "status": "INBOX", "priority": "NO_PRIORITY", "type": "OWNER_ACTION", "flags": ["needs_jay"],
                     "links": link, "blockedBy": [], "note": a["link"] or "", "sources": [src]}, src)

        # sort candidates into create / update against what tasks.db already holds
        for k, c in cands.items():
            if store.exists(k):
                cur = store.get(k)
                changes = []
                for f in ("title", "status", "priority"):
                    if c.get(f) and cur[f] != c[f]:
                        changes.append({"field": f, "from": cur[f], "to": c[f]})
                for f in c.get("flags") or []:
                    if f not in cur["flags"]:
                        changes.append({"field": f, "from": False, "to": True})
                have = {(l["provider"], l["kind"], l["ref"]) for l in cur["links"]}
                for l in c.get("links") or []:
                    if (l["provider"], l["kind"], l["ref"]) not in have:
                        changes.append({"field": "link", "from": None, "to": f"{l['kind']} {l['ref']}"})
                if changes:
                    update.append({"key": k, "project": key, "changes": changes, "sources": c["sources"]})
                else:
                    existing.append({"project": key, "key": k, "source": c["sources"][0]["id"] if c["sources"] else "-",
                                     "ref": k, "reason": "ticket already exists, nothing differs"})
            else:
                create.append(c)

    handoff = Path(handoff_dir or HANDOFF_DIR)
    for f in sorted(handoff.glob("*.md")) if handoff.is_dir() else []:
        skipped.append({"project": f.stem, "source": "handoff", "ref": f.name,
                        "reason": "handoff notes are context for a coordinator, not tasks; the file stays as it is"})

    create.sort(key=lambda c: (c["project"], c["number"]))
    return {
        "mode": "preview", "applied": False, "generatedAt": time.time(), "tookMs": round((time.time() - started) * 1000),
        "summary": {"wouldCreate": len(create), "wouldUpdate": len(update), "existing": len(existing), "ambiguous": len(ambiguous),
                    "duplicates": len(duplicates), "skipped": len(skipped)},
        "sources": sources, "wouldCreate": create, "wouldUpdate": update, "existing": existing, "ambiguous": ambiguous,
        "duplicates": duplicates, "skipped": skipped,
        "notes": ["Nothing was written. GitHub issues are not closed, edited or deleted by an import.",
                  "IDs that already use the project prefix, live or retired, are kept (SV-056 stays SV-056, "
                  "GM-014 stays GM-014) and the counter moves past them, so no key is ever reused.",
                  "P0/P1/P2/P3 in INDEX.md map to URGENT/HIGH/MEDIUM/LOW."],
    }


def apply(projects, gh_data, store, actor="system:import", handoff_dir=None):
    """Create every would-create ticket the preview lists. Returns the report.

    One transaction per project: an error rolls that project back whole and is
    listed under `errors`; other projects are unaffected. Existing tickets are
    never edited (wouldUpdate is reported, not applied), ambiguous items are
    never guessed, and a second run finds every provenance link and creates
    nothing.
    """
    pv = preview(projects, gh_data, store, handoff_dir)
    source_counts = {}
    for s in pv["sources"]:
        source_counts.setdefault(s["project"], {})[s["kind"]] = s["count"]
    by_project = {}
    for c in pv["wouldCreate"]:
        by_project.setdefault(c["project"], []).append(c)
    created, archived, keys, errors = 0, 0, [], []
    for project, cands in sorted(by_project.items()):
        made = []
        try:
            with store.batch():
                for c in cands:
                    closed = c["status"] in T.CLOSED
                    fields = {"priority": c.get("priority") or "NO_PRIORITY", "type": c.get("type"),
                              "flags": {f: True for f in c.get("flags") or []}}
                    if c.get("note"):
                        fields["description"] = c["note"]
                    if closed:
                        fields["archived"] = True
                    kw = {"number": c["number"]}
                    if c.get("keepsId"):
                        kw["prefix"] = c["proposedKey"].rsplit("-", 1)[0]
                    store.create(project, c["title"], actor, status=c["status"], **kw, **fields)
                    k = c["proposedKey"]
                    for src in c["sources"]:
                        store.link(k, "legacy", "import_source", src["id"], actor=actor)
                    for l in c.get("links") or []:
                        store.link(k, l["provider"], l["kind"], l["ref"], url=l.get("url"), actor=actor)
                    made.append((k, closed, c.get("blockedBy") or []))
                for k, _closed, deps in made:
                    for d in deps:
                        if d != k and store.exists(d):
                            store.relate(k, "blocked_by", d, actor=actor)
        except T.TaskError as e:
            errors.append({"project": project, "error": str(e), "rolledBack": len(made)})
            continue
        created += len(made)
        archived += sum(1 for _k, closed, _d in made if closed)
        keys += [k for k, _c, _d in made]
    return {
        "mode": "apply", "applied": True, "generatedAt": time.time(), "sourceCounts": source_counts,
        "created": created, "updated": 0, "archived": archived, "existing": len(pv["existing"]),
        "duplicate": len(pv["duplicates"]), "ambiguous": len(pv["ambiguous"]), "skipped": len(pv["skipped"]),
        "pendingUpdates": len(pv["wouldUpdate"]), "errors": errors, "keys": keys,
        "ambiguousItems": pv["ambiguous"], "duplicateItems": pv["duplicates"], "skippedItems": pv["skipped"],
    }
