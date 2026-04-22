import os
import shutil
import subprocess
import time

import requests

from .client import LlamaServerClient, OpenAICompatibleClient


class LlamaServerProcessManager:
    def __init__(self, *, logger, project_root: str):
        self.logger = logger
        self.project_root = project_root
        self._server_proc = None

    def _find_llama_server_exe(self):
        candidates = []
        env_path = os.environ.get("LLAMA_SERVER_EXE", "").strip()
        if env_path:
            candidates.append(env_path)

        candidates.append(
            os.path.join(
                self.project_root,
                "lib",
                "llama-b8466-bin-win-cuda-12.4-x64",
                "llama-server.exe",
            )
        )

        which_path = shutil.which("llama-server.exe")
        if which_path:
            candidates.append(which_path)

        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate
        return None

    def _wait_for_llama_server(self, base_url: str, timeout: int = 300):
        deadline = time.time() + timeout
        last_error = ""

        while time.time() < deadline:
            if self._server_proc is not None and self._server_proc.poll() is not None:
                raise RuntimeError("llama-server da thoat som khi khoi dong.")
            try:
                response = requests.get(f"{base_url}/models", timeout=5)
                if response.ok:
                    payload = response.json()
                    models = payload.get("data", [])
                    if models:
                        return
                    last_error = "llama-server da mo cong nhung chua load xong model."
            except Exception as exc:
                last_error = str(exc)
            time.sleep(1)

        raise RuntimeError(f"llama-server khong phan hoi kip thoi. {last_error}")

    def _resolve_gpu_layers(self, n_gpu_layers) -> str:
        if isinstance(n_gpu_layers, int) and n_gpu_layers >= 0:
            return str(n_gpu_layers)

        raw_value = os.environ.get("LLAMA_SERVER_NGL", "all").strip().lower()
        if raw_value in {"all", "auto"} or raw_value.isdigit():
            return raw_value

        self.logger.warning("LLAMA_SERVER_NGL=%r khong hop le, fallback ve 'all'.", raw_value)
        return "all"

    def _build_optional_args(self):
        command = []

        flash_attn = os.environ.get("LLAMA_SERVER_FLASH_ATTN", "on").strip().lower()
        if flash_attn in {"on", "off", "auto"}:
            command.extend(["--flash-attn", flash_attn])

        extra_args = os.environ.get("LLAMA_SERVER_EXTRA_ARGS", "").strip()
        if extra_args:
            command.extend(extra_args.split())

        return command

    def build_client(self, *, model_path: str, n_ctx: int, n_gpu_layers: int):
        remote_enabled = os.environ.get("ERIS_REMOTE_API_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
        if remote_enabled:
            api_key = os.environ.get("ERIS_REMOTE_API_KEY", "").strip()
            base_url = os.environ.get("ERIS_REMOTE_BASE_URL", "https://api-v2.shopaikey.com/v1").strip()
            model_name = os.environ.get("ERIS_REMOTE_MODEL", "gemini-3-flash-preview").strip()
            if not api_key:
                raise RuntimeError("ERIS_REMOTE_API_ENABLED dang bat nhung chua co ERIS_REMOTE_API_KEY.")

            self.logger.info("Dung remote API tai %s voi model %s", base_url, model_name)
            try:
                return OpenAICompatibleClient(
                    base_url=base_url,
                    api_key=api_key,
                    model_name=model_name,
                )
            except ValueError as exc:
                raise RuntimeError(f"Loi API key remote: {exc}") from exc

        base_url = os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8080/v1").rstrip("/")

        reuse_deadline = time.time() + 15
        while time.time() < reuse_deadline:
            try:
                response = requests.get(f"{base_url}/models", timeout=3)
                if response.ok:
                    payload = response.json()
                    if payload.get("data"):
                        self.logger.info("Tai su dung llama-server dang chay tai %s", base_url)
                        return LlamaServerClient(base_url)
            except Exception:
                pass
            time.sleep(1)

        server_exe = self._find_llama_server_exe()
        if not server_exe:
            raise RuntimeError(
                "Khong tim thay llama-server.exe. Hay dat bien moi truong LLAMA_SERVER_EXE tro toi file nay."
            )

        ngl = self._resolve_gpu_layers(n_gpu_layers)
        host = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")
        port = os.environ.get("LLAMA_SERVER_PORT", "8080")

        command = [
            server_exe,
            "-m",
            model_path,
            "-c",
            str(n_ctx),
            "-ngl",
            str(ngl),
            "--host",
            host,
            "--port",
            port,
            "--no-warmup",
            "--jinja",
            "--reasoning-format",
            "deepseek",
        ]
        command.extend(self._build_optional_args())

        self.logger.info("Khoi dong llama-server: %s", " ".join(command))
        self._server_proc = subprocess.Popen(command)
        self._wait_for_llama_server(f"http://{host}:{port}/v1")
        return LlamaServerClient(f"http://{host}:{port}/v1")

    def stop(self):
        if self._server_proc is None or self._server_proc.poll() is not None:
            return
        try:
            self._server_proc.terminate()
            self._server_proc.wait(timeout=10)
        except Exception:
            try:
                self._server_proc.kill()
            except Exception:
                pass
