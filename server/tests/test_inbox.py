"""Needs You v2 (ccd/inbox.py, GET /api/inbox): what v2 knows about each queue item — its pending Approval, the
shadow engine's verdict and precedents for open questions. Read-only: the queue is state.needs, unchanged."""
import unittest

from ccd import inbox
from ccd.daemon import Daemon
from ccd.store import Store

from .helpers import cfg, new_db
from . import test_ledger


class Signature(unittest.TestCase):
    def test_wording_not_noise_decides_a_match(self):
        self.assertEqual(inbox.signature("Should we keep the old export?"), inbox.signature("keep old export"))
        self.assertNotEqual(inbox.signature("Keep the old export?"), inbox.signature("Drop the old export?"))
        self.assertEqual(inbox.signature(None), "")

    def test_keys_and_versions_tell_questions_apart_and_short_ones_never_match(self):
        for a, b in (("Use UTF-8 or UTF-16 here?", "Use UTF-16 or UTF-8 here?"),
                     ("Use SHA-256 for the hashes?", "Use SHA-1 for the hashes?"),
                     ("Close GYST-12 as a duplicate of GYST-10?", "Close GYST-99 as a duplicate of GYST-3?")):
            self.assertNotEqual(inbox.signature(a), inbox.signature(b), (a, b))
        for short in ("Proceed?", "OK?", "Merge it?"):
            self.assertEqual(inbox.signature(short), "", short)


class InTheDaemon(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_ledger.InTheDaemon.asyncSetUp
    asyncTearDown = test_ledger.InTheDaemon.asyncTearDown
    to_ready = test_ledger.InTheDaemon.to_ready

    def ask(self, title, text):
        t, _ = self.ts.create("gyst", title)
        k = t["key"]
        self.d._pipeline_result(*self.d.pipeline.ask(k, [{"text": text, "kind": "yesno"}], "agent:coordinator"))
        return k

    def answer(self, k, value):
        qid = self.d.pipeline.work(k)["questions"][0]["id"]
        self.d._pipeline_result(*self.d.pipeline.answer(k, [{"id": qid, "answer": value}], "jay"))

    async def test_a_gate_item_carries_its_pending_approval_and_the_engines_verdict(self):
        k, _ = self.to_ready()
        out = self.d.inbox_state()
        self.assertTrue(out["available"])
        item = out["items"][f"gate:gyst:{k}"]
        self.assertEqual(item["approval"]["gate"], "merge")
        self.assertFalse(item["approval"]["overdue"])
        self.assertIn(item["engine"]["engine"], ("auto", "jay", "refuse"))
        self.assertEqual(out["counts"]["approvals"], 1)
        self.assertEqual(out["orphans"], [])
        self.d.ledger.clock = lambda: 10 ** 12          # long after: the approval is overdue
        self.d.inbox.clock = lambda: 10 ** 12
        self.assertTrue(self.d.inbox_state()["items"][f"gate:gyst:{k}"]["approval"]["overdue"])
        self.assertEqual(self.d.inbox_state()["counts"]["overdue"], 1)

    async def test_an_open_question_shows_an_earlier_answer_to_the_same_question_and_nothing_is_applied(self):
        first = self.ask("Export", "Keep the old export?")
        self.answer(first, "no")
        second = self.ask("Export again", "Should we keep the old export?")
        out = self.d.inbox_state()
        [p] = out["items"][f"questions:gyst:{second}"]["precedents"]
        self.assertEqual((p["question"], p["precedents"][0]["decision"], p["precedents"][0]["key"]),
                         ("Should we keep the old export?", "no", first))
        self.assertEqual(out["counts"]["precedentHits"], 1)
        self.assertIsNone(self.d.pipeline.work(second)["questions"][0].get("answer"))   # shown, never applied
        other = self.ask("Unrelated", "Rename the button?")
        self.assertNotIn(f"questions:gyst:{other}", self.d.inbox_state()["items"])

    async def test_a_precedent_from_another_project_does_not_count(self):
        t, _ = self.ts.create("samvision", "Export")
        k = t["key"]
        self.d._pipeline_result(*self.d.pipeline.ask(k, [{"text": "Keep the old export?", "kind": "yesno"}], "agent:c"))
        qid = self.d.pipeline.work(k)["questions"][0]["id"]
        self.d._pipeline_result(*self.d.pipeline.answer(k, [{"id": qid, "answer": "no"}], "jay"))
        second = self.ask("Export", "Keep the old export?")
        self.assertNotIn(f"questions:gyst:{second}", self.d.inbox_state()["items"])

    async def test_a_gate_behind_open_questions_carries_its_approval_and_is_no_orphan(self):
        k, _ = self.to_ready()
        self.d._pipeline_result(*self.d.pipeline.ask(k, [{"text": "Which date format do we use?"}], "agent:c"))
        self.assertEqual([n["kind"] for n in self.d.state()["needs"] if n["ref"] == k], ["questions"])
        out = self.d.inbox_state()
        self.assertEqual(out["orphans"], [])
        self.assertEqual(out["items"][f"questions:gyst:{k}"]["approval"]["gate"], "merge")

    async def test_a_different_kind_of_ask_or_a_task_check_is_never_a_precedent(self):
        first = self.ask("Export", "Keep the old export?")
        self.answer(first, "no")
        t, _ = self.ts.create("gyst", "Export text")
        k = t["key"]
        self.d._pipeline_result(*self.d.pipeline.ask(k, [{"text": "Keep the old export?"}], "agent:c"))   # text, not yes/no
        self.assertNotIn(f"questions:gyst:{k}", self.d.inbox_state()["items"])

    async def test_a_broken_overlay_never_breaks_the_queue(self):
        k, _ = self.to_ready()
        self.d.inbox.enrich = lambda needs: 1 / 0
        out = self.d.inbox_state()
        self.assertEqual((out["available"], out["items"]), (False, {}))
        self.assertIn(k, [n["ref"] for n in self.d.state()["needs"]])


class NoTasks(unittest.IsolatedAsyncioTestCase):
    async def test_no_task_system(self):
        store = Store(new_db())
        try:
            self.assertEqual(Daemon(cfg(), store, None).inbox_state()["available"], False)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
