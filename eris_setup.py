"""
Eris Setup & Service Manager
============================
Diem quan ly duy nhat cho toan bo Eris:
  - Check requirements
  - Install dependencies
  - Setup auth (DeepSeek, Gemini pool, TTS)
  - Full build -> isolated output
  - Start/Stop all services
  - Health dashboard (live)

Chay bang:
    .venv\\Scripts\\python.exe eris_setup.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

# ── Ket noi mau cho Windows console ──────────────────────────────────────────
os.system("")  # enable ANSI on Windows

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):  return f"{GREEN}[OK]{RESET}   {msg}"
def warn(msg): return f"{YELLOW}[WARN]{RESET} {msg}"
def err(msg):  return f"{RED}[FAIL]{RESET} {msg}"
def info(msg): return f"{CYAN}[INFO]{RESET} {msg}"

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT      = Path(__file__).resolve().parent
VENV_PY   = ROOT / ".venv" / "Scripts" / "python.exe"
STATE_DIR = ROOT / ".eris_state"
STATE_FILE = STATE_DIR / "setup_state.json"
BUILD_OUT = Path(r"C:\Users\Gtvkun\Documents\eris")

# Service ports
PORTS = {
    "whale2api":    9090,
    "webai_1":      8081,
    "webai_2":      8082,
    "webai_3":      8083,
    "cline_bridge": 7832,
    "tts_pool":     9091,
}


# ── State management ──────────────────────────────────────────────────────────

def load_state() -> dict[str, Any]:
    STATE_DIR.mkdir(exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def update_state(key: str, value: Any) -> None:
    s = load_state()
    s[key] = value
    save_state(s)


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list[str], cwd: Path | None = None, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd or ROOT, capture_output=capture, text=True)


def port_listening(port: int, timeout: float = 1.5) -> bool:
    try:
        import socket
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:
        return False


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status < 400
    except Exception:
        return False


def banner(title: str) -> None:
    w = 54
    print(f"\n{BOLD}{'=' * w}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'=' * w}{RESET}\n")


def pause(msg: str = "Enter de tiep tuc...") -> None:
    input(f"\n{CYAN}{msg}{RESET} ")


# ── 1. Check requirements ─────────────────────────────────────────────────────

def check_requirements() -> bool:
    banner("1 / 6 — Check Requirements")
    results = {}

    # Python
    v = sys.version.split()[0]
    ok_py = sys.version_info >= (3, 12)
    print(ok(f"Python {v}") if ok_py else err(f"Python {v} (can 3.12+)"))
    results["python"] = ok_py

    # Node.js
    try:
        nv = subprocess.check_output(["node", "--version"], stderr=subprocess.STDOUT).decode().strip()
        maj = int(nv.lstrip("v").split(".")[0])
        ok_node = maj >= 22
        print(ok(f"Node.js {nv}") if ok_node else warn(f"Node.js {nv} (can >= 22)"))
        results["node"] = ok_node
    except FileNotFoundError:
        print(err("Node.js: NOT FOUND — tai ve tu https://nodejs.org/ (>= 22)"))
        results["node"] = False

    # npm
    try:
        nv2 = subprocess.check_output(["npm", "--version"], stderr=subprocess.STDOUT, shell=True).decode().strip()
        print(ok(f"npm {nv2}"))
        results["npm"] = True
    except Exception:
        print(warn("npm: khong tim thay (thu npm install thu cong)"))
        results["npm"] = False

    # .venv
    ok_venv = VENV_PY.exists()
    print(ok(".venv Python") if ok_venv else warn(".venv khong co — chay: python -m venv .venv"))
    results["venv"] = ok_venv

    all_ok = all(results.values())
    update_state("requirements", results)
    print()
    if all_ok:
        print(ok("Tat ca requirements da san sang!"))
    else:
        print(warn("Mot so requirements bi thieu. Xem huong dan phia tren."))
    return all_ok


# ── 2. Install dependencies ───────────────────────────────────────────────────

def install_dependencies() -> None:
    banner("2 / 6 — Install Dependencies")

    # pip
    print(info("Installing Python packages..."))
    req_file = ROOT / "requirements.txt"
    if req_file.exists():
        run([str(VENV_PY), "-m", "pip", "install", "-r", str(req_file), "-q"])
        print(ok("pip install done"))
    else:
        print(warn("requirements.txt khong tim thay"))

    # cline-bridge npm
    bridge_dir = ROOT / "cline-bridge"
    if bridge_dir.exists():
        print(info("npm ci in cline-bridge..."))
        run(["npm", "ci", "--prefer-offline"], cwd=bridge_dir)
        print(info("Building cline-bridge..."))
        run(["npm", "run", "build"], cwd=bridge_dir)
        print(ok("cline-bridge built"))
    else:
        print(warn("cline-bridge/ khong tim thay"))

    # VS Code extension esbuild
    ext_dir = ROOT / "src" / "vscode-extension"
    if (ext_dir / "esbuild.js").exists():
        print(info("Building VS Code extension..."))
        run(["node", "esbuild.js"], cwd=ext_dir)
        print(ok("VS Code extension built"))

    update_state("dependencies", {"done": True, "ts": time.time()})
    print()
    print(ok("Dependencies installed!"))


# ── 3. Setup DeepSeek (whale2api) ─────────────────────────────────────────────

def setup_deepseek() -> None:
    banner("3 / 6 — Setup DeepSeek (Main Brain)")
    whale_dir = ROOT / "tools" / "whale2api"
    accounts_file = whale_dir / "accounts.csv"
    exe = whale_dir / "whale2api.exe"

    if not exe.exists():
        print(warn("whale2api.exe khong tim thay tai: " + str(whale_dir)))
        print(info("Download tu: https://github.com/your-fork/whale2api/releases"))
        pause()
        return

    if accounts_file.exists():
        lines = [l.strip() for l in accounts_file.read_text().splitlines() if l.strip() and not l.startswith("#")]
        print(ok(f"accounts.csv co san: {len(lines)} account(s)"))
        for l in lines:
            parts = l.split(",")
            print(f"   - {parts[0] if parts else '?'}")
    else:
        print(warn("accounts.csv chua co"))

    print()
    print("Options:")
    print("  [a] Them account moi")
    print("  [v] Verify accounts hien co")
    print("  [s] Skip")
    ch = input("Chon: ").strip().lower()

    if ch == "a":
        email = input("Email DeepSeek: ").strip()
        pwd   = input("Password: ").strip()
        if email and pwd:
            accounts_file.parent.mkdir(parents=True, exist_ok=True)
            with accounts_file.open("a", encoding="utf-8") as f:
                f.write(f"\n{email},{pwd}")
            print(ok(f"Da them: {email}"))
            update_state("deepseek", {"accounts_file": str(accounts_file), "ts": time.time()})
    elif ch == "v":
        # Start whale2api briefly va test /models
        print(info("Khoi dong whale2api de test..."))
        proc = subprocess.Popen([str(exe)], cwd=whale_dir,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        alive = port_listening(PORTS["whale2api"])
        proc.terminate()
        print(ok(f"whale2api :9090 alive") if alive else err("whale2api khong start duoc"))

    print()
    print(ok("DeepSeek setup done"))


# ── 4. Setup Gemini Playwright Pool ──────────────────────────────────────────

def setup_gemini_pool() -> None:
    banner("4 / 6 — Setup Gemini Playwright Pool (Code Executor)")
    webai_dir  = ROOT / "tools" / "WebAI-to-API"
    auth_base  = webai_dir / "runtime"
    verify_py  = webai_dir / "verify_login.py"

    if not webai_dir.exists():
        print(err("tools/WebAI-to-API khong tim thay"))
        pause()
        return

    # Quet cac slot hien co
    slots = []
    for d in sorted(auth_base.glob("auth-*")):
        gem_json = d / "gemini.json"
        slots.append({"dir": d, "name": d.name, "ok": gem_json.exists()})

    print(f"Slots hien co: {len(slots)}")
    for s in slots:
        tag = ok(s["name"]) if s["ok"] else err(s["name"] + " (thieu gemini.json)")
        print(f"   {tag}")

    print()
    print("Options:")
    print("  [a] Them account moi (mo Chrome -> login -> luu auth)")
    print("  [d] Xoa slot")
    print("  [s] Skip")
    ch = input("Chon: ").strip().lower()

    if ch == "a":
        next_slot = 1
        existing_nums = []
        for s in slots:
            try:
                existing_nums.append(int(s["name"].replace("auth-", "")))
            except ValueError:
                pass
        while next_slot in existing_nums:
            next_slot += 1

        auth_dir = auth_base / f"auth-{next_slot}"
        auth_dir.mkdir(parents=True, exist_ok=True)

        print(info(f"Slot: auth-{next_slot} -> {auth_dir}"))
        print(info("Se mo Chrome. Dang nhap Google account roi dong cua so."))
        pause("Enter de bat dau...")

        env = {**os.environ, "PLAYWRIGHT_AUTH_STATE_DIR": str(auth_dir)}
        subprocess.run([str(VENV_PY), str(verify_py)], cwd=webai_dir, env=env)

        gem_json = auth_dir / "gemini.json"
        if gem_json.exists():
            print(ok(f"auth-{next_slot} saved!"))
        else:
            print(warn("gemini.json khong duoc tao. Kiem tra lai login."))

    elif ch == "d":
        name = input("Ten slot can xoa (vi du: auth-2): ").strip()
        target = auth_base / name
        if target.exists():
            shutil.rmtree(target)
            print(ok(f"Da xoa: {name}"))
        else:
            print(warn(f"Khong tim thay: {name}"))

    # Cap nhat pool endpoints file
    _write_pool_endpoints()
    update_state("gemini_pool", {"ts": time.time()})
    print()
    print(ok("Gemini pool setup done"))


def _write_pool_endpoints() -> None:
    """Quet auth-* va ghi endpoints vao file."""
    webai_dir = ROOT / "tools" / "WebAI-to-API"
    auth_base = webai_dir / "runtime"
    slots = sorted(d for d in auth_base.glob("auth-*") if (d / "gemini.json").exists())
    port = 8081
    eps = []
    for _ in slots:
        eps.append(f"http://127.0.0.1:{port}")
        port += 1
    STATE_DIR.mkdir(exist_ok=True)
    ep_file = STATE_DIR / "gemini_pool_endpoints.txt"
    ep_file.write_text(",".join(eps), encoding="utf-8")
    if eps:
        print(info(f"Pool endpoints: {','.join(eps)}"))


# ── 5. Setup TTS ──────────────────────────────────────────────────────────────

def setup_tts() -> None:
    banner("5 / 6 — Setup ElevenLabs TTS")
    db_file = ROOT / "config" / "elevenlabs_pool.db"

    if db_file.exists():
        print(ok(f"elevenlabs_pool.db co san: {db_file}"))
        print(info("Mo Pool UI de kiem tra / them key:"))
        print(f"   {ROOT / 'run_elevenlabs_pool_ui.bat'}")
    else:
        print(warn("elevenlabs_pool.db chua co"))
        print(info("1. Lay API key tai https://elevenlabs.io/"))
        print(info("2. Chay: run_elevenlabs_pool_ui.bat -> Add Key"))

    ch = input("\nMo Pool UI ngay bay gio? [y/n]: ").strip().lower()
    if ch == "y":
        bat = ROOT / "run_elevenlabs_pool_ui.bat"
        if bat.exists():
            subprocess.Popen(["cmd", "/c", str(bat)], cwd=ROOT)
            print(info("Da mo ElevenLabs Pool UI"))
        else:
            print(warn("run_elevenlabs_pool_ui.bat khong tim thay"))

    update_state("tts", {"ts": time.time(), "db": str(db_file)})
    print()
    print(ok("TTS setup done"))


# ── 6. Full Build ─────────────────────────────────────────────────────────────

def full_build() -> None:
    banner("6 / 6 — Full Build -> " + str(BUILD_OUT))
    print(info(f"Output: {BUILD_OUT}"))
    print(warn("Qua trinh nay mat 5-10 phut (copy .venv, node_modules, etc.)"))
    ch = input("\nBat dau build? [y/n]: ").strip().lower()
    if ch != "y":
        print("Huy build.")
        return

    build_script = ROOT / "_fullbuild.py"
    if not build_script.exists():
        print(err("_fullbuild.py khong tim thay"))
        return

    print(info("Running _fullbuild.py..."))
    result = run([str(VENV_PY), str(build_script)])
    if result.returncode == 0:
        print(ok(f"Build thanh cong! Output: {BUILD_OUT}"))
        update_state("build", {"ts": time.time(), "output": str(BUILD_OUT)})
    else:
        print(err("Build that bai. Xem log phia tren."))


# ── Start all services ────────────────────────────────────────────────────────

_procs: list[subprocess.Popen] = []

def start_all() -> None:
    banner("Start All Services")
    global _procs

    whale_dir = ROOT / "tools" / "whale2api"
    webai_dir = ROOT / "tools" / "WebAI-to-API"

    # whale2api
    exe = whale_dir / "whale2api.exe"
    if exe.exists() and not port_listening(PORTS["whale2api"]):
        print(info("Starting whale2api..."))
        p = subprocess.Popen([str(exe)], cwd=whale_dir,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _procs.append(p)
        time.sleep(2)

    # Gemini pool
    auth_base = webai_dir / "runtime"
    slots = sorted(d for d in auth_base.glob("auth-*") if (d / "gemini.json").exists())
    port = 8081
    for slot_dir in slots:
        if not port_listening(port):
            print(info(f"Starting WebAI {slot_dir.name} on :{port}..."))
            env = {**os.environ,
                   "PLAYWRIGHT_AUTH_STATE_DIR": str(slot_dir),
                   "PLAYWRIGHT_HEADLESS": "true"}
            p = subprocess.Popen(
                [str(VENV_PY), "src/run.py", "--host", "127.0.0.1", "--port", str(port)],
                cwd=webai_dir, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _procs.append(p)
        else:
            print(ok(f"WebAI :{port} already running"))
        port += 1

    # cline-bridge
    bridge_js = ROOT / "cline-bridge" / "dist" / "bridge.js"
    if bridge_js.exists() and not port_listening(PORTS["cline_bridge"]):
        print(info("Starting cline-bridge..."))
        p = subprocess.Popen(["node", str(bridge_js)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _procs.append(p)

    print()
    print(info("Cho 5s de services khoi dong..."))
    time.sleep(5)
    health_dashboard(once=True)


def stop_all() -> None:
    banner("Stop All Services")
    for p in _procs:
        try:
            p.terminate()
        except Exception:
            pass
    _procs.clear()
    print(ok("Da gui lenh stop cho tat ca processes."))


# ── Health Dashboard ──────────────────────────────────────────────────────────

SERVICES = [
    ("whale2api  (Brain)",    "whale2api",    PORTS["whale2api"],    f"http://127.0.0.1:{PORTS['whale2api']}/v1/models"),
    ("WebAI-1   (Gemini 1)",  "webai_1",      PORTS["webai_1"],     f"http://127.0.0.1:{PORTS['webai_1']}/v1/models"),
    ("WebAI-2   (Gemini 2)",  "webai_2",      PORTS["webai_2"],     f"http://127.0.0.1:{PORTS['webai_2']}/v1/models"),
    ("WebAI-3   (Gemini 3)",  "webai_3",      PORTS["webai_3"],     f"http://127.0.0.1:{PORTS['webai_3']}/v1/models"),
    ("Cline Bridge",          "cline_bridge", PORTS["cline_bridge"], f"http://127.0.0.1:{PORTS['cline_bridge']}/health"),
    ("TTS Pool",              "tts_pool",     PORTS["tts_pool"],    f"http://127.0.0.1:{PORTS['tts_pool']}/health"),
]


def health_dashboard(once: bool = False) -> None:
    if not once:
        banner("Health Dashboard  [Ctrl+C de thoat]")

    def _render():
        print("\033[2J\033[H", end="")  # clear screen
        print(f"{BOLD}ERIS HEALTH DASHBOARD{RESET}  [{time.strftime('%H:%M:%S')}]")
        print("─" * 54)
        for label, _, port, url in SERVICES:
            listening = port_listening(port, timeout=0.5)
            api_ok    = http_ok(url, timeout=1.0) if listening else False
            if api_ok:
                dot = f"{GREEN}●{RESET}"
                status = "OK"
            elif listening:
                dot = f"{YELLOW}●{RESET}"
                status = "STARTING"
            else:
                dot = f"{RED}●{RESET}"
                status = "DOWN"
            print(f"  {dot} {label:<26} :{port}  {status}")
        print("─" * 54)
        print(f"  {CYAN}[Q]{RESET} Quit   {CYAN}[S]{RESET} Start all   {CYAN}[R]{RESET} Refresh")

    if once:
        _render()
        return

    # Live loop
    stop_event = threading.Event()
    def _loop():
        while not stop_event.is_set():
            _render()
            time.sleep(3)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    try:
        while True:
            ch = input().strip().lower()
            if ch == "q":
                break
            elif ch == "s":
                stop_event.set()
                t.join()
                start_all()
                stop_event.clear()
                t2 = threading.Thread(target=_loop, daemon=True)
                t2.start()
                t = t2
            elif ch == "r":
                _render()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()


# ── Main menu ─────────────────────────────────────────────────────────────────

def main_menu() -> None:
    state = load_state()

    def _status_tag(key: str) -> str:
        v = state.get(key)
        if not v:
            return f"{YELLOW}[NOT DONE]{RESET}"
        if isinstance(v, dict) and v.get("ts"):
            from datetime import datetime, timezone
            ts = datetime.fromtimestamp(v["ts"]).strftime("%m/%d %H:%M")
            return f"{GREEN}[Done {ts}]{RESET}"
        return f"{GREEN}[Done]{RESET}"

    while True:
        banner("ERIS SETUP & SERVICE MANAGER")
        print(f"  {BOLD}SETUP{RESET}")
        print(f"  [1] Check requirements          {_status_tag('requirements')}")
        print(f"  [2] Install dependencies        {_status_tag('dependencies')}")
        print(f"  [3] Setup DeepSeek accounts     {_status_tag('deepseek')}")
        print(f"  [4] Setup Gemini pool           {_status_tag('gemini_pool')}")
        print(f"  [5] Setup TTS (ElevenLabs)      {_status_tag('tts')}")
        print(f"  [6] Full build -> {str(BUILD_OUT)[:25]}")
        print()
        print(f"  {BOLD}SERVICES{RESET}")
        print(f"  [7] Start all services")
        print(f"  [8] Health dashboard (live)")
        print(f"  [9] Stop all")
        print()
        print(f"  [0] Exit")
        print()

        ch = input("Chon: ").strip()
        if ch == "1":   check_requirements()
        elif ch == "2": install_dependencies()
        elif ch == "3": setup_deepseek()
        elif ch == "4": setup_gemini_pool()
        elif ch == "5": setup_tts()
        elif ch == "6": full_build()
        elif ch == "7": start_all()
        elif ch == "8": health_dashboard()
        elif ch == "9": stop_all()
        elif ch == "0": break
        else:
            print(warn("Lua chon khong hop le"))
        pause()


if __name__ == "__main__":
    main_menu()
