# -*- coding: utf-8 -*-
"""Game knowledge and co-streaming playbook registry for Eris.

Provides structured game metadata, mechanics understanding, and co-host focus
for known stream games as well as zero-shot dynamic game detection and background
deep research via Gemini Flash (port 8000).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import unicodedata
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

logger = logging.getLogger("eris.game_knowledge")


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", str(text or "").lower())
    plain = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9+#]+", " ", plain).split())


@dataclass(frozen=True, slots=True)
class GameProfile:
    game_id: str
    title: str
    genre: str
    mechanics: str
    co_stream_focus: str
    keywords: tuple[str, ...] = ()
    source: str = "builtin"

    def to_dict(self) -> dict[str, object]:
        return {
            "game_id": self.game_id,
            "title": self.title,
            "genre": self.genre,
            "mechanics": self.mechanics,
            "co_stream_focus": self.co_stream_focus,
            "keywords": list(self.keywords),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> GameProfile:
        return cls(
            game_id=str(data.get("game_id", "custom_game")),
            title=str(data.get("title", "")),
            genre=str(data.get("genre", "Game")),
            mechanics=str(data.get("mechanics", "")),
            co_stream_focus=str(data.get("co_stream_focus", "")),
            keywords=tuple(str(k) for k in data.get("keywords", ())),
            source=str(data.get("source", "cached_research")),
        )


KNOWN_GAMES: tuple[GameProfile, ...] = (
    GameProfile(
        game_id="little_chef",
        title="Little Chef: Cozy Cooking",
        genre="2D Cozy Physics Sandbox / Drag-and-drop Cooking (itch.io indie)",
        mechanics=(
            "Game nấu ăn 2D vật lý kéo-thả chuột (drag & drop) cực kỳ tự do trong căn bếp ấm cúng: "
            "Người chơi dùng chuột kéo thả các nguyên liệu trên kệ và tủ (bánh mì, sữa 'MÜLK', mì ống pasta, vỉ trứng, túi khoai trong lưới, hũ sốt/mứt trong tủ Shane) "
            "vào nồi đen trên bếp điện, máy nướng bánh mì (toaster), hoặc bồn rửa bát để kết hợp tạo món. "
            "Có thể mở các ngăn tủ bếp (tủ Shane có khóa), bật bếp điện, dùng dao trên thanh nam châm để cắt thái, "
            "hoặc bấm vào icon chiếc Mũ Đầu Bếp (Chef's Hat) màu vàng ở góc trên bên trái để mở sổ công thức (Recipe Book). "
            "Không có áp lực thời gian; tự do thử nghiệm công thức hoặc nghịch ngợm các tương tác vật lý (bấm phím 'R' để reset bàn)."
        ),
        co_stream_focus=(
            "Hướng dẫn và bình luận chuẩn xác theo cơ chế kéo-thả chuột: quan sát các nguyên liệu đang có trên kệ và tủ "
            "(bánh mì, trứng, sữa MÜLK, mì ống, khoai, hũ sốt), gợi ý người chơi kéo nguyên liệu thả vào nồi hoặc máy nướng bánh, "
            "nhắc nhở bấm vào biểu tượng Mũ Đầu Bếp góc trên bên trái nếu muốn xem công thức nấu món cụ thể."
        ),
        keywords=("little chef", "littlechef", "chef: demo", "cozy cooking", "cozy_cooking"),
        source="builtin",
    ),
    GameProfile(
        game_id="overcooked",
        title="Overcooked / PlateUp!",
        genre="Co-op Kitchen Chaos & Restaurant Simulation",
        mechanics=(
            "Phối hợp nhịp độ cao: lấy nguyên liệu -> thái/chặt -> nấu trên bếp -> bày đĩa phục vụ khách "
            "-> thu và rửa đĩa bẩn -> dùng bình cứu hỏa dập lửa khi bếp cháy. Tránh va chạm làm rơi đồ."
        ),
        co_stream_focus=(
            "Nhắc nhở thứ tự đơn hàng, la hét vui vẻ khi bếp bắt đầu cháy hoặc tắc đường chuyền, "
            "hỗ trợ người chơi giữ bình tĩnh trước giờ cao điểm."
        ),
        keywords=("overcooked", "plateup", "plate up"),
        source="builtin",
    ),
    GameProfile(
        game_id="slay_the_spire",
        title="Slay the Spire",
        genre="Roguelike Deckbuilder",
        mechanics=(
            "Quản lý 3 năng lượng mỗi lượt, dùng bài tấn công/thủ/phép, quan sát icon ý định của quái vật "
            "(sát thương sắp gây ra, buff sức mạnh hay dính debuff), tính toán giáp chặn đòn để bảo toàn máu gốc."
        ),
        co_stream_focus=(
            "Bình luận chiến thuật bài, gợi ý tính toán điểm sát thương và giáp, đánh giá độ hợp lý khi chọn relic "
            "hoặc thẻ bài mới sau mỗi trận đánh."
        ),
        keywords=("slay the spire", "slaythespire", "spire"),
        source="builtin",
    ),
    GameProfile(
        game_id="balatro",
        title="Balatro",
        genre="Roguelike Poker Deckbuilder",
        mechanics=(
            "Đánh các tay bài poker (Flush, Full House, Straight...), kích hoạt hiệu ứng Joker để nhân hệ số "
            "Chips x Mult vượt mốc điểm Blind yêu cầu. Quản lý tiền mua thẻ Tarot, Planet và Joker trong Shop."
        ),
        co_stream_focus=(
            "Hồi hộp theo dõi thanh điểm nhân, bình luận độ 'ảo diệu' của các combo Joker, gợi ý thứ tự xếp Joker "
            "để tối đa hóa Mult."
        ),
        keywords=("balatro",),
        source="builtin",
    ),
    GameProfile(
        game_id="hollow_knight",
        title="Hollow Knight",
        genre="Metroidvania Action / Soulslike",
        mechanics=(
            "Dùng kiếm Nail đánh quái tích tụ Soul, dùng Soul để hồi máu (Focus) hoặc tung phép (Vengeful Spirit), "
            "nhảy/dash né đòn chuẩn xác, khám phá mê cung Hallownest và hạ các boss hiểm hóc."
        ),
        co_stream_focus=(
            "Hồi hộp theo dõi từng pha né đòn trong các trận đấu boss nghẹt thở, nhắc người chơi tìm góc an toàn hồi máu, "
            "cảm thán trước nghệ thuật và âm nhạc u uất tuyệt đẹp của Hallownest."
        ),
        keywords=("hollow knight", "hollowknight", "silksong"),
        source="builtin",
    ),
    GameProfile(
        game_id="stardew_valley",
        title="Stardew Valley",
        genre="Farming & Rural Life Simulation",
        mechanics=(
            "Trồng trọt, tưới cây, nuôi gia súc, câu cá, thám hiểm hầm mỏ, quản lý thanh năng lượng (Energy) "
            "và thời gian trong ngày (về giường ngủ trước 2h sáng kẻo kiệt sức)."
        ),
        co_stream_focus=(
            "Cùng tận hưởng không khí đồng quê êm đềm, nhắc nhở giờ về ngủ, gợi ý các loại cây trồng theo mùa "
            "và lịch sự kiện lễ hội trong thị trấn Pelican."
        ),
        keywords=("stardew", "stardew valley", "stardewvalley"),
        source="builtin",
    ),
    GameProfile(
        game_id="generic_cooking",
        title="Trò chơi Nấu ăn (Cooking Game)",
        genre="Cooking Simulation",
        mechanics=(
            "Chuẩn bị nguyên liệu theo công thức, thực hiện các thao tác bếp (cắt thái, xào rán, nướng, pha chế), "
            "hoàn thành món ăn và phục vụ thực khách đúng giờ."
        ),
        co_stream_focus=(
            "Canh chừng bếp chảo, nhắc nhở nguyên liệu kế tiếp, giữ nhịp độ vui tươi ấm cúng cho buổi phát sóng."
        ),
        keywords=("cooking", "chef", "kitchen", "restaurant", "baking", "cafe", "nau an", "bep"),
        source="builtin",
    ),
)


_BROWSER_SUFFIX_PATTERNS = (
    r"\s*-\s*brave\s*$",
    r"\s*-\s*google chrome\s*$",
    r"\s*-\s*microsoft edge\s*$",
    r"\s*-\s*mozilla firefox\s*$",
    r"\s*-\s*chromium\s*$",
    r"\s*-\s*play on crazygames\s*$",
    r"\s*-\s*crazygames\s*$",
    r"\s*-\s*poki\s*$",
    r"\s*-\s*game jolt\s*$",
    r"\s*-\s*itch\.io\s*$",
    r"\s*-\s*steam\s*$",
)

_AUTHOR_DEMO_PATTERNS = (
    r":\s*demo\s+by\s+[^,\-]+.*$",
    r"\s+by\s+.*$",
    r"\s*\(demo\)\s*$",
    r"\s*demo\s*$",
)


def clean_browser_title(raw_title: str) -> str:
    """Tách tiêu đề sạch giữ nguyên tác giả/demo bằng cách chỉ loại bỏ hậu tố trình duyệt/nền tảng."""
    title = str(raw_title or "").strip()
    if not title:
        return ""
    for pat in _BROWSER_SUFFIX_PATTERNS:
        title = re.sub(pat, "", title, flags=re.IGNORECASE).strip()
    return title.strip(" -:|")


def clean_game_title(raw_title: str) -> str:
    """Tách tên game gọn gàng từ tiêu đề cửa sổ trình duyệt hoặc window title."""
    title = str(raw_title or "").strip()
    if not title:
        return ""
    for pat in _BROWSER_SUFFIX_PATTERNS:
        title = re.sub(pat, "", title, flags=re.IGNORECASE).strip()
    # Nếu có author / demo suffix: "Little Chef: Demo by Julien, hello erika, Danny-vD" -> "Little Chef"
    for pat in _AUTHOR_DEMO_PATTERNS:
        cleaned = re.sub(pat, "", title, flags=re.IGNORECASE).strip()
        if cleaned:
            title = cleaned
            break
    return title.strip(" -:|")


_GAMING_INDICATORS = (
    "steam", "game", "gaming", "unity", "unreal", "cooking", "chef",
    "overcooked", "plateup", "spire", "hearthstone", "valorant", "genshin",
    "league", "dota", "minecraft", "roblox", "itch.io", "balatro", "hollow knight",
    "stardew", "poki", "crazygames", "webgl", "arcade", "emulator", "retroarch",
    "hades", "celeste", "dead cells", "lethal company", "dave the diver",
    "palworld", "monster hunter", "elden ring", "dark souls", "pizza tower",
    "clawler", "roguelike", "puzzle", "sandbox", "metroidvania",
)


_NON_GAME_PROCESSES = {
    "code.exe", "devenv.exe", "pycharm64.exe", "idea64.exe", "cursor.exe",
    "windsurf.exe", "sublime_text.exe", "notepad++.exe", "notepad.exe",
    "discord.exe", "telegram.exe", "slack.exe", "zalo.exe", "spotify.exe",
    "explorer.exe", "taskmgr.exe", "cmd.exe", "powershell.exe", "windowsterminal.exe",
    "postman.exe", "dbeaver.exe",
}

_NON_GAME_TITLE_PATTERNS = (
    r"visual studio code",
    r"\.py\b",
    r"\.ts\b",
    r"\.js\b",
    r"\.json\b",
    r"\.md\b",
    r"-\s*youtube",
    r"\byoutube\b",
    r"google search",
    r"tìm trên google",
    r"tim tren google",
    r"\bgithub\b",
    r"stack overflow",
    r"\bchatgpt\b",
    r"\bclaude\b",
    r"\bdeepseek\b",
    r"\bfacebook\b",
    r"\breddit\b",
    r"\btwitter\b",
    r"\bwikipedia\b",
    r"\bgmail\b",
    r"google docs",
    r"google sheets",
    r"steam community",
    r"steam store",
    r"welcome to steam",
)


def is_gaming_window(title: str, process: str = "") -> bool:
    """Kiểm tra xem cửa sổ hiện tại có phải là game (web game, Steam, standalone).
    
    Áp dụng guard loại trừ các tiến trình code/chat/hệ thống và các tab video/search.
    """
    raw_proc = str(process or "").strip().lower()
    if raw_proc in _NON_GAME_PROCESSES:
        return False

    raw_title = str(title or "").strip().lower()
    norm_title = _norm(title)
    norm_proc = _norm(process)

    # Kiểm tra exclusion title patterns trên cả raw_title và norm_title
    for pat in _NON_GAME_TITLE_PATTERNS:
        if re.search(pat, raw_title) or re.search(pat, norm_title):
            return False

    combined = f"{norm_title} {norm_proc}"

    # Kiểm tra catalog KNOWN_GAMES trước
    for profile in KNOWN_GAMES:
        if profile.game_id == "generic_cooking":
            continue
        if any(_norm(kw) in combined for kw in profile.keywords):
            return True

    # Kiểm tra persistent store
    if _GLOBAL_STORE.get(norm_title) is not None:
        return True
    cleaned = clean_game_title(title)
    if cleaned and _GLOBAL_STORE.get(_norm(cleaned)) is not None:
        return True

    # Kiểm tra gaming indicators với word boundary cho các từ ngắn
    for ind in _GAMING_INDICATORS:
        if len(ind) <= 6 and ind.isalpha():
            if re.search(r"\b" + re.escape(ind) + r"\b", combined):
                return True
        else:
            if ind in combined:
                return True

    return False


# ==============================================================================
# Persistent Cache Store for Game Knowledge
# ==============================================================================

class GameKnowledgeStore:
    """Quản lý bộ nhớ đệm và file lưu trữ kiến thức game đã nghiên cứu."""

    def __init__(self, cache_file: str | Path | None = None) -> None:
        if cache_file is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
            self.cache_file = base_dir / "data" / "game_knowledge_cache.json"
        else:
            self.cache_file = Path(cache_file)
        self._lock = threading.RLock()
        self._cache: dict[str, GameProfile] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self.cache_file.exists():
                return
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for k, item in data.items():
                        if isinstance(item, dict):
                            self._cache[_norm(k)] = GameProfile.from_dict(item)
            except Exception as exc:
                logger.warning("[game knowledge] Không tải được cache: %s", exc)

    def _save(self) -> None:
        with self._lock:
            try:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                payload = {k: profile.to_dict() for k, profile in self._cache.items()}
                with open(self.cache_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            except Exception as exc:
                logger.warning("[game knowledge] Không lưu được cache: %s", exc)

    def get(self, key: str) -> GameProfile | None:
        with self._lock:
            return self._cache.get(_norm(key))

    def set(self, key: str, profile: GameProfile) -> None:
        with self._lock:
            self._cache[_norm(key)] = profile
            self._save()

    def all(self) -> dict[str, GameProfile]:
        with self._lock:
            return dict(self._cache)


_GLOBAL_STORE = GameKnowledgeStore()
_RESEARCHING_TITLES: set[str] = set()
_RESEARCH_LOCK = threading.Lock()


# ==============================================================================
# Background Deep Research Worker via Gemini Flash (:8000)
# ==============================================================================

def fetch_game_profile_from_research(
    game_title: str,
    *,
    raw_window_title: str = "",
    process_name: str = "",
    base_url: str = "http://127.0.0.1:8000/v1",
    model: str = "gemini-flash",
    timeout: float = 25.0,
) -> GameProfile | None:
    """Nghiên cứu tựa game qua Gemini Flash (:8000) với bắt buộc Google / Web Search grounding."""
    title = str(game_title or "").strip()
    raw_title = str(raw_window_title or "").strip()
    proc = str(process_name or "").strip()
    if not title and not raw_title:
        return None

    # Tìm kiếm theo tiêu đề trình duyệt sạch (giữ tác giả / demo) để có bối cảnh itch.io/steam chính xác
    search_title = clean_browser_title(raw_title) if raw_title else title
    clean_short_title = clean_game_title(title or raw_title)

    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    system_prompt = (
        "Bạn là chuyên gia nghiên cứu game của trợ lý AI Eris.\n"
        "BẮT BUỘC: Bạn HÃY TÌM KIẾM TRÊN GOOGLE / WEB để tra cứu chính xác tựa game/demo theo toàn bộ tiêu đề, tác giả và bối cảnh được cung cấp.\n"
        "Tuyệt đối không phỏng đoán mơ hồ hay suy diễn sai lệch từ tên gọi chung chung.\n"
        "Nếu là game indie / itch.io demo / game jam, hãy tìm kiếm thông tin từ itch.io, tác giả, và các bài review/gameplay thực tế để nắm rõ:\n"
        "- Tên chuẩn kèm tác giả (nếu là indie demo)\n"
        "- Thể loại cụ thể\n"
        "- Luật chơi, cơ chế vật lý/tương tác, phím bấm điều khiển, mục tiêu hoặc công thức/meme đặc trưng (2-3 câu súc tích bằng tiếng Việt)\n"
        "- Lời khuyên định hướng cho streamer / co-host bình luận trực tiếp\n\n"
        "Trả về DUY NHẤT một JSON object hợp lệ (không kèm markdown fence hay văn bản thừa ngoài JSON) có đúng cấu trúc:\n"
        "{\n"
        '  "title": "<tên chuẩn của game, kèm tên tác giả/demo nếu là indie itch.io>",\n'
        '  "genre": "<thể loại cụ thể, ví dụ: 2D Physics Puzzle / Sandbox Cooking>",\n'
        '  "mechanics": "<luật chơi cốt lõi, cơ chế vật lý/điều khiển phím/chuột, mục tiêu hoặc công thức/meme đặc trưng (2-3 câu súc tích bằng tiếng Việt)>",\n'
        '  "co_stream_focus": "<hướng dẫn co-host: quan sát điều gì trên màn hình, bình luận các pha xử lý/tai nạn hài hước thế nào>"\n'
        "}"
    )

    extra_lines = []
    if raw_title:
        extra_lines.append(f"Tiêu đề cửa sổ gốc: '{raw_title}'")
    if search_title != raw_title:
        extra_lines.append(f"Tiêu đề tìm kiếm: '{search_title}'")
    if proc:
        extra_lines.append(f"Tiến trình: '{proc}'")
    extra_lines.append(f"Tên game rút gọn: '{clean_short_title}'")
    meta_text = "\n".join(extra_lines)

    user_prompt = (
        f"Hãy tìm kiếm Google trên web và nghiên cứu tựa game/demo sau:\n"
        f"{meta_text}\n\n"
        "Bắt buộc tìm kiếm web để lấy thông tin thực tế về cách chơi, cơ chế và nhà phát triển."
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }

    try:
        req = urllib.request.Request(
            endpoint,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload).encode("utf-8"),
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw_data = json.loads(response.read().decode("utf-8"))

        choices = raw_data.get("choices") or []
        if not choices:
            return None
        content = str(choices[0].get("message", {}).get("content", "") or "").strip()
        if not content:
            return None

        # Clean JSON fences if present
        clean_content = content
        if "```" in clean_content:
            clean_content = re.sub(r"^```(?:json)?\s*", "", clean_content, flags=re.MULTILINE)
            clean_content = re.sub(r"\s*```$", "", clean_content, flags=re.MULTILINE).strip()

        start = clean_content.find("{")
        end = clean_content.rfind("}")
        if 0 <= start < end:
            clean_content = clean_content[start : end + 1]

        data = json.loads(clean_content)
        profile_title = str(data.get("title") or clean_short_title or title).strip()
        profile_genre = str(data.get("genre") or "Indie Game").strip()
        profile_mechanics = str(data.get("mechanics") or "").strip()
        profile_co_stream = str(data.get("co_stream_focus") or "").strip()

        if not profile_mechanics:
            return None

        clean_display_title = clean_game_title(profile_title) or clean_short_title or profile_title
        game_id = f"researched_{_norm(clean_display_title).replace(' ', '_')[:32]}"
        keywords = tuple(
            dict.fromkeys(
                filter(
                    None,
                    [
                        clean_display_title.lower(),
                        clean_short_title.lower(),
                        search_title.lower(),
                        profile_title.lower(),
                        _norm(clean_display_title),
                    ],
                )
            )
        )
        return GameProfile(
            game_id=game_id,
            title=clean_display_title,
            genre=profile_genre,
            mechanics=profile_mechanics,
            co_stream_focus=profile_co_stream,
            keywords=keywords,
            source="gemini_web_search",
        )
    except Exception as exc:
        logger.warning("[game research] Lỗi khi nghiên cứu game '%s' qua :8000: %s", search_title, exc)
        return None


def trigger_background_game_research(
    game_title: str,
    *,
    raw_window_title: str = "",
    process_name: str = "",
    on_complete: Callable[[GameProfile], None] | None = None,
) -> None:
    """Khởi động luồng ngầm nghiên cứu game qua Gemini Flash mà không làm nghẽn hội thoại."""
    title = clean_game_title(game_title or raw_window_title)
    raw_title = str(raw_window_title or "").strip()
    proc = str(process_name or "").strip()
    if not title and not raw_title:
        return

    norm_title = _norm(title)
    norm_raw = _norm(raw_title) if raw_title else ""
    norm_browser = _norm(clean_browser_title(raw_title)) if raw_title else ""

    # Nếu đã có trong store thì không cần nghiên cứu lại
    if _GLOBAL_STORE.get(norm_title) is not None:
        return
    if norm_browser and _GLOBAL_STORE.get(norm_browser) is not None:
        return
    if norm_raw and _GLOBAL_STORE.get(norm_raw) is not None:
        return

    # Tránh gửi trùng lặp nếu đang có request chạy nền cho cùng tựa game
    dedup_key = norm_browser or norm_title
    with _RESEARCH_LOCK:
        if dedup_key in _RESEARCHING_TITLES:
            return
        _RESEARCHING_TITLES.add(dedup_key)

    def _worker() -> None:
        try:
            logger.info(
                "[game research] Bắt đầu nghiên cứu ngầm tựa game '%s' (raw='%s') qua Gemini Web Search...",
                title, raw_title,
            )
            profile = fetch_game_profile_from_research(
                title,
                raw_window_title=raw_title,
                process_name=proc,
            )
            if profile is not None:
                _GLOBAL_STORE.set(norm_title, profile)
                _GLOBAL_STORE.set(_norm(profile.title), profile)
                if norm_browser:
                    _GLOBAL_STORE.set(norm_browser, profile)
                if norm_raw:
                    _GLOBAL_STORE.set(norm_raw, profile)
                logger.info(
                    "[game research] Nghiên cứu thành công tựa game '%s' (%s) và đã lưu vào cache (source=%s).",
                    profile.title, profile.genre, profile.source,
                )
                if callable(on_complete):
                    try:
                        on_complete(profile)
                    except Exception:
                        pass
            else:
                logger.info("[game research] Không thu thập được profile cho '%s'", title)
        except Exception as exc:
            logger.warning("[game research] Worker lỗi khi nghiên cứu '%s': %s", title, exc)
        finally:
            with _RESEARCH_LOCK:
                _RESEARCHING_TITLES.discard(dedup_key)

    thread = threading.Thread(
        target=_worker,
        name=f"ERIS-GameResearcher-{dedup_key[:16]}",
        daemon=True,
    )
    thread.start()


# ==============================================================================
# Public API
# ==============================================================================

def detect_game_from_window(
    title: str,
    process: str = "",
    *,
    sync_research: bool = False,
) -> GameProfile | None:
    """Nhận diện game từ window title / process và trả GameProfile tương ứng."""
    if not is_gaming_window(title, process):
        return None

    norm_title = _norm(title)
    norm_proc = _norm(process)
    combined = f"{norm_title} {norm_proc}"

    # 1. Tìm trong persistent cache đã nghiên cứu qua Gemini Web Search
    cached = _GLOBAL_STORE.get(norm_title)
    if cached is not None:
        return cached

    cleaned_browser = clean_browser_title(title)
    if cleaned_browser:
        cached_browser = _GLOBAL_STORE.get(_norm(cleaned_browser))
        if cached_browser is not None:
            return cached_browser

    cleaned_title = clean_game_title(title)
    if cleaned_title:
        cached_cleaned = _GLOBAL_STORE.get(_norm(cleaned_title))
        if cached_cleaned is not None:
            return cached_cleaned

    # Nghiên cứu đồng bộ nếu được yêu cầu rõ ràng
    if sync_research and (cleaned_title or cleaned_browser):
        profile = fetch_game_profile_from_research(
            cleaned_title or cleaned_browser,
            raw_window_title=title,
            process_name=process,
        )
        if profile is not None:
            _GLOBAL_STORE.set(norm_title, profile)
            if cleaned_browser:
                _GLOBAL_STORE.set(_norm(cleaned_browser), profile)
            if cleaned_title:
                _GLOBAL_STORE.set(_norm(cleaned_title), profile)
            return profile

    # 2. Tìm trong catalog game tích hợp sẵn
    matched_builtin: GameProfile | None = None
    for profile in KNOWN_GAMES:
        if profile.game_id == "generic_cooking":
            continue
        if any(_norm(kw) in combined for kw in profile.keywords):
            matched_builtin = profile
            break

    if matched_builtin is not None:
        # Nếu chưa có bản nghiên cứu web search trong store, kích hoạt ngầm để nâng cấp
        trigger_background_game_research(
            cleaned_title or matched_builtin.title,
            raw_window_title=title,
            process_name=process,
        )
        return matched_builtin

    # 3. Kiểm tra generic cooking nếu có từ khóa nấu ăn
    cooking_profile = next((p for p in KNOWN_GAMES if p.game_id == "generic_cooking"), None)
    if cooking_profile and any(_norm(kw) in combined for kw in cooking_profile.keywords):
        display_title = cleaned_title if cleaned_title else cooking_profile.title
        # Trigger background web research để nâng cấp profile chi tiết hơn
        if cleaned_title or title:
            trigger_background_game_research(
                cleaned_title or title,
                raw_window_title=title,
                process_name=process,
            )
        return GameProfile(
            game_id="detected_cooking",
            title=display_title,
            genre=cooking_profile.genre,
            mechanics=cooking_profile.mechanics,
            co_stream_focus=cooking_profile.co_stream_focus,
            keywords=cooking_profile.keywords,
            source="detected_cooking",
        )

    # 4. Tựa game mới/indie bất kỳ: kích hoạt nghiên cứu web search ngầm và trả dynamic profile tạm thời
    if cleaned_title or title:
        trigger_background_game_research(
            cleaned_title or title,
            raw_window_title=title,
            process_name=process,
        )
        return GameProfile(
            game_id="custom_game",
            title=cleaned_title or title,
            genre="Trò chơi điện tử (PC / Web / Indie Game)",
            mechanics=(
                f"Tựa game '{cleaned_title}': Người chơi đang tương tác với giao diện và cơ chế trên màn hình. "
                "Cần quan sát các chỉ số (máu, năng lượng, tài nguyên, điểm số, thời gian) và nhiệm vụ hiển thị."
            ),
            co_stream_focus=(
                f"Đồng hành cùng người chơi trong '{cleaned_title}': Co-host nhận xét đồ họa, phong cách mỹ thuật, "
                "bình luận các pha xử lý, nhắc nhở biến cố bất ngờ và giữ không khí livestream cuốn hút."
            ),
            keywords=(cleaned_title.lower(),),
            source="dynamic_zero_shot",
        )

    return None


def format_game_prompt_context(profile: GameProfile | None) -> str:
    """Format thông tin game thành prompt context chuẩn cho RootAgent và Vision."""
    if profile is None:
        return ""
    source_tag = f" [Nguồn: {profile.source}]" if profile.source else ""
    return (
        f"[GAMEPLAY CONTEXT{source_tag}]\n"
        f"Tựa game: {profile.title}\n"
        f"Thể loại: {profile.genre}\n"
        f"Cơ chế & Mục tiêu cốt lõi: {profile.mechanics}\n"
        f"Định hướng Co-host: {profile.co_stream_focus}\n"
        "Yêu cầu: Bám sát diễn biến và vật phẩm thực tế trên màn hình, không bịa đặt quy tắc ngoài game.\n"
        "[/GAMEPLAY CONTEXT]"
    )


__all__ = [
    "GameProfile",
    "KNOWN_GAMES",
    "GameKnowledgeStore",
    "clean_browser_title",
    "clean_game_title",
    "is_gaming_window",
    "detect_game_from_window",
    "format_game_prompt_context",
    "fetch_game_profile_from_research",
    "trigger_background_game_research",
]
