from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk


GEMINI_API_KEYS_URL = "https://aistudio.google.com/api-keys"
DEEPSEEK_POOL_URL = "http://127.0.0.1:5010"
ELEVENLABS_POOL_URL = "http://127.0.0.1:18888"

DEEPSEEK_ROLE_KEYS = {
    "companion": "ERIS_DS_COMPANION_API_KEY",
    "surface": "ERIS_DS_SURFACE_API_KEY",
    "seed": "ERIS_DS_SEED_API_KEY",
    "executive": "ERIS_DS_EXECUTIVE_API_KEY",
    "curator": "ERIS_DS_CURATOR_API_KEY",
    "observer": "ERIS_DS_OBSERVER_API_KEY",
    "critic": "ERIS_DS_CRITIC_API_KEY",
    "inner": "ERIS_DS_INNER_API_KEY",
}


@dataclass(frozen=True)
class Action:
    group: str
    name: str
    path: str
    kind: str = "bat"
    note: str = ""


CORE_ACTIONS = [
    Action("Runtime", "Start Eris", "run_eris.bat", note="Main launcher"),
    Action("Runtime", "Runtime only", "run_runtime.bat"),
    Action("Runtime", "Smoke test", "run_smoke_test.bat"),
    Action("Runtime", "User guide", "open_user_guide.bat", note="Vietnamese non-dev guide"),
    Action("Accounts", "Secrets setup", "setup_secrets.bat", note="Create/open config\\secrets.json"),
    Action("Accounts", "Gemini login", "setup_gemini_login.bat"),
    Action("Accounts", "Tutor browser setup", "setup_tutor_browser.bat"),
    Action("Accounts", "Tutor login", "tutor_login.bat"),
    Action("Accounts", "ElevenLabs pool UI", "run_elevenlabs_pool_ui.bat"),
    Action("Accounts", "DeepSeek pool UI", "run_deepseek_pool_ui.bat"),
    Action("Accounts", "Apply DeepSeek pool keys", "apply_deepseek_pool_to_secrets.bat", note="Auto-fill secrets from Pool UI"),
    Action("Accounts", "DeepSeek worker", "tools/whale2api/whale2api.exe", kind="exe"),
    Action("Maintenance", "Install Live2D deps", "install_live2d_body.bat"),
    Action("Maintenance", "Doctor", "run_doctor.bat"),
    Action("Maintenance", "Browser extension install", "browser_extension/install.bat"),
    Action("Build", "Full build", "_fullbuild.py", kind="py"),
    Action("Build", "Patch build", "_patchbuild.py", kind="py"),
]


def app_root() -> Path:
    def looks_like_eris_root(path: Path) -> bool:
        return (
            (path / "run_eris.bat").exists()
            or (path / "src" / "manager_gui.py").exists()
            or (path / "config" / "secrets.json").exists()
            or (path / "config" / "secrets.example.json").exists()
        )

    env_root = os.environ.get("ERIS_PROJECT_ROOT", "").strip()
    if env_root:
        candidate = Path(env_root).expanduser().resolve()
        if looks_like_eris_root(candidate):
            return candidate

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir, exe_dir.parent])
    else:
        here = Path(__file__).resolve()
        candidates.extend([here.parent, here.parents[1] if here.parent.name.lower() == "src" else here.parent])

    try:
        candidates.append(Path.cwd().resolve())
    except OSError:
        pass

    for candidate in candidates:
        if looks_like_eris_root(candidate):
            return candidate
    return candidates[0] if candidates else Path.cwd()


def shorten(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


class ErisManager(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.root_dir = app_root()
        exe_name = Path(sys.executable).stem.lower()
        self.setup_mode = exe_name == "erissetup"
        self.app_title = "Eris Setup" if self.setup_mode else "Eris Manager"
        self.title(self.app_title)
        self.geometry("980x660")
        self.minsize(860, 560)
        self.configure(bg="#f5f5f2")
        self.script_rows: list[tuple[str, Path]] = []
        self.gemini_key_var = tk.StringVar()
        self.firebase_key_var = tk.StringVar()

        self._build_style()
        self._build_ui()
        self.refresh()

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f5f5f2")
        style.configure("Panel.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("TLabel", background="#f5f5f2", foreground="#202124", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("Subtle.TLabel", foreground="#5f6368")
        style.configure("PanelTitle.TLabel", background="#ffffff", font=("Segoe UI", 11, "bold"))
        style.configure("Status.TLabel", background="#ffffff", foreground="#5f6368")
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(outer)
        header.pack(fill=tk.X)
        ttk.Label(header, text=self.app_title, style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(header, text=str(self.root_dir), style="Subtle.TLabel").pack(side=tk.LEFT, padx=(16, 0))
        ttk.Button(header, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)

        body = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, pady=(14, 0))

        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=2)
        body.add(right, weight=3)

        self.status_panel = ttk.Frame(left, style="Panel.TFrame", padding=12)
        self.status_panel.pack(fill=tk.X)
        ttk.Label(self.status_panel, text="Status", style="PanelTitle.TLabel").pack(anchor=tk.W)
        self.status_text = tk.Text(self.status_panel, height=9, wrap=tk.WORD, relief=tk.FLAT, bg="#ffffff", fg="#202124")
        self.status_text.pack(fill=tk.X, pady=(8, 0))
        self.status_text.configure(state=tk.DISABLED)

        folders = ttk.Frame(left, style="Panel.TFrame", padding=12)
        folders.pack(fill=tk.X, pady=(12, 0))
        ttk.Label(folders, text="Open", style="PanelTitle.TLabel").pack(anchor=tk.W)
        buttons = ttk.Frame(folders, style="Panel.TFrame")
        buttons.pack(fill=tk.X, pady=(8, 0))
        for label, rel in [
            ("App folder", "."),
            ("Config", "config"),
            ("Logs", "logs"),
            ("Build output", r"C:\Users\Gtvkun\Documents\eris"),
            ("Release output", r"C:\Users\Gtvkun\Documents\eris_release"),
        ]:
            ttk.Button(buttons, text=label, command=lambda r=rel: self.open_path(r)).pack(fill=tk.X, pady=3)

        self.quick = ttk.Notebook(right)
        self.quick.pack(fill=tk.BOTH, expand=True)
        self.setup_frame = ttk.Frame(self.quick, padding=10)
        self.quick.add(self.setup_frame, text="Setup")
        self._build_setup_tab(self.setup_frame)

        self.action_frames: dict[str, ttk.Frame] = {}
        for group in ["Runtime", "Accounts", "Maintenance", "Build"]:
            frame = ttk.Frame(self.quick, padding=10)
            self.quick.add(frame, text=group)
            self.action_frames[group] = frame

        all_frame = ttk.Frame(self.quick, padding=10)
        self.quick.add(all_frame, text="All scripts")
        self.tree = ttk.Treeview(all_frame, columns=("path", "size"), show="headings", selectmode="browse")
        self.tree.heading("path", text="Script")
        self.tree.heading("size", text="Size")
        self.tree.column("path", width=560)
        self.tree.column("size", width=80, anchor=tk.E)
        self.tree.pack(fill=tk.BOTH, expand=True)
        row_buttons = ttk.Frame(all_frame)
        row_buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(row_buttons, text="Run selected", command=self.run_selected_script, style="Accent.TButton").pack(side=tk.LEFT)
        ttk.Button(row_buttons, text="Open selected folder", command=self.open_selected_folder).pack(side=tk.LEFT, padx=(8, 0))

        self.log = tk.Text(outer, height=6, wrap=tk.WORD, relief=tk.SOLID, bd=1, bg="#101418", fg="#d7e2ea")
        self.log.pack(fill=tk.X, pady=(12, 0))
        self.log_insert("Ready.")
        if self.setup_mode:
            self.quick.select(self.setup_frame)

    def _build_setup_tab(self, parent: ttk.Frame) -> None:
        guide = self._setup_card(parent, "Start here")
        ttk.Button(guide, text="Open user guide", command=lambda: self.run_action(self._action_by_name("User guide"))).pack(side=tk.LEFT)
        ttk.Button(guide, text="Open secrets file", command=self.open_or_create_secrets).pack(side=tk.LEFT, padx=(8, 0))

        gemini = self._setup_card(parent, "Gemini key")
        ttk.Button(gemini, text="Get Gemini key", command=lambda: self.open_url(GEMINI_API_KEYS_URL)).grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        ttk.Entry(gemini, textvariable=self.gemini_key_var, show="*", width=38).grid(row=0, column=1, sticky=tk.EW, padx=(0, 8))
        ttk.Button(gemini, text="Save", command=self.save_gemini_key, style="Accent.TButton").grid(row=0, column=2, sticky=tk.E)
        gemini.columnconfigure(1, weight=1)

        deepseek = self._setup_card(parent, "DeepSeek pool")
        ttk.Button(deepseek, text="Open Pool UI", command=lambda: self.run_action(self._action_by_name("DeepSeek pool UI"))).grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        ttk.Button(deepseek, text="Apply role keys", command=lambda: self.run_action(self._action_by_name("Apply DeepSeek pool keys")), style="Accent.TButton").grid(row=0, column=1, sticky=tk.W, padx=(0, 8))
        ttk.Button(deepseek, text="Role status", command=self.refresh_setup_status).grid(row=0, column=2, sticky=tk.W)
        ttk.Label(deepseek, text="Pool names: companion, surface, seed, executive, curator, observer, critic, inner", style="Status.TLabel").grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(8, 0))

        eleven = self._setup_card(parent, "ElevenLabs pool")
        ttk.Button(eleven, text="Open ElevenLabs Pool", command=lambda: self.run_action(self._action_by_name("ElevenLabs pool UI"))).grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        ttk.Entry(eleven, textvariable=self.firebase_key_var, show="*", width=34).grid(row=0, column=1, sticky=tk.EW, padx=(0, 8))
        ttk.Button(eleven, text="Save Firebase", command=self.save_firebase_key, style="Accent.TButton").grid(row=0, column=2, sticky=tk.E)
        ttk.Label(eleven, text="Refresh token(s), one per line:", style="Status.TLabel").grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(8, 2))
        self.eleven_tokens_text = tk.Text(eleven, height=4, wrap=tk.WORD, relief=tk.SOLID, bd=1, bg="#ffffff", fg="#202124")
        self.eleven_tokens_text.grid(row=2, column=0, columnspan=3, sticky=tk.EW)
        ttk.Button(eleven, text="Add refresh tokens to pool", command=self.add_elevenlabs_tokens, style="Accent.TButton").grid(row=3, column=0, sticky=tk.W, pady=(8, 0))
        eleven.columnconfigure(1, weight=1)

        status = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        status.pack(fill=tk.BOTH, expand=True, pady=5)
        ttk.Label(status, text="Setup status", style="PanelTitle.TLabel").pack(anchor=tk.W)
        self.setup_status_text = tk.Text(status, height=8, wrap=tk.WORD, relief=tk.FLAT, bg="#ffffff", fg="#202124")
        self.setup_status_text.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.setup_status_text.configure(state=tk.DISABLED)

    def _setup_card(self, parent: ttk.Frame, title: str) -> ttk.Frame:
        outer = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        outer.pack(fill=tk.X, pady=5)
        ttk.Label(outer, text=title, style="PanelTitle.TLabel").pack(anchor=tk.W)
        body = ttk.Frame(outer, style="Panel.TFrame")
        body.pack(fill=tk.X, pady=(8, 0))
        return body

    def refresh(self) -> None:
        self._render_actions()
        self._render_status()
        self._scan_scripts()
        self.refresh_setup_status()

    def _render_actions(self) -> None:
        for frame in self.action_frames.values():
            for child in frame.winfo_children():
                child.destroy()

        for action in CORE_ACTIONS:
            frame = self.action_frames[action.group]
            target = self.resolve(action.path)
            row = ttk.Frame(frame, style="Panel.TFrame", padding=10)
            row.pack(fill=tk.X, pady=5)
            left = ttk.Frame(row, style="Panel.TFrame")
            left.pack(side=tk.LEFT, fill=tk.X, expand=True)
            ttk.Label(left, text=action.name, style="PanelTitle.TLabel").pack(anchor=tk.W)
            status = self.file_status(target)
            detail = f"{shorten(target, self.root_dir)}  -  {status}"
            if action.note:
                detail += f"  -  {action.note}"
            ttk.Label(left, text=detail, style="Status.TLabel").pack(anchor=tk.W, pady=(2, 0))
            ttk.Button(
                row,
                text="Run",
                command=lambda a=action: self.run_action(a),
                style="Accent.TButton" if target.exists() and target.stat().st_size > 0 else "TButton",
            ).pack(side=tk.RIGHT, padx=(10, 0))

    def _render_status(self) -> None:
        checks = [
            ("secrets.json", self.root_dir / "config" / "secrets.json"),
            ("secrets guide", self.root_dir / "config" / "SECRETS_SETUP.md"),
            ("user guide", self.root_dir / "HUONG_DAN_NGUOI_DUNG.md"),
            ("ElevenLabs DB", self.root_dir / "config" / "elevenlabs_pool.db"),
            ("Portable Python", self.root_dir / "python" / "python.exe"),
            ("Live2D requirements", self.root_dir / "requirements-live2d.txt"),
            ("Eris launcher", self.root_dir / "run_eris.bat"),
            ("Eris executable", self.root_dir / "Eris.exe"),
        ]
        lines = []
        for label, path in checks:
            lines.append(f"{self.file_mark(path)} {label}: {shorten(path, self.root_dir)}")
        self.status_text.configure(state=tk.NORMAL)
        self.status_text.delete("1.0", tk.END)
        self.status_text.insert(tk.END, "\n".join(lines))
        self.status_text.configure(state=tk.DISABLED)

    def _scan_scripts(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.script_rows.clear()
        skip_parts = {".venv", "portable_python", "node_modules", "reference-repos", ".tmp_pytest", "__pycache__"}
        seen: set[Path] = set()
        for current, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in skip_parts and not d.startswith(".tmp")]
            current_path = Path(current)
            if any(part in skip_parts for part in current_path.parts):
                continue
            for name in sorted(files):
                if not name.lower().endswith(".bat"):
                    continue
                path = current_path / name
                if path in seen:
                    continue
                seen.add(path)
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                self.script_rows.append(("bat", path))
                self.tree.insert("", tk.END, values=(shorten(path, self.root_dir), str(size)))

    def _action_by_name(self, name: str) -> Action:
        for action in CORE_ACTIONS:
            if action.name == name:
                return action
        raise KeyError(name)

    def secrets_path(self) -> Path:
        return self.root_dir / "config" / "secrets.json"

    def secrets_example_path(self) -> Path:
        return self.root_dir / "config" / "secrets.example.json"

    def _ensure_secrets_file(self) -> Path:
        path = self.secrets_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            example = self.secrets_example_path()
            if not example.exists():
                raise FileNotFoundError(f"Missing file:\n{example}")
            path.write_text(example.read_text(encoding="utf-8-sig"), encoding="utf-8")
        return path

    def _load_secrets_json(self) -> dict:
        path = self._ensure_secrets_file()
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"config\\secrets.json is not valid JSON:\n{exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("config\\secrets.json must contain a JSON object.")
        return payload

    def _write_secrets_json(self, payload: dict) -> None:
        self.secrets_path().write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _save_secret_values(self, updates: dict[str, str], *, fill_empty: dict[str, str] | None = None) -> None:
        payload = self._load_secrets_json()
        api_keys = payload.setdefault("api_keys", {})
        if not isinstance(api_keys, dict):
            raise ValueError("config\\secrets.json api_keys must be a JSON object.")
        for key, value in updates.items():
            api_keys[key] = value
        for key, value in (fill_empty or {}).items():
            if not str(api_keys.get(key) or "").strip():
                api_keys[key] = value
        self._write_secrets_json(payload)

    def open_url(self, url: str) -> None:
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            self.log_insert(f"Opened: {url}")
        except OSError as exc:
            messagebox.showerror("Eris Manager", str(exc))

    def open_or_create_secrets(self) -> None:
        try:
            path = self._ensure_secrets_file()
        except Exception as exc:
            messagebox.showerror("Eris Manager", str(exc))
            return
        self.open_path(path)
        self.refresh()

    def save_gemini_key(self) -> None:
        value = self.gemini_key_var.get().strip()
        if not value:
            messagebox.showinfo("Eris Manager", "Paste Gemini API key first.")
            return
        try:
            self._save_secret_values(
                {"GEMINI_API_KEY": value},
                fill_empty={
                    "ERIS_PRIVATE_RESIDUE_CURATOR_API_KEY": value,
                    "ERIS_SPEECH_API_KEY": value,
                },
            )
        except Exception as exc:
            messagebox.showerror("Eris Manager", str(exc))
            return
        self.gemini_key_var.set("")
        self.log_insert("Saved Gemini key to config\\secrets.json")
        messagebox.showinfo("Eris Manager", "Gemini key saved.")
        self.refresh()

    def save_firebase_key(self) -> None:
        value = self.firebase_key_var.get().strip()
        if not value:
            messagebox.showinfo("Eris Manager", "Paste FIREBASE_API_KEY first.")
            return
        try:
            self._save_secret_values({"FIREBASE_API_KEY": value})
        except Exception as exc:
            messagebox.showerror("Eris Manager", str(exc))
            return
        self.firebase_key_var.set("")
        self.log_insert("Saved FIREBASE_API_KEY to config\\secrets.json")
        messagebox.showinfo("Eris Manager", "Firebase key saved.")
        self.refresh()

    def add_elevenlabs_tokens(self) -> None:
        raw = self.eleven_tokens_text.get("1.0", tk.END)
        tokens = []
        for line in raw.replace(",", "\n").replace(";", "\n").splitlines():
            token = line.strip()
            if token and token not in tokens:
                tokens.append(token)
        if not tokens:
            messagebox.showinfo("Eris Manager", "Paste ElevenLabs refresh token first.")
            return
        try:
            imported, skipped = self._insert_elevenlabs_refresh_tokens(tokens)
        except Exception as exc:
            messagebox.showerror("Eris Manager", str(exc))
            return
        self.eleven_tokens_text.delete("1.0", tk.END)
        self.log_insert(f"ElevenLabs pool updated: imported={imported} skipped={skipped}")
        messagebox.showinfo("Eris Manager", f"Added {imported} refresh token(s). Skipped {skipped}.")
        self.refresh()

    def _insert_elevenlabs_refresh_tokens(self, tokens: list[str]) -> tuple[int, int]:
        db_path = self.root_dir / "config" / "elevenlabs_pool.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        imported = 0
        with sqlite3.connect(str(db_path), timeout=8.0) as conn:
            conn.execute(
                """
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
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_eleven_status ON elevenlabs_accounts(status)")
            for token in tokens:
                label = f"ElevenLabs {int(now)}-{imported + 1}"
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO elevenlabs_accounts
                    (label, refresh_token, created_at, notes, status)
                    VALUES (?, ?, ?, ?, 'active')
                    """,
                    (label, token, now, "Added from Eris Manager setup"),
                )
                imported += int(cur.rowcount or 0)
            conn.commit()
        return imported, len(tokens) - imported

    def _deepseek_db_path(self) -> Path | None:
        candidates = [
            self.root_dir / "tools" / "whale2api" / "whale2api.db",
            self.root_dir / "tools" / "whale2api" / "docker-data" / "whale2api" / "whale2api.db",
        ]
        for path in candidates:
            if path.is_file():
                return path
        return None

    def _count_elevenlabs_accounts(self) -> int:
        db_path = self.root_dir / "config" / "elevenlabs_pool.db"
        if not db_path.is_file():
            return 0
        try:
            with sqlite3.connect(str(db_path), timeout=2.0) as conn:
                row = conn.execute("SELECT COUNT(*) FROM elevenlabs_accounts").fetchone()
                return int(row[0] or 0) if row else 0
        except sqlite3.Error:
            return 0

    def _count_deepseek_gateway_keys(self) -> int:
        db_path = self._deepseek_db_path()
        if db_path is None:
            return 0
        try:
            with sqlite3.connect(str(db_path), timeout=2.0) as conn:
                row = conn.execute("SELECT COUNT(*) FROM gateway_api_keys WHERE COALESCE(enabled, 1) = 1").fetchone()
                return int(row[0] or 0) if row else 0
        except sqlite3.Error:
            return 0

    def refresh_setup_status(self) -> None:
        if not hasattr(self, "setup_status_text"):
            return
        try:
            payload = self._load_secrets_json()
        except Exception:
            payload = {}
        api_keys = payload.get("api_keys", {}) if isinstance(payload, dict) else {}
        if not isinstance(api_keys, dict):
            api_keys = {}
        lines = [
            f"secrets.json: {self.file_mark(self.secrets_path())}",
            f"Gemini key: {'OK' if str(api_keys.get('GEMINI_API_KEY') or '').strip() else 'MISSING'}",
            f"Firebase key: {'OK' if str(api_keys.get('FIREBASE_API_KEY') or '').strip() else 'MISSING'}",
            f"ElevenLabs accounts: {self._count_elevenlabs_accounts()}",
            f"DeepSeek gateway pools: {self._count_deepseek_gateway_keys()}",
        ]
        for role, secret_name in DEEPSEEK_ROLE_KEYS.items():
            mark = "OK" if str(api_keys.get(secret_name) or "").strip() else "MISSING"
            lines.append(f"{role:<9} -> {secret_name}: {mark}")
        self.setup_status_text.configure(state=tk.NORMAL)
        self.setup_status_text.delete("1.0", tk.END)
        self.setup_status_text.insert(tk.END, "\n".join(lines))
        self.setup_status_text.configure(state=tk.DISABLED)

    def resolve(self, path: str) -> Path:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else self.root_dir / candidate

    def file_mark(self, path: Path) -> str:
        if not path.exists():
            return "MISSING"
        try:
            if path.is_file() and path.stat().st_size == 0:
                return "EMPTY"
        except OSError:
            return "WARN"
        return "OK"

    def file_status(self, path: Path) -> str:
        mark = self.file_mark(path)
        if mark == "OK":
            return "available"
        if mark == "EMPTY":
            return "empty file"
        return "missing"

    def run_action(self, action: Action) -> None:
        path = self.resolve(action.path)
        if action.kind == "py":
            self.run_python(path)
        elif action.kind == "exe":
            self.run_exe(path)
        else:
            self.run_bat(path)

    def run_selected_script(self) -> None:
        item = self.tree.focus()
        if not item:
            messagebox.showinfo("Eris Manager", "Select a script first.")
            return
        index = self.tree.index(item)
        if index < 0 or index >= len(self.script_rows):
            return
        _, path = self.script_rows[index]
        self.run_bat(path)

    def open_selected_folder(self) -> None:
        item = self.tree.focus()
        if not item:
            return
        index = self.tree.index(item)
        if index < 0 or index >= len(self.script_rows):
            return
        _, path = self.script_rows[index]
        self.open_path(path.parent)

    def run_bat(self, path: Path) -> None:
        if not self._can_run(path):
            return
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(["cmd.exe", "/k", "call", str(path)], cwd=path.parent, creationflags=flags)
        self.log_insert(f"Started: {shorten(path, self.root_dir)}")

    def run_exe(self, path: Path) -> None:
        if not self._can_run(path):
            return
        env = os.environ.copy()
        if path.name.lower() == "poolui.exe" and path.parent.name.lower() == "whale2api":
            env.setdefault("POOL_UI_ADMIN_TOKEN", "123456")
        subprocess.Popen([str(path)], cwd=path.parent, env=env)
        self.log_insert(f"Started: {shorten(path, self.root_dir)}")

    def run_python(self, path: Path) -> None:
        if not self._can_run(path):
            return
        python = self.root_dir / ".venv" / "Scripts" / "python.exe"
        if not python.exists():
            python = self.root_dir / "python" / "python.exe"
        if not python.exists():
            python = Path(sys.executable)
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(["cmd.exe", "/k", str(python), str(path)], cwd=self.root_dir, creationflags=flags)
        self.log_insert(f"Started: {shorten(path, self.root_dir)}")

    def _can_run(self, path: Path) -> bool:
        if not path.exists():
            messagebox.showerror("Eris Manager", f"Missing file:\n{path}")
            return False
        if path.is_file() and path.stat().st_size == 0:
            messagebox.showwarning("Eris Manager", f"This file is empty:\n{path}")
            return False
        return True

    def open_path(self, value: str | Path) -> None:
        path = self.resolve(str(value)) if not isinstance(value, Path) else value
        path.mkdir(parents=True, exist_ok=True) if path.suffix == "" else None
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            self.log_insert(f"Opened: {shorten(path, self.root_dir)}")
        except OSError as exc:
            messagebox.showerror("Eris Manager", str(exc))

    def log_insert(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log.insert(tk.END, f"[{stamp}] {text}\n")
        self.log.see(tk.END)


def main() -> None:
    app = ErisManager()
    app.mainloop()


if __name__ == "__main__":
    main()
