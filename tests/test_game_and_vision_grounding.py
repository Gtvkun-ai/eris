# -*- coding: utf-8 -*-
"""Test suite for game knowledge, screen relevance router, and session reset."""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from screen.game_knowledge import (
    clean_game_title,
    detect_game_from_window,
    format_game_prompt_context,
    is_gaming_window,
)
from screen.screen_relevance_router import ScreenRelevanceRouter
from screen.screen_evidence_store import ScreenEvidenceStore, ScreenTextBlock
from runtime.chat_perception import ChatPerceptionCoordinator
from runtime.chat_cycle import ChatCycleMixin


def test_game_knowledge_detection():
    # Little Chef Brave window title
    brave_title = "Little Chef: Demo by Julien, hello erika, Danny-vD - Brave"
    assert is_gaming_window(brave_title)
    profile = detect_game_from_window(brave_title)
    assert profile is not None
    assert "Little Chef" in profile.title
    assert "Cooking" in profile.genre
    assert "Physics" in profile.genre
    assert "bánh mì" in profile.mechanics or "chế biến" in profile.mechanics

    formatted = format_game_prompt_context(profile)
    assert "[GAMEPLAY CONTEXT" in formatted
    assert "Little Chef" in formatted
    assert "Cơ chế & Mục tiêu cốt lõi" in formatted

    # Slay the Spire
    spire_profile = detect_game_from_window("Slay the Spire")
    assert spire_profile is not None
    assert spire_profile.title == "Slay the Spire"
    assert "Deckbuilder" in spire_profile.genre

    # Dynamic Zero-shot game
    zero_profile = detect_game_from_window("Celeste - Steam")
    assert zero_profile is not None
    assert "Celeste" in zero_profile.title
    assert zero_profile.genre == "Trò chơi điện tử (PC / Web / Indie Game)"

    # False-positive guard tests (Non-game exclusion)
    assert is_gaming_window("game_knowledge.py - eris - Visual Studio Code", "code.exe") is False
    assert is_gaming_window("Top 10 Cooking Games - YouTube - Brave", "brave.exe") is False
    assert is_gaming_window("cooking recipe - Google Search - Brave", "brave.exe") is False
    assert is_gaming_window("Tin tức thời sự 24h - VnExpress - Brave", "brave.exe") is False
    assert detect_game_from_window("game_knowledge.py - eris - Visual Studio Code", "code.exe") is None


def test_screen_router_window_title_does_not_suppress_vision():
    from screen.evidence_models import ScreenTextSnapshot, ActiveWindowInfo
    import time
    store = ScreenEvidenceStore()
    # Simulate single accessibility block from Brave window title
    block = ScreenTextBlock(
        block_id="b1",
        text="Little Chef: Demo by Julien, hello erika, Danny-vD - Brave",
        confidence=0.88,
        source="accessibility",
        window_title="Brave",
        captured_at=time.time(),
    )
    store.publish(ScreenTextSnapshot(window=ActiveWindowInfo(title="Brave"), blocks=(block,)))
    router = ScreenRelevanceRouter(store)

    # When user says "thấy game chưa" (direct vision / screen marker)
    decision = router.route("thấy game chưa")
    # Even though confidence is 0.88, it should escalate to vision because it's sparse accessibility
    assert decision.mode == "vision"
    assert decision.needs_visual is True
    assert decision.references_screen is True

    # User says "em xem màn hình giup"
    decision2 = router.route("em xem màn hình giup")
    assert decision2.mode == "vision"
    assert decision2.needs_visual is True


def test_chat_perception_forced_vision_on_gaming():
    store = ScreenEvidenceStore()
    router = ScreenRelevanceRouter(store)
    coordinator = ChatPerceptionCoordinator(
        screen_evidence_store=store,
        screen_relevance_router=router,
    )

    capture_called = []
    def dummy_capture():
        capture_called.append(True)
        return "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="

    def dummy_interpret(uri):
        mock_report = MagicMock()
        mock_report.grounded_claims = ("claim1",)
        mock_report.to_evidence_items.return_value = [{"id": "item1", "grounded": True, "claim": "Cooking"}]
        return mock_report

    # When force_chat_vision=True (e.g. gaming is active)
    result = coordinator.prepare_turn(
        "nấu món gì đây ta",  # user didn't explicitly say "screen"
        force_chat_vision=True,
        capture_fn=dummy_capture,
        interpret_fn=dummy_interpret,
    )
    assert len(capture_called) == 1
    assert result.capture_present is True
    assert result.capture_interpreted is True
    assert result.route.mode == "vision"
    assert result.route.needs_visual is True


def test_session_reset_detection_and_wipe():
    class DummyHost(ChatCycleMixin):
        def __init__(self):
            self.logger = MagicMock()
            self.chat_history = [{"role": "user", "content": "con dao"}, {"role": "assistant", "content": "rèn kiếm"}]
            self.last_agent_turn = {"move_id": "m1"}
            self._last_assistant_text = "lời rèn kiếm"
            self.vision_facts = ("old fact",)
            self.root_session = MagicMock()

    host = DummyHost()
    reset_text = "xoá sạch mọi ký ức cũ đi. làm lại nè"
    assert host._is_session_reset_request(reset_text) is True
    assert host._is_session_reset_request("chơi game tiếp nào") is False

    host._perform_session_reset()
    assert len(host.chat_history) == 0
    assert host.last_agent_turn is None
    assert host._last_assistant_text == ""
    assert host.vision_facts == ()
    assert host.root_session._clear.called


def test_caption_prompt_game_enrichment():
    from cortex.vision_semantic_compressor import VisionSemanticCompressor
    prompt = VisionSemanticCompressor._caption_prompt(
        active_window_title="Little Chef: Demo by Julien, hello erika, Danny-vD - Brave"
    )
    assert "Little Chef" in prompt
    assert "Cooking" in prompt
    assert "Visible game mechanics" in prompt


def test_evidence_assembler_injects_game_context():
    from runtime.conversation.evidence_assembler import ConversationEvidenceAssembler
    mock_host = MagicMock()
    mock_telemetry = MagicMock()
    mock_snap = MagicMock()
    mock_snap.active_window_title = "Little Chef: Demo by Julien, hello erika, Danny-vD - Brave"
    mock_snap.active_app = "brave.exe"
    mock_telemetry.capture_snapshot.return_value = mock_snap
    mock_host.telemetry_service = mock_telemetry
    mock_host._capture_screen_frame_for_chat.return_value = ""
    mock_host._recall_memory_resonance.return_value = None
    mock_host._build_chat_source_grounding_report.return_value = None

    assembler = ConversationEvidenceAssembler(mock_host)
    result = assembler.assemble_chat("game này chơi ntn em")
    source_context = result.get("source_grounding_context", "")
    assert "[GAMEPLAY CONTEXT" in source_context
    assert "Little Chef" in source_context
    assert "Cơ chế & Mục tiêu cốt lõi" in source_context


def test_game_knowledge_store_persistence(tmp_path):
    from screen.game_knowledge import GameKnowledgeStore, GameProfile
    cache_path = tmp_path / "test_game_cache.json"
    store = GameKnowledgeStore(cache_file=cache_path)
    profile = GameProfile(
        game_id="test_game",
        title="Test Game",
        genre="Test Genre",
        mechanics="Test Mechanics",
        co_stream_focus="Test Co-stream Focus",
        source="test",
    )
    store.set("test_game", profile)
    assert cache_path.exists()

    # Re-read in a new store instance
    store2 = GameKnowledgeStore(cache_file=cache_path)
    loaded = store2.get("test_game")
    assert loaded is not None
    assert loaded.title == "Test Game"
    assert loaded.source == "test"


def test_gemini_web_search_research_contract(monkeypatch):
    import json
    from unittest.mock import MagicMock
    from screen.game_knowledge import (
        clean_browser_title,
        fetch_game_profile_from_research,
    )

    raw_title = "Little Chef: Demo by Julien, hello erika, Danny-vD - Brave"
    assert clean_browser_title(raw_title) == "Little Chef: Demo by Julien, hello erika, Danny-vD"
    assert clean_game_title(raw_title) == "Little Chef"

    # Mock urllib request to inspect prompt and verify web search mandate
    captured_payload = {}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def read(self):
            resp_body = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({
                                "title": "Little Chef: Demo by Julien, hello erika, Danny-vD",
                                "genre": "2D Physics Sandbox Puzzle",
                                "mechanics": "Kéo thả vật thể, mở vòi nước và thử nghiệm công thức nấu ăn dị.",
                                "co_stream_focus": "Bình luận các pha vật lý hài hước.",
                            })
                        }
                    }
                ]
            }
            return json.dumps(resp_body).encode("utf-8")

    def dummy_urlopen(req, timeout=None):
        nonlocal captured_payload
        captured_payload = json.loads(req.data.decode("utf-8"))
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", dummy_urlopen)

    profile = fetch_game_profile_from_research(
        "Little Chef",
        raw_window_title=raw_title,
        process_name="brave.exe",
    )
    assert profile is not None
    assert profile.title == "Little Chef"
    assert profile.source == "gemini_web_search"
    assert "Physics" in profile.genre

    # Verify Gemini prompt contract mandates Google / Web search
    messages = captured_payload.get("messages", [])
    sys_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
    assert "BẮT BUỘC: Bạn HÃY TÌM KIẾM TRÊN GOOGLE / WEB" in sys_msg
    assert "Julien, hello erika, Danny-vD" in user_msg
    assert "brave.exe" in user_msg


def test_vision_grounding_preserves_caption_and_softens_requested():
    from runtime.vision_grounding import VisionGroundingPolicy
    from cortex.observer_contracts import SemanticSceneNote

    policy = VisionGroundingPolicy()

    # Note produced from caption with confidence 0.65
    note = SemanticSceneNote(
        visible_context="Màn hình chơi game Little Chef: người chơi đang ở khu vực bếp với chảo và nguyên liệu",
        confidence=0.65,
        source="vision_caption_only",
        evidence=["vision_caption:kitchen_station"],
    )

    # When requested=False (ambient), it stays silent because 0.65 < 0.72
    report_ambient = policy.evaluate(note, requested=False)
    assert report_ambient.recommendation == "silence"

    # When requested=True (e.g. user says 'xem màn hình đi' or gaming mode active):
    # It must NOT drop the claim, but soften/speak and return facts!
    report_req = policy.evaluate(note, requested=True)
    assert report_req.recommendation in {"speak", "soften"}
    facts = report_req.to_screen_facts()
    assert len(facts) > 0
    assert "Little Chef" in facts[0]


def test_looks_like_screen_request_on_xem_man_hinh():
    class DummyHost(ChatCycleMixin):
        pass

    host = DummyHost()
    assert host._looks_like_screen_vision_request("xem màn hình đi") is True
    assert host._looks_like_screen_vision_request("nhìn màn hình coi") is True


def test_evidence_assembler_background_vision_and_game_context(monkeypatch):
    import time
    from runtime.conversation.evidence_assembler import ConversationEvidenceAssembler
    from screen.vision_perception_worker import (
        VisionPerceptionSnapshot,
        ensure_vision_perception_service,
    )

    service = ensure_vision_perception_service()
    fresh_snapshot = VisionPerceptionSnapshot(
        summary="Đang chơi Little Chef: đầu bếp đang nấu súp cà chua trên bếp ga.",
        inferred_story="Người chơi đang gom cà chua thả vào nồi súp sôi sùng sục.",
        detected_text=("RECIPE: TOMATO SOUP", "INGREDIENTS: TOMATO", "SCORE: 100"),
        window_title="Little Chef: Demo by Julien, hello erika, Danny-vD - Brave",
        process_name="brave.exe",
        captured_at=time.time(),
    )
    service.publish_snapshot(fresh_snapshot)

    mock_telemetry = MagicMock()
    mock_telemetry._get_foreground_window.return_value = {
        "title": "Little Chef: Demo by Julien, hello erika, Danny-vD - Brave",
        "process": "brave.exe",
        "process_name": "brave.exe",
    }
    mock_telemetry.capture_snapshot.return_value = None

    class DummyHost:
        def __init__(self):
            self.telemetry_service = mock_telemetry
            self.logger = MagicMock()
            self._chat_screen_route_decision = MagicMock()
            self._chat_screen_route_decision.references_screen = True
            self.last_vision_grounding_report = MagicMock()
            self.last_vision_grounding_report.grounded_claims = ()

        def _capture_screen_frame_for_chat(self, text, previous_public_turn=None):
            # User chats normally without direct screen command: no per-turn frame captured
            return ""

        def _chat_vision_status_prompt_context(self, screen_image_data_uri=""):
            # Would normally emit anti-vision guard if screenshot was taken but 0 grounded claims
            return "[VISION_STATUS]\nfresh_screen_capture: yes\ngrounded_visual_claims: 0\nrequired_stance: Không được nói tôi thấy\n[/VISION_STATUS]"

    host = DummyHost()
    assembler = ConversationEvidenceAssembler(host)

    # 1. Test assemble_chat with normal user query
    chat_evidence = assembler.assemble_chat("chào khán giả và nói về món súp hôm nay đi")
    chat_ctx = chat_evidence["source_grounding_context"]

    # Background vision MUST be embedded in chat grounding context!
    assert "[THỊ GIÁC MÀN HÌNH" in chat_ctx
    assert "đầu bếp đang nấu súp cà chua" in chat_ctx
    assert "RECIPE: TOMATO SOUP" in chat_ctx
    # Game profile MUST be embedded!
    assert "[GAMEPLAY CONTEXT" in chat_ctx
    assert "Little Chef" in chat_ctx
    # Anti-vision guard MUST be suppressed because we have fresh background vision!
    assert "Không được nói tôi thấy" not in chat_ctx

    # 2. Test assemble_autonomous
    auto_evidence = assembler.assemble_autonomous()
    auto_ctx = auto_evidence["source_grounding_context"]

    # Autonomous turn MUST have screen vision and game context!
    assert "[THỊ GIÁC MÀN HÌNH" in auto_ctx
    assert "đầu bếp đang nấu súp cà chua" in auto_ctx
    assert "[GAMEPLAY CONTEXT" in auto_ctx
    assert "Little Chef" in auto_ctx


def test_is_gaming_active_session_persistence():
    import time
    from runtime.autonomous_loop_runtime import AutonomousLoopRuntimeMixin

    class DummyAutonomousHost(AutonomousLoopRuntimeMixin):
        def __init__(self):
            self.telemetry_service = MagicMock()

    host = DummyAutonomousHost()

    # Step 1: Active game in foreground
    host.telemetry_service._get_foreground_window.return_value = {
        "title": "Little Chef: Demo by Julien, hello erika, Danny-vD - Brave",
        "process": "brave.exe",
    }
    assert host._is_gaming_active() is True
    assert getattr(host, "_last_game_title", "") == "Little Chef: Demo by Julien, hello erika, Danny-vD - Brave"

    # Step 2: User clicks on Eris window to type/chat
    host.telemetry_service._get_foreground_window.return_value = {
        "title": "Eris Virtual Companion",
        "process": "Eris.exe",
    }
    # Within 180s, session memory maintains gaming active!
    assert host._is_gaming_active() is True

    # Step 3: User minimizes to Desktop
    host.telemetry_service._get_foreground_window.return_value = {
        "title": "Desktop",
        "process": "explorer.exe",
    }
    assert host._is_gaming_active() is True

    # Step 4: After 200s, gaming session expires
    host._last_game_active_at = time.time() - 200.0
    assert host._is_gaming_active() is False


def test_vision_perception_worker_trigger_and_store_integration():
    import time
    from screen.vision_perception_worker import (
        VisionPerceptionWorker,
        VisionPerceptionSnapshot,
        VisionPerceptionService,
    )
    from screen.screen_evidence_store import ScreenEvidenceStore

    store = ScreenEvidenceStore()
    service = VisionPerceptionService()
    worker = VisionPerceptionWorker(
        service=service,
        store=store,
        poll_interval=10.0,
    )

    assert not worker.is_alive
    worker.trigger_now(force=True)
    assert worker._wake_event.is_set()

    # Simulate decomposition publishing to store
    snapshot = VisionPerceptionSnapshot(
        summary="Đang trong màn chơi Little Chef",
        detected_text=("START", "SCORE: 50"),
        window_title="Little Chef",
        process_name="brave.exe",
        captured_at=time.time(),
    )
    service.publish_snapshot(snapshot)

    # Publish text blocks to store as worker does
    from screen.evidence_models import ScreenTextBlock, ScreenTextSnapshot, ActiveWindowInfo
    blocks = tuple(
        ScreenTextBlock(
            block_id=f"vp_{i}",
            text=t,
            source="vision_perception",
            confidence=0.88,
            window_title=snapshot.window_title,
            captured_at=snapshot.captured_at,
        )
        for i, t in enumerate(snapshot.detected_text)
    )
    store.publish(ScreenTextSnapshot(
        blocks=blocks,
        window=ActiveWindowInfo(title=snapshot.window_title),
        captured_at=snapshot.captured_at,
    ))

    # ScreenEvidenceStore should now have ambient facts from background vision
    facts = store.ambient_facts(max_age_seconds=10.0)
    assert "START" in facts or "SCORE: 50" in facts


def test_stitch_two_frames():
    from PIL import Image
    from screen.vision_perception_worker import stitch_two_frames

    f1 = Image.new("RGB", (800, 600), (255, 0, 0))
    f2 = Image.new("RGB", (1024, 768), (0, 255, 0))
    composite = stitch_two_frames(f1, f2, time_gap_sec=5.2)

    assert composite.width == 1280
    assert composite.height == 388
    # Banner area (top 28 pixels) should be dark
    banner_pixel = composite.getpixel((5, 5))
    assert banner_pixel == (24, 24, 28)
    # Left frame area
    f1_pixel = composite.getpixel((100, 100))
    assert f1_pixel == (255, 0, 0)
    # Right frame area
    f2_pixel = composite.getpixel((700, 100))
    assert f2_pixel == (0, 255, 0)


def test_vision_perception_snapshot_motion_and_recipe():
    import time
    from screen.vision_perception_worker import VisionPerceptionSnapshot

    snap = VisionPerceptionSnapshot(
        summary="Đang ở trong căn bếp nhỏ của Little Chef.",
        motion="Người chơi vừa bấm PLAY và vào bếp, đang đứng cạnh nồi súp.",
        recipe_or_menu="Không có thực đơn, chế độ bếp tự do.",
        ingredients_and_tools=("mì ống", "sữa MÜLK", "bánh mì", "vỉ trứng", "nồi đen trên bếp"),
        inferred_story="Đầu bếp chuẩn bị nấu ăn.",
        window_title="Little Chef: Cozy Cooking",
        captured_at=time.time(),
    )

    ctx = snap.prompt_context()
    assert "[THỊ GIÁC MÀN HÌNH" in ctx
    assert "Biến chuyển (2 khung hình ~5s qua): Người chơi vừa bấm PLAY" in ctx
    assert "Thực đơn/Nhiệm vụ: Không có thực đơn" in ctx
    assert "Nguyên liệu & Đồ vật thấy trên màn hình: mì ống, sữa MÜLK, bánh mì, vỉ trứng, nồi đen trên bếp" in ctx
    assert "Little Chef: Cozy Cooking" in ctx

    d = snap.to_dict()
    assert d["motion"] == "Người chơi vừa bấm PLAY và vào bếp, đang đứng cạnh nồi súp."
    assert d["recipe_or_menu"] == "Không có thực đơn, chế độ bếp tự do."
    assert "mì ống" in d["ingredients_and_tools"]


def test_vision_perception_worker_cadence_and_is_gaming():
    from screen.evidence_models import ActiveWindowInfo
    from screen.vision_perception_worker import VisionPerceptionWorker, VisionPerceptionService

    svc = VisionPerceptionService()
    worker = VisionPerceptionWorker(service=svc)

    # Gaming window detection
    win_game = ActiveWindowInfo(title="Little Chef: Demo by Julien - Brave", process_name="brave.exe")
    assert worker._is_gaming(win_game) is True

    # Non-game window
    win_code = ActiveWindowInfo(title="game_knowledge.py - VSCode", process_name="code.exe")
    # Because game was just seen, session memory keeps it true for 180s on other windows, but without last_game_seen:
    worker._last_game_seen_at = 0.0
    assert worker._is_gaming(win_code) is False


def test_chat_cycle_non_blocking_when_gaming():
    class DummyHost(ChatCycleMixin):
        def __init__(self):
            self.logger = MagicMock()
            self._is_gaming_active = lambda: True
            self.telemetry_service = MagicMock()
            self.vision_perception_worker = MagicMock()
            self._chat_snapshot_for_vision = MagicMock()

    host = DummyHost()
    # coordinator mock
    mock_coord = MagicMock()
    mock_result = MagicMock()
    mock_result.route = MagicMock()
    mock_result.route.mode = "none"
    mock_result.screen_blocks = ()
    mock_result.capture_present = False
    mock_result.capture_interpreted = False
    mock_result.data_uri = ""
    mock_coord.prepare_turn.return_value = mock_result
    mock_coord.pending_vision = MagicMock()
    host._ensure_chat_perception_coordinator = lambda: mock_coord

    host._capture_screen_frame_for_chat("bấm play rồi mà")

    # Verify that prepare_turn was called with force_chat_vision=False (non-blocking!)
    mock_coord.prepare_turn.assert_called_once()
    kwargs = mock_coord.prepare_turn.call_args[1]
    assert kwargs["force_chat_vision"] is False


def test_chat_cycle_interpret_uses_vision_perception():
    from screen.vision_perception_worker import VisionPerceptionService, VisionPerceptionSnapshot
    import time

    svc = VisionPerceptionService()
    fresh_snap = VisionPerceptionSnapshot(
        summary="Căn bếp của Little Chef với đầy đủ nguyên liệu.",
        motion="Người chơi đang đứng cạnh bếp.",
        ingredients_and_tools=("nồi", "bếp điện", "sữa MÜLK", "mì ống", "bánh mì", "trứng"),
        recipe_or_menu="Chế độ tự do trong bếp.",
        captured_at=time.time(),
    )
    svc.publish_snapshot(fresh_snap)

    class DummyHost(ChatCycleMixin):
        def __init__(self):
            self.logger = MagicMock()
            self.vision_facts = ()
            self.vision_grounding_policy = None
            self.last_vision_grounding_report = None

    host = DummyHost()
    host._apply_vision_perception_snapshot_as_grounding(fresh_snap)

    # Verify that vision_facts contain rich Vietnamese ingredients and summary
    assert len(host.vision_facts) >= 3
    assert any("mì ống" in f for f in host.vision_facts)
    assert any("bánh mì" in f for f in host.vision_facts)
    assert host.last_vision_grounding_report is not None
    assert host.last_vision_grounding_report.recommendation == "speak"
    assert host.last_vision_grounding_report.reason == "vision_perception_service"


def test_vision_perception_worker_decompose_data_uri(monkeypatch):
    import io
    import base64
    from PIL import Image
    from screen.vision_perception_worker import VisionPerceptionWorker, VisionPerceptionService, VisionPerceptionSnapshot

    # Create dummy 1x1 image as base64 data URI
    img = Image.new("RGB", (64, 64), (100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64_str = base64.b64encode(buf.getvalue()).decode("ascii")
    data_uri = f"data:image/jpeg;base64,{b64_str}"

    svc = VisionPerceptionService()
    worker = VisionPerceptionWorker(service=svc)

    # Mock _send_to_gemini_docker to return a fake snapshot
    expected_snap = VisionPerceptionSnapshot(
        summary="Căn bếp Little Chef",
        ingredients_and_tools=("nồi", "bánh mì"),
    )
    monkeypatch.setattr(worker, "_send_to_gemini_docker", lambda *args, **kwargs: expected_snap)

    res = worker.decompose_data_uri(data_uri)
    assert res is not None
    assert res.summary == "Căn bếp Little Chef"
    assert "bánh mì" in res.ingredients_and_tools


def test_vision_perception_service_listeners():
    from screen.vision_perception_worker import VisionPerceptionService, VisionPerceptionSnapshot

    svc = VisionPerceptionService()
    received = []

    def on_snapshot(snap):
        received.append(snap)

    svc.register_listener(on_snapshot)
    snap1 = VisionPerceptionSnapshot(summary="Khung 1", ingredients_and_tools=("nồi",))
    svc.publish_snapshot(snap1)

    assert len(received) == 1
    assert received[0].summary == "Khung 1"
    assert svc.get_latest_snapshot() == snap1

    # Unregister
    svc.unregister_listener(on_snapshot)
    snap2 = VisionPerceptionSnapshot(summary="Khung 2")
    svc.publish_snapshot(snap2)

    # Should not receive snap2
    assert len(received) == 1
    assert svc.get_latest_snapshot() == snap2


def test_root_prompt_contract_anti_formulaic_and_genre_aware():
    from runtime.conversation.root_prompt_contract import SCREEN_COSTREAM_REVIEW_PROMPT

    # Verify organic living companion stance
    assert "LIVING GAMING COMPANION" in SCREEN_COSTREAM_REVIEW_PROMPT
    assert "Tâm thế Bạn Đồng Hành Sống Động" in SCREEN_COSTREAM_REVIEW_PROMPT
    assert "Phản xạ Đời Thường & Tự Nhiên" in SCREEN_COSTREAM_REVIEW_PROMPT
    assert "Bẻ Gãy Mọi Khuôn Mẫu" in SCREEN_COSTREAM_REVIEW_PROMPT

    # Verify genre rhythm and micro-turn live pacing
    assert "Nhạy cảm với Nhịp Điệu Từng Thể Loại" in SCREEN_COSTREAM_REVIEW_PROMPT
    assert "5–15 từ" in SCREEN_COSTREAM_REVIEW_PROMPT







