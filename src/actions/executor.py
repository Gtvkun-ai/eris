import ctypes
import json
import re
import shlex
import subprocess
import time
import webbrowser
import os # Thêm import os để sử dụng os.startfile trên Windows
import requests # Thêm import requests để thực hiện các yêu cầu HTTP khi cần thiết

from .contracts import ActionExecutionResult, VALID_SYSTEM_ACTIONS
# ActionExecutor là một lớp để thực thi các hành động hệ thống được định nghĩa 
# trong VALID_SYSTEM_ACTIONS.
# Lớp này cung cấp một phương thức execute để thực thi một hành động cụ thể dựa
#  trên tên hành động và đầu vào được cung cấp. 
# Mỗi hành động có thể có một phương thức riêng để xử lý logic thực thi của nó, 
# như lấy thông tin bài

class ActionExecutor:
    _VK_MEDIA_PLAY_PAUSE = 0xB3
    _VK_VOLUME_MUTE = 0xAD
    _VK_VOLUME_DOWN = 0xAE
    _VK_VOLUME_UP = 0xAF
    _GEMINI_API_KEY = "AIzaSyDzKTsvNUyYGWpT62Ggnd8m7MuzV9ITCkc"
    _GEMINI_SEARCH_MODEL = "gemini-2.5-flash-lite"

    def __init__(self, logger=None):
        self.logger = logger

    def execute(self, action_name: str, action_input: str = "") -> ActionExecutionResult:
        action_name = (action_name or "").strip()
        action_input = (action_input or "").strip()
        if action_name not in VALID_SYSTEM_ACTIONS:
            return ActionExecutionResult(
                action_name=action_name,
                action_input=action_input,
                success=False,
                message="Action khong hop le hoac chua duoc cap quyen.",
            )

        handler = getattr(self, f"_{action_name}", None)
        if handler is None:
            return ActionExecutionResult(
                action_name=action_name,
                action_input=action_input,
                success=False,
                message="Action chua co implementation.",
            )

        try:
            result = handler(action_input)
        except Exception as exc:
            self._log("warning", "Action %s that bai: %s", action_name, exc)
            return ActionExecutionResult(
                action_name=action_name,
                action_input=action_input,
                success=False,
                message=f"Khong thuc thi duoc action {action_name}: {exc}",
            )

        self._log("info", "[action] %s(%s) -> %s", action_name, action_input or "<empty>", result.message)
        return result

    def _get_now_playing(self, action_input: str) -> ActionExecutionResult:
        script = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType=WindowsRuntime]
$null = [System.WindowsRuntimeSystemExtensions, System.Runtime.WindowsRuntime]
function Await($op) {
  $task = [System.WindowsRuntimeSystemExtensions]::AsTask($op)
  $task.Wait()
  return $task.Result
}
$manager = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync())
$session = $manager.GetCurrentSession()
if ($null -eq $session) {
  [pscustomobject]@{ available = $false; reason = 'no_active_session' } | ConvertTo-Json -Compress
  exit
}
$props = Await ($session.TryGetMediaPropertiesAsync())
[pscustomobject]@{
  available = $true
  title = [string]$props.Title
  artist = [string]$props.Artist
  album = [string]$props.AlbumTitle
  source = [string]$session.SourceAppUserModelId
} | ConvertTo-Json -Compress
"""
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (completed.stdout or completed.stderr or "").strip()
        if completed.returncode != 0 or not output:
            return ActionExecutionResult(
                action_name="get_now_playing",
                success=False,
                message="Khong doc duoc media session hien tai.",
            )

        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return ActionExecutionResult(
                action_name="get_now_playing",
                success=False,
                message="Phan hoi media session khong hop le.",
            )

        if not payload.get("available"):
            return ActionExecutionResult(
                action_name="get_now_playing",
                success=False,
                message="Chua thay media session nao dang phat.",
                data={"reason": str(payload.get("reason", ""))},
            )

        title = str(payload.get("title", "")).strip()
        artist = str(payload.get("artist", "")).strip()
        album = str(payload.get("album", "")).strip()
        source = str(payload.get("source", "")).strip()
        if title and artist:
            message = f"Dang phat: {title} - {artist}."
        elif title:
            message = f"Dang phat: {title}."
        else:
            message = "Da thay media session dang phat nhung khong lay duoc tieu de bai."
        return ActionExecutionResult(
            action_name="get_now_playing",
            success=bool(title or artist or source),
            message=message,
            data={
                "title": title,
                "artist": artist,
                "album": album,
                "source": source,
            },
        )

    def _focus_window(self, action_input: str) -> ActionExecutionResult:
        title_hint = (action_input or "").strip().lower()
        if not title_hint:
            return ActionExecutionResult(
                action_name="focus_window",
                action_input=action_input,
                success=False,
                message="Thieu tieu de hoac tu khoa cua cua so can focus.",
            )

        user32 = ctypes.windll.user32
        hwnds: list[tuple[int, str]] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def _callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value.strip()
            if title:
                hwnds.append((hwnd, title))
            return True

        user32.EnumWindows(callback_type(_callback), 0)
        for hwnd, title in hwnds:
            if title_hint not in title.lower():
                continue
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            return ActionExecutionResult(
                action_name="focus_window",
                action_input=action_input,
                success=True,
                message=f"Da dua cua so '{title}' len foreground.",
                data={"matched_title": title},
            )

        return ActionExecutionResult(
            action_name="focus_window",
            action_input=action_input,
            success=False,
            message=f"Khong tim thay cua so phu hop voi '{action_input}'.",
        )

    def _open_url(self, action_input: str) -> ActionExecutionResult:
        url = self._normalize_url(action_input)
        if not url:
            return ActionExecutionResult(
                action_name="open_url",
                action_input=action_input,
                success=False,
                message="URL khong hop le.",
            )

        opened = webbrowser.open(url)
        return ActionExecutionResult(
            action_name="open_url",
            action_input=url,
            success=bool(opened),
            message=f"Da yeu cau he thong mo {url}.",
            data={"url": url},
        )

    def _set_volume(self, action_input: str) -> ActionExecutionResult:
        lowered = (action_input or "").strip().lower()
        if lowered in {"mute", "silent", "tat am", "tat tieng"}:
            self._press_virtual_key(self._VK_VOLUME_MUTE)
            return ActionExecutionResult(
                action_name="set_volume",
                action_input=action_input,
                success=True,
                message="Da gui lenh mute/unmute am luong he thong.",
            )

        match = re.search(r"-?\d+", lowered)
        if not match:
            return ActionExecutionResult(
                action_name="set_volume",
                action_input=action_input,
                success=False,
                message="Can truyen muc am luong tu 0 den 100.",
            )

        level = max(0, min(100, int(match.group(0))))
        for _ in range(50):
            self._press_virtual_key(self._VK_VOLUME_DOWN, pause=0.005)
        for _ in range(round(level / 2)):
            self._press_virtual_key(self._VK_VOLUME_UP, pause=0.005)

        return ActionExecutionResult(
            action_name="set_volume",
            action_input=str(level),
            success=True,
            message=f"Da dua am luong he thong ve khoang {level} phan tram.",
            data={"level": str(level)},
        )
    
    def _search_web(self, action_input: str) -> ActionExecutionResult:
        query = (action_input or "").strip()
        if not query:
            return ActionExecutionResult(
                action_name="search_web",
                action_input=action_input,
                success=False,
                message="Thieu tu khoa de search.",
            )

        api_key = os.environ.get("GEMINI_API_KEY", "").strip() or self._GEMINI_API_KEY
        if not api_key:
            return ActionExecutionResult(
                action_name="search_web",
                action_input=action_input,
                success=False,
                message="Chua cau hinh GEMINI_API_KEY cho search_web.",
            )

        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self._GEMINI_SEARCH_MODEL}:generateContent",
                params={"key": api_key},
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [
                        {
                            "parts": [
                                {
                                    "text": (
                                        "Tra loi ngan gon bang tieng Viet. "
                                        "Neu can thi tom tat thong tin web moi nhat va dua ra nguon.\n"
                                        f"Cau hoi: {query}"
                                    )
                                }
                            ]
                        }
                    ],
                    "tools": [{"google_search": {}}],
                },
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            return ActionExecutionResult(
                action_name="search_web",
                action_input=action_input,
                success=False,
                message=f"Khong goi duoc Gemini grounding API: {exc}",
            )

        candidates = payload.get("candidates") or []
        if not candidates:
            return ActionExecutionResult(
                action_name="search_web",
                action_input=action_input,
                success=False,
                message=f"Gemini khong tra ve ket qua cho '{query}'.",
            )

        candidate = candidates[0] or {}
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        answer_text = ""
        for part in parts:
            text = (part.get("text") or "").strip()
            if text:
                answer_text = text
                break

        grounding = candidate.get("groundingMetadata") or {}
        chunks = grounding.get("groundingChunks") or []
        citation_lines = []
        citation_urls = []
        for chunk in chunks[:3]:
            web = chunk.get("web") or {}
            title = (web.get("title") or "").strip()
            uri = (web.get("uri") or "").strip()
            if not title and not uri:
                continue
            if uri:
                citation_urls.append(uri)
            if title and uri:
                citation_lines.append(f"- {title}: {uri}")
            elif uri:
                citation_lines.append(f"- {uri}")
            else:
                citation_lines.append(f"- {title}")

        if not answer_text:
            return ActionExecutionResult(
                action_name="search_web",
                action_input=action_input,
                success=False,
                message=f"Gemini grounding khong tra ve noi dung cho '{query}'.",
            )

        message = answer_text
        if citation_lines:
            message = f"{answer_text}\nNguon:\n" + "\n".join(citation_lines)

        return ActionExecutionResult(
            action_name="search_web",
            action_input=action_input,
            success=True,
            message=message,
            data={
                "answer": answer_text,
                "sources": "\n".join(citation_lines),
                "source_urls": "\n".join(citation_urls),
                "model": self._GEMINI_SEARCH_MODEL,
            },
        )

    def _get_weather(self, action_input: str) -> ActionExecutionResult:
        query = (action_input or "").strip()
        if not query:
            return ActionExecutionResult(
                action_name="get_weather",
                action_input=action_input,
                success=False,
                message="Thieu thong tin de xem thoi tiet.",
            )

        api_key = os.environ.get("GEMINI_API_KEY", "").strip() or self._GEMINI_API_KEY
        if not api_key:
            return ActionExecutionResult(
                action_name="get_weather",
                action_input=action_input,
                success=False,
                message="Chua cau hinh GEMINI_API_KEY cho get_weather.",
            )

        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self._GEMINI_SEARCH_MODEL}:generateContent",
                params={"key": api_key},
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [
                        {
                            "parts": [
                                {
                                    "text": (
                                        "Tra loi ngan gon bang tieng Viet ve thoi tiet dua tren thong tin web. "
                                        "Neu nguoi dung hoi ngay mai, hom nay, quan huyen hay khu vuc cu the, "
                                        "hay giu nguyen muc do cu the do. "
                                        "Neu du lieu khong chac, noi ro muc do khong chac va khong duoc boi. "
                                        "Them 1 cau nhac nho nho neu can.\n"
                                        f"Cau hoi thoi tiet: {query}"
                                    )
                                }
                            ]
                        }
                    ],
                    "tools": [{"google_search": {}}],
                },
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            return ActionExecutionResult(
                action_name="get_weather",
                action_input=action_input,
                success=False,
                message=f"Khong goi duoc Gemini weather grounding API: {exc}",
            )

        candidates = payload.get("candidates") or []
        if not candidates:
            return ActionExecutionResult(
                action_name="get_weather",
                action_input=action_input,
                success=False,
                message=f"Gemini khong tra ve ket qua thoi tiet cho '{query}'.",
            )

        candidate = candidates[0] or {}
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        answer_text = ""
        for part in parts:
            text = (part.get("text") or "").strip()
            if text:
                answer_text = text
                break

        grounding = candidate.get("groundingMetadata") or {}
        chunks = grounding.get("groundingChunks") or []
        citation_lines = []
        citation_urls = []
        for chunk in chunks[:3]:
            web = chunk.get("web") or {}
            title = (web.get("title") or "").strip()
            uri = (web.get("uri") or "").strip()
            if not title and not uri:
                continue
            if uri:
                citation_urls.append(uri)
            if title and uri:
                citation_lines.append(f"- {title}: {uri}")
            elif uri:
                citation_lines.append(f"- {uri}")
            else:
                citation_lines.append(f"- {title}")

        if not answer_text:
            return ActionExecutionResult(
                action_name="get_weather",
                action_input=action_input,
                success=False,
                message=f"Gemini weather grounding khong tra ve noi dung cho '{query}'.",
            )

        message = answer_text
        if citation_lines:
            message = f"{answer_text}\nNguon:\n" + "\n".join(citation_lines)

        return ActionExecutionResult(
            action_name="get_weather",
            action_input=action_input,
            success=True,
            message=message,
            data={
                "answer": answer_text,
                "sources": "\n".join(citation_lines),
                "source_urls": "\n".join(citation_urls),
                "model": self._GEMINI_SEARCH_MODEL,
            },
        )

    def _play_pause_media(self, action_input: str) -> ActionExecutionResult:
        self._press_virtual_key(self._VK_MEDIA_PLAY_PAUSE)
        return ActionExecutionResult(
            action_name="play_pause_media",
            action_input=action_input,
            success=True,
            message="Da gui phim play/pause media.",
        )

    def _copy_text(self, action_input: str) -> ActionExecutionResult:
        text = action_input or ""
        if not text:
            return ActionExecutionResult(
                action_name="copy_text",
                action_input=action_input,
                success=False,
                message="Khong co noi dung de copy.",
            )

        self._set_clipboard_text(text)
        return ActionExecutionResult(
            action_name="copy_text",
            action_input=action_input,
            success=True,
            message="Da dua noi dung vao clipboard.",
            data={"text_length": str(len(text))},
        )

    def _launch_app(self, action_input: str) -> ActionExecutionResult:
        command = (action_input or "").strip()
        if not command:
            return ActionExecutionResult(
                action_name="launch_app",
                action_input=action_input,
                success=False,
                message="Thieu ten app hoac command can chay.",
            )

        alias_map = {
            "notepad": "notepad.exe",
            "calculator": "calc.exe",
            "calc": "calc.exe",
            "paint": "mspaint.exe",
            "code": "Code.exe",
            "vscode": "Code.exe",
            "spotify": "Spotify.exe",
            "chrome": "chrome.exe",
            "edge": "msedge.exe",
        }
        normalized = alias_map.get(command.lower(), command)
        args = shlex.split(normalized, posix=False)
        subprocess.Popen(args, close_fds=True)
        return ActionExecutionResult(
            action_name="launch_app",
            action_input=normalized,
            success=True,
            message=f"Da yeu cau he thong khoi chay '{normalized}'.",
            data={"command": normalized},
        )

    def _normalize_url(self, raw: str) -> str:
        candidate = (raw or "").strip()
        if not candidate:
            return ""
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate):
            return candidate
        if re.match(r"^[\w.-]+\.[a-zA-Z]{2,}(/\S*)?$", candidate):
            return f"https://{candidate}"
        return ""

    def _press_virtual_key(self, virtual_key: int, pause: float = 0.03) -> None:
        ctypes.windll.user32.keybd_event(virtual_key, 0, 0, 0)
        time.sleep(pause)
        ctypes.windll.user32.keybd_event(virtual_key, 0, 0x0002, 0)
        time.sleep(pause)

    def _set_clipboard_text(self, text: str) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        cf_unicode_text = 13
        ghnd = 0x0042
        data = text.encode("utf-16-le") + b"\x00\x00"

        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_bool
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = ctypes.c_bool
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = ctypes.c_bool
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.restype = ctypes.c_bool
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.restype = ctypes.c_void_p

        if not user32.OpenClipboard(None):
            raise RuntimeError("Khong mo duoc clipboard.")

        handle = None
        locked = None
        try:
            user32.EmptyClipboard()
            handle = kernel32.GlobalAlloc(ghnd, len(data))
            if not handle:
                raise RuntimeError("Khong cap phat duoc bo nho cho clipboard.")
            locked = kernel32.GlobalLock(handle)
            if not locked:
                raise RuntimeError("Khong lock duoc bo nho clipboard.")
            ctypes.memmove(locked, data, len(data))
            kernel32.GlobalUnlock(handle)
            locked = None
            if not user32.SetClipboardData(cf_unicode_text, handle):
                raise RuntimeError("Khong dua duoc du lieu vao clipboard.")
            handle = None
        finally:
            if locked:
                kernel32.GlobalUnlock(handle)
            if handle:
                kernel32.GlobalFree(handle)
            user32.CloseClipboard()

    def _log(self, level: str, message: str, *args) -> None:
        if self.logger is None:
            return
        getattr(self.logger, level)(message, *args)
