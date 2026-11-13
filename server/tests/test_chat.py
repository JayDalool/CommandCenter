"""Messages: Jay's conversations with the CTO and each project lead (ccd/chat.py, ccd/leadchat.py, ccd/chat_cli.py)."""
import asyncio
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from ccd import chat as chat_mod
from ccd import chat_cli
from ccd import leadchat

from .test_api import ApiBase, JSON, AUTH

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
PDF = b"%PDF-1.7\n" + b"x" * 40
EMPTY_PROMPT = "assistant text\n╭" + "─" * 20 + "╮\n│ > " + " " * 16 + "│\n╰" + \
    "─" * 20 + "╯"


async def _chunks(data, size=7):
    for i in range(0, len(data), size):
        yield data[i:i + size]


class Store(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="chat-")
        self.now = [1000.0]
        self.chat = chat_mod.Chat(os.path.join(self.base, "chat.db"), os.path.join(self.base, "files"), 4096,
                                  clock=lambda: self.now[0])

    def tearDown(self):
        self.chat.close()
        shutil.rmtree(self.base)

    def up(self, data, name, side="jay", conv="samvision"):
        return asyncio.run(self.chat.upload(conv, side, "jay" if side == "jay" else "agent:lead", name, _chunks(data)))

    def test_files_are_private_and_typed_from_their_bytes(self):
        self.assertEqual(os.stat(os.path.join(self.base, "chat.db")).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(os.path.join(self.base, "files")).st_mode & 0o777, 0o700)
        self.assertEqual(self.up(PNG, "shot.png")["mime"], "image/png")
        self.assertEqual(self.up(PNG, "renamed.pdf")["mime"], "image/png")          # bytes decide, not the name
        self.assertEqual(self.up(PDF, "plan.pdf")["kind"], "pdf")
        self.assertEqual(self.up("# Plan\nété\n".encode(), "notes.md")["mime"], "text/markdown")
        self.assertEqual(self.up(b"hi", "a.txt")["mime"], "text/plain")
        for data, name in ((b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>", "x.svg"),
                           (b"<html><script>alert(1)</script></html>", "x.html"),
                           (b"<svg onload=alert(1)>", "x.md.svg"), (b"MZ\x90\x00" + b"\x00" * 30, "x.exe"),
                           (b"# ok\n\xff\xfe broken", "bad.md"), (b"# has\x00nul" + b"x" * 20, "nul.md"), (b"", "e.md")):
            with self.assertRaises(chat_mod.ChatError, msg=name) as e:
                self.up(data, name)
            self.assertEqual(e.exception.status, 415, name)
        with self.assertRaises(chat_mod.ChatError) as e:
            self.up(PNG + b"\x00" * 5000, "big.png")
        self.assertEqual(e.exception.status, 413)
        self.assertEqual(len(os.listdir(os.path.join(self.base, "files"))), 5)   # refused uploads leave nothing

    def test_names_never_become_paths(self):
        f = self.up(PNG, "../../etc/‮passwd.png")
        self.assertEqual(f["name"], "passwd.png")
        self.assertEqual(os.listdir(os.path.join(self.base, "files")), [f["id"]])

    def test_a_message_takes_only_the_senders_own_unsent_files_of_that_conversation(self):
        mine = self.up(PNG, "a.png")
        theirs = self.up(PNG, "b.png", side="lead")
        other = self.up(PNG, "c.png", conv="gyst")
        for fid in (theirs["id"], other["id"], "0" * 32, "../x"):
            with self.assertRaises(chat_mod.ChatError):
                self.chat.add("samvision", "jay", "jay", "look", file_ids=[fid])
        m = self.chat.add("samvision", "jay", "jay", "", file_ids=[mine["id"]])     # a file alone is a message
        self.assertEqual([f["id"] for f in m["files"]], [mine["id"]])
        with self.assertRaises(chat_mod.ChatError):                                  # never sent twice
            self.chat.add("samvision", "jay", "jay", "again", file_ids=[mine["id"]])

    def test_text_rules(self):
        for bad, status in (("", 400), ("   ", 400), ("x" * (chat_mod.TEXT_MAX + 1), 413), ("bell\x07", 400),
                            ("my key is ghp_abcdefghijklmnop1234", 400), ("password: hunter22", 400),
                            ("https://user:pw@host/x", 400)):
            with self.assertRaises(chat_mod.ChatError, msg=bad[:20]) as e:
                self.chat.add("samvision", "jay", "jay", bad)
            self.assertEqual(e.exception.status, status)
        m = self.chat.add("samvision", "jay", "jay", "  line one\r\nline two\t ok  ")
        self.assertEqual(m["text"], "line one\nline two\t ok")

    def test_unseen_seen_summary_and_history_are_kept(self):
        a = self.chat.add("samvision", "jay", "jay", "first")
        self.chat.add("samvision", "jay", "jay", "second")
        self.chat.add("samvision", "lead", "agent:lead-samvision", "answer", reply_to=a["id"])
        with self.assertRaises(chat_mod.ChatError):
            self.chat.add("gyst", "lead", "agent:x", "wrong thread", reply_to=a["id"])
        self.assertEqual([m["text"] for m in self.chat.unseen("samvision", "jay")], ["first", "second"])
        s = self.chat.summary()["samvision"]
        self.assertEqual((s["unread"], s["waiting"], s["last"]["text"]), (1, 2, "answer"))
        self.assertEqual(self.chat.unread_for_jay(), {"samvision": 1})
        self.chat.nudged("samvision")
        self.assertEqual(self.chat.mark_seen("samvision", "jay", a["id"]), 1)
        self.assertEqual(self.chat.nudge_state("samvision")["count"], 0)              # reading resets the reminders
        self.assertEqual(self.chat.waiting_conversations(), ["samvision"])
        self.assertEqual(self.chat.mark_seen("samvision", "jay"), 1)
        self.assertEqual(self.chat.waiting_conversations(), [])
        self.assertEqual([m["text"] for m in self.chat.history("samvision", limit=2)], ["second", "answer"])
        self.assertEqual([m["text"] for m in self.chat.history("samvision", before=a["id"] + 1)], ["first"])

    def test_unsent_files_are_pruned_after_a_day_and_sent_ones_kept(self):
        sent = self.up(PNG, "a.png")
        self.chat.add("samvision", "jay", "jay", "x", file_ids=[sent["id"]])
        left = self.up(PNG, "b.png")
        self.now[0] += chat_mod.PENDING_TTL + 1
        self.assertEqual(self.chat.prune_pending(), 1)
        self.assertEqual(os.listdir(os.path.join(self.base, "files")), [sent["id"]])
        with self.assertRaises(chat_mod.ChatError):
            self.chat.file(left["id"])


    def test_review_fixes_in_the_store(self):
        # the saved name always ends in its type's extension
        self.assertEqual(self.up(PNG, "renamed.pdf")["name"], "renamed.pdf.png")
        self.assertEqual(self.up(PNG, "run.bat")["name"], "run.bat.png")
        self.assertEqual(self.up(PNG, "Shot.JPG.png")["name"], "Shot.JPG.png")
        self.assertEqual(self.up(b"# hi\n", "notes.markdown")["name"], "notes.markdown")
        # secrets in a text file or a name, escape codes and bidi controls in text
        for data, name, status in ((b"# conf\ntoken: abcdefgh\n", "c.md", 400), (PNG, "ghp_abcdefghijklmnop.png", 400),
                                   (b"# red \x1b[31m text", "e.md", 415), ("a \u202e b".encode(), "b.txt", 415)):
            with self.assertRaises(chat_mod.ChatError, msg=name) as e:
                self.up(data, name)
            self.assertEqual(e.exception.status, status, name)
        self.assertEqual(self.up(b"line\r\nnext\r\n", "crlf.txt")["kind"], "markdown")
        for text in ("evil \u202egnp.exe", "zero\u200bwidth", "esc \x1b[2J", "c1 \x9b"):
            with self.assertRaises(chat_mod.ChatError, msg=repr(text)):
                self.chat.add("samvision", "jay", "jay", text)
        self.assertEqual(self.chat.add("samvision", "jay", "jay", "tabs\tand\nlines, émoji 👍")["text"],
                         "tabs\tand\nlines, émoji 👍")
        # ids are bounded
        for bad in (-1, 0, 2 ** 63, True, "3"):
            with self.assertRaises(chat_mod.ChatError, msg=repr(bad)):
                self.chat.add("samvision", "jay", "jay", "x", reply_to=bad)
            with self.assertRaises(chat_mod.ChatError, msg=repr(bad)):
                self.chat.mark_seen("samvision", "jay", bad)

    def test_pending_files_are_capped_and_orphan_blobs_swept(self):
        for i in range(chat_mod.PENDING_MAX):
            self.up(PNG, f"{i}.png", conv="gyst")
        with self.assertRaises(chat_mod.ChatError) as e:
            self.up(PNG, "one-more.png", conv="gyst")
        self.assertEqual(e.exception.status, 429)
        self.up(PNG, "other.png", side="lead", conv="gyst")                          # per side
        orphan = os.path.join(self.base, "files", "f" * 32)
        open(orphan, "wb").close()
        keep = os.path.join(self.base, "files", "notes.txt")                          # not a blob name: left alone
        open(keep, "wb").close()
        self.chat.close()
        self.chat = chat_mod.Chat(os.path.join(self.base, "chat.db"), os.path.join(self.base, "files"), 4096)
        self.assertFalse(os.path.exists(orphan))
        self.assertTrue(os.path.exists(keep))
        self.assertEqual(len(os.listdir(os.path.join(self.base, "files"))), chat_mod.PENDING_MAX + 2)


class ChatApi(ApiBase):
    LEAD = dict(JSON, **{"x-ccd-actor": "agent:lead-samvision"})

    def equip(self, daemon):
        self.base = tempfile.mkdtemp(prefix="chatapi-")
        daemon.chat = chat_mod.Chat(os.path.join(self.base, "chat.db"), os.path.join(self.base, "files"), 1 << 20)
        self.started = []

        def starter(argv):
            self.started.append(argv)
            if argv[:2] == ["workspace", "create"]:
                return 0, json.dumps({"result": {"root_pane": {"pane_id": "wL:p1"}}}), ""
            self.fake.add_agent("wL:p1", self.cto_root, name="cto")
            return 0, "{}", ""
        daemon.chat_starter = starter
        self.cto_root = os.path.join(self.base, "home")
        os.makedirs(self.cto_root)
        daemon.cfg["chat_cto_root"] = self.cto_root

    def tearDown(self):
        super().tearDown()
        self.daemon.chat.close()
        shutil.rmtree(self.base)

    def prompts(self):
        return [p for m, p in self.fake.calls if m == "agent.prompt"]

    def send(self, conv, text, headers=JSON, **kw):
        return self.client.post(f"/api/chat/{conv}/messages", content=json.dumps(dict(text=text, **kw)),
                                headers=headers)

    def upload(self, conv, name, data, headers=AUTH):
        return self.client.post(f"/api/chat/files?conversation={conv}&name={name}", content=data,
                                headers=dict(headers, **{"content-type": "application/octet-stream"}))

    def test_conversations_are_the_cto_and_each_project(self):
        body = self.get("/api/chat").json()
        ids = [c["id"] for c in body["conversations"]]
        self.assertEqual(ids, ["cto", "samvision", "gyst", "mfe", "gauzemate", "commandcenter"])
        by = {c["id"]: c for c in body["conversations"]}
        self.assertEqual((by["samvision"]["lead"]["running"], by["samvision"]["lead"]["idle"]), (True, True))
        self.assertFalse(by["cto"]["lead"]["running"])
        self.assertTrue(by["gauzemate"]["lead"]["paused"])
        self.assertNotIn("root", json.dumps(body))                                   # no server paths leave
        self.assertEqual(self.get("/api/chat/nope").status_code, 404)
        self.assertEqual(self.client.get("/api/chat").status_code, 401)

    def test_jays_message_is_stored_and_the_idle_lead_gets_only_the_fixed_nudge(self):
        self.fake.tails["wE:p2"] = EMPTY_PROMPT
        words = "Please draw the auth flow as a diagram"
        r = self.send("samvision", words)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["delivery"], "nudged")
        sent = self.prompts()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["target"], "wE:p2")
        self.assertEqual(sent[0]["text"], leadchat.NUDGE_TEXT.format(conv="samvision", bin=leadchat.SCRIPTS))
        self.assertNotIn("auth flow", sent[0]["text"])                              # C2 b: never Jay's words
        kinds = [e["kind"] for e in self.store.since(0)]
        self.assertIn("chat.sent", kinds)
        self.assertNotIn(words, json.dumps(self.store.since(0)))                    # events carry no text

    def test_a_draft_in_the_leads_input_line_or_a_busy_lead_queues_and_the_tick_nudges_later(self):
        self.fake.tails["wE:p2"] = EMPTY_PROMPT.replace("> " + " " * 16, "> half a sentence Jay is typing")
        self.assertEqual(self.send("samvision", "one").json()["delivery"], "queued")
        self.fake.set_status("wE:p2", "working")
        self.assertEqual(self.send("samvision", "two").json()["delivery"], "queued")
        self.assertEqual(self.prompts(), [])
        self.fake.set_status("wE:p2", "idle")
        self.fake.tails["wE:p2"] = EMPTY_PROMPT
        self.client.portal.call(self.daemon.chat_tick)
        self.assertEqual(len(self.prompts()), 1)                                     # one nudge for both
        self.client.portal.call(self.daemon.chat_tick)
        self.assertEqual(len(self.prompts()), 1)                                     # not again within NUDGE_EVERY
        later = time.time() + leadchat.NUDGE_EVERY + 1
        for _ in range(5):
            self.client.portal.call(lambda: self.daemon.chat_tick(now=later))
            later += leadchat.NUDGE_EVERY + 1
        self.assertEqual(len(self.prompts()), leadchat.NUDGE_MAX)                    # then it stops reminding

    def test_offline_and_paused_leads(self):
        self.assertEqual(self.send("gyst", "hello").json()["delivery"], "lead-offline")
        self.assertEqual(self.send("gauzemate", "hello").json()["delivery"], "lead-paused")
        self.assertEqual(self.prompts(), [])

    def test_the_lead_reads_its_inbox_and_replies_with_files(self):
        self.send("samvision", "first")
        self.send("samvision", "second")
        self.assertEqual(self.get("/api/chat/samvision/inbox").status_code, 403)    # Jay reads the conversation
        peek = self.get("/api/chat/samvision/inbox?peek=1", headers=self.LEAD).json()
        self.assertEqual(len(peek["messages"]), 2)
        box = self.get("/api/chat/samvision/inbox", headers=self.LEAD).json()
        self.assertEqual([m["text"] for m in box["messages"]], ["first", "second"])
        self.assertEqual(self.get("/api/chat/samvision/inbox", headers=self.LEAD).json()["messages"], [])
        f = self.upload("samvision", "flow.png", PNG, headers=dict(AUTH, **{"x-ccd-actor": "agent:lead-samvision"}))
        self.assertEqual(f.status_code, 200, f.text)
        fid = f.json()["file"]["id"]
        r = self.send("samvision", "Here it is", headers=self.LEAD, files=[fid], replyTo=box["messages"][0]["id"])
        self.assertEqual(r.status_code, 200, r.text)
        ev = [e for e in self.store.since(0) if e["kind"] == "chat.reply"][-1]
        self.assertEqual(ev["data"]["messageId"], r.json()["message"]["id"])
        self.assertEqual(self.get("/api/state").json()["chat"], {"unread": 1})
        hist = self.get("/api/chat/samvision").json()["messages"]
        self.assertEqual([(m["side"], m["text"]) for m in hist],
                         [("jay", "first"), ("jay", "second"), ("lead", "Here it is")])
        d = self.get(f"/api/chat/files/{fid}")
        self.assertEqual(d.content, PNG)
        self.assertEqual(d.headers["content-type"], "application/octet-stream")
        self.assertTrue(d.headers["content-disposition"].startswith("attachment;"))
        self.assertIn("sandbox", d.headers["content-security-policy"])
        self.assertEqual(self.post("/api/chat/samvision/seen", {}, headers=self.LEAD).status_code, 403)
        self.assertEqual(self.post("/api/chat/samvision/seen", {}).json()["seen"], 1)
        self.assertEqual(self.get("/api/state").json()["chat"], {"unread": 0})

    def test_uploads_are_checked(self):
        self.assertEqual(self.upload("samvision", "x.svg", b"<svg onload=alert(1)>" + b" " * 20).status_code, 415)
        self.assertEqual(self.upload("nope", "x.png", PNG).status_code, 404)
        r = self.client.post("/api/chat/files?conversation=samvision&name=x.png", content=PNG,
                             headers=dict(AUTH, **{"content-type": "image/png"}))
        self.assertEqual(r.status_code, 415)                                         # octet-stream only
        self.assertEqual(self.get("/api/chat/files/" + "0" * 32).status_code, 404)
        self.assertEqual(self.get("/api/chat/files/..%2F..%2Fetc").status_code, 404)
        bad = self.upload("samvision", "x.png", PNG, headers=dict(AUTH, **{"x-ccd-actor": "nobody"}))
        self.assertEqual(bad.status_code, 400)

    def test_jay_starts_a_stopped_lead_after_the_budget_check(self):
        self.send("cto", "Which repos are active?")
        self.assertEqual(self.post("/api/chat/cto/start", {}).status_code, 409)       # switched off by default
        self.daemon.cfg["chat_start_leads"] = True
        self.assertEqual(self.post("/api/chat/cto/start", {}, headers=dict(JSON, **{"x-ccd-actor": "agent:x"}))
                         .status_code, 403)
        self.daemon.cfg["budgets"] = {"company": {"monthly_usd": 0}}
        r = self.post("/api/chat/cto/start", {})
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json()["needsApproval"])
        self.assertEqual(r.json()["overBudget"][0]["scope"], "company")
        self.assertEqual(self.started, [])                                            # nothing ran
        self.fake.tails["wL:p1"] = EMPTY_PROMPT
        r = self.post("/api/chat/cto/start", {"overBudgetOk": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["started"])
        self.assertEqual(self.started[0], ["workspace", "create", "--cwd", os.path.realpath(self.cto_root),
                                           "--label", "lead cto", "--no-focus"])
        self.assertEqual(self.started[1][:6], ["agent", "start", "cto", "--kind", "claude", "--pane"])
        self.assertIn("chat.over_budget_start", [e["kind"] for e in self.store.since(0)])
        self.assertEqual(r.json()["delivery"], "nudged")
        r = self.post("/api/chat/cto/start", {})                                     # running now: no second one
        self.assertFalse(r.json()["started"])
        self.assertEqual(len(self.started), 2)

    def test_a_paused_project_or_a_lead_waiting_for_adoption_is_never_started(self):
        self.daemon.cfg["chat_start_leads"] = True
        self.assertEqual(self.post("/api/chat/gauzemate/start", {}).status_code, 409)
        self.assertEqual(self.started, [])

    def test_slack_delivery_uses_the_same_store(self):
        self.fake.tails["wE:p2"] = EMPTY_PROMPT
        out = self.client.portal.call(lambda: self.daemon.deliver_to_lead("samvision", "From my phone", via="slack",
                                                                 ref="SV-071"))
        self.assertEqual((out["delivery"], out["message"]["via"], out["message"]["ref"]), ("nudged", "slack", "SV-071"))
        with self.assertRaises(Exception):
            self.client.portal.call(lambda: self.daemon.deliver_to_lead("samvision", "x", author="agent:x"))


    def test_a_lead_is_bound_to_its_own_conversation(self):
        self.send("samvision", "for samvision only")
        other = dict(JSON, **{"x-ccd-actor": "agent:lead-gyst"})
        merge = dict(JSON, **{"x-ccd-actor": "agent:merge-bot"})
        for h in (other, merge):
            self.assertEqual(self.get("/api/chat/samvision/inbox", headers=h).status_code, 403)
            self.assertEqual(self.send("samvision", "spoof", headers=h).status_code, 403)
            self.assertEqual(self.upload("samvision", "x.png", PNG, headers=dict(AUTH, **{"x-ccd-actor": h["x-ccd-actor"]}))
                             .status_code, 403)
        for h in (self.LEAD, other):                                                  # Jay's views are Jay's
            self.assertEqual(self.get("/api/chat", headers=h).status_code, 403)
            self.assertEqual(self.get("/api/chat/samvision", headers=h).status_code, 403)
        f = self.upload("samvision", "a.png", PNG).json()["file"]["id"]
        self.send("samvision", "with a file", files=[f])
        self.assertEqual(self.get(f"/api/chat/files/{f}", headers=self.LEAD).status_code, 200)
        self.assertEqual(self.get(f"/api/chat/files/{f}", headers=other).status_code, 404)
        cto = dict(JSON, **{"x-ccd-actor": "agent:cto"})
        self.assertEqual(self.get("/api/chat/cto/inbox", headers=cto).status_code, 200)
        self.assertEqual(self.get("/api/chat/samvision/inbox", headers=cto).status_code, 403)

    def test_jay_is_rate_limited_per_conversation_and_ids_are_bounded(self):
        for i in range(leadchat.JAY_PER_MINUTE):
            self.assertEqual(self.send("gyst", f"m{i}").status_code, 200)
        self.assertEqual(self.send("gyst", "one too many").status_code, 429)
        self.assertEqual(self.send("mfe", "another conversation").status_code, 200)
        for q in ("before=9" * 1 + "9" * 30, "before=-1", "before=%C2%B2", "limit=1e3"):
            self.assertEqual(self.get(f"/api/chat/mfe?{q}").status_code, 400, q)
        self.assertEqual(self.post("/api/chat/mfe/seen", {"upTo": 2 ** 70}).status_code, 400)


class Cli(unittest.TestCase):
    def test_conversation_from_the_folder_and_actor(self):
        from ccd import registry
        root = registry.PROJECTS["samvision"]["root"]
        self.assertEqual(chat_cli.conversation_here(root + "/web"), "samvision")
        self.assertIsNone(chat_cli.conversation_here("/"))
        self.assertEqual(chat_cli.actor_for("samvision"), "agent:lead-samvision")
        self.assertEqual(chat_cli.actor_for("cto"), "agent:cto")

    def test_a_symlinked_cache_folder_is_refused(self):
        base = tempfile.mkdtemp(prefix="chatcli-")
        elsewhere = tempfile.mkdtemp(prefix="chatcli-x-")
        os.symlink(elsewhere, os.path.join(base, "samvision"))
        msg = {"id": 1, "files": [{"id": "b" * 32, "name": "x.png"}]}
        with mock.patch.object(chat_cli, "CACHE", base), mock.patch.object(chat_cli, "_raw", return_value=(0, PNG)):
            [(f, path, err)] = chat_cli.save_files("samvision", msg, "agent:lead-samvision")
        self.assertIsNone(path)
        self.assertIn("symlink", err)
        self.assertEqual(os.listdir(elsewhere), [])
        shutil.rmtree(base)
        shutil.rmtree(elsewhere)

    def test_inbox_prints_messages_and_saves_files_under_the_cache(self):
        base = tempfile.mkdtemp(prefix="chatcli-")
        msg = {"id": 7, "at": 0, "via": "app", "text": "see attached",
               "files": [{"id": "a" * 32, "name": "../../x.png", "mime": "image/png", "size": 10}]}
        out = io.StringIO()
        with mock.patch.object(chat_cli, "CACHE", base), \
                mock.patch.object(chat_cli, "call", return_value=(0, {"messages": [msg], "recent": []})), \
                mock.patch.object(chat_cli, "_raw", return_value=(0, PNG)):
            self.assertEqual(chat_cli.inbox("samvision", out=out), 0)
        text = out.getvalue()
        self.assertIn("see attached", text)
        saved = os.path.join(base, "samvision", f"7-{'a' * 8}-x.png")
        self.assertIn(saved, text)
        with open(saved, "rb") as fh:
            self.assertEqual(fh.read(), PNG)
        shutil.rmtree(base)


if __name__ == "__main__":
    unittest.main()
