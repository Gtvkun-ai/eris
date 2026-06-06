import os
import shutil
import subprocess
import time
from urllib.parse import urlparse

import requests

from eris_secrets import apply_secrets_to_environ, get_provider_profile, get_secret
from .client import GeminiClient, LlamaServerClient, OpenAICompatibleClient


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

    def _base_root_url(self, base_url: str) -> str:
        value = (base_url or "").rstrip("/")
        if value.endswith("/v1"):
            return value[: -len("/v1")]
        return value

    def _deep_find_int(self, payload, keys: tuple[str, ...]) -> int | None:
        """Recursively search nested JSON payload for any key in `keys`.

        Returns the first positive integer found, else None.
        """
        if payload is None:
            return None
        if isinstance(payload, dict):
            for k, v in payload.items():
                if isinstance(k, str) and k in keys:
                    try:
                        value = int(v)
                        if value > 0:
                            return value
                    except (TypeError, ValueError):
                        pass
                found = self._deep_find_int(v, keys)
                if found is not None:
                    return found
            return None
        if isinstance(payload, list):
            for item in payload:
                found = self._deep_find_int(item, keys)
                if found is not None:
                    return found
            return None
        return None

    def _detect_running_server_n_ctx(self, base_url: str) -> int | None:
        """Best-effort detection of the currently running llama-server context size.

        llama.cpp server typically exposes `/props` on the base root (not `/v1`).
        If unavailable, returns None.
        """
        root = self._base_root_url(base_url)
        if not root:
            return None

        candidate_urls = []
        # Common endpoints across llama.cpp server versions / proxies.
        candidate_urls.append(f"{root}/props")
        candidate_urls.append(f"{root}/v1/props")

        base = (base_url or "").rstrip("/")
        candidate_urls.append(f"{base}/props")

        keys = (
            "n_ctx",
            "n_ctx_per_seq",
            "n_ctx_seq",
            "context_length",
            "ctx_size",
            "ctx",
        )

        for url in candidate_urls:
            try:
                response = requests.get(url, timeout=3)
                if not response.ok:
                    continue
                payload = response.json() if response.content else {}
            except Exception:
                continue

            found = self._deep_find_int(payload, keys)
            if found is not None:
                return found

        return None

    def _kill_local_llama_server_on_port(self, port: int) -> bool:
        """Best-effort: kill llama-server listening on localhost:<port>.

        Only kills if the owning process name looks like llama-server.
        """
        try:
            port = int(port)
        except (TypeError, ValueError):
            return False

        if port <= 0:
            return False

        if os.name == "nt":
            try:
                netstat = subprocess.check_output(
                    ["netstat", "-ano", "-p", "tcp"],
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                )
            except Exception:
                return False

            pids: set[int] = set()
            needle = f":{port}"
            for line in netstat.splitlines():
                # Example: TCP    127.0.0.1:8080     0.0.0.0:0    LISTENING    1234
                if "LISTEN" not in line.upper():
                    continue
                if needle not in line:
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                local_addr = parts[1]
                pid_str = parts[-1]
                if not local_addr.endswith(needle):
                    continue
                try:
                    pids.add(int(pid_str))
                except ValueError:
                    continue

            killed_any = False
            for pid in sorted(pids):
                try:
                    tasklist = subprocess.check_output(
                        ["tasklist", "/FI", f"PID eq {pid}"],
                        text=True,
                        encoding="utf-8",
                        errors="ignore",
                    ).lower()
                    if "llama-server" not in tasklist:
                        continue
                    subprocess.check_call(["taskkill", "/PID", str(pid), "/T", "/F"])
                    killed_any = True
                except Exception:
                    continue

            return killed_any

        # POSIX fallback.
        try:
            pids_raw = subprocess.check_output(
                ["lsof", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
        except Exception:
            return False

        killed_any = False
        for pid_str in pids_raw.split():
            try:
                pid = int(pid_str)
            except ValueError:
                continue
            try:
                comm = subprocess.check_output(
                    ["ps", "-p", str(pid), "-o", "comm="],
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                ).strip().lower()
                if "llama-server" not in comm:
                    continue
                os.kill(pid, 9)
                killed_any = True
            except Exception:
                continue
        return killed_any

    def _pick_free_port(self, host: str, preferred_port: int, *, span: int = 20) -> int:
        for offset in range(0, max(1, span)):
            port = preferred_port + offset
            try:
                response = requests.get(f"http://{host}:{port}/v1/models", timeout=1)
                if response.ok:
                    continue
            except Exception:
                return port
        return preferred_port

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

        # Avoid large prompt-cache RAM usage by default. Users can override via
        # LLAMA_SERVER_CACHE_RAM or include --cache-ram in LLAMA_SERVER_EXTRA_ARGS.
        already_has_cache_ram = "--cache-ram" in command
        cache_ram_env = os.environ.get("LLAMA_SERVER_CACHE_RAM", "").strip()
        if not already_has_cache_ram:
            if cache_ram_env:
                normalized = cache_ram_env.lower()
                if normalized in {"0", "off", "false", "no", "none"}:
                    command.extend(["--cache-ram", "0"])
                elif normalized.isdigit():
                    command.extend(["--cache-ram", normalized])
                else:
                    self.logger.warning(
                        "LLAMA_SERVER_CACHE_RAM=%r khong hop le; dung --cache-ram 1024.",
                        cache_ram_env,
                    )
                    command.extend(["--cache-ram", "1024"])
            else:
                command.extend(["--cache-ram", "1024"])

        return command

    def _resolve_mmproj_path(self) -> str:
        raw_value = os.environ.get("LLAMA_SERVER_MMPROJ", "").strip()
        if raw_value.lower() in {"0", "false", "no", "off", "none"}:
            return ""

        candidates = []
        if raw_value:
            candidates.append(raw_value)
        candidates.append(os.path.join(self.project_root, "src", "mmproj-F16.gguf"))

        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate

        if raw_value:
            self.logger.warning("Khong tim thay mmproj tai %s, chay local model o che do text-only.", raw_value)
        return ""

    def _env_flag(self, name: str, default: str = "0") -> bool:
        return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}

    def _build_remote_client(self):
        apply_secrets_to_environ()
        provider = os.environ.get("ERIS_REMOTE_PROVIDER", "gemini").strip().lower()
        remote_profile = get_provider_profile(provider, slot="remote_main")
        api_key = (
            str(remote_profile.get("api_key") or "").strip()
            or get_secret("ERIS_REMOTE_API_KEY", "GEMINI_API_KEY")
        )

        if provider == "gemini":
            base_url = (
                str(remote_profile.get("base_url") or "").strip()
                or os.environ.get(
                    "ERIS_REMOTE_BASE_URL",
                    "https://generativelanguage.googleapis.com/v1beta",
                ).strip()
            )
            model_name = (
                str(remote_profile.get("model") or "").strip()
                or str(remote_profile.get("model_name") or "").strip()
                or os.environ.get("ERIS_REMOTE_MODEL", "").strip()
                or os.environ.get("GEMINI_MODEL", "").strip()
                or "gemma-4-26b-a4b-it"
            )
            if not api_key:
                raise RuntimeError("Remote Gemini dang bat nhung chua co GEMINI_API_KEY hoac ERIS_REMOTE_API_KEY.")
            self.logger.info("Dung Gemini API tai %s voi model %s", base_url, model_name)
            try:
                return GeminiClient(base_url=base_url, api_key=api_key, model_name=model_name)
            except ValueError as exc:
                raise RuntimeError(f"Loi API key Gemini: {exc}") from exc

        base_url = (
            str(remote_profile.get("base_url") or "").strip()
            or os.environ.get("ERIS_REMOTE_BASE_URL", "https://api-v2.shopaikey.com/v1").strip()
        )
        model_name = (
            str(remote_profile.get("model") or "").strip()
            or str(remote_profile.get("model_name") or "").strip()
            or os.environ.get("ERIS_REMOTE_MODEL", "gemini-3-flash-preview").strip()
        )
        if not api_key:
            raise RuntimeError("Remote API dang bat nhung chua co ERIS_REMOTE_API_KEY.")
        self.logger.info("Dung OpenAI-compatible API tai %s voi model %s", base_url, model_name)
        try:
            return OpenAICompatibleClient(
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
            )
        except ValueError as exc:
            raise RuntimeError(f"Loi API key remote: {exc}") from exc

    def _speech_api_requested(self) -> bool:
        apply_secrets_to_environ()
        if self._env_flag("ERIS_SPEECH_API_ENABLED", "0"):
            return True
        if get_secret("ERIS_SPEECH_API_KEY", "ERIS_STYLE_API_KEY", "OPENAI_SPEECH_API_KEY", "GEMINI_SPEECH_API_KEY"):
            return True
        if os.environ.get("ERIS_SPEECH_PROVIDER", "").strip():
            return True
        profile_provider = os.environ.get("ERIS_SPEECH_PROVIDER", os.environ.get("ERIS_REMOTE_PROVIDER", "gemini")).strip().lower()
        return bool(get_provider_profile(profile_provider, slot=os.environ.get("ERIS_SPEECH_SLOT", "speech")))

    def _build_speech_client(self):
        """Build a dedicated public-speech model client.

        This keeps the main cognition client and the final wording client on
        separate API keys/endpoints when configured, while preserving the old
        local style rewrite path as fallback.
        """

        apply_secrets_to_environ()
        provider = os.environ.get("ERIS_SPEECH_PROVIDER", os.environ.get("ERIS_REMOTE_PROVIDER", "gemini")).strip().lower()
        slot = os.environ.get("ERIS_SPEECH_SLOT", "speech").strip() or "speech"
        profile = get_provider_profile(provider, slot=slot)
        api_key = (
            str(profile.get("api_key") or "").strip()
            or get_secret("ERIS_SPEECH_API_KEY", "ERIS_STYLE_API_KEY")
        )

        if provider == "gemini":
            api_key = api_key or get_secret("GEMINI_SPEECH_API_KEY", "GEMINI_API_KEY", "ERIS_REMOTE_API_KEY")
            base_url = (
                str(profile.get("base_url") or "").strip()
                or os.environ.get(
                    "ERIS_SPEECH_BASE_URL",
                    os.environ.get("ERIS_REMOTE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
                ).strip()
            )
            model_name = (
                str(profile.get("model") or "").strip()
                or str(profile.get("model_name") or "").strip()
                or os.environ.get("ERIS_SPEECH_MODEL", "").strip()
                or os.environ.get("ERIS_REMOTE_MODEL", "").strip()
                or os.environ.get("GEMINI_MODEL", "").strip()
                or "gemma-4-26b-a4b-it"
            )
            if not api_key:
                raise RuntimeError("Speech Gemini dang bat nhung chua co ERIS_SPEECH_API_KEY hoac GEMINI_API_KEY.")
            self.logger.info("Dung Gemini speech API tai %s voi model %s", base_url, model_name)
            try:
                return GeminiClient(base_url=base_url, api_key=api_key, model_name=model_name)
            except ValueError as exc:
                raise RuntimeError(f"Loi API key speech Gemini: {exc}") from exc

        if provider == "llama_server":
            base_url = (
                str(profile.get("base_url") or "").strip()
                or os.environ.get("ERIS_SPEECH_LLAMA_SERVER_URL", os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8081/v1")).strip()
            ).rstrip("/")
            self.logger.info("Dung llama-server speech rieng tai %s", base_url)
            return LlamaServerClient(base_url)

        api_key = api_key or get_secret("OPENAI_SPEECH_API_KEY", "ERIS_REMOTE_API_KEY", "OPENAI_API_KEY")
        base_url = (
            str(profile.get("base_url") or "").strip()
            or os.environ.get("ERIS_SPEECH_BASE_URL", os.environ.get("ERIS_REMOTE_BASE_URL", "https://api.openai.com/v1")).strip()
        )
        model_name = (
            str(profile.get("model") or "").strip()
            or str(profile.get("model_name") or "").strip()
            or os.environ.get("ERIS_SPEECH_MODEL", "").strip()
            or os.environ.get("ERIS_REMOTE_MODEL", "gemma-4-26b-a4b-it").strip()
        )
        if not api_key:
            raise RuntimeError("Speech API dang bat nhung chua co ERIS_SPEECH_API_KEY.")
        self.logger.info("Dung OpenAI-compatible speech API tai %s voi model %s", base_url, model_name)
        try:
            return OpenAICompatibleClient(base_url=base_url, api_key=api_key, model_name=model_name)
        except ValueError as exc:
            raise RuntimeError(f"Loi API key speech remote: {exc}") from exc

    def build_client(self, *, model_path: str, n_ctx: int, n_gpu_layers: int):
        remote_enabled = self._env_flag("ERIS_REMOTE_API_ENABLED", "1")
        if remote_enabled:
            return self._build_remote_client()

        base_url = os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8080/v1").rstrip("/")

        # If we detect a running server with insufficient n_ctx, prefer replacing it
        # (kill old llama-server on the preferred port) to avoid accumulating multiple
        # servers on incremented ports.
        should_replace_existing = False

        reuse_deadline = time.time() + 15
        while time.time() < reuse_deadline:
            try:
                response = requests.get(f"{base_url}/models", timeout=3)
                if response.ok:
                    payload = response.json()
                    if payload.get("data"):
                        # Only reuse if the running server has enough context.
                        if int(n_ctx or 0) > 4096:
                            detected_ctx = self._detect_running_server_n_ctx(base_url)
                            if detected_ctx is None:
                                self.logger.warning(
                                    "Phat hien llama-server dang chay tai %s nhung khong doc duoc n_ctx; "
                                    "can n_ctx=%s nen se khoi dong server moi.",
                                    base_url,
                                    n_ctx,
                                )
                                should_replace_existing = True
                                break
                            if detected_ctx < int(n_ctx):
                                self.logger.warning(
                                    "Phat hien llama-server dang chay tai %s voi n_ctx=%s < can=%s; "
                                    "se khoi dong server moi.",
                                    base_url,
                                    detected_ctx,
                                    n_ctx,
                                )
                                should_replace_existing = True
                                break

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
        raw_port = os.environ.get("LLAMA_SERVER_PORT", "8080")
        try:
            preferred_port = int(raw_port)
        except ValueError:
            preferred_port = 8080

        port_to_use = preferred_port
        if should_replace_existing and host in {"127.0.0.1", "localhost", "0.0.0.0"}:
            # If something is already on the preferred port, try to kill it if it's llama-server.
            try:
                probe = requests.get(f"http://{host}:{preferred_port}/v1/models", timeout=1)
                if probe.ok:
                    if self._kill_local_llama_server_on_port(preferred_port):
                        # Give the OS a moment to release the port.
                        time.sleep(0.5)
                    else:
                        port_to_use = self._pick_free_port(host, preferred_port)
            except Exception:
                # Port seems free (or unreachable) - keep preferred.
                pass
        else:
            port_to_use = self._pick_free_port(host, preferred_port)

        port = str(port_to_use)
        mmproj_path = self._resolve_mmproj_path()

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
        if mmproj_path:
            command.extend(["--mmproj", mmproj_path])
        command.extend(self._build_optional_args())
        if mmproj_path and not any("mmproj-offload" in arg for arg in command):
            command.append("--mmproj-offload")

        self.logger.info("Khoi dong llama-server: %s", " ".join(command))
        self._server_proc = subprocess.Popen(command)
        self._wait_for_llama_server(f"http://{host}:{port}/v1")
        return LlamaServerClient(f"http://{host}:{port}/v1")

    def build_style_client(self, *, model_path: str, n_ctx: int, n_gpu_layers: int):
        if self._speech_api_requested():
            return self._build_speech_client()

        if not self._env_flag("ERIS_LOCAL_STYLE_REWRITE_ENABLED", "0"):
            return None
        if not os.path.isfile(model_path):
            self.logger.warning("Khong tim thay GGUF style model tai %s; tat local style rewrite.", model_path)
            return None

        previous_remote = os.environ.get("ERIS_REMOTE_API_ENABLED")
        try:
            os.environ["ERIS_REMOTE_API_ENABLED"] = "0"
            return self.build_client(model_path=model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers)
        finally:
            if previous_remote is None:
                os.environ.pop("ERIS_REMOTE_API_ENABLED", None)
            else:
                os.environ["ERIS_REMOTE_API_ENABLED"] = previous_remote

    def build_vision_client(self, *, model_path: str, n_ctx: int, n_gpu_layers: int):
        if not self._env_flag("ERIS_LOCAL_VISION_FACTS", "1"):
            return None
        mmproj_path = self._resolve_mmproj_path()
        if not mmproj_path:
            self.logger.warning("Khong tim thay mmproj vision; vision_facts se khong dung client cognition chinh.")
            return None
        if not os.path.isfile(model_path):
            self.logger.warning("Khong tim thay GGUF vision model tai %s; vision_facts se khong dung client cognition chinh.", model_path)
            return None

        previous_remote = os.environ.get("ERIS_REMOTE_API_ENABLED")
        try:
            os.environ["ERIS_REMOTE_API_ENABLED"] = "0"
            client = self.build_client(model_path=model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers)
            self.logger.info("Local vision_facts dung mmproj: %s", mmproj_path)
            return client
        finally:
            if previous_remote is None:
                os.environ.pop("ERIS_REMOTE_API_ENABLED", None)
            else:
                os.environ["ERIS_REMOTE_API_ENABLED"] = previous_remote

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
