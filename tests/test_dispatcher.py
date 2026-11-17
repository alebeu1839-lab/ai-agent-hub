import unittest
from hub.dispatcher import Dispatcher, ApprovalRequired, WorkResult, RateLimited

TRANSITIONS = {
    "queued": {"running", "awaiting_approval"},
    "running": {"reviewing", "failed", "rate_limited"},
    "reviewing": {"completed", "queued"}
}

class Store:
    def __init__(self):
        self.tasks = {"task1": {"state": "queued", "output_ref": None}}
        self.history = []

    def get(self, key):
        return dict(self.tasks[key])

    def transition(self, key, state, *, actor, note="", executor=None, output_ref=None):
        old = self.tasks[key]["state"]
        if state not in TRANSITIONS.get(old, set()):
            raise ValueError("bad transition")
        self.tasks[key]["state"] = state
        if output_ref is not None:
            self.tasks[key]["output_ref"] = output_ref
        self.history.append((old, state, actor))
        return self.get(key)

class DispatcherTests(unittest.TestCase):
    def test_worker_review_completion(self):
        store = Store()
        dispatcher = Dispatcher(store, workers={"mock": lambda _: WorkResult("artifact://mock", "produced")})
        self.assertEqual(dispatcher.run("task1", "mock")["state"], "reviewing")
        self.assertEqual(dispatcher.approve_review("task1", reviewer="qa")["state"], "completed")
        self.assertEqual([x[1] for x in store.history], ["running", "reviewing", "completed"])

    def test_external_action_blocks_before_execution(self):
        store = Store()
        calls = []
        dispatcher = Dispatcher(store, workers={"mock": lambda _: calls.append(1)})
        with self.assertRaises(ApprovalRequired):
            dispatcher.run("task1", "mock", action="send_email")
        self.assertEqual(calls, [])
        self.assertEqual(store.get("task1")["state"], "awaiting_approval")

    def test_unknown_action_fails_closed(self):
        store = Store()
        dispatcher = Dispatcher(store, workers={"mock": lambda _: WorkResult("x")})
        with self.assertRaises(ValueError):
            dispatcher.run("task1", "mock", action="unrecognized_action")
        self.assertEqual(store.get("task1")["state"], "queued")

    def test_rate_limit_saved(self):
        store = Store()
        def limited(_):
            raise RateLimited("provider limit")
        dispatcher = Dispatcher(store, workers={"mock": limited})
        self.assertEqual(dispatcher.run("task1", "mock")["state"], "rate_limited")

    def test_invalid_worker_result_fails(self):
        store = Store()
        dispatcher = Dispatcher(store, workers={"mock": lambda _: None})
        self.assertEqual(dispatcher.run("task1", "mock")["state"], "failed")

    def test_revision_loop(self):
        store = Store()
        dispatcher = Dispatcher(store, workers={"mock": lambda _: WorkResult("artifact://mock")})
        dispatcher.run("task1", "mock")
        self.assertEqual(dispatcher.request_revision("task1", reviewer="qa", reason="fix typo")["state"], "queued")

if __name__ == "__main__":
    unittest.main()
