# -*- coding: utf-8 -*-
from __future__ import annotations
"""elevenlabs_pool_db.py — Quản lý SQLite Database & Token Pool cho ElevenLabs.

Hệ thống lưu trữ danh sách ElevenLabs Refresh Tokens, tự động đổi Firebase Token,
đồng bộ số ký tự đã dùng / hạn mức tổng và thời gian reset quota định kỳ.
"""

from contextlib import contextmanager
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_LOGGER = logging.getLogger("ElevenPool")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_db_path() -> Path:
    env_root = os.environ.get("ERIS_PROJECT_ROOT", "").strip()
    if env_root:
        candidate = Path(env_root) / "config" / "elevenlabs_pool.db"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate
    target = _PROJECT_ROOT / "config" / "elevenlabs_pool.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


@dataclass
class ElevenAccount:
    id: int
    label: str
    refresh_token: str
    bearer_token: str
    bearer_expires_at: float
    character_count: int
    character_limit: int
    status: str  # active | cooling | exhausted | disabled
    created_at: float
    cooldown_until: float
    reset_at: float
    last_used_at: float
    notes: str

    @property
    def remaining_characters(self) -> int:
        return max(0, self.character_limit - self.character_count)

    @property
    def usage_percent(self) -> float:
        if self.character_limit <= 0:
            return 100.0
        return min(100.0, round((self.character_count / self.character_limit) * 100.0, 1))

    def to_dict(self) -> Dict[str, Any]:
        now = time.time()
        return {
            "id": self.id,
            "label": self.label,
            "refresh_token_masked": self.refresh_token[:8] + "..." + self.refresh_token[-6:] if len(self.refresh_token) > 16 else self.refresh_token,
            "has_bearer": bool(self.bearer_token and now < self.bearer_expires_at),
            "character_count": self.character_count,
            "character_limit": self.character_limit,
            "remaining_characters": self.remaining_characters,
            "usage_percent": self.usage_percent,
            "status": self.status,
            "created_at": self.created_at,
            "created_at_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.created_at)),
            "cooldown_until": self.cooldown_until,
            "cooldown_remaining_s": max(0, int(self.cooldown_until - now)),
            "reset_at": self.reset_at,
            "reset_at_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.reset_at)) if self.reset_at > 0 else "Chưa xác định",
            "reset_remaining_s": max(0, int(self.reset_at - now)) if self.reset_at > 0 else 0,
            "last_used_at": self.last_used_at,
            "last_used_at_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.last_used_at)) if self.last_used_at > 0 else "Chưa từng dùng",
            "notes": self.notes,
        }


class ElevenPoolDB:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or _resolve_db_path()
        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock:
            with self._connection() as conn:
                conn.execute("""
                CREATE TABLE IF NOT EXISTS elevenlabs_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    refresh_token TEXT UNIQUE NOT NULL,
                    bearer_token TEXT DEFAULT '',
                    bearer_expires_at REAL DEFAULT 0.0,
                    character_count INTEGER DEFAULT 0,
                    character_limit INTEGER DEFAULT 10000,
                    status TEXT DEFAULT 'active',
                    created_at REAL NOT NULL,
                    cooldown_until REAL DEFAULT 0.0,
                    reset_at REAL DEFAULT 0.0,
                    last_used_at REAL DEFAULT 0.0,
                    notes TEXT DEFAULT ''
                );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_eleven_status ON elevenlabs_accounts(status);")
                conn.commit()

    def _row_to_account(self, row: sqlite3.Row) -> ElevenAccount:
        return ElevenAccount(
            id=row["id"],
            label=row["label"],
            refresh_token=row["refresh_token"],
            bearer_token=row["bearer_token"] or "",
            bearer_expires_at=float(row["bearer_expires_at"] or 0.0),
            character_count=int(row["character_count"] or 0),
            character_limit=int(row["character_limit"] or 10000),
            status=str(row["status"] or "active"),
            created_at=float(row["created_at"] or time.time()),
            cooldown_until=float(row["cooldown_until"] or 0.0),
            reset_at=float(row["reset_at"] or 0.0),
            last_used_at=float(row["last_used_at"] or 0.0),
            notes=str(row["notes"] or ""),
        )

    def add_account(
        self,
        refresh_token: str,
        label: str = "",
        notes: str = "",
        auto_sync: bool = True,
    ) -> Tuple[bool, str, Optional[ElevenAccount]]:
        token = str(refresh_token or "").strip()
        if not token:
            return False, "Refresh Token không được để trống", None

        now = time.time()
        lbl = str(label or "").strip()
        if not lbl:
            lbl = f"Acc-{token[:6]}"

        with self._lock:
            try:
                with self._connection() as conn:
                    cur = conn.execute(
                        """
                        INSERT INTO elevenlabs_accounts (label, refresh_token, created_at, notes, status)
                        VALUES (?, ?, ?, ?, 'active')
                        """,
                        (lbl, token, now, str(notes or "").strip()),
                    )
                    conn.commit()
                    acc_id = cur.lastrowid
            except sqlite3.IntegrityError:
                return False, "Refresh Token này đã tồn tại trong danh sách", None
            except Exception as exc:
                return False, f"Lỗi cơ sở dữ liệu: {exc}", None

        acc = self.get_account_by_id(acc_id)
        if auto_sync and acc:
            self.sync_subscription(acc.id)
            acc = self.get_account_by_id(acc_id)

        return True, "Đã thêm tài khoản mới thành công", acc

    def get_account_by_id(self, account_id: int) -> Optional[ElevenAccount]:
        with self._lock:
            with self._connection() as conn:
                row = conn.execute("SELECT * FROM elevenlabs_accounts WHERE id = ?", (account_id,)).fetchone()
                return self._row_to_account(row) if row else None

    def list_accounts(self) -> List[ElevenAccount]:
        now = time.time()
        # Auto-heal: reset exhausted accounts whose reset_at has passed
        self._check_auto_resets(now)
        with self._lock:
            with self._connection() as conn:
                rows = conn.execute("SELECT * FROM elevenlabs_accounts ORDER BY id ASC").fetchall()
                return [self._row_to_account(row) for row in rows]

    def _check_auto_resets(self, now: float) -> None:
        with self._lock:
            with self._connection() as conn:
                # If reset_at is set and passed, reset character count to 0 and set status to active
                conn.execute(
                    """
                    UPDATE elevenlabs_accounts
                    SET character_count = 0, status = 'active', cooldown_until = 0.0
                    WHERE status IN ('exhausted', 'cooling') AND reset_at > 0 AND reset_at <= ?
                    """,
                    (now,),
                )
                # If cooldown_until passed and not exhausted
                conn.execute(
                    """
                    UPDATE elevenlabs_accounts
                    SET status = 'active'
                    WHERE status = 'cooling' AND cooldown_until <= ? AND (reset_at == 0 OR reset_at > ?)
                    """,
                    (now, now),
                )
                conn.commit()

    def get_active_account(self) -> Optional[ElevenAccount]:
        """Lấy tài khoản tốt nhất khả dụng: status == 'active', còn quota, không bị cooldown."""
        now = time.time()
        self._check_auto_resets(now)

        with self._lock:
            with self._connection() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM elevenlabs_accounts
                    WHERE status = 'active'
                      AND cooldown_until <= ?
                      AND (character_limit == 0 OR character_count < character_limit)
                    ORDER BY (character_limit - character_count) DESC, last_used_at ASC
                    """,
                    (now,),
                ).fetchall()

                if rows:
                    return self._row_to_account(rows[0])
                return None

    def update_bearer_token(self, account_id: int, bearer_token: str, expires_in_seconds: float = 3000.0) -> None:
        now = time.time()
        expires_at = now + expires_in_seconds
        with self._lock:
            with self._connection() as conn:
                conn.execute(
                    "UPDATE elevenlabs_accounts SET bearer_token = ?, bearer_expires_at = ? WHERE id = ?",
                    (bearer_token, expires_at, account_id),
                )
                conn.commit()

    def record_usage(self, account_id: int, char_count: int) -> None:
        now = time.time()
        with self._lock:
            with self._connection() as conn:
                row = conn.execute("SELECT character_count, character_limit FROM elevenlabs_accounts WHERE id = ?", (account_id,)).fetchone()
                if row:
                    new_count = int(row["character_count"] or 0) + max(0, char_count)
                    limit = int(row["character_limit"] or 10000)
                    new_status = "exhausted" if limit > 0 and new_count >= limit else "active"
                    conn.execute(
                        """
                        UPDATE elevenlabs_accounts
                        SET character_count = ?, last_used_at = ?, status = CASE WHEN status = 'disabled' THEN 'disabled' ELSE ? END
                        WHERE id = ?
                        """,
                        (new_count, now, new_status, account_id),
                    )
                    conn.commit()

    def mark_exhausted(self, account_id: int, cooldown_seconds: float = 86400.0, reset_timestamp: float = 0.0) -> None:
        now = time.time()
        cooldown_until = now + max(60.0, cooldown_seconds)
        with self._lock:
            with self._connection() as conn:
                if reset_timestamp > 0:
                    conn.execute(
                        "UPDATE elevenlabs_accounts SET status = 'exhausted', cooldown_until = ?, reset_at = ? WHERE id = ?",
                        (cooldown_until, reset_timestamp, account_id),
                    )
                else:
                    conn.execute(
                        "UPDATE elevenlabs_accounts SET status = 'exhausted', cooldown_until = ? WHERE id = ?",
                        (cooldown_until, account_id),
                    )
                conn.commit()

    def mark_cooling(self, account_id: int, seconds: float = 300.0) -> None:
        now = time.time()
        cooldown_until = now + max(10.0, seconds)
        with self._lock:
            with self._connection() as conn:
                conn.execute(
                    "UPDATE elevenlabs_accounts SET status = 'cooling', cooldown_until = ? WHERE id = ? AND status != 'disabled'",
                    (cooldown_until, account_id),
                )
                conn.commit()

    def toggle_account(self, account_id: int, enabled: Optional[bool] = None) -> Tuple[bool, str]:
        with self._lock:
            with self._connection() as conn:
                row = conn.execute("SELECT status FROM elevenlabs_accounts WHERE id = ?", (account_id,)).fetchone()
                if not row:
                    return False, "Không tìm thấy tài khoản"
                cur_status = row["status"]
                if enabled is None:
                    new_status = "active" if cur_status == "disabled" else "disabled"
                else:
                    new_status = "active" if enabled else "disabled"
                conn.execute("UPDATE elevenlabs_accounts SET status = ? WHERE id = ?", (new_status, account_id))
                conn.commit()
                msg = "Đã bật tài khoản" if new_status == "active" else "Đã tắt tài khoản"
                return True, msg

    def delete_account(self, account_id: int) -> Tuple[bool, str]:
        with self._lock:
            with self._connection() as conn:
                cur = conn.execute("DELETE FROM elevenlabs_accounts WHERE id = ?", (account_id,))
                conn.commit()
                if cur.rowcount > 0:
                    return True, "Đã xóa tài khoản thành công"
                return False, "Không tìm thấy tài khoản để xóa"

    def sync_subscription(self, account_id: int) -> Tuple[bool, str]:
        """Đổi Firebase Bearer token và đồng bộ quota từ ElevenLabs API."""
        acc = self.get_account_by_id(account_id)
        if not acc:
            return False, "Không tìm thấy tài khoản"

        from eris_secrets import get_secret
        import requests

        firebase_key = str(get_secret("FIREBASE_API_KEY") or "").strip()
        if not firebase_key:
            return False, "Thiếu FIREBASE_API_KEY trong secrets.json/env"

        # 1. Exchange Refresh Token -> Firebase id_token
        url = f"https://securetoken.googleapis.com/v1/token?key={firebase_key}"
        headers = {
            "Referer": "https://elevenlabs.io/",
            "Origin": "https://elevenlabs.io",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"grant_type": "refresh_token", "refresh_token": acc.refresh_token}

        try:
            r = requests.post(url, headers=headers, data=data, timeout=12)
            if r.status_code != 200:
                err_msg = r.json().get("error", {}).get("message", r.text)
                self.mark_cooling(account_id, 600)
                return False, f"Lỗi đổi token từ Firebase [{r.status_code}]: {err_msg}"
            
            bearer_token = str(r.json().get("id_token") or "").strip()
            if not bearer_token:
                return False, "Firebase không trả về id_token"
            
            self.update_bearer_token(account_id, bearer_token, 3000.0)
        except Exception as exc:
            return False, f"Lỗi kết nối Firebase: {exc}"

        # 2. Fetch subscription details from ElevenLabs API
        sub_url = "https://api.elevenlabs.io/v1/user/subscription"
        sub_headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Referer": "https://elevenlabs.io/",
            "Origin": "https://elevenlabs.io",
            "User-Agent": "Mozilla/5.0",
        }

        try:
            r2 = requests.get(sub_url, headers=sub_headers, timeout=12)
            if r2.status_code == 200:
                info = r2.json()
                char_count = int(info.get("character_count", 0))
                char_limit = int(info.get("character_limit", 10000))
                reset_unix = float(info.get("next_character_count_reset_unix", 0) or 0.0)

                new_status = "active"
                if char_limit > 0 and char_count >= char_limit:
                    new_status = "exhausted"

                with self._lock:
                    with self._connection() as conn:
                        conn.execute(
                            """
                            UPDATE elevenlabs_accounts
                            SET character_count = ?, character_limit = ?, reset_at = ?, status = CASE WHEN status = 'disabled' THEN 'disabled' ELSE ? END
                            WHERE id = ?
                            """,
                            (char_count, char_limit, reset_unix, new_status, account_id),
                        )
                        conn.commit()

                return True, f"Đồng bộ thành công: {char_count}/{char_limit} ký tự"
            else:
                return False, f"ElevenLabs API trả về mã [{r2.status_code}]: {r2.text[:100]}"
        except Exception as exc:
            return False, f"Lỗi gọi ElevenLabs API: {exc}"

    def get_summary_stats(self) -> Dict[str, Any]:
        accounts = self.list_accounts()
        total_accounts = len(accounts)
        active_accounts = sum(1 for a in accounts if a.status == "active")
        exhausted_accounts = sum(1 for a in accounts if a.status == "exhausted")
        disabled_accounts = sum(1 for a in accounts if a.status == "disabled")
        
        total_characters_limit = sum(a.character_limit for a in accounts if a.status != "disabled")
        total_characters_used = sum(a.character_count for a in accounts if a.status != "disabled")
        total_characters_remaining = max(0, total_characters_limit - total_characters_used)

        return {
            "total_accounts": total_accounts,
            "active_accounts": active_accounts,
            "exhausted_accounts": exhausted_accounts,
            "disabled_accounts": disabled_accounts,
            "total_characters_limit": total_characters_limit,
            "total_characters_used": total_characters_used,
            "total_characters_remaining": total_characters_remaining,
        }


# Singleton Pool DB Instance
GLOBAL_ELEVEN_POOL = ElevenPoolDB()
