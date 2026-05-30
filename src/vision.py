import os
import signal
import subprocess
import sys
import msvcrt
import traceback

from actions import ActionExecutor, ActionRouter
from app_logging import configure_logging, get_logger
from cortex import FeRenderer, NiEngine, TiGovernor
from domain import Decision
from llm import LlmService
from llm.process_manager import LlamaServerProcessManager
from memory.memory_cognition import MemoryCognitionCore
from parser_grounding import DecisionParser
from runtime.coordinator import RuntimeCoordinator
from runtime.memory_semantic_parser_adapter import build_runtime_memory_semantic_parser
from telemetry import TelemetryService
from transport import UdpTransport

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


class AttentionOverseer:
    def __init__(self, model_path: str, n_ctx: int = 8192, n_gpu_layers: int = -1):
        self.logger = get_logger("Vision")
        self.memory_logger = get_logger("Memory")
        self.parse_logger = get_logger("Parse")
        self.process_logger = get_logger("LLM")
        self.loop_logger = get_logger("Loop")
        self.action_logger = get_logger("Action")

        patched_path = model_path.replace(".gguf", "_patched.gguf")
        if os.path.exists(patched_path):
            self.logger.info("Phát hiện model đã vá: %s", patched_path)
            model_path = patched_path

        remote_enabled = os.environ.get("ERIS_REMOTE_API_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
        if remote_enabled:
            self.logger.info("Đang dùng remote API làm cognition chính.")
        else:
            self.logger.info("Đang tải mô hình GGUF làm cognition chính: %s", model_path)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.process_manager = LlamaServerProcessManager(
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
            self.logger.info("Local GGUF style rewrite đã sẵn sàng.")
        vision_client = self.process_manager.build_vision_client(
            model_path=model_path,
            n_ctx=min(n_ctx, 4096),
            n_gpu_layers=n_gpu_layers,
        )
        if vision_client is not None:
            self.logger.info("Local GGUF vision facts đã sẵn sàng với mmproj.")
        self.llm_service = LlmService(
            self.llm_client,
            style_client=style_client,
            vision_client=vision_client,
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
        self.memory_core = MemoryCognitionCore(os.path.join(project_root, "memory_core"))
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
        self.ni_engine = NiEngine()
        self.ti_governor = TiGovernor(logger=self.loop_logger)
        self.fe_renderer = FeRenderer()
        self.action_executor = ActionExecutor(logger=self.action_logger)
        self.action_router = ActionRouter()
        self.coordinator = RuntimeCoordinator(
            logger=self.loop_logger,
            transport=self.transport,
            llm_service=self.llm_service,
            parser=self.decision_parser,
            telemetry_service=self.telemetry_service,
            ni_engine=self.ni_engine,
            ti_governor=self.ti_governor,
            fe_renderer=self.fe_renderer,
            memory_core=self.memory_core,
            body_running_fn=self._is_body_running,
            action_executor=self.action_executor,
            action_router=self.action_router,
            memory_semantic_parser=self.memory_semantic_parser,
        )
        if memory_state is not None:
            self.coordinator.memory_state = memory_state
        self.coordinator.long_term_memory = long_term_memory

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

    lock_file = os.path.join(os.path.dirname(__file__), ".vision.lock")
    lock = SingleInstanceLock(lock_file)
    try:
        lock.acquire()
    except RuntimeError as exc:
        get_logger("Lock").error("%s", exc)
        raise SystemExit(1)

    if len(sys.argv) > 1:
        model_path = sys.argv[1]
    else:
        model_path = os.environ.get(
            "GGUF_MODEL_PATH",
            os.path.join(os.path.dirname(__file__), "model.gguf"),
        )

    remote_enabled = os.environ.get("ERIS_REMOTE_API_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
    style_enabled = os.environ.get("ERIS_LOCAL_STYLE_REWRITE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
    if not os.path.isfile(model_path) and (not remote_enabled or style_enabled):
        logger.error("Không tìm thấy file mô hình: %s", model_path)
        logger.error("Dùng: python vision.py <đường_dẫn_model.gguf>")
        logger.error("Hoặc: set GGUF_MODEL_PATH=<đường_dẫn_model.gguf>")
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
