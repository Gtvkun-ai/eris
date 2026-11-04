# -*- coding: utf-8 -*-
"""Throwaway verification for task eris-async-summary-no-ocr (not a pytest test).

Chay BEFORE moi thay doi o src/ de lay baseline, chay lai voi --phase after sau
FEAT-002/003. Moi state nam trong thu muc tam; khong dong vao
C:\\Users\\Gtvkun\\Documents\\eris.

    python verify_async_summary_no_ocr.py --phase before|after [--sleep 6]

Phase `before` ghi FAIL nhung luon thoat 0. Phase `after` thoat != 0 neu co FAIL.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.abc
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

REPO = Path(r"c:\Users\Gtvkun\Documents\GitHub\eris")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

TASK_DIR = Path(__file__).resolve().parent
HOT_PATH_LIMIT_S = 1.0
OCR_MODULES = ("rapidocr_onnxruntime", "onnxruntime", "pytesseract")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass


# --------------------------------------------------------------------------- helpers
@contextlib.contextmanager
def envset(**values):
    old = {key: os.environ.get(key) for key in values}
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(value)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def short_stack(thread, depth=8):
    frame = sys._current_frames().get(getattr(thread, "ident", None))
    if frame is None:
        return None
    return [f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in traceback.extract_stack(frame)[-depth:]]


def alive_eris_stacks():
    out = {}
    for thread in threading.enumerate():
        if thread.name.startswith("ERIS-") and thread.is_alive():
            out[thread.name] = short_stack(thread)
    return out


def timed(fn, *, cap, bg=None):
    """Chay fn tren thread rieng, do thoi gian; chup stack neu chay qua 1 s."""
    box = {}

    def run():
        started = time.perf_counter()
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = repr(exc)
        box["elapsed"] = time.perf_counter() - started

    thread = threading.Thread(target=run, name="hotpath-probe", daemon=True)
    started = time.perf_counter()
    thread.start()
    thread.join(HOT_PATH_LIMIT_S)
    stacks = None
    if thread.is_alive():
        stacks = {"probe_thread": short_stack(thread)}
        if bg is not None and bg.is_alive():
            stacks["background_thread"] = short_stack(bg)
        stacks["eris_threads"] = alive_eris_stacks()
        thread.join(max(0.0, cap - HOT_PATH_LIMIT_S))
    done = not thread.is_alive()
    info = {
        "elapsed_s": round(box.get("elapsed", time.perf_counter() - started), 3),
        "completed": done,
        "error": box.get("error"),
        "blocked_stack": stacks,
    }
    return info, box.get("result")


def merge_verdict(verdicts):
    values = [v for v in verdicts if v]
    if any(v == "FAIL" for v in values):
        return "FAIL"
    if any(v == "PASS" for v in values):
        return "PASS"
    return "N/A"


def vd(ok):
    return "PASS" if ok else "FAIL"


# --------------------------------------------------------------------------- fakes
from memory.living_user.runtime_adapter import CuratorInferenceError  # noqa: E402


class FakeAdapter:
    """summarize_episode ngu `sleep` giay (modes ok/fail/hang)."""

    def __init__(self, mode="ok", sleep=6.0):
        self.mode = mode
        self.sleep = float(sleep)
        self.calls = 0
        self.in_call = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()

    def summarize_episode(self, payload):
        with self._lock:
            self.calls += 1
        self.in_call.set()
        if self.mode == "fail":
            raise CuratorInferenceError("provider_error")
        self.release.wait(30.0 if self.mode == "hang" else self.sleep)
        return {"summary": "Tom tat gia lap do Gemini fake tra ve.", "title": "Fake episode", "importance": 0.7}

    def propose_profile_operations(self, payload):
        return {"operations": [], "action_operations": []}

    def summarize_episode_rollup(self, payload):
        anchors = list(payload.get("allowed_anchors") or ["2000-01-01"])
        return {"segments": [{"anchor": anchors[0], "text": "Recap gia lap."}]}


class Scenario:
    def __init__(self, root, name, *, mode="ok", sleep=6.0, adapter=True):
        from memory.living_user import LivingUserMemoryService
        self.dir = Path(root) / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.adapter = FakeAdapter(mode, sleep) if adapter else None
        self.service = LivingUserMemoryService(self.dir, model_adapter=self.adapter)
        self.bg = None

    def seed_turns(self, session="s1"):
        rows = (("user", "u1", "xin chao ve du an eris"), ("assistant", "a1", "chao anh, hom nay lam gi"),
                ("user", "u2", "sua bo nho de khong bi treo"), ("assistant", "a2", "ok, tach viec tom tat ra rieng"))
        for role, turn_id, text in rows:
            self.service.record_conversation_turn(role, text, session_id=session, turn_id=turn_id)

    def start_background(self, wait=10.0):
        """BEFORE: dream() flush inline. AFTER: dream() chi yeu cau worker."""
        self.bg = threading.Thread(target=lambda: self.service.dream(reason="idle"), name="verify-dream", daemon=True)
        self.bg.start()
        return self.adapter.in_call.wait(wait)

    def close(self):
        if self.adapter is not None:
            self.adapter.release.set()
        if self.bg is not None:
            self.bg.join(15)
        stop = getattr(self.service, "stop_consolidation", None)
        if callable(stop):
            with contextlib.suppress(Exception):
                stop(timeout=3.0)


def buffer_ids(service):
    return [row.get("id") for row in list(service._turn_buffer)]


def status_of(service):
    fn = getattr(service, "consolidation_status", None)
    if not callable(fn):
        return None
    try:
        return dict(fn())
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)}


# --------------------------------------------------------------------------- check 1
def _build_hot_path_callables(sc, root):
    from runtime.turn_memory_pipeline import TurnMemoryPipeline, TurnMemoryEnvelope, TurnMemoryPipelineConfig
    kernel = SimpleNamespace(core=SimpleNamespace(base_dir=str(sc.dir)),
                             plan_ingest=lambda *a, **k: SimpleNamespace(request_count=0, decision_count=0))
    pipeline = TurnMemoryPipeline(memory_kernel=kernel, living_user=sc.service, config=TurnMemoryPipelineConfig())
    envelope = TurnMemoryEnvelope(text="MY TEXT", turn_id="u9", evidence_ids=("u9",), context={"role": "user"})
    calls = {
        "capture_interpretation_context": lambda: sc.service.capture_interpretation_context(evidence_ids=("u9",)),
        "enqueue_curator": lambda: pipeline._enqueue_curator(envelope),
        "record_conversation_turn": lambda: sc.service.record_conversation_turn(
            "user", "hot path turn", session_id="s1", turn_id="u9"),
    }
    try:
        from runtime.state_commit_service import StateCommitServiceMixin
        host = SimpleNamespace(
            turn_memory_pipeline=pipeline, logger=logging.getLogger("verify.host"), runtime_session_id="s1",
            workspace_manager=None, active_project_id="", _turn_memory_pipeline_enabled=lambda: True,
            _frame_memory_storage_permission=lambda frame: True)
        calls["ingest_user_turn_memory_hot_path"] = lambda: StateCommitServiceMixin._ingest_user_turn_memory_hot_path(
            host, "text", turn_id="u9")
    except Exception as exc:  # noqa: BLE001
        calls["ingest_user_turn_memory_hot_path"] = None
        calls["_ingest_build_error"] = repr(exc)
    return calls


def check_hot_path(ctx):
    timings = {}
    names = ("capture_interpretation_context", "enqueue_curator", "record_conversation_turn",
             "ingest_user_turn_memory_hot_path")
    for name in names:
        sc = Scenario(ctx["root"], f"c1_{name}", sleep=ctx["sleep"])
        try:
            sc.seed_turns()
            started = sc.start_background()
            calls = _build_hot_path_callables(sc, ctx["root"])
            fn = calls.get(name)
            if fn is None:
                timings[name] = {"skipped": True, "reason": calls.get("_ingest_build_error", "not buildable")}
                continue
            info, result = timed(fn, cap=ctx["sleep"] + 20, bg=sc.bg)
            info["adapter_in_call_when_started"] = bool(started)
            info["returned"] = repr(result)[:80]
            timings[name] = info
        finally:
            sc.close()
    measured = {k: v for k, v in timings.items() if not v.get("skipped")}
    blocked = {k: v["elapsed_s"] for k, v in measured.items() if (not v["completed"]) or v["elapsed_s"] >= HOT_PATH_LIMIT_S}
    slow_half = [k for k, v in measured.items() if (not v["completed"]) or v["elapsed_s"] >= 0.5 * ctx["sleep"]]
    if not measured:
        hypothesis = "inconclusive"
    elif not blocked:
        hypothesis = "refuted"
    elif slow_half:
        hypothesis = "confirmed"
    else:
        hypothesis = "inconclusive"
    ok = bool(measured) and not blocked
    return {
        "verdict": vd(ok),
        "summary": "; ".join(f"{k}={v['elapsed_s']}s" for k, v in measured.items()),
        "limit_s": HOT_PATH_LIMIT_S,
        "fake_gemini_sleep_s": ctx["sleep"],
        "timings": timings,
        "blocked_callables_s": blocked,
        "hypothesis_turn_buffer_lock_blocks_hot_path": hypothesis,
    }


# --------------------------------------------------------------------------- check 2
def check_late_turns(ctx):
    from memory.living_user import LivingUserMemoryService
    sc = Scenario(ctx["root"], "c2", sleep=ctx["sleep"])
    try:
        sc.seed_turns()
        sc.start_background()
        late_ids = ["late1", "late2", "late3"]
        record_timings = []
        for turn_id in late_ids:
            info, _ = timed(lambda t=turn_id: sc.service.record_conversation_turn(
                "user", f"turn den muon {t}", session_id="s1", turn_id=t), cap=ctx["sleep"] + 20, bg=sc.bg)
            record_timings.append({"id": turn_id, "elapsed_s": info["elapsed_s"], "completed": info["completed"]})
        deadline = time.time() + ctx["sleep"] + 12
        if ctx["phase"] == "after":
            while time.time() < deadline and not sc.service.episode_store.all():
                time.sleep(0.25)
            trim_deadline = time.time() + 5
            while time.time() < trim_deadline and any(x in buffer_ids(sc.service) for x in ("u1", "a1", "u2", "a2")):
                time.sleep(0.1)
        else:
            sc.bg.join(max(1.0, deadline - time.time()))
        ids = buffer_ids(sc.service)
        episodes = sc.service.episode_store.all()
        reloaded = LivingUserMemoryService(sc.dir)
        re_ids = buffer_ids(reloaded)
        re_eps = reloaded.episode_store.all()
        checks = {
            "late_in_memory_buffer": all(x in ids for x in late_ids),
            "episode_exists": len(episodes) >= 1,
            "reload_sees_episode": len(re_eps) >= 1,
            "reload_sees_late_turns": all(x in re_ids for x in late_ids),
        }
        return {
            "verdict": vd(all(checks.values())),
            "summary": f"checks={checks} late_record_s={[t['elapsed_s'] for t in record_timings]}",
            "checks": checks,
            "late_record_timings": record_timings,
            "buffer_ids_after": ids,
            "reload_buffer_ids": re_ids,
            "originals_trimmed(info)": not any(x in ids for x in ("u1", "a1", "u2", "a2")),
            "episode_sources": [e.source for e in episodes],
        }
    finally:
        sc.close()


# --------------------------------------------------------------------------- check 3
def check_failure_retry(ctx):
    sub = {}
    originals = ["u1", "a1", "u2", "a2"]
    # (i) fail adapter
    sc = Scenario(ctx["root"], "c3_fail", mode="fail", sleep=ctx["sleep"])
    try:
        sc.seed_turns()
        sc.service.dream(reason="idle")
        if hasattr(sc.service, "consolidation_status"):
            deadline = time.time() + 10
            while time.time() < deadline and (status_of(sc.service) or {}).get("failures", 0) < 1:
                time.sleep(0.2)
        st = status_of(sc.service)
        eps = sc.service.episode_store.all()
        buf = buffer_ids(sc.service)
        buffer_kept = all(x in buf for x in originals)
        no_episode = len(eps) == 0
        retry_ok = bool(st) and st.get("failures") == 1 and float(st.get("next_retry_in_s") or 0) > 0
        sub["i_fail_keeps_turns_and_schedules_retry"] = {
            "verdict": vd(buffer_kept and no_episode and retry_ok),
            "buffer_kept": buffer_kept, "no_episode_written": no_episode, "retry_scheduled": retry_ok,
            "episodes_written": [{"source": e.source, "summary": e.summary[:80]} for e in eps],
            "buffer_len": len(buf), "status": st,
        }
    finally:
        sc.close()

    has_async = hasattr(sc.service, "request_consolidation")
    # (ii) hang adapter + timeout 2 s
    if not has_async:
        sub["ii_hang_times_out"] = {"verdict": "N/A", "note": "request_consolidation absent (BEFORE); hang would hold the lock 30 s"}
    else:
        with envset(ERIS_LIVING_USER_EPISODE_TIMEOUT_SEC="2"):
            sc = Scenario(ctx["root"], "c3_hang", mode="hang", sleep=ctx["sleep"])
        try:
            sc.seed_turns()
            started = time.time()
            sc.service.dream(reason="idle")
            sc.adapter.in_call.wait(10)
            hot, _ = timed(lambda: sc.service.capture_interpretation_context(evidence_ids=("u9",)),
                           cap=ctx["sleep"] + 20)
            deadline = time.time() + 14
            while time.time() < deadline and (status_of(sc.service) or {}).get("failures", 0) < 1:
                time.sleep(0.2)
            to_failure = round(time.time() - started, 2)
            st = status_of(sc.service) or {}
            buf = buffer_ids(sc.service)
            last_error = str(st.get("last_error") or "")
            good = (st.get("failures", 0) >= 1 and to_failure <= 9.0 and "timeout" in last_error.lower()
                    and all(x in buf for x in originals) and hot["completed"] and hot["elapsed_s"] < HOT_PATH_LIMIT_S
                    and not st.get("pending"))
            sub["ii_hang_times_out"] = {"verdict": vd(good), "seconds_to_failure": to_failure, "hot_path": hot,
                                        "status": st, "buffer_kept": all(x in buf for x in originals)}
        finally:
            sc.close()
    # (iii) single flight
    if not has_async:
        sub["iii_single_flight"] = {"verdict": "N/A", "note": "request_consolidation absent (BEFORE)"}
    else:
        sc = Scenario(ctx["root"], "c3_single", sleep=min(3.0, ctx["sleep"]))
        try:
            sc.seed_turns()
            sc.service.request_consolidation("verify_a")
            sc.adapter.in_call.wait(10)
            sc.service.request_consolidation("verify_b")
            sc.service.request_consolidation("verify_c")
            deadline = time.time() + sc.adapter.sleep + 10
            while time.time() < deadline and not sc.service.episode_store.all():
                time.sleep(0.2)
            time.sleep(1.5)
            sub["iii_single_flight"] = {"verdict": vd(sc.adapter.calls == 1), "adapter_calls": sc.adapter.calls,
                                        "episodes": len(sc.service.episode_store.all())}
        finally:
            sc.close()
    # (iv) gate: user turn active -> zero adapter calls
    if not has_async:
        sub["iv_gate_user_turn_active"] = {"verdict": "N/A", "note": "request_consolidation absent (BEFORE)"}
    else:
        from runtime.inference_broker import GLOBAL_INFERENCE_BROKER
        cls = type(GLOBAL_INFERENCE_BROKER)
        original = cls.user_turn_active
        cls.user_turn_active = lambda self: True
        sc = Scenario(ctx["root"], "c3_gate", sleep=min(3.0, ctx["sleep"]))
        try:
            sc.seed_turns()
            sc.service.request_consolidation("verify_gate")
            time.sleep(2.5)
            buf = buffer_ids(sc.service)
            sub["iv_gate_user_turn_active"] = {
                "verdict": vd(sc.adapter.calls == 0 and all(x in buf for x in originals)),
                "adapter_calls": sc.adapter.calls, "status": status_of(sc.service)}
        finally:
            cls.user_turn_active = original
            sc.close()
    verdict = merge_verdict([v["verdict"] for v in sub.values()])
    return {"verdict": verdict, "summary": "; ".join(f"{k}={v['verdict']}" for k, v in sub.items()), "sub": sub}


# --------------------------------------------------------------------------- check 4
def check_pending_view(ctx):
    from memory.living_user.models import UserEpisode, UserMemoryScope
    out = {}
    for variant in ("with_older_episode", "without_older_episode"):
        sc = Scenario(ctx["root"], f"c4_{variant}", sleep=ctx["sleep"])
        try:
            old_id = ""
            if variant == "with_older_episode":
                now = time.time()
                old = sc.service.episode_store.add(UserEpisode(
                    id="", session_id="s0", title="Older", summary="Older summary persisted earlier",
                    evidence_ids=("old1", "old2"), scope=UserMemoryScope(),
                    started_at=now - 3600, ended_at=now - 3000))
                old_id = old.id
            sc.seed_turns()
            sc.start_background()
            cap_info, cap = timed(lambda: sc.service.capture_interpretation_context(), cap=ctx["sleep"] + 20, bg=sc.bg)
            view_info, view = timed(lambda: sc.service.episode_prompt_view(), cap=ctx["sleep"] + 20, bg=sc.bg)
            cap = cap if isinstance(cap, dict) else {}
            view = view if isinstance(view, dict) else {}
            episode_ids = [row.get("episode_id") for row in cap.get("episodes", [])]
            recent_ids = [row.get("id") for row in cap.get("recent_conversation", [])]
            fast = (cap_info["completed"] and cap_info["elapsed_s"] < HOT_PATH_LIMIT_S
                    and view_info["completed"] and view_info["elapsed_s"] < HOT_PATH_LIMIT_S)
            if variant == "with_older_episode":
                good = fast and old_id in episode_ids and len(recent_ids) >= 1 and any(
                    row.get("title") == "Older" for row in view.get("recent_episodes", []))
            else:
                good = (fast and episode_ids == [] and len(recent_ids) >= 1 and view.get("recent_episodes") == []
                        and view.get("episode_recap") == "" and not cap_info["error"] and not view_info["error"])
            out[variant] = {"verdict": vd(good), "capture": cap_info, "prompt_view": view_info,
                            "episode_ids": episode_ids, "recent_turn_ids": recent_ids,
                            "view_recent_episode_titles": [r.get("title") for r in view.get("recent_episodes", [])],
                            "view_recap": view.get("episode_recap")}
        finally:
            sc.close()
    return {"verdict": merge_verdict([v["verdict"] for v in out.values()]),
            "summary": "; ".join(f"{k}={v['verdict']} capture={v['capture']['elapsed_s']}s" for k, v in out.items()),
            "variants": out}


# --------------------------------------------------------------------------- check 5/6 fixtures
class Sink:
    def __init__(self):
        self.snapshots = []

    def publish(self, snapshot):
        self.snapshots.append(snapshot)


class RecordingWorker:
    def __init__(self):
        self.start_calls = 0
        self.refresh_calls = []

    def start(self):
        self.start_calls += 1

    def refresh_now(self, **kwargs):
        from screen.evidence_models import ActiveWindowInfo, ScreenTextSnapshot
        self.refresh_calls.append(dict(kwargs))
        return ScreenTextSnapshot(window=ActiveWindowInfo(title="Fake"), blocks=(), captured_at=time.time(),
                                  revision=1, backend="uia_only")


class FakeStructured:
    def contexts_for_turn(self, text, max_age_seconds=30.0):
        return ()

    def evidence_for_turn(self, text, max_age_seconds=30.0):
        return ()

    def has_fresh_relevant_state(self, text, max_age_seconds=30.0):
        return False

    def active_engagement_id(self, engagement_kind=""):
        return ""


def drive_turn(text, previous=""):
    from runtime.chat_perception import ChatPerceptionCoordinator
    from screen.screen_evidence_store import ScreenEvidenceStore
    from screen.screen_relevance_router import ScreenRelevanceRouter
    store = ScreenEvidenceStore()
    worker = RecordingWorker()
    coord = ChatPerceptionCoordinator(screen_evidence_store=store, screen_text_worker=worker,
                                      screen_relevance_router=ScreenRelevanceRouter(store),
                                      structured_provider=FakeStructured(), logger=None)
    captured = {"n": 0, "report": None}

    def capture():
        captured["n"] += 1
        return "data:image/jpeg;base64,AAAA"

    def interpret(data_uri):
        captured["report"] = SimpleNamespace(
            grounded_claims=("claim",), recommendation="none", source="fake", stale=False,
            to_evidence_items=lambda grounded_only=True: [{
                "id": "vision:fake:1", "source": "vision", "claim": "fake vision claim", "grounded": True,
                "stale": False, "confidence": 0.8, "tags": ["vision", "screen"]}])
        return captured["report"]

    result = coord.prepare_turn(text, previous_assistant_text=previous, capture_fn=capture, interpret_fn=interpret)
    route = result.route
    debug = dict(getattr(route, "debug", {}) or {}) if route is not None else {}
    items = ()
    if captured["n"]:
        items = coord.build_screen_grounding_items(
            screen_blocks=result.screen_blocks, route=route, vision_report=captured["report"],
            screen_image_data_uri=result.data_uri, capture_interpreted=result.capture_interpreted)
    return {
        "text": text,
        "route_mode": str(getattr(route, "mode", "none")) if route is not None else "none",
        "references_screen": bool(getattr(route, "references_screen", False)) if route is not None else False,
        "inherited": bool(debug.get("anaphora_inherited", False)),
        "needs_visual": bool(getattr(route, "needs_visual", False)) if route is not None else False,
        "route_reason": str(getattr(route, "reason", "")) if route is not None else "",
        "capture_called_this_turn": captured["n"] > 0,
        "pending_vision_queued": bool(coord.pending_vision.pending),
        "refresh_now_calls": worker.refresh_calls,
        "force_ocr_true_passed": any(call.get("force_ocr") is True for call in worker.refresh_calls),
        "grounding_item_sources": [str(i.get("source")) if isinstance(i, dict) else str(getattr(i, "source", ""))
                                   for i in items],
    }


# --------------------------------------------------------------------------- check 5
class ImportRecorder(importlib.abc.MetaPathFinder):
    def __init__(self):
        self.hits = []

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in OCR_MODULES:
            self.hits.append(fullname)
        return None


def _make_worker(ow, sink):
    from screen.evidence_models import ActiveWindowInfo, ScreenTextBlock
    from PIL import Image
    worker = ow.IncrementalScreenTextWorker(sink)
    window = ActiveWindowInfo(title="Fake Window", hwnd=1, bounds=(0, 0, 200, 120), process_name="fake.exe")
    worker.window_provider = SimpleNamespace(get=lambda: window)
    uia_block = ScreenTextBlock("uia1", "Van ban UIA gia lap", "uia", 0.9, "Fake Window", time.time(), (0, 0, 10, 10))
    worker.uia_reader = SimpleNamespace(is_sensitive=lambda title: False, allow_sensitive=False,
                                        read=lambda w: (uia_block,))
    worker._capture = lambda w: Image.new("RGB", (200, 120), "white")
    return worker


def _run_worker(ow, sink):
    worker = _make_worker(ow, sink)
    started = time.perf_counter()
    worker.start()
    start_s = round(time.perf_counter() - started, 3)
    snap_forced = worker.refresh_now(force_ocr=True)
    with worker._capture_lock:
        snap_bg = worker._capture_snapshot(force_ocr=False)
    worker._stop.set()
    worker._trigger.set()
    worker.stop()
    return worker, snap_forced, snap_bg, start_s


def check_ocr_off(ctx):
    import screen.ocr_worker as ow
    from screen.ocr_worker import _OCRBackend  # noqa: F401
    recorder = ImportRecorder()
    probe = {"backends": [], "subprocess": []}

    def wrap(cls):
        class Recording(cls):
            def __init__(self, *a, **k):
                probe["backends"].append(cls.name)
                super().__init__(*a, **k)
        return Recording

    def fake_run(cmd, *a, **k):
        probe["subprocess"].append(" ".join(map(str, cmd)) if isinstance(cmd, (list, tuple)) else str(cmd))
        rc = 0 if "--version" in str(cmd) else 1
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="fake")

    real_run, real_rapid, real_tess, real_choose = subprocess.run, ow._RapidOCRBackend, ow._PytesseractBackend, ow._choose_ocr_backend
    cache = Path(ctx["root"]) / "ocr_state.json"
    result = {}
    sys.meta_path.insert(0, recorder)
    try:
        ow._RapidOCRBackend, ow._PytesseractBackend = wrap(real_rapid), wrap(real_tess)
        subprocess.run = fake_run
        ow._auto_install_rapidocr.attempted = False
        # ---- OFF (default: bien moi truong khong dat)
        with envset(ERIS_SCREEN_OCR_ENABLED=None, ERIS_LIGHT_OCR_CACHE_PATH=str(cache)):
            sink = Sink()
            worker, snap_forced, snap_bg, start_s = _run_worker(ow, sink)
            turns_off = {
                "explicit_nhin_man_hinh_di": drive_turn("nhin man hinh di"),
                "direct_tu_xem_di": drive_turn("tu xem di"),
            }
        pip_calls = [c for c in probe["subprocess"] if "pip" in c]
        off = {
            "import_attempts": list(recorder.hits),
            "backend_constructions": list(probe["backends"]),
            "subprocess_calls": list(probe["subprocess"]),
            "pip_calls": pip_calls,
            "worker_backend": None if worker.backend is None else getattr(worker.backend, "name", "?"),
            "worker_start_s": start_s,
            "refresh_snapshot_backend": getattr(snap_forced, "backend", None),
            "background_snapshot_backend": getattr(snap_bg, "backend", None),
            "turns": turns_off,
        }
        # ---- ON (ERIS_SCREEN_OCR_ENABLED=1) voi backend gia
        probe["backends"].clear(); probe["subprocess"].clear(); recorder.hits.clear()

        class FakeBackend(ow._OCRBackend):
            name = "fakeocr"
            available = True

            def read(self, image, *, window_title, captured_at):
                from screen.evidence_models import ScreenTextBlock
                return (ScreenTextBlock("ocr1", "fake ocr text", "ocr", 0.8, window_title, captured_at, (0, 0, 5, 5)),)

        ow._choose_ocr_backend = lambda: FakeBackend()
        with envset(ERIS_SCREEN_OCR_ENABLED="1", ERIS_LIGHT_OCR_CACHE_PATH=str(cache)):
            worker_on, snap_on, _snap_bg_on, _ = _run_worker(ow, Sink())
            turn_on = drive_turn("nhin man hinh di")
        on = {
            "worker_backend": None if worker_on.backend is None else getattr(worker_on.backend, "name", "?"),
            "refresh_snapshot_backend": getattr(snap_on, "backend", None),
            "snapshot_has_ocr_block": any(b.source == "ocr" for b in getattr(snap_on, "blocks", ())),
            "force_ocr_true_passed": turn_on["force_ocr_true_passed"],
            "capture_called_this_turn": turn_on["capture_called_this_turn"],
            "pending_vision_queued": turn_on["pending_vision_queued"],
        }
    finally:
        sys.meta_path.remove(recorder)
        subprocess.run = real_run
        ow._RapidOCRBackend, ow._PytesseractBackend, ow._choose_ocr_backend = real_rapid, real_tess, real_choose
    explicit = off["turns"]["explicit_nhin_man_hinh_di"]
    parts = {
        "no_ocr_imports": not off["import_attempts"],
        "no_backend_probe": not off["backend_constructions"],
        "no_pip_calls": not off["pip_calls"],
        "worker_backend_is_none": off["worker_backend"] is None,
        "snapshots_report_uia_only": off["refresh_snapshot_backend"] == "uia_only" and off["background_snapshot_backend"] == "uia_only",
        "no_force_ocr_true_in_chat": not any(t["force_ocr_true_passed"] for t in off["turns"].values()),
        "explicit_reference_captures_vision_same_turn": bool(explicit["capture_called_this_turn"] and explicit["needs_visual"]
                                                            and "vision" in explicit["grounding_item_sources"]),
        "switch_on_restores_old_path": bool(on["force_ocr_true_passed"] and on["snapshot_has_ocr_block"]
                                            and on["refresh_snapshot_backend"] == "fakeocr"),
    }
    return {"verdict": vd(all(parts.values())),
            "summary": "failed=" + ",".join(k for k, v in parts.items() if not v) if not all(parts.values()) else "all ok",
            "parts": parts, "off": off, "on": on}


# --------------------------------------------------------------------------- check 6
FALSE_POSITIVE_CASES = (
    ("vụ đó lâu rồi á",
     "Chín giờ năm mươi tư rồi, anh vẫn ngồi với Gemini trên Brave. Cái council đó ráp xong chưa, hay vẫn đang kẹt ở khâu gộp các nhánh lại thành một câu trả lời đọc được?"),
    ("nó ko hiểu ý tôi. làm ko hợp ý",
     "Loay hoay kiểu gì? Sửa một chỗ xong đẻ ra ba lỗi mới, hay cứ vòng vòng đọc hiểu rồi không chịu đụng vào code?"),
    ("cái này ko hay. tôi tâm sự cái này còn hỏi lại kỹ thuật, fe tệ quá nha",
     "Không hiểu ý thì khó nói lắm — vì có khi lỗi tại cái đầu nó, cũng có khi tại cái brief mình đưa nó tự suy diễn thêm. Anh nói rõ ý cỡ nào rồi, hay mới phác ra là nó chạy luôn?"),
)


def check_false_positives(ctx):
    table = {}
    for label, flag in (("ocr_off(default)", None), ("ocr_on", "1")):
        with envset(ERIS_SCREEN_OCR_ENABLED=flag):
            table[label] = [drive_turn(text, previous) for text, previous in FALSE_POSITIVE_CASES]
    rows = []
    for label, turns in table.items():
        for turn in turns:
            rows.append(f"{label}: refs={int(turn['references_screen'])} inh={int(turn['inherited'])} "
                        f"mode={turn['route_mode']} vis={int(turn['needs_visual'])} "
                        f"capture_now={int(turn['capture_called_this_turn'])} pending={int(turn['pending_vision_queued'])} "
                        f"force_ocr={int(turn['force_ocr_true_passed'])}")
    return {
        "verdict": "REPORT",
        "summary": " | ".join(rows[:3]) + " ...",
        "table": table,
        "fix_suggestion": ("Stop matching accent-folded 'anh'/'code' anchors and 'no'/'do'/'day' deictics in "
                           "screen_anaphora_rescue.py; match the accented original instead (e.g. 'ảnh')."),
        "note": "Report only. Not a pass/fail check.",
    }


# --------------------------------------------------------------------------- check 7
def check_rollup_value_error(ctx):
    from memory.living_user.episode_rollup import EpisodeRollupStore
    from memory.living_user.episode_store import UserEpisodeStore
    from memory.living_user.models import UserEpisode

    def make(name):
        base = Path(ctx["root"]) / f"c7_{name}"
        base.mkdir(parents=True, exist_ok=True)
        store = UserEpisodeStore(base / "episodes.json")
        old = time.time() - 30 * 86400
        for index, sid in enumerate(("r1", "r2")):
            store.add(UserEpisode(id="", session_id=sid, title=f"T{index}", summary=f"old summary {index}",
                                  started_at=old + index, ended_at=old + index + 10))
        return EpisodeRollupStore(base / "rollup.json", store, authority=lambda: ()), base

    class Adapter:
        def __init__(self, shape):
            self.shape = shape

        def summarize_episode_rollup(self, payload):
            anchors = list(payload["allowed_anchors"])
            if self.shape == "bad_anchor":
                return {"segments": [{"anchor": "1999-01-01", "text": "x"}]}
            if self.shape == "nine_segments":
                return {"segments": [{"anchor": anchors[0], "text": f"s{i}"} for i in range(9)]}
            if self.shape == "duplicate_anchor":
                return {"segments": [{"anchor": anchors[0], "text": "a"}, {"anchor": anchors[0], "text": "b"}]}
            return {"segments": [{"anchor": anchors[0], "text": "Recap hop le."}]}

    cases = {}
    for name, shape, corrupt in (("a_anchor_not_allowed", "bad_anchor", False), ("b_nine_segments", "nine_segments", False),
                                 ("c_duplicate_anchor", "duplicate_anchor", False), ("d_corrupt_json", "valid", True),
                                 ("e_control_valid", "valid", False)):
        rollup, base = make(name)
        if corrupt:
            (base / "rollup.json").write_text("{not json", encoding="utf-8")
        cases[name] = rollup.run(Adapter(shape))
    failing = [cases[k] for k in cases if not k.startswith("e_")]
    # JSONDecodeError subclasses ValueError nhung `type(exc).__name__` in ra ten con.
    all_value_error = all(r.get("status") == "failed" and r.get("error") in {"ValueError", "JSONDecodeError"}
                          for r in failing)
    control_ok = cases["e_control_valid"].get("status") == "committed"
    has_detail = all(bool(str(r.get("detail") or "").strip()) for r in failing)
    ok = all_value_error and control_ok and (has_detail if ctx["phase"] == "after" else True)
    return {"verdict": vd(ok),
            "summary": f"ValueError for all 4 bad inputs={all_value_error}; control committed={control_ok}; detail present={has_detail}",
            "cases": cases, "detail_present_on_failures": has_detail}


# --------------------------------------------------------------------------- main
CHECKS = (
    ("1", "Hot path not blocked while Gemini summarises", check_hot_path),
    ("2", "Turns during the call survive; result persisted", check_late_turns),
    ("3", "Failure / timeout keeps turns and schedules retry", check_failure_retry),
    ("4", "What chat sees while the summary is pending", check_pending_view),
    ("5", "OCR off never loads or forces OCR", check_ocr_off),
    ("6", "False-positive screen routing cost (report only)", check_false_positives),
    ("7", "Rollup ValueError probe", check_rollup_value_error),
)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--sleep", type=float, default=6.0, help="fake Gemini summarize latency in seconds (5-10)")
    parser.add_argument("--only", default="", help="comma-separated check ids, debugging only")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.ERROR)
    wanted = {x.strip() for x in args.only.split(",") if x.strip()}
    started = time.time()
    results = {"phase": args.phase, "sleep_s": args.sleep, "python": sys.version.split()[0],
               "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "checks": {}}
    with tempfile.TemporaryDirectory(prefix="eris_verify_", ignore_cleanup_errors=True) as root:
        ctx = {"root": root, "sleep": args.sleep, "phase": args.phase}
        with envset(ERIS_CURATOR_INBOX_DB=None, ERIS_LIVING_USER_EPISODE_TIMEOUT_SEC=None,
                    ERIS_LIGHT_OCR_CACHE_PATH=str(Path(root) / "ocr_state.json")):
            for check_id, title, fn in CHECKS:
                if wanted and check_id not in wanted:
                    continue
                t0 = time.time()
                try:
                    outcome = fn(ctx)
                except Exception as exc:  # noqa: BLE001
                    outcome = {"verdict": "ERROR", "summary": repr(exc), "traceback": traceback.format_exc()}
                outcome["title"] = title
                outcome["duration_s"] = round(time.time() - t0, 2)
                results["checks"][check_id] = outcome
                print(f"[{outcome['verdict']:6}] check {check_id}: {title} ({outcome['duration_s']}s)", flush=True)
                print(f"         {str(outcome.get('summary', ''))[:400]}", flush=True)
    hot = results["checks"].get("1", {})
    results["hot_path_timings_s"] = {k: (v.get("elapsed_s") if not v.get("skipped") else None)
                                     for k, v in (hot.get("timings") or {}).items()}
    results["hypothesis_turn_buffer_lock_blocks_hot_path"] = hot.get("hypothesis_turn_buffer_lock_blocks_hot_path")
    results["total_duration_s"] = round(time.time() - started, 1)
    out_path = TASK_DIR / f"results_{args.phase}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nhot path timings (s): {results['hot_path_timings_s']}")
    print(f"hypothesis (turn_buffer_lock blocks hot path): {results['hypothesis_turn_buffer_lock_blocks_hot_path']}")
    print(f"results written to {out_path}")
    failed = [cid for cid, r in results["checks"].items() if r["verdict"] in {"FAIL", "ERROR"}]
    if args.phase == "after" and failed:
        print(f"AFTER phase failed checks: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
