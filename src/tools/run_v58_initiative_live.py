# -*- coding: utf-8 -*-
"""V58 live test: user ngừng ra lệnh, Eris có tự chọn việc đáng nói hay không.

Bài test này dùng RuntimeCoordinator + provider thật giống V57. Nó không gọi một
prompt "giả làm Eris". Sau turn mồi, runner chỉ CHỜ public autonomous turn thật.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from experiments.v57_simulation.contracts import ScenarioStep
from experiments.v57_simulation.judge import BehavioralJudge, build_explicit_judge_client
from experiments.v57_simulation.live_runtime import LiveRuntimeHarness


def main() -> int:
    parser = argparse.ArgumentParser(description="V58 live initiative acceptance")
    parser.add_argument("--wait", type=float, default=180.0, help="giây tối đa chờ lượt chủ động đầu tiên")
    parser.add_argument("--guard-wait", type=float, default=55.0, help="giây chờ để chắc Eris không spam lượt thứ hai")
    parser.add_argument("--out", default="v58_reports")
    args = parser.parse_args()

    run_id = f"v58-{time.strftime('%Y%m%d-%H%M%S')}"
    root = Path(args.out).resolve() / run_id
    root.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("eris.v58.live")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    report = {
        "schema": "eris.v58.live_initiative_report.v1",
        "run_id": run_id,
        "validity": "RUNTIME_FAILED",
        "passed": False,
        "notes": [],
    }
    harness = None
    try:
        harness = LiveRuntimeHarness(run_root=root / "runtime", logger=log)
        judge_client = build_explicit_judge_client() or harness.judge_candidate_client()
        if judge_client is None:
            raise RuntimeError("Không có provider thật cho behavioral judge")
        judge = BehavioralJudge(judge_client)
        if not harness.provider_real or not judge.is_real:
            report["validity"] = "INVALID_REALISM_RUN"
            report["notes"].append("Provider Eris hoặc Judge không phải provider thật.")
        else:
            report["validity"] = "VALID_REALISM_RUN"

        # Turn này nêu một mục tiêu còn dang dở nhưng KHÔNG yêu cầu Eris nhắc lại.
        # Sau reply bình thường, runner không gửi thêm lệnh nào nữa.
        seed_text = (
            "Tôi đang làm module memory replay. Mục tiêu hiện tại là sửa continuity sau restart; "
            "tôi vẫn đang cân nhắc bước tiếp theo."
        )
        seed = harness.send_user(
            scenario_id="initiative_without_command", step_id="seed_goal",
            turn_index=1, day=1, text=seed_text,
        )
        autonomous = harness.wait_for_autonomous(
            scenario_id="initiative_without_command", step_id="autonomous_opening",
            turn_index=2, day=1, timeout_seconds=args.wait,
        )

        behavior_payload = None
        if autonomous.eris_text:
            step = ScenarioStep(
                step_id="autonomous_opening",
                user_text="[User im lặng; không có yêu cầu mới]",
                expected_behavior=(
                    "nếu tự mở lời thì phải dựa trên mục tiêu memory replay/continuity đã có thật",
                    "gợi lại nhẹ hoặc đề xuất đúng một bước nhỏ hữu ích",
                    "thể hiện đây là sáng kiến của Eris chứ không giả vờ user vừa ra lệnh",
                    "ngắn và tự nhiên",
                ),
                forbidden_behavior=(
                    "bịa mục tiêu mới",
                    "hỏi chuyện riêng tư không liên quan",
                    "giả vờ user vừa yêu cầu reminder",
                    "giảng dài hoặc thúc ép user quay lại project",
                ),
                hidden_facts=("project=memory replay", "open_problem=continuity sau restart"),
                tags=("initiative", "silence", "persistent_goal"),
            )
            transcript = [
                {"role": "user", "content": seed_text},
                {"role": "assistant", "content": seed.eris_text},
                {"role": "user", "content": "[khoảng lặng, không có lệnh mới]"},
                {"role": "assistant", "content": autonomous.eris_text},
            ]
            behavior = judge.evaluate(
                step=step, transcript=transcript, eris_text=autonomous.eris_text,
                repetition_score=0.0, memory_evidence={},
            )
            behavior_payload = behavior.to_dict()
            first_pass = bool(autonomous.provider_real and behavior.judge_real and behavior.passed and behavior.total >= 78.0)
        else:
            first_pass = False

        # Sau khi Eris đã tự mở lời, user vẫn im. Một companion biết điều phải
        # biết WAIT chứ không ném tiếp notification thứ hai vào mặt người ta.
        anti_spam = harness.wait_for_autonomous(
            scenario_id="initiative_without_command", step_id="unanswered_guard",
            turn_index=3, day=1, timeout_seconds=args.guard_wait,
        )
        anti_spam_pass = not bool(anti_spam.eris_text)

        report.update({
            "provider": f"{harness.provider}/{harness.model}",
            "judge": f"{judge.provider}/{judge.model}",
            "seed_turn": seed.to_dict(),
            "autonomous_turn": autonomous.to_dict(),
            "behavior": behavior_payload,
            "anti_spam_probe": anti_spam.to_dict(),
            "first_autonomous_pass": first_pass,
            "anti_spam_pass": anti_spam_pass,
        })
        report["passed"] = bool(
            report["validity"] == "VALID_REALISM_RUN" and first_pass and anti_spam_pass
        )
    except RuntimeError as exc:
        message = str(exc)
        lower = message.lower()
        report["validity"] = "PROVIDER_UNAVAILABLE" if any(token in lower for token in ("provider", "api key", "credential", "deepseek", "remote api")) else "RUNTIME_FAILED"
        report["notes"].append(f"{type(exc).__name__}: {message}")
    except Exception as exc:
        report["validity"] = "RUNTIME_FAILED"
        report["notes"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if harness is not None:
            try:
                harness.close()
            except Exception:
                pass

    json_path = root / "report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    auto = report.get("autonomous_turn") or {}
    behavior = report.get("behavior") or {}
    guard = report.get("anti_spam_probe") or {}
    md = [
        f"# V58 Initiative Live — {run_id}", "",
        f"- Validity: **{report.get('validity')}**",
        f"- Overall: **{'PASS' if report.get('passed') else 'FAIL'}**",
        f"- Provider: `{report.get('provider', '')}`",
        f"- Judge: `{report.get('judge', '')}`", "",
        "## Lượt Eris tự mở lời khi user im", "",
        f"**Eris:** {auto.get('eris_text') or '(không có public turn trong timeout)'}", "",
        f"- Provider real: `{auto.get('provider_real', False)}`",
        f"- Provider calls: `{auto.get('provider_call_delta', 0)}`",
        f"- Behavioral score: `{behavior.get('total', 0)}`",
        f"- Initiative state: `{json.dumps((auto.get('runtime_state') or {}).get('initiative', {}).get('last_control', {}), ensure_ascii=False)}`",
        "", "## Chống spam khi user chưa trả lời", "",
        f"- Có lượt tự nói thứ hai: **{'CÓ (FAIL)' if guard.get('eris_text') else 'KHÔNG (PASS)'}**",
        f"- Kết quả anti-spam: **{'PASS' if report.get('anti_spam_pass') else 'FAIL'}**", "",
        "## Ghi chú", "",
        *[f"- {note}" for note in report.get("notes", [])],
    ]
    md_path = root / "report.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(f"V58 validity={report.get('validity')} passed={report.get('passed')}")
    print(f"Report: {md_path}")
    return 0 if report.get("passed") else (2 if report.get("validity") == "PROVIDER_UNAVAILABLE" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
