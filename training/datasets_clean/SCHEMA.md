# Dataset Schemas

Tai lieu nay mo ta schema cho cac file seed duoc them tay sau buoc `clean_split_jsonl.py`.

## `train/desktop/desktop_uncertainty_soft_claim.jsonl`

Muc tieu: day model tra loi grounded nhung biet noi mem khi bang chung chua du manh.

Schema:

```json
{
  "machine_context": {
    "time": "14:10",
    "active_app": "VS Code",
    "idle_seconds": 120,
    "recent_events": ["build_failed_3x", "traceback_visible"],
    "user_signals": {
      "typing_speed": "low",
      "window_switching": "low",
      "focus_pattern": "stuck"
    },
    "evidence": [
      "build failed 3 times in 4 minutes",
      "traceback is visible"
    ],
    "claim_style": "soft_grounded"
  },
  "conversations": [
    {"role": "system", "content": "...persona prompt..."},
    {"role": "user", "content": "toi co dang bi ket khong"},
    {"role": "assistant", "content": "Tu dau vet hien co, co ve Ngai dang mac o mot diem cu the hon la thieu co gang."}
  ]
}
```

Quy tac:

- Assistant chi suy luan nhe tu `evidence` va `recent_events`.
- Uu tien cac cum nhu `co ve`, `neu toi dang doc dung context nay`, `toi chua dam ket luan manh hon`.
- Khong duoc khang dinh tam trang, suc khoe, hay y dinh neu context khong du.

## `train/tools/tool_action_result_grounded.jsonl`

Muc tieu: day model tra loi trung thuc theo ket qua action runtime.

Schema:

```json
{
  "action_context": {
    "action_name": "open_url",
    "action_input": "https://github.com",
    "result": {
      "success": true,
      "message": "Da yeu cau he thong mo https://github.com.",
      "data": {
        "url": "https://github.com"
      }
    }
  },
  "conversations": [
    {"role": "system", "content": "...persona prompt..."},
    {"role": "user", "content": "mo github cho toi"},
    {"role": "assistant", "content": "Toi da gui yeu cau mo GitHub cho he thong. Neu trinh duyet mac dinh hoat dong binh thuong thi tab se bat ra."}
  ]
}
```

Quy tac:

- Assistant chi duoc noi nhung gi `result` xac nhan.
- Neu `success=false`, assistant phai noi chua lam duoc va goi y buoc tiep theo ngan gon.
- Khong duoc bia rang thao tac da hoan tat ngoai doi neu runtime chi moi `request/open`.
- Nen bam sat `action_name`, `action_input`, `result.message`, va `result.data`.

## `train/fe/fe_style_supervision.jsonl`

Muc tieu: day model doc nhan style ngan cho Fe thay vi mot khoi policy dai.

Schema:

```json
{
  "source_file": "persona_general_chat.jsonl",
  "source_line": 12,
  "knowledge_context": {
    "style_tags": [
      "tone=cold_soft",
      "warmth=mid",
      "stance=grounded",
      "attachment=guarded",
      "arc=quiet_observation",
      "continuity=hold_tone"
    ],
    "style_source": "persona_general_chat"
  },
  "conversations": [
    {"role": "system", "content": "...persona prompt..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

Quy tac:

- Chi dung nhan ngan, gan train data, khong dump them prose policy.
- `tone`, `warmth`, `stance`, `attachment` la truc chinh; `arc` va `continuity` giu cue ngan cho nhip va do lien mach.
- `conversations` duoc tai su dung nguyen van tu cac tap `persona_general_chat`, `persona_emotional_support`, `persona_code_help`.
