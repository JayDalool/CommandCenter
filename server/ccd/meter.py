"""Token and cost metering (v2 Phase 1, PR 7; docs/COMMANDCENTER_V2_DISCOVERY.md Phase 1 item 7).

Measured, not guessed: the agents' own session logs on this machine carry the API's usage for every model reply.

    claude    ~/.claude/projects/**/*.jsonl      assistant lines: message.model, message.usage (input, output,
                                                 cache read, cache write 5m/1h), cwd, gitBranch, sessionId
    codex     ~/.codex/sessions/**/*.jsonl       token_count events (last_token_usage), model from turn_context,
                                                 cwd from session_meta
    reported  a work step's optional `usage` object (an agent reporting its own spend)

Only the usage fields, model, time, session id, working directory and branch are read; message text is never stored.
Each reply is one `usage_records` row (deduplicated by message id or file position). Rows are tied to a project
by working directory and to a ticket by a ticket key in the directory or branch name.

Cost is an ESTIMATE at Anthropic list prices (PRICES, as of PRICES_AS_OF), not a bill: a subscription plan is not
charged per token, and Codex has no price here (tokens only). Budgets from a profile's `target.budget` are shown
against month-to-date usage; nothing is stopped when one is passed (enforcement is Phase 2).
"""
import datetime
import glob
import json
import os
import re
import time

PRICES_AS_OF = "2026-10-06"
# USD per million tokens: (input, output, cache read). Cache writes: 1.25 x input (5 min), 2 x input (1 h).
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25), "claude-mythos-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.0), "claude-mythos-5": (10.0, 50.0, 1.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20), "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50), "claude-opus-4-7": (5.0, 25.0, 0.50), "claude-opus-4-6": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20), "claude-sonnet-5": (2.0, 10.0, 0.20), "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01), "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
MAX_BYTES_PER_SCAN = 8 * 1024 * 1024
MAX_FILES = 5000
MAX_AGE_DAYS = 60
MAX_LINE = 4 * 1024 * 1024
KEY_IN_TEXT = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{0,8}-\d{1,6})(?![A-Za-z0-9])")


def price_of(model):
    """The list price row for a model id, by the longest matching prefix; None when unknown."""
    if not isinstance(model, str):
        return None
    best = max((k for k in PRICES if model.startswith(k)), key=len, default=None)
    return PRICES[best] if best else None


def cost_usd(model, inp, out, cache_read, write_5m, write_1h):
    p = price_of(model)
    if p is None:
        return None
    i, o, r = p
    return round((inp * i + out * o + cache_read * r + write_5m * i * 1.25 + write_1h * i * 2.0) / 1e6, 6)


def _ts(value):
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def parse_claude(obj):
    """A usage row from one Claude Code transcript line, or None."""
    if not isinstance(obj, dict) or obj.get("type") != "assistant":
        return None
    msg = obj.get("message")
    if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
        return None
    model = msg.get("model")
    if not isinstance(model, str) or model.startswith("<"):
        return None
    u = msg["usage"]
    cc = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
    w1h, w5m = _int(cc.get("ephemeral_1h_input_tokens")), _int(cc.get("ephemeral_5m_input_tokens"))
    write = _int(u.get("cache_creation_input_tokens"))
    if w1h + w5m == 0:
        w5m = write
    ref = msg.get("id") or obj.get("requestId") or obj.get("uuid")
    if not isinstance(ref, str):
        return None
    inp, out, read = _int(u.get("input_tokens")), _int(u.get("output_tokens")), _int(u.get("cache_read_input_tokens"))
    return {"source": "claude", "ref": ref[:120], "at": _ts(obj.get("timestamp")), "session": obj.get("sessionId"),
            "model": model[:80], "input": inp, "output": out, "cache_read": read, "cache_write": w5m + w1h,
            "cost": cost_usd(model, inp, out, read, w5m, w1h), "cwd": obj.get("cwd"), "branch": obj.get("gitBranch")}


def parse_codex(obj, ctx):
    """A usage row from one Codex rollout line, or None. `ctx` carries cwd/model/session across lines."""
    if not isinstance(obj, dict):
        return None
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    kind = obj.get("type")
    if kind == "session_meta":
        ctx["cwd"], ctx["session"] = payload.get("cwd"), payload.get("id")
        return None
    if kind == "turn_context":
        if isinstance(payload.get("model"), str):
            ctx["model"] = payload["model"]
        if isinstance(payload.get("cwd"), str):
            ctx["cwd"] = payload["cwd"]
        return None
    if kind != "event_msg" or payload.get("type") != "token_count":
        return None
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    last = info.get("last_token_usage") if isinstance(info.get("last_token_usage"), dict) else None
    if last is None:
        return None
    # Codex repeats a token_count (e.g. on rate-limit updates) without new usage: the running total is unchanged.
    total = json.dumps(info.get("total_token_usage"), sort_keys=True) if info.get("total_token_usage") else None
    if total is not None and total == ctx.get("total"):
        return None
    ctx["total"] = total
    cached = _int(last.get("cached_input_tokens"))
    return {"source": "codex", "ref": None, "at": _ts(obj.get("timestamp")), "session": ctx.get("session"),
            "model": str(ctx.get("model") or "codex")[:80], "input": max(0, _int(last.get("input_tokens")) - cached),
            "output": _int(last.get("output_tokens")), "cache_read": cached, "cache_write": 0, "cost": None,
            "cwd": ctx.get("cwd"), "branch": None}


def _read_file(source, path, offset, limit, ctx):
    """Whole lines from `offset`, at most `limit` bytes. A line longer than MAX_LINE is skipped, not waited on."""
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(limit)
    end = data.rfind(b"\n")
    if end < 0:
        if len(data) >= MAX_LINE:
            with open(path, "rb") as f:          # skip to the end of the overlong line
                f.seek(offset + len(data))
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        return [], offset + len(data), ctx, len(data)
                    nl = chunk.find(b"\n")
                    if nl >= 0:
                        return [], f.tell() - len(chunk) + nl + 1, ctx, len(data)
        return [], offset, ctx, len(data)
    rows, pos = {}, 0
    for line in data[:end + 1].splitlines(keepends=True):
        line_at = offset + pos
        pos += len(line)
        if len(line) > MAX_LINE or (b'"usage"' not in line and b"token_count" not in line
                                    and b"session_meta" not in line and b"turn_context" not in line):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        r = parse_claude(obj) if source == "claude" else parse_codex(obj, ctx)
        if r is None:
            continue
        if r["ref"] is None:
            r["ref"] = f"{os.path.basename(path)}:{line_at}"[-200:]
        # Claude Code logs one line per content block, all with the reply's id; keep the fullest count.
        if r["ref"] not in rows or r["output"] > rows[r["ref"]]["output"]:
            rows[r["ref"]] = r
    return list(rows.values()), offset + end + 1, ctx, end + 1


class Meter:
    """Three steps so the slow part never touches the database from another thread:
    `plan()` (event loop: cursors) → `read(plan)` (any thread: files only) → `store(results)` (event loop)."""

    def __init__(self, db, roots=None, attribute=None, clock=time.time):
        """`roots`: [(source, directory)]. `attribute(cwd, branch)` → (project, ticket_key)."""
        home = os.path.expanduser("~")
        self.db = db
        self.roots = roots if roots is not None else [("claude", os.path.join(home, ".claude", "projects")),
                                                      ("codex", os.path.join(home, ".codex", "sessions"))]
        self.attribute = attribute or (lambda cwd, branch: (None, None))
        self.clock = clock

    def plan(self):
        cursors = {r[0]: (r[1], r[2], r[3]) for r in self.db.execute("SELECT path, inode, offset, context FROM usage_cursor")}
        return [(source, root, cursors) for source, root in self.roots]

    @staticmethod
    def read(plan, budget=MAX_BYTES_PER_SCAN):
        """Files only (safe off the event loop): what is new in every log, up to `budget` bytes in all."""
        results = []
        for source, root, cursors in plan:
            if not os.path.isdir(root):
                continue
            found = []
            for p in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
                try:
                    found.append((os.stat(p), p))
                except OSError:
                    continue
            found.sort(key=lambda x: -x[0].st_mtime)                     # newest first
            for st, path in found[:MAX_FILES]:
                if budget <= 0:
                    return results
                if path not in cursors and st.st_mtime < time.time() - MAX_AGE_DAYS * 86400:
                    continue                                              # history older than this is not metered
                inode, offset, ctx = cursors.get(path, (st.st_ino, 0, "{}"))
                try:
                    ctx = json.loads(ctx or "{}")
                except ValueError:
                    ctx = {}
                if inode != st.st_ino or offset > st.st_size:   # replaced or truncated: read again (rows dedupe)
                    inode, offset, ctx = st.st_ino, 0, {}
                if offset == st.st_size:
                    continue
                try:
                    rows, offset, ctx, used = _read_file(source, path, offset, min(budget, st.st_size - offset), ctx)
                except OSError:
                    continue
                budget -= max(used, 1)
                results.append((path, inode, offset, ctx, rows))
        return results

    def store(self, results):
        """Event loop: insert the rows and move each cursor, one transaction per file (a savepoint inside a caller's
        transaction). Attribution is worked out once per (directory, branch) per pass. Returns rows added."""
        added, seen = 0, {}
        for path, inode, offset, ctx, rows in results:
            own = not self.db.in_transaction
            self.db.execute("BEGIN IMMEDIATE" if own else "SAVEPOINT meter_store")
            try:
                for r in rows:
                    where = (r.get("cwd"), r.get("branch"))
                    if where not in seen:
                        seen[where] = self.attribute(*where)
                    project, key = seen[where]
                    cur = self.db.execute(
                        "INSERT OR IGNORE INTO usage_records (at, source, ref, session, project, ticket_key, model, "
                        "input, output, cache_read, cache_write, cost_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r["at"] or self.clock(), r["source"], r["ref"],
                         str(r["session"])[:80] if r.get("session") else None, project, key, r["model"], r["input"],
                         r["output"], r["cache_read"], r["cache_write"], r["cost"]))
                    added += cur.rowcount
                self.db.execute("INSERT INTO usage_cursor (path, inode, offset, context) VALUES (?,?,?,?) "
                                "ON CONFLICT(path) DO UPDATE SET inode=excluded.inode, offset=excluded.offset, "
                                "context=excluded.context", (path, inode, offset, json.dumps(ctx)[:2000]))
                self.db.execute("COMMIT" if own else "RELEASE meter_store")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK" if own else "ROLLBACK TO meter_store")
                    if not own:
                        self.db.execute("RELEASE meter_store")
                raise
        return added

    def scan(self, budget=MAX_BYTES_PER_SCAN):
        """All three steps in this thread (tests, tools)."""
        return self.store(self.read(self.plan(), budget))

    def report(self, ref, project, ticket_key, actor, usage):
        """A work step's own `usage` ({model, inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens}).
        Recorded as reported; ignored when malformed. Returns True when a row was added."""
        if not isinstance(usage, dict):
            return False
        model = usage.get("model") if isinstance(usage.get("model"), str) else None
        inp, out = _int(usage.get("inputTokens")), _int(usage.get("outputTokens"))
        read, write = _int(usage.get("cacheReadTokens")), _int(usage.get("cacheWriteTokens"))
        if inp + out + read + write == 0 or max(inp, out, read, write) > 10 ** 9:
            return False
        with self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO usage_records (at, source, ref, project, ticket_key, actor, model, input, output, "
                "cache_read, cache_write, cost_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.clock(), "reported", str(ref)[:200], project, ticket_key, actor, model and model[:80], inp, out,
                 read, write, cost_usd(model, inp, out, read, write, 0)))
        return cur.rowcount > 0

    def summary(self, days=14, budgets=None):
        """Totals for the window: by project, model, day and ticket, plus month-to-date against budgets."""
        now = self.clock()
        since = now - days * 86400
        cols = "COUNT(*), SUM(input), SUM(output), SUM(cache_read), SUM(cache_write), SUM(cost_usd), " \
               "SUM(cost_usd IS NULL)"

        # Totals come from the logs only: an agent's own `reported` usage is usually the same replies again, so it is
        # shown under bySource and never added in.
        measured = "source != 'reported'"

        def rows(group, where=measured):
            return [dict(zip(("key", "replies", "input", "output", "cacheRead", "cacheWrite", "costUsd", "unpriced"),
                             (r[0],) + tuple(x or 0 for x in r[1:])))
                    for r in self.db.execute(f"SELECT {group}, {cols} FROM usage_records WHERE at >= ? AND {where} "
                                             f"GROUP BY 1 ORDER BY 7 DESC, 4 DESC LIMIT 50", (since,))]
        total = self.db.execute(f"SELECT {cols} FROM usage_records WHERE at >= ? AND {measured}", (since,)).fetchone()
        month = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).replace(day=1, hour=0, minute=0, second=0,
                                                                                   microsecond=0).timestamp()
        mtd = {r[0]: {"costUsd": r[1] or 0, "tokens": r[2] or 0} for r in self.db.execute(
            "SELECT project, SUM(cost_usd), SUM(input + output + cache_read + cache_write) FROM usage_records "
            f"WHERE at >= ? AND {measured} GROUP BY project", (month,))}
        out_budgets = []
        for project, b in sorted((budgets or {}).items()):
            spent = mtd.get(project, {"costUsd": 0, "tokens": 0})
            out_budgets.append({"project": project, "monthlyUsd": b.get("monthly_usd"),
                                "monthlyTokens": b.get("monthly_tokens"), "spentUsd": round(spent["costUsd"], 4),
                                "spentTokens": spent["tokens"]})
        return {"days": days, "since": since, "pricesAsOf": PRICES_AS_OF,
                "total": dict(zip(("replies", "input", "output", "cacheRead", "cacheWrite", "costUsd", "unpriced"),
                                  tuple(x or 0 for x in total))),
                "byProject": rows("COALESCE(project, '(unattributed)')"), "byModel": rows("COALESCE(model, '?')"),
                "byDay": rows("date(at, 'unixepoch')"), "byTicket": [r for r in rows("ticket_key") if r["key"]][:10],
                "bySource": rows("source", "1"), "budgets": out_budgets}
