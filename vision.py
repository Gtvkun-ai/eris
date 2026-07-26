import os
import signal
import subprocess
import sys
import msvcrt
import traceback

from actions import ActionExecutor, ActionRouter
from app_logging import configure_logging, get_logger
from domain import Decision
from llm import LlmService
from llm.process_manager import RemoteModelProcessManager
from memory.memory_cognition import MemoryCognitionCore
from parser_grounding import DecisionParser
from runtime.coordinator import RuntimeCoordinator
from runtime.memory_semantic_parser_adapter import build_runtime_memory_semantic_parser
from runtime.tts_engine import build_tts_engine
from runtime.workspace_manager import ErisHome
from telemetry import TelemetryService
from transport import UdpTransport

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


class AttentionOverseer:
    def __init__(self, model_path: str = "", n_ctx: int = 8192, n_gpu_layers: int = -1):
        self.logger = get_logger("Vision")
        self.memory_logger = get_logger("Memory")
        self.parse_logger = get_logger("Parse")
        self.process_logger = get_logger("LLM")
        self.loop_logger = get_logger("Loop")
        self.action_logger = get_logger("Action")

        remote_enabled = os.environ.get("ERIS_REMOTE_API_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
        if remote_enabled:
            self.logger.info("Đang dùng remote API làm cognition chính.")
        else:
            self.logger.info("Remote API dang tat; local model runtime da bi go khoi runtime nay.")
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.eris_home = ErisHome()
        memory_root = self.eris_home.path("memory") / "core"
        memory_root.mkdir(parents=True, exist_ok=True)
        # Mọi store legacy còn sót cũng phải ghi vào ErisLive, không được lén
        # quay về source repo chỉ vì ai đó viết đường dẫn tương đối từ thời đồ đá.
        os.environ["ERIS_MEMORY_CORE_DIR"] = str(memory_root)
        # Materialize runtime settings trước khi dựng provider clients. Nếu làm
        # sau, panel có đổi model observer thì process vẫn ngoan cố dùng env cũ
        # đến lần khởi động kế tiếp, một kiểu "live settings" khá giàu tính châm biếm.
        try:
            from runtime.runtime_settings_store import RuntimeSettingsStore
            RuntimeSettingsStore().load(materialize_env=True)
        except Exception as exc:
            self.logger.debug("Runtime settings bootstrap trước provider bị bỏ qua: %s", exc)
        self.process_manager = RemoteModelProcessManager(
            logger=self.process_logger,
            project_root=project_root,
        )
        self.llm_client = self.process_manager.build_client(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
        )
        style_client = self.process_manager.build_style_client(
            model_path=model_path,
            n_ctx=min(n_ctx, 4096),
            n_gpu_layers=n_gpu_layers,
        )
        if style_client is not None:
            provider_label = getattr(style_client, "base_url", "") or style_client.__class__.__name__
            self.logger.info("Speech/style client đã sẵn sàng: %s", provider_label)
        vision_client = self.process_manager.build_vision_client(
            model_path=model_path,
            n_ctx=min(n_ctx, 4096),
            n_gpu_layers=n_gpu_layers,
        )
        if vision_client is not None:
            self.logger.info("Vision facts client đã sẵn sàng.")
        fallback_client = self.process_manager.build_format_fallback_client(
            model_path=model_path,
            n_ctx=min(n_ctx, 4096),
            n_gpu_layers=n_gpu_layers,
        )
        escalation_client = self.process_manager.build_escalation_client(
            model_path=model_path,
            n_ctx=min(n_ctx, 4096),
            n_gpu_layers=n_gpu_layers,
        )
        social_models_enabled = str(
            os.environ.get(
                "ERIS_SOCIAL_OBSERVER_ENABLED",
                os.environ.get("ERIS_SOCIAL_COGNITION_V2_ENABLED", "1"),
            ) or "1"
        ).strip().lower() in {"1", "true", "yes", "on"}
        social_parser_client = self.process_manager.build_social_parser_client() if social_models_enabled else None
        social_critic_client = self.process_manager.build_social_critic_client() if social_models_enabled else None
        social_fallback_client = self.process_manager.build_social_fallback_client() if social_models_enabled else None
        if escalation_client is not None:
            provider_label = getattr(escalation_client, "base_url", "") or escalation_client.__class__.__name__
            self.logger.info("Escalation client (bái sư) đã sẵn sàng: %s", provider_label)
        self.llm_service = LlmService(
            self.llm_client,
            style_client=style_client,
            vision_client=vision_client,
            fallback_client=fallback_client,
            escalation_client=escalation_client,
            social_parser_client=social_parser_client,
            social_critic_client=social_critic_client,
            social_fallback_client=social_fallback_client,
            logger=self.logger,
        )
        self.logger.info("Mô hình đã sẵn sàng.")
        self.memory_semantic_parser = build_runtime_memory_semantic_parser(
            llm_service=self.llm_service,
            logger=self.memory_logger,
        )
        if self.memory_semantic_parser is not None:
            self.memory_logger.info(
                "Memory semantic parser đã bật: provider=%s model=%s",
                getattr(self.memory_semantic_parser, "provider", "unknown"),
                getattr(self.memory_semantic_parser, "model", ""),
            )

        self.transport = UdpTransport("127.0.0.1", 4242, "127.0.0.1", 4243)
        self.memory_core = MemoryCognitionCore(str(memory_root))
        try:
            memory_state = self.memory_core.load()
            packet = self.memory_core.recall("")
            long_term_memory = []
            for name in ("repair", "procedural", "semantic", "relational", "affective_residue", "episodic"):
                long_term_memory.extend(str(item) for item in getattr(packet, name, ()) or ())
            if long_term_memory:
                self.memory_logger.info("Đã nạp %s mảnh ký ức cốt lõi.", len(long_term_memory))
        except Exception as exc:
            memory_state = None
            long_term_memory = []
            self.memory_logger.warning("Lỗi đọc tệp ký ức: %s", exc)

        fallback_decision = Decision(
            text="Lỗi phân tích cú pháp. Chuỗi JSON từ hệ thống bị hỏng.",
            animation="stand",
            extracted_fact="",
        )
        self.decision_parser = DecisionParser(fallback_decision, logger=self.parse_logger)
        self.telemetry_service = TelemetryService()
        self.action_executor = ActionExecutor(logger=self.action_logger)
        self.action_router = ActionRouter()
        self.coordinator = RuntimeCoordinator(
            logger=self.loop_logger,
            transport=self.transport,
            llm_service=self.llm_service,
            parser=self.decision_parser,
            telemetry_service=self.telemetry_service,
            memory_core=self.memory_core,
            body_running_fn=self._is_body_running,
            action_executor=self.action_executor,
            action_router=self.action_router,
            memory_semantic_parser=self.memory_semantic_parser,
        )
        if memory_state is not None:
            self.coordinator.memory_state = memory_state
        self.coordinator.long_term_memory = long_term_memory

        # TTS engine — khởi động sau coordinator để biết cờ ERIS_TTS_ENABLED.
        self.tts_engine = build_tts_engine()
        bind_tts = getattr(self.coordinator, "bind_tts_engine", None)
        if callable(bind_tts):
            bind_tts(self.tts_engine)
        else:
            self.coordinator.tts_engine = self.tts_engine

    def _is_body_running(self) -> bool:
        try:
            result = subprocess.run(
                ["tasklist", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = result.stdout.lower()
            return "godot" in output or "eris" in output
        except Exception:
            return True

    def stop(self, reason: str = ""):
        if not self.coordinator.running:
            return
        if reason:
            self.logger.info(reason)
        self.coordinator.stop()
        self.process_manager.stop()
        if hasattr(self, "tts_engine") and self.tts_engine is not None:
            self.tts_engine.shutdown()

    def run_loop(self):
        self.coordinator.run_loop()


class SingleInstanceLock:
    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        self.handle = None

    def acquire(self):
        self.handle = open(self.lock_path, "a+")
        self.handle.seek(0)
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError("vision.py đã chạy ở tiến trình khác.")
        self.handle.truncate(0)
        self.handle.write(str(os.getpid()))
        self.handle.flush()

    def release(self):
        if not self.handle:
            return
        try:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.handle.close()
        self.handle = None


if __name__ == "__main__":
    configure_logging()
    logger = get_logger("Vision")

    # Nạp .env (OS-env > .env > secrets.json) NGAY khi khởi động để mọi toggle/
    # provider trong .env thực sự có hiệu lực dưới Eris.exe (sửa R3/E7).
    from eris_secrets import apply_secrets_to_environ, log_config_sources

    apply_secrets_to_environ()
    log_config_sources(
        "ERIS_REMOTE_PROVIDER",
        "ERIS_LOCAL_LLM_ENGINE",
        "ERIS_PRIVATE_MIND_PROVIDER",
        "ERIS_PRIVATE_MIND_FRAGMENT_PROVIDER",
        "ERIS_LLM_PROMPT_HARD_CAP_TOKENS",
    )

    runtime_home = ErisHome()
    lock_file = str(runtime_home.path("state") / "vision.lock")
    lock = SingleInstanceLock(lock_file)
    try:
        lock.acquire()
    except RuntimeError as exc:
        get_logger("Lock").error("%s", exc)
        raise SystemExit(1)

    if len(sys.argv) > 1:
        model_path = sys.argv[1]
    else:
        model_path = ""

    remote_enabled = os.environ.get("ERIS_REMOTE_API_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
    if not remote_enabled:
        logger.error("ERIS_REMOTE_API_ENABLED=0 nhưng local model runtime đã bị gỡ khỏi runtime.")
        raise SystemExit(1)

    raw_ctx = os.environ.get("ERIS_N_CTX", "").strip()
    n_ctx = 8192
    if raw_ctx:
        try:
            n_ctx = int(raw_ctx)
        except ValueError:
            logger.warning("ERIS_N_CTX=%r khong hop le, dung mac dinh %d.", raw_ctx, n_ctx)

    overseer = AttentionOverseer(model_path, n_ctx=n_ctx)

    def handle_signal(signum, _frame):
        overseer.stop(f"Nhận tín hiệu {signum}, đang thoát...")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, handle_signal)

    try:
        overseer.run_loop()
    except KeyboardInterrupt:
        overseer.stop("KeyboardInterrupt")
    except Exception as exc:
        logger.error("vision.py gặp lỗi chưa bắt: %s", exc)
        traceback.print_exc()
        raise
    finally:
        overseer.stop("Dừng tiến trình.")
        lock.release()
