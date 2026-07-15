import threading
import time
import unittest
from types import SimpleNamespace

from runtime.model_budget_policy import ModelBudgetPolicy, ModelBudgetPolicyConfig


def make_config(**overrides):
    data = dict(
        enabled=True,
        queue_enabled=True,
        resource_guard_enabled=True,
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
        vision_force_run=False,
    )
    data.update(overrides)
    return ModelBudgetPolicyConfig(**data)


class ModelBudgetPolicyQueueTests(unittest.TestCase):
    def test_budget_policy_blocks_local_heavy_tier_under_resource_pressure(self):
        policy = ModelBudgetPolicy(
            make_config(
                cpu_block_percent=80.0,
                ram_block_percent=80.0,
                gpu_block_percent=70.0,
                vram_block_percent=72.0,
            )
        )
        snapshot = policy.capture()
        snapshot.cpu_percent = 97.0
        snapshot.ram_percent = 96.0
        snapshot.gpu_util_percent = 88.0
        snapshot.vram_used_mb = 3600.0
        snapshot.vram_total_mb = 4096.0
        snapshot.external_vram_used_mb = 3600.0

        decision = policy.can_run("vision_compressor", resource_snapshot=snapshot, reason="pressure_smoke")

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.verdict, "block")
        self.assertIn("resource_guard:", decision.reason)
        self.assertIn("cpu_busy", decision.debug.get("resource_reasons", ()))
        self.assertIn("vram_busy", decision.debug.get("resource_reasons", ()))

    def test_queue_only_mode_allows_high_resource_pressure(self):
        policy = ModelBudgetPolicy(
            make_config(
                resource_guard_enabled=False,
                cpu_block_percent=80.0,
                ram_block_percent=80.0,
                gpu_block_percent=70.0,
                vram_block_percent=72.0,
                gpu_temp_block_c=82.0,
            )
        )
        snapshot = policy.capture()
        snapshot.cpu_percent = 99.0
        snapshot.ram_percent = 98.0
        snapshot.gpu_util_percent = 96.0
        snapshot.vram_used_mb = 4000.0
        snapshot.vram_total_mb = 4096.0
        snapshot.external_vram_used_mb = 4000.0
        snapshot.gpu_temperature_c = 90.0

        decision = policy.can_run("vision_compressor", resource_snapshot=snapshot, reason="queue_only")

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "scheduler_allow")
        self.assertFalse(decision.debug.get("resource_guard_enabled"))

    def test_remote_main_ignores_gpu_vram_pressure_but_still_has_scheduler_reason(self):
        policy = ModelBudgetPolicy(make_config(remote_api_enabled=True, cpu_block_percent=80.0, ram_block_percent=80.0))
        snapshot = policy.capture()
        snapshot.cpu_percent = 20.0
        snapshot.ram_percent = 30.0
        snapshot.gpu_util_percent = 95.0
        snapshot.vram_used_mb = 3800.0
        snapshot.vram_total_mb = 4096.0
        policy._active_leases["vision_busy"] = SimpleNamespace(tier="vision_compressor")

        decision = policy.can_run("main_cognition", resource_snapshot=snapshot, reason="remote_main")

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "scheduler_allow")
        self.assertFalse(policy._is_heavy_tier("main_cognition"))

    def test_external_vram_excludes_eris_active_lease_reservation(self):
        policy = ModelBudgetPolicy(make_config())
        snapshot = policy.capture()
        snapshot.vram_used_mb = 2600.0
        snapshot.vram_total_mb = 4096.0
        snapshot.external_vram_used_mb = 1500.0
        policy._active_leases["vision_busy"] = SimpleNamespace(tier="vision_compressor")

        decision = policy.can_run(
            "subconscious_4b",
            resource_snapshot=snapshot,
            reason="queued_after_vision",
            ignore_active_lock=True,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "scheduler_allow")
        self.assertGreater(decision.debug.get("reserved_vram_mb", 0.0), 0.0)

    def test_heavy_models_do_not_overlap(self):
        policy = ModelBudgetPolicy(make_config())
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
        policy = ModelBudgetPolicy(make_config(default_queue_timeout_seconds=5.0))
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

    def test_sensory_tier_has_lighter_cpu_ram_guard(self):
        policy = ModelBudgetPolicy(make_config(cpu_block_percent=80.0, ram_block_percent=80.0))
        snapshot = policy.capture()
        snapshot.cpu_percent = 89.0
        snapshot.ram_percent = 87.0

        decision = policy.can_run("sensory_0_6b", resource_snapshot=snapshot, reason="observer_tick")

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "scheduler_allow")

    def test_vision_can_bypass_vram_guard_on_4gb_profile(self):
        policy = ModelBudgetPolicy(
            make_config(
                assume_gtx_1650ti_4gb=True,
                cpu_block_percent=80.0,
                ram_block_percent=80.0,
                gpu_block_percent=70.0,
                vram_block_percent=72.0,
            )
        )
        snapshot = policy.capture()
        snapshot.cpu_percent = 24.0
        snapshot.ram_percent = 41.0
        snapshot.gpu_util_percent = 18.0
        snapshot.vram_used_mb = 3920.0
        snapshot.vram_total_mb = 4096.0
        snapshot.external_vram_used_mb = 3920.0

        decision = policy.can_run("vision_compressor", resource_snapshot=snapshot, reason="vision_must_try")

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "scheduler_allow")
        self.assertTrue(decision.debug.get("vision_vram_guard_bypassed"))

    def test_vision_force_run_ignores_soft_resource_guard(self):
        policy = ModelBudgetPolicy(
            make_config(
                vision_force_run=True,
                cpu_block_percent=80.0,
                ram_block_percent=80.0,
                gpu_block_percent=70.0,
                vram_block_percent=72.0,
            )
        )
        snapshot = policy.capture()
        snapshot.cpu_percent = 98.0
        snapshot.ram_percent = 97.0
        snapshot.gpu_util_percent = 94.0
        snapshot.vram_used_mb = 3900.0
        snapshot.vram_total_mb = 4096.0
        snapshot.external_vram_used_mb = 3900.0

        decision = policy.can_run("vision_compressor", resource_snapshot=snapshot, reason="blindness_recovery")

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "vision_force_run")
        self.assertTrue(decision.debug.get("vision_force_run"))
        ignored = decision.debug.get("ignored_resource_reasons", ())
        self.assertIn("cpu_busy", ignored)
        self.assertIn("ram_busy", ignored)
        self.assertIn("gpu_busy", ignored)
        self.assertIn("vram_busy", ignored)

    def test_vision_force_run_priority_lane_ignores_queue_full_and_timeout(self):
        policy = ModelBudgetPolicy(
            make_config(
                vision_force_run=True,
                max_queue_size=1,
                default_queue_timeout_seconds=0.01,
                vision_force_run_priority=5000,
                vision_force_run_queue_timeout_seconds=0.0,
            )
        )
        policy._queue.append(
            SimpleNamespace(
                request_id="stale",
                tier="subconscious_4b",
                reason="stale",
                priority=1,
                enqueued_at=time.time(),
                timeout_seconds=10.0,
                sequence=1,
                status="queued",
                cancel_event=None,
                last_budget_decision=None,
                to_dict=lambda: {},
            )
        )

        result = policy.run_queued(
            "vision_compressor",
            lambda: "saw",
            reason="forced_vision",
            priority=1,
            timeout_seconds=0.01,
        )

        self.assertEqual(result, "saw")
        self.assertGreater(policy.last_4b_finished_at, 0.0)

    def test_vision_force_run_keeps_gpu_overheat_hard_veto(self):
        policy = ModelBudgetPolicy(
            make_config(
                vision_force_run=True,
                gpu_temp_block_c=82.0,
            )
        )
        snapshot = policy.capture()
        snapshot.gpu_temperature_c = 90.0

        decision = policy.can_run("vision_compressor", resource_snapshot=snapshot, reason="too_hot")

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.verdict, "kill")
        self.assertEqual(decision.reason, "gpu_overheat")

    def test_local_gguf_main_forces_past_resource_pressure_and_active_lease(self):
        policy = ModelBudgetPolicy(
            make_config(
                remote_api_enabled=False,
                cpu_block_percent=80.0,
                ram_block_percent=80.0,
                gpu_block_percent=70.0,
                vram_block_percent=72.0,
                main_cooldown_seconds=60.0,
            )
        )
        policy.mark_started("main_cognition")
        policy._active_leases["vision_busy"] = SimpleNamespace(tier="vision_compressor")
        snapshot = policy.capture()
        snapshot.cpu_percent = 98.0
        snapshot.ram_percent = 97.0
        snapshot.gpu_util_percent = 94.0
        snapshot.vram_used_mb = 3900.0
        snapshot.vram_total_mb = 4096.0
        snapshot.external_vram_used_mb = 3900.0

        decision = policy.can_run("main_cognition", resource_snapshot=snapshot, reason="must_wake")

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "force_local_gguf_main")
        self.assertTrue(decision.debug.get("force_local_gguf"))

    def test_local_gguf_main_uses_priority_lane_without_queue_timeout(self):
        policy = ModelBudgetPolicy(
            make_config(
                remote_api_enabled=False,
                max_queue_size=1,
                default_queue_timeout_seconds=0.01,
                force_local_gguf_priority=9000,
            )
        )
        policy._queue.append(
            SimpleNamespace(
                request_id="stale",
                tier="vision_compressor",
                reason="stale",
                priority=1,
                enqueued_at=time.time(),
                timeout_seconds=10.0,
                sequence=1,
                status="queued",
                cancel_event=None,
                last_budget_decision=None,
                to_dict=lambda: {},
            )
        )

        result = policy.run_queued("main_cognition", lambda: "ran", reason="forced_main")

        self.assertEqual(result, "ran")
        self.assertEqual(policy.last_main_finished_at > 0.0, True)


if __name__ == "__main__":
    unittest.main()
