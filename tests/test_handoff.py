from __future__ import annotations

import unittest

from hub.handoff import select_next


def child(gid, title, **kw):
    return {"id": gid, "title": title, **kw}


class SelectNextTests(unittest.TestCase):
    def test_first_runnable_child_keeps_display_order(self):
        kids = [child("a", "first", body="依存: blocker"),
                child("b", "second"), child("c", "third"),
                child("blocker", "公開 blocker")]
        selection = select_next({}, kids, set(), set(), {})
        self.assertEqual(selection.next["id"], "b")
        self.assertEqual(selection.skipped, [("a", "blocked_by_dependency"),
                                             ("blocker", "needs_owner_approval")])
        self.assertEqual([c["id"] for c in selection.remaining], ["a", "b", "c", "blocker"])

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
        kids[0]["body"] = "依存：blocker-id"
        kids.append(child("blocker-id", "blocker", body="公開"))
        selection = select_next({}, kids, set(), {"addness-claimed"}, {})
        reasons = dict(selection.skipped)
        self.assertEqual(reasons["dep"], "blocked_by_dependency")
        self.assertEqual(reasons["wait"], "waiting_approval")
        self.assertEqual(reasons["done"], "completed")
        self.assertEqual(reasons["duplicate2"], "duplicate_title")
        self.assertEqual(reasons["claimed"], "in_progress_elsewhere")
        self.assertEqual(reasons["stopped"], "stopped")
        self.assertEqual(reasons["approval"], "needs_owner_approval")

    def test_claim_with_done_marker_is_not_in_progress(self):
        kids = [child("x", "x", comments=[{"body": "[ai-agent-hub:claim x]\n[ai-agent-hub:done x]"}])]
        self.assertEqual(select_next({}, kids, set(), set(), {}).next["id"], "x")

    def test_already_in_today_is_preserved_without_next(self):
        kids = [child("x", "already"), child("y", "later")]
        selection = select_next({}, kids, {"x"}, set(), {})
        self.assertIsNone(selection.next)
        self.assertEqual(selection.skipped, [("x", "already_queued_next")])


if __name__ == "__main__":
    unittest.main()
