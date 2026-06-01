import threading
import time
import unittest
from types import SimpleNamespace

from runtime.model_budget_policy import ModelBudgetPolicy, ModelBudgetPolicyConfig


def test_config(**overrides):
    data = dict(
        enabled=True,
        queue_enabled=True,
        remote_api_enabled=False,
        cpu_block_percent=999.0,
        ram_block_percent=999.0,
        gpu_block_percent=999.0,
        vram_block_percent=999.0,
        gpu_temp_block_c=999.0,
        main_cooldown_seconds=0.0,
        four_b_cooldown_seconds=0.0,
        default_queue_timeout_seconds=2.0,
        queue_poll_seconds=0.01,
        max_queue_size=8,
        assume_gtx_1650ti_4gb=False,
    )
    data.update(overrides)
    return ModelBudgetPolicyConfig(**data)


class ModelBudgetPolicyQueueTests(unittest.TestCase):
    def test_budget_policy_unconditionally_allows_under_pressure(self):
        policy = ModelBudgetPolicy(test_config(cpu_block_percent=80.0, ram_block_percent=80.0))
        snapshot = policy.capture()
        snapshot.cpu_percent = 97.0
        snapshot.ram_percent = 96.0

        decision = policy.can_run("main_cognition", resource_snapshot=snapshot, reason="pressure_smoke")

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.verdict, "allow")
        self.assertEqual(decision.reason, "queue_only_policy")
        self.assertTrue(decision.debug.get("resource_guard_disabled"))

    def test_budget_policy_ignores_vram_and_gpu_pressure(self):
        policy = ModelBudgetPolicy(test_config(remote_api_enabled=True, cpu_block_percent=80.0, ram_block_percent=80.0))
        snapshot = policy.capture()
        snapshot.cpu_percent = 99.0
        snapshot.ram_percent = 98.0
        snapshot.gpu_util_percent = 95.0
        snapshot.vram_used_mb = 3800.0
        snapshot.vram_total_mb = 4096.0
        policy._active_leases["vision_busy"] = SimpleNamespace(tier="vision_compressor")

        decision = policy.can_run("main_cognition", resource_snapshot=snapshot, reason="remote_main")

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "queue_only_policy")
        self.assertFalse(policy._is_heavy_tier("main_cognition"))

    def test_heavy_models_do_not_overlap(self):
        policy = ModelBudgetPolicy(test_config())
        events = []
        lock = threading.Lock()

        def run(name, tier, sleep_time):
            def job():
                with lock:
                    events.append(("start", name, time.time()))
                time.sleep(sleep_time)
                with lock:
                    events.append(("end", name, time.time()))
                return name
            return policy.run_queued(tier, job, reason=name, priority=10)

        t1 = threading.Thread(target=run, args=("main", "main_cognition", 0.06))
        t2 = threading.Thread(target=run, args=("vision", "vision_compressor", 0.01))
        t1.start()
        time.sleep(0.01)
        t2.start()
        t1.join()
        t2.join()

        names = [item[:2] for item in events]
        self.assertEqual(names, [("start", "main"), ("end", "main"), ("start", "vision"), ("end", "vision")])
        self.assertGreater(policy.last_main_started_at, 0.0)
        self.assertGreater(policy.last_main_finished_at, 0.0)

    def test_cancel_queued_request_before_it_runs(self):
        policy = ModelBudgetPolicy(test_config(default_queue_timeout_seconds=5.0))
        first_started = threading.Event()
        release_first = threading.Event()
        cancel_event = threading.Event()
        errors = []

        def long_job():
            first_started.set()
            release_first.wait(1.0)
            return "main"

        def queued_job():
            try:
                policy.run_queued("vision_compressor", lambda: "vision", reason="cancel_me", priority=1, cancel_event=cancel_event)
            except Exception as exc:
                errors.append(str(exc))

        t1 = threading.Thread(target=lambda: policy.run_queued("main_cognition", long_job, reason="main", priority=10))
        t2 = threading.Thread(target=queued_job)
        t1.start()
        self.assertTrue(first_started.wait(1.0))
        t2.start()
        time.sleep(0.05)
        cancel_event.set()
        release_first.set()
        t1.join()
        t2.join()

        self.assertTrue(any("model_request_cancelled" in item for item in errors), errors)


if __name__ == "__main__":
    unittest.main()
