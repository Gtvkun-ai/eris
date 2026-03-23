import os
import shutil
import subprocess
import time

import requests

from .client import LlamaServerClient


class LlamaServerProcessManager:
    def __init__(self, *, logger, project_root: str):
        self.logger = logger
        self.project_root = project_root
        self._server_proc = None

    # _find_llama_server_exe tìm kiếm file thực thi llama-server.exe trong một số vị trí tiềm năng,
    # bao gồm đường dẫn được chỉ định trong biến môi trường LLAMA_SERVER_EXE,
    # thư mục lib trong dự án,  và trong PATH hệ thống. 
    # Nếu tìm thấy file, nó trả về đường dẫn đầy đủ; nếu không tìm thấy, nó trả về None.
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

    # _wait_for_llama_server liên tục kiểm tra xem llama-server
    #  đã sẵn sàng để nhận yêu cầu hay chưa bằng cách gửi yêu cầu GET 
    # đến endpoint /models.
    # Nếu server phản hồi thành công và trả về thông tin về các
    #  mô hình đã load, hàm sẽ trả về. Nếu server mở cổng nhưng 
    # chưa load xong model, nó sẽ ghi lại lỗi và tiếp tục chờ. 
    # Nếu server không phản hồi kịp thời hoặc thoát sớm, 
    # nó sẽ ném ra lỗi RuntimeError với thông tin chi tiết về lỗi cuối cùng gặp phải.
    def _wait_for_llama_server(self, base_url: str, timeout: int = 300):
        deadline = time.time() + timeout
        last_error = ""

        while time.time() < deadline:
            if self._server_proc is not None and self._server_proc.poll() is not None:
                raise RuntimeError("llama-server đã thoát sớm khi khởi động.")
            try:
                response = requests.get(f"{base_url}/models", timeout=5)
                if response.ok:
                    payload = response.json()
                    models = payload.get("data", [])
                    if models:
                        return
                    last_error = "llama-server đã mở cổng nhưng chưa load xong model."
            except Exception as exc:
                last_error = str(exc)
            time.sleep(1)

        raise RuntimeError(f"llama-server không phản hồi kịp thời. {last_error}")

    # build_client là phương thức chính để tạo một instance của LlamaServerClient.
    # Nó đầu tiên cố gắng tái sử dụng một instance llama-server đang chạy 
    # nếu có thể kết nối thành công đến endpoint /models. 
    # Nếu không thể tái sử dụng, nó sẽ tìm kiếm file thực thi llama-server.exe, 
    # khởi động một tiến trình mới với các tham số cấu hình, và chờ cho đến khi 
    # server sẵn sàng trước khi trả về một instance LlamaServerClient kết nối đến 
    # server đó.
    def build_client(self, *, model_path: str, n_ctx: int, n_gpu_layers: int):
        base_url = os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8080/v1").rstrip("/")

        reuse_deadline = time.time() + 15
        while time.time() < reuse_deadline:
            try:
                response = requests.get(f"{base_url}/models", timeout=3)
                if response.ok:
                    payload = response.json()
                    if payload.get("data"):
                        self.logger.info("Tái sử dụng llama-server đang chạy tại %s", base_url)
                        return LlamaServerClient(base_url)
            except Exception:
                pass
            time.sleep(1)

        server_exe = self._find_llama_server_exe()
        if not server_exe:
            raise RuntimeError("Không tìm thấy llama-server.exe. Hãy đặt biến môi trường LLAMA_SERVER_EXE trỏ tới file này.")

        ngl = n_gpu_layers if n_gpu_layers >= 0 else int(os.environ.get("LLAMA_SERVER_NGL", "20"))
        host = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")
        port = os.environ.get("LLAMA_SERVER_PORT", "8080")

        #build_client là phương thức chính để tạo một instance của LlamaServerClient.
        # Nó đầu tiên cố gắng tái sử dụng một instance llama-server đang chạy 
        # nếu có thể kết nối thành công đến endpoint /models. 
        # Nếu không thể tái sử dụng, nó sẽ tìm kiếm file thực thi llama-server.exe, 
        # khởi động một tiến trình mới với các tham số cấu hình, 
        # và chờ cho đến khi server sẵn sàng trước khi trả về một
        #  instance LlamaServerClient kết nối đến server đó.
        command = [
            server_exe,
            "-m", model_path,
            "-c", str(n_ctx),
            "-ngl", str(ngl),
            "--host", host,
            "--port", port,
            "--no-warmup",
            "--jinja",
            "--reasoning-format",
            "deepseek",
        ]
        self.logger.info("Khởi động llama-server: %s", " ".join(command))
        self._server_proc = subprocess.Popen(command)
        self._wait_for_llama_server(f"http://{host}:{port}/v1")
        return LlamaServerClient(f"http://{host}:{port}/v1")

    # stop là phương thức để dừng tiến trình llama-server nếu nó đang chạy.
    # Nó kiểm tra xem tiến trình có tồn tại và đang chạy hay không,
    # sau đó cố gắng gửi tín hiệu terminate và chờ tiến trình kết thúc trong vòng 10 giây. 
    # Nếu tiến trình không kết thúc sau khi gửi terminate, nó sẽ cố gắng gửi tín hiệu kill.
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
