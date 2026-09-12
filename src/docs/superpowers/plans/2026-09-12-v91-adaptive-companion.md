# ERIS V91 Adaptive Companion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tách Eris Desktop khỏi Eris Code thật sự và thêm Adaptive Companion Brain dùng conversation/life-horizon/mentor evidence để điều chỉnh cách Eris đồng hành, dạy và trêu.

**Architecture:** Eris Code trở thành GitPilot client thuần VS Code, không biết Desktop. Eris Desktop thêm `AdaptiveCompanionService` độc lập, persistent nhẹ và được inject vào discourse context mỗi user turn; EngineeringMentor chỉ là một nguồn evidence kỹ thuật tùy chọn.

**Tech Stack:** Python 3.12+/pytest, TypeScript/VS Code API, JSON persistence.

**Spec:** `docs/superpowers/specs/2026-09-12-v91-adaptive-companion-design.md`

## Global Constraints

- Extension phải chạy đầy đủ khi Eris Desktop tắt/không cài.
- Desktop không được cần extension để companion/mentor hoạt động.
- Không lưu raw source/terminal telemetry trong Adaptive Companion state.
- Self-report không được tăng mastery kỹ thuật.
- Mỉa/trêu chỉ là cue; relationship/affective layer có quyền cuối.
- Vietnamese comments/docs cho boundary mới.

---

### Task 1: Adaptive Companion core

**Files:**
- Create: `runtime/adaptive_companion.py`
- Test: `tests/test_adaptive_companion_v91.py`

**Interfaces:**
- Produces: `AdaptiveCompanionService.observe_user_turn(user_text, turn_id="", now=None)`
- Produces: `AdaptiveCompanionService.prompt_context(user_text, turn_id="", now=None)`
- Consumes optional: EngineeringMentor snapshot and LifeHorizon snapshot through owner.

- [ ] Viết test fail cho explicit learning/activity persistence.
- [ ] Chạy test để xác nhận RED.
- [ ] Implement model/state tối thiểu.
- [ ] Chạy GREEN.
- [ ] Viết test fail cho fast delegation không lecture, explicit learning có teaching, strong skill → peer, teasing cue không phải authority.
- [ ] Implement policy tối thiểu và chạy GREEN.

### Task 2: Desktop integration không phụ thuộc extension

**Files:**
- Modify: `runtime/coordinator.py`
- Modify: `runtime/ai_orchestrated/orchestrator.py`
- Test: `tests/test_adaptive_companion_integration_v91.py`

**Interfaces:**
- Coordinator exposes `adaptive_companion_service`.
- Orchestrator injects `ADAPTIVE_COMPANION_V91` into discourse context.

- [ ] Viết test fail xác nhận service init độc lập observer.
- [ ] Viết test fail xác nhận prompt context được inject cho foreground turn.
- [ ] Implement integration.
- [ ] Chạy GREEN.

### Task 3: Retire V90 observer startup on Desktop

**Files:**
- Modify: `runtime/coordinator.py`
- Test: `tests/test_eris_code_decoupling_v91.py`

**Interfaces:**
- `eris_code_observer_link` và `coding_observation_service` vẫn tồn tại attribute để compatibility nhưng luôn `None` ở normal V91 startup.

- [ ] Viết static/behavior test fail cho observer startup block.
- [ ] Remove listener initialization khỏi normal startup.
- [ ] Chạy GREEN.

### Task 4: Eris Code tách sạch Desktop

**Files:**
- Modify: `vscode-extension/src/extension.ts`
- Modify: `vscode-extension/src/gitPilotClient.ts`
- Modify: `vscode-extension/src/selfTest.ts`
- Modify: `vscode-extension/package.json`
- Modify: `vscode-extension/package-lock.json`
- Modify: `vscode-extension/CHANGELOG.md`
- Modify: `vscode-extension/docs/ARCHITECTURE.md`
- Delete via manifest: `vscode-extension/src/erisObserverBridge.ts`
- Delete via manifest: `vscode-extension/src/companionWorkspaceObserver.ts`
- Delete via manifest: `vscode-extension/src/codingObservation.ts`
- Test: `tests/test_eris_code_decoupling_v91.py`

**Interfaces:**
- `GitPilotClient(context, runtime, terminalObserver)` only.
- No `erisCode.erisLink.*` contribution.

- [ ] Viết static test fail cho Eris Link refs.
- [ ] Remove bridge/observation dependencies khỏi activation/client/self-test.
- [ ] Bump extension `0.22.0`.
- [ ] `npm run typecheck` + compile.

### Task 5: Mentor delivery alignment

**Files:**
- Modify: `runtime/companion_mentor_orchestrator.py`
- Modify: `runtime/engineering_mentor.py`
- Test: `tests/test_companion_mentor_integration_v84.py`
- Test: `tests/test_adaptive_companion_v91.py`

**Interfaces:**
- Existing mentor API unchanged.
- Companion-first ordinary discussion; supervisor no longer depends on GitPilot flow to feel alive.

- [ ] Add regression tests for companion-first and no forced supervisor from absent extension.
- [ ] Adjust prompt boundaries/comments to V91 independent model.
- [ ] Run mentor suite.

### Task 6: Vietnamese release docs + verification + FILECHANGEONLY

**Files:**
- Create: `V91_CHANGESET_VI.txt`
- Create: `V91_TEST_STATUS_VI.txt`
- Create: `docs/V91_ADAPTIVE_COMPANION_VI.md`
- Create package root: `V91_APPLY_README_VI.txt`, `V91_DELETE_FILES_VI.txt`

- [ ] Run V91 tests.
- [ ] Run mentor regression V80→V91.
- [ ] Run VS Code typecheck/compile.
- [ ] Package only modified/new files plus deletion manifest.
