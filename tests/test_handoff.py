from __future__ import annotations

import unittest
from uuid import NAMESPACE_URL, uuid5

from hub.handoff import select_next


def child(gid, title, **kw):
    return {"id": make_id(gid), "title": title, **kw}


def make_id(name):
    value = uuid5(NAMESPACE_URL, name).hex
    return f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:]}"


class SelectNextTests(unittest.TestCase):
    def test_first_runnable_child_keeps_display_order(self):
        kids = [child("a", "first", body=f"依存: {make_id('blocker')}"),
                child("b", "second"), child("c", "third"),
                child("blocker", "公開 blocker")]
        selection = select_next({}, kids, set(), set(), {})
        self.assertEqual(selection.next["id"], make_id("b"))
        self.assertEqual(selection.skipped, [(make_id("a"), "blocked_by_dependency"),
                                             (make_id("blocker"), "needs_owner_approval")])
        self.assertEqual([c["id"] for c in selection.remaining],
                         [make_id("a"), make_id("b"), make_id("c"), make_id("blocker")])

    def test_empty_children_has_no_selection(self):
        selection = select_next({}, [], set(), set(), {})
        self.assertIsNone(selection.next)
        self.assertEqual(selection.remaining, [])

    def test_each_exclusion_reason(self):
        kids = [
            child("dep", "dependency", body="依存：blocker"),
            child("wait", "waiting", comments=[{"body": "承認待ち"}]),
            child("done", "completed", status="COMPLETED"),
            child("duplicate", "【別】 same title", status="DONE"),
            child("duplicate2", "【prefix】same   title"),
            child("claimed", "claimed", comments=[{"body": "[ai-agent-hub:claim task=x]"}]),
            child("stopped", "stopped", comments=[{"body": "[ai-agent-hub:stop]"}]),
            child("approval", "リリース公開"),
        ]
        # Give the dependency a live sibling so it blocks.
        kids[0]["body"] = f"依存：{make_id('blocker-id')}"
        kids.append(child("blocker-id", "blocker", body="公開"))
        selection = select_next({}, kids, set(), {f"addness-{make_id('claimed')}"}, {})
        reasons = dict(selection.skipped)
        self.assertEqual(reasons[make_id("dep")], "blocked_by_dependency")
        self.assertEqual(reasons[make_id("wait")], "waiting_approval")
        self.assertEqual(reasons[make_id("done")], "completed")
        self.assertEqual(reasons[make_id("duplicate2")], "duplicate_title")
        self.assertEqual(reasons[make_id("claimed")], "in_progress_elsewhere")
        self.assertEqual(reasons[make_id("stopped")], "stopped")
        self.assertEqual(reasons[make_id("approval")], "needs_owner_approval")

    def test_claim_with_done_marker_is_not_in_progress(self):
        kids = [child("x", "x", comments=[{"body": "[ai-agent-hub:claim x]\n[ai-agent-hub:done x]"}])]
        self.assertEqual(select_next({}, kids, set(), set(), {}).next["id"], make_id("x"))

    def test_already_in_today_is_preserved_without_next(self):
        kids = [child("x", "already"), child("y", "later")]
        selection = select_next({}, kids, {make_id("x")}, set(), {})
        self.assertIsNone(selection.next)
        self.assertEqual(selection.skipped, [(make_id("x"), "already_queued_next")])

    def test_deleted_child_and_invalid_uuid_are_excluded(self):
        kids = [child("deleted", "gone", deleted=True), {"id": "not-a-uuid", "title": "bad"}]
        selection = select_next({}, kids, set(), set(), {})
        self.assertEqual(selection.skipped, [(make_id("deleted"), "deleted"),
                                             ("not-a-uuid", "invalid_id")])


if __name__ == "__main__":
    unittest.main()
