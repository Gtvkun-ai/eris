# -*- coding: utf-8 -*-
"""eris_manager_server.py — REST API Server & HTML Control Panel cho Eris Manager.

Cung cấp Web Interface tại http://localhost:19999 để quản lý Eris Services (DeepSeek, Gemini, TTS, v.v.).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import subprocess
import shutil
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

_LOGGER = logging.getLogger("ErisManagerServer")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

PORTS = {
    "whale2api": 9090,
    "webai_1": 8081,
    "webai_2": 8082,
    "webai_3": 8083,
    "cline_bridge": 7832,
    "tts_pool": 9091,
}

_procs: list[subprocess.Popen] = []


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ERIS — Production Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b1120;
            --card-bg: #1e293b;
            --card-bg-glass: rgba(30, 41, 59, 0.7);
            --card-border: #334155;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent: #6366f1;
            --accent-hover: #4f46e5;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --info: #3b82f6;
            --radius: 16px;
            --blur: blur(12px);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            background-color: var(--bg-color);
            background-image: radial-gradient(circle at 15% 50%, rgba(99, 102, 241, 0.08), transparent 25%),
                              radial-gradient(circle at 85% 30%, rgba(16, 185, 129, 0.08), transparent 25%);
            color: var(--text-main);
            line-height: 1.5;
            min-height: 100vh;
        }

        .layout {
            display: flex;
            min-height: 100vh;
        }

        /* Sidebar */
        .sidebar {
            width: 260px;
            background: var(--card-bg-glass);
            backdrop-filter: var(--blur);
            border-right: 1px solid var(--card-border);
            padding: 24px 16px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 0 8px 24px 8px;
            margin-bottom: 12px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }

        .brand-logo {
            width: 36px;
            height: 36px;
            background: linear-gradient(135deg, #6366f1, #a855f7);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 18px;
            color: #fff;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
        }

        .brand-title {
            font-size: 18px;
            font-weight: 700;
            letter-spacing: -0.02em;
        }

        .nav-item {
            padding: 12px 16px;
            border-radius: 10px;
            color: var(--text-muted);
            font-weight: 500;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .nav-item:hover {
            background: rgba(255,255,255,0.05);
            color: var(--text-main);
        }

        .nav-item.active {
            background: var(--accent);
            color: #fff;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2);
        }

        /* Main Content */
        .content {
            flex: 1;
            padding: 40px;
            max-width: 1100px;
            margin: 0 auto;
        }

        .tab-pane {
            display: none;
            animation: fadeIn 0.3s ease;
        }
        .tab-pane.active {
            display: block;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 32px;
        }

        .title {
            font-size: 28px;
            font-weight: 700;
            letter-spacing: -0.02em;
        }
        
        .subtitle {
            color: var(--text-muted);
            font-size: 14px;
            margin-top: 4px;
        }

        /* Controls */
        .btn {
            background-color: var(--accent);
            color: #fff;
            border: none;
            padding: 10px 20px;
            font-size: 14px;
            font-weight: 600;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }

        .btn:hover {
            background-color: var(--accent-hover);
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
        }

        .btn-success { background-color: var(--success); }
        .btn-success:hover { background-color: #059669; box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3); }
        
        .btn-danger { background-color: var(--danger); }
        .btn-danger:hover { background-color: #dc2626; box-shadow: 0 4px 12px rgba(239, 68, 68, 0.3); }

        .btn-secondary {
            background-color: rgba(255, 255, 255, 0.05);
            color: var(--text-main);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .btn-secondary:hover {
            background-color: rgba(255, 255, 255, 0.1);
            box-shadow: none;
        }

        /* Cards */
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 24px;
        }

        .card {
            background: var(--card-bg-glass);
            backdrop-filter: var(--blur);
            border: 1px solid var(--card-border);
            border-radius: var(--radius);
            padding: 24px;
            transition: transform 0.2s ease;
        }

        .card:hover {
            transform: translateY(-2px);
            border-color: rgba(255,255,255,0.15);
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }

        .card-title {
            font-size: 16px;
            font-weight: 600;
        }

        /* Status Badge */
        .status {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 600;
        }
        .status-on { background: rgba(16, 185, 129, 0.15); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.3); }
        .status-off { background: rgba(239, 68, 68, 0.15); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.3); }

        /* Forms */
        .form-group {
            margin-bottom: 20px;
        }
        .form-label {
            display: block;
            font-size: 13px;
            font-weight: 500;
            color: var(--text-muted);
            margin-bottom: 8px;
        }
        .form-textarea {
            width: 100%;
            background-color: rgba(0,0,0,0.2);
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 12px 16px;
            color: var(--text-main);
            font-family: monospace;
            font-size: 13px;
            min-height: 150px;
            resize: vertical;
            transition: all 0.2s ease;
        }
        .form-textarea:focus {
            outline: none;
            border-color: var(--accent);
            background-color: rgba(0,0,0,0.4);
        }

        /* Table */
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            text-align: left;
            padding: 16px;
            border-bottom: 1px solid var(--card-border);
        }
        th {
            font-size: 12px;
            text-transform: uppercase;
            color: var(--text-muted);
            font-weight: 600;
            letter-spacing: 0.05em;
        }
        td {
            font-size: 14px;
        }
        
    </style>
</head>
<body>
    <div class="layout">
        <!-- Sidebar -->
        <div class="sidebar">
            <div class="brand">
                <div class="brand-logo">E</div>
                <div class="brand-title">Eris Manager</div>
            </div>
            
            <div class="nav-item active" onclick="switchTab('dashboard', this)">
                <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>
                Dashboard
            </div>
            <div class="nav-item" onclick="switchTab('deepseek', this)">
                <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"></path></svg>
                DeepSeek Accounts
            </div>
            <div class="nav-item" onclick="switchTab('gemini', this)">
                <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01"></path></svg>
                Gemini WebAI Pool
            </div>
        </div>

        <!-- Content -->
        <div class="content">
            <!-- DASHBOARD TAB -->
            <div id="tab-dashboard" class="tab-pane active">
                <div class="header">
                    <div>
                        <div class="title">System Dashboard</div>
                        <div class="subtitle">Live status of all Eris microservices</div>
                    </div>
                    <div style="display:flex; gap:12px;">
                        <button class="btn btn-secondary" onclick="stopAll()">⏹ Stop All</button>
                        <button class="btn btn-success" onclick="startAll()">▶ Start All</button>
                    </div>
                </div>

                <div class="grid">
                    <!-- Cards will be injected via JS -->
                </div>
            </div>

            <!-- DEEPSEEK TAB -->
            <div id="tab-deepseek" class="tab-pane">
                <div class="header">
                    <div>
                        <div class="title">DeepSeek Setup</div>
                        <div class="subtitle">Manage Whale2API accounts (Main Brain)</div>
                    </div>
                    <button class="btn" onclick="saveDeepSeek()">Save Changes</button>
                </div>
                <div class="card">
                    <div class="form-group">
                        <label class="form-label">accounts.csv (Format: email,password)</label>
                        <textarea id="ds-accounts" class="form-textarea" placeholder="email@example.com,password123"></textarea>
                    </div>
                    <p style="font-size:12px; color:var(--text-muted);">This file is loaded by Whale2API to automatically cycle DeepSeek tokens.</p>
                </div>
            </div>

            <!-- GEMINI TAB -->
            <div id="tab-gemini" class="tab-pane">
                <div class="header">
                    <div>
                        <div class="title">Gemini Playwright Pool</div>
                        <div class="subtitle">Manage WebAI-to-API session cookies (Code Executor)</div>
                    </div>
                    <div style="display:flex; gap:12px;">
                        <button class="btn btn-secondary" onclick="loadGeminiPool()">🔄 Refresh</button>
                        <button class="btn" onclick="addGeminiAccount()">➕ Add Account (Open Chrome)</button>
                    </div>
                </div>
                <div class="card" style="padding: 0;">
                    <table>
                        <thead>
                            <tr>
                                <th>Slot Name</th>
                                <th>Status</th>
                                <th style="text-align: right;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="gemini-tbody">
                            <!-- Injected via JS -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Tab Switching
        function switchTab(id, el) {
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            document.getElementById('tab-' + id).classList.add('active');
            
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            el.classList.add('active');

            if (id === 'deepseek') loadDeepSeek();
            if (id === 'gemini') loadGeminiPool();
        }

        // --- DASHBOARD API ---
        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                const grid = document.querySelector('.grid');
                grid.innerHTML = '';
                
                Object.keys(data).forEach(key => {
                    const svc = data[key];
                    const isUp = svc.up;
                    const statusClass = isUp ? 'status-on' : 'status-off';
                    const statusText = isUp ? '● ONLINE' : '● OFFLINE';
                    
                    grid.innerHTML += `
                        <div class="card">
                            <div class="card-header">
                                <div class="card-title">${svc.name}</div>
                                <div class="status ${statusClass}">${statusText}</div>
                            </div>
                            <div style="color:var(--text-muted); font-size:13px;">Port: ${svc.port}</div>
                        </div>
                    `;
                });
            } catch (err) {
                console.error("Status fetch failed", err);
            }
        }
        
        async function startAll() {
            await fetch('/api/control', { method: 'POST', body: JSON.stringify({action: 'start'}) });
            setTimeout(fetchStatus, 1500);
        }

        async function stopAll() {
            await fetch('/api/control', { method: 'POST', body: JSON.stringify({action: 'stop'}) });
            setTimeout(fetchStatus, 1000);
        }

        // --- DEEPSEEK API ---
        async function loadDeepSeek() {
            const res = await fetch('/api/deepseek');
            const data = await res.json();
            document.getElementById('ds-accounts').value = data.content;
        }

        async function saveDeepSeek() {
            const content = document.getElementById('ds-accounts').value;
            await fetch('/api/deepseek', { 
                method: 'POST', 
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({content: content}) 
            });
            alert('Saved successfully!');
        }

        // --- GEMINI API ---
        async function loadGeminiPool() {
            const res = await fetch('/api/gemini');
            const data = await res.json();
            const tbody = document.getElementById('gemini-tbody');
            tbody.innerHTML = '';
            
            if (data.slots.length === 0) {
                tbody.innerHTML = '<tr><td colspan="3" style="text-align:center; padding: 32px; color:var(--text-muted);">No Playwright accounts found. Click "Add Account" to configure one.</td></tr>';
                return;
            }

            data.slots.forEach(slot => {
                const status = slot.has_cookie ? '<span class="status status-on">● Valid Cookie</span>' : '<span class="status status-off">● Missing Cookie</span>';
                tbody.innerHTML += `
                    <tr>
                        <td style="font-weight:600;">${slot.name}</td>
                        <td>${status}</td>
                        <td style="text-align: right;">
                            <button class="btn btn-secondary" style="padding: 6px 12px; font-size:12px;" onclick="removeGemini('${slot.name}')">Remove</button>
                        </td>
                    </tr>
                `;
            });
        }

        async function addGeminiAccount() {
            alert('A Chrome window will open. Please log into Google and close the window to save the session.');
            await fetch('/api/gemini/add', { method: 'POST' });
            setTimeout(loadGeminiPool, 5000); // Check back later
        }

        async function removeGemini(slotName) {
            if (!confirm(`Delete ${slotName}?`)) return;
            await fetch('/api/gemini/remove', { 
                method: 'POST', 
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: slotName}) 
            });
            loadGeminiPool();
        }

        // Auto Refresh Dashboard
        fetchStatus();
        setInterval(() => {
            if (document.getElementById('tab-dashboard').classList.contains('active')) {
                fetchStatus();
            }
        }, 3000);
    </script>
</body>
</html>
"""


class ErisManagerHandler(BaseHTTPRequestHandler):

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "" or path == "/":
            self._send_html(HTML_TEMPLATE)
            return

        if path == "/api/status":
            res = {}
            for k, port in PORTS.items():
                up = False
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                        up = True
                except:
                    pass
                name_map = {
                    "whale2api": "Whale2API (Brain)",
                    "webai_1": "Gemini WebAI #1",
                    "webai_2": "Gemini WebAI #2",
                    "webai_3": "Gemini WebAI #3",
                    "cline_bridge": "Cline Bridge",
                    "tts_pool": "TTS Pool (ElevenLabs)"
                }
                res[k] = {"name": name_map.get(k, k), "port": port, "up": up}
            self._send_json(res)
            return

        if path == "/api/deepseek":
            acc_file = ROOT / "tools" / "whale2api" / "accounts.csv"
            content = ""
            if acc_file.exists():
                content = acc_file.read_text(encoding="utf-8")
            self._send_json({"content": content})
            return

        if path == "/api/gemini":
            auth_base = ROOT / "tools" / "WebAI-to-API" / "runtime"
            slots = []
            if auth_base.exists():
                for d in sorted(auth_base.glob("auth-*")):
                    if d.is_dir():
                        slots.append({
                            "name": d.name,
                            "has_cookie": (d / "gemini.json").exists()
                        })
            self._send_json({"slots": slots})
            return

        self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b""
        payload = {}
        if post_data:
            try:
                payload = json.loads(post_data.decode("utf-8"))
            except Exception:
                pass

        if path == "/api/deepseek":
            acc_file = ROOT / "tools" / "whale2api" / "accounts.csv"
            acc_file.parent.mkdir(parents=True, exist_ok=True)
            acc_file.write_text(payload.get("content", ""), encoding="utf-8")
            self._send_json({"success": True})
            return

        if path == "/api/gemini/add":
            def _worker():
                auth_base = ROOT / "tools" / "WebAI-to-API" / "runtime"
                next_slot = 1
                while (auth_base / f"auth-{next_slot}").exists():
                    next_slot += 1
                auth_dir = auth_base / f"auth-{next_slot}"
                auth_dir.mkdir(parents=True, exist_ok=True)
                
                webai_dir = ROOT / "tools" / "WebAI-to-API"
                verify_py = webai_dir / "verify_login.py"
                env = {**os.environ, "PLAYWRIGHT_AUTH_STATE_DIR": str(auth_dir)}
                subprocess.run([str(VENV_PY), str(verify_py)], cwd=webai_dir, env=env)
            
            threading.Thread(target=_worker, daemon=True).start()
            self._send_json({"success": True})
            return

        if path == "/api/gemini/remove":
            name = payload.get("name")
            if name and name.startswith("auth-"):
                target = ROOT / "tools" / "WebAI-to-API" / "runtime" / name
                if target.exists():
                    shutil.rmtree(target)
            self._send_json({"success": True})
            return

        if path == "/api/control":
            action = payload.get("action")
            global _procs
            if action == "stop":
                for p in _procs:
                    try:
                        p.terminate()
                    except:
                        pass
                _procs.clear()
            elif action == "start":
                # Whale2API
                whale_dir = ROOT / "tools" / "whale2api"
                exe = whale_dir / "whale2api.exe"
                if exe.exists():
                    p = subprocess.Popen([str(exe)], cwd=whale_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    _procs.append(p)
                
                # Gemini
                webai_dir = ROOT / "tools" / "WebAI-to-API"
                auth_base = webai_dir / "runtime"
                slots = sorted(d for d in auth_base.glob("auth-*") if (d / "gemini.json").exists())
                port = 8081
                for slot_dir in slots:
                    env = {**os.environ, "PLAYWRIGHT_AUTH_STATE_DIR": str(slot_dir), "PLAYWRIGHT_HEADLESS": "true"}
                    p = subprocess.Popen([str(VENV_PY), "src/run.py", "--host", "127.0.0.1", "--port", str(port)], cwd=webai_dir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    _procs.append(p)
                    port += 1
                
                # Cline
                bridge_js = ROOT / "cline-bridge" / "dist" / "bridge.js"
                if bridge_js.exists():
                    p = subprocess.Popen(["node", str(bridge_js)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    _procs.append(p)

            self._send_json({"success": True})
            return

        self._send_json({"error": "Not Found"}, 404)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    port_arg = 19999
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port_arg = int(sys.argv[1])

    server = ThreadingHTTPServer(("127.0.0.1", port_arg), ErisManagerHandler)
    print(f"=== ERIS Manager Web UI ===")
    print(f"Listening at http://127.0.0.1:{port_arg}")
    server.serve_forever()
