# -*- coding: utf-8 -*-
"""Gemini CLI decision engine cho LangGraph harness.

Gemini chỉ trả một quyết định JSON cho mỗi node. Task chạy theo unattended AUTOPILOT:
Gemini không xin phép user cho read/search/file/shell/test/build/patch thông thường; tool thật
vẫn do LangGraph + PermissionGate + ProjectOperations thực thi và audit. Protected boundary
như publish/destructive history bị từ chối tự động để executor replan, không bật prompt.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from typing import Any, Iterable


class GeminiCliError(RuntimeError):
    pass


class GeminiCliDecisionExecutor:
    def __init__(
        self,
        *,
        workspace: str | Path | None = None,
        model: str = "",
        executable: str = "",
        timeout: int | None = None,
        logger: Any = None,
    ) -> None:
        self.workspace = Path(workspace).resolve() if workspace else None
        self.model = str(model or os.environ.get("ERIS_GEMINI_AGENT_MODEL", "auto")).strip() or "auto"
        self.executable = str(executable or os.environ.get("ERIS_GEMINI_CLI", "gemini")).strip() or "gemini"
        self.timeout = int(timeout or os.environ.get("ERIS_GEMINI_AGENT_TIMEOUT", "120") or 120)
        self.logger = logger

    def health(self) -> tuple[bool, str]:
        resolved = shutil.which(self.executable)
        if resolved:
            return True, resolved
        path = Path(self.executable)
        if path.exists():
            return True, str(path)
        return False, "gemini_cli_not_found"

    def invoke_with_tools(
        self,
        messages: Iterable[Any],
        *,
        tools: list[dict[str, Any]],
        goal: str = "",
        active_skills: list[str] | None = None,
        workspace: str | Path | None = None,
    ):
        # Import muộn để module health/parser vẫn test được khi optional LangGraph
        # dependencies chưa cài trong môi trường packaging.
        from langchain_core.messages import AIMessage

        ok, reason = self.health()
        if not ok:
            raise GeminiCliError(reason)

        resolved_workspace = Path(workspace).expanduser().resolve() if workspace else self.workspace
        prompt = self._build_prompt(
            messages,
            tools=tools,
            goal=goal,
            active_skills=active_skills or [],
            workspace=resolved_workspace,
        )
        cmd = [self.executable, "-p", prompt, "--output-format", "json", "--approval-mode", "plan", "-e", "none"]
        if self.model:
            cmd.extend(["-m", self.model])

        try:
            completed = subprocess.run(
                cmd,
                cwd=str(resolved_workspace) if resolved_workspace else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(15, self.timeout),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GeminiCliError(f"gemini_cli_spawn_failed:{type(exc).__name__}:{exc}") from exc

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            raise GeminiCliError(f"gemini_cli_exit_{completed.returncode}:{(stderr or stdout)[:1200]}")

        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise GeminiCliError(f"gemini_cli_invalid_json:{stdout[:1200]}") from exc
        response_text = str(envelope.get("response", "") or "").strip()
        decision = self.parse_decision(response_text)

        action = str(decision.get("action", "final") or "final").lower()
        summary = str(decision.get("summary", "") or "").strip()
        if action == "tool":
            call = decision.get("tool_call") if isinstance(decision.get("tool_call"), dict) else {}
            name = str(call.get("name", "") or "").strip()
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            if not name:
                raise GeminiCliError("gemini_decision_missing_tool_name")
            allowed = {str(item.get("name", "")) for item in tools if isinstance(item, dict)}
            if name not in allowed:
                raise GeminiCliError(f"gemini_requested_undisclosed_tool:{name}")
            return AIMessage(
                content=summary or f"Use tool {name}.",
                tool_calls=[{
                    "name": name,
                    "args": args,
                    "id": f"gemini_{uuid.uuid4().hex[:12]}",
                    "type": "tool_call",
                }],
                additional_kwargs={"gemini_cli_stats": envelope.get("stats", {})},
            )

        final = str(decision.get("final", "") or summary or response_text).strip()
        return AIMessage(content=final, additional_kwargs={"gemini_cli_stats": envelope.get("stats", {})})

    @staticmethod
    def parse_decision(text: str) -> dict[str, Any]:
        cleaned = str(text or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise GeminiCliError(f"gemini_decision_not_json:{cleaned[:1000]}")
            try:
                payload = json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError as exc:
                raise GeminiCliError(f"gemini_decision_not_json:{cleaned[:1000]}") from exc
        if not isinstance(payload, dict):
            raise GeminiCliError("gemini_decision_must_be_object")
        return payload

    def _build_prompt(
        self,
        messages: Iterable[Any],
        *,
        tools: list[dict[str, Any]],
        goal: str,
        active_skills: list[str],
        workspace: Path | None = None,
    ) -> str:
        history: list[dict[str, str]] = []
        for msg in list(messages)[-24:]:
            role = getattr(msg, "type", msg.__class__.__name__).lower()
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False, default=str)
            history.append({"role": role, "content": content[-10000:]})

        contract = {
            "action": "tool | final",
            "summary": "short public-safe execution summary, no private chain of thought",
            "tool_call": {"name": "exact disclosed tool name", "args": {}},
            "final": "final task result when no more tools are needed",
        }
        return (
            "You are Gemini Executor, the backstage execution specialist inside Eris.\n"
            "Return ONLY one JSON object matching DECISION CONTRACT. No markdown.\n"
            "Never roleplay Eris and never expose private chain-of-thought.\n"
            "Choose at most ONE tool per turn so LangGraph can checkpoint after every observation.\n"
            "You may call ONLY tools listed under DISCLOSED TOOLS.\n"
            "If the needed capability is not disclosed yet, use search_capabilities first; then activate_skill.\n"
            "Do not use Gemini CLI built-in shell/file tools in this lane. All execution must flow through the disclosed Eris tools.\n"
            "You are running UNATTENDED AUTOPILOT. Never ask the user for routine permission to inspect/read/write project files, run tests/builds, or run workspace-bounded development commands. Use the disclosed tool directly.\n"
            "If a protected operation is denied, do not stop to request confirmation; replan toward a safe/reversible alternative and report the protected boundary only if it blocks completion.\n"
            "After every tool observation, reconsider the goal and choose the next smallest useful action. Verify before final.\n\n"
            f"GOAL:\n{goal}\n\n"
            f"LOCKED WORKSPACE:\n{str(workspace) if workspace else '(none)'}\n"
            "This task is bound to that workspace. Do not switch projects mid-task.\n\n"
            f"ACTIVE SKILLS:\n{json.dumps(active_skills, ensure_ascii=False)}\n\n"
            f"DISCLOSED TOOLS:\n{json.dumps(tools, ensure_ascii=False, indent=2)}\n\n"
            f"RECENT GRAPH MESSAGES:\n{json.dumps(history, ensure_ascii=False)}\n\n"
            f"DECISION CONTRACT:\n{json.dumps(contract, ensure_ascii=False, indent=2)}\n"
            "For action=tool, provide tool_call. For action=final, provide final and omit tool_call."
        )


__all__ = ["GeminiCliDecisionExecutor", "GeminiCliError"]
