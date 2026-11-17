import unittest
from hub.providers import Provider, ProviderRegistry, ProviderDisabled, default_registry
from hub.dispatcher import WorkResult

class ProviderTests(unittest.TestCase):
    def test_live_providers_are_disabled(self):
        registry = default_registry()
        self.assertEqual(len(registry.manifest()), 3)
        for entry in registry.manifest():
            self.assertFalse(entry["can_execute"])
            with self.assertRaises(ProviderDisabled):
                registry.execute(entry["name"], {"task_id": "t"})

    def test_mock_execute(self):
        registry = ProviderRegistry()
        registry.register(Provider("mock-gpt", "mock", True, "local-memory"),
                          handler=lambda task: WorkResult("mock://" + task["task_id"]))
        self.assertEqual(registry.execute("mock-gpt", {"task_id": "t"}).output_ref, "mock://t")

    def test_no_live_mode(self):
        with self.assertRaises(ValueError):
            Provider("gpt", "live", True, "api")

    def test_no_empty_task(self):
        registry=ProviderRegistry()
        registry.register(Provider("mock","mock",True),
                          handler=lambda task: WorkResult("mock://ok"))
        with self.assertRaises(ValueError):
            registry.execute("mock", {})
