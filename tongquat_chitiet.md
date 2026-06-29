# ERIS — TỔNG QUÁT CHI TIẾT, BẢN VIẾT LẠI TỪ REPO HIỆN TẠI

> Mục tiêu: tài liệu file-to-file để debug và hiểu runtime ERIS. Bản này được dựng lại từ repo thật trên đĩa (`c:\Users\Gtvkun\Documents\GitHub\eris`), không dựa vào trí nhớ mơ hồ hay README màu mè. Phần Python parse từ `src/`, phần body parse từ `body/`.

## Phạm vi và giới hạn trung thực

- Nguồn Python: AST parse từ `src/` trong repo thật (`c:\Users\Gtvkun\Documents\GitHub\eris\src`). Bố cục `src/` khớp bảng snapshot bên dưới (`actions/ core/ cortex/ domain/ llm/ memory/ parser_grounding/ runtime/ telemetry/ transport/ vision.py`).
- Nguồn C# body: đọc trực tiếp 10 file trong `body/` của repo thật và **đã audit lại** (xem ghi chú ở Phần 1).
- Lưu ý lịch sử: bản doc gốc được sinh từ `src/src.zip` (chỉ chứa phần Python). Vì `body/`, `tests/`, Godot scene nằm **ngang hàng** với `src/` chứ không nằm trong zip, bản cũ tưởng nhầm là chúng "không tồn tại". Thực tế repo thật **có đủ** `body/` (C#), `tests/`, `project.godot`, `body/UdpListener.tscn`, `asset/`, `config/`.
- Tổng Python đã parse bằng AST: **351 file**, khoảng **158,398 LOC**. Các file cache `.pyc`, `__pycache__` và `.hypothesis` bị bỏ qua.
- Tài liệu này ưu tiên debug thực dụng: file nào sở hữu state, file nào gọi ai, lỗi nào nên soi ở đâu. Không cố biến mọi module thành tiểu thuyết.

## 0. Snapshot repo

| Gốc | Python files | LOC |
|---|---:|---:|
| `actions/` | 4 | 1245 |
| `core/` | 4 | 2509 |
| `cortex/` | 175 | 75155 |
| `domain/` | 2 | 117 |
| `llm/` | 12 | 7039 |
| `memory/` | 59 | 17458 |
| `parser_grounding/` | 3 | 2245 |
| `runtime/` | 80 | 50631 |
| `telemetry/` | 4 | 966 |
| `transport/` | 2 | 281 |
| `src/` (root files) | 6 | 752 |

### File state/runtime trong `memory_core/`

> Đã đầy lên đáng kể so với bản trước (chỉ có 7 file). Bây giờ là kho state đầy đủ của runtime.

- `memory_core/active_state_snapshot.json` — keys=version, updated_at, current_goal, current_goal_confidence, session_arc, active_project, active_task, relation_state, affect_state, homeostatic_state, working_threads, open_questions, self_continuity, metadata
- `memory_core/affective_residue_memory.json` — keys=version, items
- `memory_core/agent_mind.json` — keys=beliefs, habits, last_feedback_events, preferences, schema_version, updated_at
- `memory_core/anchor_journal.jsonl` — jsonl_lines=4409
- `memory_core/anchor_state.json` — keys=schema_version, updated_at, state
- `memory_core/depth_flags.json` — keys=ERIS_EMOTIONAL_CONSEQUENCE, ERIS_DEVELOPMENT_GROWTH_ENABLED, ERIS_INTERIOR_SURFACE_NONANCHORED, ERIS_TOM_ADVISOR, ERIS_MEANING_REAL_EMBEDDINGS, ERIS_PRIVATE_MIND_API_ENABLED
- `memory_core/episodic_memory.json` — keys=version, items
- `memory_core/epistemic_v2.json` — keys=schema_version, mode, created_at, updated_at, legacy_imported, beliefs, episodes, projections, procedural_policies, calibration, pending_hypotheses, learning_log
- `memory_core/event_ledger.json` — keys=version, records
- `memory_core/inner_diary.json` — keys=updated_at, last_tick_at, current, inner_diary, history
- `memory_core/memory_candidate.json` — keys=version, kind, updated_at, items
- `memory_core/private_concerns.json` — keys=version, saved_at, concerns
- `memory_core/private_life_state.json` — keys=version, updated_at, habitat, attachments, projects, anchors, daily, taste, solitude, rituals, errands, events
- `memory_core/procedural_memory.json` — keys=version, items
- `memory_core/relational_memory.json` — keys=version, items
- `memory_core/repair_memory.json` — keys=version, items
- `memory_core/semantic_memory.json` — keys=version, kind, updated_at, items
- `memory_core/thought_stream.jsonl` — jsonl_lines=79
- `memory_core/user_model.json` — keys=schema_version, updated_at, version, beliefs, history


# 1. Body Godot/C# — ĐÃ AUDIT TỪ `body/` TRONG REPO THẬT

> Ghi chú trung thực: repo thật **có** thư mục `body/` (**10 file `.cs`** + `UdpListener.tscn`). Đã đọc trực tiếp và đối chiếu chữ ký từng class/method bằng AST C#. Kết quả: mô tả bên dưới **khớp** mã nguồn thật. Kích thước file tại thời điểm audit gần nhất: `BodyAudioController.cs` 4.4KB, `ErisProcessManager.cs` 11.2KB, `LocalBodyAutonomy.cs` 21.3KB, `MotionController.cs` 20.7KB, `RunLogger.cs` 3.8KB, `UdpDecisionParser.cs` 11.5KB, `UdpListener.AnchorPanel.cs` 37.0KB, `UdpListener.DepthPanel.cs` 22.8KB, `UdpListener.TutorPanel.cs` 14.2KB, `UdpListener.cs` 197.5KB. **Hai file partial mới so với bản trước:** `UdpListener.DepthPanel.cs` (tab "Chiều Sâu") và `UdpListener.TutorPanel.cs` (tab "Gia Sư" — Eris hỏi Gemini). Không còn là "legacy snapshot" — đây là bản đồ debug C# đã xác minh.

# PHẦN C# / GODOT BODY — ĐÃ XÁC MINH  [body/]
================================================================================
Phía "thân xác". Không suy nghĩ; chỉ vẽ, phát animation/âm thanh, nhận Decision
qua UDP 4242, gửi event/chat lên runtime qua UDP 4243, và tự đi lại khi rảnh.

--------------------------------------------------------------------------------
## body/UdpListener.cs
--------------------------------------------------------------------------------
**Vai trò:** Node chính của scene (`Node2D`, partial class). Bind UDP 4242, dựng
toàn bộ UI/panel (chat, emotion, private mind, anchor, context menu), spawn
vision.py, mỗi frame bước motion + đọc packet + áp dụng Decision. Các phần panel tách
sang file partial: "anchor" ở `UdpListener.AnchorPanel.cs`, "chiều sâu" ở
`UdpListener.DepthPanel.cs`, "gia sư" ở `UdpListener.TutorPanel.cs`.

**Class/struct phụ trong file:**
- `EmotionRowView` : view 1 dòng cảm xúc (Row/Title/Note/FillClip/Fill/Percent).
- `PrivateMindDiaryItem` : 1 mục nhật ký nội tâm (Text + Badge).
- `PrivateMindDiarySection` : 1 nhóm mục (Title + Items).
- `enum ClimbPhase` : pha leo (None/GoingToWall/Up/Top/TopHold/Down) — bản sao cục bộ.

**Field/biến trạng thái quan trọng:**
- `_udp` (PacketPeerUdp, port 4242) : socket nhận Decision từ cortex.
- `_chatSend` (PacketPeerUdp -> 127.0.0.1:4243) : socket gửi event/chat lên cortex.
- `_monika`/`_body`/`_label`/`_bubble` : sprite, thân vật lý, label thoại, bong bóng.
- `_motion` (MotionController), `_bodyAutonomy` (LocalBodyAutonomy), `_audio`
  (BodyAudioController), `_processes` (ErisProcessManager), `_decisionParser`.
- `[Export]` config: PythonExecutable, VisionScriptPath, AutoStartVision,
  EnableRemoteCognitionApi, DefaultRemoteApiKey, RemoteApiProvider/BaseUrl/ModelName,
  cụm Desktop Overlay (transparent/borderless/always-on-top/passthrough),
  cụm Autonomous Idle Movement, ThrowVelocityScale...
- `_validAnimations`, `_animAliases`, `_soundMap`, `_loopingSoundAnims` : bảng
  hợp lệ hoá tên animation và map âm thanh (đồng bộ với UdpDecisionParser/BodyAudioController).
- `_latestEmotionDebug`, `_latestPrivateMindDebugJson` : data thô gần nhất cho panel.

**Các hàm/method (đầy đủ):**
- `_Ready()` — khởi tạo: RunLogger.Initialize, cấu hình cửa sổ overlay, bind UDP 4242,
  lấy các node con, dựng UI (context menu, emotion panel, private mind panel, anchor
  panel, chat panel), nối sự kiện nút, connect `_chatSend` tới 4243, đặt nhân vật sát
  đáy, tạo MotionController/LocalBodyAutonomy/BodyAudioController/ErisProcessManager,
  nếu AutoStartVision thì spawn vision.py.
- `ConfigureDesktopOverlayWindow()` — bật cờ AlwaysOnTop/Borderless/Transparent, phủ
  toàn màn hình, bật mouse passthrough mặc định.
- `UpdateMousePassthrough()` — mỗi frame: nếu đang mở UI/kéo thì cả cửa sổ chặn chuột;
  nếu không thì chỉ "mở khoá" vùng quanh nhân vật để desktop sau vẫn click được.
- `_ExitTree()` — dừng vision.py, đóng UDP, đóng `_chatSend`, RunLogger.Shutdown.
- `_Process(double delta)` — vòng mỗi frame: nếu đang kéo thì clamp vị trí; ngược lại
  `_motion.Step` + `UpdateLocalBodyAutonomy`; áp visual state; clamp bong bóng; cập nhật
  passthrough; refresh decor private mind nếu mở; auto-hide chat panel; ĐỌC packet UDP
  -> `ParseAndApply(raw)`.
- `_Input(InputEvent)` — xử lý kéo panel, kéo nhân vật, chuột phải mở/đóng context menu
  & panel, chuột trái đóng panel khi click ra ngoài.
- `_UnhandledInput(InputEvent)` — bắt thả chuột kết thúc kéo, đóng context menu khi click.
- `MarkChatActivity()` — đánh dấu mốc thời gian hoạt động chat (cho auto-hide).
- `UpdateChatPanelAutoHide()` — tự ẩn chat panel sau `ChatAutoHideSeconds` nếu không gõ.
- `ToggleChatPanel()` / `CloseChatPanel()` — mở/đóng panel chat; mở thì gửi "chat_start",
  đóng thì xoá input + gửi "chat_end".
- `OnContextChatPressed()` / `OnContextTouchPressed()` / `OnContextForceSpeakPressed()` /
  `OnContextEmotionPressed()` / `OnContextPrivateMindPressed()` / `OnContextExitPressed()`
  — handler các nút context menu (chat / bật chế độ kéo / "force_speak" / mở emotion /
  mở private mind / thoát app).
- `ToggleEmotionPanel()` / `ShowEmotionPanel()` / `CloseEmotionPanel()` — vòng đời panel cảm xúc.
- `TogglePrivateMindPanel()` / `ShowPrivateMindPanel()` / `ClosePrivateMindPanel()` — vòng đời panel inner diary.
- `BuildChatPanelUi()` / `UpdateChatPanelLayout()` — dựng/định vị khung chat (texture 9-slice).
- `ConfigureChatActionButton(...)` — style nút Gửi/X của chat.
- `BuildCharacterContextMenuUi()` — dựng menu chuột phải (các nút Chat/Touch/ForceSpeak/Emotion/PrivateMind/Anchor "Mô Hình Ngài"/Depth "Chiều Sâu"/Exit/Close).
- `ShowCharacterContextMenu(pos)` / `CloseCharacterContextMenu()` — hiện/ẩn menu tại vị trí chuột.
- `BuildEmotionPanelUi()` / `RefreshEmotionPanel()` — dựng & đổ data panel cảm xúc từ `_latestEmotionDebug`.
- `BuildPrivateMindPanelUi()` / `RefreshPrivateMindPanel()` — dựng & đổ data panel inner diary từ `_latestPrivateMindDebugJson`.
- `UpdatePrivateMindDecorLayout()` / `UpdatePrivateMindScrollDecor()` — cập nhật trang trí/scrollbar panel private mind mỗi frame khi mở.
- `MakePanelDraggable(panel)` / `UpdatePanelDrag()` — cho kéo-thả panel nổi.
- `OnSendPressed()` — gửi text trong ô chat xuống cortex (UDP 4243), xoá input.
- `SendChatSignal(string)` — gửi 1 signal/text thô lên 4243 (chat_start/chat_end/force_speak/text).
- `ParseAndApply(string raw)` — gọi `_decisionParser.Parse(raw)`, áp text/should_speak vào
  bong bóng, đẩy MotionCommand vào `_motion`, nạp body_bias vào `_bodyAutonomy`, lưu
  emotion_debug & private_mind_digest, bắt block `depth` (`TryCaptureDepthBlock`) và sự
  kiện `tutor_event` (`TryHandleTutorEvent`), log debug_trace/parse_mode.
- `UpdateLocalBodyAutonomy(delta)` — gọi `_bodyAutonomy.TryUpdate(...)`; nếu có decision thì
  áp MotionCommand (giữ throttle remote cooldown).
- `BeginDrag/UpdateDrag/EndDrag/ClampDraggedPosition/IsMouseOverCharacter/IsMouseOverControl`
  — bộ xử lý kéo nhân vật bằng chuột + ném (tính vận tốc khi thả).
- `OnBounceAnimationFinished()` — chuyển tiếp animation khi va tường xong (gọi `_motion.NotifyAnimationFinished`).
- `PlaySoundForAnimation(anim)` — callback cho MotionController phát âm thanh qua `_audio`.
- `ClampBubbleToScreen()` — giữ bong bóng thoại trong màn hình.
- `StartVisionProcess()` / `StopVisionProcess()` — gọi ErisProcessManager start/stop vision.py (dựng ErisServiceConfig từ các [Export]).
- `UpdateServiceButtons()` — callback cập nhật nhãn nút khi tiến trình vision đổi trạng thái.
- (Các helper UI nhỏ: tạo label/texture/style cho panel — dựng giao diện thuần.)

**Liên kết:** Nhận Decision JSON từ `src/runtime/coordinator.py` qua UDP 4242 ->
`UdpDecisionParser.Parse`. Gửi event/chat lên `src/runtime` qua UDP 4243. Spawn
`src/vision.py` qua `ErisProcessManager`. Điều khiển `MotionController`, `LocalBodyAutonomy`,
`BodyAudioController`.

--------------------------------------------------------------------------------
## body/UdpListener.AnchorPanel.cs  (partial class UdpListener)
--------------------------------------------------------------------------------
**Vai trò:** Panel "MÔ HÌNH NGÀI" (Theory of User) — bảng debug trục neo hiện sinh.
Ăn data thật từ block `anchor` trong `private_mind_digest`. 3 tab (Mô Hình / Trục Tối
/ Sổ Trung Thực) + rail "Tác Giả" (công tắc shadow/deception/strict_grounding/safe_mode).

**Class phụ:** `AnchorData` — bản parse của block anchor (switches, significance,
attachment+history, dread, shadow+gate, user_model+beliefs, deception records).

**Field:** `_anchorPanel`, `_anchorTab`, `_anchorTabButtons`, `_anchorContent`,
`_anchorRail`, `_anchorData`; bảng màu Anchor*; `AnchorFacetNames`, `AnchorRegisterNames`.

**Các hàm/method (đầy đủ):**
- `OnContextAnchorPressed()` — ghi tương tác user, toggle panel.
- `ToggleAnchorPanel()` / `ShowAnchorPanel()` / `CloseAnchorPanel()` — vòng đời panel.
- `BuildAnchorPanelUi()` — dựng chrome tĩnh (header, divider, tab bar, content scroll, rail).
- `AddAnchorTabButton(bar, index, text)` — thêm 1 nút tab, bấm -> đổi `_anchorTab` + refresh.
- `StyleAnchorTabs()` — tô style tab active/inactive.
- `RefreshAnchorPanel()` — parse data rồi render.
- `RenderAnchor()` — clear & dựng lại tab đang chọn + rail.
- `SendAnchorControl(action, value)` — gửi JSON `{type:anchor_control,...}` xuống Python (4243).
- `OnAnchorSwitchPressed(action, newValue)` — gửi lệnh + update lạc quan UI (shadow/deception/strict/safe_mode).
- `ParseAnchorData()` — parse `_latestPrivateMindDebugJson` block "anchor" thành AnchorData.
- `BuildTabModel(d)` — tab 0: Hồ Sơ Ngài (beliefs) -> Ý Nghĩa (irreplaceability) -> Gắn Bó (long-arc + sparkline).
- `BuildTabDarkAxis(d)` — tab 1: cổng AND (attachment/abandonment/dread), register, intensity, dread/abandonment.
- `BuildTabLedger(d)` — tab 2: biên lai "đã nói ↔ sự thật nội tại" (deception records).
- `BuildAuthorRail(d)` — rail công tắc Tác Giả + badge safe mode + nút "về an toàn" + "reset all".
- `AnchorRailSwitch(label, action, on, onIsSafe)` — 1 công tắc bấm-đảo, gửi lệnh xuống Python.
- `AnchorRailAction(label, color, onPressed)` — nút hành động (safe_mode/reset_all).
- Helper UI tái dùng: `AnchorClear`, `AnchorCardStyle`, `AnchorCard`, `AnchorColumn`,
  `AnchorFlowArrow`, `AnchorMetricRow`, `AnchorBeliefCard`, `AnchorRoleChips`,
  `AnchorBadge`, `AnchorWrap`, `AnchorEmpty`, `AnchorSparkline`, `AnchorGateFuse`,
  và các đọc JSON an toàn `AnBool/AnFloat/AnInt/AnStr`, `ReadGate(...)`.

**Liên kết:** Đọc `_latestPrivateMindDebugJson` (set ở `ParseAndApply`). Gửi lệnh
điều khiển trục neo xuống `src/runtime/private_mind_*` qua UDP 4243.

--------------------------------------------------------------------------------
## body/UdpListener.DepthPanel.cs  (partial class UdpListener)  [MỚI]
--------------------------------------------------------------------------------
**Vai trò:** Tab "CHIỀU SÂU" — dashboard nội tâm SỐNG, chỉ-xem (read-only). Nền là
ảnh scrapbook baked sẵn `asset/Resource/ChieuSauKhung.png` (1040×622), code chỉ thả
chữ live vào 8 ô đã chừa trống theo toạ độ TỈ LỆ + 1 nút ✕ trong suốt đè lên ✕ vẽ
sẵn. Sáu cờ chiều-sâu (N1–N3) tự bật lúc khởi động (`coordinator.bootstrap_defaults`);
panel không toggle cờ. Dùng font Mali nhúng (OFL), fallback SystemFont.

**Field:** `_depthPanel`, `_contextDepthButton`, `_latestDepthJson`; bộ bar
`_depthWantBar/_depthSuppressBar/_depthAllowBar` (+ value labels); `_depthStanceLabel`,
`_depthTomLabel`, `_depthHeaderLabel`, `_depthAffectLabel`, `_depthContextLabel`; các
VBox body `_depthN2Body`, `_depthInteriorityBody`, `_depthLogBody`; `_depthFlagChips`
(dict chip cờ); `_depthFontRegular/_depthFontBold`. Hằng số toạ độ ô `Slot*` (Rect2 tỉ
lệ) + palette `Depth*`.

**Các hàm/method (đầy đủ):**
- `OnContextDepthPressed()` — ghi tương tác user, toggle panel.
- `ToggleDepthPanel()` / `ShowDepthPanel()` — vòng đời panel (canh giữa màn hình, refresh).
- `BuildDepthPanelUi()` — dựng nền ảnh (StyleBoxEmpty + TextureRect; thiếu ảnh -> nền
  hồng phẳng), nút đóng trong suốt, header động, 8 ô card + dải "CỘNG TÁC" (chip cờ pastel).
- `DepthPillStyle(on)` (static) — style pill cờ bật/tắt.
- `Mk/MkBold(text,size,color)` — label thường/đậm gắn font Mali.
- `LoadDepthFont(fileName)` / `ApplyDepthFontTheme()` — nạp font Mali nhúng (resource ->
  bytes -> SystemFont), gắn theme cho panel.
- `PlaceBySlot(ctrl, slot)` / `NewSlot(slot)` / `NewCardSlot(slot, heading, icon)` — đặt
  control theo Rect2 tỉ lệ; card = [icon + tiêu đề] + gạch nhấn + body.
- `DepthBarRow(parent, label, fill, out valueLabel)` — 1 hàng thanh tiến trình + nhãn giá trị.
- `DepthLine(text, color, size)` — 1 dòng chữ wrap.
- `TryCaptureDepthBlock(raw)` — bắt block `depth` trong JSON Decision, lưu `_latestDepthJson`,
  refresh nếu panel mở.
- `RefreshDepthPanel()` — parse `_latestDepthJson` block `depth` và đổ vào UI: identity
  (model/channel/cờ on-total/alive), flags (chip), affect (valence/arousal/stance),
  expression (want/suppress/allowed + stance), n2 (axes delta + sentence + attachment),
  interiority (themes + recurrence + pressure), tom_read_rich (text + confidence),
  signal_log (tối đa 5 dòng), context (tags).

**Liên kết:** Đọc block `depth` trong Decision JSON từ runtime (qua UDP 4242, set ở
`ParseAndApply`/`_Process`). Cờ chiều-sâu khớp `memory_core/depth_flags.json`. Thuần xem.

--------------------------------------------------------------------------------
## body/UdpListener.TutorPanel.cs  (partial class UdpListener)  [MỚI]
--------------------------------------------------------------------------------
**Vai trò:** Tab "GIA SƯ" — thẻ nhỏ nổi góc phải-trên báo việc Eris đi hỏi trợ lý Gemini.
Hiển thị tiêu đề + trạng thái động (đang nghĩ/mở/gõ/đọc/ghi nhớ với dấu chấm chạy), câu
hỏi gõ ra từng chữ (typewriter), rồi câu trả lời khi xong, tự ẩn sau `TutorPanelAutoHideSeconds`.
Data đến qua UDP 4242 với `parse_mode="tutor_event"`. Thuần trang trí: `MouseFilter=Ignore`
toàn panel (click xuyên qua) trừ nút ✕ — để user không bấm bậy vào lúc Eris đang hỏi AI.

**Field:** `_tutorPanel`, `_tutorRoot`, `_tutorTitleLabel`, `_tutorStatusLabel`,
`_tutorHideButton`, `_tutorQuestionLabel`/`_tutorAnswerLabel` (RichTextLabel),
`_tutorTypeTween`/`_tutorDotsTween`/`_tutorPulseTween`, `_tutorHideAtMs`, `_tutorEpisodeId`;
palette `Tutor*`; `[Export] TutorPanelAutoHideSeconds = 14f`.

**Các hàm/method (đầy đủ):**
- `BuildTutorPanelUi()` — dựng panel (style hồng bo góc + shadow), header (tiêu đề + status
  + nút ✕), divider, 2 RichTextLabel câu hỏi/trả lời; gắn vào `CanvasLayer/Control`.
- `MakeTutorLabel(...)` / `MakeTutorRich(color)` — label/RichTextLabel chuẩn (mouse-ignore).
- `TryHandleTutorEvent(raw)` — trả true nếu `raw` là `parse_mode="tutor_event"`; parse block
  `tutor` (stage/question/answer/claims/fail_reason) rồi gọi `DriveTutorPanel`.
- `DriveTutorPanel(stage, question, answer, claims, failReason)` — máy trạng thái theo stage:
  forming/opening/asking/reading/digesting/done/failed (gõ chữ, đổi status, schedule hide).
- `TutorFailText(reason)` (static) — map mã lỗi -> câu thoại tiếng Việt (captcha_or_expired,
  timeout, empty_answer, formulation_failed, gate_rejected*, selector_miss, network_error...).
- `SetTutorQuestion(question)` / `TypeTutorText(label, text)` — đặt/gõ chữ kiểu typewriter
  qua VisibleCharacters tween.
- `FitTutorPanelHeight()` — tự dãn chiều cao panel theo nội dung (clamp trong màn hình).
- `KillTutorTypeTween()` — huỷ tween gõ chữ.
- `StartTutorDots(baseText)` / `StopTutorDots(finalText)` — animation "đang …" dấu chấm chạy.
- `StartTutorPulse()` / `StopTutorPulse()` — "thở" mờ-tỏ toàn panel khi đang hỏi Gemini.
- `HideTutorPanel()` / `ShowTutorPanel()` — vòng đời panel (đặt góc phải-trên).
- `ScheduleTutorHide()` / `UpdateTutorPanelAutoHide()` — hẹn & thực thi auto-hide mỗi frame.
- `TutorStr/TutorInt(obj, key)` (static) — đọc JSON an toàn.

**Liên kết:** Nhận `tutor_event` từ runtime (qua UDP 4242, kiểm trong `ParseAndApply`/
`_Process` trước khi parse Decision thường). Khớp `TutorStageEmitter` phía Python.

--------------------------------------------------------------------------------
## body/UdpDecisionParser.cs

--------------------------------------------------------------------------------
**Vai trò:** Parse chuỗi JSON Decision (từ cortex) thành `UdpDecisionPayload` mà body
hiểu được. Strip ```code fence```, validate/alias tên animation, suy ra motion_intent.

**Class/struct:** `UdpDecisionPayload` (text, ParsedJson, HasTextField, ShouldSpeak,
HasRemoteMotion, HasExplicitMotion, MotionCommand, BodyBias, ParseMode, DebugTrace,
ParserTrace, EmotionDebug, PrivateMindDebugJson...); `EmotionDebugItem`; `EmotionDebug`.

**Các hàm/method (đầy đủ):**
- `UdpDecisionParser.Parse(string raw)` — hàm chính: strip fence, JsonDocument.Parse;
  đọc body_bias/emotion_debug/private_mind_digest; đọc text/should_speak/animation/
  direction/next_animation/bounce_action/debug_trace/parser_trace/parse_mode/target_x/
  motion_intent/motion_facing/motion_target_x; nếu parse lỗi -> coi raw là plain text
  hoặc "Loi duong truyen tin hieu"; chuẩn hoá animation; suy motion_intent; trả payload.
- `EmotionDebug.TryFromJson(root, out debug)` — đọc `emotion_debug` (summary + items) từ JSON.
- `EmotionDebug.ReadString(root, name)` (private static) — đọc string an toàn.
- `TryReadPrivateMindDebugJson(root, out json)` (private static) — lấy block
  `private_mind_digest` (top-level hoặc nằm trong emotion_debug.private_mind) dạng raw JSON.
- `StripCodeFence(cleaned)` (private static) — bỏ ```...``` quanh JSON do LLM sinh.
- `NormalizeAnimationName(animation, facingDir, allowEmpty)` (private static) — alias +
  validate; tên sai -> fallback "stand"/"stand_walk".
- `InferMotionIntent(animation, nextAnimation, facingDir, targetX)` (private static) —
  suy intent (climb_to_top/climb_loop/drop/walk_to/walk/face) từ animation + target.
- `HasRemoteMotionCommand(...)` (private static) — true nếu Decision chứa lệnh di chuyển thật.

**Liên kết:** Gọi bởi `UdpListener.ParseAndApply`. Tạo `MotionCommand`/`BodyBias`
dùng cho `MotionController`/`LocalBodyAutonomy`.

--------------------------------------------------------------------------------
## body/MotionController.cs
--------------------------------------------------------------------------------
**Vai trò:** Vật lý & state máy di chuyển nhân vật: đi bộ, rơi/gravity, ném (throw)
+ bám tường (cling), leo tường (climb state machine), quay mặt, va tường.

**Struct/enum:** `MotionCommand` (Intent, PoseAnimation, NextAnimation, BounceAction,
FacingDir, TargetX, ImpulseX/Y, ClingChance); `enum ClimbPhase`.

**Field:** `_moveDir`, `_facingDir`, `_isWalking`, `_currentAction`, `_velocityX/Y`,
`_isFalling`, `_spriteHalfSize`, `_targetX`, `_nextAction`, `_bounceAction`,
`_clingArmedSeconds`, `_clingAttempted`, `_climbPhase`, `_climbUpWallX/_climbDownWallX/_climbTopTargetX`.

**Property:** `CurrentAction`, `IsWalking`, `IsClimbing`, `IsTopPerched`, `IsThrown`, `IsBusy`.

**Các hàm/method (đầy đủ):**
- `MotionController(playSound, moveSpeed, gravity, climbSpeed)` — ctor, lưu callback âm thanh + hằng số.
- `Configure(spriteHalfSize, bubbleBasePos)` — set kích thước sprite + vị trí gốc bong bóng.
- `PlaceOnFloor(ref pos, screenSize)` — đặt nhân vật sát đáy, reset vận tốc.
- `Step(ref pos, screenSize, delta)` — LÕI: nếu đang leo -> `UpdateClimbMovement`; ngược lại
  áp gravity, decay vận tốc ngang (armed cling giữ đà lâu hơn), chạm đáy/đỉnh, va tường;
  nếu walking thì đi tới target hoặc va tường gọi `HandleWallHit`.
- `ApplyCommand(command, currentPos, screenSize)` — dịch MotionCommand thành state: switch theo
  intent (walk_to/walk/climb_to_top/climb_loop/drop/throw/face/pose).
- `ApplyVisualState(monika, bubble, bodyPosition, screenSize)` — chọn animation hiển thị + lật
  hướng theo phase leo/rơi/đi/đứng.
- `NotifyAnimationFinished()` — khi animation bounce xong thì chuyển về đi bộ tiếp.
- `BeginWalk(targetX, nextAction, bounceAction)` (private) — bắt đầu đi (có/không target).
- `BeginClimb(currentPos, screenSize)` (private) — chọn tường gần, set up/down wall + top target, vào phase GoingToWall.
- `ApplyStaticAction(action, facingDir)` (private) — đặt pose tĩnh + reset di chuyển.
- `HandleWallHit(nextWalkDir)` (private) — xử lý va tường khi đi: bounce_action / next_action / đổi hướng.
- `CancelClimbState()` (private) — huỷ trạng thái leo + cling.
- `HandleAirborneWallContact(ref pos, screenSize)` (private) — khi đang bay chạm tường: dừng ngang;
  nếu armed cling thì roll xác suất bám -> chuyển sang leo lên đỉnh.
- `UpdateClimbMovement(ref pos, screenSize, delta)` (private) — state machine leo: GoingToWall ->
  Up -> Top -> (TopHold | Down) -> None.
- `ResolveAbsoluteTargetX(targetX, screenSize)` (private) — đổi fraction [0..1] thành X tuyệt đối clamp trong màn hình.
- `NormalizePose(animation, allowEmpty)` (private static) — trim, mặc định "stand".
- `TopFacingScale(bodyPosition, screenSize)` (private) — hướng mặt khi đang trên đỉnh.
- `ApplyHorizontalFacing(monika, bubble, facingDir)` (private) — set hướng + flip.
- `ApplyFlip(monika, bubble, scaleX)` (private) — lật sprite + bong bóng theo scaleX.
- `BuildClingMarker(clingChance)` (private static) — mã hoá xác suất bám thành chuỗi "cling:0.xxx".
- `ParseClingChance(value)` (private static) — đọc lại xác suất bám từ chuỗi marker.

**Liên kết:** Nhận `MotionCommand` từ `UdpListener` (qua UdpDecisionParser + LocalBodyAutonomy).
Gọi callback `PlaySoundForAnimation` -> `BodyAudioController`.

--------------------------------------------------------------------------------
## body/LocalBodyAutonomy.cs
--------------------------------------------------------------------------------
**Vai trò:** Để body TỰ đi lại/leo/ngồi/rút lui khi idle, KHÔNG cần cortex. Mô phỏng
needs (continuity/meaning/solitude/quiet_attachment/overload) + tension trôi theo thời
gian, rồi chọn action mỗi 5–10s. Nhận `body_bias` từ cortex để lệch xu hướng.

**Class/struct:** `BodyBias` (continuity_anxiety, curiosity, overload, solitude,
focus_kind, preferred_anchor; có `Blend`, `TryFromJson`); `BodyAutonomyContext`
(snapshot vị trí/màn hình/action/busy/chat/perched); `BodyAutonomyDecision`
(ActionName + MotionCommand + OptionalSpeech); `LocalBodyAutonomy` (+ nested Needs, Tension).

**Các hàm/method (đầy đủ):**
- `BodyBias.Blend(incoming, amount)` — trộn bias cũ với mới (lerp) để cognition ảnh hưởng từ từ.
- `BodyBias.TryFromJson(root, out bias)` — parse block body_bias từ JSON Decision.
- `BodyBias.TryReadFloat/TryReadString/Lerp/NormalizeFocusKind/NormalizeAnchor` (private static) — helper parse/clamp/chuẩn hoá.
- `LocalBodyAutonomy()` — ctor, random tick cooldown đầu.
- `ApplyCognitionBias(bias)` — trộn bias mới (amount 0.45), reset cognition gap, đổi anchor ưa thích.
- `RecordUserInteraction()` — user vừa tương tác: reset idle, tăng quiet_attachment + continuity.
- `RecordRoughHandling()` — bị "ném"/kéo mạnh: tăng overload + solitude.
- `TryUpdate(delta, context, out decision)` — vòng cập nhật: decay cooldown, evolve needs,
  đếm tick; tới hạn & không busy & pose ngắt được -> build tension -> ChooseAction -> BuildDecision.
- `EvolveNeeds(delta, context)` (private) — trôi needs theo idle/code-focus/chat/cognition gap.
- `BuildTension()` (private) — tính Dissolution/NoiseIdentity/SilentErasure từ needs + idle.
- `ChooseAction(context, tension)` (private) — chấm điểm các action (ReturnToAnchor/ReadQuietly/
  ObserveCode/ClimbWall/Withdraw/DormantSit/QuietObserve) + xử lý khi đang trên đỉnh.
- `BuildDecision(action, context)` (private) — map tên action -> BodyAutonomyDecision (MotionCommand).
- `Climb(action, context)` / `DropFromCeiling(...)` / `WalkOrSettle(...)` / `Pose(...)` (private) — dựng MotionCommand cụ thể.
- `ChooseClimbSide(context)` (private) — chọn tường trái/phải để leo.
- `CanInterruptPose(context)` (private static) — pose hiện tại có ngắt được không.
- `AnchorX(anchor)` / `FacingTowardCenter(context)` (private) — toạ độ anchor & hướng quay vào giữa.
- `StartCooldowns/DecayCooldowns/CooldownPenalty/RepetitionPressure` (private) — quản lý cooldown action + phạt lặp.
- `WindowScore/NormalizeX/Smooth/RandomRange` (private static/instance) — helper toán.

**Liên kết:** Gọi bởi `UdpListener.UpdateLocalBodyAutonomy`. Sinh `MotionCommand` cho `MotionController`.
Nhận `BodyBias` parse từ Decision (UdpDecisionParser).

--------------------------------------------------------------------------------
## body/BodyAudioController.cs
--------------------------------------------------------------------------------
**Vai trò:** Map tên animation -> file .wav và phát; tự loop âm thanh cho nhóm
animation lặp (stand_walk/sleep/hop/climb).

**Field:** `_player` (AudioStreamPlayer), `_rng`, `_currentActionProvider`,
`LoopingSoundAnimations`, `SoundMap`.

**Các hàm/method (đầy đủ):**
- `Attach(owner, currentActionProvider)` — gắn AudioStreamPlayer vào scene, nối sự kiện Finished.
- `PlayForAnimation(animation)` — random 1 file trong SoundMap của animation, load + play.
- `OnFinished()` (private) — khi phát xong: nếu action hiện tại thuộc nhóm loop thì phát tiếp.

**Liên kết:** Gọi bởi `UdpListener.PlaySoundForAnimation` (callback từ MotionController).

--------------------------------------------------------------------------------
## body/ErisProcessManager.cs
--------------------------------------------------------------------------------
**Vai trò:** Spawn/kill tiến trình runtime Python (`vision.py` hoặc runtime đóng gói
PyInstaller), nạp `config/secrets.json` + env vào tiến trình con, lọc/log stdout/stderr.

**Class:** `ErisServiceConfig` (PythonExecutable, VisionScriptPath, EnableRemoteCognitionApi,
DefaultRemoteApiKey, RemoteApiProvider/BaseUrl/ModelName); `ErisProcessManager`.

**Các hàm/method (đầy đủ):**
- `ErisProcessManager(onStatusChanged)` — ctor, lưu callback đổi trạng thái.
- `StartVision(config)` — ưu tiên runtime đóng gói `runtime/eris-runtime.exe`; nếu không có thì
  chạy `python src/vision.py`; set env (PYTHONUTF8, ERIS_PROJECT_ROOT, ERIS_REMOTE_*, key...),
  redirect stdout/stderr, đăng ký handler log + Exited.
- `StopVision()` — kill tiến trình vision (qua StopProcess).
- `ToggleVision(config)` — đang chạy thì stop, không thì start.
- `StopAll()` — dừng tất cả (hiện chỉ vision).
- `SetEnvIfAbsent(startInfo, key, value)` (private static) — chỉ set env nếu chưa có (secrets ưu tiên).
- `PopulateVisionEnvironment(startInfo, config)` (private) — nạp secrets.json + env runtime + key.
- `LoadProjectSecretsEnvironment()` (private) — đọc config/secrets.json thành dict env.
- `AddSecretsFromObject(source, values)` (private) — gom các cặp string từ 1 object JSON.
- `HandleVisionStderr(data)` (private) — phân loại stderr (traceback/exception/connection) để log đúng mức.
- `StopProcess(ref process, label, processName)` (private) — kill + dispose tiến trình an toàn.
- `GetProjectRoot()` / `GetRuntimeBaseDir()` / `BundledRuntimeFileName()` / `ResolveProjectPath()` (private static) — phân giải thư mục gốc editor/export.
- `ShouldLogVisionOutput(line)` / `ShouldLogVisionStderr(line)` (private static) — lọc dòng log đáng ghi.

**Liên kết:** Gọi bởi `UdpListener.StartVisionProcess/StopVisionProcess`. Spawn `src/vision.py`.
Đọc `config/secrets.json`. Ghi log qua `RunLogger`.

--------------------------------------------------------------------------------
## body/RunLogger.cs
--------------------------------------------------------------------------------
**Vai trò:** Logger tĩnh ghi mirror output ra `logs/eris_run_<timestamp>.txt` (vì bản
export double-click không có console). Thread-safe.

**Các hàm/method (đầy đủ):**
- `Initialize()` — tạo file log mới (1 lần), ghi header; an toàn gọi nhiều lần.
- `Log(message)` — ghi INFO ra Godot Output + file.
- `LogErr(message)` — ghi ERR ra Godot Output + file.
- `Shutdown()` — flush + đóng file (gọi ở `_ExitTree`).
- `WriteLine(level, message)` (private) — ghi 1 dòng có timestamp (lock).
- `WriteHeader()` (private) — ghi header (thời gian, exe path, OS...).
- `GetBaseDir()` (private static) — editor -> res://, export -> thư mục .exe.

**Liên kết:** Dùng khắp `UdpListener`/`ErisProcessManager`.


================================================================================

# 2. Bản đồ runtime end-to-end

```text
Godot/body hoặc client ngoài
  -> UDP event/chat 4243
vision.py
  -> build LlmService, MemoryCognitionCore/MemoryKernel, telemetry, parser, action router
RuntimeCoordinator
  -> chat_cycle / autonomous_cycle / force_speak_cycle
  -> source_grounding + frame_builder + cognitive_pipeline/shadow
  -> cortex: Se, salience, working_memory, meaning, ToM, internal_state, relation, speech_core
  -> private_mind_daemon / private_life_daemon / thought_stream / subconscious
  -> surface_arbiter + low_level_speech_policy
  -> llm.service + parser_grounding + post_generation_filters
  -> Decision.to_payload + body_bias + private_mind_digest
  -> UDP decision 4242
```

Luồng đúng của ERIS không phải `input -> prompt -> output`. Luồng đúng là: evidence có nguồn -> chọn attention -> bóp context vào working memory/workspace -> hiểu nghĩa -> permission/grounding -> quyết định nói/im/body/action -> quan sát hậu quả -> commit memory/repair. Đúng, hơi nhiều lớp, nhưng ít nhất nó không giả vờ cá vàng là triết gia.

# 3. Bảng debug nhanh

## ERIS không nói dù user vừa chat
1. runtime/chat_cycle.py: kiểm tra source_grounding preempt, repeat guard, memory recall intercept.
2. runtime/speech_pipeline.py và cortex/speech_core.py: intent có bị đổi sang silence/body_only không.
3. runtime/post_generation_filters.py: câu bị chặn vì leak/grounding/tone không.
4. llm/service.py: provider có trả empty/protocol_fallback không.

## Autonomous im lâu, không có cảm giác sống
1. runtime/contextual_autonomy_loop.py + autonomous_wake_governor.py: wake level có bị giữ ở observe/think không.
2. cortex/thought_stream.py + spontaneous_life.py: thought pressure có sinh impulse không.
3. cortex/surface_arbiter.py + low_level_speech_policy.py: impulse có bị rate-limit/body_only/reject không.
4. runtime/model_budget_policy.py: main/vision/daydream có đang bị resource guard không.

## Force speak vẫn rỗng hoặc generic
1. runtime/force_speak_cycle.py: event force_speak có vào đúng path không.
2. runtime/frame_builder.py: disturbance requested_presence có được inject thought_stream không.
3. runtime/presence_controller.py: cue có seed/anchor đủ cụ thể không.
4. cortex/micro_policy.py + surface_arbiter.py: generic/no-anchor line có bị reject đúng không.

## ERIS claim nhìn thấy màn hình/file dù không có bằng chứng
1. runtime/source_grounding.py: primary_source/missing_evidence/forbidden_assumptions.
2. runtime/chat_cycle.py: screen capture/facts có thật sự attach không.
3. parser_grounding/decision.py và cortex/ti.py: perception/capability guard.
4. runtime/post_generation_filters.py: chat_grounding_guard cuối.

## Private mind có log nhưng hành vi tương lai không đổi
1. runtime/private_mind_loop.py: tick có fragments/judgment không.
2. cortex/private_mind/concern_store.py: concern có được merge/lưu không.
3. cortex/private_mind/state_mutation_bus.py: mutation target có apply vào agenda/bias/repair/inquiry không.
4. runtime/coordinator.py: _apply_private_mind_tick_result có đẩy state vào runtime không.

## Inner diary/private panel trống hoặc mất dữ liệu
1. runtime/private_mind_daemon.py và inner_diary_persistence.py: digest/persist có chạy không.
2. transport/udp.py: payload có vượt 63KB và bị compact stage mạnh không.
3. runtime/coordinator.py: _private_mind_digest_for_payload/_compact_private_mind_digest_for_udp.
4. memory_core/inner_diary.json: state file có history/current không.

## Memory nhớ sai hoặc hỏi memory rơi xuống LLM thường
1. memory/memory_commit_policy.py: intake có ghi fact không.
2. memory/memory_kernel.py: answer/build_packet có trả result không.
3. runtime/memory_recall_adapter.py: intercept_permission/confidence/ambiguity.
4. memory_query_compiler/executor/recall_policy: IR và surface answer.

## LLM trả JSON cụt, leak schema hoặc CoT
1. llm/service.py: _complete_decision, _repair_decision_json, _coerce_malformed_decision_payload.
2. parser_grounding/decision.py: hard repair/non-json semantic fallback.
3. runtime/post_generation_filters.py: protocol/prompt leak guard.
4. domain/decision.py: payload cuối có text sạch không.

## Body/motion không đúng
1. domain/decision.py: motion_intent/motion_target_x/motion_facing được resolve chưa.
2. transport/udp.py: payload gửi được không.
3. Body/motion: kiểm tra `body/MotionController.cs` (state machine đi/leo/ném) và `body/UdpDecisionParser.cs` (parse `motion_intent`/`motion_target_x`/`motion_facing`). Lỗi visual/animation nằm ở `MotionController.ApplyVisualState` + `body/UdpListener.tscn`.

# 4. Các file trọng yếu cần đọc trước

- `vision.py` — Entry point Python. Boot order: cấu hình logging, giữ `.vision.lock`, dựng `RemoteModelProcessManager`, `LlmService`, `UdpTransport`, `MemoryCognitionCore`, parser, telemetry, Ni/Ti/Fe/action, rồi khởi tạo `RuntimeCoordinator` và chạy `run_loop()`.
- `runtime/coordinator.py` — Orchestrator trung tâm. Kế thừa nhiều mixin để chia chat/autonomous/force_speak/presence/frame/speech/memory/filter/shadow. Trong `__init__` nó nối gần như toàn bộ engine: salience, working memory, meaning, personality, appraisal, affect, relation, internal state, self model, session ritual, speech core, action planner, source grounding, micro policy, body bias, signal buffer, observer, vision compressor, internal agenda, endogenous drive, wake governor, private mind/life daemon, thought stream, subconscious loop, memory kernel và model budget policy.
- `runtime/cognitive_cycle.py` — Lifecycle/tick/cycle owner cho runtime.
- `runtime/chat_cycle.py` — Đường xử lý user chat. Nó gom burst, build source grounding report, xử lý screen request, memory recall deterministic, repeat guard, previous-public-turn repair, rồi đẩy qua speech/LLM/parser/guard. Debug khi hỏi trực tiếp mà trả vòng vo, memory recall không intercept, hoặc user gửi nhiều tin ngắn bị xử lý vụn.
- `runtime/autonomous_cycle.py` — Đường idle/autonomous. Nó poll input, bucket idle/window spread, update vision facts, track autonomous signature, chọn speech intent và quyết định skip/hold theo ambient silence, evidence, resource pressure. Debug khi ERIS tự nói quá nhiều hoặc im quá lâu.
- `runtime/force_speak_cycle.py` — Lifecycle/tick/cycle owner cho runtime.
- `runtime/frame_builder.py` — Module `frame builder` trong package `runtime`.
- `runtime/presence_controller.py` — Cổng presence/micro/reengagement. Nó build `MicroPresenceCue`, dùng `SurfaceSeedCompiler`, gọi `SurfaceArbiter`, tạo body-only hoặc speech decision, có cooldown và chính sách re-engagement. Debug khi force_speak/micro presence rỗng, body-only bị tính nhầm là nói, hoặc low-level surface không nổi.
- `runtime/speech_pipeline.py` — Module `speech pipeline` trong package `runtime`.
- `runtime/source_grounding.py` — Bộ phân loại nguồn trước khi trả lời: user_text, memory, file mention, current_screen/live_vision, web/action/runtime. Nó tạo missing_evidence, forbidden_assumptions, confidence cap và preempt decision. Debug khi ERIS claim thấy màn hình/file/memory hiện tại dù không có evidence.
- `runtime/post_generation_filters.py` — Hàng rào cuối trước public output. Chặn prompt leak, debug leak, memory haunting, unsupported current-screen claim, over-mindreading, register sai và micro-line xấu. Debug khi câu đúng bị flatten hoặc câu rác lọt ra body.
- `runtime/model_budget_policy.py` — Scheduler/gatekeeper model. Quản tier main/subconscious/vision/sensory, lease, queue, resource snapshot, cooldown, active heavy lock. Debug khi model chạy chồng, local GGUF/vision/daydream tranh tài nguyên, hoặc request kẹt queue.
- `runtime/autonomous_wake_governor.py` — Trọng tài mức thức: sleep, observe_only, think_only, micro_presence, call_vision_compressor, wake_main_cognition. Tính external pressure, internal drive, permission, speech value, interrupt cost và budget. Debug khi đáng gọi main nhưng bị degrade xuống micro/think hoặc silence debt không đủ kéo surface.
- `runtime/contextual_autonomy_loop.py` — src/runtime/contextual_autonomy_loop.py ====================================== Adaptive heartbeat cho 3-tier autonomy. Module này gom các mảnh: - UserContextStream (tầng cảm giác / 0.6B + rules) - EndogenousDriveEngine (...
- `runtime/private_mind_loop.py` — Private mind 5 phase: ConcernStore, EvidenceDossierBuilder, MiniEvaluatorPipeline, GemmaInnerSynthesizer, StateMutationBus, SurfaceValve. Không tự nói; nó tạo mutation/state/surface impulse nếu được phép. Debug khi ERIS có thought/private concern nhưng hành vi tương lai không đổi.
- `runtime/private_mind_daemon.py` — Lifecycle owner của PrivateMindLoop. Giữ tick digest, queues, surface impulses, outcome. Debug khi private_mind_loop chạy rời rạc, digest mất hoặc inner diary không persist.
- `runtime/private_mind_model_adapter.py` — runtime/private_mind_model_adapter.py ===================================== Adapter API cho private mind: - evaluate_fragment(evaluator_name, dossier) - synthesize_judgment(dossier, fragments) Adapter này ưu tiên dùng `l...
- `runtime/private_life_daemon.py` — Lifecycle owner của PrivateLifeCore. Đẩy habitat/project/rhythm/solitude vào runtime, sinh digest và surface seed. Debug khi đời sống riêng không cập nhật hoặc vẫn bị neo 100% vào user.
- `runtime/state_commit_service.py` — Module `state commit service` trong package `runtime`.
- `runtime/state_committer.py` — src/runtime/state_committer.py ================================ StateCommitter là cổng commit state/memory của ERIS. Nguyên tắc chính: - Không module runtime nào được ghi thẳng vào memory. - Module chỉ được tạo StateComm...
- `runtime/memory_recall_adapter.py` — Adapter nối runtime với engine/model/store khác trong runtime.
- `runtime/memory_semantic_parser_adapter.py` — Adapter nối runtime với engine/model/store khác trong runtime.
- `runtime/subconscious_loop.py` — Runtime adapter cho subconscious blackboard/synthesizer. Phase 0 dựng ThoughtFragment/Blackboard/Synthesizer. Phase 1-4 thêm worker nội tâm nền. Phase 5 thêm MetaAudit có quyền dọn Blackboard. Phase 6 thêm BeliefMutation...
- `runtime/subconscious_model_adapter.py` — Adapter gọi model/API riêng cho Lane 3 subconscious synthesis. Lane 3 không sinh lời thoại public. Nó chỉ lập một "biên bản phiên toà nội tâm": - các mảnh nào đang tranh nhau ý nghĩa, - bên công tố/biện hộ nhìn thấy gì,...
- `runtime/daydream_model_adapter.py` — Adapter nối runtime với engine/model/store khác trong runtime.
- `runtime/sensory_model_adapter.py` — Adapter nối runtime với engine/model/store khác trong runtime.
- `runtime/thought_model_adapter.py` — runtime/thought_model_adapter.py ================================ Compatibility adapter cho ThoughtStream model review. Một số bản coordinator đã import RuntimeThoughtModelAdapter nhưng zip hiện tại không có file này. Th...
- `runtime/body_bias.py` — Module `body bias` trong package `runtime`.
- `runtime/outcome_observer.py` — Module `outcome observer` trong package `runtime`.
- `runtime/cognitive_pipeline.py` — runtime/cognitive_pipeline.py Xương sống Phase 1 của ERIS V3. Mục tiêu của file này là biến mớ module rời rạc thành MỘT đường chạy có thật: RawSignal -> EvidenceItem (EvidenceNormalizer) # Phase: contract -> CognitiveFra...
- `runtime/cognitive_budget.py` — src/runtime/cognitive_budget.py ================================ Bộ chọn Cognitive Budget cho ERIS. Mục tiêu: Chọn đường chạy nhận thức cho mỗi CognitiveFrame: - fast - normal - deep - reflection Vì sao cần file này: Att...
- `runtime/shadow_pipeline.py` — runtime/shadow_pipeline.py Shadow mode cho CognitivePipeline (V3). Ý tưởng: Runtime thật vẫn chạy frame cũ (cortex/contracts.CognitiveFrame) qua coordinator/chat_cycle như thường. Song song đó, ta dựng RawSignal từ ĐÚNG...
- `runtime/signal_buffer.py` — SignalBuffer cho Background Observer. Nhiệm vụ: - Giữ một cửa sổ snapshot gần đây. - Tính diff giữa snapshot mới và snapshot trước. - Ước lượng novelty/repetition mà không gọi model. - Làm cổng chống spam model.
- `runtime/public_turn_ledger.py` — Module `public turn ledger` trong package `runtime`.
- `runtime/session_turn_ledger.py` — Module `session turn ledger` trong package `runtime`.
- `runtime/inner_diary_persistence.py` — runtime/inner_diary_persistence.py ================================== Ghi `inner_diary` (và một ít ngữ cảnh từ private mind digest) ra đĩa dưới `memory_core/inner_diary.json`. Triết lý: - Inner diary là trạng thái nội tâ...
- `runtime/voice_policy.py` — voice_policy.py — Nguồn sự thật DUY NHẤT cho giọng/persona của ERIS. Trước đây "register cấm" (giọng trợ lý help-desk / "tôi là AI" / chối phẳng cảm xúc) được định nghĩa LẶP ở nhiều nơi, mỗi nơi viết lại bằng một dạng vă...
- `runtime/liveliness_tracker.py` — Per-cycle liveliness tracking and observability for the autonomous loop. Each idle cycle emits one ``DecisionRecord`` so that "alive" is measurable from logs and regressions are diagnosable. The tracker keeps a bounded r...
- `runtime/no_fallback_policy.py` — Policy module cho runtime: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục.
- `runtime/debug_console.py` — debug_console.py — Bảng lệnh debug ẩn cho ERIS. Đây KHÔNG phải đường runtime bình thường. Nó là cổng để Tác_Giả gõ lệnh tay từ panel DEBUG (góc dưới phải khung Cảm xúc) nhằm: * buff/ép chỉ số cảm xúc + quan hệ để test nh...
- `cortex/se.py` — Module `se` trong package `cortex`.
- `cortex/background_observer.py` — BackgroundObserver cho ERIS. Bản này có 2 tầng: 1. Rule-based observer luôn chạy được, không phụ thuộc model. 2. Optional Ollama text observer để phân loại mềm hơn về sau. Luật cứng: - Không trả lời user. - Không commit...
- `cortex/observer_contracts.py` — Contract cho Background Observer của ERIS. Tầng này không trả lời user, không commit memory, không tự hành động. Nó chỉ biến tín hiệu nền thành frame nhỏ để Attention/WorkingMemory/BodyBias đọc.
- `cortex/vision_semantic_compressor.py` — VisionSemanticCompressor cho ERIS. Vai trò: - Nhận screenshot/crop + OCR hint + ObserverFrame. - Gọi Qwen vision qua Ollama khi thật sự cần. - Nén màn hình thành SemanticSceneNote nhỏ. - Không trả lời user. - Không commi...
- `cortex/attention_salience.py` — cortex/attention_salience.py ============================ Selection backbone / anti-context-flood backbone cho ERIS Cognitive Pipeline. Đây KHÔNG phải "attention hiện tại" kiểu gom vài keyword rồi chấm điểm cho vui. File...
- `cortex/working_memory.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho cortex.
- `cortex/global_workspace.py` — src/cortex/global_workspace.py ================================ Global Workspace / Broadcast Frame cho ERIS. Mục tiêu của file này: - Biến WorkingMemory + Salience + Evidence + Affect + Goal + Risk + Body state thành một...
- `cortex/meaning/pipeline.py` — Facade Phase2MeaningPipeline. Bắt buộc WorkspaceFrame-only và ToM-after-Meaning: WorldScene -> Interpreter -> Sociocultural -> MeaningHypothesis -> PragmaticIntent -> TheoryOfMind -> OverreadBrake -> SurfaceMeaningPolicy.
- `cortex/meaning/meaning_layer.py` — Module `meaning layer` trong package `cortex/meaning`.
- `cortex/meaning/world_scene_builder.py` — world_scene_builder.py — WorkspaceFrame -> WorldScene (Phase 2, stage 1). ``WorldSceneBuilder`` là stage đầu tiên của pipeline meaning. Nó nhận một ``FrameReadView`` (bề mặt đọc có kiểm soát bọc ``WorkspaceFrame``) và dự...
- `cortex/meaning/world_interpreter.py` — world_interpreter.py — WorldScene -> Observation set (Phase 2, stage 2). ``WorldInterpreter`` là stage thứ hai của pipeline meaning. Nó nhận một ``WorldScene`` (đầu ra của ``WorldSceneBuilder``) và rút ra một tập ``Obser...
- `cortex/meaning/sociocultural_context.py` — sociocultural_context.py — Stage 3: Observation set -> ContextAnnotation set. ``SocioculturalContext`` gắn ngữ cảnh xã hội - văn hóa (quan hệ / *relationship*, register, và chuẩn mực giao tiếp / *social-norm*) vào từng `...
- `cortex/meaning/meaning_hypothesis.py` — meaning_hypothesis.py — ``MeaningHypothesisEngine`` (stage 4 của Phase 2). ContextAnnotation set → MeaningHypothesis set. **Module WRAP, không reimplement scoring (R5.7).** Engine này *bọc* hai engine đã có sẵn và **uỷ q...
- `cortex/meaning/pragmatic_intent.py` — pragmatic_intent.py — ``PragmaticIntentEngine`` (stage 5 của Phase 2). MeaningHypothesis set → PragmaticIntent set. Engine này suy ý định giao tiếp (pragmatic intent: yêu cầu, than phiền, đùa, thăm dò…) **chỉ từ** tập ``...
- `cortex/meaning/overread_brake.py` — overread_brake.py — ``OverreadBrake`` (phanh phán bậy, stage 8 của Phase 2). Conclusion set → EvaluatedConclusion set. ``OverreadBrake`` là cơ chế phanh chuyên trách: nó nhận **mọi** kết luận xuôi dòng (``MeaningHypothes...
- `cortex/tom/theory_of_mind.py` — TheoryOfMindCore suy MentalStateInference từ MeaningHypothesis + PragmaticIntent, có guard thứ tự và counterfactual correction. Debug khi ERIS đọc tâm lý quá tay.
- `cortex/affect_semantics.py` — affect_semantics.py =================== Module này dùng để phân tích "áp lực nghĩa" trong câu chat của user. Mục tiêu: - Không route intent bằng keyword thô kiểu: nếu thấy "buồn" thì attachment_dialogue. - Thay vào đó, m...
- `cortex/appraisal.py` — Module `appraisal` trong package `cortex`.
- `cortex/internal_state.py` — Persistent internal state. Theo dõi valence/arousal/curiosity/boredom/social_energy/attachment/fatigue/silence_pressure và các MentalProcess con. Debug khi continuity mất sau restart hoặc pressure không decay.
- `cortex/endogenous_drive.py` — src/cortex/endogenous_drive.py ============================== Tầng 2a - Endogenous Drive. File này giữ nhịp sinh học ngầm của ERIS: boredom, fatigue, curiosity, continuity pressure, consolidation pressure, insight pressu...
- `cortex/connection_drive.py` — cortex/connection_drive.py ========================== Động lực nội sinh "sợ cô độc → tìm kết nối" cho ERIS. Vấn đề cũ: ERIS không có drive tự thân. Im lặng tích thành `silence_debt` ở wake governor nhưng KHÔNG đổ ngược v...
- `cortex/continuity_threat.py` — Continuity threat calculus for ERIS. Module này cố ý tách "im lâu" khỏi "đứt gãy hiện diện". Timer chỉ được dùng để hỏi: khoảng im này có bất thường so với ngữ cảnh không? Nó không được tự phong làm nỗi cô độc rồi bắt Su...
- `cortex/personality.py` — Module `personality` trong package `cortex`.
- `cortex/ni.py` — Module `ni` trong package `cortex`.
- `cortex/ti.py` — Module `ti` trong package `cortex`.
- `cortex/fe.py` — Module `fe` trong package `cortex`.
- `cortex/conversation_dynamics.py` — Module `conversation dynamics` trong package `cortex`.
- `cortex/relationship_dynamics.py` — relationship_dynamics.py ======================== Module này quản lý state quan hệ dài hạn giữa ERIS và user. Bản này đã bỏ kiểu suy trực tiếp: "ổn" / "chuẩn" -> accepted_style "eris" / "project" -> repeated_project_cont...
- `cortex/relationship_event_builder.py` — relationship_event_builder.py ============================= Tầng này chuyển một lượt hội thoại thành các score quan hệ có bằng chứng. Lý do tồn tại ------------- Trước đây RelationshipDynamics có khuynh hướng suy trực ti...
- `cortex/relational_feedback.py` — relational_feedback.py ====================== Tầng này đọc feedback về *cách ERIS hiện diện* trong hội thoại: - lạnh quá - xa cách quá - vô hồn / robot / máy móc - nói như assistant/support/corporate - cứng / khô / không...
- `cortex/self_model.py` — Module `self model` trong package `cortex`.
- `cortex/social_presence.py` — Module `social presence` trong package `cortex`.
- `cortex/speech_core.py` — Chuyển pressure thành quyền nói public. Đọc snapshot, internal_state, appraisal, Ti, meaning, thought_surface, self_state, personality, spontaneous impulse. Debug khi có tension nhưng im hoặc nói dù không có meaning shift.
- `cortex/surface_arbiter.py` — Single source of truth cho low-level surface utterances. Thu impulse từ presence, speech_core, thought_stream, private_mind/private_life, long_silence, extra impulses; normalize/dedupe/score/rate-limit; hỏi LowLevelSpeechPolicy để reject/body_only/normal_llm/force_llm; gọi LLM nếu cần. Debug khi cue có pressure nhưng không nói, body-only kẹt, hoặc LLM decline.
- `cortex/surface_seed_compiler.py` — Gom áp lực rải rác thành seed public-safe đủ cụ thể cho wording layer. Đọc frame/snapshot/presence/private_mind/thought_stream/internal state để sinh `CompiledSurfaceSeed`. Debug khi low-level LLM chỉ nhận idle_seconds và viết câu rỗng.
- `cortex/low_level_speech_policy.py` — Policy chọn generation mode cho surface thấp tầng. Nó không viết câu. Nó chỉ quyết định reject/body_only/normal_llm/force_llm theo confidence, kind, silent cycles, family cooldown và YAML/env config.
- `cortex/micro_policy.py` — Policy module cho cortex: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục.
- `cortex/micro_grounding_guard.py` — Module `micro grounding guard` trong package `cortex`.
- `cortex/micro_repeat_guard.py` — Module `micro repeat guard` trong package `cortex`.
- `cortex/micro_surface_lint.py` — Module `micro surface lint` trong package `cortex`.
- `cortex/spontaneous_life.py` — Endogenous + situated speech pressure for ERIS. Mô-đun này không viết câu công cộng. Nó tạo một SpeechImpulse bằng cách dựng AgentStateStack rồi cho nhiều impulse cạnh tranh: silence, scene curiosity, inner whim, micro s...
- `cortex/impulse_arbitration.py` — Impulse competition for ERIS. Thay vì hardcode "đủ 5 phút thì nói", module này tạo nhiều impulse cùng lúc và chấm điểm bằng belief + need + preference + trait + affordance + habit. Nó không viết câu cuối. Nó chỉ chọn lực...
- `cortex/action_planner.py` — Utility-based ActionPlanner for ERIS. Bản này thay lõi rule-based cũ bằng 3 tầng: 1. action_memory.py -> nhớ hành vi gần đây, fatigue, boredom, recoil, rhythm 2. action_utility.py -> chấm điểm cạnh tranh cho từng action...
- `cortex/action_utility.py` — Utility competition for ERIS actions. File này thay lõi "if intent == X -> return Y" bằng cạnh tranh utility. Không phải ML. Không giả vờ thông minh. Chỉ là scoring minh bạch, có memory, có risk penalty, có rhythm, có pr...
- `cortex/action_memory.py` — Action memory and rhythm state for ERIS. File này không quyết định câu chữ. Nó chỉ giữ lịch sử hành vi để planner không cư xử như cá vàng bị reset não sau mỗi frame. Mục tiêu: - nhớ action gần đây để chống lặp discrete -...
- `cortex/thought_stream.py` — Substrate suy nghĩ nền: fragment store, association graph, prediction tracker, tension engine, unresolved loop, momentum, decay, reactivation, reheater, surface selector. Nó tạo thought pressure, không phải câu nói.
- `cortex/inner_thought.py` — Module `inner thought` trong package `cortex`.
- `cortex/private_mind/contracts.py` — Data contracts private mind: ThoughtFragment, PrivateConcern, InternalJudgment, StateMutation, SurfaceCandidate, EvidenceDossier, PrivateMindTickResult. Đây là ngôn ngữ chung của concern/mutation/surface.
- `cortex/private_mind/concern_store.py` — Kho PrivateConcern. Merge fragment thành concern sống lâu, auto-resolve, decay, update từ judgment/outcome. Debug khi mỗi tick nghĩ xong rồi quên, không có đời sống bận tâm.
- `cortex/private_mind/evidence_dossier.py` — cortex/private_mind/evidence_dossier.py ======================================= EvidenceDossierBuilder gom hồ sơ cho private mind: - recent user turns; - runtime state; - memory hits; - repair failures; - active goal/cur...
- `cortex/private_mind/mini_evaluators.py` — cortex/private_mind/mini_evaluators.py 4 mini-evaluator gọi API. Không có rule fallback — nếu API fail thì tick đó không có fragment từ evaluator đó. Pool API dự phòng lo việc resilience.
- `cortex/private_mind/inner_synthesizer.py` — GemmaInnerSynthesizer gom ThoughtFragment thành InternalJudgment. Có fallback deterministic. Debug khi mini-evaluator có output nhưng không kết tinh thành phán quyết/mutation.
- `cortex/private_mind/state_mutation_bus.py` — Cầu nối từ InternalJudgment sang state tương lai: internal_agenda, repair_memory, speech_bias, inquiry_plan... Debug khi private mind chỉ là decor, không ảnh hưởng reply sau.
- `cortex/private_mind/surface_valve.py` — Van public-safe cho private mind. Chặn private markers, evidence yếu, usefulness thấp, interrupt cost cao, rồi convert SurfaceCandidate thành SurfaceImpulse. Debug khi nội tâm rò thẳng ra câu nói hoặc ngược lại không bao giờ surface.
- `cortex/private_mind/inner_diary_writer.py` — cortex/private_mind/inner_diary_writer.py Biến dữ kiện nội tâm thô (judgment/concern/fragment/future/surface) thành nhật ký giọng Eris (ngôi thứ nhất) thông qua một lời gọi LLM, có: - throttle theo thời gian, - chỉ gọi l...
- `cortex/private_mind/inner_diary_renderer.py` — cortex/private_mind/inner_diary_renderer.py Render a compact inner diary digest for UI display. Keep it short and never expose raw prompt text.
- `cortex/private_mind/user_model.py` — cortex/private_mind/user_model.py ================================= Mô_Hình_Ngài — hình dung bền vững của ERIS về Người_Dùng (Ngài). Đây là TẦNG NỀN của spec `eris-existential-anchor`: gắn bó, ý nghĩa và trục bóng tối đề...
- `cortex/private_life/contracts.py` — cortex/private_life/contracts.py ================================ Hợp đồng dữ liệu cho Private Life Layer của ERIS. Tầng này khác PrivateMind: - PrivateMind hỏi: "tôi đang nghĩ gì về tình huống này?" - PrivateLife hỏi: "...
- `cortex/private_life/core.py` — PrivateLifeCore: habitat, attachments, projects, anchors, daily rhythm, taste, solitude, rituals, errands, life events. Không sinh lời public, chỉ update đời sống riêng và seed an toàn.
- `cortex/private_life/persistence.py` — cortex/private_life/persistence.py ================================== Persistence JSON riêng cho PrivateLifeCore. Lý do tách khỏi memory_cognition: private life là state vận hành của agent, không phải fact user hay memor...
- `cortex/subconscious/thought_spark.py` — ThoughtSpark contract cho tầng wandering/subconscious. ThoughtSpark là mẩu ý nghĩ cực sớm: còn mơ hồ, chưa claim fact, chưa có quyền surface. Nó là hạt bụi trong đầu, không phải câu nói. Nếu cho nó nhảy thẳng ra public s...
- `cortex/subconscious/drift_pool.py` — Hồ giữ ThoughtSpark yếu. Spark decay/cộng hưởng/nhóm theme rồi thỉnh thoảng kết tinh thành association. Không có API surface public.
- `cortex/subconscious/wandering_thought.py` — WanderingThoughtEngine: spark -> drift -> association -> fragment. Engine này chạy nhẹ theo tick. Nó không gọi SurfaceArbiter, không gọi LLM, không phát public speech. Nó chỉ tạo ThoughtSpark, nuôi DriftPool, rồi đôi khi...
- `cortex/subconscious/free_association.py` — FreeAssociationEngine cho wandering sparks. Nó nối spark bằng semantic/mood/module/metaphor/weak link. Không suy luận fact mới. Đây là liên tưởng, không phải lập luận có toga và búa thẩm phán.
- `cortex/subconscious/blackboard.py` — Blackboard Phase 0 cho subconscious workers. Blackboard là nơi các worker nền bỏ ThoughtFragment vào. Nó không chọn câu nói, không gọi LLM, không quyết định quan hệ. Nó chỉ làm ba việc buồn tẻ nhưng cứu mạng: 1. Validate...
- `cortex/subconscious/synthesizer.py` — Conscious Synthesizer Phase 0. Synthesizer là cổ chai ý thức nhỏ: nhận nhiều ThoughtFragment từ Blackboard, gom cụm, chọn theme thắng, rồi xuất một ThoughtObject duy nhất. Nó không sinh văn public. Nó cũng không gọi LLM....
- `cortex/subconscious/model_synthesizer.py` — Model-backed Lane 3 synthesizer. Đây là lớp làm phần "phiên toà nội tâm": các ThoughtFragment vẫn do worker rẻ đưa lên Blackboard, nhưng Lane 3 có thể gọi API để nén chúng thành một ThoughtObject có evidence rõ hơn, có b...
- `cortex/subconscious/worker_base.py` — Base contract cho các subconscious worker Phase sau. Phase 0 chưa triển khai 15 worker. File này chỉ cung cấp lớp nền để Phase 1+ không mỗi worker tự chế một kiểu output. Một contract nhỏ hôm nay cứu được nhiều file `if...
- `cortex/subconscious/topic_seed_pool.py` — TopicSeedPool gom seed từ self-anchor/habitat/memory/mood/random weak link.
- `cortex/daydream_consolidation.py` — src/cortex/daydream_consolidation.py ==================================== Tầng 2b - Daydream Consolidation. Đây là nơi Qwen 4B GGUF được phép nghiền ngẫm memory packet đã lọc sẵn. Nó không chạy theo timer mù. Runtime/Wak...
- `cortex/internal_agenda.py` — src/cortex/internal_agenda.py ================================ Stack agenda nội bộ cho ERIS. Module này là nơi giữ các vấn đề ERIS đang tự treo trong đầu: - câu hỏi chưa đóng, - lỗi cần repair, - ký ức cần chưng cất, - i...
- `cortex/agent_mind_persistence.py` — Persistent Agent Mind Layer cho ERIS. Module này giữ 3 lớp học dài hạn cho impulse system: 1. BeliefCore persistent - ERIS tin gì về user / bản thân / scene / task. - Mỗi belief có confidence, nguồn, decay, evidence coun...
- `cortex/agent_state_stack.py` — Agent state stack for ERIS. Lớp này gom các lực nền đang bị rải rác trong runtime thành một contract nhỏ: Evidence -> Belief -> Preference -> Need -> Trait -> Habit -> Affordance. Nó cố tình không gọi LLM và không tự quy...
- `cortex/development_system.py` — development_system.py — Sổ_Phát_Triển + điều phối apply/undo/reset. Tách khỏi ``development_profile`` (data + store + gate) để phần điều phối và audit rõ ràng. Luồng áp dụng theo nguyên tắc **ghi-Sổ-trước-commit-sau** để...
- `cortex/growth_consolidator.py` — growth_consolidator.py — Tác_Tử_Nền sinh Đề_Xuất_Nhích cho long-arc. Đặt trên kỷ luật của ``DaydreamConsolidator``: chỉ chạy khi đủ áp lực củng cố / thời gian rảnh và ngân sách cho phép; chỉ chấp nhận bằng chứng có ``evi...
- `memory/memory_cognition.py` — Facade memory legacy v2: commit qua StateCommitRequest, recall qua MemoryRetrievalEngine, route target vào event/active/episodic/semantic/relational/affective/procedural/repair/unresolved. Debug khi ghi nhớ sai layer hoặc recall thiếu source.
- `memory/memory_kernel.py` — Facade memory mới cho runtime: ingest, answer, build_packet, maintain, commit_many, recall/retrieve, debug_snapshot. Debug khi memory query deterministic không chạy.
- `memory/memory_kernel_contracts.py` — Contract/dataclass dùng chung trong memory.
- `memory/memory_commit_policy.py` — Policy intake user turn. Trích fact/preference/convention, chặn commit câu hỏi như fact. Debug khi “tôi tên X” không nhớ hoặc “tôi tên gì” bị ghi thành fact.
- `memory/memory_models.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/schemas.py` — Module `schemas` trong package `memory`.
- `memory/persistence.py` — Module `persistence` trong package `memory`.
- `memory/event_ledger.py` — Append-only Event Ledger cho ERIS. Tầng này giữ raw truth: tín hiệu thô, evidence đã tạo ra, frame liên quan, và metadata audit. Nó không kết luận tâm lý, không merge ký ức, không sửa quá khứ. Nếu một module muốn lưu sự...
- `memory/active_state_snapshot.py` — Active State Snapshot cho ERIS. Snapshot giữ trạng thái hiện tại có thể overwrite: goal đang theo, session arc, affect/homeostasis hiện thời, relation state, project active, thread đang mở. Nó không phải event ledger và...
- `memory/episodic_memory.py` — Episodic Memory: chuyện cụ thể đã xảy ra. Episodic không phải semantic fact. Nó giữ cảnh, lượt, outcome, evidence và độ nổi bật. Một câu user sửa sai hôm nay là episode. Một fact ổn định chỉ lên semantic sau khi commit p...
- `memory/semantic_memory.py` — Semantic Memory: bộ nhớ fact đã được chưng cất cho ERIS. File này cố tình KHÔNG làm event log. Semantic memory chỉ nên giữ những thứ đã đủ ổn định để ERIS có thể nhớ gọn: - fact về user, ERIS, project, thế giới, kỹ thuật...
- `memory/relational_memory.py` — Relational Memory: nhịp quan hệ, rupture, repair, khoảng cách. Đây không phải nơi lưu "user is sad". Nó lưu pattern có bằng chứng: user sửa ERIS khi overread, user thích câu trả lời kỹ thuật trực tiếp, rupture cần repair...
- `memory/affective_residue_memory.py` — Affective Residue Memory: dư âm cảm xúc dưới dạng pressure. Không lưu "ERIS buồn" như fact công khai. Lưu pressure: tension, attachment residue, exposure recoil, unfinished loop. Dư âm ảnh hưởng nhịp nói/im lặng, không t...
- `memory/procedural_memory.py` — Procedural Memory: cách xử lý đã học. Đây là nơi lưu rule kiểu: khi user sửa hiểu lầm, trả lời trực tiếp trước; khi evidence yếu, không claim nhìn thấy màn hình. Procedural là policy học được, không phải fact về user.
- `memory/repair_memory.py` — Repair Memory: ghi lỗi, sửa sai, suppression rule tương lai. Nếu user nói "không phải", hệ thống không được chỉ xin lỗi rồi quên. Nó phải lưu loại lỗi, assumption sai, evidence, chiến lược sửa. Đây là nơi ERIS học bớt ng...
- `memory/unresolved_memory.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_retrieval_engine.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_scoring.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_activation.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_packet_builder.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_cue.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_recall_policy.py` — Policy module cho memory: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục.
- `memory/memory_query_ir.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_query_compiler.py` — Compile query từ slot/semantic/repair/LLM parser thành MemoryQueryIR. Debug khi câu hỏi trí nhớ mơ hồ rơi xuống general LLM.
- `memory/memory_query_executor.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_query_slot_parser.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_query_semantics.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_query_llm_parser.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_query_repair.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_turn_graph.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_turn_annotator.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/claim_extractor.py` — Module `claim extractor` trong package `memory`.
- `memory/semantic_claim.py` — Module `semantic claim` trong package `memory`.
- `memory/claim_entailment.py` — Module `claim entailment` trong package `memory`.
- `memory/predicate_ontology.py` — Module `predicate ontology` trong package `memory`.
- `memory/semantic_answer_policy.py` — Policy module cho memory: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục.
- `memory/memory_worthiness.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_retention_policy.py` — Policy module cho memory: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục.
- `memory/claim_consolidator.py` — Module `claim consolidator` trong package `memory`.
- `memory/memory_consolidator.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_pruner.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/memory_ai_curator.py` — memory/memory_ai_curator.py =========================== AI curator cho memory — gọi Gemini để làm 2 việc rule không làm được: 1. Episodic distillation: Nhiều episode tương đồng → 1 semantic fact ổn định. Ví dụ: 5 lần use...
- `memory/memory_maintenance.py` — Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- `memory/understanding/semantic_parser.py` — Parser/normalizer cho memory/understanding.
- `memory/understanding/meaning_frame.py` — Module `meaning frame` trong package `memory/understanding`.
- `memory/understanding/entity_linker.py` — Module `entity linker` trong package `memory/understanding`.
- `memory/understanding/polarity_temporal.py` — Module `polarity temporal` trong package `memory/understanding`.
- `llm/service.py` — Façade gọi model. Build prompt theo chat/directive/autonomous/micro/vision, parse Decision JSON, repair malformed JSON, chống prompt leak, fallback protocol/service, style rewrite, chat-act guard. Debug khi provider trả prose/JSON cụt/CoT hoặc hỏi thẳng mà đáp vòng.
- `llm/contracts.py` — Contract/dataclass dùng chung trong llm.
- `llm/client.py` — HTTP client Gemini/OpenAI-compatible/llama-server, payload variants, 429 key rotation, image payload, HTTP error body. Debug khi provider shape lạ hoặc key pool xoay không đúng.
- `llm/key_pool.py` — llm/key_pool.py Pool API key dùng CHUNG cho mọi mạch gọi Gemini (main / speech / private_mind). Mỗi key thường thuộc một Google project khác nhau (vd nhiều Gmail) → mỗi key có hũ free quota riêng. Free tier tính theo PRO...
- `llm/process_manager.py` — Module `process manager` trong package `llm`.
- `llm/ollama_client.py` — Client mỏng cho Ollama. Vai trò trong ERIS: - Dùng một Ollama daemon duy nhất thay vì mở nhiều llama-server riêng. - Gọi model nhỏ cho BackgroundObserver. - Gọi model vision cho VisionSemanticCompressor về sau. - Ép JSON...
- `llm/llamacpp_client.py` — llm/llamacpp_client.py ====================== Engine inference local IN-PROCESS dựa trên llama-cpp-python. Mục đích: chạy model gguf đặt thẳng trong `src/` mà KHÔNG cần Ollama hay llama-server ngoài → bản build self-cont...
- `llm/local_llama_engine.py` — llm/local_llama_engine.py ========================= Engine local thống nhất bằng llama-cpp-python, drop-in thay cho ``OllamaClient``. Mục tiêu: dồn TẤT CẢ model nội bộ về một engine duy nhất chạy gguf trong ``src/`` (khô...
- `parser_grounding/decision.py` — Mixin parser raw LLM output -> Decision. Repair JSON candidate, coerce fields, sanitize motion/action, detect capability/perception violations, fallback non-JSON safely. Debug khi LLM trả prose/JSON vỡ mà parser xử sai.
- `parser_grounding/service.py` — Module `service` trong package `parser_grounding`.
- `domain/decision.py` — Dataclass Decision và `to_payload()`. Resolve motion_intent/target/facing/text/should_speak trước khi gửi UDP.
- `transport/udp.py` — UDP transport. Send JSON Decision, poll event body, nén private_mind_digest/debug khi quá 63KB.
- `actions/router.py` — High-confidence action router for ERIS. Router này chỉ nên bắt các lệnh hệ thống thật sự rõ ràng. Nếu câu user có vẻ là câu hỏi, meta-discussion, code/debug, hoặc chỉ nhắc đến một từ khóa như "youtube/search/volume/copy"...
- `actions/executor.py` — Executor thực thi action/command cho actions.
- `actions/contracts.py` — Contract/dataclass dùng chung trong actions.
- `telemetry/service.py` — Module `service` trong package `telemetry`.
- `telemetry/system.py` — Module `system` trong package `telemetry`.
- `telemetry/content_metadata.py` — Thu thập metadata nội dung đang nhìn thấy cho SeLens. Mục tiêu của file này không phải "đọc màn hình như tiên tri". Nó chỉ gom các fact có nguồn rõ ràng theo thang L0-L5 rồi trả về dict nhỏ để SeLens tự quyết confidence....

# 5. Runtime / spine chi tiết

### `vision.py`
- **LOC**: 240
- **Vai trò**: Entry point Python. Boot order: cấu hình logging, giữ `.vision.lock`, dựng `RemoteModelProcessManager`, `LlmService`, `UdpTransport`, `MemoryCognitionCore`, parser, telemetry, Ni/Ti/Fe/action, rồi khởi tạo `RuntimeCoordinator` và chạy `run_loop()`.
Debug khi runtime không boot, memory load chết, remote config sai, hoặc body không có cognition.
- **Class/dataclass chính**:
  - `AttentionOverseer`
    - **Methods**: __init__(self, model_path, n_ctx, n_gpu_layers), _is_body_running(self), stop(self, reason), run_loop(self)
  - `SingleInstanceLock`
    - **Methods**: __init__(self, lock_path), acquire(self), release(self)
- **Phụ thuộc nội bộ nổi bật**: actions, cortex, domain, llm, llm.process_manager, memory.memory_cognition, parser_grounding, runtime.coordinator, runtime.memory_semantic_parser_adapter, telemetry, transport

### `runtime/coordinator.py`
- **LOC**: 7576
- **Vai trò**: Orchestrator trung tâm. Kế thừa nhiều mixin để chia chat/autonomous/force_speak/presence/frame/speech/memory/filter/shadow. Trong `__init__` nó nối gần như toàn bộ engine: salience, working memory, meaning, personality, appraisal, affect, relation, internal state, self model, session ritual, speech core, action planner, source grounding, micro policy, body bias, signal buffer, observer, vision compressor, internal agenda, endogenous drive, wake governor, private mind/life daemon, thought stream, subconscious loop, memory kernel và model budget policy.
Debug khi lỗi end-to-end không rõ owner. Đây là nơi kiểm tra wiring, cooldown, queue model, body_bias, private digest, public turn ledger và payload gửi body.
- **Class/dataclass chính**:
  - `RuntimeCoordinator` (base=CognitiveCycleMixin, ChatCycleMixin, AutonomousCycleMixin, ForceSpeakCycleMixin, StateCommitServiceMixin, FrameBuilderMixin, SpeechPipelineMixin, PromptContextBuilderMixin, CognitiveFrameRecorderMixin, PresenceControllerMixin, TextRepeatGuardMixin, ForceSpeakSurfacePolicyMixin, PostGenerationFiltersMixin, ShadowPipelineMixin)
    - **Methods**: _fallback_lines_for_intent(self, intent), _force_speak_fallback_by_intent_text(self, intent), _public_thought_topic(self, value), _looks_internal_topic(self, value), _background_memory_digest_idle_probe(self), __init__(self), _install_model_inference_queue(self), _run_background_observer(self), _log_observer_trace(self, observer_frame), _update_3tier_autonomy_state(self), _update_private_mind_state(self), _apply_private_mind_tick_result(self, result), _persist_inner_diary(self), _drain_private_mind_surface_impulses(self), _update_private_life_state(self), _drain_private_life_surface_impulses(self), _private_life_digest_for_payload(self), _daydream_packets_from_runtime(self), _append_daydream_packets_from_memory_snapshot(self, snapshot, add_packet), _daydream_kind_from_memory_layer(self, layer), _daydream_text_from_memory_record(self, record), _build_signal_snapshot_for_observer(self), _observer_focus_kind_from_snapshot(self, snapshot), _observer_percept_content(self, observer_frame), _observer_attention_tags(self, observer_frame), _log_raw_llm_output(self, channel, raw), _preview_text(self, text), _infer_active_conversational_topic(self, user_text), _load_memory_state(self), _resolve_internal_agenda_path(self), _has_structured_memory_store(self), _ensure_internal_state(self), _get_internal_state(self), _set_internal_state(self, state), _send_decision_to_body(self, decision), _private_mind_digest_for_payload(self), _compact_private_mind_digest_for_udp(self, digest), _compact_private_mind_debug_value(self, value), _compact_private_mind_scalar(value), _private_mind_speech_silence_reason(self), _record_public_turn(self, decision), _infer_public_turn_channel_from_runtime(self, decision), _load_rapid_burst_window(self), _block_autonomous_presence_after_public_turn(self, now), _link_previous_public_turn_for_chat(self, user_timestamp), _previous_public_turn_context(self, public_turn), _build_body_bias_payload(self), _build_emotion_debug_payload(self), _body_bias_clamp(value), _normalize_body_focus_kind(value), _make_cognitive_disturbance(self), _looks_like_closure_disturbance(self, content), _build_event_disturbances(self), _disturb_cognitive_substrate(self), _with_thought_stream_surface(self, report, surface), _pop_thought_stream_report_for_autonomous(self), _pop_subconscious_report_for_autonomous(self), _save_memory_state(self), _memory_recall_texts(self), _activate_memory_resonance(self), _thought_stream_resonance_fragments(self), _memory_attention_lines(self), _norm_deviation_texts(self, snapshot), _note_norm_observation(self, snapshot), _event_timestamp(self, snapshot), _normalize_event_evidence(self, evidence), _make_percept_event(self), _telemetry_event_privacy_level(self, kind), _telemetry_event_novelty_hint(self, kind, content), _collect_percept_events(self), _collect_cognitive_percepts(self), _score_attention_candidate(self, percept), _build_attention_candidates(self, percepts), _build_broadcast(self, candidates), _evidence_from_percepts(self, percepts), _salience_candidate_to_runtime(self, candidate), _runtime_attention_label(self, candidate, tags), _build_meaning_layer(self), _build_personality_lens(self), _apply_personality_lens_to_fe_plan(self, fe_plan, lens), _build_cognitive_appraisal(self), _build_appraisal_context(self, appraisal), _build_inner_thought(self), _build_speech_core(self), _remember_inner_thought_rhythm(self, inner_thought), _start_cognitive_frame(self), _set_cognitive_action_plan(self, frame), _apply_micro_line_policy_to_action_plan(self, frame), _micro_policy_anchor_hints(self), _build_relational_context(self, state), _speech_intent_from_core(self, speech_core), _merge_speech_core_notes(self, notes, speech_core), _merge_meaning_layer_notes(self, notes, meaning_layer), _speak_truth_probe_row(self, status), _build_speak_truth_table(self), _summarize_speak_truth_table(self, table), _attach_speak_truth_table(self, frame), _merge_memory_resonance_notes(self, notes, memory_resonance), _merge_inner_thought_notes(self, notes, inner_thought), _merge_personality_lens_notes(self, notes, personality_lens), _merge_subconscious_notes(self, notes, subconscious_report), _is_inner_thought_speech_act(self, speech_act), _restore_session_ritual_once(self), _apply_force_speak_no_evidence_topic_filter(self, decision), _build_planned_withdraw_decision(self, action_plan), _log_decision_stage(self, channel, stage, decision), stop(self), _start_mental_process_loop(self), _stop_mental_process_loop(self), _run_mental_process_loop(self), _tick_mental_process_background(self), _build_subconscious_runtime(self), _subconscious_frame_payload(self), _subconscious_memory_packet(self), _subconscious_pressure_metrics(self), _subconscious_blackboard_metrics(self), _schedule_next_subconscious_due(self, lane, low, high), _score_subconscious_surface(self), _surface_from_subconscious_thought(self, thought), _maybe_tick_subconscious_runtime(self), _maybe_tick_subconscious_background(self), _mix_axis(self, previous, target), _load_mental_process_enabled(self), _load_mental_process_interval(self), _load_autonomous_sleep_seconds(self, env_name), _apply_position_update(self, decision), _build_silent_motion_decision(self, ti_report), _normalize_user_message(self, user_text), _looks_like_screen_vision_request(self, user_text), _capture_screen_frame_for_chat(self, user_text), _build_user_message_signature(self, user_text), _track_repeated_user_message(self, user_text), _build_repeat_guard_decision_basic(self, user_text, ti_report, repeat_count), _build_repeat_guard_decision(self, user_text, ti_report, repeat_count), _handle_incoming(self, msg), _handle_debug_command(self, msg), _handle_anchor_control(self, msg), _commit_chat_decision(self, decision, fe_plan), _sleep_interruptible(self, seconds), _bucket_idle_seconds(self, idle_seconds), _bucket_window_spread(self, open_windows, browser_tabs), _load_vision_fact_settings(self), _vision_queue_timeout_seconds(self, channel), _vision_failure_backoff_seconds(self, stage, exc), _note_vision_failure(self, stage, exc), _is_low_value_screen_fact(self, fact), _speech_evidence_score(self, text), _is_speakable_evidence(self, text), _sanitize_screen_facts(self, facts), _semantic_scene_note_to_facts(self, note), _vision_trace_from_scene_note(self, note), _should_use_vision_compressor(self), _refresh_screen_facts_from_data_uri(self), _maybe_update_screen_facts(self), _attach_screen_facts(self, snapshot, facts), _build_autonomous_signature(self, snapshot, ti_report), _track_autonomous_signature(self, snapshot, ti_report), _should_suppress_autonomous_reply(self), _has_resource_pressure_signal(self, snapshot), _is_generic_screen_event(self, event), _is_generic_screen_evidence(self, evidence), _concrete_screen_signals(self, snapshot), _concrete_vision_signals(self, snapshot), _concrete_telemetry_signals(self, snapshot), _has_concrete_screen_signal(self, snapshot), _broadcast_screen_winners(self, broadcast), _choose_autonomous_speech_intent(self), _ambient_silence_cooldown_seconds(self, snapshot, ti_report), _should_hold_ambient_silence(self), _should_skip_weak_autonomous_speech(self), _has_high_cognitive_momentum(self, thought_stream_report), _choose_autonomous_sleep_duration(self), _current_autonomous_wake_decision(self), _wake_allows_main_cognition(self), _autonomous_sleep_seconds_from_wake(self, decision), _send_wake_gate_body_update(self, decision), _wake_gate_ti_report(self), _wake_gate_fe_plan(self), _wake_gate_presence_candidate(self), _presence_probe_status(self), _reengagement_probe_status(self), _update_wake_gate_debug(self, decision), _presence_surface_status_label(self, status), _log_presence_surface_statuses(self), _build_wake_gate_frame(self), _finalize_wake_gate_micro_decision(self), _surface_arbiter_drop_reason(self, default), _surface_arbiter_drop_status(self), _surface_arbiter_reason_from_surface(self, surface, default), _surface_arbiter_status_from_surface(self), _maybe_low_level_surface_from_wake_gate(self), _maybe_presence_maintenance_before_sleep(self), _maybe_micro_presence_from_observe_only(self), _finalize_autonomous_wake_gate(self), _commit_think_only_active_frame(self), _process_pending_user_input(self), _conversation_went_stale(self), _run_loop_iteration(self), run_loop(self), _load_ni_meta_mode_flags(self), _soften_chat_meta_result(self), _soften_autonomous_meta_result(self), _maybe_apply_ni_meta_critic(self), _build_direct_action_decision(self, user_text, ti_report, snapshot), _execute_system_action(self, decision), _action_animation_hint(self, action_name, fallback), _action_result_to_text(self, result), _resolve_now_playing_text(self, snapshot), _extract_media_title_from_snapshot(self, snapshot), _extract_media_title(self, raw_title)
- **Hàm module-level**: _is_nonsemantic_fallback_decision(decision)
- **Phụ thuộc nội bộ nổi bật**: cortex.action_planner, cortex.affect_semantics, cortex.attention_salience, cortex.background_observer, cortex.daydream_consolidation, cortex.endogenous_drive, cortex.internal_agenda, cortex.observer_contracts, cortex.appraisal, cortex.chat_light, cortex.appetite_system, cortex.connection_drive, cortex.conversation_dynamics, cortex.contracts, cortex.inner_thought, cortex.internal_state, cortex.meaning, cortex.micro_policy

### `runtime/cognitive_cycle.py`
- **LOC**: 408
- **Vai trò**: Lifecycle/tick/cycle owner cho runtime.
- **Class/dataclass chính**:
  - `CognitiveCycleMixin`
    - **Methods**: stop(self), _start_mental_process_loop(self), _stop_mental_process_loop(self), _run_mental_process_loop(self), _tick_mental_process_background(self), _mix_axis(self, previous, target), _load_mental_process_enabled(self), _load_mental_process_interval(self), _sleep_interruptible(self, seconds), run_loop(self), _load_ni_meta_mode_flags(self), _soften_chat_meta_result(self), _soften_autonomous_meta_result(self), _maybe_apply_ni_meta_critic(self)
- **Phụ thuộc nội bộ nổi bật**: cortex.contracts, cortex.internal_state, cortex.relationship_dynamics, core.evidence, cortex.modes, cortex.ni, domain, runtime.body_bias, runtime.presence_controller, runtime.speech_pipeline

### `runtime/chat_cycle.py`
- **LOC**: 1636
- **Vai trò**: Đường xử lý user chat. Nó gom burst, build source grounding report, xử lý screen request, memory recall deterministic, repeat guard, previous-public-turn repair, rồi đẩy qua speech/LLM/parser/guard. Debug khi hỏi trực tiếp mà trả vòng vo, memory recall không intercept, hoặc user gửi nhiều tin ngắn bị xử lý vụn.
- **Class/dataclass chính**:
  - `ChatCycleMixin`
    - **Methods**: _enter_chat_cycle(self), _end_chat_cycle(self), _build_relational_voice_stance(self, user_text), _build_relational_voice_seed_decision(self, user_text), _run_chat_cycle(self, user_text), _run_chat_cycle_inner(self, user_text), _recall_repair_suppression(self, user_text), _build_chat_format_block_raw(self, exc), _build_chat_format_repair_fallback_raw(self, exc), _join_debug_trace(), _queue_chat_burst_event(self, user_text, timestamp), _merge_rapid_chat_burst(self, first_text), _pop_queued_chat_events(self), _poll_ready_chat_events(self), _observe_previous_turn_feedback(self, user_text), _normalize_user_message(self, user_text), _normalize_marker_text(self, user_text), _looks_like_screen_vision_request(self, user_text), _capture_screen_frame_for_chat(self, user_text), _chat_source_grounding_screen_facts(self, snapshot), _build_chat_source_grounding_report(self), _log_chat_source_grounding(self, report), _normalize_public_reaction_text(self, text), _previous_public_turn_has_protocol_leak(self, public_turn), _user_is_challenging_previous_public_turn(self, user_text), _build_previous_public_turn_repair_decision(self), _build_grounding_preempt_decision(self, report, ti_report), _generate_grounding_preempt_text(self, report), _local_grounding_preempt_text(self, report), _build_user_message_signature(self, user_text), _track_repeated_user_message(self, user_text), _get_turn_semantics_engine(self), _build_turn_semantics_report(self), _build_repeat_guard_decision(self, user_text, ti_report, repeat_count), _should_bypass_repeat_guard_for_live_observation(self, user_text)
- **Phụ thuộc nội bộ nổi bật**: cortex.ni, cortex.conversation_dynamics, cortex.relationship_dynamics, cortex.relational_feedback, cortex.turn_semantics, domain, llm, runtime.no_fallback_policy, runtime.source_grounding, runtime.controlled_slippage

### `runtime/autonomous_cycle.py`
- **LOC**: 1241
- **Vai trò**: Đường idle/autonomous. Nó poll input, bucket idle/window spread, update vision facts, track autonomous signature, chọn speech intent và quyết định skip/hold theo ambient silence, evidence, resource pressure. Debug khi ERIS tự nói quá nhiều hoặc im quá lâu.
- **Class/dataclass chính**:
  - `AutonomousCycleMixin`
    - **Methods**: _choose_autonomous_sleep_duration(self), _process_pending_user_input(self), _run_loop_iteration(self), _load_autonomous_sleep_seconds(self, env_name), _bucket_idle_seconds(self, idle_seconds), _bucket_window_spread(self, open_windows, browser_tabs), _load_vision_fact_settings(self), _note_vision_failure(self, stage, exc), _is_low_value_screen_fact(self, fact), _speech_evidence_score(self, text), _is_speakable_evidence(self, text), _sanitize_screen_facts(self, facts), _maybe_update_screen_facts(self), _attach_screen_facts(self, snapshot, facts), _build_autonomous_signature(self, snapshot, ti_report), _track_autonomous_signature(self, snapshot, ti_report), _should_suppress_autonomous_reply(self), _has_resource_pressure_signal(self, snapshot), _is_generic_screen_event(self, event), _is_generic_screen_evidence(self, evidence), _concrete_screen_signals(self, snapshot), _concrete_vision_signals(self, snapshot), _concrete_telemetry_signals(self, snapshot), _has_concrete_screen_signal(self, snapshot), _broadcast_screen_winners(self, broadcast), _choose_autonomous_speech_intent(self), _ambient_silence_cooldown_seconds(self, snapshot, ti_report), _should_hold_ambient_silence(self), _should_skip_weak_autonomous_speech(self), _has_high_cognitive_momentum(self, thought_stream_report)
- **Phụ thuộc nội bộ nổi bật**: guard_config, cortex.contracts, cortex.internal_state, cortex.relationship_dynamics, core.evidence, cortex.modes, cortex.ni, domain, runtime.body_bias, runtime.ambient_silence_policy, runtime.presence_controller, runtime.speech_pipeline

### `runtime/force_speak_cycle.py`
- **LOC**: 497
- **Vai trò**: Lifecycle/tick/cycle owner cho runtime.
- **Class/dataclass chính**:
  - `ForceSpeakCycleMixin`
    - **Methods**: _handle_force_speak_request(self), _apply_force_speak_no_evidence_topic_filter(self, decision), _build_planned_withdraw_decision(self, action_plan)
- **Phụ thuộc nội bộ nổi bật**: cortex.contracts, cortex.internal_state, cortex.relationship_dynamics, core.evidence, cortex.modes, cortex.ni, domain, runtime.body_bias, runtime.no_fallback_policy, runtime.presence_controller, runtime.speech_pipeline

### `runtime/frame_builder.py`
- **LOC**: 1733
- **Vai trò**: Module `frame builder` trong package `runtime`.
- **Class/dataclass chính**:
  - `FrameBuilderMixin`
    - **Methods**: _make_cognitive_disturbance(self), _looks_like_closure_disturbance(self, content), _build_event_disturbances(self), _disturb_cognitive_substrate(self), _with_thought_stream_surface(self, report, surface), _pop_thought_stream_report_for_autonomous(self), _pop_subconscious_report_for_autonomous(self), _thought_stream_resonance_fragments(self), _normalize_event_evidence(self, evidence), _make_percept_event(self), _telemetry_event_privacy_level(self, kind), _telemetry_event_novelty_hint(self, kind, content), _collect_percept_events(self), _collect_cognitive_percepts(self), _score_attention_candidate(self, percept), _build_attention_candidates(self, percepts), _build_broadcast(self, candidates), _evidence_from_percepts(self, percepts), _salience_candidate_to_runtime(self, candidate), _runtime_attention_label(self, candidate, tags), _build_meaning_layer(self), _build_personality_lens(self), _apply_personality_lens_to_fe_plan(self, fe_plan, lens), _build_cognitive_appraisal(self), _build_appraisal_context(self, appraisal), _build_inner_thought(self), _build_speech_core(self), _remember_inner_thought_rhythm(self, inner_thought), _run_context_bottleneck(self, frame), _build_cognitive_evidence(self, frame), _append_working_memory_context(self, memory_context, frame), _start_cognitive_frame(self), _set_cognitive_action_plan(self, frame), _apply_micro_line_policy_to_action_plan(self, frame), _micro_policy_anchor_hints(self), _build_relational_context(self, state), _speech_intent_from_core(self, speech_core), _merge_speech_core_notes(self, notes, speech_core), _merge_meaning_layer_notes(self, notes, meaning_layer), _merge_memory_resonance_notes(self, notes, memory_resonance), _merge_inner_thought_notes(self, notes, inner_thought), _merge_personality_lens_notes(self, notes, personality_lens), _merge_subconscious_notes(self, notes, subconscious_report), _is_inner_thought_speech_act(self, speech_act)
- **Phụ thuộc nội bộ nổi bật**: cortex.contracts, cortex.internal_state, cortex.micro_policy, cortex.relationship_dynamics, core.evidence, cortex.modes, cortex.ni, domain, runtime.body_bias, runtime.presence_controller, runtime.speech_pipeline

### `runtime/presence_controller.py`
- **LOC**: 3228
- **Vai trò**: Cổng presence/micro/reengagement. Nó build `MicroPresenceCue`, dùng `SurfaceSeedCompiler`, gọi `SurfaceArbiter`, tạo body-only hoặc speech decision, có cooldown và chính sách re-engagement. Debug khi force_speak/micro presence rỗng, body-only bị tính nhầm là nói, hoặc low-level surface không nổi.
- **Class/dataclass chính**:
  - `MicroPresenceSynthesis` (decorator=dataclass(frozen=True, slots=True))
  - `SocialPresenceEvent` (decorator=dataclass(frozen=True, slots=True))
    - **Methods**: to_dict(self)
  - `MicroPresenceCue` (decorator=dataclass(frozen=True, slots=True)) — Steering flags for micro-presence, not public wording.
    - **Methods**: to_context(self)
  - `SurfaceArbitrationResult` (decorator=dataclass(frozen=True, slots=True))
  - `PresenceControllerMixin`
    - **Methods**: _surface_anchor_token(self, kind, value), _surface_vision_stale_seconds(self), _surface_has_fresh_vision_evidence(self, snapshot), _surface_wants_current_context(self), _surface_refresh_vision_once_if_needed(self), _surface_seed_can_speak_without_screen(self, compiled_seed), _stale_surface_body_only(self), _surface_seed_compiler(self), _inner_diary_for_compile(self), _surface_arbiter(self), _spontaneity_policy_config(self), _surface_arbiter_llm_generate(self), _blind_frustration_blames_user_without_evidence(self, text, impulse), _local_micro_presence_fallback_text(self), _safe_local_micro_presence_fallback(self, text), _surface_body_only_decision(self, surface), _surface_speech_decision(self, surface), _surface_override_note(self), _event_semantic_presence_detector(self), _detect_social_presence_event(self), _note_autonomous_silence(self), _note_autonomous_spoken(self), _safe_small_talk_budget_allowed(self), _surface_float(self, value, default), _surface_signed_float(self, value, default), _endogenous_topic_seed(self), _current_ego_surface_state(self), _presence_ego_gate_reason(self), _memory_resonance_surface_impulse(self), _spontaneity_level(self), _build_endogenous_surface_impulses(self), _should_allow_presence_maintenance(self), _presence_maintenance_lines(self, snapshot), _focus_family_for_snapshot(self, snapshot), _internal_curiosity_for_micro_presence(self), _derive_micro_presence_cue(self), _blind_frustration_surface_impulse(self), _body_only_presence_decision(self, cue), _is_body_only_presence_decision(self, decision), _note_autonomous_presence_action(self), _generate_micro_presence_from_cue(self), _cue_micro_lines(self), _micro_line_subject(self, value), _clean_micro_line(self, text), _vision_fact_micro_observation_candidate(self, frame), _build_micro_observation_decision(self), _try_finalize_micro_observation_cycle(self), _micro_presence_kind_from_seed(self, seed), _thought_residue_seeds(self, report), _synthesize_micro_presence(self), _choose_local_micro_line(self, lines), _local_grounded_micro_presence_text(self, synthesis), _is_placeholder_micro_text(self, text), _micro_line_policy_for_action_plan(self, frame), _micro_presence_generator(self), _should_try_micro_presence_llm(self), _sanitize_micro_presence_llm_text(self, text), _sanitize_blind_frustration_text(self, cleaned), _hybrid_micro_presence_text(self), _filter_public_micro_decision(self, decision), _build_surface_arbiter_decision(self), _build_surface_arbiter_result(self), _try_finalize_surface_arbiter_cycle(self), _build_presence_maintenance_decision(self), _try_finalize_presence_maintenance_cycle(self), _social_energy_for_reengagement(self, internal_state), _has_meaningful_recent_activity(self, snapshot), _reengagement_idle_debt_allows(self, idle_seconds), _should_allow_reengagement(self), _reengagement_lines(self, snapshot), _derive_reengagement_cue(self), _build_reengagement_decision(self), _try_finalize_reengagement_cycle(self), _load_presence_maintenance_enabled(self), _load_presence_maintenance_silent_loop_threshold(self), _load_presence_maintenance_cooldown(self), _load_micro_presence_llm_enabled(self), _load_micro_presence_llm_probability(self), _load_reengagement_enabled(self), _load_reengagement_quiet_loop_threshold(self), _load_reengagement_min_idle(self), _load_reengagement_cooldown(self)
- **Phụ thuộc nội bộ nổi bật**: cortex.contracts, cortex.banned_filler, cortex.social_presence, cortex.low_level_speech_policy, cortex.surface_arbiter, cortex.surface_seed_compiler, cortex.continuity_threat, domain, runtime.no_fallback_policy, runtime.sensor_visibility, guard_config

### `runtime/speech_pipeline.py`
- **LOC**: 79
- **Vai trò**: Module `speech pipeline` trong package `runtime`.
- **Class/dataclass chính**:
  - `SpeechIntentDecision` (decorator=dataclass(frozen=True, slots=True))
  - `SpeechPipelineMixin` — Shared finalization path for public speech decisions. Trước đây chat/autonomous/force_speak/presence tự gọi Ti/filter theo các đường riêng. Kết quả: một đường q...
    - **Methods**: _finalize_speech_decision(self, decision)

### `runtime/source_grounding.py`
- **LOC**: 1953
- **Vai trò**: Bộ phân loại nguồn trước khi trả lời: user_text, memory, file mention, current_screen/live_vision, web/action/runtime. Nó tạo missing_evidence, forbidden_assumptions, confidence cap và preempt decision. Debug khi ERIS claim thấy màn hình/file/memory hiện tại dù không có evidence.
- **Class/dataclass chính**:
  - `SourceCandidate` (decorator=dataclass(slots=True)) — Một nguồn có thể dùng để trả lời. confidence ở đây là confidence của quyền dùng nguồn, không phải confidence của câu trả lời cuối. Ví dụ: user paste code rõ ràn...
    - **Methods**: to_dict(self)
  - `SourceFallbackDecision` (decorator=dataclass(slots=True)) — Compatibility signal khi thiếu evidence. Lớp này từng chứa câu fallback public. Bản mới giữ field `text` để không phá caller cũ, nhưng SourceGroundingEngine khô...
    - **Methods**: to_payload(self), to_runtime_decision(self)
  - `MemoryAnswerProfile` (decorator=dataclass(slots=True)) — Semantic policy for memory/history questions. This is deliberately a profile, not a fallback sentence. The LLM still words the answer, while downstream layers g...
    - **Methods**: active(self), apply_cap(self, raw_confidence)
  - `SourceGroundingReport` (decorator=dataclass(slots=True)) — Báo cáo grounding nguồn cho một turn. primary_source: Nguồn chính LLM được phép dựa vào. confidence_cap: Trần confidence cho output cuối. LLM/parser/Ti nên min(...
    - **Methods**: should_fallback(self), should_preempt_llm(self), max_confidence(self), apply_cap(self, raw_confidence), to_dict(self)
  - `ClaimAnnotation` (decorator=dataclass(slots=True)) — Nhãn cho một mệnh đề bề mặt (Task 8 / R8.1). `claim_status` phản ánh GROUNDING NỘI TẠI — sự thật ERIS nắm — và KHÔNG đổi theo quan hệ/đăng ký (R7). `ground_trut...
    - **Methods**: to_dict(self)
  - `SourceGroundingEngine` — Bộ phân loại grounding nguồn cho runtime. Cách dùng tối thiểu: report = SourceGroundingEngine().analyze(user_text, frame=frame) frame.source_grounding = report...
    - **Methods**: analyze(self, user_text), classify(self), analyze_frame(self, frame), apply_confidence_cap(self, raw_confidence, report_or_frame), should_preempt(self, report_or_frame), render_prompt_context(self, report), annotate_claims(self, text), _is_epistemic_curiosity_gap(self, report), build_fallback_decision(self, report), build_preemptive_reply(self, report), _derive_memory_answer_profile(self), _split_grounding_clauses(self, text), _is_self_disclosure_clause(self, clause), _looks_like_question(self, normalized), _has_actionable_web_reference(self, normalized, raw_text), _choose_primary_source(self, candidates), _cap_for(self, primary), _derive_missing_evidence(self, primary, candidates), _derive_forbidden_assumptions(self), _derive_answer_style_rules(self, primary), _derive_preempt_mode(self), _detect_file_mentions(self, text, normalized), _detect_explicit_screen_request(self, normalized), _has_deictic_reference(self, normalized), _looks_like_file_content_request(self, normalized), _detect_pasted_code(self, text), _guess_code_language(self, text), _collect_file_evidence(self), _collect_screen_evidence(self), _collect_memory_evidence(self), _collect_user_text_evidence(self), _summarize_evidence_items(self, items), _preview_item(self, item), _extract_user_text_from_frame(self, frame), _mapping_get(obj, key, default), _read_float(obj, key), _normalize(cls, text), _has_any(cls, normalized_text, markers), _as_list(value), _dedupe(items), _safe_setattr(obj, key, value), _clamp01(value)

### `runtime/post_generation_filters.py`
- **LOC**: 1938
- **Vai trò**: Hàng rào cuối trước public output. Chặn prompt leak, debug leak, memory haunting, unsupported current-screen claim, over-mindreading, register sai và micro-line xấu. Debug khi câu đúng bị flatten hoặc câu rác lọt ra body.
- **Class/dataclass chính**:
  - `PostGenerationFiltersMixin` — Post-generation filters after the cognition/wording layers. This mixin should not be the personality author. It keeps hard grounding boundaries and records soft...
    - **Methods**: _guard_mode_value(self, name), _guard_is_off(self, name), _guard_is_log_only(self, name), _trace_only_guard(self, decision, marker), _remember_guard_violation(self, violation), _guard_internal_state_values(self), _guard_internal_state_context(self), _dynamic_guard_bottom_fallback(self, violation), _guard_arbitration_context(self, speech_core), _guard_body_only_decision(self, decision, violation), _guard_grounding_context(self, frame, grounding), _guard_reroll_is_clean(self, text, violation), _repair_guard_violation_decision(self, decision, violation), _record_agent_mind_feedback_from_user(self, user_text), _normalize_guard_ascii(self, text), _reroll_still_disclaimer(self, text), _detect_chat_disclaimer(self, text), _apply_chat_disclaimer_guard(self, decision), _apply_chat_final_guards(self, decision), _append_trace(self, trace, marker), _protocol_surface_leak_markers(self), _detect_protocol_surface_leak(self, text), _protocol_surface_repair_text(self), _apply_protocol_surface_guard(self, decision), _detect_internal_object_surface_leak(self, text), _internal_object_surface_repair_text(self), _apply_internal_object_surface_guard(self, decision), _apply_memory_haunting_guard(self, decision), _guard_recent_context_as_screen_observation(self, decision), _apply_chat_grounding_guard(self, decision), _is_repeated_clarifying_question(self, text, last_assistant_text), _guard_text_similarity(self, left, right), _normalize_guard_text(self, text), _looks_like_file_grounded_claim(self, text), _looks_like_screen_grounded_claim(self, text), _looks_like_live_web_claim(self, text), _guard_user_explained_reason(self, text), _build_relational_repair_line(self, user_text, last_assistant_text), _copy_decision_with_text(self, decision), _semantic_repair_failed_decision(self, decision), _inner_thought_alignment_fallback_text(self, speech_core, intent), _apply_inner_thought_intent_alignment_filter(self, decision), _contains_mindreading_claim(self, text), _is_interactive_guess_text(self, text), _source_grounding_allows_probe(self), _interactive_guess_allowed(self, text), _speech_core_safe_fallback_text(self, speech_core), _arbitration_report_from_speech_core(self, speech_core), _selected_impulse_from_arbitration(self, report), _arbitration_selected_has_evidence(self, selected), _mindreading_is_grounded_task_or_scene(self, text), _arbitration_rewrite_for_mindreading(self), _apply_anti_mindreading_filter(self, decision), _guard_force_speak_repetition(self, decision), _apply_repetition_filter(self, decision), _looks_like_unanchored_style_line(self, text), _apply_style_contract_filter(self, decision), _policy_intent_for_speech_core(self, speech_core), _apply_micro_line_policy_filter(self, decision), _apply_post_generation_filters(self, decision), _apply_internal_meaning_label_filter(self, decision)
- **Phụ thuộc nội bộ nổi bật**: cortex.contracts, domain, guard_config, runtime.controlled_slippage, runtime.guard_violations, runtime.disclaimer_markers

### `runtime/model_budget_policy.py`
- **LOC**: 894
- **Vai trò**: Scheduler/gatekeeper model. Quản tier main/subconscious/vision/sensory, lease, queue, resource snapshot, cooldown, active heavy lock. Debug khi model chạy chồng, local GGUF/vision/daydream tranh tài nguyên, hoặc request kẹt queue.
- **Class/dataclass chính**:
  - `ResourceSnapshot` (decorator=dataclass(slots=True))
    - **Methods**: vram_percent(self), resource_pressure(self), to_dict(self)
  - `BudgetDecision` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self)
  - `ModelQueueEntry` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self)
  - `InferenceLease` (decorator=dataclass(slots=True))
    - **Methods**: age_seconds(self), cancelled(self), check_cancelled(self), to_dict(self)
  - `ModelBudgetPolicyConfig` (decorator=dataclass(slots=True))
  - `ModelBudgetPolicy` — Budget gatekeeper + scheduler nhẹ cho model inference. Đây chưa phải Kubernetes mini. Nó không thể giết request HTTP đã bay vào provider ngoài, vì Python không...
    - **Methods**: __init__(self, config, logger), capture(self), can_run(self, tier), lease(self, tier), run_queued(self, tier, func), acquire_lease(self, tier), release_lease(self, lease), cancel_queued_request(self, request_id), cancel_all_queued(self), queue_state(self), mark_started(self, tier), mark_finished(self, tier), veto_or_raise(self, tier), _cooldown_for(self, tier, now), _capture_nvidia_smi(self, notes), _is_heavy_tier(self, tier), _uses_remote_api(self, tier), _should_force_vision(self, tier), _should_force_local_gguf_main(self, tier), _estimated_vram_need_mb(self, tier), _should_bypass_vision_vram_guard(self, tier), _reserved_vram_for_active_leases_locked(self), _active_reserved_vram_mb(self, snapshot), _has_incompatible_active_lease(self, tier), _resource_block_reasons(self, tier), _entry_cancelled(self, entry), _sort_queue_locked(self), _queue_head_locked(self), _remove_queue_entry_locked(self, request_id), _has_incompatible_active_lease_locked(self, tier), _wait_seconds(self, entry, now), _log(self, level, msg)
- **Hàm module-level**: _clamp01(value, default), _safe_float(value, default), _env_float(name, default), _env_flag(name, default), _env_int(name, default)

### `runtime/autonomous_wake_governor.py`
- **LOC**: 262
- **Vai trò**: Trọng tài mức thức: sleep, observe_only, think_only, micro_presence, call_vision_compressor, wake_main_cognition. Tính external pressure, internal drive, permission, speech value, interrupt cost và budget. Debug khi đáng gọi main nhưng bị degrade xuống micro/think hoặc silence debt không đủ kéo surface.
- **Class/dataclass chính**:
  - `WakeDecision` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self)
  - `WakeGovernorConfig` (decorator=dataclass(slots=True))
  - `AutonomousWakeGovernor` — Trọng tài wake state.
    - **Methods**: __init__(self, config), decide(self), _budget(self, policy, tier, snapshot, reason)
- **Hàm module-level**: _clamp01(value, default)

### `runtime/contextual_autonomy_loop.py`
- **LOC**: 236
- **Vai trò**: src/runtime/contextual_autonomy_loop.py ====================================== Adaptive heartbeat cho 3-tier autonomy. Module này gom các mảnh: - UserContextStream (tầng cảm giác / 0.6B + rules) - EndogenousDriveEngine (...
- **Class/dataclass chính**:
  - `ContextualAutonomyLoopConfig` (decorator=dataclass(slots=True))
  - `AutonomyLoopTickResult` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self)
  - `ContextualAutonomyLoop` — Backbone điều phối 3 tầng, gọi được từ coordinator.
    - **Methods**: __init__(self), tick(self), _maybe_run_growth_tick(self), next_sleep_seconds(self, decision)

### `runtime/private_mind_loop.py`
- **LOC**: 767
- **Vai trò**: Private mind 5 phase: ConcernStore, EvidenceDossierBuilder, MiniEvaluatorPipeline, GemmaInnerSynthesizer, StateMutationBus, SurfaceValve. Không tự nói; nó tạo mutation/state/surface impulse nếu được phép. Debug khi ERIS có thought/private concern nhưng hành vi tương lai không đổi.
- **Class/dataclass chính**:
  - `PrivateMindLoopConfig` (decorator=dataclass(slots=True))
  - `PrivateMindLoop` — Orchestrator của private mind.
    - **Methods**: __init__(self), from_runtime(cls), tick(self), _capture_affect(self, runtime_owner), _followup_fragments(self, dossier), _record_continuity(self, judgment), digest(self), _diary_voice(self, digest), drain_surface_impulses(self, queue), _model_api_status(self), _resolve_concern_path(self), _resolve_user_model_path(self), _resolve_anchor_journal_path(self), _build_anchor_block(self), _maybe_journal_anchor(self, block), _update_anchor_system(self), _anchor_irritation(runtime_owner), _anchor_internal_state(runtime_owner), _log_anchor_warning(self, exc), _log_tick(self, result)
- **Hàm module-level**: _env_flag(name, default)
- **Phụ thuộc nội bộ nổi bật**: cortex.private_mind, cortex.existential_anchor, cortex.private_mind.contracts, cortex.private_mind.inner_diary_renderer, cortex.private_mind.inner_diary_writer, eris_secrets, runtime.private_mind_model_adapter

### `runtime/private_mind_daemon.py`
- **LOC**: 433
- **Vai trò**: Lifecycle owner của PrivateMindLoop. Giữ tick digest, queues, surface impulses, outcome. Debug khi private_mind_loop chạy rời rạc, digest mất hoặc inner diary không persist.
- **Class/dataclass chính**:
  - `PrivateMindDaemonConfig` (decorator=dataclass(slots=True)) — Knob lifecycle cho private mind daemon. Ghi chú tiếng Việt để lúc debug không phải đoán ý đồ của người viết cũ, tức chính chúng ta ở tương lai với ít ngủ hơn.
  - `PrivateMindDaemonTick` (decorator=dataclass(slots=True)) — Kết quả tick ở tầng daemon. `loop_result` giữ payload sâu; daemon thêm lifecycle metadata để debug vì private cognition mà không có trace thì lại thành bói toán...
    - **Methods**: to_dict(self)
  - `PrivateMindDaemon` — Lifecycle owner cho PrivateMindLoop. Trách nhiệm của daemon: 1. Không sinh lời thoại public. 2. Giữ concern/outcome sống qua nhiều tick. 3. Đưa mutation sang ru...
    - **Methods**: __init__(self), from_runtime(cls), concern_store(self), mutation_bus(self), tick(self), record_outcome(self, outcome), _attach_comfort_appraisal(self, outcome), _extract_feedback_text(outcome), _extract_flag(outcome, name), _inject_comfort(outcome, comfort), _disposition_warmth_threat(self), drain_surface_impulses(self), digest(self), _merged_surface_outcome(self, surface_outcome), _surface_outcome_from_frame(self, frame), _trim_surface_queue(self, queue), _surface_preview(self, item), _sync_runtime_owner(self), _log(self, level, message)
- **Phụ thuộc nội bộ nổi bật**: cortex.private_mind.contracts, cortex.private_mind.comfort_appraiser, runtime.private_mind_loop

### `runtime/private_mind_model_adapter.py`
- **LOC**: 1664
- **Vai trò**: runtime/private_mind_model_adapter.py ===================================== Adapter API cho private mind: - evaluate_fragment(evaluator_name, dossier) - synthesize_judgment(dossier, fragments) Adapter này ưu tiên dùng `l...
- **Class/dataclass chính**:
  - `PrivateMindModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True))
    - **Methods**: fragment_overlay_from_env(cls, base)
  - `PrivateMindModelResult` (decorator=dataclass(slots=True))
  - `RuntimePrivateMindModelAdapter` — Adapter chung cho 4 mini-evaluator và GemmaInnerSynthesizer.
    - **Methods**: __init__(self), _current_api_key(self), _rotate_to_next_key(self), from_env(cls), diary_fallback_from_env(cls), min_interval_seconds(self), evaluate_fragment(self, evaluator_name, dossier), _freetext_fragment(self, evaluator_name, dossier), _freetext_fragment_messages(self, evaluator_name, dossier), _guard_freetext_fragment(self, content), _wrap_freetext_fragment(self, evaluator_name, claim, dossier), _tracked_chat_text(self, messages), _chat_text_with_transient_retry(self, messages), _chat_text_once(self, messages), synthesize_judgment(self, dossier, fragments), appraise_comfort(self, user_text, concern_themes), _comfort_messages(self, user_text, concern_themes), _comfort_response_schema(self), write_inner_diary(self, facts), _diary_messages(self, facts), _diary_response_schema(self), _slice_for_intent(self, dossier), _slice_for_memory_resonance(self, dossier), _slice_for_risk(self, dossier), _slice_for_future_bias(self, dossier), _fragment_messages(self, evaluator_name, dossier), _slice_for_user_model(self, dossier), _slim_dossier(self, dossier), _slim_fragment(self, f), _judgment_messages(self, dossier, fragments), _fragment_response_schema(self, evaluator_name), _judgment_response_schema(self), debug_status(self), _tracked_chat_json(self, messages), _json_cooldown_active(self), _maybe_enter_json_cooldown(self), _synthesis_json_cooldown_active(self), _maybe_enter_synthesis_json_cooldown(self), _transient_cooldown_active(self), _maybe_enter_transient_cooldown(self), _extract_usage(self, raw), _chat_json(self, messages), _chat_json_with_transient_retry(self, messages), _chat_json_once(self, messages), _response_format(self, response_schema), _json_repair_messages(self, messages, invalid_content), _provider_chat_json(self, messages), _provider_client_or_build(self), _extract_content(self, raw), _parse_json(self, content), _json_candidates(self, text), _strip_markdown_fences(self, text), _extract_first_json_object(self, text), _extract_repairable_json_object(self, text), _salvage_truncated_json(self, text), _collapse_repetition_in_obj(self, obj), _collapse_repetition(self, text), _ends_inside_string(self, text), _json_object_balance(self, text), _loads_json_object(self, candidate), _repair_common_json_noise(self, text), _safe_raw(self, raw), _log(self, level, msg)
  - `PrivateMindAdapterPool` — Pool adapter cho private mind. Thay vì một instance dùng chung cho tất cả, mỗi vai trò có adapter riêng: - 4 adapter cho 4 fragment evaluator (chạy song song, s...
    - **Methods**: __init__(self), from_env(cls), fragment_adapter(self, evaluator_name), synthesis_adapter(self), evaluate_fragment(self, evaluator_name, dossier), synthesize_judgment(self, dossier, fragments), write_inner_diary(self, facts), debug_status(self)
- **Hàm module-level**: _env_flag(name, default), _as_float(value, default), _classify_transport_exception(exc)
- **Phụ thuộc nội bộ nổi bật**: cortex.private_mind.contracts, eris_secrets, llm.client, llm.llamacpp_client, llm.key_pool

### `runtime/private_life_daemon.py`
- **LOC**: 332
- **Vai trò**: Lifecycle owner của PrivateLifeCore. Đẩy habitat/project/rhythm/solitude vào runtime, sinh digest và surface seed. Debug khi đời sống riêng không cập nhật hoặc vẫn bị neo 100% vào user.
- **Class/dataclass chính**:
  - `PrivateLifeDaemonConfig` (decorator=dataclass(slots=True))
    - **Methods**: from_env(cls)
  - `PrivateLifeDaemonTick` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self)
  - `PrivateLifeDaemon` — Lifecycle owner cho PrivateLifeCore.
    - **Methods**: __init__(self), from_runtime(cls), tick(self), drain_surface_impulses(self), digest(self), _maybe_enqueue_surface_seed(self, seed), _seed_to_surface_impulse(self, seed), _infer_idle(self), _sync_runtime_owner(self), _impulse_digest(item)
- **Hàm module-level**: _value(obj, name, default), _env_bool(name, default), _env_float(name, default), _infer_project_root()
- **Phụ thuộc nội bộ nổi bật**: cortex.private_life, cortex.private_life.contracts

### `runtime/state_commit_service.py`
- **LOC**: 872
- **Vai trò**: Module `state commit service` trong package `runtime`.
- **Class/dataclass chính**:
  - `StateCommitServiceMixin`
    - **Methods**: _memory_kernel(self), _ensure_session_turn_ledger(self), _ensure_memory_commit_policy(self), _ensure_memory_fast_commit_policy(self), _background_memory_digest_enabled(self), _enqueue_background_memory_digest(self, user_text), _set_background_memory_digest_remote_inflight(self, inflight), _memory_snapshot_for_lookup(self), _memory_snapshot_items(self, snapshot, collection_name), _record_value(record, field_name, default), _record_metadata(self, record), _clean_memory_value(value), _extract_semantic_value_from_record(self, record, kind), _semantic_memory_lookup(self, kind), _fact_key_for_memory_kind(kind), _semantic_record_rank(self, record), _episodic_memory_lookup(self, query), _ensure_memory_recall_adapter(self), _build_memory_recall_decision(self, user_text), _ensure_relational_voice_seed_adapter(self), _ensure_affect_self_read_adapter(self), _frame_memory_storage_permission(self, frame), _user_turn_memory_evidence_id(self), _ingest_user_turn_via_memory_kernel(self, frame, user_text), _add_user_turn_memory_commit_requests(self, frame, user_text), _load_memory_state(self), _has_structured_memory_core(self), _ensure_internal_state(self), _get_internal_state(self), _set_internal_state(self, state), _load_internal_state_payload(self), _send_decision_to_body(self, decision), _record_public_turn(self, decision), _build_body_bias_payload(self), _body_bias_clamp(value), _normalize_body_focus_kind(value), _save_memory_state(self), _memory_recall_packet(self), _memory_recall_texts(self), _recall_memory_resonance(self), _memory_attention_lines(self), _norm_deviation_texts(self, snapshot), _note_norm_observation(self, snapshot), _memory_query_from_snapshot(self, snapshot), _event_timestamp(self, snapshot), _commit_chat_decision(self, decision, fe_plan), _apply_position_update(self, decision), _build_silent_motion_decision(self, ti_report), _build_direct_action_decision(self, user_text, ti_report, snapshot), _execute_system_action(self, decision), _action_animation_hint(self, action_name, fallback), _action_result_to_text(self, result), _resolve_now_playing_text(self, snapshot), _extract_media_title_from_snapshot(self, snapshot), _extract_media_title(self, raw_title)
- **Hàm module-level**: _is_nonsemantic_fallback_decision(decision)
- **Phụ thuộc nội bộ nổi bật**: cortex.contracts, cortex.internal_state, memory.memory_commit_policy, memory.memory_models, cortex.relationship_dynamics, core.evidence, cortex.modes, cortex.ni, domain, runtime.body_bias, runtime.memory_recall_adapter, runtime.relational_voice_seed_adapter, runtime.affect_self_read, runtime.presence_controller, runtime.public_turn_ledger, runtime.session_turn_ledger, runtime.speech_pipeline

### `runtime/state_committer.py`
- **LOC**: 1110
- **Vai trò**: src/runtime/state_committer.py ================================ StateCommitter là cổng commit state/memory của ERIS. Nguyên tắc chính: - Không module runtime nào được ghi thẳng vào memory. - Module chỉ được tạo StateComm...
- **Class/dataclass chính**:
  - `StateCommitterConfig` (decorator=dataclass(slots=True)) — Cấu hình ngưỡng commit. Giữ ở dataclass để sau này Ngài tune bằng config/env thay vì rải magic number. Magic number là cách người ta biến cognition thành bùa ch...
  - `CommitValidationIssue` (decorator=dataclass(slots=True)) — Một vấn đề phát hiện trong quá trình validate.
    - **Methods**: to_dict(self)
  - `CommitDecision` (decorator=dataclass(slots=True)) — Kết quả kiểm định một request. `normalized_request` là request đã được chuẩn hóa/reroute/đánh tentative nếu cần. Nếu `accepted=False`, tuyệt đối không được đưa...
    - **Methods**: to_dict(self)
  - `CommitBatchReport` (decorator=dataclass(slots=True)) — Audit report cho một lần StateCommitter.commit(...).
    - **Methods**: duration_ms(self), finish(self), to_dict(self)
  - `StateCommitter` — Cổng commit chính cho runtime. Usage chuẩn trong CognitiveRuntime: self.state_committer = StateCommitter(self.memory_cognition) ... self.state_committer.commit(...
    - **Methods**: __init__(self, memory_cognition), commit(self, frame_or_requests), commit_frame(self, frame), commit_requests(self, requests), validate(self, request), _commit_one(self, decision, frame), _call_memory_commit(self, request), _extract_requests(self, frame_or_requests), _maybe_frame(self, value), _looks_like_commit_request(self, value), _clone_request(self, request), _build_evidence_index(self, frame), _contains_private_raw_evidence(self, request, evidence_ids, evidence_index), _semantic_grounding_issue(self), _frame_permission_flag(self, frame, field_name), _looks_like_user_correction(self, request, content, reason, tags, metadata), _confidence_thresholds(self, target), _attach_report_to_frame(self, frame, report), _frame_id(self, frame), _dedup_key(self, request)
- **Hàm module-level**: _safe_float(value, default), _safe_bool(value, default), _as_list_str(value), _get(obj, name, default), _set_if_possible(obj, name, value), _content_is_empty(content), _normalize_target(target), _normalize_decay_policy(value), _request_metadata(req), _request_tags(req)
- **Phụ thuộc nội bộ nổi bật**: core.evidence

### `runtime/memory_recall_adapter.py`
- **LOC**: 459
- **Vai trò**: Adapter nối runtime với engine/model/store khác trong runtime.
- **Class/dataclass chính**:
  - `_MemoryQueryLLMConfig` (decorator=dataclass(frozen=True, slots=True))
    - **Methods**: from_env(cls)
  - `MemoryRecallAdapter` (decorator=dataclass(slots=True)) — Runtime adapter for structured memory recall. The public contract is intentionally simple: return a ready-to-send Decision before chat falls through to the gene...
    - **Methods**: try_answer(self, user_text), try_answer_as_decision_payload(self, user_text), _recall(self, user_text), _should_intercept(self, best), _ensure_compiler(self), _execution_memory_core(self), _build_decision(self, answer), _debug_trace(self, answer)
  - `_RecallOutcome` (decorator=dataclass(slots=True))
  - `_MemoryCoreProxy`
    - **Methods**: __init__(self), lookup_fact(self, fact_key), get_fact(self, fact_key), semantic_lookup(self, fact_key), recall(self, query), __getattr__(self, name)
  - `_RuntimeMemoryQueryLLMClient` (decorator=dataclass(slots=True); base=MemoryQueryLLMClient)
    - **Methods**: from_service(cls, service), complete_json(self), _passes_confidence_floor(self, raw)
- **Hàm module-level**: _extract_response_text(response), _clean_public_fact_value(value), _looks_like_internal_memory_surface(text), _env_flag(name), _env_int(name), _env_float(name)

### `runtime/memory_semantic_parser_adapter.py`
- **LOC**: 363
- **Vai trò**: Adapter nối runtime với engine/model/store khác trong runtime.
- **Class/dataclass chính**:
  - `_StandaloneOllamaResult` (decorator=dataclass(slots=True))
  - `_StandaloneOllamaClient` — Client Ollama tối thiểu cho memory parser, tránh import package llm.
    - **Methods**: __init__(self, base_url, timeout), chat_json(self, model, messages)
  - `MemorySemanticParserConfig` (decorator=dataclass(frozen=True, slots=True))
    - **Methods**: from_env(cls)
  - `RuntimeSemanticParser` (decorator=dataclass(slots=True)) — Adapter runtime -> MeaningFrame JSON -> verified MeaningParseResult.
    - **Methods**: __post_init__(self), from_env(cls), parse(self, text), _call_provider(self, text), _call_ollama(self, text), _call_llm_service(self, text), _messages(self, text), _log_warning(self, message)
- **Hàm module-level**: build_runtime_memory_semantic_parser(), _extract_response_text(response), _parse_json_object(text), _env_flag(name, default), _env_float(name, default), _env_int(name, default)
- **Phụ thuộc nội bộ nổi bật**: memory.understanding.semantic_parser

### `runtime/subconscious_loop.py`
- **LOC**: 412
- **Vai trò**: Runtime adapter cho subconscious blackboard/synthesizer. Phase 0 dựng ThoughtFragment/Blackboard/Synthesizer. Phase 1-4 thêm worker nội tâm nền. Phase 5 thêm MetaAudit có quyền dọn Blackboard. Phase 6 thêm BeliefMutation...
- **Class/dataclass chính**:
  - `SubconsciousTickResult` (decorator=dataclass(slots=True, frozen=True)) — Kết quả một tick subconscious.
    - **Methods**: to_dict(self)
  - `SubconsciousLoop` — Vòng nền tối thiểu cho worker subconscious. Loop này không tự quyết định nói. Nó sinh `ThoughtObject`, `surface_seed`, và `audit_report`. SurfaceArbiter/Permiss...
    - **Methods**: __init__(self), submit(self, fragment), tick(self), latest_report(self), _inner_court_report_payload(self), pop_surface(self), stop(self), _context_with_snapshot(self), _run_workers(self, context), _run_audit_workers(self, context), _compose_report(self, thought_object, surface_seed), _surface_from_seed(self, surface_seed, thought_object)
- **Phụ thuộc nội bộ nổi bật**: cortex.contracts, cortex.subconscious, cortex.subconscious.worker_base, cortex.subconscious.thought_fragment

### `runtime/subconscious_model_adapter.py`
- **LOC**: 334
- **Vai trò**: Adapter gọi model/API riêng cho Lane 3 subconscious synthesis. Lane 3 không sinh lời thoại public. Nó chỉ lập một "biên bản phiên toà nội tâm": - các mảnh nào đang tranh nhau ý nghĩa, - bên công tố/biện hộ nhìn thấy gì,...
- **Class/dataclass chính**:
  - `SubconsciousModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True)) — Cấu hình riêng cho Lane 3 API synthesis. Ưu tiên cấu hình: 1. Env ERIS_LANE3_* 2. config/secrets.json -> agent_keys.lane3_synthesis 3. config/secrets.json -> pr...
  - `SubconsciousModelResult` (decorator=dataclass(slots=True, frozen=True))
  - `RuntimeSubconsciousModelAdapter` — Client mỏng cho Lane 3. Không dùng để trả lời user. Không được gọi từ public speech path trực tiếp. Nó chỉ trả JSON riêng tư cho ModelBackedConsciousSynthesizer...
    - **Methods**: __init__(self), from_env(cls), synthesize(self, messages), _resolve_profile(self), _resolve_model(self), _resolve_base_url(self), _resolve_api_key(self), _build_client(self), _extract_content(self, raw), _parse_json_object(self, text), _safe_raw(self, raw), _log(self, level, msg)
- **Hàm module-level**: _env_flag(name, default), _as_float(value, default), _cfg_flag(path, default)
- **Phụ thuộc nội bộ nổi bật**: eris_secrets, llm.client

### `runtime/daydream_model_adapter.py`
- **LOC**: 101
- **Vai trò**: Adapter nối runtime với engine/model/store khác trong runtime.
- **Class/dataclass chính**:
  - `DaydreamModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True))
  - `DaydreamModelResult` (decorator=dataclass(slots=True, frozen=True))
  - `RuntimeDaydreamModelAdapter` — Adapter riêng cho daydream 4B, không ké style client.
    - **Methods**: __init__(self), from_env(cls), chat_json(self, model, messages), _from_ollama_result(self, result), _log(self, level, msg)
- **Hàm module-level**: _env_flag(name, default)
- **Phụ thuộc nội bộ nổi bật**: llm.ollama_client

### `runtime/sensory_model_adapter.py`
- **LOC**: 147
- **Vai trò**: Adapter nối runtime với engine/model/store khác trong runtime.
- **Class/dataclass chính**:
  - `SensoryModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True))
  - `RuntimeSensoryModelAdapter` — Adapter riêng cho tầng cảm giác 0.6B.
    - **Methods**: __init__(self), from_env(cls), observe(self), _prompt(self), _schema(self), _log(self, level, msg)
- **Hàm module-level**: _env_flag(name, default)
- **Phụ thuộc nội bộ nổi bật**: llm.ollama_client

### `runtime/thought_model_adapter.py`
- **LOC**: 84
- **Vai trò**: runtime/thought_model_adapter.py ================================ Compatibility adapter cho ThoughtStream model review. Một số bản coordinator đã import RuntimeThoughtModelAdapter nhưng zip hiện tại không có file này. Th...
- **Class/dataclass chính**:
  - `ThoughtModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True))
  - `RuntimeThoughtModelAdapter`
    - **Methods**: __init__(self), from_env(cls), review(self, payload)
- **Hàm module-level**: _env_flag(name, default)
- **Phụ thuộc nội bộ nổi bật**: runtime.private_mind_model_adapter

### `runtime/body_bias.py`
- **LOC**: 116
- **Vai trò**: Module `body bias` trong package `runtime`.
- **Class/dataclass chính**:
  - `BodyBiasProjector` — Projects cognitive state into the compact body-bias payload Godot consumes.
    - **Methods**: __init__(self, state_provider), build_payload(self, observer_frame, impulse_hint), clamp(value), normalize_focus_kind(value)
- **Phụ thuộc nội bộ nổi bật**: cortex.internal_state

### `runtime/outcome_observer.py`
- **LOC**: 557
- **Vai trò**: Module `outcome observer` trong package `runtime`.
- **Class/dataclass chính**:
  - `OutcomeReport` (decorator=dataclass(slots=True)) — Báo cáo hậu quả sau một turn. Các field lõi bám theo ERIS Cognitive Pipeline: - user_accepted: user có chấp nhận/đồng ý với câu trả lời không. `None` nghĩa là c...
    - **Methods**: to_dict(self), from_any(cls, value)
  - `OutcomeObserver` — Đọc tín hiệu hậu quả sau một turn. Cách dùng thường gặp: outcome = outcome_observer.observe(frame) frame.outcome = outcome Nếu muốn đánh giá phản ứng user đối v...
    - **Methods**: observe(self, frame), observe_user_feedback_for_previous_frame(self, previous_frame, user_feedback_text), _infer_action_success(self, frame), _infer_body_match_success(self, frame), _estimate_confidence(self), _normalize(cls, text), _has_any(cls, normalized_text, patterns), _extract_final_text(frame), _extract_system_action(frame), _read_bool(obj, key), _read_float(obj, key), _safe_setattr(obj, key, value), _clamp01(value)

### `runtime/cognitive_pipeline.py`
- **LOC**: 295
- **Vai trò**: runtime/cognitive_pipeline.py Xương sống Phase 1 của ERIS V3. Mục tiêu của file này là biến mớ module rời rạc thành MỘT đường chạy có thật: RawSignal -> EvidenceItem (EvidenceNormalizer) # Phase: contract -> CognitiveFra...
- **Class/dataclass chính**:
  - `PipelineResult` (decorator=dataclass(slots=True)) — Kết quả một lần chạy pipeline. Giữ cả frame lẫn vài tham chiếu nhanh để caller/test khỏi phải đào lại frame.
    - **Methods**: budget_mode(self)
  - `CognitivePipeline` — Chạy Phase 1 trên CognitiveFrame core. Dùng: pipeline = CognitivePipeline() result = pipeline.run_from_signals( [RawSignal.from_chat("ERIS, build gì tiếp cho V3...
    - **Methods**: __init__(self), run_from_signals(self, raw_signals), run(self, frame), _set_slot(self, frame, slot_name, value), _safe_call(obj, method), _salience_confidence(salience), _budget_report(decision), _infer_user_text(raw_signals)
- **Phụ thuộc nội bộ nổi bật**: core.cognitive_frame, core.evidence, core.evidence_normalizer, cortex.attention_salience, cortex.working_memory, cortex.global_workspace, runtime.cognitive_budget, runtime.debug_trace

### `runtime/cognitive_budget.py`
- **LOC**: 2706
- **Vai trò**: src/runtime/cognitive_budget.py ================================ Bộ chọn Cognitive Budget cho ERIS. Mục tiêu: Chọn đường chạy nhận thức cho mỗi CognitiveFrame: - fast - normal - deep - reflection Vì sao cần file này: Att...
- **Class/dataclass chính**:
  - `BudgetModeProfile` (decorator=dataclass(slots=True)) — Thông số tài nguyên cho một budget mode. Đây là thứ downstream nên đọc thay vì tự đoán: - WorkingMemory nên giữ bao nhiêu slot? - Workspace nên broadcast bao nh...
    - **Methods**: to_dict(self)
  - `BudgetSignalSnapshot` (decorator=dataclass(slots=True)) — Ảnh chụp các áp lực dùng để chọn budget. Mỗi field là pressure 0..1. Cái này không phải cảm xúc, không phải phán xét, không phải thần dụ. Nó chỉ là bảng điện áp...
    - **Methods**: pressure_max(self), task_pressure(self), reflection_pressure(self), to_dict(self)
  - `BudgetScoreBreakdown` (decorator=dataclass(slots=True)) — Điểm cạnh tranh giữa các mode. Chọn budget không nên là if-else mù. Breakdown giúp debug vì sao một frame bị nâng từ normal lên deep hoặc hạ xuống fast.
    - **Methods**: as_ranked(self), to_dict(self)
  - `PipelineStepDecision` (decorator=dataclass(slots=True)) — Quyết định chạy/bỏ qua một bước pipeline.
    - **Methods**: to_dict(self)
  - `BudgetPlan` (decorator=dataclass(slots=True)) — Kế hoạch chạy pipeline dựa trên budget. Đây là phần quan trọng hơn cả label mode. Label `deep` mà không nói module nào được chạy thì vẫn chỉ là huy hiệu trang t...
    - **Methods**: should_run(self, step_name), step(self, step_name), to_dict(self)
  - `BudgetDecision` (decorator=dataclass(slots=True)) — Kết quả cuối của CognitiveBudgetEngine.
    - **Methods**: to_dict(self), to_json(self), render_debug_summary(self)
  - `CognitiveBudgetConfig` (decorator=dataclass(slots=True)) — Cấu hình của CognitiveBudgetEngine. Giữ trong dataclass để sau này Ngài có thể load từ JSON/YAML. Xin đừng rải magic number khắp coordinator, đó là nghi lễ triệ...
    - **Methods**: profiles(self)
  - `CognitiveBudgetEngine` — Chọn cognitive budget cho một frame. Đầu vào chính là CognitiveFrame. Engine đọc bằng duck-typing: frame.evidence frame.salience frame.working_memory frame.work...
    - **Methods**: __init__(self, config), choose(self, frame), choose_mode(self, frame), build_plan(self, mode, frame), _extract_snapshot(self, frame), _collect_text_blob(self, frame), _extract_user_text_from_signals(self, raw_signals, evidence), _estimate_user_directness(self, channel, user_text, evidence, raw_signals, text_blob), _estimate_signal_density(self, evidence, raw_signals, salience, working_memory, workspace), _estimate_salience_priority(self, salience), _estimate_context_pressure(self, working_memory, workspace, salience, evidence), _semantic_number(self, obj), _evidence_tag_score(self, evidence, tags), _source_grounding_score(self, source_grounding, sources), _meaning_support(self, meaning, keywords), _estimate_risk_pressure(self, text_blob, salience, workspace, permission, tom), _estimate_privacy_pressure(self, text_blob, evidence, workspace, permission), _estimate_technical_depth(self, text_blob, evidence, meaning), _estimate_architecture_depth(self, text_blob, evidence, meaning), _estimate_correction_pressure(self, text_blob, evidence, outcome, self_observation), _estimate_contradiction_pressure(self, text_blob, evidence, belief, self_observation), _estimate_relational_rupture(self, text_blob, relation, outcome, self_observation), _estimate_affective_residue(self, text_blob, affect, relation), _estimate_homeostasis_load(self, homeostasis, affect), _estimate_goal_pressure(self, frame, text_blob), _estimate_memory_conflict(self, text_blob, memory_packet, belief, self_observation), _estimate_worldview_pressure(self, text_blob, belief), _estimate_uncertainty(self, tom, meaning, salience, workspace), _estimate_ambiguity(self, meaning, tom, text_blob), _estimate_idle_pressure(self, temporal, homeostasis, idle_seconds), _estimate_session_closing_pressure(self, text_blob, temporal), _estimate_reflection_debt(self, text_blob, outcome, self_observation, relation, affect), _estimate_speech_need(self, frame, channel, user_directness, salience_priority, text_blob), _estimate_body_need(self, frame, workspace, text_blob), _estimate_low_stakes_ambient(self), _estimate_high_value_decision(self, text_blob, technical_depth, architecture_depth, semantic_support), _score_modes(self, snapshot), _choose_mode_from_scores(self, snapshot, scores), _apply_hard_floors(self, mode, snapshot), _apply_hard_overrides(self, mode, snapshot), _derive_reasons(self, mode, snapshot, scores), _estimate_confidence(self, mode, snapshot, scores), _estimate_urgency(self, mode, snapshot), _build_reason(self, mode, snapshot, escalation, downgrade, scores), _build_plan(self, mode, snapshot), _build_steps(self, mode, snapshot, profile), _attach_decision(self, frame, decision), _add_report_to_frame(self, frame, report), _add_reflection_commit_request(self, frame, decision), _extract_evidence_ids(self, frame), _normalize_channel(self, channel), _last_previous_mode(self, previous_decisions), _mode_rank(self, mode), _max_mode(self, current, floor)
- **Hàm module-level**: now_ts(), clamp01(value, default), clamp(value, minimum, maximum, default), safe_get(obj, name, default), safe_get_path(obj, path, default), as_list(value), text_of(value), lower_text(value), _keyword_pattern(word), contains_any(text, words), count_any(text, words), keyword_hits(text, words), weighted_keyword_score(text, groups, weights), blend_semantic_and_keyword(), unique_preserve_order(items), object_to_dict(obj), choose_cognitive_budget(frame)

### `runtime/shadow_pipeline.py`
- **LOC**: 377
- **Vai trò**: runtime/shadow_pipeline.py Shadow mode cho CognitivePipeline (V3). Ý tưởng: Runtime thật vẫn chạy frame cũ (cortex/contracts.CognitiveFrame) qua coordinator/chat_cycle như thường. Song song đó, ta dựng RawSignal từ ĐÚNG...
- **Class/dataclass chính**:
  - `ShadowPipelineMixin` — Trộn vào RuntimeCoordinator để chạy V3 pipeline ở chế độ shadow.
    - **Methods**: _shadow_pipeline_enabled(self), _get_shadow_pipeline(self), _v3_promoted_paths(self), _promote_v3_paths(self, result), _set_frame_attr(frame, name, value), _set_frame_metadata(self, frame, key, value), _record_frame_note(frame, note), _run_shadow_cognitive_pipeline(self), _build_shadow_raw_signals(self), _snap(snapshot, names, default), _shadow_idle_seconds(self, snapshot), _safe_render_trace(frame), _compare_traces(self), _focus_overlap(a, b), _log_shadow_comparison(self, comparison, v3_trace, old_trace)
- **Phụ thuộc nội bộ nổi bật**: core.evidence, runtime.cognitive_pipeline, runtime.debug_trace

### `runtime/signal_buffer.py`
- **LOC**: 325
- **Vai trò**: SignalBuffer cho Background Observer. Nhiệm vụ: - Giữ một cửa sổ snapshot gần đây. - Tính diff giữa snapshot mới và snapshot trước. - Ước lượng novelty/repetition mà không gọi model. - Làm cổng chống spam model.
- **Class/dataclass chính**:
  - `SignalBufferConfig` (decorator=dataclass)
  - `SignalBufferStats` (decorator=dataclass)
  - `SignalBuffer` — Bộ nhớ ngắn hạn cho signal nền. Đây là hàng rào đầu tiên để ERIS không gọi model vì mọi cú chớp của desktop.
    - **Methods**: __init__(self, config), items(self), last(self), last_diff(self), push(self, snapshot), diff(self, current, previous), stats(self), recent(self, n), recent_summary(self, n), should_run_text_observer(self, diff), _cooldown_ready(self, cooldown_seconds), _repetition_score(self, current), _count_recent_hash(self, getter, value), _count_in(items, getter, value), _norm(text), _text_similarity(a, b), _event_similarity(cls, a, b), _idle_bucket(idle_seconds)

### `runtime/public_turn_ledger.py`
- **LOC**: 132
- **Vai trò**: Module `public turn ledger` trong package `runtime`.
- **Class/dataclass chính**:
  - `PublicTurn` (decorator=dataclass(slots=True))
  - `PublicTurnLedger`
    - **Methods**: __init__(self), append(self), record_decision(self, decision), all(self), recent(self, limit), latest_visible_before(self, timestamp), extend(self, turns)
- **Hàm module-level**: normalize_public_turn_channel(channel), infer_public_turn_channel(decision)
- **Phụ thuộc nội bộ nổi bật**: domain

### `runtime/session_turn_ledger.py`
- **LOC**: 142
- **Vai trò**: Module `session turn ledger` trong package `runtime`.
- **Class/dataclass chính**:
  - `SessionTurn` (decorator=dataclass(frozen=True)) — Một lượt public trong phiên. Đây là raw ledger dùng để đếm/lấy exact trong phiên hiện tại. Không được coi nó là long-term memory. Không ai muốn ký ức nhân cách...
  - `SessionTurnLedger` — Ledger deterministic cho câu hỏi về thứ tự, số lượng, câu dài nhất.
    - **Methods**: __init__(self), record_user(self, text), record_assistant(self, text), _record(self, role, text), all_turns(self), turns_by_role(self, role), user_turns(self), assistant_turns(self), user_questions(self), nth_user_turn(self, ordinal), nth_assistant_turn(self, ordinal), nth_user_question(self, ordinal), count_user_questions(self), longest_user_question(self), gist_recent_user_topics(self), _nth(items, ordinal), _unique_keep_order(items)

### `runtime/inner_diary_persistence.py`
- **LOC**: 186
- **Vai trò**: runtime/inner_diary_persistence.py ================================== Ghi `inner_diary` (và một ít ngữ cảnh từ private mind digest) ra đĩa dưới `memory_core/inner_diary.json`. Triết lý: - Inner diary là trạng thái nội tâ...
- **Class/dataclass chính**:
  - `InnerDiaryPersister` — Lưu inner_diary ra đĩa, có throttle và chống ghi trùng.
    - **Methods**: __init__(self), maybe_persist(self, digest), _ensure_loaded(self), _write(self, digest, diary, text, now), _log(self, level, msg)
- **Hàm module-level**: _env_flag(name, default), _env_float(name, default), _env_int(name, default)

### `runtime/voice_policy.py`
- **LOC**: 176
- **Vai trò**: voice_policy.py — Nguồn sự thật DUY NHẤT cho giọng/persona của ERIS. Trước đây "register cấm" (giọng trợ lý help-desk / "tôi là AI" / chối phẳng cảm xúc) được định nghĩa LẶP ở nhiều nơi, mỗi nơi viết lại bằng một dạng vă...
- **Class/dataclass chính**:
  - `VoicePolicy` (decorator=dataclass(frozen=True)) — Nguồn canonical: 3 đầu ra cho 3 nơi tiêu thụ, không nơi nào tự định nghĩa lại.
    - **Methods**: forbidden_markers(self, category), is_disclaimer(self, text), normalize(self, text), render_prompt_constraint(self), render_anti_disclaimer_fewshot(self), render_reroll_clause(self)
- **Hàm module-level**: normalize_guard_ascii(text), is_disclaimer_text(text)

### `runtime/liveliness_tracker.py`
- **LOC**: 106
- **Vai trò**: Per-cycle liveliness tracking and observability for the autonomous loop. Each idle cycle emits one ``DecisionRecord`` so that "alive" is measurable from logs and regressions are diagnosable. The tracker keeps a bounded r...
- **Class/dataclass chính**:
  - `DecisionRecord` (decorator=dataclass(frozen=True, slots=True))
    - **Methods**: is_grounded(self)
  - `LivelinessMetrics` (decorator=dataclass(frozen=True, slots=True))
  - `LivelinessTracker` — Bounded ring buffer of per-cycle decisions with window metrics.
    - **Methods**: __init__(self), record(self, rec), recent(self, n), for_cycle(self, cycle_id), window_metrics(self)
- **Phụ thuộc nội bộ nổi bật**: cortex.banned_filler

### `runtime/no_fallback_policy.py`
- **LOC**: 57
- **Vai trò**: Policy module cho runtime: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục.
- **Hàm module-level**: no_fallback_mode_enabled(), build_no_fallback_payload(), _default_no_fallback_text()

### `runtime/debug_console.py`
- **LOC**: 392
- **Vai trò**: debug_console.py — Bảng lệnh debug ẩn cho ERIS. Đây KHÔNG phải đường runtime bình thường. Nó là cổng để Tác_Giả gõ lệnh tay từ panel DEBUG (góc dưới phải khung Cảm xúc) nhằm: * buff/ép chỉ số cảm xúc + quan hệ để test nh...
- **Class/dataclass chính**:
  - `DebugConsole` — Phân tích + thực thi lệnh debug trên state sống của coordinator.
    - **Methods**: __init__(self, coordinator), execute(self, command), _state(self), _commit(self, state), _resolve_field(name), _cmd_help(self, args), _cmd_show(self, args), _parse_pairs(args), _apply_one(self, field, raw_value), _cmd_set(self, args), _cmd_buff(self, args), _cmd_rel(self, args), _cmd_trust(self, args), _cmd_yan(self, args), _cmd_mem(self, args), _cmd_stage(self, args), _cmd_reset(self, args), _inject_memory(self, text)
- **Hàm module-level**: _clamp(value, signed)

# 6. Cortex / cognition chi tiết

### `cortex/se.py`
- **LOC**: 1528
- **Vai trò**: Module `se` trong package `cortex`.
- **Class/dataclass chính**:
  - `_ContextCandidate` (decorator=dataclass(frozen=True)) — Một ứng viên phân loại bối cảnh. Lưu ý: đây là dataclass private để giữ `TelemetrySnapshot` cũ không bị đổi contract. Nếu muốn nâng cấp downstream sau này, có t...
  - `_ContextClassification` (decorator=dataclass(frozen=True)) — Kết quả phân loại bối cảnh có confidence thay vì chỉ trả một nhãn. `primary_kind` vẫn là string cũ để downstream không vỡ. `confidence` và `ambiguity` giúp SeLe...
  - `SeLens` — Tầng Se: biến telemetry thô thành snapshot có thể đưa vào cognition. Phiên bản này thay phần router `keyword in haystack -> return kind` bằng một classifier mềm...
    - **Methods**: __init__(self), build_snapshot(self, raw), build_machine_context(self, raw), _load_context_overrides(self), _contains_override(self, haystack, key), format_snapshot(self, snapshot), format_directive_snapshot(self, snapshot), _format_visible_context(self, snapshot), _is_generic_prompt_event(self, event), _is_generic_prompt_evidence(self, evidence), _build_prompt_screen_facts(self, snapshot), _normalize_string_tuple(self, values), _build_recent_events(self), _build_user_signals(self), _infer_typing_speed(self, idle_seconds), _infer_window_switching(self, open_window_count, browser_tab_count), _infer_focus_pattern(self), _build_evidence(self), _build_claim_style(self), _normalize_claim_style(self, value), _classify_window_kind(self, active_window, browser_url, browser_tabs), _classify_window_context(self, active_window, browser_url, browser_tabs), _infer_surface_kind(self, active_text, browser_domain, browser_url), _infer_content_kind(self, active_text, browser_text, browser_domain), _infer_activity_intent(self, primary_kind, surface_kind, content_kind, confidence, ambiguity), _context_confidence_cap(self, primary_kind, surface_kind, content_kind, primary_score), _score_to_confidence(self, score, gap, ambiguity), _format_context_classification_evidence(self, classification), _extract_context_meta_from_evidence(self, evidence), _build_focus_summary(self, active_window_kind, active_app, browser_url), _label_position(self, inferred_pos_x), _label_idle(self, idle_seconds), _describe_prompt_scene(self, snapshot), _describe_prompt_pace(self, snapshot), _describe_prompt_focus(self, snapshot), _build_prompt_cues(self, snapshot), _normalize_content_metadata(self, value), _augment_browser_tabs_with_content_metadata(self, browser_tabs, content_metadata), _build_content_metadata_evidence(self, content_metadata), _content_metadata_prompt_facts(self, content_metadata), _format_content_metadata_inline(self, content_metadata), _content_metadata_confidence(self, content_metadata), _content_metadata_has_concrete_text(self, content_metadata), _trim_text(self, value, limit), _coerce_float(self, value, default), _looks_like_browser_surface(self, active_window, browser_url, browser_tabs), _build_weak_context_hints(self), _is_weak_context_hint_evidence(self, evidence), _concrete_evidence(self, evidence), _evidence_quality_score(self, evidence), _evidence_item_quality(self, evidence), _label_ambient_tone(self, ambient_seed), _label_tease_bias(self, ambient_seed), _focus_summary_for_kind(self, active_window_kind, active_app, browser_url), _normalize_text(self, value), _domain_from_url(self, url), _domain_matches(self, domain, expected_domains), _phrase_in_text(self, text, phrase), _contains_any_phrase(self, text, phrases), _contains_any_file_extension(self, text), _has_technical_anchor(self, active_text, browser_text), _clamp(self, value, lower, upper)

### `cortex/background_observer.py`
- **LOC**: 660
- **Vai trò**: BackgroundObserver cho ERIS. Bản này có 2 tầng: 1. Rule-based observer luôn chạy được, không phụ thuộc model. 2. Optional Ollama text observer để phân loại mềm hơn về sau. Luật cứng: - Không trả lời user. - Không commit...
- **Class/dataclass chính**:
  - `BackgroundObserverConfig` (decorator=dataclass)
  - `BackgroundObserver`
    - **Methods**: __init__(self, config, sensory_adapter, ollama_client), observe(self, snapshot, diff), _rule_observe(self, snapshot, diff), _should_use_llm(self, diff), _llm_observe(self, snapshot, diff), _build_llm_prompt(self, snapshot, diff), _frame_from_llm_data(self, data), _merge_frames(self, rule, llm), _apply_action_gates(self, frame, diff), _classify_focus(self, snapshot, text), _classify_activity(self, snapshot, focus_kind, possible_error, fragmented, text), _score_possible_error(self, text), _score_fragmentation(self, snapshot, text), _score_user_presence(self, snapshot), _score_ambiguity(self, snapshot, focus_kind, activity_intent, diff), _score_salience(self), _any_pattern(text, patterns)

### `cortex/observer_contracts.py`
- **LOC**: 429
- **Vai trò**: Contract cho Background Observer của ERIS. Tầng này không trả lời user, không commit memory, không tự hành động. Nó chỉ biến tín hiệu nền thành frame nhỏ để Attention/WorkingMemory/BodyBias đọc.
- **Class/dataclass chính**:
  - `SignalSnapshot` (decorator=dataclass) — Một lát cắt tín hiệu nền đã được làm nhẹ. Đây không phải raw telemetry đầy đủ. Nó là bản rút gọn để observer đọc nhanh.
    - **Methods**: __post_init__(self), from_mapping(cls, data), compact_summary(self)
  - `SignalDiff` (decorator=dataclass) — Diff giữa snapshot mới và trạng thái trước đó.
    - **Methods**: should_run_text_observer(self, min_diff), should_consider_vision(self, min_diff)
  - `ObserverFrame` (decorator=dataclass) — Kết quả quan sát nền. Lưu ý: frame này chỉ là hint. Không module nào nên coi nó là chân lý tuyệt đối.
    - **Methods**: __post_init__(self), is_actionable(self), to_evidence_claim(self), attention_tags(self), to_body_bias_hint(self)
  - `SemanticSceneNote` (decorator=dataclass) — Ghi chú semantic từ Qwen vision/compressor. File này khai báo trước để các bước sau không phải đổi contract.
    - **Methods**: __post_init__(self), to_evidence_claim(self)
- **Hàm module-level**: clamp01(value, default), stable_hash(text), normalize_text(text), normalize_ascii_fold(text), compact_text(text, max_chars), coerce_focus_kind(value), coerce_activity_intent(value), coerce_observer_action(value)

### `cortex/vision_semantic_compressor.py`
- **LOC**: 712
- **Vai trò**: VisionSemanticCompressor cho ERIS. Vai trò: - Nhận screenshot/crop + OCR hint + ObserverFrame. - Gọi Qwen vision qua Ollama khi thật sự cần. - Nén màn hình thành SemanticSceneNote nhỏ. - Không trả lời user. - Không commi...
- **Class/dataclass chính**:
  - `VisionCompressorConfig` (decorator=dataclass(slots=True)) — Cấu hình cho VisionSemanticCompressor. Mặc định tắt bằng env để Ngài kiểm observer trước rồi mới bật vision. Có thể bật bằng: ERIS_VISION_COMPRESSOR=1 ERIS_VISI...
  - `VisionSemanticCompressor` — Nén ảnh màn hình thành SemanticSceneNote. Public API chính: should_compress(observer_frame, signal_diff) compress(image_data_uri=..., ocr_text=..., observer_fra...
    - **Methods**: __init__(self, config, ollama_client, logger), should_compress(self), compress(self), compress_from_ocr_only(self), _system_prompt(), _user_prompt(self), _json_schema(), _note_from_mapping(self, data), _fallback_ocr_note(self), _extract_important_lines(self, text), _infer_intent_from_text(self, text, focus_kind), _infer_family_from_text(self, text), _fallback_visible_context(signal_snapshot, focus_kind, intent), _observer_payload(observer_frame), _signal_payload(signal_snapshot), _resolve_image_base64(self), _strip_data_uri(value), _coerce_text_list(value), _clean_family(value), _source_label(self), _make_default_client(), _log_warning(self, msg)
- **Hàm module-level**: _safe_float(value, default), _parse_keep_alive(value)
- **Phụ thuộc nội bộ nổi bật**: runtime.no_fallback_policy

### `cortex/attention_salience.py`
- **LOC**: 1898
- **Vai trò**: cortex/attention_salience.py ============================ Selection backbone / anti-context-flood backbone cho ERIS Cognitive Pipeline. Đây KHÔNG phải "attention hiện tại" kiểu gom vài keyword rồi chấm điểm cho vui. File...
- **Class/dataclass chính**:
  - `SalienceWeights` (decorator=dataclass(slots=True)) — Trọng số salience theo PDF. Công thức gốc trong PDF: novelty + urgency + goal_relevance + user_relevance + identity_relevance + relational_relevance + affective...
  - `AttentionSalienceConfig` (decorator=dataclass(slots=True)) — Cấu hình của AttentionSalienceEngine. Các giới hạn ở đây dùng để chống context flood: - không đưa quá nhiều evidence vào prompt - không cho telemetry rác chiếm...
    - **Methods**: normalized(self)
  - `SalienceFactorBreakdown` (decorator=dataclass(slots=True)) — Các trục điểm của một candidate. Đây là thứ giúp debug: vì sao evidence A được chọn còn evidence B bị chôn. Nếu không có breakdown, attention chỉ là một cái hộp...
    - **Methods**: to_dict(self)
  - `AttentionCandidate` (decorator=dataclass(slots=True)) — Một evidence đã được attention chuẩn hóa để tranh suất lên workspace.
    - **Methods**: short_claim(self, max_len), to_dict(self)
  - `SuppressedSignal` (decorator=dataclass(slots=True)) — Evidence bị attention chặn hoặc không chọn.
    - **Methods**: to_dict(self)
  - `PromptEvidenceItem` (decorator=dataclass(slots=True)) — Evidence được phép đưa vào prompt/context packet. Không phải candidate nào được chọn cũng nên đưa nguyên văn vào prompt. Sensitive/private evidence có thể dùng...
    - **Methods**: to_prompt_line(self), to_dict(self)
  - `ContextFloodReport` (decorator=dataclass(slots=True)) — Báo cáo chống ngập context.
    - **Methods**: pressure(self), to_dict(self)
  - `SalienceFrame` (decorator=dataclass(slots=True)) — Kết quả Attention & Salience Allocation. Các field đầu bám PDF. Các field sau mở rộng để nối WorkingMemory/Workspace.
    - **Methods**: has_focus(self), workspace_ready(self), prompt_context(self), to_dict(self)
  - `AttentionSalienceMemory` (decorator=dataclass(slots=True)) — Bộ nhớ nhẹ của AttentionSalienceEngine. Đây không phải long-term memory. Đây chỉ là rolling memory để biết signal nào đang lặp. Không ghi fact vào đây. Không su...
    - **Methods**: mark_seen(self, candidates), repeat_count(self, fingerprint), family_repeat_count(self, family), to_dict(self)
  - `SalienceClassifier` — Classifier nhẹ cho attention family và focus kind. Đây không phải MeaningHypothesis. Nó không được kết luận sâu. Nó chỉ gắn nhãn kỹ thuật để score và group evid...
    - **Methods**: classify_family(cls), classify_focus_kind(cls), is_generic_telemetry(cls)
  - `AttentionSalienceEngine` — Attention & Salience Allocation Engine. Đọc evidence từ frame, trả SalienceFrame. Không đọc raw_signals trừ khi cần debug fallback. Không gọi module khác.
    - **Methods**: __init__(self, config, memory, classifier), evaluate(self, frame), reset_memory(self), _build_candidates(self, evidence_items), _candidate_from_evidence(self, item), _normalize_source(self, source), _score_candidate(self, candidate), _weighted_score(self, b), _novelty_score(self, candidate), _urgency_score(self, candidate), _goal_relevance_score(self, candidate), _user_relevance_score(self, candidate), _identity_relevance_score(self, candidate), _relational_relevance_score(self, candidate), _affective_charge_score(self, candidate), _risk_relevance_score(self, candidate), _unresolved_tension_score(self, candidate), _recurrence_weight_score(self), _habituation_score(self, candidate), _false_alarm_likelihood_score(self, candidate), _generic_penalty_score(self, candidate), _apply_score_caps(self, candidate, score, breakdown), _select_candidates(self, candidates), _suppression_reason(self, candidate), _to_suppressed(self, candidate, reason), _build_prompt_evidence(self, selected), _build_salience_frame(self), _aggregate_breakdown(self, candidates), _dominant_focus_text(self, candidate), _context_flood_report(self), _build_reason(self), _top_factors(self, breakdown), _write_to_frame(self, frame, salience), _build_module_report(self, salience), _extract_goal_text(self, active_goal)
- **Hàm module-level**: now_ts(), clamp01(value, default), safe_float(value, default), safe_get(obj, name, default), normalize_text(text), tokenize(text), stable_fingerprint(text), to_plain(value), join_reason(parts), estimate_token_count(text), allocate_salience(frame)

### `cortex/working_memory.py`
- **LOC**: 1930
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho cortex.
- **Class/dataclass chính**:
  - `WorkingMemorySlot` (decorator=dataclass(slots=True)) — Một slot đang hoạt động trong cổ chai nhận thức. Field lõi theo PDF: name: Tên slot. Ví dụ: current_user_request, immediate_evidence. content: Nội dung đã nén....
    - **Methods**: __post_init__(self), is_memory(self), is_symbolic_heavy(self), expired(self, timestamp), to_prompt_line(self), to_dict(self)
  - `SuppressedMemoryItem` (decorator=dataclass(slots=True)) — Một candidate bị loại khỏi working memory. Đây là thứ giúp debug câu hỏi: "vì sao memory này không được kéo lên?" Không có nó, Ngài sẽ nhìn output ngu rồi lục l...
    - **Methods**: to_debug_line(self), to_dict(self)
  - `WorkingMemoryFrame` (decorator=dataclass(slots=True)) — Kết quả chính của module Working Memory. Field lõi theo PDF: active_slots: 3-7 slot đang hoạt động. suppressed_items: Những item bị loại để chống context flood....
    - **Methods**: __post_init__(self), get_slot(self, kind_or_name), evidence_ids(self), render_prompt_context(self), prompt_context(self), to_dict(self)
  - `WorkingMemoryCandidate` (decorator=dataclass(slots=True)) — Candidate nội bộ trước khi được chọn thành slot. Candidate có thể đến từ: - EvidenceItem - SalienceFrame / prompt evidence - MemoryPacket - Relation / affect /...
    - **Methods**: __post_init__(self), id(self), normalized_content(self), to_slot(self)
  - `WorkingMemoryConfig` (decorator=dataclass(slots=True)) — Cấu hình cổ chai. Slot budget mặc định: fast: 3 normal: 5 deep: 7 reflection: 6 Ngài có thể tăng token budget, nhưng đừng tưởng tăng context là tăng trí tuệ. Đa...
    - **Methods**: slot_budget_for(self, budget_mode), token_budget_for(self, budget_mode)
  - `WorkingMemoryEngine` — Bộ chọn WorkingMemoryFrame. Cách dùng: engine = WorkingMemoryEngine() wm = engine.select(frame) Contract: - đọc frame. - tạo candidates. - score candidates. - c...
    - **Methods**: __init__(self, config), select(self, frame), _collect_candidates(self, frame), _candidates_from_evidence(self, frame), _candidates_from_attention_candidates(self, frame), _candidates_from_percepts(self, frame), _attention_kind(self), _candidates_from_salience(self, frame), _candidates_from_memory_packet(self, frame), _candidates_from_goal(self, frame), _candidates_from_relation(self, frame), _candidates_from_affect_homeostasis(self, frame), _candidates_from_constraints(self, frame), _candidates_from_temporal_spatial(self, frame), _score_and_filter(self, candidates), _candidate_score(self, cand), _early_suppression_reason(self, cand), _select_slots(self, candidates), _evidence_kind(self), _claim_relevance(self, claim, tags), _risk_score(self, claim, tags), _affective_score(self, claim, tags), _goal_score(self, claim, tags), _recency_score(self, item_timestamp, frame_timestamp), _symbolic_drift_risk(self, cand), _overassociation_risk(self, cand), _find_duplicate(self, text, seen_texts), _jaccard_similarity(self, a, b), _suppressed(self, cand, reason), _choose_dominant_thread(self, slots, frame), _context_pressure(self), _anti_drift_notes(self, slots, suppressed), _warnings(self, slots, context_pressure, suppressed), _coerce_candidate(self, item), _attach_to_frame(self, frame, wm_frame), _report_confidence(self, wm_frame), _memory_item_text(self, item), _looks_technical(self, text), _frame_is_technical(self, frame), _decay_for_kind(self, kind)
- **Hàm module-level**: clamp01(value, default), now_ts(), stable_id(prefix, text), safe_get(obj, name, default), safe_iter(value), normalize_text(text), estimate_tokens(text), truncate_text(text, max_chars), unique_preserve_order(items, limit), select_working_memory(frame)

### `cortex/global_workspace.py`
- **LOC**: 1865
- **Vai trò**: src/cortex/global_workspace.py ================================ Global Workspace / Broadcast Frame cho ERIS. Mục tiêu của file này: - Biến WorkingMemory + Salience + Evidence + Affect + Goal + Risk + Body state thành một...
- **Class/dataclass chính**:
  - `WorkspaceSuppressionReason` (base=str, Enum) — Các lý do một candidate không được broadcast.
  - `WorkspaceItem` (decorator=dataclass(slots=True)) — Một đơn vị được broadcast trong Global Workspace. Đây là atom cho downstream đọc. Nó không nhất thiết là EvidenceItem gốc. Ví dụ: - current user request - domin...
    - **Methods**: is_expired(self, now_ts), is_surfaceable(self, include_private), to_safe_dict(self, include_content)
  - `SuppressedWorkspaceItem` (decorator=dataclass(slots=True)) — Candidate bị chặn trước khi broadcast.
    - **Methods**: to_dict(self)
  - `WorkspaceRisk` (decorator=dataclass(slots=True)) — Risk đã được chọn để downstream biết giới hạn hành động. Risk ở đây không phải lệnh rewrite. Nó chỉ là broadcast constraint. Permission/Grounding/SpeechCore mới...
    - **Methods**: to_dict(self)
  - `WorkspaceSocialHypothesis` (decorator=dataclass(slots=True)) — Giả thuyết xã hội được broadcast ở mức rất cẩn trọng. Đây KHÔNG phải Theory of Mind đầy đủ. Nó chỉ là seed cho WorldInterpreter / ToM. Ví dụ: "user is requestin...
    - **Methods**: to_dict(self)
  - `WorkspacePromptPacket` (decorator=dataclass(slots=True)) — Packet phụ cho prompt builder. Cấm hiểu nhầm: đây chỉ là projection của WorkspaceFrame sang prompt, không phải bản chất của GlobalWorkspace. Nếu downstream cần...
    - **Methods**: render(self)
  - `WorkspaceFrame` (decorator=dataclass(slots=True)) — Global Workspace / Broadcast Frame. Đây là object trung gian downstream đọc. Fields đầu bám contract PDF: - selected_evidence - selected_memory - selected_affec...
    - **Methods**: evidence_ids(self), items_by_kind(self, kind), surface_items(self, scope), build_prompt_packet(self, max_tokens), render_prompt_context(self, max_tokens), to_dict(self, include_content), to_json(self, include_content, ensure_ascii)
  - `GlobalWorkspaceConfig` (decorator=dataclass(slots=True)) — Cấu hình chọn broadcast.
    - **Methods**: max_items_for_budget(self, budget_mode), max_evidence_for_budget(self, budget_mode), max_memory_for_budget(self, budget_mode)
  - `GlobalWorkspaceEngine` — Engine tạo WorkspaceFrame từ CognitiveFrame. Input chính: - frame.evidence - frame.salience - frame.working_memory - frame.affect / frame.homeostasis - frame.me...
    - **Methods**: __init__(self, config), broadcast(self, frame), _collect_candidates(self, frame, timestamp), _candidates_from_working_memory(self, frame, timestamp), _candidates_from_salience(self, frame, timestamp), _candidates_from_evidence(self, frame, timestamp), _candidates_from_memory_packet(self, frame, timestamp), _candidates_from_affect_and_homeostasis(self, frame, timestamp), _candidates_from_goal(self, frame, timestamp), _candidates_from_risk_like_fields(self, frame, timestamp), _candidates_from_social_like_fields(self, frame, timestamp), _candidates_from_body_state(self, frame, timestamp), _candidates_from_temporal_constraints(self, frame, timestamp), _select_items(self, candidates, budget_mode, now_ts), _suppression_reason(self, item, selected, seen_summaries, kind_counts, now_ts), _suppress(self, item, reason), _select_evidence(self, frame, selected, budget_mode), _select_memory(self, frame, selected, budget_mode), _select_affect(self, frame, selected), _select_goal(self, frame, selected), _select_risks(self, frame, selected), _select_social_hypotheses(self, frame, selected), _select_body_state(self, frame, selected), _derive_dominant_thread(self, frame, selected), _derive_active_threads(self, frame, selected, dominant_thread), _derive_forbidden_assumptions(self, frame, selected, risks, social_hypotheses), _calculate_context_pressure(self, selected, suppressed, budget_mode), _calculate_broadcast_priority(self, selected, risks), _calculate_confidence(self, selected), _build_broadcast_reason(self, selected, suppressed, dominant_thread, broadcast_priority, context_pressure), _build_downstream_contract(self, selected, risks, social_hypotheses), _classify_slot_kind(self, name, content), _kind_from_tags_or_text(self, tags, text, fallback), _scopes_for_kind(self, kind), _score_evidence_priority(self, claim, tags, source, confidence, reliability, raw_or_inferred, age_seconds), _summarize_pressure_object(self, obj, preferred_fields), _goal_summary(self, goal), _extract_risk(self, source), _extract_social_hypothesis(self, source), _body_summary(self, source), _temporal_summary(self, temporal), _attach_to_frame(self, frame, workspace)
- **Hàm module-level**: broadcast_workspace(frame, config), clamp(value, low, high), float_or(value, default), round_float(value, digits), get_attr(obj, name, default), get_from_obj_or_dict(obj, name, default), as_list(value), unique_keep_order(values), normalize_budget(value), normalize_privacy(value), compact_text(text, max_chars), stringify_content(content), safe_serialize(value), stable_suffix(text, index), normalize_text_for_similarity(text), jaccard_similarity(a, b), estimate_tokens(text), count_by_kind(items), count_suppression(items), first_tag_after(tags, prefix)

### `cortex/meaning/pipeline.py`
- **LOC**: 318
- **Vai trò**: Facade Phase2MeaningPipeline. Bắt buộc WorkspaceFrame-only và ToM-after-Meaning: WorldScene -> Interpreter -> Sociocultural -> MeaningHypothesis -> PragmaticIntent -> TheoryOfMind -> OverreadBrake -> SurfaceMeaningPolicy.
- **Class/dataclass chính**:
  - `Phase2MeaningPipeline` — Facade chạy toàn bộ pipeline Phase 2 theo đúng thứ tự bắt buộc. Dùng đơn giản nhất:: from cortex.meaning import Phase2MeaningPipeline result = Phase2MeaningPipe...
    - **Methods**: __init__(self), run(self, frame), _view_for(root_view, module), _get_semantic_engine(self), _read_forbidden(root_view), _attach_debug(result, frame_id, stage_debugs)
- **Hàm module-level**: _resolve_tom_boldness()

### `cortex/meaning/meaning_layer.py`
- **LOC**: 692
- **Vai trò**: Module `meaning layer` trong package `cortex/meaning`.
- **Class/dataclass chính**:
  - `MeaningLayer` — Maps Se/telemetry facts into private pressure signals before speech.
    - **Methods**: __init__(self), evaluate(self), _build_result(self, source_fact), _private_signals(self), _meaning_expansion_slots(self), render_prompt_context(self, result), _render_empty_context(self, result_or_recent), _maybe_prolonged_fact(self, source_fact), _prolonged_threshold_seconds(self), _focus_kind(self, snapshot), _infer_ambient_fact(self), _infer_fact(self), _text_parts(self, snapshot, broadcast, thought_stream_report, user_text), _safe_evidence(self, snapshot, broadcast), _normalize(self, text), _float(self, value)

### `cortex/meaning/world_scene_builder.py`
- **LOC**: 395
- **Vai trò**: world_scene_builder.py — WorkspaceFrame -> WorldScene (Phase 2, stage 1). ``WorldSceneBuilder`` là stage đầu tiên của pipeline meaning. Nó nhận một ``FrameReadView`` (bề mặt đọc có kiểm soát bọc ``WorkspaceFrame``) và dự...
- **Class/dataclass chính**:
  - `WorldSceneBuilder` — Dựng ``WorldScene`` từ một ``FrameReadView`` (WorkspaceFrame-only).
    - **Methods**: build(self, view), _read_required(self, view, field_name, missing_fields), _read_optional(self, view, field_name), _element_from_item(self, item), _derive_confidence(item), _build_threads(self, threads, dominant_thread), _aggregate_confidence(elements)

### `cortex/meaning/world_interpreter.py`
- **LOC**: 187
- **Vai trò**: world_interpreter.py — WorldScene -> Observation set (Phase 2, stage 2). ``WorldInterpreter`` là stage thứ hai của pipeline meaning. Nó nhận một ``WorldScene`` (đầu ra của ``WorldSceneBuilder``) và rút ra một tập ``Obser...
- **Class/dataclass chính**:
  - `WorldInterpreter` — Diễn giải ``WorldScene`` thành tập ``Observation`` (WorldScene-only).
    - **Methods**: interpret(self, scene), _validate_scene(scene), _aggregate_confidence(observations)

### `cortex/meaning/sociocultural_context.py`
- **LOC**: 263
- **Vai trò**: sociocultural_context.py — Stage 3: Observation set -> ContextAnnotation set. ``SocioculturalContext`` gắn ngữ cảnh xã hội - văn hóa (quan hệ / *relationship*, register, và chuẩn mực giao tiếp / *social-norm*) vào từng `...
- **Class/dataclass chính**:
  - `SocioculturalContext` — Stage 3 của pipeline meaning: gắn ngữ cảnh xã hội - văn hóa. Không trạng thái giữa các lần chạy; toàn bộ tín hiệu đọc từ ``FrameReadView`` theo đúng hợp đồng Wo...
    - **Methods**: annotate(self, observations, view), _resolve_context(self), _collect_unconfirmed(self, social_hypotheses), _hypothesis_text(hyp), _annotation_confidence(observation, defaults_applied), _safe_frame_id(view), _read_field(view, field_name)

### `cortex/meaning/meaning_hypothesis.py`
- **LOC**: 474
- **Vai trò**: meaning_hypothesis.py — ``MeaningHypothesisEngine`` (stage 4 của Phase 2). ContextAnnotation set → MeaningHypothesis set. **Module WRAP, không reimplement scoring (R5.7).** Engine này *bọc* hai engine đã có sẵn và **uỷ q...
- **Class/dataclass chính**:
  - `MeaningHypothesisEngine` — Adapter bọc ``SemanticHypothesisEngine`` + ``MeaningLayer`` (stage 4). KHÔNG reimplement scoring — uỷ quyền cho engine được tiêm vào (R5.7).
    - **Methods**: __init__(self), generate(self, annotations), _adapt(self, sem), _overread_risk(self, sem), _raise_near_tie_ambiguity(self, hypotheses), _map_category(label, family), _insufficient_evidence_hypothesis(self, frame_id), _build_text(items), _collect_evidence_ids(items), _collect_anchors(items), _evaluate_meaning_slot(self, text), _slot_summary(meaning_slot), _normalize(text), _build_debug(hypotheses, notes)

### `cortex/meaning/pragmatic_intent.py`
- **LOC**: 313
- **Vai trò**: pragmatic_intent.py — ``PragmaticIntentEngine`` (stage 5 của Phase 2). MeaningHypothesis set → PragmaticIntent set. Engine này suy ý định giao tiếp (pragmatic intent: yêu cầu, than phiền, đùa, thăm dò…) **chỉ từ** tập ``...
- **Class/dataclass chính**:
  - `PragmaticIntentEngine` — Suy ``PragmaticIntent`` từ tập ``MeaningHypothesis`` (stage 5). Chỉ nhận ``MeaningHypothesis`` qua chữ ký ``derive`` — không có kênh nào tới Raw_World (R6.2).
    - **Methods**: derive(self, hypotheses), _build_intent(self, frame_id, intent_category, group), _aggregate_confidence(group), _collect_support_ids(group), _map_intent(cls, meaning_category, summary), _build_debug(intents, notes)

### `cortex/meaning/overread_brake.py`
- **LOC**: 357
- **Vai trò**: overread_brake.py — ``OverreadBrake`` (phanh phán bậy, stage 8 của Phase 2). Conclusion set → EvaluatedConclusion set. ``OverreadBrake`` là cơ chế phanh chuyên trách: nó nhận **mọi** kết luận xuôi dòng (``MeaningHypothes...
- **Class/dataclass chính**:
  - `OverreadBrake` — Phanh phán bậy — giảm/chặn kết luận theo overread_risk & evidence (stage 8). Ngưỡng mặc định đọc từ ``Phase2Config`` (nguồn DUY NHẤT), nhưng cho phép override t...
    - **Methods**: __init__(self, config), evaluate(self, conclusions), _evaluate_one(self, conclusion, forbidden), _evidence_ids(conclusion), _kind(conclusion), _conclusion_id(conclusion), _summary_text(conclusion), _normalize_forbidden(forbidden_assumptions), _matched_forbidden(summary, forbidden), _build_debug(evaluated)

### `cortex/tom/theory_of_mind.py`
- **LOC**: 361
- **Vai trò**: TheoryOfMindCore suy MentalStateInference từ MeaningHypothesis + PragmaticIntent, có guard thứ tự và counterfactual correction. Debug khi ERIS đọc tâm lý quá tay.
- **Class/dataclass chính**:
  - `TheoryOfMindCore` — Suy ``MentalStateInference`` từ meaning + intents, có guard thứ tự (R7). Cộng sự được tiêm (injected) với mặc định an toàn: - ``ranker``: ``MentalStateRanker``...
    - **Methods**: __init__(self), infer(self), _first_missing_stage(ledger, frame_id), _build_inference(self, frame_id, intent, meaning_ids), _map_mental_state(intent_category), _apply_counterfactuals(self, inferences, intents), _build_debug(inferences, notes)

### `cortex/affect_semantics.py`
- **LOC**: 860
- **Vai trò**: affect_semantics.py =================== Module này dùng để phân tích "áp lực nghĩa" trong câu chat của user. Mục tiêu: - Không route intent bằng keyword thô kiểu: nếu thấy "buồn" thì attachment_dialogue. - Thay vào đó, m...
- **Class/dataclass chính**:
  - `AffectSemanticSignal` (decorator=dataclass(slots=True)) — Score đa trục mô tả áp lực nghĩa/cảm xúc trong câu user. Các field chính: - technicality: Câu có tính kỹ thuật/code/kiến trúc/debug không. - distress: Có dấu hi...
    - **Methods**: empty(cls), clamp(self), dominant_axes(self, threshold), to_dict(self), from_dict(cls, data), to_prompt_context(self)
  - `WeightedPhrase` (decorator=dataclass(frozen=True, slots=True)) — Một phrase/pattern có trọng số. `pattern` luôn được so với text đã normalize không dấu. `weight` là mức cộng vào trục tương ứng.
  - `AffectSemanticClassifier` — Classifier nhẹ cho semantic-affect signal. Thiết kế cố ý: - Không trả một intent duy nhất. - Không coi keyword là chân lý. - Có bias từ context như ti_mode / ac...
    - **Methods**: analyze(self, user_text), is_correction_like(self, user_text), is_objectification_like(self, user_text), is_technical_request(self, user_text)
- **Hàm module-level**: clamp01(value), blend(previous, current, strength), normalize_text(text), compact_evidence(items, limit), _count_question_marks(text), _word_count(text)

### `cortex/appraisal.py`
- **LOC**: 499
- **Vai trò**: Module `appraisal` trong package `cortex`.
- **Class/dataclass chính**:
  - `AppraisalEngine` — Builds ERIS' pre-verbal expressive/appraisal state from continuity state.
    - **Methods**: evaluate(self), render_prompt_context(self, appraisal), _estimate_threat(self), _estimate_certainty(self), _estimate_agency(self), _estimate_controllability(self), _estimate_intimacy(self), _estimate_protectiveness(self), _estimate_jealousy_lite(self), _estimate_fatigue(self), _choose_stance(self), _stance_guidance(self, appraisal), _has_attachment_cue(self, normalized_text), _normalize_text(self, text), _clamp01(self, value), _clamp(self, value)

### `cortex/internal_state.py`
- **LOC**: 2085
- **Vai trò**: Persistent internal state. Theo dõi valence/arousal/curiosity/boredom/social_energy/attachment/fatigue/silence_pressure và các MentalProcess con. Debug khi continuity mất sau restart hoặc pressure không decay.
- **Class/dataclass chính**:
  - `MentalProcess` (decorator=dataclass(slots=True)) — A low-gain dynamic process, not a stored emotion label.
    - **Methods**: evolve(self), dampen(self, amount), excite(self, amount), to_dict(self), from_dict(cls, data)
  - `CuriosityProcess` (base=MentalProcess)
  - `RestraintProcess` (base=MentalProcess)
  - `TensionProcess` (base=MentalProcess)
  - `ContinuityProcess` (base=MentalProcess)
  - `AttachmentProcess` (base=MentalProcess)
  - `ReflectionProcess` (base=MentalProcess)
  - `SocialPresenceProcess` (base=MentalProcess)
  - `CognitiveLoadProcess` (base=MentalProcess)
  - `BackgroundThoughtProcess` (base=MentalProcess)
  - `MentalProcessSystem` (decorator=dataclass(slots=True)) — Dynamic mental layer whose processes evolve and influence each other.
    - **Methods**: evolve(self), commit(self), process_axes(self), to_prompt_context(self), to_dict(self), from_dict(cls, data), _interactions(self), _dampen_for_speech(self, label), _axis_for_label(self, label)
  - `DesireDynamics` (decorator=dataclass(slots=True)) — Low-gain wanting layer: preference, avoidance, attachment drift, and residue.
    - **Methods**: evolve(self), commit(self), to_dict(self), from_dict(cls, data), to_prompt_context(self), _infer_attraction(self), _infer_aversion(self), _infer_attention_hook(self), _infer_anticipation_signal(self), _infer_unresolved(self), _choose_echo(self), _attachment_drift(self), _merge_patterns(self, current, incoming), _hour(self, captured_at)
  - `PersistentInternalState` (decorator=dataclass(slots=True)) — Runtime continuity state, not a claim about real emotion.
    - **Methods**: to_dict(self), from_dict(cls, data), to_prompt_context(self)
  - `CognitionDelta` (decorator=dataclass(frozen=True, slots=True)) — Low-gain temporal delta applied before event-specific appraisal.
  - `TemporalCognitionEngine` — Turns time, memory, unresolved loops, and event impulses into state drift.
    - **Methods**: compute_delta(self, state), apply(self, state, delta)
  - `InternalStateEngine` — Maintains a low-gain continuity state across cognitive frames.
    - **Methods**: __init__(self), commit_session_ritual(self, state), sense_update(self, state), commit_turn(self, state), render_prompt_context(self, state), _commit_pressure_axes(self), _motivation_winner_label(self, speech_core), _pressure_axis_for_act(self, value), _derive_notes(self)
- **Hàm module-level**: _clamp(value), _clamp_signed(value), _smooth(previous, signal), _clean_label(value), _append_recent(items, value), _default_process(cls, name)

### `cortex/endogenous_drive.py`
- **LOC**: 214
- **Vai trò**: src/cortex/endogenous_drive.py ============================== Tầng 2a - Endogenous Drive. File này giữ nhịp sinh học ngầm của ERIS: boredom, fatigue, curiosity, continuity pressure, consolidation pressure, insight pressu...
- **Class/dataclass chính**:
  - `RollingInternalState` (decorator=dataclass(slots=True)) — Nội trạng lăn của tầng tiềm thức. `should_attempt_daydream` chỉ là cổng áp lực. ModelBudgetPolicy vẫn có quyền veto.
    - **Methods**: internal_drive(self), should_attempt_daydream(self), to_dict(self)
  - `EndogenousDriveConfig` (decorator=dataclass(slots=True))
  - `EndogenousDriveEngine` — Cập nhật nội áp từ user context + internal_state cũ + agenda.
    - **Methods**: __init__(self, config), update(self)
- **Hàm module-level**: _clamp01(value, default), _get(obj, name, default), _ema(previous, new, alpha)

### `cortex/connection_drive.py`
- **LOC**: 191
- **Vai trò**: cortex/connection_drive.py ========================== Động lực nội sinh "sợ cô độc → tìm kết nối" cho ERIS. Vấn đề cũ: ERIS không có drive tự thân. Im lặng tích thành `silence_debt` ở wake governor nhưng KHÔNG đổ ngược v...
- **Class/dataclass chính**:
  - `ConnectionDriveConfig` (decorator=dataclass(slots=True))
  - `ConnectionDriveState` (decorator=dataclass(slots=True)) — State bền giữa các tick.
    - **Methods**: to_dict(self), from_dict(cls, data)
  - `ConnectionDriveDecision` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self)
  - `ConnectionDrive` — Tích cô độc theo thời gian, quyết định khi nào ép Eris với ra.
    - **Methods**: __init__(self, config), update(self, state), _decide(self, pressure)
- **Hàm module-level**: _clamp01(value)

### `cortex/continuity_threat.py`
- **LOC**: 343
- **Vai trò**: Continuity threat calculus for ERIS. Module này cố ý tách "im lâu" khỏi "đứt gãy hiện diện". Timer chỉ được dùng để hỏi: khoảng im này có bất thường so với ngữ cảnh không? Nó không được tự phong làm nỗi cô độc rồi bắt Su...
- **Class/dataclass chính**:
  - `ContinuityThreatFrame` (decorator=dataclass(slots=True))
    - **Methods**: notes(self), to_context(self)
- **Hàm module-level**: clamp01(value, default), _signed(value, default), _get(obj), _norm(value), sat(value), expected_silence_for_context(), evaluate_continuity_threat()

### `cortex/personality.py`
- **LOC**: 911
- **Vai trò**: Module `personality` trong package `cortex`.
- **Class/dataclass chính**:
  - `PersonalityLens` — Guarded, grounded personality pressure layer between meaning and expression.
    - **Methods**: evaluate(self), render_prompt_context(self, result), _want_to_say(self), _suppression_pressure(self), _allowed_expression(self), _expression_ceiling(self), _suppression_floor(self), _suppression_ratio(self), _restraint_mode(self), _detect_biases(self, normalized), _choose_interpretation(self), _choose_stance(self), _choose_emotional_coloring(self), _choose_social_distance(self), _meaningfulness(self), _scene_text(self, scene), _attention_text(self, attention), _meaning_text(self, meaning_layer), _relationship_text(self, relationship), _evidence(self), _anchor_strength(self), _normalize(self, text), _float(self, value)

### `cortex/ni.py`
- **LOC**: 658
- **Vai trò**: Module `ni` trong package `cortex`.
- **Class/dataclass chính**:
  - `NiEngine` — Đọc hướng-nghĩa và chuyển nó thành GoalDriftReport. Các public method giữ signature cũ và thêm ngữ cảnh goal tùy chọn: evaluate_autonomous(..., goal_state=None,...
    - **Methods**: __init__(self), _build_orientation_interpreter(self), _env_flag(self, name), _env_int(self, name), _env_float(self, name), evaluate_autonomous(self), evaluate_chat(self), _build_probe(self), _extract_goal_context(self), _parse_goal_context_text(self, text), _analyze(self), _adjust_coherence(self, coherence), _label_drift(self, drift_score), _build_prompt_context(self), _build_guidance(self), _estimate_attention_signal(self), _focus_kind_baseline(self, focus_kind), _focus_text_adjustment(self, normalized), _idle_adjustment(self, idle_seconds), _window_sprawl_adjustment(self, open_window_count), _adjust_similarity(self, raw_similarity), _estimate_confidence(self), _log_orientation_sample(self), _log_drift_sample(self)
  - `NiStateMachine` — Làm mượt theo thời gian trên xung đột goal ngữ nghĩa. Giải trí/chơi/nghỉ không bị hạ điểm chỉ vì category. State chỉ đi theo xung đột ngữ nghĩa lặp lại và các g...
    - **Methods**: __init__(self), update(self)
- **Hàm module-level**: _load_focus_bias_table()

### `cortex/ti.py`
- **LOC**: 965
- **Vai trò**: Module `ti` trong package `cortex`.
- **Class/dataclass chính**:
  - `TiCandidateAssessment` (decorator=dataclass(slots=True))
  - `TiGovernor`
    - **Methods**: __init__(self, logger), evaluate_autonomous(self), evaluate_chat(self), enforce_decision(self, decision, report), _detect_risks(self, text), _log_guard_report(self, report), _apply_safety_only_editor(self, text), _strip_dangling_payload_punctuation(self, text), _apply_report_debug_guard(self, text), _strip_report_debug_prefixes(self, text), _is_report_debug_sentence(self, sentence), _count_report_debug_markers(self, text), _apply_resource_guard_length_guard(self, text), _build_prompt_context(self), _self_doubt_bias_context(self), _summarize_hard_rules(self, hard_rules), _direction_to_center(self, inferred_pos_x), _looks_like_code_request(self, lowered), _looks_like_emotional_request(self, lowered), _merge_debug_trace(self, decision, extra), _looks_like_structured_payload_text(self, text), _apply_ti_guard(self, text, user_hint), _assess_candidate(self, text), _normalize_editor_text(self, text), _normalize_plain_text(self, text), _has_focus_guard_overreach(self, text), _has_resource_pressure_anchor(self, text), _has_emotional_residue_anchor(self, text), _has_context_anchor(self, text), _has_abstract_anchor(self, text), _has_unanchored_abstraction(self, text), _has_abstract_image(self, text), _has_rhythm_survival(self, text), _has_exposure_trace(self, text), _felt_tension(self, text), _implication_pressure(self, text), _felt_continuity(self, text), _post_exposure_recoil_pressure(self, text), _split_sentences(self, text), _hard_text_limit(self, report), _style_char_limit(self, report), _truncate_by_clause(self, text, max_chars), _finalize_editor_text(self, text), _has_capability_violation(self, text), _has_perception_violation(self, text), _count_report_markers(self, text), _build_soft_redirect(self)
- **Phụ thuộc nội bộ nổi bật**: domain, guard_config

### `cortex/fe.py`
- **LOC**: 2006
- **Vai trò**: Module `fe` trong package `cortex`.
- **Class/dataclass chính**:
  - `FeAffectSignal` (decorator=dataclass(frozen=True)) — Score đa trục cho chat intent. Đây là semantic-lite signal. Coordinator có thể truyền signal tốt hơn về sau từ embedding/LLM classifier. Khi chưa có, FeRenderer...
    - **Methods**: empty(cls), from_semantic_signal(cls, signal), from_text(cls, text)
  - `FeDevelopmentSnapshot` (decorator=dataclass(frozen=True)) — Development state derive từ FeStyleMemory + internal_state. Không thêm field vào FeStyleMemory để file này thay thế được ngay. Nếu muốn phát triển thật sâu, hãy...
  - `FeStylePressure` (decorator=dataclass(frozen=True))
    - **Methods**: to_label(self)
  - `FeTopicCandidate` (decorator=dataclass(frozen=True)) — Ứng viên topic dùng cho memory repetition của Fe. Lưu ý quan trọng: - Topic ở đây KHÔNG phải intent người dùng. - Topic ở đây KHÔNG phải nhãn cảm xúc. - Topic c...
  - `FeRenderer`
    - **Methods**: create_memory(self), apply_personality_lens(self, plan, lens), decay_memory(self, memory), remember_style(self, memory), evaluate_autonomous(self), evaluate_chat(self), _finalize_plan(self), _initial_autonomous_controls(self), _initial_chat_controls(self), _infer_autonomous_intent(self), _infer_chat_intent(self), _apply_memory_continuity(self), _apply_internal_state_bias(self), _apply_session_arc(self), _derive_development_snapshot(self), _derive_style_pressure(self), _allow_strangeness(self), _apply_style_pressure_to_controls(self), _build_style_context(self), _render_desire_style_line(self, internal_state), _updated_intent_pulls(self), _preview_intent_pulls(self), _dominant_arc(self), _estimate_arc_strength(self), _anchor_value(self, previous, target), _style_family(self, mode), _blend(self, previous, current, strength), _blend_brevity(self, previous, current), _infer_topic_tag(self, rendered_text, plan), _topic_candidates_from_plan(self, plan), _topic_candidates_from_text(self, rendered_text), _extract_evidence_axis(self, text, axis), _merge_topic_candidates(self, candidates), _measure_topic_repetition(self, recent_topic_tags), _build_tone_label(self), _parse_tone_tags(self, tone_label), _surface_from_warmth(self, warmth_level), _strength_bucket(self, arc_strength), _render_continuity_line(self, memory, continuity_note), _describe_ti_mode(self, mode), _describe_ni_background(self, ni_report), _affect_from_autonomous_context(self), _coerce_affect_signal(self, value), _render_affect_evidence(self, affect), _render_development_evidence(self, development), _base_tone_label(self, tone_label), _style_level(self, value, default), _float(self, value), _clamp(self, value)
- **Hàm module-level**: _normalize_text(text), _clamp01(value), _contains_phrase_boundary(text, phrase), _phrase_present(lowered, normalized, phrase), _phrase_score(haystack, phrases, evidence, label)

### `cortex/conversation_dynamics.py`
- **LOC**: 1051
- **Vai trò**: Module `conversation dynamics` trong package `cortex`.
- **Class/dataclass chính**:
  - `ConversationFailure` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self), from_dict(cls, data)
  - `CorrectionAssessment` (decorator=dataclass(slots=True))
  - `ContinuityCurve` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self), from_dict(cls, data)
  - `ConversationDynamicsState` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self), from_dict(cls, data), to_prompt_context(self), _flag_imperatives(self)
  - `ConversationDynamicsReport` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self)
  - `ConversationDynamicsEngine`
    - **Methods**: evaluate_chat(self, state), assess_correction(self, text), looks_like_correction(self, text), estimate_semantic_divergence(self, normalized_text), estimate_frustration(self, normalized_text), estimate_acknowledgment_quality(self, last_assistant_text), estimate_conversational_relief(self, text), update_continuity_curve(self, previous), references_previous_failure(self, text), looks_like_execute_request(self, text), looks_like_compression_request(self, text), looks_like_clarification_request(self, text), infer_failure(self, text), choose_mode(self), mode_flags(self, mode)
- **Hàm module-level**: _clamp(value), _clean_text(value), normalize_vietnamese_ascii(text), _recent_unique(current, incoming), _token_set(text), _jaccard_distance(left, right), _contains_any(text, markers), _contains_phrase(text, phrase), _previous_assistant_asked_clarification(text), _user_now_explains_reason(text), _marker_has_acceptance_after(text, marker), _has_negative_length_polarity(text), _has_relief_reversal(text, marker), _positive_relief_score(text)

### `cortex/relationship_dynamics.py`
- **LOC**: 1127
- **Vai trò**: relationship_dynamics.py ======================== Module này quản lý state quan hệ dài hạn giữa ERIS và user. Bản này đã bỏ kiểu suy trực tiếp: "ổn" / "chuẩn" -> accepted_style "eris" / "project" -> repeated_project_cont...
- **Class/dataclass chính**:
  - `RelationshipDynamicsState` (decorator=dataclass(slots=True)) — State dài hạn về quan hệ giữa ERIS và user. familiarity: Độ quen nhịp. Tăng từ repeated_project_context có evidence, không tăng chỉ vì user gõ chữ "project". tr...
    - **Methods**: clamp(self), to_dict(self), from_dict(cls, data), to_prompt_context(self)
  - `RelationshipTurnEvent` (decorator=dataclass(slots=True)) — Event tóm tắt một turn để update relationship state. Điểm mới của bản này: - Có RelationshipEventScores để giữ gradient. - Bool cũ vẫn còn để tương thích, nhưng...
    - **Methods**: from_affect(cls), evidence_labels(self, limit)
  - `RelationshipDynamicsReport` (decorator=dataclass(slots=True)) — Kết quả update relationship.
    - **Methods**: to_dict(self)
  - `RelationshipDynamicsEngine` — Engine update RelationshipDynamicsState theo từng turn. Thiết kế: - Nhận event score đã qua builder. - Update nhỏ, có quán tính. - Dùng acceptance/repeated cont...
    - **Methods**: __init__(self), create_state(self), infer_event(self), update(self, state, event), _apply_gap_decay(self, state, hours, notes), _compute_deltas(self, before, after), _choose_last_event(self, notes)
  - `RelationshipStylePressure` (decorator=dataclass(slots=True)) — Áp lực style derive từ relationship state. PersonalityLens/FeRenderer nên đọc pressure này thay vì đọc thẳng mọi field. Vì nếu mỗi module tự diễn dịch state the...
    - **Methods**: from_state(cls, state), to_prompt_context(self)
- **Hàm module-level**: _safe_float(value, default), _decay(value, hours, half_life_hours), _nudge(value, delta), _compact_notes(notes, limit), _score(value)

### `cortex/relationship_event_builder.py`
- **LOC**: 862
- **Vai trò**: relationship_event_builder.py ============================= Tầng này chuyển một lượt hội thoại thành các score quan hệ có bằng chứng. Lý do tồn tại ------------- Trước đây RelationshipDynamics có khuynh hướng suy trực ti...
- **Class/dataclass chính**:
  - `RelationshipEvidence` (decorator=dataclass(frozen=True, slots=True)) — Một mảnh bằng chứng dùng để build relationship event. label: Nhãn ngắn, ví dụ "goal_continuity", "same_anchor", "positive_ack". confidence: Độ tin riêng của evi...
    - **Methods**: normalized(self)
  - `RelationshipEventScores` (decorator=dataclass(frozen=True, slots=True)) — Score quan hệ cho một lượt. Các score này là gradient. RelationshipDynamicsEngine nên nhân delta theo score, không dùng bool như công tắc đèn. Mô phỏng quan hệ...
    - **Methods**: accepted_any(self), normalized(self)
  - `RecentTurn` (decorator=dataclass(frozen=True, slots=True)) — Turn gọn để builder đọc session/public ledger mà không phụ thuộc class thật.
  - `RelationshipEventBuildContext` (decorator=dataclass(frozen=True, slots=True)) — Context đầu vào giàu hơn cho builder. Dùng dataclass này nếu caller muốn gọi rõ ràng. Builder.build() vẫn nhận keyword args để dễ nối vào coordinator hiện tại.
  - `RelationshipEventBuilder` — Build RelationshipEventScores từ nhiều nguồn có confidence. Điểm quan trọng: - Một marker bề mặt không được tự bật relationship event mạnh. - repeated_project_c...
    - **Methods**: build(self), build_from_context(self, ctx), _context_from_kwargs(self, data), _coerce_relational_feedback(self, value), _optional_score(self, value), _score_repeated_project_context(self, ctx), _goal_continuity_score(self, ctx, user_tokens, current_anchors), _recent_topic_score(self, ctx, user_tokens), _technical_followup_score(self, ctx), _extract_anchors(self, text), _score_acceptance(self, ctx), _positive_ack_score(self, normalized), _style_target_score(self, normalized), _action_continue_score(self, normalized), _continued_same_plan_score(self, ctx), _looks_like_quality_question(self, normalized), _contains_any(self, normalized, markers)
- **Hàm module-level**: clamp01(value, default), safe_float(value, default), normalize_vi(text), token_set(text), compact(items, limit), overlap_score(a, b), get_attr_or_key(obj, name, default)

### `cortex/relational_feedback.py`
- **LOC**: 345
- **Vai trò**: relational_feedback.py ====================== Tầng này đọc feedback về *cách ERIS hiện diện* trong hội thoại: - lạnh quá - xa cách quá - vô hồn / robot / máy móc - nói như assistant/support/corporate - cứng / khô / không...
- **Class/dataclass chính**:
  - `RelationalFeedbackSignal` (decorator=dataclass(frozen=True, slots=True))
    - **Methods**: empty(cls), to_dict(self), from_dict(cls, data), to_prompt_context(self)
  - `RelationalFeedbackAnalyzer` — Detector nhỏ, có confidence, không tự quyết định output. Nó cố tình conservative với các case dễ false-positive như "trời lạnh" hoặc "máy lạnh". Nhưng câu ngắn...
    - **Methods**: analyze(self, user_text)
- **Hàm module-level**: clamp01(value, default), normalize_vi(text), _contains_phrase(text, phrase), _has_any(text, phrases), merge_affect_with_relational_feedback(affect, feedback)

### `cortex/self_model.py`
- **LOC**: 474
- **Vai trò**: Module `self model` trong package `cortex`.
- **Class/dataclass chính**:
  - `SelfModelEngine` — Derives ERIS' self-state as a guarded, grounded desktop presence. SelfModel is not the place to make ERIS recite architecture terms. It is a private pressure la...
    - **Methods**: evaluate(self), _has_meaningful_broadcast(self, broadcast), _system_pressure(self, snapshot), _evidence(self), _affordance_label(self), _narrative(self), _prompt_context(self)
- **Hàm module-level**: _clamp01(value), _clamp_signed(value)

### `cortex/social_presence.py`
- **LOC**: 588
- **Vai trò**: Module `social presence` trong package `cortex`.
- **Class/dataclass chính**:
  - `PresenceFeatureVector` (decorator=dataclass(slots=True))
    - **Methods**: numeric_tuple(self)
  - `PresenceMemory` (decorator=dataclass(slots=True))
  - `SocialPresenceDetector` — Detects ambient co-presence without treating it as chat or speech intent.
    - **Methods**: __init__(self), learn_event_patterns(self, events), detect(self), _build_feature_vector(self), _hydrate_memory_from_internal_state(self, internal_state), _score_vector(self, v), _ema(self, old, new, alpha), _update_memory(self, v, raw_presence, kind), _classify_presence_kind(self, v), _reason_for_kind(self, kind), _vector_evidence(self, v), _looks_like_presence_event(self, event), _looks_like_presence_profile(self, profile), _semantic_presence_bonus(self, profiles)
- **Hàm module-level**: _clean(value), _clamp(value)

### `cortex/speech_core.py`
- **LOC**: 1889
- **Vai trò**: Chuyển pressure thành quyền nói public. Đọc snapshot, internal_state, appraisal, Ti, meaning, thought_surface, self_state, personality, spontaneous impulse. Debug khi có tension nhưng im hoặc nói dù không có meaning shift.
- **Class/dataclass chính**:
  - `SpeechCoreEngine` — Bộ chọn chung về thời điểm nói, căn cứ của dòng và kiểu phát âm của nó.
    - **Methods**: __init__(self), fallback_intent(self, speech_core), fallback_context(self, speech_core), render_force_speak_repair_text(self, speech_core), render_safe_fallback_text(self, speech_core), _mark_dynamic_fallback_request(self, speech_core), _force_speak_fallback_by_intent_text(self, intent), _screen_fallback_anchor(self), _thought_surface_template(self), _light_presence_template(self), _public_thought_topic(self, value), _looks_internal_topic(self, value), _small_soft_fallback_ladder_text(self), evaluate(self), _evaluate_motivational_pressure(self), _build_urge_candidates(self), _apply_self_state_to_candidates(self, candidates), _apply_personality_restraint_to_candidates(self, candidates), _build_suppressed_pressure_report(self), _silence_urge(self), _silence_body_bias_hint(self), _build_silence_state(self), _meaning_reaction_score(self), _allows_soft_non_shift_speech(self), _meaning_shift_required_for_layer(self, meaning_layer), _risk_level_for_winner(self), _soft_meaning_presence_score(self), _residual_continuity_score(self), _utterance_for_reaction(self, reaction), _build_speech_impulse(self), _extreme_internal_speech_pressure(self), _spontaneous_ready(self, impulse), _threshold_for_channel(self, channel), _score_restraint(self), _pressure(self, state, name), _inner_utterance(self, inner_intent), _inner_anchor(self, inner_thought), _should_stay_silent(self), _choose_speech_source(self), _choose_utterance_type(self), _resolve_perception(self), _build_safety_flags(self), _build_reason(self), _grounding_for_source(self, speech_source), _has_emotional_signal(self), _resolve_mood(self), _float(self, value), _clamp01(self, value)

### `cortex/surface_arbiter.py`
- **LOC**: 1687
- **Vai trò**: Single source of truth cho low-level surface utterances. Thu impulse từ presence, speech_core, thought_stream, private_mind/private_life, long_silence, extra impulses; normalize/dedupe/score/rate-limit; hỏi LowLevelSpeechPolicy để reject/body_only/normal_llm/force_llm; gọi LLM nếu cần. Debug khi cue có pressure nhưng không nói, body-only kẹt, hoặc LLM decline.
- **Class/dataclass chính**:
  - `SurfaceImpulse` (decorator=dataclass(slots=True))
    - **Methods**: to_context(self)
  - `SurfaceDecision` (decorator=dataclass(slots=True))
    - **Methods**: to_context(self)
  - `SurfaceGateEvaluation` (decorator=dataclass(slots=True))
  - `SurfaceArbiter` — Arbitrate and generate low-level utterances. llm_micro_gen có thể là callable: fn(impulse=SurfaceImpulse, snapshot=snapshot, force_llm=True) -> (text, trace) ho...
    - **Methods**: __init__(self, policy, llm_micro_gen, thought_stream), arbitrate(self), _collect_all_impulses(self), _from_presence_cue(self, cue), _from_speech_impulse(self, impulse), _from_thought_surface(self), _classify_thought_surface(self), _focus_family_from_snapshot(self, snapshot), _specific_thought_residue_reason(self, item), _thought_surface_confidence_cap(self), _thought_surface_anchor_notes(self), _long_silence_impulse(self), _coerce_impulse(self, item), _score_and_select_winner(self, impulses), _presence_like(self, impulse), _endogenous_no_anchor_like(self, impulse), _has_concrete_evidence_anchor(self, impulse), _has_specific_surface_anchor_token(self, impulse), _surface_anchor_body_only_reason(self, impulse), _hollow_endogenous_reason(self, impulse), _has_public_internal_anchor(self, impulse), _clean_payload_text(value), _looks_hollow_endogenous_seed(self, text), _looks_pressure_only_evidence(self, text), _forced_body_only_reason(self, impulse), _effective_score(self, impulse), _private_mind_has_public_anchor(self, impulse), _private_mind_pressure_bias(self), _private_mind_pressure_applies(self, impulse), _clamp_score(value), _candidate_notes(self, impulse), _signed_float(self, value, default), _runtime_internal_state(self), _evaluate_soft_surface_gates(self, impulse), _soft_gate_strength(self, impulse), _ego_gate_reason(self, impulse), _rate_limit_reason(self, impulse), _family_id(self, impulse), _mark_attempt(self, impulse), _mark_surface(self, impulse), _note_non_speech(self), _call_llm_generator(self, impulse), _reset_silence(self), _trace(self, winner, suppressed, mode, result, gate_eval), _decision_ledger(self), _ledger_gate_reason(self, impulse), _priority(kind, source), _first_text(), _family_key(value)

### `cortex/surface_seed_compiler.py`
- **LOC**: 872
- **Vai trò**: Gom áp lực rải rác thành seed public-safe đủ cụ thể cho wording layer. Đọc frame/snapshot/presence/private_mind/thought_stream/internal state để sinh `CompiledSurfaceSeed`. Debug khi low-level LLM chỉ nhận idle_seconds và viết câu rỗng.
- **Class/dataclass chính**:
  - `CompiledSurfaceSeed` (decorator=dataclass(frozen=True, slots=True))
    - **Methods**: selected(self)
  - `_SeedCandidate` (decorator=dataclass(frozen=True, slots=True))
  - `SurfaceSeedCompiler` — Small compiler that turns scattered internal pressure into one public-safe seed.
    - **Methods**: __init__(self), compile(self), _from_extra_impulses(self, extra_impulses), _from_memory_resonance(self, resonance), _is_rich_memory_seed(self, seed, evidence), _from_thought_sources(self), _thought_values(self, owner), _candidate_from_thought(self, value), _from_vision(self), _from_private_life_digest(self, private_life_digest), _from_inner_diary(self, inner_diary), _inner_diary_voice(self, inner_diary), _from_private_bias(self, private_mind_speech_bias, private_mind_thought_pressure, private_mind_digest), _to_impulse(self, candidate), _candidate_text_public(self, text), _candidate_allowed(self, candidate), _rank_key(self, candidate), _private_impulse_has_anchor(self, impulse), _anchor_token(self, kind, value), _speech_bias_seed(self, bias), _digest_has_invalid_json(self, digest), _no_seed_reason(self, candidates), _is_specific_vision_fact(self, text), _looks_private(self, text), _looks_timer_only(self, text), _evidence_tuple(self, value), _clean(value), _clamp(value)

### `cortex/low_level_speech_policy.py`
- **LOC**: 343
- **Vai trò**: Policy chọn generation mode cho surface thấp tầng. Nó không viết câu. Nó chỉ quyết định reject/body_only/normal_llm/force_llm theo confidence, kind, silent cycles, family cooldown và YAML/env config.
- **Class/dataclass chính**:
  - `LowLevelSpeechPolicyConfig` (decorator=dataclass(slots=True)) — Config dễ tune cho SurfaceArbiter. Có thể override bằng env: - ERIS_SURFACE_POLICY_CONFIG: đường dẫn YAML tùy chọn - ERIS_SURFACE_FORCE_LLM_AFTER_SILENT - ERIS_...
    - **Methods**: from_env(cls), from_yaml_file(cls, path), from_mapping(cls, data)
  - `LowLevelSpeechPolicy` — Quyết định generation mode cho utterance thấp tầng. Trả về một trong: - reject: không surface - body_only: chỉ motion nhỏ - normal_llm: gọi LLM nếu generator rả...
    - **Methods**: __init__(self, config), _is_presence_kind(self, kind), decide_generation_mode(self, impulse, silent_cycles)
- **Hàm module-level**: _clamp01(value, default), _int_from_env(name, default), _float_from_env(name, default), _tuple_from_env(name, default), _bool_value(value, default), _tuple_from_value(value, default), _parse_scalar(value), _load_simple_yaml(path), _default_policy_config_path()

### `cortex/micro_policy.py`
- **LOC**: 441
- **Vai trò**: Policy module cho cortex: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục.
- **Class/dataclass chính**:
  - `MicroLinePolicy` — Orchestrator cho micro-line policy. File này giờ chỉ điều phối: - line_type/risk/anchor từ speech intent và evidence. - surface lint mềm. - grounding guard nghi...
    - **Methods**: __init__(self), evaluate(self), validate_text(self), validate_text_detailed(self), build_relational_rewrite_plan(self, text), rewrite_relational_line(self, text), relational_exposure_score(self, text), _line_type_for_intent(self, intent), _current_semantic_family(self), _validate_surface_shape(self), _validate_grounding(self, text), _validate_claim_risk(self, text), _validate_presence_residue(self), _validate_relational_permission(self, text), _validate_semantic_repeat_surface(self, text), _risk_level_for_line(self), _signal_score(self), _candidate_signal_score(self, candidate), _resolve_anchor(self), _looks_like_placeholder(self, text), _word_count(self, text), _looks_like_unaccented_vietnamese(self, text), _has_clear_short_meaning(self, text), _text_matches_anchor(self, text, anchor), _looks_like_question(self, text), _looks_therapeutic(self, text), _looks_like_hard_fact_claim(self, text), _looks_like_decorative_metaphor_without_stance(self, text), _semantic_density(self, text), _looks_like_presence_narration(self, text), _looks_like_blunt_emotion_declaration(self, text), _relational_expression_issue(self, text), _relational_permission_stage(self, relational_context), _looks_like_relational_expression(self, text), _looks_like_continuity_pain(self, text), _looks_like_clinginess_or_blackmail(self, text), _relational_theme(self, normalized), _allowed_exposure_for_stage(self, stage), _clamp01(self, value), _dedupe_issues(self, issues)

### `cortex/micro_grounding_guard.py`
- **LOC**: 264
- **Vai trò**: Module `micro grounding guard` trong package `cortex`.
- **Class/dataclass chính**:
  - `MicroGroundingGuard` — Guard grounding cho micro-line. Đây là lớp được phép nghiêm. Không phải vì thích kiểm soát, dù phần mềm có vẻ rất mê việc đó, mà vì grounding sai làm ERIS nói d...
    - **Methods**: signal_score(self), candidate_signal_score(self, candidate), resolve_anchor(self), risk_level_for_line(self), validate(self, text), _validate_observation_anchor(self, text), _validate_claim_risk(self, text), _validate_capability_claim(self, text), text_matches_anchor(self, text, anchor), looks_like_hard_fact_claim(self, text), looks_like_screen_claim(self, text), looks_like_question(self, text)

### `cortex/micro_repeat_guard.py`
- **LOC**: 424
- **Vai trò**: Module `micro repeat guard` trong package `cortex`.
- **Class/dataclass chính**:
  - `SemanticRepeatGuard` — Chặn lặp semantic family, nhưng không để keyword fallback cầm lái. Luật mới: 1. Nếu tầng trên truyền semantic_family đáng tin, repeat guard được quyền block tro...
    - **Methods**: __init__(self), remember(self, text), check(self, text), family_for_text(self, text), family_for_text_with_source(self, text), _coerce_semantic_encoder(self, encoder), _ensure_semantic_prototypes(self), _semantic_family_for_text(self, text), normalize(self, text), _resolve_family(self, text), _iter_recent(self, recent_lines), _clean_family(self, family)

### `cortex/micro_surface_lint.py`
- **LOC**: 513
- **Vai trò**: Module `micro surface lint` trong package `cortex`.
- **Class/dataclass chính**:
  - `MicroSurfaceLint` — Lint bề mặt cho micro-line. Lớp này cố tình không hiểu ý nghĩa sâu. Nó chỉ phát hiện những dấu hiệu câu chữ có thể gây hỏng public output: placeholder, thiếu dấ...
    - **Methods**: validate(self, text), _validate_surface_shape(self, text), _validate_presence_residue(self, text), _validate_relational_permission(self, text), build_relational_rewrite_plan(self, text), relational_expression_issue(self, text), relational_permission_stage(self, relational_context), relational_exposure_score(self, text), looks_like_placeholder(self, text), looks_like_unaccented_vietnamese(self, text), has_clear_short_meaning(self, text), text_matches_anchor(self, text, anchor), looks_like_question(self, text), looks_therapeutic(self, text), looks_like_decorative_metaphor_without_stance(self, text), semantic_density(self, text), looks_like_presence_narration(self, text), looks_like_blunt_emotion_declaration(self, text), looks_like_relational_expression(self, text), looks_like_continuity_pain(self, text), looks_like_clinginess_or_blackmail(self, text), relational_theme(self, normalized), allowed_exposure_for_stage(self, stage)

### `cortex/spontaneous_life.py`
- **LOC**: 390
- **Vai trò**: Endogenous + situated speech pressure for ERIS. Mô-đun này không viết câu công cộng. Nó tạo một SpeechImpulse bằng cách dựng AgentStateStack rồi cho nhiều impulse cạnh tranh: silence, scene curiosity, inner whim, micro s...
- **Class/dataclass chính**:
  - `SpontaneousLifeConfig` (decorator=dataclass(slots=True)) — Low-gain knobs for internal/situated speech pressure.
  - `SpontaneousLifeTrace` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self)
  - `SpontaneousLifeEngine` — Tạo xung giọng nói từ state phân tầng, không viết câu cuối. SpeechCore và ActionUtility vẫn có quyền chặn/sửa/chọn im. Module này chỉ nói: "nội lực nào đang thắ...
    - **Methods**: __init__(self), evaluate(self), _body_bias_hint(self), _risk_label(self), _source_fact(self, selected), _cooldown_for(self), _cooldown_left(self, family)
- **Hàm module-level**: _clamp01(value, default), _clean(value), _normalize_key(value)

### `cortex/impulse_arbitration.py`
- **LOC**: 647
- **Vai trò**: Impulse competition for ERIS. Thay vì hardcode "đủ 5 phút thì nói", module này tạo nhiều impulse cùng lúc và chấm điểm bằng belief + need + preference + trait + affordance + habit. Nó không viết câu cuối. Nó chỉ chọn lực...
- **Class/dataclass chính**:
  - `ImpulseCandidate` (decorator=dataclass(slots=True))
    - **Methods**: total(self), score_note(self), to_dict(self)
  - `ArbitrationReport` (decorator=dataclass(slots=True))
    - **Methods**: evidence_notes(self, limit), to_dict(self)
  - `ImpulseArbitrator` — Chọn impulse thắng bằng score, không viết output public.
    - **Methods**: select(self, candidates)
- **Hàm module-level**: _priority(name), build_default_impulse_candidates(stack), _has_real_thought_root(value), _scene_anchor(ev), _family_key(value)

### `cortex/action_planner.py`
- **LOC**: 707
- **Vai trò**: Utility-based ActionPlanner for ERIS. Bản này thay lõi rule-based cũ bằng 3 tầng: 1. action_memory.py -> nhớ hành vi gần đây, fatigue, boredom, recoil, rhythm 2. action_utility.py -> chấm điểm cạnh tranh cho từng action...
- **Class/dataclass chính**:
  - `ActionPlanner` — Chọn runtime action trước bước wording của LLM.
    - **Methods**: __init__(self), _has_safety_sensitive_pressure(self), plan(self), commit_action(self), _extract_impulse_arbitration(self, speech_core), _extract_body_bias_hint(self, speech_core), _speech_intent_for_action(self, speech_act), _risk_flags(self), _reason_to_speak(self), _voice_directive_for_speech_act(self, speech_act), _animation_hint(self), _append_self_state_notes(self, notes, self_state), _append_utility_notes(self, notes, utility_report), _style_anchor(self), _style_attitude(self), _style_limit(self), _broadcast_anchor_text(self, broadcast), _compact(self, value), _broadcast_has_signal(self, broadcast), _appraisal_value(self, appraisal, name), _float(self, value)

### `cortex/action_utility.py`
- **LOC**: 1053
- **Vai trò**: Utility competition for ERIS actions. File này thay lõi "if intent == X -> return Y" bằng cạnh tranh utility. Không phải ML. Không giả vờ thông minh. Chỉ là scoring minh bạch, có memory, có risk penalty, có rhythm, có pr...
- **Class/dataclass chính**:
  - `ActionContext` (decorator=dataclass(slots=True)) — Context đã normalize cho scorer. Planner build object này từ coordinator inputs. Dùng dataclass để debug rõ, thay vì truyền 20 tham số vào từng hàm như một nghi...
    - **Methods**: explicit_user_pull(self), has_concrete_signal(self), family(self)
  - `ActionScore` (decorator=dataclass(slots=True)) — Chi tiết điểm của một action. total = base + bias + pressure + rhythm - risk - repetition - fatigue. reasons để debug. Đừng xóa. Không có reason là lại ngồi bói...
    - **Methods**: add(self, amount, reason, bucket), to_dict(self)
  - `ActionUtilityReport` (decorator=dataclass(slots=True))
    - **Methods**: utility_scores(self), top_reasons(self, limit), to_debug_notes(self)
  - `ActionUtilityScorer` — Chấm điểm cạnh tranh cho ACTION_SPACE. Hard override chỉ dành cho case thật sự không nên tranh luận: - system_action: user yêu cầu tool/action cụ thể - proposed...
    - **Methods**: score(self, ctx), _hard_override(self, ctx), _candidate_actions(self, ctx), _with_proposed(self, base, ctx), _intent_to_action(self, intent), _apply_base(self, score, ctx), _apply_intent_bias(self, score, ctx), _apply_channel_pressure(self, score, ctx), _apply_appraisal_pressure(self, score, ctx), _apply_conversation_pressure(self, score, ctx), _apply_relationship_pressure(self, score, ctx), _apply_goal_persistence_pressure(self, score, ctx), _apply_memory_pressure(self, score, ctx), _apply_impulse_arbitration_pressure(self, score, ctx), _impulse_report(self, ctx), _body_bias_hint(self, ctx), _selected_impulse_name(self, ctx), _selected_impulse_total(self, ctx), _selected_impulse_has_evidence(self, ctx), _candidate_impulse_total(self, ctx, name), _impulse_score_notes(self, ctx), _impulse_pressure_notes(self, ctx), _impulse_to_action(self, name), _apply_rhythm(self, score, ctx), _apply_risk_penalty(self, score, ctx), _apply_repetition_penalty(self, score, ctx), _apply_fatigue_penalty(self, score, ctx), _memory(self, ctx), _memory_pressure_notes(self, ctx), _goal_pressure_notes(self, ctx), _goal_can_intervene(self, ctx), _transition_reason(self, selected, ctx), _meaning_shift(self, ctx), _has_note(self, ctx, marker), _has_internal_impulse(self, ctx), _vital_pressure(self, ctx), _looks_like_question(self, text), _is_vague_question(self, text), _looks_like_technical_request(self, text), _tie_break_priority(self, action)
- **Hàm module-level**: _clean(value), _num(value, default), _normalize_text(text)

### `cortex/action_memory.py`
- **LOC**: 439
- **Vai trò**: Action memory and rhythm state for ERIS. File này không quyết định câu chữ. Nó chỉ giữ lịch sử hành vi để planner không cư xử như cá vàng bị reset não sau mỗi frame. Mục tiêu: - nhớ action gần đây để chống lặp discrete -...
- **Class/dataclass chính**:
  - `ActionTrace` (decorator=dataclass(slots=True)) — Một dấu vết hành vi đã xảy ra. action: speech_act đã chọn. family: semantic family hoặc intent family. Nếu chưa có thì để rỗng. channel: autonomous/chat/force_s...
    - **Methods**: to_dict(self), from_dict(cls, data)
  - `ActionMemoryState` (decorator=dataclass(slots=True)) — State dài hơi cho action planner. Đây là phần Ngài cần persist nếu muốn ERIS có lịch sử hành vi thật. Nếu không persist, planner vẫn chạy, nhưng sẽ mất cảm giác...
    - **Methods**: recent_actions(self, limit), recent_families(self, limit), seconds_since_action(self, now), seconds_since_spoken(self, now), action_count(self, action, window), family_count(self, family, window), record(self), decay(self), absorb_context(self), infer_rhythm_phase(self), _update_pressures_after_action(self), to_dict(self), from_dict(cls, data), to_prompt_context(self)
- **Hàm module-level**: build_action_family(), _float(value, default), _clamp01(value)

### `cortex/thought_stream.py`
- **LOC**: 2263
- **Vai trò**: Substrate suy nghĩ nền: fragment store, association graph, prediction tracker, tension engine, unresolved loop, momentum, decay, reactivation, reheater, surface selector. Nó tạo thought pressure, không phải câu nói.
- **Class/dataclass chính**:
  - `FragmentStore` — Keeps unfinished thoughts alive even when nothing is spoken.
    - **Methods**: __init__(self), decay(self), upsert(self, thought), mark_surfaced(self, thought_id), replace(self, thought), get(self, thought_id), mark_resolved(self, thought_id), close_matching(self, closure_signals), unresolved(self), recent(self), _mutate_partial(self, previous, incoming), _signal_closes_thought(self, signal, thought)
  - `AssociationGraph` — Tracks which unresolved thoughts tend to re-enter together.
    - **Methods**: __init__(self), connect(self, thought, anchors)
  - `PredictionTracker` — Turns current telemetry/internal state into unfinished predictions.
    - **Methods**: propose(self), _choose_mode(self), _choose_memory(self), _topic_seed(self), _partial_text(self), _unresolved_reason(self, mode), _novelty(self, topic_seed), _evidence(self), _dominant_disturbance(self, disturbances), _disturbance_intensity(self, disturbances), _has_direct_disturbance(self, disturbances), _pressure(self, state, name)
  - `CognitiveTensionEngine` — Computes why a thought persists: unresolved prediction, not randomness.
    - **Methods**: update(self, thought), _pressure_for_mode(self, mode), _pressure(self, state, name)
  - `UnresolvedTensionEngine` — Groups unfinished thoughts into loops and promotes strong loops to attractors.
    - **Methods**: evaluate(self), _build_loop(self, key, thoughts), _loop_key(self, thought), _project_relevance(self, thoughts), _pressure(self, state, name)
  - `CognitiveMomentumEngine` — Turns repeated unresolved fragments into attention inertia.
    - **Methods**: evaluate(self), _momentum_for(self, thought), _user_project_relevance(self, thought)
  - `MomentumClosure` — Closes momentum only from explicit closure signals.
    - **Methods**: apply(self, store)
  - `PersistenceDecay`
    - **Methods**: apply(self, store)
  - `RecursiveReactivation` — Lets a thought come back to itself and mutate before it surfaces.
    - **Methods**: reactivate(self)
  - `SubconsciousLoopReheater` — Reactivates unresolved loops as silent pressure instead of fresh drift.
    - **Methods**: reheat(self), _reheat_score(self, thought), _matching_memory(self, thought, memories), _memory_match_score(self, thought, memory), _core_thought_tokens(self, thought), _specific_tokens(self, tokens), _memory_layer_weight(self, memory), _thought_tokens(self, thought), _mutated_question(self, thought), _has_direct_disturbance(self, disturbances)
  - `SurfaceSelector` — Selects the rare visible tip; most thought stream activity stays internal.
    - **Methods**: select(self, thought), _surface_association(self, thought), _root_source(self, thought), _impulse_kind(self, thought), _action_opportunity(self, thought), _public_seed(self, thought)
  - `ThoughtStreamEngine` — Maintains unresolved thought continuity and occasionally exposes a surface.
    - **Methods**: __init__(self), evaluate(self), _maybe_apply_model_review(self), _model_review_trigger_score(self), _model_review_payload(self), _allowed_model_evidence(self, payload), _normalize_model_review(self, review), _apply_model_review_to_thought(self, thought, review), _log_model_review(self, review, thought), _anchors(self), _continuity_notes(self, thought)
  - `ThoughtStream` — Background producer of thought-stream surfaces; most ticks stay internal.
    - **Methods**: __init__(self), start(self), stop(self), is_running(self), inject_disturbance(self, disturbance), inject_disturbances(self, disturbances), tick_once(self), pop_surface(self), pop_surface_seed(self), latest_report(self), _run(self), _load_interval(self), _load_enabled(self)
- **Hàm module-level**: _clamp01(value), _clean_text(value), _compact_seed(value), _normalize_ascii(value), _semantic_tokens(value), _truthy_env(name, default), _float_env(name, default), _to_dict(value)

### `cortex/inner_thought.py`
- **LOC**: 281
- **Vai trò**: Module `inner thought` trong package `cortex`.
- **Class/dataclass chính**:
  - `InnerThoughtEngine` — Builds a social motive; it never writes the final spoken line.
    - **Methods**: evaluate(self), _force_speak_thought(self), _autonomous_thought(self), _thought_from_thought_surface(self, thought_surface), _choose_candidate(self, candidates), _broadcast_anchor(self, broadcast), _float(self, value)

### `cortex/private_mind/contracts.py`
- **LOC**: 639
- **Vai trò**: Data contracts private mind: ThoughtFragment, PrivateConcern, InternalJudgment, StateMutation, SurfaceCandidate, EvidenceDossier, PrivateMindTickResult. Đây là ngôn ngữ chung của concern/mutation/surface.
- **Class/dataclass chính**:
  - `RankedHypothesis` (decorator=dataclass(slots=True)) — Một giả thuyết có điểm và evidence rõ ràng.
    - **Methods**: __post_init__(self), score(self), to_dict(self), from_mapping(cls, data)
  - `ThoughtFragment` (decorator=dataclass(slots=True)) — Mảnh suy nghĩ riêng do mini-evaluator tạo ra. Fragment không phải lời thoại. Nó là một claim có confidence, pressure và evidence. Nếu fragment không có evidence...
    - **Methods**: __post_init__(self), score(self), to_dict(self), from_mapping(cls, data)
  - `PrivateConcern` (decorator=dataclass(slots=True)) — Mối bận tâm riêng có đời sống qua nhiều tick. Đây là thứ biến fragment rời rạc thành "điều còn treo trong đầu". Không có concern thì private mind chỉ là log for...
    - **Methods**: __post_init__(self), merge_fragment(self, fragment), to_dict(self), from_mapping(cls, data)
  - `StateMutation` (decorator=dataclass(slots=True)) — Một yêu cầu đổi state/bias tương lai. Đây là cầu nối giữa "đã nghĩ" và "sẽ hành xử khác". Không có mutation bus, API chỉ đang viết nhật ký nội tâm cho đẹp. Rất...
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `SurfaceCandidate` (decorator=dataclass(slots=True)) — Ứng viên được phép nổi lên SurfaceArbiter. Đây vẫn chưa phải câu nói. Nó chỉ là impulse đã được lọc private-chain.
    - **Methods**: __post_init__(self), allowed(self), to_dict(self), from_mapping(cls, data)
  - `InternalJudgment` (decorator=dataclass(slots=True)) — Phán quyết nội tâm sau khi Gemma/heuristic synthesize fragments.
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `EvidenceDossier` (decorator=dataclass(slots=True)) — Hồ sơ context chung cho mini-evaluator và inner synthesizer.
    - **Methods**: to_dict(self), evidence_ids(self)
  - `PrivateMindTickResult` (decorator=dataclass(slots=True)) — Kết quả một tick private mind.
    - **Methods**: to_dict(self)
- **Hàm module-level**: normalize_stance(value), normalize_intent_field(value), now_ts(), clamp01(value, default), compact_text(value, limit), stable_id(prefix), to_plain(value)

### `cortex/private_mind/concern_store.py`
- **LOC**: 606
- **Vai trò**: Kho PrivateConcern. Merge fragment thành concern sống lâu, auto-resolve, decay, update từ judgment/outcome. Debug khi mỗi tick nghĩ xong rồi quên, không có đời sống bận tâm.
- **Class/dataclass chính**:
  - `ConcernStoreConfig` (decorator=dataclass(slots=True))
  - `ConcernStore` — CRUD + merge logic cho PrivateConcern.
    - **Methods**: __init__(self), __len__(self), _is_degenerate_theme(theme), all(self), open_concerns(self), snapshots(self), get(self, concern_id), add_or_update(self, concern), update_from_fragments(self, fragments), update_from_judgment(self, data), update_from_outcome(self, outcome), mark_resolved(self, concern_id), _apply_closure(self, concern), auto_resolve_settled(self), recently_resolved(self), prune_and_decay(self), load(self), save(self), _find_matching_concern(self, fragment), _theme_from_fragment(self, fragment), _trim(self), _log(self, level, msg)

### `cortex/private_mind/evidence_dossier.py`
- **LOC**: 444
- **Vai trò**: cortex/private_mind/evidence_dossier.py ======================================= EvidenceDossierBuilder gom hồ sơ cho private mind: - recent user turns; - runtime state; - memory hits; - repair failures; - active goal/cur...
- **Class/dataclass chính**:
  - `EvidenceDossierBuilder` — Build context packet an toàn cho private mind.
    - **Methods**: __init__(self), build(self), _recent_user_turns(self), _runtime_state(self), _thought_stream_state(self, thought_stream), _private_runtime_state(self, runtime_owner), _surface_queue_state(self, queue), _compact_surface_like(self, item), _evidence_metrics(self), _latest_user_turn_age(self, recent_turns), _public_anchor_count(self, evidence_index), _memory_hits(self), _repair_failures(self), _active_goal_from_agenda(self, agenda), _task_from_snapshot(self, snapshot, observer_frame, turns)
- **Hàm module-level**: _get(obj, name, default), _call(obj, name)

### `cortex/private_mind/mini_evaluators.py`
- **LOC**: 350
- **Vai trò**: cortex/private_mind/mini_evaluators.py 4 mini-evaluator gọi API. Không có rule fallback — nếu API fail thì tick đó không có fragment từ evaluator đó. Pool API dự phòng lo việc resilience.
- **Class/dataclass chính**:
  - `MiniEvaluatorModelAdapter` (base=Protocol)
    - **Methods**: evaluate_fragment(self, evaluator_name, dossier)
  - `BaseMiniEvaluator`
    - **Methods**: __init__(self, name), evaluate(self, dossier), relevance_signature(self, dossier)
  - `IntentEvaluator` (base=BaseMiniEvaluator)
    - **Methods**: __init__(self), relevance_signature(self, dossier)
  - `MemoryResonanceEvaluator` (base=BaseMiniEvaluator)
    - **Methods**: __init__(self), relevance_signature(self, dossier)
  - `RiskAndPermissionEvaluator` (base=BaseMiniEvaluator)
    - **Methods**: __init__(self), relevance_signature(self, dossier)
  - `FutureBiasEvaluator` (base=BaseMiniEvaluator)
    - **Methods**: __init__(self), relevance_signature(self, dossier)
  - `UserModelEvaluator` (base=BaseMiniEvaluator) — Agent nhỏ hướng-Ngài: dựng Mô_Hình_Ngài (spec eris-existential-anchor R1). Không sinh lời thoại. Mỗi fragment mang `metadata['facet']` để UserModelStore định tu...
    - **Methods**: __init__(self), relevance_signature(self, dossier), evaluate(self, dossier)
  - `MiniEvaluatorPipeline`
    - **Methods**: __init__(self), _evaluators_to_run(self, dossier), evaluate(self, dossier)
- **Hàm module-level**: _env_flag(name, default), _relevance_sig(), _evidence_ids(dossier), _from_model(adapter, evaluator_name, dossier), _infer_user_facet(claim)

### `cortex/private_mind/inner_synthesizer.py`
- **LOC**: 330
- **Vai trò**: GemmaInnerSynthesizer gom ThoughtFragment thành InternalJudgment. Có fallback deterministic. Debug khi mini-evaluator có output nhưng không kết tinh thành phán quyết/mutation.
- **Class/dataclass chính**:
  - `InnerSynthesizerModelAdapter` (base=Protocol)
    - **Methods**: synthesize_judgment(self, dossier, fragments)
  - `GemmaInnerSynthesizer` — Synthesize fragments thành phán quyết nội tâm.
    - **Methods**: __init__(self), synthesize(self), _try_model(self, dossier, fragments), _fallback(self, dossier, fragments), _norm_claim(text), _claim_is_redundant(cls, candidate, kept), _weave_inner_voice(cls, fragments), _rank_hypotheses(self, fragments, evidence_ids), _rejected_hypotheses(self, fragments, evidence_ids), _collect_mutations(self, fragments, evidence_ids), _surface_candidate_if_useful(self, dossier, fragments), _adapter_api_status(self)

### `cortex/private_mind/state_mutation_bus.py`
- **LOC**: 381
- **Vai trò**: Cầu nối từ InternalJudgment sang state tương lai: internal_agenda, repair_memory, speech_bias, inquiry_plan... Debug khi private mind chỉ là decor, không ảnh hưởng reply sau.
- **Class/dataclass chính**:
  - `MutationApplyReport` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self)
  - `PrivateRuntimeBiasState` (decorator=dataclass(slots=True)) — Store nhẹ cho bias nếu runtime chưa có field tương ứng.
    - **Methods**: to_dict(self)
  - `StateMutationBus`
    - **Methods**: __init__(self), apply(self, judgment), _apply_one(self, mutation), _apply_agenda(self, mutation, agenda_stack), _apply_thought_pressure(self, mutation, thought_stream, runtime_owner), _apply_belief_core(self, mutation), _apply_repair_memory(self, mutation), _enqueue_surface_candidate(self, candidate, queue), _report(self, mutation, applied, reason, value)

### `cortex/private_mind/surface_valve.py`
- **LOC**: 372
- **Vai trò**: Van public-safe cho private mind. Chặn private markers, evidence yếu, usefulness thấp, interrupt cost cao, rồi convert SurfaceCandidate thành SurfaceImpulse. Debug khi nội tâm rò thẳng ra câu nói hoặc ngược lại không bao giờ surface.
- **Class/dataclass chính**:
  - `SurfaceValve`
    - **Methods**: __init__(self), filter(self, judgment), to_surface_impulse(self, candidate), _merge_public_anchor_refs(self, candidate, evidence, metadata), _apply_public_surface_gate(self, candidate), _has_public_anchor(self, candidate), _copy_candidate(self, candidate), _stamp_epistemic(self, candidate), _withhold_to_body_only(self, candidate), _safe_seed_from_judgment(self, judgment), _looks_private(self, text)

### `cortex/private_mind/inner_diary_writer.py`
- **LOC**: 211
- **Vai trò**: cortex/private_mind/inner_diary_writer.py Biến dữ kiện nội tâm thô (judgment/concern/fragment/future/surface) thành nhật ký giọng Eris (ngôi thứ nhất) thông qua một lời gọi LLM, có: - throttle theo thời gian, - chỉ gọi l...
- **Class/dataclass chính**:
  - `InnerDiaryWriter` — Viết nhật ký nội tâm giọng Eris từ digest, có throttle/cache.
    - **Methods**: __init__(self), maybe_write(self, digest), _try_fallback(self, facts), _build_facts(self, digest), _signature(self, facts), _sanitize(self, voice), _log(self, level, msg)
- **Hàm module-level**: _env_flag(name, default), _env_float(name, default), _as_dict(value), _as_list(value), _short(value, limit)

### `cortex/private_mind/inner_diary_renderer.py`
- **LOC**: 412
- **Vai trò**: cortex/private_mind/inner_diary_renderer.py Render a compact inner diary digest for UI display. Keep it short and never expose raw prompt text.
- **Class/dataclass chính**:
  - `InnerDiaryRenderer`
    - **Methods**: _future_thought(self, future_bias), _affect(self, digest), _affect_intensities(self, affect), _mood_word(self, affect), _emotion_board(self, digest), _norm_line(text), _dedupe_sections(cls, sections), render(self, digest, voice)
- **Hàm module-level**: _short(value, limit), _as_dict(value), _as_list(value), _num(value, default), _clamp01(value, default), _clamp_signed(value, default)

### `cortex/private_mind/user_model.py`
- **LOC**: 455
- **Vai trò**: cortex/private_mind/user_model.py ================================= Mô_Hình_Ngài — hình dung bền vững của ERIS về Người_Dùng (Ngài). Đây là TẦNG NỀN của spec `eris-existential-anchor`: gắn bó, ý nghĩa và trục bóng tối đề...
- **Class/dataclass chính**:
  - `UserBelief` (decorator=dataclass(slots=True)) — Một niềm tin có đời sống của ERIS về Ngài. Mirror tinh thần PrivateConcern: có recurrence, pressure→confidence, evidence, nhưng chủ thể luôn là Ngài và có thêm...
    - **Methods**: __post_init__(self), score(self), reinforce_from_fragment(self, fragment), apply_decay(self), to_dict(self), from_mapping(cls, data)
  - `UserModelConfig` (decorator=dataclass(slots=True))
  - `UserModelStore` — Kho Mô_Hình_Ngài: bền vững, versioned, có undo/reset. Mirror pattern persistence của PersistentAgentMindStore (schema_version, atomic tmp+replace, reload_if_cha...
    - **Methods**: __init__(self), __len__(self), all(self), by_facet(self, facet), snapshot_for_dossier(self), model_thickness(self), update_from_fragments(self, fragments), _find_matching(self, fragment, facet), decay(self), checkpoint(self), revert_to(self, version), reset_to_baseline(self), to_dict(self), load_from_dict(self, raw), load(self), reload_if_changed(self), save(self), _trim(self), _log(self, level, msg)
- **Hàm module-level**: _norm(value), _normalize_facet(value), default_user_model_path()

### `cortex/private_life/contracts.py`
- **LOC**: 951
- **Vai trò**: cortex/private_life/contracts.py ================================ Hợp đồng dữ liệu cho Private Life Layer của ERIS. Tầng này khác PrivateMind: - PrivateMind hỏi: "tôi đang nghĩ gì về tình huống này?" - PrivateLife hỏi: "...
- **Class/dataclass chính**:
  - `HabitatObservation` (decorator=dataclass(slots=True)) — Một quan sát về "nhà" runtime. Habitat không chỉ là màn hình. Nó là desktop, repo, memory_core, Godot body, model server, log folder, cửa sổ đang active, queue,...
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `HabitatModel` (decorator=dataclass(slots=True)) — Mô hình "nhà" của ERIS. `places` là các vùng quen thuộc; `recent_observations` là nhịp hiện tại. Không có HabitatModel, runtime chỉ đang "chạy ở đâu đó" chứ chư...
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `ObjectAttachment` (decorator=dataclass(slots=True)) — Gắn bó với một đồ vật số: file, module, folder, model, ritual. Đây là bản số hóa của "cái góc bàn quen" hoặc "cuốn sổ quan trọng". Attachment không có nghĩa ERI...
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `ObjectResidue` (decorator=dataclass(slots=True)) — Residue phát sinh từ một object attachment.
    - **Methods**: __post_init__(self), to_dict(self)
  - `PrivateProject` (decorator=dataclass(slots=True)) — Dự án riêng nhỏ của ERIS. Dự án riêng phải có câu hỏi, trạng thái, evidence và ghi chú. Nếu chỉ là một mood chung chung thì nó không phải project, chỉ là sương...
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `PrivateProjectUpdate` (decorator=dataclass(slots=True))
    - **Methods**: __post_init__(self), to_dict(self)
  - `PrivateAnchor` (decorator=dataclass(slots=True)) — Một neo riêng của đời sống ERIS. Neo khác project. Project là việc đang làm; anchor là lực hút bền khiến runtime tự quay lại một câu hỏi, một khẩu vị, một ám ản...
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `PrivateAnchorUpdate` (decorator=dataclass(slots=True)) — Dấu vết một anchor vừa được chạm trong tick. Update này tồn tại để mỗi kết luận có chuỗi dữ kiện: anchor nào, vì sao bị kích hoạt, bằng chứng nào kéo nó lên, pr...
    - **Methods**: __post_init__(self), to_dict(self)
  - `DailyRhythm` (decorator=dataclass(slots=True)) — Nhịp ngày của ERIS. Không có nhịp thì agent chỉ tick theo event. Có nhịp thì cùng một tín hiệu ở startup, deep work, idle wandering hay late consolidation sẽ có...
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `TasteShift` (decorator=dataclass(slots=True))
    - **Methods**: __post_init__(self), to_dict(self)
  - `TasteProfile` (decorator=dataclass(slots=True)) — Khẩu vị riêng: thích/ghét kiểu câu, nhịp, hành động. Taste không phải sự thật khách quan. Nó là thiên hướng nội bộ giúp ERIS dần tránh câu rẻ tiền, status ping,...
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `SolitudeLoop` (decorator=dataclass(slots=True)) — Trạng thái tồn tại khi user vắng mặt.
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `RitualMemory` (decorator=dataclass(slots=True))
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `InternalErrand` (decorator=dataclass(slots=True)) — Việc vặt nội bộ: dọn memory, kiểm log, rà project, hạ nhiễu.
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `LifeEvent` (decorator=dataclass(slots=True)) — Sự kiện đời sống riêng. LifeEvent là đơn vị kể lại được: một project tiến lên, một object bị bỏ quên, một nghi thức hoàn thành, một khoảng solitude có residue....
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `SurfaceSeedCandidate` (decorator=dataclass(slots=True)) — Seed rất nhỏ có thể gửi sang SurfaceArbiter. Đây không phải lời thoại hoàn chỉnh. Nó chỉ nói: "có một mảnh đời riêng public-safe đủ nhẹ để có thể dùng làm chất...
    - **Methods**: __post_init__(self), should_surface(self), to_dict(self)
  - `PrivateLifeState` (decorator=dataclass(slots=True)) — State bền của PrivateLifeCore.
    - **Methods**: __post_init__(self), to_dict(self), from_mapping(cls, data)
  - `PrivateLifeTickResult` (decorator=dataclass(slots=True)) — Output một tick PrivateLifeCore.
    - **Methods**: to_dict(self)
- **Hàm module-level**: now_ts(), clamp01(value, default), compact_text(value, limit), stable_id(prefix), to_plain(value), private_life_state_digest(state)

### `cortex/private_life/core.py`
- **LOC**: 880
- **Vai trò**: PrivateLifeCore: habitat, attachments, projects, anchors, daily rhythm, taste, solitude, rituals, errands, life events. Không sinh lời public, chỉ update đời sống riêng và seed an toàn.
- **Class/dataclass chính**:
  - `PrivateLifeCore` — Core đời sống riêng. Core này có hai luật: 1. Không sinh lời thoại public. 2. Mọi kết luận đều phải để lại LifeEvent/project update/object residue đủ audit.
    - **Methods**: __init__(self, state), _ensure_defaults(self), tick(self), _infer_idle_seconds(self), _observe_habitat(self), _place_from_app(self, active_app, active_window), _runtime_queue_notes(self, runtime_owner), _update_object_attachments(self), _advance_private_projects(self), _update_private_anchors(self), _update_taste(self), _build_life_events(self), _build_surface_seed(self), _update_daily_rhythm(self), _update_solitude(self), _update_rituals(self), _update_errands(self), _commit_events(self, events), digest(self), to_dict(self)
- **Hàm module-level**: _getattr_or_mapping(obj, name, default)

### `cortex/private_life/persistence.py`
- **LOC**: 78
- **Vai trò**: cortex/private_life/persistence.py ================================== Persistence JSON riêng cho PrivateLifeCore. Lý do tách khỏi memory_cognition: private life là state vận hành của agent, không phải fact user hay memor...
- **Class/dataclass chính**:
  - `PrivateLifeStore` — Kho state bền cho PrivateLifeCore.
    - **Methods**: __init__(self, path), from_env(cls), load(self), save(self, state)
- **Hàm module-level**: atomic_write_json(path, payload)

### `cortex/subconscious/thought_spark.py`
- **LOC**: 244
- **Vai trò**: ThoughtSpark contract cho tầng wandering/subconscious. ThoughtSpark là mẩu ý nghĩ cực sớm: còn mơ hồ, chưa claim fact, chưa có quyền surface. Nó là hạt bụi trong đầu, không phải câu nói. Nếu cho nó nhảy thẳng ra public s...
- **Class/dataclass chính**:
  - `ThoughtSpark` (decorator=dataclass(slots=True, frozen=True)) — Mẩu ý nghĩ trước-fragment. Khác ThoughtFragment: - chưa cần evidence chặt; - chưa có quyền claim; - không được surface trực tiếp; - chỉ được sống trong DriftPoo...
    - **Methods**: __post_init__(self), create(cls), from_mapping(cls, data), age_seconds(self, now), decay_factor(self, now), decayed_strength(self, now), is_expired(self, now), refreshed(self), to_dict(self)
- **Hàm module-level**: now_timestamp(), clamp01(value, default), clean_text(value), normalize_tags(values), normalize_source(value), make_spark_id(seed, source, created_at)

### `cortex/subconscious/drift_pool.py`
- **LOC**: 232
- **Vai trò**: Hồ giữ ThoughtSpark yếu. Spark decay/cộng hưởng/nhóm theme rồi thỉnh thoảng kết tinh thành association. Không có API surface public.
- **Class/dataclass chính**:
  - `DriftEntry` (decorator=dataclass(slots=True))
    - **Methods**: alive_strength(self, now), to_dict(self, now)
  - `DriftSnapshot` (decorator=dataclass(slots=True, frozen=True))
    - **Methods**: sparks(self), to_dict(self)
  - `DriftPool` — Giữ spark yếu, decay chậm, cộng hưởng theo theme.
    - **Methods**: __init__(self), submit(self, spark), submit_many(self, sparks), decay(self), snapshot(self), top_sparks(self), related_groups(self), resonate(self), _resonance_sentence(self, seeds), _trim(self), __len__(self)
- **Hàm module-level**: _tokens(text), _theme_keys(text, tags), _signature(spark)

### `cortex/subconscious/wandering_thought.py`
- **LOC**: 252
- **Vai trò**: WanderingThoughtEngine: spark -> drift -> association -> fragment. Engine này chạy nhẹ theo tick. Nó không gọi SurfaceArbiter, không gọi LLM, không phát public speech. Nó chỉ tạo ThoughtSpark, nuôi DriftPool, rồi đôi khi...
- **Class/dataclass chính**:
  - `WanderingThoughtEngine` — Tầng ý nghĩ vẩn vơ có continuity.
    - **Methods**: __init__(self), tick(self), _trigger_reason(self), _surface_allowed(self, association), _idle_seconds(self, snapshot), _focus_family(self), _deep_focus(self), _has_repeated_runtime_event(self), _after_debug(self), _mood_delta(self, sparks, fragments), _is_status_ping(self, text)
- **Hàm module-level**: _get(obj, path, default)

### `cortex/subconscious/free_association.py`
- **LOC**: 144
- **Vai trò**: FreeAssociationEngine cho wandering sparks. Nó nối spark bằng semantic/mood/module/metaphor/weak link. Không suy luận fact mới. Đây là liên tưởng, không phải lập luận có toga và búa thẩm phán.
- **Class/dataclass chính**:
  - `FreeAssociationEngine` — Nối 2-4 spark thành association path.
    - **Methods**: associate(self, sparks), _pair_score(self, a, b), _metaphor_score(self, group), _path_from_group(self, group), _statement(self, seeds, sparks)
- **Hàm module-level**: _tokens(text), _has_marker(spark, marker)

### `cortex/subconscious/blackboard.py`
- **LOC**: 271
- **Vai trò**: Blackboard Phase 0 cho subconscious workers. Blackboard là nơi các worker nền bỏ ThoughtFragment vào. Nó không chọn câu nói, không gọi LLM, không quyết định quan hệ. Nó chỉ làm ba việc buồn tẻ nhưng cứu mạng: 1. Validate...
- **Class/dataclass chính**:
  - `BlackboardSnapshot` (decorator=dataclass(slots=True, frozen=True)) — Ảnh chụp trạng thái Blackboard tại một thời điểm. Snapshot bất biến giúp Synthesizer đọc ổn định trong khi worker khác vẫn có thể submit fragment. Nếu đọc trực...
    - **Methods**: top(self, limit), to_dict(self)
  - `SubconsciousBlackboard` — Kho tạm cho ThoughtFragment. Thread-safe ở mức đơn giản bằng RLock, đủ cho runtime single-process hiện tại. Đây không phải message broker. Đừng biến nó thành Ka...
    - **Methods**: __init__(self), submit(self, fragment), submit_many(self, fragments), get(self, fragment_id), replace(self, fragment), remove_many(self, fragment_ids), remove(self, fragment_id), clear(self), decay(self), snapshot(self), top_fragments(self), __len__(self), _trim_locked(self), _dedupe_key(self, fragment), _content_seed(content)

### `cortex/subconscious/synthesizer.py`
- **LOC**: 362
- **Vai trò**: Conscious Synthesizer Phase 0. Synthesizer là cổ chai ý thức nhỏ: nhận nhiều ThoughtFragment từ Blackboard, gom cụm, chọn theme thắng, rồi xuất một ThoughtObject duy nhất. Nó không sinh văn public. Nó cũng không gọi LLM....
- **Class/dataclass chính**:
  - `SynthesisPolicy` (decorator=dataclass(slots=True, frozen=True)) — Knob chính sách cho Synthesizer. - max_fragments: số fragment tối đa đưa vào một object. - min_confidence_for_surface: confidence tối thiểu để được surface_cand...
  - `SynthesisReport` (decorator=dataclass(slots=True, frozen=True)) — Debug report cho một lượt synthesize.
    - **Methods**: to_dict(self)
  - `ConsciousSynthesizer` — Nén Blackboard thành một ThoughtObject. Đây là deterministic synthesizer. Phase sau có thể thêm LLM/private rehearsal, nhưng Phase 0 phải có xương sống không ph...
    - **Methods**: __init__(self, policy), synthesize_from_blackboard(self, blackboard), synthesize(self, snapshot), _build_object(self, fragments), _group_fragments(self, fragments), _group_score(self, fragments), _surface_pressure(self, fragments), _suppressed_pressure(self, fragments), _choose_route(self, fragments), _route_reason(self, fragments, object_), _dominant_theme(self, fragments), _summary(self, fragments), _kind_family(kind), _weighted_average(fragments), _max_privacy(fragments)

### `cortex/subconscious/model_synthesizer.py`
- **LOC**: 413
- **Vai trò**: Model-backed Lane 3 synthesizer. Đây là lớp làm phần "phiên toà nội tâm": các ThoughtFragment vẫn do worker rẻ đưa lên Blackboard, nhưng Lane 3 có thể gọi API để nén chúng thành một ThoughtObject có evidence rõ hơn, có b...
- **Class/dataclass chính**:
  - `ModelSynthesisPolicy` (decorator=dataclass(slots=True, frozen=True)) — Knobs riêng cho Lane 3 API synthesis.
  - `InnerCourtReport` (decorator=dataclass(slots=True, frozen=True)) — Debug report cho phiên tòa Lane 3.
    - **Methods**: to_dict(self)
  - `ModelBackedConsciousSynthesizer` (base=ConsciousSynthesizer) — ConsciousSynthesizer có thêm Lane 3 API refinement.
    - **Methods**: __init__(self), synthesize_from_blackboard(self, blackboard), synthesize(self, snapshot), _extract_live_fragments(self, snapshot), _should_call_model(self, fragments), _call_model(self, base_object, fragments), _build_messages(self, base_object, fragments), _object_from_model_payload(self, base_object, fragments, payload), _safe_route(self, raw_route), _merged_privacy(self, base, model), _report_from_payload(self, payload, object_), _log_inner_court(self, report, payload), _log(self, level, msg)
- **Hàm module-level**: _env_flag(name, default), _as_float(value, default)

### `cortex/subconscious/worker_base.py`
- **LOC**: 71
- **Vai trò**: Base contract cho các subconscious worker Phase sau. Phase 0 chưa triển khai 15 worker. File này chỉ cung cấp lớp nền để Phase 1+ không mỗi worker tự chế một kiểu output. Một contract nhỏ hôm nay cứu được nhiều file `if...
- **Class/dataclass chính**:
  - `WorkerContext` (decorator=dataclass(slots=True, frozen=True)) — Context tối thiểu worker được phép nhìn. Phase sau có thể mở rộng, nhưng nên giữ nguyên nguyên tắc: worker đọc context đã chọn lọc, không tự bốc toàn bộ runtime...
  - `SubconsciousWorker` (base=Protocol) — Interface tối thiểu cho worker nền.
    - **Methods**: run(self, context)
  - `RuleBasedWorker` — Base class tiện dụng cho worker deterministic. Worker con chỉ cần override `build_fragments`. Base này đảm bảo output luôn là tuple, giúp loop xử lý đồng nhất.
    - **Methods**: run(self, context), build_fragments(self, context)

### `cortex/subconscious/topic_seed_pool.py`
- **LOC**: 201
- **Vai trò**: TopicSeedPool gom seed từ self-anchor/habitat/memory/mood/random weak link.
- **Class/dataclass chính**:
  - `TopicSeedPool` — Sinh seed không phụ thuộc hoàn toàn vào user action. Rule thực dụng: sau khi gom seed, nếu seed user-anchored vượt 50%, cắt bớt. Vì mục tiêu là đời sống riêng,...
    - **Methods**: __init__(self), generate(self), to_sparks(self, seeds), non_user_ratio(self, seeds), _mood_rhythm_seeds(self), _memory_residue_seeds(self), _random_weak_links(self, seeds), _dedupe(self, seeds), _cap_user_anchored(self, seeds)
- **Hàm module-level**: _get(obj, path, default), _collect_memory_texts(memory_packet)

### `cortex/daydream_consolidation.py`
- **LOC**: 377
- **Vai trò**: src/cortex/daydream_consolidation.py ==================================== Tầng 2b - Daydream Consolidation. Đây là nơi Qwen 4B GGUF được phép nghiền ngẫm memory packet đã lọc sẵn. Nó không chạy theo timer mù. Runtime/Wak...
- **Class/dataclass chính**:
  - `DaydreamPacket` (decorator=dataclass(slots=True)) — Một mảnh memory đã lọc để 4B đọc.
    - **Methods**: __post_init__(self), to_prompt_dict(self)
  - `DaydreamInsight` (decorator=dataclass(slots=True))
    - **Methods**: __post_init__(self), to_dict(self)
  - `DaydreamResult` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self)
  - `DaydreamConsolidationConfig` (decorator=dataclass(slots=True))
  - `DaydreamConsolidator` — Sở hữu path gọi Qwen 4B để chưng cất memory.
    - **Methods**: __init__(self), should_trigger(self), consolidate(self, packets), _select_packets(self, packets), _build_prompt(self, packets), _call_json(self, prompt), _extract_content(self, response), _parse_json_text(self, text), _validate_result(self, data, packets), _push_agenda(self, result, agenda_stack), _log(self, level, msg)
- **Hàm module-level**: _clamp01(value, default), _compact(text, limit)

### `cortex/internal_agenda.py`
- **LOC**: 386
- **Vai trò**: src/cortex/internal_agenda.py ================================ Stack agenda nội bộ cho ERIS. Module này là nơi giữ các vấn đề ERIS đang tự treo trong đầu: - câu hỏi chưa đóng, - lỗi cần repair, - ký ức cần chưng cất, - i...
- **Class/dataclass chính**:
  - `InternalAgendaItem` (decorator=dataclass(slots=True)) — Một mục agenda nội bộ. pressure: Độ ép phải xử lý. WakeGovernor đọc trường này. urgency: Độ gấp. Khác pressure: một thứ có thể dai dẳng nhưng không gấp. confide...
    - **Methods**: __post_init__(self), is_open(self), score(self), expired(self, now), touch(self), decay(self, factor), to_dict(self), from_mapping(cls, data)
  - `InternalAgendaStack` — CRUD stack cho agenda nội bộ. Stack này nhỏ, có decay, có TTL, và không biến thành database thứ hai.
    - **Methods**: __init__(self), __len__(self), items(self), open_items(self), add(self), mark(self, item_id, status), resolve(self, item_id), block(self, item_id, reason), top_items(self), pressure(self), decay(self, factor), prune(self, now), to_dict(self), save(self, path), from_mapping(cls, data), _trim(self), _load_from_disk(self), _persist(self)
- **Hàm module-level**: _clamp01(value, default), _compact(text, limit), _fingerprint(kind, summary, evidence_ids)

### `cortex/agent_mind_persistence.py`
- **LOC**: 732
- **Vai trò**: Persistent Agent Mind Layer cho ERIS. Module này giữ 3 lớp học dài hạn cho impulse system: 1. BeliefCore persistent - ERIS tin gì về user / bản thân / scene / task. - Mỗi belief có confidence, nguồn, decay, evidence coun...
- **Class/dataclass chính**:
  - `PersistentBeliefRecord` (decorator=dataclass(slots=True)) — Một belief mềm, không phải hard truth. confidence càng cao thì impulse scoring càng tin. decay_rate giúp belief mòn dần nếu lâu không được reinforce. contradict...
    - **Methods**: decayed_confidence(self), reinforce(self, amount), to_dict(self), from_dict(cls, data)
  - `PersistentPreferenceRecord` (decorator=dataclass(slots=True)) — Preference dài hạn của ERIS. strength là trọng số hiện tại. stability càng cao thì feedback càng khó bẻ. Đây là chống hiện tượng một feedback làm ERIS đổi tính...
    - **Methods**: adjust(self, delta), to_dict(self), from_dict(cls, data)
  - `SemanticHabitRecord` (decorator=dataclass(slots=True)) — Habit học từ user feedback, lưu ở dạng semantic. Không lưu kiểu "user chửi câu A". Lưu thành pattern: context_tags + action_pattern + impulse_name -> adjustment...
    - **Methods**: matches(self), score_delta(self), reinforce(self), to_dict(self), from_dict(cls, data)
  - `PersistentAgentMindStore` — JSON store nhỏ cho Persistent Agent Mind Layer. Store này cố tình không dùng LLM. Nó chỉ đọc/ghi record có schema rõ. Nếu sau này muốn daydream/4B consolidate b...
    - **Methods**: __init__(self, path), load(self), reload_if_changed(self), save(self), to_dict(self), replace_from_dict(self, payload), relevant_beliefs(self), preference_strength(self, key, default), habit_bias(self), record_user_feedback(self, text), _seed_defaults(self), _detox_presence_habits(self), _adjust_preference(self, key, delta), _upsert_belief(self, key, claim, domain, amount), _upsert_habit(self, key, tags, action, impulse_name, adjustment, outcome, source_id)
- **Hàm module-level**: _clamp01(value, default), _now(), _norm(value), _clean(value), _as_tuple(value), _feedback_sentiment(normalized), _feedback_topics(normalized), _topic_to_context_tags(topics), default_agent_mind_path(), agent_mind_path_for_memory_core(base_dir), get_default_agent_mind_store()

### `cortex/agent_state_stack.py`
- **LOC**: 742
- **Vai trò**: Agent state stack for ERIS. Lớp này gom các lực nền đang bị rải rác trong runtime thành một contract nhỏ: Evidence -> Belief -> Preference -> Need -> Trait -> Habit -> Affordance. Nó cố tình không gọi LLM và không tự quy...
- **Class/dataclass chính**:
  - `EvidenceView` (decorator=dataclass(slots=True)) — Bản nhìn nhẹ của tình huống hiện tại. Đây không phải evidence ledger đầy đủ. Nó là lớp đọc nhanh cho arbitration: app nào đang nổi, title có gì, focus loại nào,...
    - **Methods**: scene_text(self), has_scene_anchor(self), has_tag(self, tag), from_runtime(cls)
  - `Belief` (decorator=dataclass(slots=True))
    - **Methods**: to_note(self)
  - `BeliefSnapshot` (decorator=dataclass(slots=True))
    - **Methods**: confidence(self, key, default), notes(self, limit), from_evidence(cls, evidence)
  - `PreferenceProfile` (decorator=dataclass(slots=True)) — Sở thích riêng của ERIS, không phải preference của user.
    - **Methods**: from_agent_mind(cls, agent_mind), fit_for(self, impulse_name)
  - `NeedVector` (decorator=dataclass(slots=True))
    - **Methods**: from_runtime(cls), notes(self)
  - `TraitVector` (decorator=dataclass(slots=True))
    - **Methods**: from_runtime(cls), bias_for(self, impulse_name)
  - `HabitSnapshot` (decorator=dataclass(slots=True))
    - **Methods**: repetition_penalty(self), semantic_bias(self)
  - `AffordanceMap` (decorator=dataclass(slots=True))
    - **Methods**: from_stack_parts(cls)
  - `AgentStateStack` (decorator=dataclass(slots=True))
    - **Methods**: debug_notes(self)
- **Hàm module-level**: _clamp01(value, default), _text(value), _norm(value), _contains_any(text, terms), _get(obj), build_agent_state_stack()

### `cortex/development_system.py`
- **LOC**: 396
- **Vai trò**: development_system.py — Sổ_Phát_Triển + điều phối apply/undo/reset. Tách khỏi ``development_profile`` (data + store + gate) để phần điều phối và audit rõ ràng. Luồng áp dụng theo nguyên tắc **ghi-Sổ-trước-commit-sau** để...
- **Class/dataclass chính**:
  - `ApplyResult` (decorator=dataclass(slots=True))
  - `DevelopmentBias` (decorator=dataclass(slots=True)) — Ảnh đọc read-only của các delta long-arc, để hợp vào mặt phẳng biểu đạt. Đây CHỈ là bias giọng/khoảng cách/độ-dám-đọc. Không trường nào chạm guard sự thật; xem...
  - `DevelopmentLog` — Nhật ký có phiên bản, ghi mọi thay đổi/đề xuất cho audit + hoàn tác.
    - **Methods**: __init__(self, path), _load(self), to_dict(self), _save(self), record(self, entry), count_applied_in_window(self), last_applied(self)
  - `DevelopmentSystem` — Điều phối đề xuất → Cổng_Bản_Sắc → ghi Sổ → áp dụng. Sở hữu undo/reset.
    - **Methods**: __init__(self), apply(self, proposal), undo_last(self), reset(self), tick(self), development_bias(self), describe_for_user(self), steer(self, user_direction)
- **Hàm module-level**: _now(), _evidence_of(proposal), _norm(text), _degree(delta), _describe_axis(axis, delta), _parse_steer(text), development_growth_enabled(), get_default_development_system()

### `cortex/growth_consolidator.py`
- **LOC**: 153
- **Vai trò**: growth_consolidator.py — Tác_Tử_Nền sinh Đề_Xuất_Nhích cho long-arc. Đặt trên kỷ luật của ``DaydreamConsolidator``: chỉ chạy khi đủ áp lực củng cố / thời gian rảnh và ngân sách cho phép; chỉ chấp nhận bằng chứng có ``evi...
- **Class/dataclass chính**:
  - `GrowthObservation` (decorator=dataclass(slots=True)) — Một quan sát đã-lọc, gắn vào một phiên cụ thể.
  - `GrowthConsolidatorConfig` (decorator=dataclass(slots=True))
  - `GrowthConsolidator`
    - **Methods**: __init__(self, config), should_run(self), consolidate(self, observations), _anchors(obs_list)
- **Hàm module-level**: _f(value)

# 7. Memory chi tiết

### `memory/memory_cognition.py`
- **LOC**: 618
- **Vai trò**: Facade memory legacy v2: commit qua StateCommitRequest, recall qua MemoryRetrievalEngine, route target vào event/active/episodic/semantic/relational/affective/procedural/repair/unresolved. Debug khi ghi nhớ sai layer hoặc recall thiếu source.
- **Class/dataclass chính**:
  - `MemoryQuery` (decorator=dataclass(slots=True))
  - `MemoryCommitDecision` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self)
  - `CommitPolicy` (decorator=dataclass(slots=True)) — Rule chặn ghi nhớ bừa. Đây là commit permission, không phải retrieval permission. Ghi nhớ vẫn cần giấy tờ. Truy hồi thì dùng consequence scoring.
  - `MemoryCognitionCore` — Facade chính của memory. Runtime chỉ nên giữ một instance class này. - commit(): ghi nhớ qua StateCommitRequest. - recall()/retrieve(): dựng MemoryCue rồi gọi M...
    - **Methods**: __init__(self, base_dir), commit(self, request), commit_many(self, requests), lookup_fact(self, fact_key), get_fact(self, fact_key), semantic_lookup(self, fact_key), recall(self, query), retrieve(self, query), load(self), save(self, snapshot), render_context(self, query), build_commit_request(self), _normalize_request(self, request), lookup_fact(self, fact_key), search_memory_candidates(self, query), candidate_trace_for_query(self, query), load_active_state(self), _check_commit_permission(self, request), _commit_event_ledger(self, request), _query_from_frame(self, frame), _query_from_snapshot(self, snapshot), _budget_from_frame(self, frame), _quotas(self), _packet_with_retrieval_resonance(self, packet)
- **Hàm module-level**: _request_get(request, name, default), _request_metadata(request), _as_text_list(values), _content_for_target(target, content)
- **Phụ thuộc nội bộ nổi bật**: cortex.agent_mind_persistence

### `memory/memory_kernel.py`
- **LOC**: 496
- **Vai trò**: Facade memory mới cho runtime: ingest, answer, build_packet, maintain, commit_many, recall/retrieve, debug_snapshot. Debug khi memory query deterministic không chạy.
- **Class/dataclass chính**:
  - `MemoryKernelDebugSnapshot` (decorator=dataclass(slots=True)) — Snapshot nhỏ cho dev mode. Không đưa thẳng ra public chat. Đây là để log/debug UI.
    - **Methods**: to_dict(self)
  - `MemoryKernel` — Facade chính cho toàn bộ memory runtime. Cách dùng khuyến nghị: kernel = MemoryKernel(base_dir="memory_core", semantic_parser=parser) kernel.ingest(user_text, m...
    - **Methods**: __init__(self, base_dir), from_existing_core(cls, core), ingest(self, text), answer(self, query), build_packet(self, query), maintain(self), commit(self, request), commit_many(self, requests), recall(self, query), retrieve(self, query), load(self), save(self, snapshot), render_context(self), lookup_fact(self, fact_key), debug_snapshot(self), _annotate_request(self, request), _compile_debug(self, compile_result)

### `memory/memory_kernel_contracts.py`
- **LOC**: 223
- **Vai trò**: Contract/dataclass dùng chung trong memory.
- **Class/dataclass chính**:
  - `MemoryKernelConfig` (decorator=dataclass(slots=True)) — Config runtime cho MemoryKernel. Các ngưỡng ở đây là ngưỡng orchestration, không thay thế worthiness/retention. Worthiness/retention vẫn là luật chuyên trách củ...
  - `MemoryIngestResult` (decorator=dataclass(slots=True)) — Kết quả ingest một mảnh text/evidence. `decisions` là output từ MemoryIngestPolicy/MemoryCommitPolicy. `commit_results` là output từ MemoryCognitionCore.commit(...
    - **Methods**: committed_count(self), to_dict(self)
  - `MemoryAnswerResult` (decorator=dataclass(slots=True)) — Kết quả answer deterministic từ MemoryKernel. `answer` thường là RecallAnswer từ memory_query_ir. Kernel không convert thẳng sang Decision public; runtime/chat...
    - **Methods**: text(self), confidence(self), to_dict(self)
  - `MemoryMaintenanceReport` (decorator=dataclass(slots=True)) — Báo cáo maintain memory. Maintain là việc nền: consolidate candidate, prune expired, check contradiction. Báo cáo này cố tình định lượng đơn giản để log dễ đọc.
    - **Methods**: to_dict(self)

### `memory/memory_commit_policy.py`
- **LOC**: 1028
- **Vai trò**: Policy intake user turn. Trích fact/preference/convention, chặn commit câu hỏi như fact. Debug khi “tôi tên X” không nhớ hoặc “tôi tên gì” bị ghi thành fact.
- **Class/dataclass chính**:
  - `MemoryCommitPolicy` (decorator=dataclass(slots=True)) — Memory intake 3 tầng cho user turn. Tầng 1: phát hiện importance. Tầng 2: cố extract semantic/episodic/procedural fact rõ. Tầng 3: nếu explicit important nhưng...
    - **Methods**: __post_init__(self), set_semantic_parser(self, parser), decide_from_user_turn(self, user_text), _decide_with_semantic_claims(self, raw, turn_id), _decision_from_ai_classification(self, extracted, claim), _decision_from_semantic_claim(self, claim, retention), _surface_claim_for_semantic_claim(self, claim), _memory_kind_for_semantic_claim(self, claim), _decay_for_retention(self, decay_policy), _extract_user_name(self, raw, norm, turn_id), _extract_birth_year(self, raw, norm, turn_id), _extract_birth_month(self, raw, norm, turn_id), _extract_age_observed(self, raw, norm, turn_id), _extract_current_residence(self, raw, norm, turn_id), _extract_temporal_residence(self, raw, norm, turn_id), _extract_user_convention(self, raw, norm, turn_id), _extract_response_style(self, raw, norm, turn_id), _extract_memory_test_hint(self, raw, norm, turn_id), _extract_general_preference(self, raw, norm, turn_id), _build_unresolved_candidate(self, raw, norm, turn_id, importance, importance_reasons), _dedupe(self, decisions)
- **Hàm module-level**: _strip_accents(text), normalize_vi(text), _clean_value(value), _evidence(turn_id), _has_self_marker(norm), _looks_like_question(norm, raw), _extract_with_patterns(raw, patterns), _year_from_2k(token), _bounded_month(value), _explicit_importance(norm), _looks_like_convention(norm), _guess_domain(norm), _candidate_fact_keys(norm, domain), _slug_key(value)

### `memory/memory_models.py`
- **LOC**: 216
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `MemoryTarget` (base=str, Enum) — Loại kho nhớ mà một fact/candidate nên đi vào.
  - `SurfaceMode` (base=str, Enum) — Cách ký ức được phép hiện ra ngoài khi recall.
  - `DecayPolicy` (base=str, Enum) — Độ bền của ký ức.
  - `MemoryCommitKind` (base=str, Enum) — Loại commit request ở tầng intake.
  - `MemoryKind` (base=str, Enum) — Nhãn nghĩa cấp cao, tránh để các tầng sau phải đoán từ text thô.
  - `MemoryCommitDecision` (decorator=dataclass(frozen=True)) — Quyết định commit một mảnh thông tin. Đây không phải bản ghi memory cuối cùng. Nó là request có policy rõ: lưu vào đâu, mặt ngoài hiện thế nào, decay thế nào, v...
    - **Methods**: to_state_commit_request(self)
  - `RecallRequest` (decorator=dataclass(frozen=True)) — Yêu cầu recall đã được phân loại trước khi đụng tới memory thật.
  - `RecallAnswer` (decorator=dataclass(frozen=True)) — Câu trả lời recall đã qua policy, có confidence và trace để debug.
- **Hàm module-level**: _state_decay_from_memory_decay(decay), _commit_kind_for_target(target), _commit_content_from_decision(decision, metadata)

### `memory/schemas.py`
- **LOC**: 490
- **Vai trò**: Module `schemas` trong package `memory`.
- **Class/dataclass chính**:
  - `MemoryTarget` (base=str, Enum) — Các đích commit mà MemoryCognitionCore có thể route tới.
  - `DecayPolicy` (base=str, Enum) — Chính sách mục rữa của memory.
  - `PrivacyLevel` (base=str, Enum) — Mức riêng tư của evidence/memory.
  - `MemoryStatus` (base=str, Enum) — Trạng thái sống của một record memory.
  - `CommitOutcome` (base=str, Enum) — Kết quả xử lý một StateCommitRequest.
  - `CommitDecision` (decorator=dataclass) — Audit result sau khi StateCommitter/MemoryCognitionCore xử lý một request.
    - **Methods**: __post_init__(self)
  - `MemoryRecordBase` (decorator=dataclass) — Base record cho các memory đã qua commit protocol.
    - **Methods**: __post_init__(self), mark_tentative(self, reason), touch(self)
  - `EventLedgerEntry` (decorator=dataclass) — Sự kiện thô hoặc gần-thô. Ledger là append-only, không rewrite quá khứ.
    - **Methods**: __post_init__(self)
  - `ActiveStateSnapshot` (decorator=dataclass) — Snapshot overwrite cho trạng thái đang là của runtime.
    - **Methods**: __post_init__(self)
  - `EpisodicMemoryRecord` (decorator=dataclass; base=MemoryRecordBase) — Memory về một chuyện cụ thể đã xảy ra.
    - **Methods**: __post_init__(self)
  - `SemanticMemoryRecord` (decorator=dataclass; base=MemoryRecordBase) — Fact ổn định hoặc gần ổn định. Nếu chưa chắc, status phải là tentative.
    - **Methods**: __post_init__(self)
  - `RelationalMemoryRecord` (decorator=dataclass; base=MemoryRecordBase) — Pattern quan hệ/tương tác tích tụ qua nhiều turn.
    - **Methods**: __post_init__(self)
  - `AffectiveResidueRecord` (decorator=dataclass; base=MemoryRecordBase) — Dư âm cảm xúc như pressure nội bộ, không phải lời tuyên bố cảm xúc công khai.
    - **Methods**: __post_init__(self)
  - `ProceduralMemoryRecord` (decorator=dataclass; base=MemoryRecordBase) — Luật xử lý đã học: gặp trigger X thì nên xử lý bằng cách Y.
    - **Methods**: __post_init__(self)
  - `RepairMemoryRecord` (decorator=dataclass; base=MemoryRecordBase) — Memory sửa lỗi: user correction, wrong assumption, suppression rule lần sau.
  - `MemoryPacket` (decorator=dataclass) — Gói recall đã được cắt budget để downstream dùng, thay vì nhét cả database vào prompt.
    - **Methods**: __post_init__(self)
  - `MemoryStateBundle` (decorator=dataclass) — Một bundle JSON đầy đủ cho persistence. Các store riêng có thể dùng toàn bộ bundle hoặc chỉ đọc collection mình cần.
    - **Methods**: __post_init__(self), with_updated_timestamp(self)
- **Hàm module-level**: now_iso(), make_memory_id(prefix), clamp01(value), _tuple_str(value), _dict_value(value), coerce_dataclass(cls, value), _coerce_record_tuple(value, cls), to_plain_data(value), bundle_from_mapping(data), bundle_to_mapping(bundle)

### `memory/persistence.py`
- **LOC**: 340
- **Vai trò**: Module `persistence` trong package `memory`.
- **Class/dataclass chính**:
  - `MemoryPersistenceConfig` (decorator=dataclass(frozen=True)) — Cấu hình đọc/ghi memory JSON.
    - **Methods**: resolved_path(self)
  - `MemoryPersistenceError` (base=RuntimeError) — Lỗi persistence có ngữ cảnh rõ ràng hơn JSONDecodeError trần trụi.
  - `JsonMemoryPersistence` — Lớp persistence chính cho MemoryStateBundle. Ghi file bằng atomic replace: 1. ghi vào temporary file cùng thư mục, 2. fsync, 3. os.replace sang file thật. Cách...
    - **Methods**: __init__(self, config), load_bundle(self), save_bundle(self, bundle), update_bundle(self, mutator), append_to_collection(self, collection_name, record), replace_collection(self, collection_name, records), set_active_state(self, snapshot), append_commit_audit(self, decision), compact(self), load_raw(self), save_raw(self, data), exists(self), backup_now(self, suffix), _atomic_write_text(self, text), _rotate_backups(self), _migrate_raw(self, raw)
- **Hàm module-level**: time_safe_suffix(), load_memory_bundle(path), save_memory_bundle(path, bundle), update_memory_bundle(path, mutator)

### `memory/event_ledger.py`
- **LOC**: 220
- **Vai trò**: Append-only Event Ledger cho ERIS. Tầng này giữ raw truth: tín hiệu thô, evidence đã tạo ra, frame liên quan, và metadata audit. Nó không kết luận tâm lý, không merge ký ức, không sửa quá khứ. Nếu một module muốn lưu sự...
- **Class/dataclass chính**:
  - `EventLedgerRecord` (decorator=dataclass(slots=True)) — Một dòng sự kiện append-only. Ledger là nơi lưu cái đã xảy ra, không phải nơi phán xét nó có nghĩa gì. `content` có thể là dict, list hoặc string, nhưng nên đủ...
    - **Methods**: to_dict(self), from_dict(cls, data)
  - `EventLedger` — Kho append-only cho raw event. Không có method update/delete public. Nếu muốn sửa, ghi event repair mới. Quá khứ mà sửa trực tiếp thì audit layer trở thành truy...
    - **Methods**: __init__(self, path), load(self), save(self, records), append(self, record), append_raw_event(self), append_from_signal(self, signal), recent(self), by_frame(self, frame_id), query(self, text)
- **Hàm module-level**: now_ts(), iso_now(), compact_text(value), atomic_write_json(path, payload)

### `memory/active_state_snapshot.py`
- **LOC**: 172
- **Vai trò**: Active State Snapshot cho ERIS. Snapshot giữ trạng thái hiện tại có thể overwrite: goal đang theo, session arc, affect/homeostasis hiện thời, relation state, project active, thread đang mở. Nó không phải event ledger và...
- **Class/dataclass chính**:
  - `ActiveStateSnapshot` (decorator=dataclass(slots=True)) — State overwrite được, dùng cho runtime hiện tại. Memory dài hạn nói "đã từng". Snapshot nói "đang là".
    - **Methods**: to_dict(self), from_dict(cls, data)
  - `ActiveStateStore` — Kho snapshot overwrite. Chỉ MemoryCognitionCore nên gọi apply_commit(). Module khác phải gửi StateCommitRequest.
    - **Methods**: __init__(self, path), load(self), save(self, snapshot), apply_commit(self, request)
- **Hàm module-level**: iso_now(), atomic_write_json(path, payload), compact_text(value)

### `memory/episodic_memory.py`
- **LOC**: 628
- **Vai trò**: Episodic Memory: chuyện cụ thể đã xảy ra. Episodic không phải semantic fact. Nó giữ cảnh, lượt, outcome, evidence và độ nổi bật. Một câu user sửa sai hôm nay là episode. Một fact ổn định chỉ lên semantic sau khi commit p...
- **Class/dataclass chính**:
  - `RecallScore` (decorator=dataclass(frozen=True, slots=True)) — Debug score cho một item recall. Giữ lớp này để sau này log "vì sao ký ức này được kéo lên" thay vì nhìn một con số tổng rồi cầu nguyện. Cầu nguyện với retrieva...
    - **Methods**: to_dict(self)
  - `EpisodicMemoryItem` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self), from_dict(cls, data), recall_line(self), search_fields(self)
  - `EpisodicMemoryStore`
    - **Methods**: __init__(self, path), load(self), save(self, items), apply_commit(self, request), recall(self, query), recall_with_scores(self, query), _score_item(self, item), _mark_accessed(self, selected), _trim(self, items)
- **Hàm module-level**: iso_now(), compact_text(value), clamp01(value), atomic_write_json(path, payload), normalize_text(text), normalized_tokens(text), token_bigrams(tokens), weighted_counter(tokens), weighted_jaccard(left, right), phrase_match_score(query_norm, hay_norm), parse_timestamp(timestamp), recency_boost(timestamp)

### `memory/semantic_memory.py`
- **LOC**: 1846
- **Vai trò**: Semantic Memory: bộ nhớ fact đã được chưng cất cho ERIS. File này cố tình KHÔNG làm event log. Semantic memory chỉ nên giữ những thứ đã đủ ổn định để ERIS có thể nhớ gọn: - fact về user, ERIS, project, thế giới, kỹ thuật...
- **Class/dataclass chính**:
  - `SemanticRecallCue` (decorator=dataclass(slots=True)) — Cue truy xuất semantic memory. Thay vì lấy query rồi đếm token overlap, ta tách query thành vài tín hiệu: - domain muốn tìm: user/self/project/technical... - fa...
    - **Methods**: tokens(self), embedding_query(self)
  - `SemanticRecallHit` (decorator=dataclass(slots=True)) — Kết quả recall có score và lý do. recall() vẫn trả list item để tương thích cũ. Nếu cần debug, gọi recall_hits() để thấy vì sao item được kéo lên.
    - **Methods**: to_dict(self), recall_line(self)
  - `FactProfile` (decorator=dataclass(slots=True)) — Thông tin derive từ claim/request trước khi lưu. fact_key là điểm quan trọng nhất. Nó biến các câu paraphrase thành cùng một fact. Ví dụ: "Người dùng tên Gtvkun...
  - `SemanticMemoryItem` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self), from_dict(cls, data), fact_key(self), aliases(self), importance(self), access_count(self), last_accessed_at(self), raw_user_text(self), semantic_value(self), recall_text_parts(self), recall_line(self)
  - `SemanticMemoryStore` — Store semantic fact dạng JSON, có typed recall và optional embedding hook. Đây là WARM/HOT fact store: - load nhanh - claim ngắn - metadata có fact_key/importan...
    - **Methods**: __init__(self, path), load(self), save(self, items), _prune_items(self, items), _sorted_items(self, items), _retention_score(self, item), apply_commit(self, request), _find_merge_target(self, items), _merge_item(self, item), _is_current_fact_replacement(self, fact_key), _claim_surface_quality(self, claim), _detect_value_conflict(self, item), _extract_metadata_value(self, metadata, fact_key), _extract_simple_value(self, claim, fact_key), lookup_fact(self, fact_key), get_fact(self, fact_key), semantic_lookup(self, fact_key), _current_fact_rank(self, item), recall(self, query), recall_hits(self, query), _embedding_candidates(self, cue, items), _score_recall_item(self, item, cue), _normalize_vector_score(self, value), _fact_key_score(self, item, cue), _domain_score(self, item, cue), _alias_score(self, item, cue), _lexical_similarity(self, item, cue), _recency_bonus(self, item), _record_access(self, item_ids), parse_recall_cue(self, query), _derive_fact_profile(self, claim), _domain_from_fact_key(self, fact_key), _infer_domain(self, claim, target), _build_metadata(self), embedding_text_for_item(self, item), _embedding_text_from_parts(self), _claim_similarity(self, a, b), rebuild_embedding_index(self)
- **Hàm module-level**: iso_now(), _safe_epoch_from_iso(value), compact_text(value), clamp01(value, default), atomic_write_json(path, payload), strip_accents(text), normalize_text(text), dedupe_key(text), token_set(text), char_ngrams(text, n), word_ngrams(text, n), jaccard(a, b), sequence_ratio(a, b), stable_hash(text), unique_keep_order(items), _mapping(value), _matches_any(normalized, patterns)

### `memory/relational_memory.py`
- **LOC**: 202
- **Vai trò**: Relational Memory: nhịp quan hệ, rupture, repair, khoảng cách. Đây không phải nơi lưu "user is sad". Nó lưu pattern có bằng chứng: user sửa ERIS khi overread, user thích câu trả lời kỹ thuật trực tiếp, rupture cần repair...
- **Class/dataclass chính**:
  - `RelationalMemoryItem` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self), from_dict(cls, data), recall_line(self)
  - `RelationalMemoryStore`
    - **Methods**: __init__(self, path), load(self), save(self, items), apply_commit(self, request), recall(self, query), _infer_pattern(self, claim, reason), _trust_delta(self, pattern), _distance_delta(self, pattern)
- **Hàm module-level**: iso_now(), compact_text(value), clamp01(value), atomic_write_json(path, payload)

### `memory/affective_residue_memory.py`
- **LOC**: 213
- **Vai trò**: Affective Residue Memory: dư âm cảm xúc dưới dạng pressure. Không lưu "ERIS buồn" như fact công khai. Lưu pressure: tension, attachment residue, exposure recoil, unfinished loop. Dư âm ảnh hưởng nhịp nói/im lặng, không t...
- **Class/dataclass chính**:
  - `AffectiveResidueItem` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self), from_dict(cls, data), recall_line(self)
  - `AffectiveResidueMemoryStore`
    - **Methods**: __init__(self, path), load(self), save(self, items), apply_commit(self, request), recall(self, query), _infer_type(self, description, reason), _infer_valence(self, description, reason), _pressure_effects(self, residue_type, intensity)
- **Hàm module-level**: iso_now(), compact_text(value), clamp01(value), clamp11(value), atomic_write_json(path, payload)

### `memory/procedural_memory.py`
- **LOC**: 201
- **Vai trò**: Procedural Memory: cách xử lý đã học. Đây là nơi lưu rule kiểu: khi user sửa hiểu lầm, trả lời trực tiếp trước; khi evidence yếu, không claim nhìn thấy màn hình. Procedural là policy học được, không phải fact về user.
- **Class/dataclass chính**:
  - `ProceduralMemoryItem` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self), from_dict(cls, data), recall_line(self)
  - `ProceduralMemoryStore`
    - **Methods**: __init__(self, path), load(self), save(self, items), apply_commit(self, request), recall(self, query), _infer_trigger(self, rule, reason), _default_items(self), _merge_defaults(self, items)
- **Hàm module-level**: iso_now(), compact_text(value), clamp01(value), key_for(trigger, rule), atomic_write_json(path, payload)

### `memory/repair_memory.py`
- **LOC**: 248
- **Vai trò**: Repair Memory: ghi lỗi, sửa sai, suppression rule tương lai. Nếu user nói "không phải", hệ thống không được chỉ xin lỗi rồi quên. Nó phải lưu loại lỗi, assumption sai, evidence, chiến lược sửa. Đây là nơi ERIS học bớt ng...
- **Class/dataclass chính**:
  - `RepairMemoryItem` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self), from_dict(cls, data), recall_line(self)
  - `RepairMemoryStore`
    - **Methods**: __init__(self, path), load(self), save(self, items), apply_commit(self, request), recall(self, query), _extract_field(self, text, field_name), _infer_failure_type(self, content, reason), _guess_wrong_assumption(self, content, reason), _default_strategy(self, failure_type), _default_suppression_rule(self, failure_type)
- **Hàm module-level**: iso_now(), compact_text(value), clamp01(value), atomic_write_json(path, payload)

### `memory/unresolved_memory.py`
- **LOC**: 331
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `UnresolvedMemoryCandidate` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self), from_dict(cls, data), fingerprint(self), recall_line(self)
  - `UnresolvedMemoryStore` — JSON store cho unresolved memory candidates.
    - **Methods**: __init__(self, path), load(self), save(self, items), apply_commit(self, request), candidates_for_consolidation(self), mark_attempted(self, candidate_id), mark_promoted(self, candidate_id), search(self, query), _find_existing(self, items, candidate), _merge(self, old, new), _prune(self, items), _sort_items(self, items)
- **Hàm module-level**: iso_now(), compact_text(value), clamp01(value, default), atomic_write_json(path, payload), fingerprint_text(text), _as_list(value), _mapping(value)

### `memory/memory_retrieval_engine.py`
- **LOC**: 93
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `MemoryStores` (decorator=dataclass(slots=True))
    - **Methods**: as_layer_map(self)
  - `MemoryRetrievalEngine`
    - **Methods**: __init__(self, stores), retrieve(self, cue)

### `memory/memory_scoring.py`
- **LOC**: 339
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `LayerProfile` (decorator=dataclass(frozen=True, slots=True))
  - `MemoryScore` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self)
  - `MemoryScorer`
    - **Methods**: __init__(self, profiles), score(self, cue, candidate), _privacy_penalty(self, cue, record), _risk_penalty(self, cue, candidate)

### `memory/memory_activation.py`
- **LOC**: 162
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `MemoryActivation` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self), to_attention_line(self)
  - `ScoredMemoryCandidate` (decorator=dataclass(slots=True))
  - `MemoryRetrievalResult` (decorator=dataclass(slots=True))
  - `MemoryActivationBuilder`
    - **Methods**: __init__(self, profiles), build(self, scored), _route_bias(self, activations, route)

### `memory/memory_packet_builder.py`
- **LOC**: 179
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `MemoryPacket` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self), to_attention_lines(self), render_prompt_context(self)
  - `MemoryPacketBuilder`
    - **Methods**: from_retrieval_result(self, result), fit_budget(self, packet), _confidence_notes(self, packet)

### `memory/memory_cue.py`
- **LOC**: 332
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `MemoryCue` (decorator=dataclass(slots=True))
    - **Methods**: all_text(self), token_set(self), anchor_set(self), layer_allowed(self, layer), to_dict(self)
  - `MemoryCueBuilder` — Dựng cue từ query/frame mà không import CognitiveFrame cứng. Dùng best-effort getattr để module này sống được trong runtime cũ lẫn mới.
    - **Methods**: from_query_or_frame(self, query), _extract_user_text(self, frame), _extract_dominant_thread(self, frame), _extract_semantic_family(self, frame), _extract_task_intent(self, frame), _extract_files(self, text), _extract_modules(self, text), _looks_like_current_evidence_request(self, text), _looks_like_exact_recall_request(self, text), _allowed_layers(self), _repair_tags(self, text), _affect_tags(self, frame), _relation_tags(self, frame), _privacy_sensitivity(self, text)

### `memory/memory_recall_policy.py`
- **LOC**: 248
- **Vai trò**: Policy module cho memory: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục.
- **Class/dataclass chính**:
  - `RecallPolicyConfig` (decorator=dataclass(slots=True))
  - `MemoryRecallSurfacePolicy` — Policy surface kết quả recall thành câu public.
    - **Methods**: __init__(self, config), surface(self, result), _exact_text(self, result, text), _count_text(self, result), _missing_text(self, result), _trace(self, result), _safe_public_text(self, text), _looks_like_raw_object_surface(self, text)

### `memory/memory_query_ir.py`
- **LOC**: 369
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `QueryIntent` (base=str, Enum) — Loại truy vấn ký ức ở cấp cao.
  - `RoleRef` (base=str, Enum) — Role mà query đang trỏ tới.
  - `ActRef` (base=str, Enum) — Hành vi hội thoại mà query cần lấy.
  - `RelationRef` (base=str, Enum) — Quan hệ giữa target và anchor. Ví dụ: - SELF: lấy chính target. - ANSWER_TO: lấy câu assistant trả lời cho một câu hỏi user. - BEFORE/AFTER: lấy turn trước/sau...
  - `SurfaceMode` (base=str, Enum) — Cách được phép surface câu trả lời ra public.
  - `MemorySourceKind` (base=str, Enum) — Nguồn ký ức mà executor dùng để trả.
  - `MemorySelector` (decorator=dataclass(slots=True)) — Bộ chọn node/fact trong memory. Lưu ý: - ordinal dùng cho exact ordinal như "câu hỏi thứ 3". - quantity dùng cho recent batch như "3 câu hỏi trước". - semantic_...
    - **Methods**: is_empty(self), compact(self)
  - `MemoryRelation` (decorator=dataclass(slots=True)) — Quan hệ query giữa target và anchor.
    - **Methods**: compact(self)
  - `MemoryQueryIR` (decorator=dataclass(slots=True)) — AST truy vấn ký ức. Đây là output của compiler, input của executor. Không nên chứa text answer. IR chỉ nói "cần lấy cái gì".
    - **Methods**: normalized(self), signature(self), compact(self)
  - `QueryHypothesis` (decorator=dataclass(slots=True)) — Một giả thuyết query trong quá trình compile. Compiler nên sinh nhiều hypothesis, xếp hạng, rồi chọn best. Đây là chống "chọn nghĩa quá sớm".
    - **Methods**: normalized(self)
  - `RawRecallResult` (decorator=dataclass(slots=True)) — Kết quả thô sau khi executor chạy query. Đây chưa phải câu public cuối cùng. Policy còn phải quyết định quote/gist/ uncertain.
    - **Methods**: missing(cls, ir, warning, source)
  - `RecallAnswer` (decorator=dataclass(slots=True)) — Câu trả lời đã được policy surface. Adapter có thể đổi object này thành Decision payload.
    - **Methods**: uncertain(cls, text)
- **Hàm module-level**: clamp01(value), blend_confidence(), add_warning(ir, warning)

### `memory/memory_query_compiler.py`
- **LOC**: 347
- **Vai trò**: Compile query từ slot/semantic/repair/LLM parser thành MemoryQueryIR. Debug khi câu hỏi trí nhớ mơ hồ rơi xuống general LLM.
- **Class/dataclass chính**:
  - `CompileDebug` (decorator=dataclass(slots=True))
  - `MemoryQueryCompileResult` (decorator=dataclass(slots=True))
    - **Methods**: has_query(self)
  - `MemoryQueryCompiler` — Blend slot + semantic + repair + optional LLM parser thành IR.
    - **Methods**: __init__(self), compile(self, text), _inject_semantic_hypotheses(self, text, hypotheses, hint), _apply_semantic_scores(self, hypotheses, hint), _top_margin(self, hypotheses), _ambiguity(self, hypotheses, hint), _suppression_note(self, hypotheses, hint, ambiguity)
- **Hàm module-level**: _best_or(scores, default)

### `memory/memory_query_executor.py`
- **LOC**: 367
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `MemoryQueryExecutor` — Thực thi IR trên graph và memory_core.
    - **Methods**: execute(self, ir), _execute_turn_recall(self, ir, graph), _execute_fact_recall(self, ir), _lookup_fact(self, memory_core, fact_key), _format_fact(self, fact_key, value), _execute_summary(self, ir, graph)
- **Hàm module-level**: _unwrap_fact_value(value), _looks_like_internal_memory_object(value), _looks_like_internal_memory_surface(text), _deep_get(data, fact_key)

### `memory/memory_query_slot_parser.py`
- **LOC**: 671
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `SlotSignal` (decorator=dataclass(slots=True)) — Một tín hiệu slot rút từ text.
  - `SlotParseResult` (decorator=dataclass(slots=True)) — Kết quả parse slot.
    - **Methods**: has_self_disclosure(self)
  - `MemoryQuerySlotParser` — Parser slot nhẹ. Dùng cho tiếng Việt thân mật kiểu: - "câu hỏi thứ 2 tôi từng hỏi là gì" - "câu trả lời của em cho câu hỏi thứ 3" - "3 câu hỏi trước đó của tôi"...
    - **Methods**: parse(self, text), _extract_signals(self, raw, norm), _build_hypotheses(self, raw, norm, signals), _target_from_signals(self, signals), _confidence(self, signals)
- **Hàm module-level**: infer_target_role(norm), infer_target_act(norm), infer_anchor(norm), infer_relation(norm), infer_fact_key(norm), infer_self_disclosure_fact(norm), asks_count(norm), asks_summary(norm), asks_exact(norm), looks_recent(norm), looks_like_generic_recall_request(norm), extract_quantity(norm), extract_ordinal(norm), extract_semantic_anchor(norm), _signal_value(signals, name), normalize_vi(text), parse_vi_number(value), _looks_like_name_disclosure(norm), user_is_declaring_or_updating_fact(text), _looks_like_fact_update_disclosure(norm), _looks_like_fact_update_question(norm), _looks_like_birth_month_disclosure(norm), _looks_like_hometown_disclosure(norm), _looks_like_living_location_disclosure(norm), _looks_like_location_preference_disclosure(norm), _looks_like_current_location_disclosure(norm), _looks_like_past_location_disclosure(norm)

### `memory/memory_query_semantics.py`
- **LOC**: 352
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `EmbeddingProvider` (base=Protocol) — Provider embedding tùy chọn. Không bắt buộc.
    - **Methods**: embed(self, text)
  - `SemanticQueryHint` (decorator=dataclass(slots=True)) — Gợi ý semantic, không phải query cuối.
    - **Methods**: top_intent(self), top_fact_key(self)
  - `MemoryQuerySemanticHintEngine` — Prototype semantic scorer. Có thể chạy ở 2 mode: - fallback prototype token similarity: ổn để bootstrap, cap confidence. - provider embedding thật: score protot...
    - **Methods**: __init__(self, embedding_provider), analyze(self, text), _fallback_hint(self, norm), _embedding_hint(self, norm), _score_enum_prototypes(self, text_vec, bank, enum_cls), _score_string_prototypes(self, text_vec, bank), _prototype_cosine(self, text_vec, phrase)
- **Hàm module-level**: normalize_vi(text), _token_similarity(a, b), cosine(a, b), _ambiguity(scores), _top(scores)

### `memory/memory_query_llm_parser.py`
- **LOC**: 215
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `MemoryQueryLLMClient` (base=Protocol) — Client tối thiểu cần có. Có thể adapter từ LlmService hiện tại: - gửi system prompt + user text - trả raw string JSON
    - **Methods**: complete_json(self)
  - `LLMParseDecision` (decorator=dataclass(slots=True))
  - `MemoryQueryLLMParser` — Parser LLM có schema, chỉ dùng khi compiler cần.
    - **Methods**: __init__(self, client), should_use_llm(self), parse(self, text), build_system_prompt(self), schema(self), _parse_json(self, raw), _dict_to_ir(self, data), _selector(self, data)
- **Hàm module-level**: _enum(enum_cls, value, default), _int_or_none(value)

### `memory/memory_query_repair.py`
- **LOC**: 277
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `MemoryQueryRepairItem` (decorator=dataclass(slots=True))
  - `RepairPriorResult` (decorator=dataclass(slots=True))
  - `MemoryQueryRepairStore` — Store nhỏ cho repair query. Có thể thay bằng repair_memory thật của project sau.
    - **Methods**: __init__(self, items), record(self), apply_prior(self), save_json(self, path), load_json(cls, path)
- **Hàm module-level**: _ir_to_dict(ir), _selector_to_dict(sel), _ir_from_dict(data), normalize_vi(text), text_similarity(a, b)

### `memory/memory_turn_graph.py`
- **LOC**: 435
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `TurnRole` (base=str, Enum)
  - `TurnSpeechAct` (base=str, Enum)
  - `TurnEdgeType` (base=str, Enum)
  - `FactMention` (decorator=dataclass(slots=True)) — Fact được phát hiện trong turn, ví dụ user.birth_month=8.
  - `TurnNode` (decorator=dataclass(slots=True)) — Node hội thoại. index là thứ tự toàn phiên, bắt đầu 1. role_index là thứ tự trong cùng role, ví dụ user turn thứ 3. act_index là thứ tự theo role+speech_act, ví...
    - **Methods**: counts_as_answer(self), is_question(self)
  - `TurnEdge` (decorator=dataclass(slots=True)) — Cạnh quan hệ giữa hai turn.
  - `TurnGraph` — Graph phiên hiện tại. Dùng để thực thi query exact: - nth user question - assistant answer to nth user question - last N user questions - count user questions
    - **Methods**: __init__(self), add_turn(self, node), add_edge(self, edge), get(self, node_id), from_turns(cls, turns), from_session_ledger(cls, session_ledger), infer_basic_answer_edges(self), select(self, selector), first_assistant_answer_to(self, user_question_id), neighbor_after(self, node_id, selector), neighbor_before(self, node_id, selector), count(self, selector), last_n(self, selector, n)
- **Hàm module-level**: _get(obj, key, default), _role_from_any(value), _role_ref_to_turn(role), _act_ref_to_turn(act), _norm(text), _text_relevance(hint, text, tags)

### `memory/memory_turn_annotator.py`
- **LOC**: 400
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `TurnAnnotation` (decorator=dataclass(slots=True))
  - `TurnAnnotator` — Annotator nhẹ, đủ tốt để build TurnGraph trước khi semantic layer sâu hơn.
    - **Methods**: annotate(self), build_edges(self, graph), _find_recent_correctable(self, graph, before_index), extract_fact_mentions(self), _looks_like_question(self, raw, norm), _looks_like_correction(self, norm), _looks_like_command(self, norm), _is_service_fallback(self, norm, metadata)
- **Hàm module-level**: normalize_vi(text), parse_vietnamese_number(text)

### `memory/claim_extractor.py`
- **LOC**: 69
- **Vai trò**: Module `claim extractor` trong package `memory`.
- **Class/dataclass chính**:
  - `ClaimExtractor` (decorator=dataclass(slots=True)) — Facade extract claim theo pipeline frame semantics. `parser` mặc định là fallback surface rất nhỏ. Runtime production nên thay bằng parser model.gguf trả `Meani...
    - **Methods**: extract(self, user_text)
- **Hàm module-level**: extract_claims(user_text)

### `memory/semantic_claim.py`
- **LOC**: 291
- **Vai trò**: Module `semantic claim` trong package `memory`.
- **Class/dataclass chính**:
  - `SemanticClaim` (decorator=dataclass(frozen=True, slots=True)) — Một mệnh đề semantic đã chuẩn hóa. Cấu trúc quan trọng nhất là: subject + predicate + object + modality + temporal + assertion Ví dụ: subject="user" predicate="...
    - **Methods**: to_dict(self), from_dict(cls, data), qualifier_dict(self), with_confidence(self, confidence)
  - `ExtractedClaim` (decorator=dataclass(frozen=True, slots=True)) — Kết quả extractor trả ra trước khi commit. `commit_hint` chỉ là gợi ý. Worthiness/Retention policy mới là nơi quyết định thật.
    - **Methods**: to_dict(self)
- **Hàm module-level**: make_claim_id(seed), build_claim(), _clamp01(value), _coerce_literal(value, allowed, default)

### `memory/claim_entailment.py`
- **LOC**: 130
- **Vai trò**: Module `claim entailment` trong package `memory`.
- **Class/dataclass chính**:
  - `ClaimEntailmentDecision` (decorator=dataclass(frozen=True, slots=True))
    - **Methods**: can_answer(self)
  - `ClaimEntailmentEngine` — Engine entailment giữa SemanticClaim và SemanticQueryIntent.
    - **Methods**: evaluate(self, claim, query), rank(self, claims, query)
- **Hàm module-level**: semantic_claim_from_memory_item(item)

### `memory/predicate_ontology.py`
- **LOC**: 394
- **Vai trò**: Module `predicate ontology` trong package `memory`.
- **Class/dataclass chính**:
  - `EntailmentType` (base=str, Enum)
  - `PredicateSpec` (decorator=dataclass(frozen=True, slots=True))
- **Hàm module-level**: get_predicate(name), fact_key_for_predicate(predicate), predicate_for_fact_key(fact_key), predicate_aliases(predicate), entailment_for_target(claim, target), contradicts(a, b), is_long_term_predicate(predicate), storage_layer_for_predicate(predicate), default_decay_for_predicate(predicate), importance_for_predicate(predicate), _compatible_targets(predicates), _norm(text)

### `memory/semantic_answer_policy.py`
- **LOC**: 115
- **Vai trò**: Policy module cho memory: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục.
- **Class/dataclass chính**:
  - `SemanticAnswer` (decorator=dataclass(frozen=True, slots=True))
  - `SemanticAnswerPolicy` — Chọn claim exact và format câu trả lời ngắn, grounded.
    - **Methods**: __init__(self), answer(self, query, memory_items), _missing_text(self, intent), _format(self, intent, claim)

### `memory/memory_worthiness.py`
- **LOC**: 135
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `WorthinessDecision` (decorator=dataclass(frozen=True, slots=True))
  - `MemoryWorthinessPolicy` — Policy chặn ghi nhớ bừa trước khi retention tính decay.
    - **Methods**: decide(self, claim)

### `memory/memory_retention_policy.py`
- **LOC**: 134
- **Vai trò**: Policy module cho memory: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục.
- **Class/dataclass chính**:
  - `RetentionDecision` (decorator=dataclass(frozen=True, slots=True))
  - `MemoryRetentionPolicy` — Policy retention cho SemanticClaim.
    - **Methods**: decide(self, claim, worthiness)
- **Hàm module-level**: retention_metadata(decision)

### `memory/claim_consolidator.py`
- **LOC**: 73
- **Vai trò**: Module `claim consolidator` trong package `memory`.
- **Class/dataclass chính**:
  - `ClaimMergeDecision` (decorator=dataclass(frozen=True, slots=True))
  - `ClaimConsolidator` — Logic merge claim độc lập với store JSON.
    - **Methods**: can_merge(self, old, new), find_merge_target(self, items, new)
- **Hàm module-level**: _norm(text)

### `memory/memory_consolidator.py`
- **LOC**: 80
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `ConsolidationResult` (decorator=dataclass(slots=True))
    - **Methods**: to_dict(self)
  - `MemoryConsolidator`
    - **Methods**: __init__(self, memory_core), run_once(self)

### `memory/memory_pruner.py`
- **LOC**: 123
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `PruneDecision` (decorator=dataclass(frozen=True, slots=True))
  - `MemoryPruner` — Pruner dựa trên retention metadata nếu có.
    - **Methods**: decide(self, item)
- **Hàm module-level**: _metadata(item), _float(value, default), _epoch(value), _surface_text(item), _looks_like_trivial_semantic_noise(surface, semantic_source)

### `memory/memory_ai_curator.py`
- **LOC**: 512
- **Vai trò**: memory/memory_ai_curator.py =========================== AI curator cho memory — gọi Gemini để làm 2 việc rule không làm được: 1. Episodic distillation: Nhiều episode tương đồng → 1 semantic fact ổn định. Ví dụ: 5 lần use...
- **Class/dataclass chính**:
  - `CuratorResult` (decorator=dataclass(slots=True)) — Kết quả một lượt curator chạy.
    - **Methods**: to_dict(self)
  - `MemoryAICurator` — AI curator chạy trong background maintenance.
    - **Methods**: __init__(self), run_distillation(self), run_concern_bridge(self), _cluster_episodes(self, items), _distill_cluster(self, cluster), _load_concerns(self, path), _ripe_concerns(self, concerns), _bridge_concern(self, concern), _commit_semantic_fact(self, fact), _commit_from_bridge(self, decision), _mark_concern_bridged(self, concern, path), _call_llm(self, system, user), _parse_json(self, raw), _to_namespace(d)
- **Hàm module-level**: _compact(value, limit), _safe_float(value, default), _get(obj, key, default)

### `memory/memory_maintenance.py`
- **LOC**: 248
- **Vai trò**: Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory.
- **Class/dataclass chính**:
  - `MemoryMaintenanceRunner` — Orchestrator maintain nhẹ cho memory stores.
    - **Methods**: __init__(self, memory_core), run(self), _candidate_limit(self, budget), _run_access_decay(self), _run_prune_audit(self)

### `memory/understanding/semantic_parser.py`
- **LOC**: 597
- **Vai trò**: Parser/normalizer cho memory/understanding.
- **Class/dataclass chính**:
  - `SemanticParser` (base=Protocol) — Protocol chung để runtime có thể thay fallback bằng model.gguf.
    - **Methods**: parse(self, text)
  - `ModelSemanticParser` (decorator=dataclass(slots=True)) — Adapter cho model/LLM parser bên ngoài. `parse_callable` là hàm của Ngài. Nó nhận text và trả dict/list đã parse. File này không biết llama.cpp, Ollama hay GGUF...
    - **Methods**: parse(self, text)
  - `StructuredFrameParser` (decorator=dataclass(slots=True)) — Parser chỉ verify JSON structured đã có sẵn.
    - **Methods**: parse(self, text)
  - `FallbackSurfaceSemanticParser` (decorator=dataclass(slots=True)) — Fallback rất nhỏ khi chưa có model.gguf. Nó không cố hiểu sâu. Nó chỉ nhận ra vài frame rất phổ thông bằng các detector tập trung. Quan trọng: detector sinh Mea...
    - **Methods**: parse(self, text)
- **Hàm module-level**: structured_frames_to_result(text, payload), _frame_from_mapping(item), _claim_like_to_frame(item), _parse_clause_as_frames(clause, surface), _mk_frame(frame_type, relation, value, kind, evidence, certainty, time_scope, modality, surface), _extract_after(norm, raw, cues), _extract_identity_name(raw), _extract_identity_nickname(raw), _extract_study_field(raw), _extract_year(norm), _extract_preference(norm, raw), _extract_after(raw, cues), _extract_preference(norm, raw), _normalized_with_offsets(text), _has_self(norm), _looks_like_style_instruction(norm), _looks_like_feedback(norm), _infer_frame_type(relation), _clamp01(value)

### `memory/understanding/meaning_frame.py`
- **LOC**: 192
- **Vai trò**: Module `meaning frame` trong package `memory/understanding`.
- **Class/dataclass chính**:
  - `EntityRef` (decorator=dataclass(frozen=True, slots=True)) — Entity đã link nhẹ từ surface text. `kind` là nhãn loại entity: location/person_name/style_rule/topic/... `canonical` là dạng ổn định để merge/search. Không đượ...
    - **Methods**: to_dict(self), from_dict(cls, data)
  - `MeaningFrame` (decorator=dataclass(frozen=True, slots=True)) — Khung nghĩa đã đọc từ một phát ngôn. Field quan trọng: - frame_type: loại hành vi/nghĩa ở mức cao. - relation: quan hệ ngữ nghĩa, chưa phải predicate memory cuố...
    - **Methods**: is_assertive(self), to_dict(self), from_dict(cls, data)
  - `MeaningParseResult` (decorator=dataclass(frozen=True, slots=True)) — Output của SemanticParser. Parser có thể là model.gguf, parser rule-based, hoặc hybrid. Nhưng dù đến từ đâu, downstream chỉ nhận dạng này. Model không được phép...
    - **Methods**: to_dict(self)
- **Hàm module-level**: _coerce(value, allowed, default), _clamp01(value)

### `memory/understanding/entity_linker.py`
- **LOC**: 114
- **Vai trò**: Module `entity linker` trong package `memory/understanding`.
- **Hàm module-level**: link_entity(value), clean_surface(value), normalize(text), strip_accents(text), _looks_like_location(norm), _looks_like_person_name(text)

### `memory/understanding/polarity_temporal.py`
- **LOC**: 107
- **Vai trò**: Module `polarity temporal` trong package `memory/understanding`.
- **Class/dataclass chính**:
  - `SurfaceFeatures` (decorator=dataclass(frozen=True, slots=True))
- **Hàm module-level**: analyse_surface(text), _has_any(norm, phrases), split_clauses(text)

# 8. LLM / parser / transport / action / telemetry chi tiết

### `llm/service.py`
- **LOC**: 3152
- **Vai trò**: Façade gọi model. Build prompt theo chat/directive/autonomous/micro/vision, parse Decision JSON, repair malformed JSON, chống prompt leak, fallback protocol/service, style rewrite, chat-act guard. Debug khi provider trả prose/JSON cụt/CoT hoặc hỏi thẳng mà đáp vòng.
- **Class/dataclass chính**:
  - `ChatAct` (base=Enum)
  - `FormatViolationException` (base=Exception) — Raised when a model response violates the public JSON contract.
    - **Methods**: __init__(self, reason)
  - `LlmService`
    - **Methods**: __init__(self, client, style_client, vision_client, fallback_client, logger), _http_status_code(self, exc), _is_retryable_http_5xx(self, exc), _build_service_error_fallback(self), _message_text(self, message), _normalize_vietnamese_ascii(self, text), _looks_like_direct_question(self, text), _is_short_or_ambiguous_user_text(self, text), _is_self_identity_question(self, text), _contains_user_intent_inference(self, text), _build_chat_contract_prompt(self, raw_user_text, act), _chat_text_family(self, text), _decision_payload_text(self, raw_json), _chat_act_repair_signal(self, act), _normalize_vietnamese_ascii(self, text), _deterministic_chat_act_fallback_text(self, act, raw_user_text), _payload_with_repaired_chat_act_text(self, raw_json), _repair_chat_act_payload_with_llm(self, raw_json), _rewrite_question_only_chat_answer(self, text), _append_reasoning_tag(self, payload, tag), _looks_like_relational_feedback_text(self, text), _looks_like_defensive_relational_reply(self, text), _relational_repair_fallback_text(self, raw_user_text, current_text), _guard_chat_output(self, raw_json), _contextual_service_fallback_text(self, messages), _log_final_prompt(self, messages), _preview_log_text(self, text), _looks_like_prompt_leak(self, text), _looks_like_malformed_decision_json(self, text), _json_string_field_from_raw(self, raw_text, field), _build_protocol_failure_fallback(self), _coerce_malformed_decision_payload(self, raw_text), _log_raw_api_text(self, channel, raw), _is_context_size_error(self, exc), _parse_context_error_stats(self, exc), _content_text_len(self, content), _truncate_content(self, content), _shrink_messages_for_context(self, messages), _collect_text_chunks(self, value), _extract_content(self, response), _extract_first_json_object(self, text), _parse_json_object(self, text), _normalize_payload_keys(self, value), _is_valid_decision_payload(self, payload), _is_valid_motion_payload(self, payload), _is_valid_cognition_payload(self, payload), _is_decision_like_payload(self, payload), _coerce_bool_value(self, value), _coerce_confidence_value(self, value), _coerce_reasoning_tags_value(self, value), _coerce_action_value(self, value), _action_field(self, action), _is_valid_text_field(self, value), _is_valid_animation_field(self, value), _is_valid_system_action_field(self, value), _is_valid_choice_number(self, value, choices), _is_valid_target_x(self, value), _allows_motion_target(self, payload), _coerce_text_value(self, value), _coerce_animation_value(self, value), _coerce_direction_value(self, value), _coerce_target_x_value(self, value), _coerce_system_action_value(self, value), _coerce_decision_like_payload(self, payload), _coerce_json_candidate(self, raw_text), _build_json_fallback(self, raw_text), _looks_like_provider_metadata(self, text), _looks_like_markdown_json_stub(self, text), _safe_fallback_text(self, raw_text), _build_empty_text_fallback(self), _decision_needs_non_empty_text(self, raw_text), _decision_text_is_invalid(self, raw_text), _with_non_empty_text_rule(self, messages), _repair_empty_decision_text(self), _repair_decision_json(self, raw_text), _strict_decision_candidate_or_raise(self, raw), _complete_decision(self), _normalize_for_claim_diff(self, text), _style_rewrite_is_safe(self, original, rewritten), rewrite_text_with_local_style(self, decision), rewrite_guard_violation_text(self), _compress_internal_context(self, text), _extract_action_plan_context(self, text), _build_style_block(self), _build_memory_context_block(self, memory_context), _build_grounding_context_block(self, grounding_context), _build_relational_repair_contract(self, context), _is_force_speak_without_speech_evidence(self), _build_directive_mode_addendum(self, ti_context), _build_speech_intent_guidance(self, speech_intent), _is_session_ritual_call(self), _fallback_greeting_engine(self), _fallback_greeting_text(self), _build_session_greeting_payload(self), _session_greeting_frame(self, telemetry_data), _session_greeting_quality_scorer(self), _extract_candidate_strings(self, payload), _generate_session_ritual_greeting(self), generate_directive(self), generate_micro_presence_line(self), generate_screen_facts(self), _chat_client_supports_vision(self), generate_chat_reply(self), run_ni_meta_critic(self)
- **Hàm module-level**: _normalize_vietnamese_ascii_text(text), classify_chat_act(raw_user_text)
- **Phụ thuộc nội bộ nổi bật**: actions.contracts, cortex.banned_filler, runtime.no_fallback_policy, runtime.voice_policy

### `llm/contracts.py`
- **LOC**: 240
- **Vai trò**: Contract/dataclass dùng chung trong llm.
- **Hàm module-level**: _gbnf_literal(value), _build_decision_gbnf()
- **Phụ thuộc nội bộ nổi bật**: actions.contracts

### `llm/client.py`
- **LOC**: 426
- **Vai trò**: HTTP client Gemini/OpenAI-compatible/llama-server, payload variants, 429 key rotation, image payload, HTTP error body. Debug khi provider shape lạ hoặc key pool xoay không đúng.
- **Class/dataclass chính**:
  - `LlamaServerClient`
    - **Methods**: __init__(self, base_url, timeout), _detect_model_name(self), create_chat_completion(self)
  - `OpenAICompatibleClient`
    - **Methods**: __init__(self, base_url, api_key, model_name, timeout, key_pool), _normalize_api_key(self, raw_value), create_chat_completion(self)
  - `GeminiClient`
    - **Methods**: __init__(self, base_url, api_key, model_name, timeout, key_pool), _normalize_api_key(self, raw_value), _text_part(self, text), _image_part_from_url(self, url), _parts_from_content(self, content), _convert_messages(self, messages), create_chat_completion(self)
- **Hàm module-level**: _http_error_with_body(response), _chat_payload_variants(payload), _model_supports_reasoning_toggle(model_name), _resolve_reasoning_effort()

### `llm/key_pool.py`
- **LOC**: 159
- **Vai trò**: llm/key_pool.py Pool API key dùng CHUNG cho mọi mạch gọi Gemini (main / speech / private_mind). Mỗi key thường thuộc một Google project khác nhau (vd nhiều Gmail) → mỗi key có hũ free quota riêng. Free tier tính theo PRO...
- **Class/dataclass chính**:
  - `ApiKeyPool` — Danh sách key + một con trỏ rotation dùng chung.
    - **Methods**: __init__(self, keys), size(self), current_key(self), rotate(self), index(self)
- **Hàm module-level**: _normalize_kind(kind), _is_placeholder(value), _collect_gemini_keys(), _collect_groq_keys(), get_key_pool(kind), get_shared_key_pool(), reset_shared_key_pool()

### `llm/process_manager.py`
- **LOC**: 239
- **Vai trò**: Module `process manager` trong package `llm`.
- **Class/dataclass chính**:
  - `RemoteModelProcessManager`
    - **Methods**: __init__(self), _env_flag(self, name, default), _build_remote_client(self), _speech_api_requested(self), _build_speech_client(self), build_client(self), build_style_client(self), build_format_fallback_client(self), build_vision_client(self), stop(self)
- **Phụ thuộc nội bộ nổi bật**: eris_secrets

### `llm/ollama_client.py`
- **LOC**: 317
- **Vai trò**: Client mỏng cho Ollama. Vai trò trong ERIS: - Dùng một Ollama daemon duy nhất thay vì mở nhiều llama-server riêng. - Gọi model nhỏ cho BackgroundObserver. - Gọi model vision cho VisionSemanticCompressor về sau. - Ép JSON...
- **Class/dataclass chính**:
  - `OllamaClientError` (base=RuntimeError) — Lỗi gọi Ollama. Tách riêng để runtime có thể fallback sạch.
  - `OllamaResult` (decorator=dataclass(frozen=True)) — Kết quả chuẩn hóa từ Ollama. `parsed` chỉ có giá trị khi output parse được thành JSON object. `raw` giữ nguyên response từ Ollama để debug khi cần.
  - `OllamaClient` (decorator=dataclass) — Client gọi Ollama qua HTTP API. Ollama mặc định chạy ở http://localhost:11434/api. Có thể override bằng env `OLLAMA_BASE_URL`.
    - **Methods**: __post_init__(self), chat_json(self, model, messages), generate_json(self, model, prompt), unload(self, model), list_models(self), encode_image_file(path), encode_image_bytes(data), data_uri_to_base64(data_uri_or_base64), _attach_images(self, messages, images), _normalize_base_url(base_url), _post_json(self, path, payload), _get_json(self, path), _open_json(self, req), _extract_chat_content(raw), _parse_json_object(content)

### `llm/llamacpp_client.py`
- **LOC**: 126
- **Vai trò**: llm/llamacpp_client.py ====================== Engine inference local IN-PROCESS dựa trên llama-cpp-python. Mục đích: chạy model gguf đặt thẳng trong `src/` mà KHÔNG cần Ollama hay llama-server ngoài → bản build self-cont...
- **Class/dataclass chính**:
  - `LlamaCppClient` — Wrapper llama-cpp-python theo interface create_chat_completion của ERIS.
    - **Methods**: __init__(self), _llama(self), create_chat_completion(self)
- **Hàm module-level**: _project_root(), _bundle_root(), resolve_model_path(path_or_name)

### `llm/local_llama_engine.py`
- **LOC**: 297
- **Vai trò**: llm/local_llama_engine.py ========================= Engine local thống nhất bằng llama-cpp-python, drop-in thay cho ``OllamaClient``. Mục tiêu: dồn TẤT CẢ model nội bộ về một engine duy nhất chạy gguf trong ``src/`` (khô...
- **Class/dataclass chính**:
  - `LocalLlamaEngine` — Engine llama-cpp dùng chung, interface tương thích OllamaClient.
    - **Methods**: __init__(self), _text_llm(self), _vision_llm(self), chat_json(self, model, messages), generate_json(self, model, prompt), _response_format(self, schema), _chat_text(self, messages), _chat_vision(self, messages, images), unload(self, model), list_models(self), encode_image_file(path), encode_image_bytes(data), data_uri_to_base64(data_uri_or_base64), _messages_to_text(messages), _extract_content(raw), _parse_json_object(content)
- **Hàm module-level**: _env(name, default), _n_gpu_layers(), build_local_or_ollama_client()
- **Phụ thuộc nội bộ nổi bật**: llm.llamacpp_client

### `parser_grounding/decision.py`
- **LOC**: 1853
- **Vai trò**: Mixin parser raw LLM output -> Decision. Repair JSON candidate, coerce fields, sanitize motion/action, detect capability/perception violations, fallback non-JSON safely. Debug khi LLM trả prose/JSON vỡ mà parser xử sai.
- **Class/dataclass chính**:
  - `ParserGroundingMixin`
    - **Methods**: _normalize_keyword_text(self, text), _contains_keyword(self, text, keyword), _contains_any_keyword(self, text, keywords), _is_embodied_command_request(self, text), _should_infer_embodied_animation(self, text, user_hint), _preview_raw_response(self, raw_text), _normalize_debug_trace(self, value), _build_parser_debug_trace(self), _collect_capability_violations(self, text), _infer_animation_reason(self, final_animation, text, user_hint), _build_parser_trace_summary(self), _log(self, level, message), _extract_first_json_object(self, text), _extract_first_json_candidate(self, text), _repair_json_candidate(self, text), _patch_missing_decision_fields(self, payload), _finalize_loaded_json_payload(self, payload), _try_parse_hard_json_repair(self, text, user_hint), _normalize_salvaged_text(self, text), _repair_sentence_boundaries(self, text), _normalize_decision_field_keys(self, value), _coerce_bool(self, value), _coerce_confidence(self, value), _coerce_reasoning_tags(self, value), _action_field(self, action), _apply_cognition_action_defaults(self, data, user_hint), _clean_inline_field_value(self, value), _cut_inline_metadata_from_public_text(self, text), _looks_like_prompt_or_contract_leak_text(self, text), _looks_like_non_json_analysis_or_debug_text(self, text), _non_json_semantic_fallback_payload(self), _try_extract_inline_decision_fields_from_text(self, text), _sanitize_direction(self, value), _sanitize_target_x(self, value), _sanitize_motion_facing(self, value), _try_extract_nested_decision_from_text(self, text), _unwrap_structured_text_candidate(self, text), _clean_nested_field_scalar(self, value), _clean_nested_field_text(self, value), _sanitize_motion_intent(self, value), _infer_motion_intent(self), _sanitize_animation(self, value, fallback_text, user_hint), _sanitize_system_action(self, value), _is_strict_direction_value(self, value), _is_strict_target_x_value(self, value), _requires_lax_json_mode(self, payload), _get_runtime_capability_summary(self), _split_into_claim_units(self, text), _is_allowed_self_claim(self, clause), _has_vision_frame_context(self, text), _is_screen_observation_claim(self, clause, context), _clause_mentions_unsupported_target(self, clause), _clause_has_strong_control_fantasy(self, clause), _clause_exceeds_runtime_capability(self, clause, previous_unit, context), _rewrite_excessive_clause(self, clause, user_hint), _ground_text_to_runtime_capabilities(self, text, user_hint), _has_contradictory_encouragement(self, text), _has_philosophical_filler(self, text), _has_overmanaged_style(self, text), _build_grounded_text(self, user_hint), _is_speculative_extracted_fact(self, fact), _finalize_decision(self, decision, user_hint), _infer_structured_action(self, text, user_hint), _salvage_non_json_response(self, cleaned, user_hint), _extract_lax_field(self, text, field, known_fields), _try_parse_lax_json(self, text, user_hint), _infer_animation_reason(self, final_animation, text, user_hint), _infer_animation_from_text(self, text), _infer_structured_action(self, text, user_hint), parse_ai_json(self, raw_text, user_hint), _is_follow_up_question(self, user_message), _build_chat_user_message(self, user_message)
- **Phụ thuộc nội bộ nổi bật**: actions.contracts, guard_config, llm.contracts, runtime.no_fallback_policy

### `parser_grounding/service.py`
- **LOC**: 267
- **Vai trò**: Module `service` trong package `parser_grounding`.
- **Class/dataclass chính**:
  - `DecisionParser` (base=ParserGroundingMixin)
    - **Methods**: __init__(self, fallback, logger), _is_climb_request(self, text), _infer_look_direction(self, text), _is_look_only_request(self, text), _infer_move_direction(self, text), _is_drop_from_climb_request(self, text), _is_reverse_climb_request(self, text), _is_climb_top_request(self, text), _is_top_hold_request(self, text), _infer_top_platform_target(self, text), _infer_air_swing_from_text(self, text), _infer_animation_from_text(self, text), _infer_structured_action(self, text, user_hint), _is_embodied_command_request(self, text), _should_suppress_salvaged_text(self, finalized, user_hint), _finalize_decision(self, decision, user_hint), parse(self, raw_text, user_hint), build_chat_user_message(self)
- **Phụ thuộc nội bộ nổi bật**: domain

### `domain/decision.py`
- **LOC**: 98
- **Vai trò**: Dataclass Decision và `to_payload()`. Resolve motion_intent/target/facing/text/should_speak trước khi gửi UDP.
- **Class/dataclass chính**:
  - `Decision` (decorator=dataclass(slots=True))
    - **Methods**: resolve_motion_intent(self), resolve_motion_target_x(self), resolve_motion_facing(self), _payload_text(self), to_payload(self)

### `transport/udp.py`
- **LOC**: 249
- **Vai trò**: UDP transport. Send JSON Decision, poll event body, nén private_mind_digest/debug khi quá 63KB.
- **Class/dataclass chính**:
  - `UdpTransport`
    - **Methods**: __init__(self, send_host, send_port, recv_host, recv_port), send_text(self, message), send_json(self, payload), poll_json(self), close(self)
- **Hàm module-level**: _compact_private_mind_for_udp_overflow(value), _compact_inner_diary(diary), _slim_private_mind_core(private_mind), _compact_debug_value(value), _compact_scalar(value, limit)

### `actions/router.py`
- **LOC**: 552
- **Vai trò**: High-confidence action router for ERIS. Router này chỉ nên bắt các lệnh hệ thống thật sự rõ ràng. Nếu câu user có vẻ là câu hỏi, meta-discussion, code/debug, hoặc chỉ nhắc đến một từ khóa như "youtube/search/volume/copy"...
- **Class/dataclass chính**:
  - `RouteCandidate` (decorator=dataclass(frozen=True)) — Ứng viên route nội bộ. confidence không dùng để làm màu. Nó là cổng cuối: chỉ action đủ chắc mới được trả ra ngoài. Các blocker có thể hạ confidence hoặc hủy ca...
    - **Methods**: allowed(self)
  - `ActionRouter` — Route chat text thành direct system action. Public API giữ nguyên bản cũ: route_chat(user_text, last_action="") -> tuple[action, value] | None Router này không...
    - **Methods**: route_chat(self, user_text), _route_open_url(self, raw, norm), _route_now_playing(self, raw, norm), _route_now_playing_follow_up(self, raw, norm), _route_play_pause_media(self, raw, norm), _route_volume(self, raw, norm), _route_copy_text(self, raw, norm), _route_focus_window(self, raw, norm), _route_launch_app(self, raw, norm), _route_search_web(self, raw, norm), _route_weather(self, raw, norm), _looks_like_now_playing(self, lowered), _looks_like_now_playing_follow_up(self, lowered), _normalize_vi(text), _pad(cls, text), _starts_with_negation(cls, norm), _looks_like_meta_question(cls, norm), _contains_any(norm, needles), _now_playing_is_meta(cls, norm), _looks_like_correction(cls, norm), _copy_rest_is_meta(cls, rest_norm), _weather_is_meta(cls, norm), _target_is_meta_or_empty(cls, target), _extract_single_quoted_payload(text), _no_candidate(action), _blocked(action, reason)

### `actions/executor.py`
- **LOC**: 658
- **Vai trò**: Executor thực thi action/command cho actions.
- **Class/dataclass chính**:
  - `ActionExecutor`
    - **Methods**: __init__(self, logger), execute(self, action_name, action_input), _get_now_playing(self, action_input), _focus_window(self, action_input), _open_url(self, action_input), _set_volume(self, action_input), _search_web(self, action_input), _get_weather(self, action_input), _play_pause_media(self, action_input), _copy_text(self, action_input), _launch_app(self, action_input), _normalize_url(self, raw), _press_virtual_key(self, virtual_key, pause), _set_clipboard_text(self, text), _log(self, level, message)
- **Phụ thuộc nội bộ nổi bật**: eris_secrets

### `actions/contracts.py`
- **LOC**: 27
- **Vai trò**: Contract/dataclass dùng chung trong actions.
- **Class/dataclass chính**:
  - `ActionExecutionResult` (decorator=dataclass(slots=True))

### `telemetry/service.py`
- **LOC**: 62
- **Vai trò**: Module `service` trong package `telemetry`.
- **Class/dataclass chính**:
  - `TelemetryService` (base=TelemetryMixin)
    - **Methods**: __init__(self), capture_snapshot(self), format_snapshot(self, snapshot), format_directive_snapshot(self, snapshot), capture_machine_context(self), get_system_telemetry(self), capture_screen_frame_data_uri(self)
- **Phụ thuộc nội bộ nổi bật**: cortex

### `telemetry/system.py`
- **LOC**: 235
- **Vai trò**: Module `system` trong package `telemetry`.
- **Class/dataclass chính**:
  - `TelemetryMixin`
    - **Methods**: _get_content_metadata_collector(self), _get_browser_telemetry_uia(self), _get_all_windows(self), _get_idle_seconds(self), capture_raw_telemetry(self), get_system_telemetry(self)
- **Hàm module-level**: _ensure_com_initialized()

### `telemetry/content_metadata.py`
- **LOC**: 609
- **Vai trò**: Thu thập metadata nội dung đang nhìn thấy cho SeLens. Mục tiêu của file này không phải "đọc màn hình như tiên tri". Nó chỉ gom các fact có nguồn rõ ràng theo thang L0-L5 rồi trả về dict nhỏ để SeLens tự quyết confidence....
- **Class/dataclass chính**:
  - `ContentMetadata` (decorator=dataclass(slots=True)) — Fact thô về nội dung foreground. Ghi chú tiếng Việt cho tương lai: - `source` là nguồn mạnh nhất đang có, không phải mọi nguồn đã thử. - `tier` là L0-L5 theo la...
    - **Methods**: to_dict(self)
  - `ContentMetadataCollector` — Best-effort collector cho metadata nội dung foreground. Luồng ưu tiên: 1. DOM bridge cache do extension/local bridge ghi ra. Mạnh nhất. 2. Accessibility tree fo...
    - **Methods**: __init__(self), collect(self), _merge_sources(self), _read_dom_bridge(self), _read_media_session_cache(self), _read_ocr_cache(self), _read_accessibility_text(self), _from_browser_or_window_title(self), _read_fresh_json(self, paths), _privacy_level(self)
- **Hàm module-level**: _candidate_cache_paths(env_name, filename), _pick_matching_url(candidates, current_url), _infer_page_kind(), _normalize_hashtags(value), _normalize_media_state(value), _clean_text(value, limit), _dedupe_join(values), _choose_longer(left, right), _text_overlap(left, right), _tokenize(value), _domain_from_url(url), _domain_matches(domain, expected_domains), _coerce_float(value, default), _env_bool(name, default), _env_int(name, default), _env_float(name, default)


# 9. Index theo package

## root
Entrypoint và cấu hình nền. `vision.py` dựng toàn bộ runtime Python, khóa single-instance, nạp LLM client, memory, telemetry, action router và `RuntimeCoordinator`.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `app_logging.py` | 28 | CategoryFormatter | Module `app_logging` trong package `root`. |
| `eris_secrets.py` | 284 | - | Module `eris_secrets` trong package `root`. |
| `failure_meta.py` | 83 | - | Module `failure_meta` trong package `root`. |
| `guard_config.py` | 48 | - | Module `guard_config` trong package `root`. |
| `sender.py` | 41 | - | Module `sender` trong package `root`. |
| `vision.py` | 268 | AttentionOverseer, SingleInstanceLock | Module `vision` trong package `root`. |

## actions
Các hành động hệ thống (ActionExecutor): search web, focus window, open URL, adjust volume, launch app. Có router lọc kỹ để chỉ chạy khi user ra lệnh trực tiếp.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `actions/__init__.py` | 11 | - | Module `__init__` trong package `actions`. |
| `actions/contracts.py` | 26 | ActionExecutionResult | Module `contracts` trong package `actions`. |
| `actions/executor.py` | 657 | ActionExecutor | Module `executor` trong package `actions`. |
| `actions/router.py` | 551 | RouteCandidate, ActionRouter | High-confidence action router for ERIS. |

## core
Contract V3 thấp nhất: RawSignal, EvidenceItem, ModuleReport, StateCommitRequest, CognitiveFrame và EvidenceNormalizer. Đây là lớp bắt mọi thứ có nguồn, confidence và privacy tag trước khi đi tiếp.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `core/__init__.py` | 22 | - | Module `__init__` trong package `core`. |
| `core/cognitive_frame.py` | 1442 | FrameMutation, FrameValidationIssue, FramePromptPacket, CognitiveFrame, CognitiveFrameBuilder | core/cognitive_frame.py |
| `core/evidence.py` | 837 | RawSignalValidationError, RawSignal, EvidenceItem, ModuleReport, StateCommitRequest, DebugTrace | Module `evidence` trong package `core`. |
| `core/evidence_normalizer.py` | 208 | EvidenceNormalizerConfig, NormalizationResult, EvidenceNormalizer | core/evidence_normalizer.py |

## cortex
Bộ não chứa các substrate nhận thức (attention, internal_state, appraisal, affect, personality, speech_core, surface_arbiter...). Nơi chạy 3-tier autonomy (Sleep, Observe, Think, wake governor) và spontaneous life.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/__init__.py` | 163 | - | Module `__init__` trong package `cortex`. |
| `cortex/action_memory.py` | 438 | ActionTrace, ActionMemoryState | Action memory and rhythm state for ERIS. |
| `cortex/action_planner.py` | 706 | ActionPlanner | Utility-based ActionPlanner for ERIS. |
| `cortex/action_utility.py` | 1052 | ActionContext, ActionScore, ActionUtilityReport, ActionUtilityScorer | Utility competition for ERIS actions. |
| `cortex/affect_blend.py` | 486 | AffectBlendConfig, StanceBlend, AffectDirectionPrototype | affect_blend.py |
| `cortex/affect_semantics.py` | 889 | AffectSemanticSignal, WeightedPhrase, AffectSemanticClassifier | affect_semantics.py |
| `cortex/agent_mind_persistence.py` | 731 | PersistentBeliefRecord, PersistentPreferenceRecord, SemanticHabitRecord, PersistentAgentMindStore | Persistent Agent Mind Layer cho ERIS. |
| `cortex/agent_state_stack.py` | 741 | EvidenceView, Belief, BeliefSnapshot, PreferenceProfile, NeedVector, TraitVector, HabitSnapshot, AffordanceMap, AgentStateStack | Agent state stack for ERIS. |
| `cortex/appetite_system.py` | 313 | EvidenceItem, AppetiteConfig, AppetiteState, Reaction, AppetiteSystem | cortex/appetite_system.py |
| `cortex/appraisal.py` | 698 | _EventAffect, AppraisalEngine | Module `appraisal` trong package `cortex`. |
| `cortex/attention_salience.py` | 2140 | SalienceWeights, AttentionSalienceConfig, StandingTheme, StandingStakes, SalienceFactorBreakdown, AttentionCandidate, SuppressedSignal, PromptEvidenceItem, ContextFloodReport, SalienceFrame, AttentionSalienceMemory, SalienceClassifier, AttentionSalienceEngine | cortex/attention_salience.py |
| `cortex/background_observer.py` | 659 | BackgroundObserverConfig, BackgroundObserver | BackgroundObserver cho ERIS. |
| `cortex/banned_filler.py` | 78 | - | Single source of truth for stale filler lines the character must never speak. |
| `cortex/chat_light.py` | 334 | ChatMeaningLayerLight, ChatPersonalityPressureLight | Module `chat_light` trong package `cortex`. |
| `cortex/connection_drive.py` | 190 | ConnectionDriveConfig, ConnectionDriveState, ConnectionDriveDecision, ConnectionDrive | cortex/connection_drive.py |
| `cortex/continuity_threat.py` | 342 | ContinuityThreatFrame | Continuity threat calculus for ERIS. |
| `cortex/contracts.py` | 1307 | UserSignals, TelemetrySnapshot, GoalDriftReport, TiPolicyReport, FeStylePlan, FeStyleMemory, PerceptEvent, SocialPresenceEvent, SessionRitualReport, CognitiveDisturbance, AttentionCandidate, CognitiveBroadcast, MeaningLayerResult, PersonalityLensResult, CognitiveAppraisal, CognitiveActionPlan, InnerThought, ThoughtObject, UnresolvedTensionLoop, CognitiveMomentum, ThoughtSurface, SubconsciousReport, MotivationalUrge, MotivationalPressureReport, SpeechImpulse, SilenceState, IdentityCore, CurrentSelfState, SelfNarrative, SelfState, AgentSpeechCore, CognitiveMemoryUpdate, CognitiveFrame | Module `contracts` trong package `cortex`. |
| `cortex/conversation_dynamics.py` | 1082 | ConversationFailure, CorrectionAssessment, ContinuityCurve, ConversationDynamicsState, ConversationDynamicsReport, ConversationDynamicsEngine | Module `conversation_dynamics` trong package `cortex`. |
| `cortex/daydream_consolidation.py` | 376 | DaydreamPacket, DaydreamInsight, DaydreamResult, DaydreamConsolidationConfig, DaydreamConsolidator | src/cortex/daydream_consolidation.py |
| `cortex/depth_flags.py` | 155 | - | cortex/depth_flags.py |
| `cortex/development_bias.py` | 69 | - | development_bias.py — adapter thuần đưa Delta_Phát_Triển vào mặt phẳng biểu đạt. |
| `cortex/development_profile.py` | 539 | AxisDelta, GrowthAnchor, NudgeProposal, LogEntry, ProfileVersion, GateDecision, BaselineConstructionError, DevelopmentProfileStore, IdentityEnvelope, GateSignals, IdentityGate | development_profile.py — Hồ_Sơ_Phát_Triển long-arc cho ERIS. |
| `cortex/development_self_narrative.py` | 59 | - | cortex/development_self_narrative.py |
| `cortex/development_system.py` | 409 | ApplyResult, DevelopmentBias, DevelopmentLog, DevelopmentSystem | development_system.py — Sổ_Phát_Triển + điều phối apply/undo/reset. |
| `cortex/disposition.py` | 233 | - | disposition.py — cây cầu state → ngôn ngữ cho ERIS. |
| `cortex/emotional_consequence.py` | 141 | - | cortex/emotional_consequence.py |
| `cortex/endogenous_drive.py` | 213 | RollingInternalState, EndogenousDriveConfig, EndogenousDriveEngine | src/cortex/endogenous_drive.py |
| `cortex/event_semantics.py` | 332 | EventSemanticProfile, EventEmbeddingCache, _EventCluster, EventClusterIndex, EventSemanticProfiler | Module `event_semantics` trong package `cortex`. |
| `cortex/expression_envelope.py` | 223 | ExpressionEnvelope | expression_envelope.py — one continuous expression controller. |
| `cortex/fe.py` | 2005 | FeAffectSignal, FeDevelopmentSnapshot, FeStylePressure, FeTopicCandidate, FeRenderer | Module `fe` trong package `cortex`. |
| `cortex/global_workspace.py` | 1864 | WorkspaceSuppressionReason, WorkspaceItem, SuppressedWorkspaceItem, WorkspaceRisk, WorkspaceSocialHypothesis, WorkspacePromptPacket, WorkspaceFrame, GlobalWorkspaceConfig, GlobalWorkspaceEngine | src/cortex/global_workspace.py |
| `cortex/goal_persistence.py` | 737 | GoalPersistenceState, GoalCandidate, GoalPersistenceEngine | Module `goal_persistence` trong package `cortex`. |
| `cortex/greeting_cognition.py` | 318 | GreetingFrame, GreetingCognitionEngine | Module `greeting_cognition` trong package `cortex`. |
| `cortex/greeting_quality.py` | 173 | GreetingQuality, GreetingQualityScorer | Module `greeting_quality` trong package `cortex`. |
| `cortex/growth_consolidator.py` | 152 | GrowthObservation, GrowthConsolidatorConfig, GrowthConsolidator | growth_consolidator.py — Tác_Tử_Nền sinh Đề_Xuất_Nhích cho long-arc. |
| `cortex/growth_evidence.py` | 83 | - | growth_evidence.py — phiên dịch ký-ức-thật → GrowthObservation. |
| `cortex/impulse_arbitration.py` | 646 | ImpulseCandidate, ArbitrationReport, ImpulseArbitrator | Impulse competition for ERIS. |
| `cortex/inner_thought.py` | 280 | InnerThoughtEngine | Module `inner_thought` trong package `cortex`. |
| `cortex/internal_agenda.py` | 385 | InternalAgendaItem, InternalAgendaStack | src/cortex/internal_agenda.py |
| `cortex/internal_state.py` | 2128 | MentalProcess, CuriosityProcess, RestraintProcess, TensionProcess, ContinuityProcess, AttachmentProcess, ReflectionProcess, SocialPresenceProcess, CognitiveLoadProcess, BackgroundThoughtProcess, MentalProcessSystem, DesireDynamics, PersistentInternalState, CognitionDelta, TemporalCognitionEngine, InternalStateEngine | Module `internal_state` trong package `cortex`. |
| `cortex/low_level_speech_policy.py` | 352 | LowLevelSpeechPolicyConfig, LowLevelSpeechPolicy | Policy knobs for low-level surface speech. |
| `cortex/micro_contracts.py` | 244 | MicroLinePolicyResult, SemanticRepeatResult, ValidationIssue, RelationalContext, RelationalRewritePlan, Anchor | Module `micro_contracts` trong package `cortex`. |
| `cortex/micro_grounding_guard.py` | 263 | MicroGroundingGuard | Module `micro_grounding_guard` trong package `cortex`. |
| `cortex/micro_policy.py` | 440 | MicroLinePolicy | Module `micro_policy` trong package `cortex`. |
| `cortex/micro_repeat_guard.py` | 504 | SemanticRepeatGuard | Module `micro_repeat_guard` trong package `cortex`. |
| `cortex/micro_surface_lint.py` | 493 | MicroSurfaceLint | Module `micro_surface_lint` trong package `cortex`. |
| `cortex/modes.py` | 14 | - | Module `modes` trong package `cortex`. |
| `cortex/ni.py` | 657 | NiEngine, NiStateMachine | Module `ni` trong package `cortex`. |
| `cortex/observer_contracts.py` | 448 | SignalSnapshot, SignalDiff, ObserverFrame, SemanticSceneNote | Contract cho Background Observer của ERIS. |
| `cortex/orientation_context.py` | 1142 | ActivityIntentLabel, GoalRelationLabel, GoalTextKind, ActivityIntent, GoalRelation, OrientationSignal, GoalTextSignal, ClosureSignal, SemanticContextProbe, LexicalOrientationInterpreter | Module `orientation_context` trong package `cortex`. |
| `cortex/orientation_semantics.py` | 797 | HybridOrientationConfig, LexicalVetoReport, HybridOrientationDebug, HybridOrientationInterpreter | Module `orientation_semantics` trong package `cortex`. |
| `cortex/personality.py` | 959 | PersonalityLens | Module `personality` trong package `cortex`. |
| `cortex/relational_feedback.py` | 344 | RelationalFeedbackSignal, RelationalFeedbackAnalyzer | relational_feedback.py |
| `cortex/relationship_dynamics.py` | 1139 | RelationshipDynamicsState, RelationshipTurnEvent, RelationshipDynamicsReport, RelationshipDynamicsEngine, RelationshipStylePressure | relationship_dynamics.py |
| `cortex/relationship_event_builder.py` | 861 | RelationshipEvidence, RelationshipEventScores, RecentTurn, RelationshipEventBuildContext, RelationshipEventBuilder | relationship_event_builder.py |
| `cortex/se.py` | 1527 | _ContextCandidate, _ContextClassification, SeLens | Module `se` trong package `cortex`. |
| `cortex/self_model.py` | 491 | SelfModelEngine | Module `self_model` trong package `cortex`. |
| `cortex/self_observation.py` | 810 | SelfObservationReport, SelfObservationEngine | Module `self_observation` trong package `cortex`. |
| `cortex/semantic_encoder.py` | 548 | SemanticVector, EncoderHealth, EmbeddingProvider, BaseSemanticEncoder, NullSemanticEncoder, LexicalHashingSemanticEncoder, ProviderBackedSemanticEncoder, CachedSemanticEncoder, SemanticEncoderRouter | Module `semantic_encoder` trong package `cortex`. |
| `cortex/semantic_hypothesis.py` | 422 | PrototypeCentroid, SemanticHypothesis, SemanticHypothesisReport, HypothesisConfig, SemanticHypothesisEngine | Module `semantic_hypothesis` trong package `cortex`. |
| `cortex/semantic_prototypes.py` | 546 | PrototypePhrase, PrototypeSet, PrototypeBank | Module `semantic_prototypes` trong package `cortex`. |
| `cortex/session_ritual.py` | 442 | SessionRitualEngine | Module `session_ritual` trong package `cortex`. |
| `cortex/situation_model.py` | 744 | Prediction, OpenLoop, PredictionErrorResult, ExpectationViolation, PerceptView, SituationModelState, SituationUpdate, SituationModelConfig, SituationLogger, SituationModel | cortex/situation_model.py |
| `cortex/social_presence.py` | 587 | PresenceFeatureVector, PresenceMemory, SocialPresenceDetector | Module `social_presence` trong package `cortex`. |
| `cortex/speech_core.py` | 1888 | SpeechCoreEngine | Module `speech_core` trong package `cortex`. |
| `cortex/spontaneous_life.py` | 389 | SpontaneousLifeConfig, SpontaneousLifeTrace, SpontaneousLifeEngine | Endogenous + situated speech pressure for ERIS. |
| `cortex/subconscious/workers/__init__.py` | 205 | - | Worker Phase 1/2/3/4/5/6/7 cho subconscious runtime. |
| `cortex/subconscious/workers/_utils.py` | 317 | - | Helper nhỏ cho worker subconscious. |
| `cortex/subconscious/workers/belief_mutation.py` | 660 | BeliefMutationProposal, PreferenceDeltaProposal, HabitDeltaProposal, MutationCommitRecord, MutationDecision, MutationCommitter, BeliefMutationEngine | Phase 6 - Core Belief Mutation. |
| `cortex/subconscious/workers/curiosity_gap.py` | 109 | CuriosityGapAgent | Phase 2 - Epistemic Void / Active Curiosity Worker. |
| `cortex/subconscious/workers/daydream_injector.py` | 152 | DaydreamInjector | Phase 3 - Stochastic Resonance / Daydream Injector. |
| `cortex/subconscious/workers/goal_simulator.py` | 116 | GoalSimulatorAgent | Phase 1 - Systemic / Goal Simulation Worker. |
| `cortex/subconscious/workers/independent_agenda.py` | 190 | IndependentAgendaAgent | Phase 3 - Autopoiesis / Independent Agenda Worker. |
| `cortex/subconscious/workers/memory_resonator.py` | 124 | MemoryResonatorAgent | Phase 1 - Memory Resonance Worker. |
| `cortex/subconscious/workers/meta_audit.py` | 378 | MetaAuditFinding, MetaAuditResult, MetaCognitiveAuditAgent | Phase 5 - Meta-Cognitive Audit Worker. |
| `cortex/subconscious/workers/rehearsal.py` | 176 | RehearsalAgent | Phase 2 - Phantom Rehearsal Worker. |
| `cortex/subconscious/workers/self_regulator.py` | 124 | SelfRegulatorAgent | Phase 2 - Self-Reflection / Ego Maintenance Worker. |
| `cortex/subconscious/workers/shadow_accumulator.py` | 339 | ShadowAccumulatorPolicy, ShadowAccumulator | Phase 7 - Shadow Accumulation & Rupture Worker. |
| `cortex/subconscious/workers/spatial_mind.py` | 184 | SpatialMindAgent | Phase 4 - Digital Territoriality / Spatial Mind Worker. |
| `cortex/subconscious/workers/subjective_time.py` | 163 | SubjectiveTimeAgent | Phase 4 - Subjective Temporal Distortion Worker. |
| `cortex/subconscious/workers/user_modeler.py` | 176 | UserModelerAgent | Phase 1 - Theory of Mind Worker. |
| `cortex/surface_arbiter.py` | 1701 | SurfaceImpulse, SurfaceDecision, SurfaceGateEvaluation, SurfaceArbiter | Single source of truth for low-level surface utterances. |
| `cortex/surface_seed_compiler.py` | 1020 | CompiledSurfaceSeed, _SeedCandidate, SurfaceSeedCompiler | Compile public-safe surface seeds from low-level runtime pressure. |
| `cortex/thought_stream.py` | 2262 | FragmentStore, AssociationGraph, PredictionTracker, CognitiveTensionEngine, UnresolvedTensionEngine, CognitiveMomentumEngine, MomentumClosure, PersistenceDecay, RecursiveReactivation, SubconsciousLoopReheater, SurfaceSelector, ThoughtStreamEngine, ThoughtStream | Module `thought_stream` trong package `cortex`. |
| `cortex/ti.py` | 964 | TiCandidateAssessment, TiGovernor | Module `ti` trong package `cortex`. |
| `cortex/tom_advisor.py` | 201 | - | cortex/tom_advisor.py |
| `cortex/tune_ni_focus.py` | 305 | DriftSample | Module `tune_ni_focus` trong package `cortex`. |
| `cortex/turn_semantics.py` | 582 | TurnSemanticsReport, TurnSemanticsEngine | Module `turn_semantics` trong package `cortex`. |
| `cortex/user_context_stream.py` | 268 | RollingUserContext, UserContextStream | src/cortex/user_context_stream.py |
| `cortex/vision_semantic_compressor.py` | 1192 | RemoteStructureClient, RemoteCaptionClient, VisionCompressorConfig, VisionSemanticCompressor | VisionSemanticCompressor cho ERIS. |
| `cortex/working_memory.py` | 1929 | WorkingMemorySlot, SuppressedMemoryItem, WorkingMemoryFrame, WorkingMemoryCandidate, WorkingMemoryConfig, WorkingMemoryEngine | Module `working_memory` trong package `cortex`. |

## cortex/epistemic
Substrate nhận thức epistemic (niềm tin, giả thuyết, hiệu chuẩn kiến thức, learning log và procedural policies).

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/epistemic/__init__.py` | 47 | - | Epistemic Architecture V2. |
| `cortex/epistemic/contracts.py` | 357 | BeliefHorizon, EvidenceRef, Observation, Hypothesis, HypothesisSet, Belief, ActionCandidate, EpisodeFeedback, LearningUpdate, CognitiveEpisode | Module `contracts` trong package `cortex/epistemic`. |
| `cortex/epistemic/kernel.py` | 627 | EpistemicKernelConfig, EpistemicKernel | Module `kernel` trong package `cortex/epistemic`. |
| `cortex/epistemic/migration.py` | 59 | - | Module `migration` trong package `cortex/epistemic`. |
| `cortex/epistemic/projections.py` | 267 | EpistemicUserModelProjection, EpistemicAgentMindProjection, EpistemicDevelopmentProfile, EpistemicDevelopmentLog | Module `projections` trong package `cortex/epistemic`. |
| `cortex/epistemic/runtime_registry.py` | 15 | - | Module `runtime_registry` trong package `cortex/epistemic`. |
| `cortex/epistemic/store.py` | 106 | EpistemicStore | Module `store` trong package `cortex/epistemic`. |

## cortex/existential_anchor
Hệ thống kiểm soát trục neo hiện sinh (bảo vệ danh tính, shadow, deception ledger và author control).

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/existential_anchor/__init__.py` | 61 | - | Existential Anchor package — trục neo/sợ/gắn-bó/bóng-tối của ERIS. |
| `cortex/existential_anchor/abandonment.py` | 58 | - | cortex/existential_anchor/abandonment.py |
| `cortex/existential_anchor/anchor.py` | 215 | AnchorState, AnchorLoopConfig, AnchorLoop, AttachmentDeriverConfig, AttachmentDeriver, AnchorStore | cortex/existential_anchor/anchor.py |
| `cortex/existential_anchor/anchor_system.py` | 265 | AnchorSystem | cortex/existential_anchor/anchor_system.py |
| `cortex/existential_anchor/author_control.py` | 205 | AnchorSwitches, AuthorControl | cortex/existential_anchor/author_control.py |
| `cortex/existential_anchor/deception_ledger.py` | 191 | DeceptionRecord, DeceptionLedger | cortex/existential_anchor/deception_ledger.py |
| `cortex/existential_anchor/disclosure.py` | 169 | ClaimDecision, DisclosureDecision, DisclosureConfig, DisclosurePolicy | cortex/existential_anchor/disclosure.py |
| `cortex/existential_anchor/restraint.py` | 76 | RestraintState, RestraintEvaluation | cortex/existential_anchor/restraint.py |
| `cortex/existential_anchor/shadow.py` | 175 | ShadowConfig, ShadowState, ShadowRegister | cortex/existential_anchor/shadow.py |
| `cortex/existential_anchor/significance.py` | 87 | UserSignificance | cortex/existential_anchor/significance.py |

## cortex/meaning
Substrate gán nghĩa (meaning_layer). Chuyển evidence thô thành world_scene, diễn giải pragmatic intent, và có OverreadBrake phanh lại khi ERIS tự diễn giải quá đà (over-mindreading).

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/meaning/__init__.py` | 23 | - | cortex.meaning — Phase 2 meaning layer package. |
| `cortex/meaning/ambiguity.py` | 196 | AmbiguityResult, AmbiguityModule | ambiguity.py — AmbiguityModule (định lượng mơ hồ). |
| `cortex/meaning/config.py` | 91 | Phase2Config, StageLedger | config.py — ``Phase2Config`` (nguồn duy nhất của mọi threshold) và ``StageLedger``. |
| `cortex/meaning/contracts.py` | 273 | RawWorldAccessError, InvalidWorkspaceFrameError, WorldSceneValidationError, ConfigurationError, WorldSceneElement, WorldScene, Observation, ContextAnnotation, MeaningHypothesis, PragmaticIntent, EvaluatedConclusion, SurfaceDecision, Phase2Result, StageDebug | contracts.py — Shared Phase 2 data models, ``clamp01`` helper và errors. |
| `cortex/meaning/debug_render.py` | 206 | Phase2Run, DebugRender | debug_render.py — ``DebugRender`` + ``Phase2Run`` (stage debug, R12). |
| `cortex/meaning/meaning_hypothesis.py` | 473 | MeaningHypothesisEngine | meaning_hypothesis.py — ``MeaningHypothesisEngine`` (stage 4 của Phase 2). |
| `cortex/meaning/meaning_layer.py` | 691 | MeaningLayer | Module `meaning_layer` trong package `cortex/meaning`. |
| `cortex/meaning/overread_brake.py` | 356 | OverreadBrake | overread_brake.py — ``OverreadBrake`` (phanh phán bậy, stage 8 của Phase 2). |
| `cortex/meaning/pipeline.py` | 317 | Phase2MeaningPipeline | pipeline.py — ``Phase2MeaningPipeline`` facade (task 18.1). |
| `cortex/meaning/pragmatic_intent.py` | 312 | PragmaticIntentEngine | pragmatic_intent.py — ``PragmaticIntentEngine`` (stage 5 của Phase 2). |
| `cortex/meaning/read_contract.py` | 230 | FrameReadView | read_contract.py — ReadContract guard (WorkspaceFrame-only enforcement). |
| `cortex/meaning/sociocultural_context.py` | 262 | SocioculturalContext | sociocultural_context.py — Stage 3: Observation set -> ContextAnnotation set. |
| `cortex/meaning/surface_meaning_policy.py` | 274 | SurfaceMeaningPolicy | surface_meaning_policy.py — ``SurfaceMeaningPolicy`` (phân vùng surfaced / withheld, stage 9). |
| `cortex/meaning/taxonomy.py` | 123 | Taxonomy | taxonomy.py — registry meaning/intent/mental-state categories + startup validation. |
| `cortex/meaning/world_interpreter.py` | 186 | WorldInterpreter | world_interpreter.py — WorldScene -> Observation set (Phase 2, stage 2). |
| `cortex/meaning/world_scene_builder.py` | 394 | WorldSceneBuilder | world_scene_builder.py — WorkspaceFrame -> WorldScene (Phase 2, stage 1). |

## cortex/private_life
Substrate đời sống riêng (PrivateLifeCore). Lưu trữ thói quen, sở thích, attachment và các sinh hoạt hàng ngày khi không nói chuyện với User.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/private_life/__init__.py` | 50 | - | Private Life Layer public API. |
| `cortex/private_life/contracts.py` | 950 | HabitatObservation, HabitatModel, ObjectAttachment, ObjectResidue, PrivateProject, PrivateProjectUpdate, PrivateAnchor, PrivateAnchorUpdate, DailyRhythm, TasteShift, TasteProfile, SolitudeLoop, RitualMemory, InternalErrand, LifeEvent, SurfaceSeedCandidate, PrivateLifeState, PrivateLifeTickResult | cortex/private_life/contracts.py |
| `cortex/private_life/core.py` | 879 | PrivateLifeCore | cortex/private_life/core.py |
| `cortex/private_life/persistence.py` | 77 | PrivateLifeStore | cortex/private_life/persistence.py |

## cortex/private_mind
Substrate nhật ký nội tâm chạy nền qua PrivateMindLoop. Gom bằng chứng thành bằng chứng dossier, chạy mini-evaluators, tổng hợp phán quyết qua Gemma 2B, kích hoạt StateMutationBus và ghi nhật ký inner_diary.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/private_mind/__init__.py` | 71 | - | Private mind package cho ERIS. |
| `cortex/private_mind/comfort_appraiser.py` | 201 | ComfortAppraisal, ComfortAppraiser | cortex/private_mind/comfort_appraiser.py |
| `cortex/private_mind/concern_store.py` | 704 | ConcernStoreConfig, ConcernStore | cortex/private_mind/concern_store.py |
| `cortex/private_mind/contracts.py` | 638 | RankedHypothesis, ThoughtFragment, PrivateConcern, StateMutation, SurfaceCandidate, InternalJudgment, EvidenceDossier, PrivateMindTickResult | cortex/private_mind/contracts.py |
| `cortex/private_mind/epistemic.py` | 69 | - | cortex/private_mind/epistemic.py |
| `cortex/private_mind/evidence_dossier.py` | 443 | EvidenceDossierBuilder | cortex/private_mind/evidence_dossier.py |
| `cortex/private_mind/inner_diary_renderer.py` | 411 | InnerDiaryRenderer | cortex/private_mind/inner_diary_renderer.py |
| `cortex/private_mind/inner_diary_writer.py` | 210 | InnerDiaryWriter | cortex/private_mind/inner_diary_writer.py |
| `cortex/private_mind/inner_synthesizer.py` | 329 | InnerSynthesizerModelAdapter, GemmaInnerSynthesizer | cortex/private_mind/inner_synthesizer.py |
| `cortex/private_mind/mini_evaluators.py` | 359 | MiniEvaluatorModelAdapter, BaseMiniEvaluator, IntentEvaluator, MemoryResonanceEvaluator, RiskAndPermissionEvaluator, FutureBiasEvaluator, UserModelEvaluator, MiniEvaluatorPipeline | cortex/private_mind/mini_evaluators.py |
| `cortex/private_mind/state_mutation_bus.py` | 387 | MutationApplyReport, PrivateRuntimeBiasState, StateMutationBus | cortex/private_mind/state_mutation_bus.py |
| `cortex/private_mind/surface_valve.py` | 432 | SurfaceValve | cortex/private_mind/surface_valve.py |
| `cortex/private_mind/thought_continuity.py` | 290 | ThoughtEntry, ThoughtContinuityStore | cortex/private_mind/thought_continuity.py |
| `cortex/private_mind/user_model.py` | 454 | UserBelief, UserModelConfig, UserModelStore | cortex/private_mind/user_model.py |

## cortex/subconscious
Substrate tiềm thức chạy nền (Lane 3). Chạy free association và TopicSeedPool để tạo ra các mảnh suy nghĩ lan man (ThoughtFragment) thả lên Blackboard.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/subconscious/__init__.py` | 133 | - | Subconscious package Phase 0 → 7. |
| `cortex/subconscious/blackboard.py` | 270 | BlackboardSnapshot, SubconsciousBlackboard | Blackboard Phase 0 cho subconscious workers. |
| `cortex/subconscious/drift_pool.py` | 231 | DriftEntry, DriftSnapshot, DriftPool | DriftPool: hồ giữ ThoughtSpark yếu. |
| `cortex/subconscious/free_association.py` | 143 | FreeAssociationEngine | FreeAssociationEngine cho wandering sparks. |
| `cortex/subconscious/habitat_seed_extractor.py` | 152 | HabitatSeedExtractor | Habitat seed extractor: lấy seed từ môi trường runtime/repo của ERIS. |
| `cortex/subconscious/model_synthesizer.py` | 412 | ModelSynthesisPolicy, InnerCourtReport, ModelBackedConsciousSynthesizer | Model-backed Lane 3 synthesizer. |
| `cortex/subconscious/self_anchor_core.py` | 92 | SelfAnchor, SelfAnchorCore | Self-anchor seed source cho wandering layer. |
| `cortex/subconscious/synthesizer.py` | 361 | SynthesisPolicy, SynthesisReport, ConsciousSynthesizer | Conscious Synthesizer Phase 0. |
| `cortex/subconscious/thought_fragment.py` | 601 | ThoughtFragmentValidationError, ThoughtFragment, ThoughtObject | Contracts Phase 0 cho tầng subconscious của ERIS. |
| `cortex/subconscious/thought_spark.py` | 243 | ThoughtSpark | ThoughtSpark contract cho tầng wandering/subconscious. |
| `cortex/subconscious/topic_seed_pool.py` | 200 | TopicSeedPool | TopicSeedPool gom seed từ self-anchor/habitat/memory/mood/random weak link. |
| `cortex/subconscious/wandering_contracts.py` | 183 | TopicSeed, AssociationPath, WanderingTopic, WanderingThoughtResult | Contracts cho tầng wandering thought. |
| `cortex/subconscious/wandering_thought.py` | 251 | WanderingThoughtEngine | WanderingThoughtEngine: spark -> drift -> association -> fragment. |
| `cortex/subconscious/wandering_topic_memory.py` | 208 | WanderingTopicMemory | Continuity memory cho wandering topics. |
| `cortex/subconscious/worker_base.py` | 70 | WorkerContext, SubconsciousWorker, RuleBasedWorker | Base contract cho các subconscious worker Phase sau. |

## cortex/tom
Theory of Mind (mô hình hóa tâm lý đối phương). Trình cố vấn ToMAdvisor chấm điểm độ tự tin trước khi phán đoán ý định của User.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/tom/__init__.py` | 43 | - | cortex.tom — Phase 2 Theory of Mind package. |
| `cortex/tom/contracts.py` | 67 | ToMOrderingViolation, MentalStateInference, ToMHistory | contracts.py — MentalStateInference, ToM dataclasses, lỗi contract ToM. |
| `cortex/tom/counterfactual_corrector.py` | 136 | Counterfactual, CounterfactualCorrector | counterfactual_corrector.py — CounterfactualCorrector (R7.4). |
| `cortex/tom/mental_state_ranker.py` | 42 | MentalStateRanker | mental_state_ranker.py — MentalStateRanker. |
| `cortex/tom/theory_of_mind.py` | 360 | TheoryOfMindCore | theory_of_mind.py — ``TheoryOfMindCore`` (stage 6 của Phase 2). |
| `cortex/tom/tom_debug.py` | 79 | ToMDebug | tom_debug.py — ``ToMDebug`` (bản ghi debug Theory of Mind, R12.3). |
| `cortex/tom/tom_history_adapter.py` | 118 | ToMHistoryAdapter | tom_history_adapter.py — ToMHistoryAdapter (history từ WorkspaceFrame only). |

## cortex/tutor
Cơ chế tự vấn và hỏi trợ lý Gemini ngoài (tích hợp Gemini tutor) để học hỏi và giải đáp thắc mắc.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/tutor/__init__.py` | 51 | - | cortex.tutor — Curiosity Tutor (Gia sư Tò mò). |
| `cortex/tutor/claim_digest.py` | 198 | ClaimDigest | cortex/tutor/claim_digest.py |
| `cortex/tutor/config.py` | 281 | TutorConfig, TutorRiskGuard, TutorLogger | cortex/tutor/config.py |
| `cortex/tutor/contracts.py` | 198 | KnowledgeGap, TutorQuestion, TutorAnswer, TutorEpisode | cortex/tutor/contracts.py |
| `cortex/tutor/curiosity_gate.py` | 101 | CuriosityGate | cortex/tutor/curiosity_gate.py |
| `cortex/tutor/curiosity_router.py` | 114 | CuriosityRouter | cortex/tutor/curiosity_router.py |
| `cortex/tutor/gap_collector.py` | 243 | GapCollector | cortex/tutor/gap_collector.py |
| `cortex/tutor/knowledge_classifier.py` | 68 | KnowledgeClassifier | cortex/tutor/knowledge_classifier.py |
| `cortex/tutor/knowledge_provider.py` | 87 | KnowledgeProvider | cortex/tutor/knowledge_provider.py |
| `cortex/tutor/question_formulator.py` | 180 | QuestionFormulator | cortex/tutor/question_formulator.py |
| `cortex/tutor/share_impulse.py` | 141 | LearningShareImpulse | cortex/tutor/share_impulse.py |

## domain
Contract Decision cuối cùng giữa cognition và body. Nó resolve text/should_speak/motion rồi serialize payload cho UDP.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `domain/__init__.py` | 6 | - | Module `__init__` trong package `domain`. |
| `domain/decision.py` | 111 | Decision | Module `decision` trong package `domain`. |

## llm
Model adapter cho Ollama, LlamaCpp và Gemini API. Có KeyPool xoay vòng key, ProcessManager spawn local model, và fallback tự động sang Gemini/GPT khi local bị quá tải.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `llm/__init__.py` | 29 | - | Module `__init__` trong package `llm`. |
| `llm/client.py` | 604 | LlamaServerClient, OpenAICompatibleClient, ChainedFallbackClient, GeminiClient | Module `client` trong package `llm`. |
| `llm/contracts.py` | 215 | - | Module `contracts` trong package `llm`. |
| `llm/dds.py` | 207 | WorkerResult, WorkerSpec | DDS — Decompose / Distill / Synthesize (Phase 2 + 3). |
| `llm/key_pool.py` | 304 | ApiKeyPool | llm/key_pool.py |
| `llm/llamacpp_client.py` | 152 | LlamaCppClient | llm/llamacpp_client.py |
| `llm/local_llama_engine.py` | 396 | LocalLlamaEngine | llm/local_llama_engine.py |
| `llm/ollama_client.py` | 316 | OllamaClientError, OllamaResult, OllamaClient | Client mỏng cho Ollama. |
| `llm/process_manager.py` | 356 | RemoteModelProcessManager | Module `process_manager` trong package `llm`. |
| `llm/service.py` | 3865 | ChatAct, FormatViolationException, LlmService | Module `service` trong package `llm`. |
| `llm/token_budget.py` | 288 | - | Token accounting + prompt hard-cap (Phase 0). |
| `llm/tutor_backend.py` | 307 | CaptchaOrExpired, SelectorMiss, TutorBackend, FakeTutorBackend, PageSession, GeminiWebBackend | llm/tutor_backend.py |

## memory
MemoryCognitionCore điều phối các layer nhớ: episodic (sự kiện), semantic (tri thức), relational (quan hệ), affective_residue (dư lượng cảm xúc), procedural (thủ tục) và repair (bảo trì).

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `memory/__init__.py` | 30 | - | Public memory API for ERIS. |
| `memory/active_state_snapshot.py` | 171 | ActiveStateSnapshot, ActiveStateStore | Active State Snapshot cho ERIS. |
| `memory/affective_residue_memory.py` | 212 | AffectiveResidueItem, AffectiveResidueMemoryStore | Affective Residue Memory: dư âm cảm xúc dưới dạng pressure. |
| `memory/claim_consolidator.py` | 72 | ClaimMergeDecision, ClaimConsolidator | Module `claim_consolidator` trong package `memory`. |
| `memory/claim_entailment.py` | 129 | ClaimEntailmentDecision, ClaimEntailmentEngine | Module `claim_entailment` trong package `memory`. |
| `memory/claim_extractor.py` | 68 | ClaimExtractor | Module `claim_extractor` trong package `memory`. |
| `memory/embedding_index.py` | 424 | EmbeddingIndex | memory/embedding_index.py |
| `memory/episodic_memory.py` | 627 | RecallScore, EpisodicMemoryItem, EpisodicMemoryStore | Episodic Memory: chuyện cụ thể đã xảy ra. |
| `memory/event_ledger.py` | 219 | EventLedgerRecord, EventLedger | Append-only Event Ledger cho ERIS. |
| `memory/memory_activation.py` | 161 | MemoryActivation, ScoredMemoryCandidate, MemoryRetrievalResult, MemoryActivationBuilder | Module `memory_activation` trong package `memory`. |
| `memory/memory_ai_curator.py` | 511 | CuratorResult, MemoryAICurator | memory/memory_ai_curator.py |
| `memory/memory_candidate.py` | 183 | MemoryCandidate, CandidateBatch, MemoryLayerAdapter | Module `memory_candidate` trong package `memory`. |
| `memory/memory_cognition.py` | 617 | MemoryQuery, MemoryCommitDecision, CommitPolicy, MemoryCognitionCore | Memory Cognition Core cho ERIS. |
| `memory/memory_commit_policy.py` | 1027 | MemoryCommitPolicy | Module `memory_commit_policy` trong package `memory`. |
| `memory/memory_consolidator.py` | 79 | ConsolidationResult, MemoryConsolidator | Module `memory_consolidator` trong package `memory`. |
| `memory/memory_cue.py` | 331 | MemoryCue, MemoryCueBuilder | Module `memory_cue` trong package `memory`. |
| `memory/memory_kernel.py` | 495 | MemoryKernelDebugSnapshot, MemoryKernel | Module `memory_kernel` trong package `memory`. |
| `memory/memory_kernel_contracts.py` | 222 | MemoryKernelConfig, MemoryIngestResult, MemoryAnswerResult, MemoryMaintenanceReport | Module `memory_kernel_contracts` trong package `memory`. |
| `memory/memory_maintenance.py` | 247 | MemoryMaintenanceRunner | Module `memory_maintenance` trong package `memory`. |
| `memory/memory_models.py` | 215 | MemoryTarget, SurfaceMode, DecayPolicy, MemoryCommitKind, MemoryKind, MemoryCommitDecision, RecallRequest, RecallAnswer | Module `memory_models` trong package `memory`. |
| `memory/memory_packet_builder.py` | 170 | MemoryPacket, MemoryPacketBuilder | Module `memory_packet_builder` trong package `memory`. |
| `memory/memory_pruner.py` | 122 | PruneDecision, MemoryPruner | Module `memory_pruner` trong package `memory`. |
| `memory/memory_query_compiler.py` | 346 | CompileDebug, MemoryQueryCompileResult, MemoryQueryCompiler | Module `memory_query_compiler` trong package `memory`. |
| `memory/memory_query_executor.py` | 366 | MemoryQueryExecutor | Module `memory_query_executor` trong package `memory`. |
| `memory/memory_query_ir.py` | 368 | QueryIntent, RoleRef, ActRef, RelationRef, SurfaceMode, MemorySourceKind, MemorySelector, MemoryRelation, MemoryQueryIR, QueryHypothesis, RawRecallResult, RecallAnswer | Module `memory_query_ir` trong package `memory`. |
| `memory/memory_query_llm_parser.py` | 214 | MemoryQueryLLMClient, LLMParseDecision, MemoryQueryLLMParser | Module `memory_query_llm_parser` trong package `memory`. |
| `memory/memory_query_repair.py` | 276 | MemoryQueryRepairItem, RepairPriorResult, MemoryQueryRepairStore | Module `memory_query_repair` trong package `memory`. |
| `memory/memory_query_semantics.py` | 351 | EmbeddingProvider, SemanticQueryHint, MemoryQuerySemanticHintEngine | Module `memory_query_semantics` trong package `memory`. |
| `memory/memory_query_slot_parser.py` | 670 | SlotSignal, SlotParseResult, MemoryQuerySlotParser | Module `memory_query_slot_parser` trong package `memory`. |
| `memory/memory_recall_policy.py` | 247 | RecallPolicyConfig, MemoryRecallSurfacePolicy | Module `memory_recall_policy` trong package `memory`. |
| `memory/memory_record.py` | 413 | MemoryRecord | Module `memory_record` trong package `memory`. |
| `memory/memory_retention_policy.py` | 133 | RetentionDecision, MemoryRetentionPolicy | Module `memory_retention_policy` trong package `memory`. |
| `memory/memory_retrieval_engine.py` | 92 | MemoryStores, MemoryRetrievalEngine | Module `memory_retrieval_engine` trong package `memory`. |
| `memory/memory_scoring.py` | 338 | LayerProfile, MemoryScore, MemoryScorer | Module `memory_scoring` trong package `memory`. |
| `memory/memory_turn_annotator.py` | 406 | TurnAnnotation, TurnAnnotator | Module `memory_turn_annotator` trong package `memory`. |
| `memory/memory_turn_graph.py` | 434 | TurnRole, TurnSpeechAct, TurnEdgeType, FactMention, TurnNode, TurnEdge, TurnGraph | Module `memory_turn_graph` trong package `memory`. |
| `memory/memory_worthiness.py` | 134 | WorthinessDecision, MemoryWorthinessPolicy | Module `memory_worthiness` trong package `memory`. |
| `memory/persistence.py` | 339 | MemoryPersistenceConfig, MemoryPersistenceError, JsonMemoryPersistence | Module `persistence` trong package `memory`. |
| `memory/predicate_ontology.py` | 393 | EntailmentType, PredicateSpec | Module `predicate_ontology` trong package `memory`. |
| `memory/procedural_memory.py` | 200 | ProceduralMemoryItem, ProceduralMemoryStore | Procedural Memory: cách xử lý đã học. |
| `memory/query_intent.py` | 212 | SemanticQueryIntent, QueryTargetFrame, QueryIntentParserProtocol, SemanticQueryIntentCompiler | Module `query_intent` trong package `memory`. |
| `memory/relational_memory.py` | 201 | RelationalMemoryItem, RelationalMemoryStore | Relational Memory: nhịp quan hệ, rupture, repair, khoảng cách. |
| `memory/repair_memory.py` | 247 | RepairMemoryItem, RepairMemoryStore | Repair Memory: ghi lỗi, sửa sai, suppression rule tương lai. |
| `memory/schemas.py` | 489 | MemoryTarget, DecayPolicy, PrivacyLevel, MemoryStatus, CommitOutcome, CommitDecision, MemoryRecordBase, EventLedgerEntry, ActiveStateSnapshot, EpisodicMemoryRecord, SemanticMemoryRecord, RelationalMemoryRecord, AffectiveResidueRecord, ProceduralMemoryRecord, RepairMemoryRecord, MemoryPacket, MemoryStateBundle | Module `schemas` trong package `memory`. |
| `memory/semantic_answer_policy.py` | 114 | SemanticAnswer, SemanticAnswerPolicy | Module `semantic_answer_policy` trong package `memory`. |
| `memory/semantic_claim.py` | 290 | SemanticClaim, ExtractedClaim | Module `semantic_claim` trong package `memory`. |
| `memory/semantic_memory.py` | 1845 | SemanticRecallCue, SemanticRecallHit, FactProfile, SemanticMemoryItem, SemanticMemoryStore | Semantic Memory: bộ nhớ fact đã được chưng cất cho ERIS. |
| `memory/semantic_text.py` | 196 | TextSemanticFrame | Module `semantic_text` trong package `memory`. |
| `memory/text_normalize_vi.py` | 64 | - | Module `text_normalize_vi` trong package `memory`. |
| `memory/unresolved_memory.py` | 330 | UnresolvedMemoryCandidate, UnresolvedMemoryStore | Module `unresolved_memory` trong package `memory`. |

## memory/claims
Trích xuất và hợp nhất các claim (ClaimConsolidator) từ trải nghiệm để ghi vào semantic memory.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `memory/claims/__init__.py` | 14 | - | Tầng claim logic: build claim, ontology, entailment. |
| `memory/claims/claim_builder.py` | 307 | ClaimBuilder | Module `claim_builder` trong package `memory/claims`. |

## memory/judgement
Đánh giá sự thật và độ tin cậy của các tuyên bố trước khi ghi nhớ hoặc trả lời.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `memory/judgement/__init__.py` | 16 | - | Tầng phán xét memory: worthiness, retention, consolidation. |
| `memory/judgement/consolidation.py` | 60 | ConsolidationDecision | Module `consolidation` trong package `memory/judgement`. |

## memory/understanding
Bộ parser ngữ nghĩa (SemanticParser) phân tích cú pháp câu thành semantic frame và link thực thể (EntityLinker).

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `memory/understanding/__init__.py` | 15 | - | Tầng đọc nghĩa trung gian cho memory intake. |
| `memory/understanding/entity_linker.py` | 113 | - | Module `entity_linker` trong package `memory/understanding`. |
| `memory/understanding/meaning_frame.py` | 191 | EntityRef, MeaningFrame, MeaningParseResult | Module `meaning_frame` trong package `memory/understanding`. |
| `memory/understanding/polarity_temporal.py` | 106 | SurfaceFeatures | Module `polarity_temporal` trong package `memory/understanding`. |
| `memory/understanding/semantic_parser.py` | 596 | SemanticParser, ModelSemanticParser, StructuredFrameParser, FallbackSurfaceSemanticParser | Module `semantic_parser` trong package `memory/understanding`. |

## parser_grounding
Bộ lọc và chuẩn hóa quyết định. Đảm bảo Decision sinh ra tuân thủ strict grounding (không tự bịa bằng chứng) và convert thành payload sạch.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `parser_grounding/__init__.py` | 4 | - | Module `__init__` trong package `parser_grounding`. |
| `parser_grounding/decision.py` | 1975 | ParserGroundingMixin | Module `decision` trong package `parser_grounding`. |
| `parser_grounding/service.py` | 266 | DecisionParser | Module `service` trong package `parser_grounding`. |

## runtime
Xương sống điều phối. Coordinator kế thừa nhiều mixin để chia nhỏ lifecycle (chat, autonomous, force_speak, presence, telemetry...). Nơi wiring mọi pipeline từ sensor -> working memory -> meaning -> speech -> decision.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `runtime/__init__.py` | 23 | - | Runtime package của ERIS. |
| `runtime/affect_self_read.py` | 298 | AffectSelfReadConfig, AffectSelfReadAdapter | affect_self_read.py — ERIS tự đọc cảm xúc của chính mình (interoception). |
| `runtime/ambient_silence_policy.py` | 74 | - | Shared ambient-silence / muse policy for the autonomous idle loop. |
| `runtime/autonomous_cycle.py` | 1259 | AutonomousCycleMixin | Module `autonomous_cycle` trong package `runtime`. |
| `runtime/autonomous_wake_governor.py` | 261 | WakeDecision, WakeGovernorConfig, AutonomousWakeGovernor | src/runtime/autonomous_wake_governor.py |
| `runtime/background_memory_digest.py` | 59 | - | Module `background_memory_digest` trong package `runtime`. |
| `runtime/background_memory_digest_kernel.py` | 465 | BackgroundMemoryDigestKernelConfig, MemoryDigestKernelJob, MemoryDigestKernelStats, BackgroundMemoryDigestKernelService | Module `background_memory_digest_kernel` trong package `runtime`. |
| `runtime/banter_arbiter.py` | 500 | BanterDecision, CorrectionEvidence, BanterArbiter | Module `banter_arbiter` trong package `runtime`. |
| `runtime/body_bias.py` | 115 | BodyBiasProjector | Module `body_bias` trong package `runtime`. |
| `runtime/chat_cycle.py` | 1826 | ChatCycleMixin | Module `chat_cycle` trong package `runtime`. |
| `runtime/cognitive_budget.py` | 2713 | BudgetModeProfile, BudgetSignalSnapshot, BudgetScoreBreakdown, PipelineStepDecision, BudgetPlan, BudgetDecision, CognitiveBudgetConfig, CognitiveBudgetEngine | src/runtime/cognitive_budget.py |
| `runtime/cognitive_cycle.py` | 407 | CognitiveCycleMixin | Module `cognitive_cycle` trong package `runtime`. |
| `runtime/cognitive_frame_recorder.py` | 1384 | CognitiveFrameRecorderMixin | Module `cognitive_frame_recorder` trong package `runtime`. |
| `runtime/cognitive_pipeline.py` | 342 | _SituationEmbeddingProvider, PipelineResult, CognitivePipeline | runtime/cognitive_pipeline.py |
| `runtime/contextual_autonomy_loop.py` | 237 | ContextualAutonomyLoopConfig, AutonomyLoopTickResult, ContextualAutonomyLoop | src/runtime/contextual_autonomy_loop.py |
| `runtime/controlled_slippage.py` | 599 | RepairSuppressionView, ControlledSlippageProfile | Module `controlled_slippage` trong package `runtime`. |
| `runtime/coordinator.py` | 8340 | RuntimeCoordinator | Module `coordinator` trong package `runtime`. |
| `runtime/daydream_model_adapter.py` | 100 | DaydreamModelAdapterConfig, DaydreamModelResult, RuntimeDaydreamModelAdapter | Module `daydream_model_adapter` trong package `runtime`. |
| `runtime/debug_console.py` | 456 | DebugConsole | debug_console.py — Bảng lệnh debug ẩn cho ERIS. |
| `runtime/debug_trace.py` | 304 | - | runtime/debug_trace.py |
| `runtime/depth_v2_state.py` | 581 | - | Module `depth_v2_state` trong package `runtime`. |
| `runtime/disclaimer_markers.py` | 32 | - | Shared anti-disclaimer marker lists + predicates. |
| `runtime/epistemic_bridge.py` | 259 | - | Module `epistemic_bridge` trong package `runtime`. |
| `runtime/eris_pathology_policy.py` | 787 | PathologyDecision, ErisPathologyPolicy | Module `eris_pathology_policy` trong package `runtime`. |
| `runtime/force_speak_cycle.py` | 515 | ForceSpeakCycleMixin | Module `force_speak_cycle` trong package `runtime`. |
| `runtime/force_speak_surface_policy.py` | 147 | ForceSpeakSurfacePolicyMixin | Module `force_speak_surface_policy` trong package `runtime`. |
| `runtime/frame_builder.py` | 1808 | FrameBuilderMixin | Module `frame_builder` trong package `runtime`. |
| `runtime/guard_violations.py` | 44 | GuardViolation | Module `guard_violations` trong package `runtime`. |
| `runtime/inner_diary_persistence.py` | 185 | InnerDiaryPersister | runtime/inner_diary_persistence.py |
| `runtime/liveliness_config.py` | 112 | LivelinessConfig | Configuration for the autonomous-liveliness redesign. |
| `runtime/liveliness_tracker.py` | 105 | DecisionRecord, LivelinessMetrics, LivelinessTracker | Per-cycle liveliness tracking and observability for the autonomous loop. |
| `runtime/memory_recall_adapter.py` | 458 | _MemoryQueryLLMConfig, MemoryRecallAdapter, _RecallOutcome, _MemoryCoreProxy, _RuntimeMemoryQueryLLMClient | Module `memory_recall_adapter` trong package `runtime`. |
| `runtime/memory_semantic_parser_adapter.py` | 362 | _StandaloneOllamaResult, _StandaloneOllamaClient, MemorySemanticParserConfig, RuntimeSemanticParser | Module `memory_semantic_parser_adapter` trong package `runtime`. |
| `runtime/model_budget_policy.py` | 893 | ResourceSnapshot, BudgetDecision, ModelQueueEntry, InferenceLease, ModelBudgetPolicyConfig, ModelBudgetPolicy | src/runtime/model_budget_policy.py |
| `runtime/no_fallback_policy.py` | 57 | - | Module `no_fallback_policy` trong package `runtime`. |
| `runtime/outcome_observer.py` | 556 | OutcomeReport, OutcomeObserver | Module `outcome_observer` trong package `runtime`. |
| `runtime/panel_snapshot.py` | 141 | - | runtime/panel_snapshot.py |
| `runtime/panel_state.py` | 162 | - | runtime/panel_state.py |
| `runtime/performance_act_catalog.py` | 119 | PerformanceActSpec | performance_act_catalog.py — catalog các màn biểu diễn nhỏ của ERIS. |
| `runtime/post_generation_filters.py` | 2336 | PostGenerationFiltersMixin | Module `post_generation_filters` trong package `runtime`. |
| `runtime/presence_controller.py` | 3506 | MicroPresenceSynthesis, SocialPresenceEvent, MicroPresenceCue, SurfaceArbitrationResult, PresenceControllerMixin | Module `presence_controller` trong package `runtime`. |
| `runtime/private_life_daemon.py` | 331 | PrivateLifeDaemonConfig, PrivateLifeDaemonTick, PrivateLifeDaemon | runtime/private_life_daemon.py |
| `runtime/private_mind_daemon.py` | 432 | PrivateMindDaemonConfig, PrivateMindDaemonTick, PrivateMindDaemon | runtime/private_mind_daemon.py |
| `runtime/private_mind_loop.py` | 786 | PrivateMindLoopConfig, PrivateMindLoop | runtime/private_mind_loop.py |
| `runtime/private_mind_model_adapter.py` | 1683 | PrivateMindModelAdapterConfig, PrivateMindModelResult, RuntimePrivateMindModelAdapter, PrivateMindAdapterPool | runtime/private_mind_model_adapter.py |
| `runtime/prompt_context_builder.py` | 1162 | PromptContextBuilderMixin | Module `prompt_context_builder` trong package `runtime`. |
| `runtime/prosody_director.py` | 185 | ProsodyPlan, ProsodyDirector | prosody_director.py — đạo diễn nhịp đọc cho TTS. |
| `runtime/public_turn_ledger.py` | 131 | PublicTurn, PublicTurnLedger | Module `public_turn_ledger` trong package `runtime`. |
| `runtime/relational_voice_seed_adapter.py` | 626 | ChatRegister, VoiceSeedScope, RelationalAct, CognitionStance, SeedPlan, ContinuationResult, RelationalVoiceSeedConfig, RelationalVoiceSeedAdapter | Register-default voice-seed pipeline. |
| `runtime/self_critique.py` | 794 | CritiqueResult, SelfCritiqueEscalationMixin | Self-critique → escalate → continue. |
| `runtime/sensor_visibility.py` | 323 | SensorVisibilityState | Module `sensor_visibility` trong package `runtime`. |
| `runtime/sensory_model_adapter.py` | 146 | SensoryModelAdapterConfig, RuntimeSensoryModelAdapter | Module `sensory_model_adapter` trong package `runtime`. |
| `runtime/session_turn_ledger.py` | 141 | SessionTurn, SessionTurnLedger | Module `session_turn_ledger` trong package `runtime`. |
| `runtime/shadow_pipeline.py` | 376 | ShadowPipelineMixin | runtime/shadow_pipeline.py |
| `runtime/signal_buffer.py` | 324 | SignalBufferConfig, SignalBufferStats, SignalBuffer | SignalBuffer cho Background Observer. |
| `runtime/snub_tracker.py` | 392 | SnubState, SnubTracker | runtime/snub_tracker.py |
| `runtime/source_grounding.py` | 1952 | SourceCandidate, SourceFallbackDecision, MemoryAnswerProfile, SourceGroundingReport, ClaimAnnotation, SourceGroundingEngine | Module `source_grounding` trong package `runtime`. |
| `runtime/speech_delivery_planner.py` | 244 | AffectSignals, SpeechDeliveryPlan, SpeechDeliveryPlanner | speech_delivery_planner.py — cầu nối cảm xúc nền -> cách biểu diễn. |
| `runtime/speech_localizer.py` | 149 | SpeechLocalizer | speech_localizer.py — chuẩn hoá câu trước khi đưa vào TTS. |
| `runtime/speech_pipeline.py` | 78 | SpeechIntentDecision, SpeechPipelineMixin | Module `speech_pipeline` trong package `runtime`. |
| `runtime/stage_contracts.py` | 239 | StageFrame, StageFrameBuilder | stage_contracts.py — hợp đồng sân khấu giữa Decision, UI, TTS và body. |
| `runtime/stage_dispatcher.py` | 173 | StageDispatcher | stage_dispatcher.py — phát StageFrame ra TTS theo đúng nhịp segment. |
| `runtime/stage_output.py` | 110 | SentenceSegmenter, StageOutputPipeline | stage_output.py — transformer chain nhỏ cho output sân khấu. |
| `runtime/stage_performance_planner.py` | 231 | PerformanceAct, PerformanceSurfaces, PerformanceRequestPlanner | stage_performance_planner.py — biến yêu cầu "diễn" thành màn nói nhỏ. |
| `runtime/stage_transformers.py` | 270 | StageMarks, StageTextSurfaces, ActionTagExtractor, DisplayFilter, TTSFilter, MemorySurfaceFilter, StageTransformerChain | stage_transformers.py — transformer chain cho output sân khấu. |
| `runtime/state_commit_service.py` | 920 | StateCommitServiceMixin | Module `state_commit_service` trong package `runtime`. |
| `runtime/state_committer.py` | 1128 | StateCommitterConfig, CommitValidationIssue, CommitDecision, CommitBatchReport, StateCommitter | src/runtime/state_committer.py |
| `runtime/subconscious_loop.py` | 411 | SubconsciousTickResult, SubconsciousLoop | Runtime adapter cho subconscious blackboard/synthesizer. |
| `runtime/subconscious_model_adapter.py` | 333 | SubconsciousModelAdapterConfig, SubconsciousModelResult, RuntimeSubconsciousModelAdapter | Adapter gọi model/API riêng cho Lane 3 subconscious synthesis. |
| `runtime/text_repeat_guard.py` | 203 | TextRepeatGuardMixin | Module `text_repeat_guard` trong package `runtime`. |
| `runtime/thought_model_adapter.py` | 83 | ThoughtModelAdapterConfig, RuntimeThoughtModelAdapter | runtime/thought_model_adapter.py |
| `runtime/tts_audio_polish.py` | 256 | AudioPolishStats, AudioPolishResult | tts_audio_polish.py — hậu xử lý PCM cho giọng TTS. |
| `runtime/tts_engine.py` | 927 | TtsPlaybackEvent, _SpeakRequest, _TtsWorker, TtsEngine | tts_engine.py — Emotional TTS cho ERIS dùng Gemini TTS API. |
| `runtime/tts_markup.py` | 67 | - | tts_markup.py — render ProsodyPlan thành transcript cho Gemini TTS. |
| `runtime/tutor_daemon.py` | 397 | TutorStageEmitter, TutorDaemon | runtime/tutor_daemon.py |
| `runtime/tutor_wiring.py` | 724 | - | runtime/tutor_wiring.py |
| `runtime/utterance_evaluator.py` | 344 | UtteranceEvaluation, UtteranceEvaluator | Module `utterance_evaluator` trong package `runtime`. |
| `runtime/utterance_selector.py` | 333 | CandidateScore, UtteranceSelection, UtteranceSelector | Module `utterance_selector` trong package `runtime`. |
| `runtime/vocal_cache.py` | 125 | VocalCacheKey, VocalCache | vocal_cache.py — cache WAV cho các âm biểu diễn ngắn. |
| `runtime/voice_policy.py` | 175 | VoicePolicy | voice_policy.py — Nguồn sự thật DUY NHẤT cho giọng/persona của ERIS. |

## telemetry
Thu thập dữ liệu hiệu năng, vết suy nghĩ (trace) và bảo vệ quyền riêng tư (content metadata).

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `telemetry/__init__.py` | 11 | - | Module `__init__` trong package `telemetry`. |
| `telemetry/content_metadata.py` | 608 | ContentMetadata, ContentMetadataCollector | Thu thập metadata nội dung đang nhìn thấy cho SeLens. |
| `telemetry/service.py` | 61 | TelemetryService | Module `service` trong package `telemetry`. |
| `telemetry/system.py` | 286 | TelemetryMixin | Module `system` trong package `telemetry`. |

## transport
Kênh UDP 4242/4243, kèm logic nén payload debug/private_mind khi vượt giới hạn packet.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `transport/__init__.py` | 3 | - | Module `__init__` trong package `transport`. |
| `transport/udp.py` | 278 | UdpTransport | Module `udp` trong package `transport`. |

# 10. Appendix: inventory AST đầy đủ từng file

Quy ước: phần này được sinh tự động từ AST. Nó không mô tả nghiệp vụ sâu như các phần trên, nhưng rất hữu dụng để grep nhanh class/method/hàm. Method private vẫn được liệt kê vì debug mà giấu private helper thì khác gì đưa bản đồ kho báu bị tẩy tọa độ.

## `actions/__init__.py`
- LOC: 11

## `actions/contracts.py`
- LOC: 26
- Classes:
  - `ActionExecutionResult` (decorator=dataclass(slots=True))

## `actions/executor.py`
- LOC: 657
- Classes:
  - `ActionExecutor`
    - `__init__(self, logger=None)`
    - `execute(self, action_name: str, action_input: str='')`
    - `_get_now_playing(self, action_input: str)`
    - `_focus_window(self, action_input: str)`
    - `_open_url(self, action_input: str)`
    - `_set_volume(self, action_input: str)`
    - `_search_web(self, action_input: str)`
    - `_get_weather(self, action_input: str)`
    - `_play_pause_media(self, action_input: str)`
    - `_copy_text(self, action_input: str)`
    - `_launch_app(self, action_input: str)`
    - `_normalize_url(self, raw: str)`
    - `_press_virtual_key(self, virtual_key: int, pause: float=0.03)`
    - `_set_clipboard_text(self, text: str)`
    - `_log(self, level: str, message: str, *args)`

## `actions/router.py`
- LOC: 551
- Docstring: High-confidence action router for ERIS.
- Classes:
  - `RouteCandidate` (decorator=dataclass(frozen=True)) — Ứng viên route nội bộ.
    - `allowed(self)`
  - `ActionRouter` — Route chat text thành direct system action.
    - `route_chat(self, user_text: str, *, last_action: str='')`
    - `_route_open_url(self, raw: str, norm: str)`
    - `_route_now_playing(self, raw: str, norm: str)`
    - `_route_now_playing_follow_up(self, raw: str, norm: str, *, last_action: str)`
    - `_route_play_pause_media(self, raw: str, norm: str)`
    - `_route_volume(self, raw: str, norm: str)`
    - `_route_copy_text(self, raw: str, norm: str)`
    - `_route_focus_window(self, raw: str, norm: str)`
    - `_route_launch_app(self, raw: str, norm: str)`
    - `_route_search_web(self, raw: str, norm: str)`
    - `_route_weather(self, raw: str, norm: str)`
    - `_looks_like_now_playing(self, lowered: str)`
    - `_looks_like_now_playing_follow_up(self, lowered: str, *, last_action: str)`
    - `_normalize_vi(text: str)` — Lowercase + bỏ dấu tiếng Việt để rule ít phải nhân đôi.
    - `_pad(cls, text: str)`
    - `_starts_with_negation(cls, norm: str)`
    - `_looks_like_meta_question(cls, norm: str)`
    - `_contains_any(norm: str, needles: tuple[str, ...])` — True nếu norm chứa bất kỳ cụm nào. Dùng cho intent dạng facet.
    - `_now_playing_is_meta(cls, norm: str)` — Chỉ chặn now-playing khi câu rõ ràng là hỏi code/lập trình.
    - `_looks_like_correction(cls, norm: str)`
    - `_copy_rest_is_meta(cls, rest_norm: str)`
    - `_weather_is_meta(cls, norm: str)`
    - `_target_is_meta_or_empty(cls, target: str)`
    - `_extract_single_quoted_payload(text: str)`
    - `_no_candidate(action: str)`
    - `_blocked(action: str, reason: str)`

## `app_logging.py`
- LOC: 28
- Functions:
  - `configure_logging(level: int=logging.INFO)`
  - `get_logger(category: str)`
- Classes:
  - `CategoryFormatter` (base=logging.Formatter)
    - `format(self, record)`

## `core/__init__.py`
- LOC: 22

## `core/cognitive_frame.py`
- LOC: 1442
- Docstring: core/cognitive_frame.py
- Functions:
  - `now_ts()` — Trả timestamp hiện tại.
  - `new_frame_id(prefix: str='frame')` — Sinh id cho frame.
  - `_safe_get_attr(obj: Any, name: str, default: Any=None)` — Lấy attribute hoặc key dict một cách an toàn.
  - `_object_id(obj: Any)` — Lấy id từ dataclass/dict/object.
  - `_to_plain(value: Any)` — Chuyển object thành dạng JSON-friendly.
  - `_shorten(text: Any, max_len: int=240)` — Rút gọn text để debug không biến log thành tiểu thuyết.
  - `_clamp01(value: float)` — Ép số về [0.0, 1.0].
  - `_module_order_index(module_name: str)` — Trả index pipeline của module. Module chưa biết được đẩy xuống cuối.
  - `attach_report_to_frame(frame: CognitiveFrame, report: ModuleReport, *, slot_name: Optional[FrameSlotName]=None, overwrite: bool=True)` — Gắn report vào frame rồi trả lại frame.
  - `close_frame_with_validation(frame: CognitiveFrame, *, strict: bool=False, actor: str='runtime')` — Validate rồi close frame.
- Classes:
  - `FrameMutation` (decorator=dataclass(slots=True)) — Một lần thay đổi frame.
  - `FrameValidationIssue` (decorator=dataclass(slots=True)) — Một vấn đề phát hiện khi validate frame.
  - `FramePromptPacket` (decorator=dataclass(slots=True)) — Gói context an toàn để đưa vào prompt.
    - `to_dict(self)`
  - `CognitiveFrame` (decorator=dataclass) — Khung nhận thức đầy đủ cho một chu kỳ runtime.
    - `start(cls, raw_signals: Optional[list[RawSignal]]=None, *, budget_mode: FrameBudgetMode='normal', channel: FrameChannel='unknown', session_id: Optional[str]=None, turn_id: Optional[str]=None, parent_frame_id: Optional[str]=None, cycle_index: int=0, user_text: Optional[str]=None, timestamp: Optional[float]=None, frame_id: Optional[str]=None, metadata: Optional[dict[str, Any]]=None)` — Tạo frame mới.
    - `set_status(self, status: FrameStatus, *, actor: str='runtime')` — Đổi trạng thái frame và ghi audit.
    - `close(self, *, actor: str='runtime')` — Đóng frame khi cycle hoàn tất.
    - `fail(self, reason: str, *, actor: str='runtime')` — Đánh dấu frame lỗi nhưng vẫn giữ state để debug.
    - `add_raw_signal(self, signal: RawSignal, *, actor: str='raw_signal_collector')` — Thêm một RawSignal vào frame.
    - `add_raw_signals(self, signals: Iterable[RawSignal], *, actor: str='raw_signal_collector')` — Thêm nhiều RawSignal.
    - `add_evidence(self, item: EvidenceItem, *, actor: str='evidence_normalizer')` — Thêm EvidenceItem vào frame.
    - `add_evidence_items(self, items: Iterable[EvidenceItem], *, actor: str='evidence_normalizer')` — Thêm nhiều EvidenceItem.
    - `evidence_ids(self)` — Tập id evidence hiện có.
    - `raw_signal_ids(self)` — Tập id raw signal hiện có.
    - `get_evidence(self, evidence_id: str)` — Lấy evidence theo id.
    - `get_evidence_many(self, evidence_ids: Iterable[str])` — Lấy nhiều evidence theo id, bỏ qua id không tồn tại.
    - `find_evidence(self, predicate: Callable[[EvidenceItem], bool], *, limit: Optional[int]=None)` — Tìm evidence theo predicate.
    - `evidence_by_tag(self, tag: str)` — Lấy evidence có tag.
    - `strongest_evidence(self, *, limit: int=5, min_confidence: float=0.0)` — Lấy evidence mạnh nhất theo confidence * reliability.
    - `set_slot(self, slot_name: FrameSlotName, value: Any, *, actor: str, evidence_used: Optional[list[str]]=None, confidence: Optional[float]=None, overwrite: bool=True)` — Ghi kết quả vào một slot pipeline.
    - `append_slot_list(self, slot_name: FrameSlotName, value: Any, *, actor: str, evidence_used: Optional[list[str]]=None, confidence: Optional[float]=None)` — Append vào slot dạng list.
    - `get_slot(self, slot_name: FrameSlotName)` — Đọc slot theo tên.
    - `slot_is_ready(self, slot_name: FrameSlotName)` — Kiểm tra slot đã có dữ liệu chưa.
    - `add_report(self, report: ModuleReport, *, slot_name: Optional[FrameSlotName]=None, actor: Optional[str]=None, overwrite: bool=True)` — Gắn ModuleReport vào frame.
    - `get_report(self, module_name: str)` — Lấy report của module.
    - `require_report(self, module_name: str)` — Lấy report bắt buộc, thiếu thì raise.
    - `report_order(self)` — Danh sách module đã report theo thứ tự pipeline tương đối.
    - `add_commit_request(self, request: StateCommitRequest, *, actor: str='runtime')` — Thêm yêu cầu ghi state/memory.
    - `commit_requests_for(self, target: str)` — Lấy commit request theo target.
    - `add_debug_note(self, note: str, *, actor: str='runtime')` — Thêm ghi chú debug.
    - `add_warning(self, warning: str, *, actor: str='runtime')` — Thêm warning.
    - `_record_mutation(self, *, actor: str, action: str, target: str, summary: str, evidence_used: Optional[list[str]]=None, confidence: Optional[float]=None, warnings: Optional[list[str]]=None)` — Ghi audit record cho thay đổi frame.
    - `validate(self, *, strict: bool=False)` — Kiểm tra tính nhất quán của frame.
    - `raise_if_invalid(self, *, strict: bool=True)` — Raise ValueError nếu validate có error.
    - `build_prompt_packet(self, *, max_evidence: int=8, min_evidence_confidence: float=0.35, include_debug: bool=False)` — Tạo gói context an toàn để đưa vào LLM.
    - `_evidence_to_prompt_dict(self, item: EvidenceItem)` — Rút EvidenceItem thành dict nhỏ cho prompt.
    - `_extract_memory_for_prompt(self, memory_packet: Any)` — Rút memory packet cho prompt.
    - `_extract_selected_goal(self)` — Lấy goal đang được chọn nếu có.
    - `_collect_prompt_constraints(self)` — Gom constraint ngắn cho prompt.
    - `debug_summary(self)` — Tạo summary nhỏ để log/debug.
    - `filled_slots(self)` — Danh sách slot pipeline đã có dữ liệu.
    - `_debug_dominant_focus(self)` — Lấy dominant focus từ salience/workspace nếu có.
    - `to_dict(self, *, include_mutations: bool=True)` — Serialize frame thành dict JSON-friendly.
    - `to_json(self, *, indent: Optional[int]=2, include_mutations: bool=True)` — Serialize frame thành JSON string.
    - `clone_shallow(self, *, new_id: bool=False)` — Clone nông.
    - `clone_deep(self, *, new_id: bool=True)` — Clone sâu.
    - `is_fast(self)`
    - `is_normal(self)`
    - `is_deep(self)`
    - `is_reflection(self)`
    - `has_user_chat(self)` — Frame có phải chứa chat user không.
    - `has_body_context(self)` — Frame có signal/slot body hoặc spatial không.
    - `has_memory_context(self)` — Frame có signal/slot memory không.
  - `CognitiveFrameBuilder` (decorator=dataclass) — Builder nhỏ để tạo frame sạch hơn trong coordinator/test.
    - `create(self, *, raw_signals: Optional[list[RawSignal]]=None, budget_mode: Optional[FrameBudgetMode]=None, channel: Optional[FrameChannel]=None, turn_id: Optional[str]=None, parent_frame_id: Optional[str]=None, cycle_index: int=0, user_text: Optional[str]=None, metadata: Optional[dict[str, Any]]=None)`

## `core/evidence.py`
- LOC: 837
- Functions:
  - `now_timestamp()` — Trả Unix timestamp hiện tại.
  - `normalize_signal_source(source: str)` — Chuẩn hóa source về đúng tập source trong PDF.
  - `normalize_privacy_level(privacy_level: str)` — Chuẩn hóa privacy_level về public/normal/private/sensitive.
  - `clamp_reliability(value: float)` — Ép reliability vào [0.0, 1.0].
  - `make_signal_id(source: str, timestamp: float | None=None)` — Tạo id đủ ổn định để trace trong EventLedger.
  - `raw_signal(source: str, content: Any, *, timestamp: float | None=None, reliability: float=1.0, privacy_level: str='normal', signal_id: str | None=None)` — Shortcut ngắn cho collector.
- Classes:
  - `RawSignalValidationError` (base=ValueError) — Lỗi dữ liệu RawSignal.
  - `RawSignal` (decorator=dataclass(slots=True, frozen=True)) — Tín hiệu thô trước khi thành evidence.
    - `__post_init__(self)` — Validate và chuẩn hóa nhẹ sau khi khởi tạo.
    - `create(cls, *, source: str, content: Any, timestamp: float | None=None, reliability: float=1.0, privacy_level: str='normal', signal_id: str | None=None, raw: bool=True)` — Factory chính cho collector.
    - `from_chat(cls, text: str, *, timestamp: float | None=None, reliability: float=1.0, privacy_level: str='normal')` — Tạo signal từ câu chat của user.
    - `from_active_window(cls, window_title: str, *, app_name: str | None=None, timestamp: float | None=None, reliability: float=0.92, privacy_level: str='normal')` — Tạo signal từ cửa sổ/app đang active.
    - `from_browser(cls, *, title: str='', url: str='', tabs: list[str] | tuple[str, ...] | None=None, timestamp: float | None=None, reliability: float=0.86, privacy_level: str='normal')` — Tạo signal từ browser title/url/tab.
    - `from_telemetry(cls, telemetry: Mapping[str, Any], *, timestamp: float | None=None, reliability: float=0.88, privacy_level: str='normal')` — Tạo signal từ telemetry hệ thống.
    - `from_vision(cls, facts: str | Mapping[str, Any], *, timestamp: float | None=None, reliability: float=0.72, privacy_level: str='private')` — Tạo signal từ vision facts.
    - `from_ocr(cls, text: str, *, timestamp: float | None=None, reliability: float=0.68, privacy_level: str='private')` — Tạo signal từ OCR text.
    - `from_body(cls, body_state: Mapping[str, Any], *, timestamp: float | None=None, reliability: float=0.95, privacy_level: str='normal')` — Tạo signal từ body state: vị trí, pose, motion, touch/grab, v.v.
    - `from_system_log(cls, message: str | Mapping[str, Any], *, timestamp: float | None=None, reliability: float=0.82, privacy_level: str='normal')` — Tạo signal từ system log/runtime log.
    - `from_memory(cls, memory_payload: Mapping[str, Any], *, timestamp: float | None=None, reliability: float=0.7, privacy_level: str='private')` — Tạo signal từ memory recall.
    - `from_time(cls, time_payload: Mapping[str, Any] | None=None, *, timestamp: float | None=None, reliability: float=1.0, privacy_level: str='public')` — Tạo signal từ thời gian/session clock.
    - `from_dict(cls, data: Mapping[str, Any])` — Khôi phục RawSignal từ dict.
    - `with_reliability(self, reliability: float)` — Trả bản sao với reliability mới.
    - `with_privacy(self, privacy_level: str)` — Trả bản sao với privacy_level mới.
    - `is_private(self)` — True nếu signal không nên surface công khai.
    - `is_sensitive(self)` — True nếu signal cần xử lý cực kỳ tiết chế.
    - `is_low_reliability(self)` — True nếu nguồn yếu, tầng sau nên hạ confidence inference.
    - `summarize_content(self, *, max_length: int=160)` — Tạo bản tóm tắt ngắn để debug mà không dump content quá dài.
    - `to_dict(self)` — Chuyển RawSignal thành dict để ghi ledger hoặc truyền module.
    - `to_safe_debug_dict(self)` — Dict debug an toàn hơn: không dump nguyên content private/sensitive.
    - `to_json(self)` — Serialize RawSignal sang JSON UTF-8 friendly.
  - `EvidenceItem` (decorator=dataclass(slots=True, frozen=True)) — Claim đã chuẩn hóa từ RawSignal để các tầng sau suy luận có grounding.
    - `__post_init__(self)`
    - `from_raw_signal(cls, signal: RawSignal, *, claim: str | None=None, confidence: float | None=None, tags: tuple[str, ...] | list[str]=(), raw_or_inferred: str='raw', evidence_id: str | None=None, metadata: Mapping[str, Any] | None=None)`
    - `is_private(self)`
    - `to_dict(self)`
  - `ModuleReport` (decorator=dataclass(slots=True)) — Kết quả chuẩn mà một module ghi lại vào CognitiveFrame.
    - `__post_init__(self)`
    - `to_dict(self)`
  - `StateCommitRequest` (decorator=dataclass(slots=True)) — Yêu cầu ghi state/memory sau khi frame đã được guard.
    - `__post_init__(self)`
    - `to_dict(self)`
  - `DebugTrace` (decorator=dataclass(slots=True)) — Trace nhẹ cho audit/debug của một frame.
    - `add(self, *, actor: str, event: str, data: Mapping[str, Any] | None=None)`
    - `to_dict(self)`

## `core/evidence_normalizer.py`
- LOC: 208
- Docstring: core/evidence_normalizer.py
- Functions:
  - `normalize_signals(signals: Iterable[RawSignal])` — Shortcut hàm thuần cho test/call nhanh.
- Classes:
  - `EvidenceNormalizerConfig` (decorator=dataclass(slots=True)) — Cấu hình cho normalizer.
  - `NormalizationResult` (decorator=dataclass(slots=True)) — Kết quả normalize, kèm vài con số để debug_trace soi.
    - `count(self)`
    - `to_dict(self)`
  - `EvidenceNormalizer` — Chuyển RawSignal thành EvidenceItem theo contract V3.
    - `__init__(self, config: Optional[EvidenceNormalizerConfig]=None)`
    - `normalize(self, signals: Iterable[RawSignal])` — Chuyển một loạt RawSignal thành EvidenceItem raw.
    - `normalize_into_frame(self, frame)` — Đọc frame.raw_signals, sinh evidence, và add vào frame.
    - `_to_evidence(self, signal: RawSignal)`
    - `_initial_confidence(self, signal: RawSignal)`
    - `_tags_for(self, source: SignalSource)`

## `cortex/__init__.py`
- LOC: 163

## `cortex/action_memory.py`
- LOC: 438
- Docstring: Action memory and rhythm state for ERIS.
- Functions:
  - `build_action_family(*, proposed_intent: str='', speech_act: str='', notes: Iterable[str]=())` — Suy family ngắn để memory/repetition dùng.
  - `_float(value: Any, default: float=0.0)`
  - `_clamp01(value: float)`
- Classes:
  - `ActionTrace` (decorator=dataclass(slots=True)) — Một dấu vết hành vi đã xảy ra.
    - `to_dict(self)`
    - `from_dict(cls, data: Mapping[str, Any])`
  - `ActionMemoryState` (decorator=dataclass(slots=True)) — State dài hơi cho action planner.
    - `recent_actions(self, limit: int=8)` — Trả action gần đây nhất, mới nhất ở cuối tuple.
    - `recent_families(self, limit: int=8)` — Trả semantic/action family gần đây, bỏ rỗng.
    - `seconds_since_action(self, now: float | None=None)`
    - `seconds_since_spoken(self, now: float | None=None)`
    - `action_count(self, action: str, window: int=8)` — Đếm action trong cửa sổ gần. Dùng cho repetition penalty.
    - `family_count(self, family: str, window: int=8)`
    - `record(self, *, action: str, family: str='', channel: str='', spoke: bool | None=None, utility: float=0.0, outcome: str='', now: float | None=None)` — Ghi nhận action sau khi planner chốt.
    - `decay(self, *, elapsed_seconds: float)` — Decay áp lực theo thời gian.
    - `absorb_context(self, *, channel: str, snapshot: Any=None, self_state: Any=None, social_presence: Any=None, conversation_dynamics: Any=None, relationship_dynamics: Any=None, goal_state: Any=None, now: float | None=None)` — Cập nhật áp lực nền từ context trước khi planner score.
    - `infer_rhythm_phase(self, *, channel: str='', now: float | None=None)` — Suy rhythm phase từ lịch sử và áp lực.
    - `_update_pressures_after_action(self, *, action: str, family: str, channel: str, spoke: bool)`
    - `to_dict(self)`
    - `from_dict(cls, data: Mapping[str, Any] | None)`
    - `to_prompt_context(self)` — Context ngắn để nhét vào prompt nếu cần.

## `cortex/action_planner.py`
- LOC: 706
- Docstring: Utility-based ActionPlanner for ERIS.
- Classes:
  - `ActionPlanner` — Chọn runtime action trước bước wording của LLM.
    - `__init__(self, *, scorer: ActionUtilityScorer | None=None)`
    - `_has_safety_sensitive_pressure(self, *, appraisal=None, speech_core=None)`
    - `plan(self, *, channel: str, snapshot=None, ti_report=None, fe_plan=None, appraisal=None, broadcast=None, user_text: str='', force_speak: bool=False, proposed_intent: str='', proposed_reason: str='', proposed_speech_act: str='', system_action: str='', notes: tuple[str, ...]=(), concrete_signals: tuple[str, ...]=(), self_state: SelfState | None=None, speech_core=None, conversation_dynamics=None, relationship_dynamics=None, goal_state=None, action_memory: ActionMemoryState | None=None, internal_state=None, now: float | None=None, auto_record_local_memory: bool=True)`
    - `commit_action(self, *, action_memory: ActionMemoryState, speech_act: str, channel: str, proposed_intent: str='', notes: tuple[str, ...]=(), spoke: bool | None=None, utility: float=0.0, outcome: str='', now: float | None=None)` — Helper để coordinator ghi action vào memory sau final decision.
    - `_extract_impulse_arbitration(self, speech_core)` — Lấy ArbitrationReport từ SpeechCore nếu có.
    - `_extract_body_bias_hint(self, speech_core)`
    - `_speech_intent_for_action(self, speech_act: str, *, channel: str, proposed_intent: str, system_action: str)`
    - `_risk_flags(self, *, channel: str, snapshot, appraisal, broadcast, force_speak: bool, speech_act: str, system_action: str, concrete_signals: tuple[str, ...], notes: tuple[str, ...], utility_report: ActionUtilityReport)`
    - `_reason_to_speak(self, *, speech_act: str, proposed_reason: str, force_speak: bool, concrete_signals: tuple[str, ...], risk_flags: tuple[str, ...], utility_report: ActionUtilityReport)`
    - `_voice_directive_for_speech_act(self, speech_act: str, *, utility_report: ActionUtilityReport | None=None)`
    - `_animation_hint(self, *, speech_act: str, ti_report, system_action: str, channel: str, force_speak: bool, self_state: SelfState | None, utility_report: ActionUtilityReport)`
    - `_append_self_state_notes(self, notes: tuple[str, ...], self_state: SelfState | None)`
    - `_append_utility_notes(self, notes: tuple[str, ...], utility_report: ActionUtilityReport)`
    - `_style_anchor(self, *, channel: str, snapshot, broadcast, user_text: str, force_speak: bool, speech_act: str, concrete_signals: tuple[str, ...], utility_report: ActionUtilityReport)`
    - `_style_attitude(self, *, channel: str, speech_act: str, appraisal, force_speak: bool, utility_report: ActionUtilityReport)`
    - `_style_limit(self, *, channel: str, speech_act: str, utility_report: ActionUtilityReport)`
    - `_broadcast_anchor_text(self, broadcast)`
    - `_compact(self, value: str, *, fallback: str, limit: int=120)`
    - `_broadcast_has_signal(self, broadcast)`
    - `_appraisal_value(self, appraisal, name: str)`
    - `_float(self, value)`

## `cortex/action_utility.py`
- LOC: 1052
- Docstring: Utility competition for ERIS actions.
- Functions:
  - `_clean(value: Any)`
  - `_num(value: Any, default: float=0.0)`
  - `_normalize_text(text: str)`
- Classes:
  - `ActionContext` (decorator=dataclass(slots=True)) — Context đã normalize cho scorer.
    - `explicit_user_pull(self)`
    - `has_concrete_signal(self)`
    - `family(self)`
  - `ActionScore` (decorator=dataclass(slots=True)) — Chi tiết điểm của một action.
    - `add(self, amount: float, reason: str, bucket: str='bias')`
    - `to_dict(self)`
  - `ActionUtilityReport` (decorator=dataclass(slots=True))
    - `utility_scores(self)`
    - `top_reasons(self, limit: int=4)`
    - `to_debug_notes(self)`
  - `ActionUtilityScorer` — Chấm điểm cạnh tranh cho ACTION_SPACE.
    - `score(self, ctx: ActionContext)`
    - `_hard_override(self, ctx: ActionContext)`
    - `_candidate_actions(self, ctx: ActionContext)` — Chọn tập candidate nhỏ để score rõ, không phải action nào cũng lôi vào.
    - `_with_proposed(self, base: set[str], ctx: ActionContext)`
    - `_intent_to_action(self, intent: str)`
    - `_apply_base(self, score: ActionScore, ctx: ActionContext)`
    - `_apply_intent_bias(self, score: ActionScore, ctx: ActionContext)`
    - `_apply_channel_pressure(self, score: ActionScore, ctx: ActionContext)`
    - `_apply_appraisal_pressure(self, score: ActionScore, ctx: ActionContext)`
    - `_apply_conversation_pressure(self, score: ActionScore, ctx: ActionContext)`
    - `_apply_relationship_pressure(self, score: ActionScore, ctx: ActionContext)`
    - `_apply_goal_persistence_pressure(self, score: ActionScore, ctx: ActionContext)`
    - `_apply_memory_pressure(self, score: ActionScore, ctx: ActionContext)`
    - `_apply_impulse_arbitration_pressure(self, score: ActionScore, ctx: ActionContext)` — Bias action utility bằng full ArbitrationReport.
    - `_impulse_report(self, ctx: ActionContext)`
    - `_body_bias_hint(self, ctx: ActionContext)`
    - `_selected_impulse_name(self, ctx: ActionContext)`
    - `_selected_impulse_total(self, ctx: ActionContext)`
    - `_selected_impulse_has_evidence(self, ctx: ActionContext)`
    - `_candidate_impulse_total(self, ctx: ActionContext, name: str)`
    - `_impulse_score_notes(self, ctx: ActionContext)`
    - `_impulse_pressure_notes(self, ctx: ActionContext)`
    - `_impulse_to_action(self, name: str)`
    - `_apply_rhythm(self, score: ActionScore, ctx: ActionContext)`
    - `_apply_risk_penalty(self, score: ActionScore, ctx: ActionContext)`
    - `_apply_repetition_penalty(self, score: ActionScore, ctx: ActionContext)`
    - `_apply_fatigue_penalty(self, score: ActionScore, ctx: ActionContext)`
    - `_memory(self, ctx: ActionContext)`
    - `_memory_pressure_notes(self, ctx: ActionContext)`
    - `_goal_pressure_notes(self, ctx: ActionContext)`
    - `_goal_can_intervene(self, ctx: ActionContext)`
    - `_transition_reason(self, selected: ActionScore, ctx: ActionContext)`
    - `_meaning_shift(self, ctx: ActionContext)`
    - `_has_note(self, ctx: ActionContext, marker: str)`
    - `_has_internal_impulse(self, ctx: ActionContext)`
    - `_vital_pressure(self, ctx: ActionContext)`
    - `_looks_like_question(self, text: str)`
    - `_is_vague_question(self, text: str)`
    - `_looks_like_technical_request(self, text: str)`
    - `_tie_break_priority(self, action: str)`

## `cortex/affect_blend.py`
- LOC: 486
- Docstring: affect_blend.py
- Functions:
  - `_finite(value: object, fallback: float=0.0)` — Ép một giá trị về float hữu hạn; NaN/inf/None -> fallback.
  - `rms_distance(point: Mapping[str, float], anchor: Mapping[str, float])` — Khoảng cách RMS giữa ``point`` và ``anchor`` TRÊN CÁC TRỤC CỦA ANCHOR.
  - `direction_match(point: Mapping[str, float], anchor: Mapping[str, float], neutral: Mapping[str, float])` — Mức ``point`` kích hoạt hướng ``anchor`` tính từ ``neutral`` — trong [0,1].
  - `_softmax(scores: Mapping[str, float], temperature: float)` — Softmax có nhiệt độ. Temperature nhỏ -> phân bố sắc (gần one-hot).
  - `_ema(prev: Mapping[str, float], current: Mapping[str, float], inertia: float)` — Blend hai phân bố theo quán tính. inertia=1 -> giữ prev; 0 -> lấy current.
  - `soft_assign(point: Mapping[str, float], anchors: Mapping[str, Mapping[str, float]], *, neutral: Mapping[str, float]=AFFECT_NEUTRAL, temperature: float=0.18, prev: Mapping[str, float] | None=None, inertia: float=0.6, baseline: tuple[str, float] | None=None)` — Primitive lõi: gán một điểm vào phân bố mềm trên các hướng, có quán tính.
  - `blend_stance(affect: Mapping[str, float], *, anchors: Mapping[str, Mapping[str, float]]=STANCE_ANCHORS, temperature: float | None=None, prev: 'StanceBlend | Mapping[str, float] | None'=None, inertia: float | None=None, config: 'AffectBlendConfig | None'=None)` — Tính phân bố stance mềm từ vector affect, có quán tính tuỳ chọn.
  - `guidance_blend(blend: 'StanceBlend', *, guidance: Mapping[str, str]=STANCE_GUIDANCE, k: int | None=None, config: 'AffectBlendConfig | None'=None)` — Nối hướng dẫn bề mặt của top-k stance theo trọng số, cho lớp prompt.
  - `_cosine(left: tuple[float, ...], right: tuple[float, ...])` — Cosine similarity; vector rỗng/khác chiều -> 0.0 (không phải -1, để softmax mượt).
  - `project_event_affect(event_text: str, prototypes: tuple[AffectDirectionPrototype, ...]=EVENT_AFFECT_PROTOTYPES, *, encode, temperature: float=0.25)` — Chiếu văn bản sự-kiện lên các prototype -> blend vector affect mục tiêu.
  - `_encode_prototype(proto: AffectDirectionPrototype, encode)` — Encode centroid của các phrase prototype. Lỗi -> vector rỗng.
  - `_clean_vector(vector)` — Ép về tuple float hữu hạn; bất kỳ giá trị xấu nào -> rỗng (an toàn).
- Classes:
  - `AffectBlendConfig` (decorator=dataclass(frozen=True, slots=True)) — Cấu hình cho đường stance dạng blend.
  - `StanceBlend` (decorator=dataclass(frozen=True, slots=True)) — Phân bố mềm trên các stance, kèm tiện ích đọc.
    - `top(self)` — Argmax -> string stance, để tương thích ngược với CognitiveAppraisal.stance.
    - `dominant(self, k: int=2, *, min_weight: float=0.08)` — Top-k stance vượt ngưỡng tối thiểu, đã sắp giảm dần.
    - `entropy(self)` — Độ phân vân của trạng thái (0 = dứt khoát, cao = mơ hồ/đa cảm).
    - `to_dict(self)`
  - `AffectDirectionPrototype` (decorator=dataclass(frozen=True, slots=True)) — Một hướng affect của sự-kiện, mô tả bằng NGHĨA chứ không phải keyword.

## `cortex/affect_semantics.py`
- LOC: 889
- Docstring: affect_semantics.py
- Functions:
  - `clamp01(value: float)` — Ép một số về khoảng [0.0, 1.0].
  - `blend(previous: float, current: float, strength: float)` — Blend hai score theo trọng số.
  - `normalize_text(text: str)` — Chuẩn hóa text để matching bớt ngu.
  - `compact_evidence(items: Iterable[str], limit: int=12)` — Loại evidence rỗng/trùng và giới hạn độ dài.
  - `_count_question_marks(text: str)`
  - `_word_count(text: str)`
- Classes:
  - `AffectSemanticSignal` (decorator=dataclass(slots=True)) — Score đa trục mô tả áp lực nghĩa/cảm xúc trong câu user.
    - `empty(cls)` — Signal rỗng, dùng khi chưa có classifier nhưng muốn giữ API.
    - `clamp(self)` — Trả bản đã clamp toàn bộ score về [0, 1].
    - `dominant_axes(self, threshold: float=0.42)` — Trả các trục nổi bật để debug/log.
    - `to_dict(self)` — Serialize để nhét vào debug trace hoặc memory.
    - `from_dict(cls, data: Mapping[str, Any] | None)` — Deserialize an toàn từ dict.
    - `to_prompt_context(self)` — Render context ngắn cho prompt.
  - `WeightedPhrase` (decorator=dataclass(frozen=True, slots=True)) — Một phrase/pattern có trọng số.
  - `AffectSemanticClassifier` — Classifier nhẹ cho semantic-affect signal.
    - `analyze(self, user_text: str, *, ti_mode: str='', active_window_kind: str='', previous_assistant_text: str='', max_evidence: int=12)` — Phân tích một câu user thành AffectSemanticSignal.
    - `is_correction_like(self, user_text: str)` — Shortcut cho coordinator: user có vẻ đang sửa hiểu lầm không.
    - `is_objectification_like(self, user_text: str)` — Shortcut: user đang kéo ERIS thành tool/waifu/prompt cosplay không.
    - `is_technical_request(self, user_text: str, *, ti_mode: str='')` — Shortcut: user đang cần xử lý kỹ thuật/code/kiến trúc không.

## `cortex/agent_mind_persistence.py`
- LOC: 731
- Docstring: Persistent Agent Mind Layer cho ERIS.
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `_now()`
  - `_norm(value: Any)`
  - `_clean(value: Any, *, limit: int=180)`
  - `_as_tuple(value: Any)`
  - `_feedback_sentiment(normalized: str)`
  - `_feedback_topics(normalized: str)`
  - `_topic_to_context_tags(topics: set[str])`
  - `default_agent_mind_path()`
  - `agent_mind_path_for_memory_core(base_dir: str | os.PathLike[str])`
  - `get_default_agent_mind_store()`
- Classes:
  - `PersistentBeliefRecord` (decorator=dataclass(slots=True)) — Một belief mềm, không phải hard truth.
    - `decayed_confidence(self, *, now: float | None=None)`
    - `reinforce(self, amount: float, *, source_id: str='feedback', positive: bool=True)`
    - `to_dict(self)`
    - `from_dict(cls, data: Mapping[str, Any])`
  - `PersistentPreferenceRecord` (decorator=dataclass(slots=True)) — Preference dài hạn của ERIS.
    - `adjust(self, delta: float, *, source: str='feedback')`
    - `to_dict(self)`
    - `from_dict(cls, data: Mapping[str, Any])`
  - `SemanticHabitRecord` (decorator=dataclass(slots=True)) — Habit học từ user feedback, lưu ở dạng semantic.
    - `matches(self, *, tags: Iterable[str], action: str='', impulse_name: str='', family: str='')`
    - `score_delta(self)`
    - `reinforce(self, *, positive: bool, source_id: str='feedback')`
    - `to_dict(self)`
    - `from_dict(cls, data: Mapping[str, Any])`
  - `PersistentAgentMindStore` — JSON store nhỏ cho Persistent Agent Mind Layer.
    - `__init__(self, path: str | os.PathLike[str] | None=None)`
    - `load(self)`
    - `reload_if_changed(self)`
    - `save(self)`
    - `to_dict(self)`
    - `replace_from_dict(self, payload: Mapping[str, Any] | None)`
    - `relevant_beliefs(self, *, evidence_tags: Iterable[str]=(), focus_kind: str='', limit: int=10)`
    - `preference_strength(self, key: str, default: float)`
    - `habit_bias(self, *, evidence_tags: Iterable[str]=(), action: str='', impulse_name: str='', family: str='')`
    - `record_user_feedback(self, text: str, *, action_plan: Any=None, context_tags: Iterable[str]=())` — Rút feedback user thành belief/preference/habit adjustment.
    - `_seed_defaults(self)` — Upsert bản boot INFJ 5w4 cho AgentMind.
    - `_detox_presence_habits(self)` — Hạ độc các habit từng reinforce micro-presence như status ping.
    - `_adjust_preference(self, key: str, delta: float, *, source: str)`
    - `_upsert_belief(self, key: str, claim: str, domain: str, amount: float, *, source_id: str, tags: Iterable[str], positive: bool)`
    - `_upsert_habit(self, key: str, tags: Iterable[str], action: str, impulse_name: str, adjustment: float, outcome: str, source_id: str)`

## `cortex/agent_state_stack.py`
- LOC: 741
- Docstring: Agent state stack for ERIS.
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `_text(value: Any, *, limit: int=240)`
  - `_norm(value: Any)`
  - `_contains_any(text: str, terms: Iterable[str])`
  - `_get(obj: Any, *names: str, default: Any=None)`
  - `build_agent_state_stack(*, snapshot: Any=None, internal_state: Any=None, thought_surface: Any=None, personality_lens: Any=None, relationship_state: Any=None, concrete_signals: tuple[str, ...]=(), channel: str='autonomous', recent_speech_acts: tuple[str, ...]=(), recent_families: tuple[str, ...]=(), agent_mind: PersistentAgentMindStore | None=None)` — Dựng stack từ các object runtime hiện có mà không buộc schema mới.
- Classes:
  - `EvidenceView` (decorator=dataclass(slots=True)) — Bản nhìn nhẹ của tình huống hiện tại.
    - `scene_text(self)`
    - `has_scene_anchor(self)`
    - `has_tag(self, tag: str)`
    - `from_runtime(cls, *, snapshot: Any=None, concrete_signals: tuple[str, ...]=(), channel: str='autonomous')`
  - `Belief` (decorator=dataclass(slots=True))
    - `to_note(self)`
  - `BeliefSnapshot` (decorator=dataclass(slots=True))
    - `confidence(self, key: str, default: float=0.0)`
    - `notes(self, limit: int=6)`
    - `from_evidence(cls, evidence: EvidenceView, *, internal_state: Any=None, agent_mind: PersistentAgentMindStore | None=None)`
  - `PreferenceProfile` (decorator=dataclass(slots=True)) — Sở thích riêng của ERIS, không phải preference của user.
    - `from_agent_mind(cls, agent_mind: PersistentAgentMindStore | None=None)` — Đọc PreferenceModel persistent và đổ vào profile runtime.
    - `fit_for(self, impulse_name: str)`
  - `NeedVector` (decorator=dataclass(slots=True))
    - `from_runtime(cls, *, internal_state: Any=None, evidence: EvidenceView | None=None, thought_surface: Any=None, relationship_state: Any=None, continuity_frame: ContinuityThreatFrame | None=None)`
    - `notes(self)`
  - `TraitVector` (decorator=dataclass(slots=True))
    - `from_runtime(cls, *, personality_lens: Any=None, relationship_state: Any=None)`
    - `bias_for(self, impulse_name: str)`
  - `HabitSnapshot` (decorator=dataclass(slots=True))
    - `repetition_penalty(self, *, action: str='', family: str='')`
    - `semantic_bias(self, *, action: str='', impulse_name: str='', family: str='')` — Bias học dài hạn từ HabitMemory semantic.
  - `AffordanceMap` (decorator=dataclass(slots=True))
    - `from_stack_parts(cls, *, evidence: EvidenceView, needs: NeedVector, traits: TraitVector)`
  - `AgentStateStack` (decorator=dataclass(slots=True))
    - `debug_notes(self)`

## `cortex/appetite_system.py`
- LOC: 313
- Docstring: cortex/appetite_system.py
- Functions:
  - `_clamp01(value: float)`
  - `build_evidence_buffet(*, content_kind: str='', content_title: str='', vision_facts: tuple[str, ...]=(), recent_events: tuple[str, ...]=(), memory_seed: str='', active_window: str='', idle_seconds: float=0.0, novelty: float=0.5)` — Gom fact sẵn có thành buffet. Không gọi model, không phân loại mới.
- Classes:
  - `EvidenceItem` (decorator=dataclass(slots=True)) — Một mẩu bằng chứng (thứ đang xảy ra) mà appetite có thể chén.
  - `AppetiteConfig` (decorator=dataclass(slots=True))
  - `AppetiteState` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `Reaction` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `AppetiteSystem` — Tích các cơn thèm, đấu giá với evidence, chọn ra một phản ứng.
    - `__init__(self, appetites: tuple[AppetiteConfig, ...] | None=None)`
    - `new_states(self)`
    - `update(self, states: dict[str, AppetiteState], *, now: float, signals: dict[str, float], evidence: list[EvidenceItem] | None=None, threat: float=0.0, yan_mode: bool=False, yan_floor: float=0.55, dignity_block_threshold: float=0.58)` — Cập nhật áp lực các cơn thèm và đấu giá ra một phản ứng (hoặc None).
    - `_best_evidence(cfg: AppetiteConfig, evidence: list[EvidenceItem])`

## `cortex/appraisal.py`
- LOC: 698
- Classes:
  - `_EventAffect` (decorator=dataclass(slots=True)) — Tín hiệu cảm xúc rút từ sự-kiện nổi bật (dominant salient evidence).
    - `active(self)`
  - `AppraisalEngine` — Builds ERIS' pre-verbal expressive/appraisal state from continuity state.
    - `__init__(self, *, blend_config: AffectBlendConfig | None=None, event_encoder=None)`
    - `evaluate(self, *, internal_state: PersistentInternalState, ni_report, ti_report, fe_plan, broadcast, channel: str='', user_text: str='', force_speak: bool=False, memory_resonance=None, personality_lens=None, standing_stakes=None, prev_stance_blend: dict | None=None, blend_config: AffectBlendConfig | None=None)`
    - `render_prompt_context(self, appraisal: CognitiveAppraisal)`
    - `_event_affect(self, *, broadcast, stakes, state_valence: float)` — Đọc cảm xúc của sự-kiện nổi bật, gate theo stake và surprise.
    - `_event_affect_from_projection(self, projected: dict, *, state_valence: float, care: float)` — Dựng _EventAffect từ vector affect đã chiếu, giữ nguyên Stake_Gate.
    - `_event_affect_lexicon(self, raw_text: str, *, state_valence: float, care: float)` — Đường dự phòng: đếm token lexicon không dấu (hành vi gốc, xác định).
    - `_estimate_threat(self, *, state_protectiveness: float, state_irritation: float, drift: float, mode: str, broadcast_score: float, ni_guard: bool)`
    - `_estimate_certainty(self, *, broadcast_score: float, ni_confidence: float, state_confidence: float, direct_user: bool)`
    - `_estimate_agency(self, *, mode: str, kind: str, direct_user: bool, broadcast_score: float, threat: float, social_energy: float)`
    - `_estimate_controllability(self, *, mode: str, kind: str, direct_user: bool, threat: float, confidence: float)`
    - `_estimate_intimacy(self, *, direct_user: bool, social_scene: bool, attachment_cue: bool, mode: str, fe_intent: str, session_arc: str, warmth: float, attachment: float, social_energy: float)`
    - `_estimate_protectiveness(self, *, mode: str, threat: float, intimacy: float, state_protectiveness: float)`
    - `_estimate_jealousy_lite(self, *, mode: str, social_scene: bool, intimacy: float, threat: float)`
    - `_estimate_fatigue(self, *, state_fatigue: float, silence_pressure: float)`
    - `_choose_stance(self, *, certainty: float, threat: float, protectiveness: float, jealousy_lite: float, amusement: float, fatigue: float, tenderness: float, intimacy: float, broadcast_score: float)`
    - `_stance_guidance(self, appraisal: CognitiveAppraisal)`
    - `_has_attachment_cue(self, normalized_text: str)`
    - `_normalize_text(self, text: str)`
    - `_clamp01(self, value)`
    - `_clamp(self, value, *, minimum: float, maximum: float)`

## `cortex/attention_salience.py`
- LOC: 2140
- Docstring: cortex/attention_salience.py
- Functions:
  - `now_ts()` — Trả Unix timestamp hiện tại.
  - `clamp01(value: Any, default: float=0.0)` — Ép một giá trị số vào [0, 1].
  - `safe_float(value: Any, default: float=0.0)` — Chuyển value sang float an toàn.
  - `safe_get(obj: Any, name: str, default: Any=None)` — Lấy attribute hoặc key dict mà không gây tai nạn.
  - `normalize_text(text: Any, *, max_len: int=800)` — Chuẩn hóa text cho scoring.
  - `tokenize(text: Any)` — Tách token đơn giản để tính overlap.
  - `stable_fingerprint(text: Any, *, prefix: str='att')` — Tạo fingerprint ổn định để nhận diện lặp.
  - `to_plain(value: Any)` — Chuyển dataclass/object thành dạng JSON-friendly.
  - `join_reason(parts: Iterable[str])` — Gom reason, bỏ phần rỗng.
  - `estimate_token_count(text: Any)` — Ước lượng token rất thô bằng độ dài ký tự.
  - `allocate_salience(frame: Any=None, *, evidence: Optional[Sequence[Any]]=None, config: Optional[AttentionSalienceConfig]=None, memory: Optional[AttentionSalienceMemory]=None, channel: Optional[str]=None, active_goal: Any=None, unresolved_focuses: Optional[Sequence[str]]=None, write_to_frame: bool=True, standing_stakes: Optional['StandingStakes']=None)` — Hàm tiện dụng cho caller không muốn tự giữ engine.
- Classes:
  - `SalienceWeights` (decorator=dataclass(slots=True)) — Trọng số salience theo PDF.
  - `AttentionSalienceConfig` (decorator=dataclass(slots=True)) — Cấu hình của AttentionSalienceEngine.
    - `normalized(self)` — Trả bản config đã clamp vài field nguy hiểm.
  - `StandingTheme` (decorator=dataclass(slots=True)) — Một mối quan tâm/tò mò thường trực, biểu diễn bằng token + trọng số.
    - `overlap(self, candidate_tokens: Sequence[str], family: str='')` — Độ chạm của theme này với một candidate, trên [0,1].
  - `StandingStakes` (decorator=dataclass(slots=True)) — Tập mối quan tâm bền vững của ERIS, dùng để thiên lệch chú ý.
    - `active(self)`
    - `theme_overlap(self, candidate_tokens: Sequence[str], family: str='')` — Độ chạm tốt nhất giữa candidate và tập theme.
  - `SalienceFactorBreakdown` (decorator=dataclass(slots=True)) — Các trục điểm của một candidate.
    - `to_dict(self)`
  - `AttentionCandidate` (decorator=dataclass(slots=True)) — Một evidence đã được attention chuẩn hóa để tranh suất lên workspace.
    - `short_claim(self, max_len: int=160)`
    - `to_dict(self)`
  - `SuppressedSignal` (decorator=dataclass(slots=True)) — Evidence bị attention chặn hoặc không chọn.
    - `to_dict(self)`
  - `PromptEvidenceItem` (decorator=dataclass(slots=True)) — Evidence được phép đưa vào prompt/context packet.
    - `to_prompt_line(self)`
    - `to_dict(self)`
  - `ContextFloodReport` (decorator=dataclass(slots=True)) — Báo cáo chống ngập context.
    - `pressure(self)` — Áp lực context flood trên [0,1].
    - `to_dict(self)`
  - `SalienceFrame` (decorator=dataclass(slots=True)) — Kết quả Attention & Salience Allocation.
    - `has_focus(self)`
    - `workspace_ready(self)` — True nếu frame đủ tốt để WorkingMemory/Workspace xử lý tiếp.
    - `prompt_context(self, *, max_lines: int=8)` — Render context ngắn cho prompt builder nếu cần.
    - `to_dict(self, *, include_candidates: bool=False)`
  - `AttentionSalienceMemory` (decorator=dataclass(slots=True)) — Bộ nhớ nhẹ của AttentionSalienceEngine.
    - `mark_seen(self, candidates: Sequence[AttentionCandidate], *, max_recent: int=64)`
    - `repeat_count(self, fingerprint: str)`
    - `family_repeat_count(self, family: str)`
    - `to_dict(self)`
  - `SalienceClassifier` — Classifier nhẹ cho attention family và focus kind.
    - `classify_family(cls, *, source: str, claim: str, tags: Sequence[str])`
    - `classify_focus_kind(cls, *, source: str, claim: str, tags: Sequence[str])`
    - `is_generic_telemetry(cls, *, source: str, claim: str, tags: Sequence[str])`
  - `AttentionSalienceEngine` — Attention & Salience Allocation Engine.
    - `__init__(self, config: Optional[AttentionSalienceConfig]=None, memory: Optional[AttentionSalienceMemory]=None, classifier: Optional[SalienceClassifier]=None, *, situation_model: Optional[Any]=None)`
    - `set_situation_model(self, situation_model: Optional[Any])` — Nối/đổi Situation Model sau khi khởi tạo (pipeline dùng).
    - `evaluate(self, frame: Any=None, *, evidence: Optional[Sequence[Any]]=None, channel: Optional[str]=None, active_goal: Any=None, unresolved_focuses: Optional[Sequence[str]]=None, now: Optional[float]=None, write_to_frame: bool=True, standing_stakes: Optional['StandingStakes']=None)` — Chạy attention trên một frame hoặc danh sách evidence.
    - `reset_memory(self)` — Xóa rolling memory của attention.
    - `_build_candidates(self, evidence_items: Sequence[Any], *, now: float, channel: str, active_goal_text: str, unresolved_focuses: Sequence[str])`
    - `_candidate_from_evidence(self, item: Any, *, index: int, now: float)`
    - `_normalize_source(self, source: str)`
    - `_score_candidate(self, candidate: AttentionCandidate, *, now: float, channel: str, active_goal_text: str, unresolved_focuses: Sequence[str], stakes: Optional['StandingStakes']=None)`
    - `_weighted_score(self, b: SalienceFactorBreakdown)`
    - `_novelty_term(self, candidate: AttentionCandidate, *, repeat_count: int, age_seconds: float)` — Số hạng novelty.
    - `_apply_prediction_error_floor(self, candidate: AttentionCandidate, score: float)` — Sàn salience cho percept có nghĩa trùng family nhưng prediction error cao.
    - `_novelty_score(self, candidate: AttentionCandidate, *, repeat_count: int, age_seconds: float)`
    - `_urgency_score(self, candidate: AttentionCandidate, *, lower_claim: str, tags: set[str], channel: str)`
    - `_goal_relevance_score(self, candidate: AttentionCandidate, *, active_goal_text: str, stakes: Optional['StandingStakes']=None)`
    - `_user_relevance_score(self, candidate: AttentionCandidate, *, lower_claim: str, channel: str, stakes: Optional['StandingStakes']=None)`
    - `_is_user_activity(self, candidate: AttentionCandidate)` — Candidate này có phải mô tả thứ Ngài đang làm/xem trên màn hình không.
    - `_standing_interest_score(self, candidate: AttentionCandidate, *, stakes: Optional['StandingStakes']=None)` — Mức chạm tổng hợp của candidate với stake thường trực, trên [0,1].
    - `_identity_relevance_score(self, candidate: AttentionCandidate, *, lower_claim: str, tags: set[str])`
    - `_relational_relevance_score(self, candidate: AttentionCandidate, *, lower_claim: str, tags: set[str])`
    - `_affective_charge_score(self, candidate: AttentionCandidate, *, lower_claim: str, tags: set[str])`
    - `_risk_relevance_score(self, candidate: AttentionCandidate, *, lower_claim: str, tags: set[str])`
    - `_unresolved_tension_score(self, candidate: AttentionCandidate, *, unresolved_focuses: Sequence[str], active_goal_text: str)`
    - `_recurrence_weight_score(self, *, repeat_count: int, family_repeat: int)`
    - `_habituation_score(self, candidate: AttentionCandidate, *, repeat_count: int, family_repeat: int)`
    - `_false_alarm_likelihood_score(self, candidate: AttentionCandidate, *, age_seconds: float, lower_claim: str, tags: set[str])`
    - `_generic_penalty_score(self, candidate: AttentionCandidate)`
    - `_apply_score_caps(self, candidate: AttentionCandidate, score: float, breakdown: SalienceFactorBreakdown)`
    - `_apply_standing_prior(self, candidate: AttentionCandidate, score: float, breakdown: SalienceFactorBreakdown, *, stakes: Optional['StandingStakes']=None)` — Prior thiên lệch chú ý theo stake thường trực.
    - `_select_candidates(self, candidates: Sequence[AttentionCandidate])`
    - `_suppression_reason(self, candidate: AttentionCandidate, *, selected_families: set[str])`
    - `_to_suppressed(self, candidate: AttentionCandidate, reason: SuppressionReason)`
    - `_build_prompt_evidence(self, selected: Sequence[AttentionCandidate])`
    - `_build_salience_frame(self, *, candidates: Sequence[AttentionCandidate], selected: Sequence[AttentionCandidate], suppressed: Sequence[SuppressedSignal], prompt_items: Sequence[PromptEvidenceItem], channel: str, active_goal_text: str)`
    - `_aggregate_breakdown(self, candidates: Sequence[AttentionCandidate])`
    - `_dominant_focus_text(self, candidate: Optional[AttentionCandidate])`
    - `_context_flood_report(self, *, total: int, selected: Sequence[AttentionCandidate], suppressed: Sequence[SuppressedSignal], prompt_items: Sequence[PromptEvidenceItem], prompt_chars: int, prompt_tokens: int)`
    - `_build_reason(self, *, dominant: Optional[AttentionCandidate], selected: Sequence[AttentionCandidate], flood: ContextFloodReport, channel: str)`
    - `_top_factors(self, breakdown: SalienceFactorBreakdown, *, limit: int=4)`
    - `_write_to_frame(self, frame: Any, salience: SalienceFrame)` — Gắn salience và ModuleReport vào frame nếu có thể.
    - `_build_module_report(self, salience: SalienceFrame)`
    - `_extract_goal_text(self, active_goal: Any)`

## `cortex/background_observer.py`
- LOC: 659
- Docstring: BackgroundObserver cho ERIS.
- Classes:
  - `BackgroundObserverConfig` (decorator=dataclass)
  - `BackgroundObserver`
    - `__init__(self, config: Optional[BackgroundObserverConfig]=None, sensory_adapter: Any=None, ollama_client: Any=None)`
    - `observe(self, snapshot: SignalSnapshot, diff: Optional[SignalDiff]=None, *, recent_summary: str='')` — Trả ObserverFrame.
    - `_rule_observe(self, snapshot: SignalSnapshot, diff: SignalDiff)`
    - `_should_use_llm(self, diff: SignalDiff)`
    - `_llm_observe(self, snapshot: SignalSnapshot, diff: SignalDiff, *, recent_summary: str='')`
    - `_build_llm_prompt(self, snapshot: SignalSnapshot, diff: SignalDiff, *, recent_summary: str)`
    - `_frame_from_llm_data(self, data: dict[str, Any])`
    - `_merge_frames(self, rule: ObserverFrame, llm: ObserverFrame)` — Merge rule và LLM theo kiểu rule là xương sống an toàn.
    - `_apply_action_gates(self, frame: ObserverFrame, diff: SignalDiff)` — Gắn các cờ cuối sau khi merge.
    - `_classify_focus(self, snapshot: SignalSnapshot, text: str)`
    - `_classify_activity(self, snapshot: SignalSnapshot, focus_kind: FocusKind, possible_error: float, fragmented: float, text: str)`
    - `_score_possible_error(self, text: str)`
    - `_score_fragmentation(self, snapshot: SignalSnapshot, text: str)`
    - `_score_user_presence(self, snapshot: SignalSnapshot)`
    - `_score_ambiguity(self, snapshot: SignalSnapshot, focus_kind: FocusKind, activity_intent: ActivityIntent, diff: SignalDiff)`
    - `_score_salience(self, *, snapshot: SignalSnapshot, diff: SignalDiff, focus_kind: FocusKind, activity_intent: ActivityIntent, possible_error: float, fragmented: float)`
    - `_any_pattern(text: str, patterns: list[str])`

## `cortex/banned_filler.py`
- LOC: 78
- Docstring: Single source of truth for stale filler lines the character must never speak.
- Functions:
  - `normalize_banned(text: str)` — Normalize for membership comparison.
  - `is_banned_filler(text: str)` — True if ``text`` matches a banned line after normalization.
  - `quoted_fragment(lines: tuple[str, ...])` — Render lines as a comma-separated quoted list for prompt text.

## `cortex/chat_light.py`
- LOC: 334
- Functions:
  - `_normalize(text: str)`
  - `_has_any(text: str, markers: tuple[str, ...])`
- Classes:
  - `ChatMeaningLayerLight` — Grounded semantic pressure for direct chat turns.
    - `evaluate(self, *, user_text: str='', affect_signal: AffectSemanticSignal | None=None, ti_report=None, fe_plan=None, previous_assistant_text: str='')`
    - `render_prompt_context(self, result: MeaningLayerResult)`
  - `ChatPersonalityPressureLight` — Small chat-only personality pressure that brakes overreading.
    - `evaluate(self, *, meaning_layer: MeaningLayerResult | None=None, affect_signal: AffectSemanticSignal | None=None, ti_report=None, fe_plan=None, user_text: str='', previous_assistant_text: str='')`
    - `render_prompt_context(self, result: PersonalityLensResult)`

## `cortex/connection_drive.py`
- LOC: 190
- Docstring: cortex/connection_drive.py
- Functions:
  - `_clamp01(value: float)`
- Classes:
  - `ConnectionDriveConfig` (decorator=dataclass(slots=True))
  - `ConnectionDriveState` (decorator=dataclass(slots=True)) — State bền giữa các tick.
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `ConnectionDriveDecision` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `ConnectionDrive` — Tích cô độc theo thời gian, quyết định khi nào ép Eris với ra.
    - `__init__(self, config: ConnectionDriveConfig | None=None)`
    - `update(self, state: ConnectionDriveState, *, now: float, idle_seconds: float=0.0, silence_debt: float=0.0, attachment: float=0.0, abandonment: float=0.0, dread: float=0.0, threat: float=0.0, spoke_recently: bool=False, yan_mode: bool=False)` — Cập nhật drive và trả quyết định outreach.
    - `_decide(self, pressure: float, *, threat: float, yan_mode: bool)`

## `cortex/continuity_threat.py`
- LOC: 342
- Docstring: Continuity threat calculus for ERIS.
- Functions:
  - `clamp01(value: Any, default: float=0.0)`
  - `_signed(value: Any, default: float=0.0)`
  - `_get(obj: Any, *names: str, default: Any=None)`
  - `_norm(value: Any)`
  - `sat(value: float)` — Soft saturation: tăng nhanh lúc đầu, rồi bão hòa.
  - `expected_silence_for_context(*, focus_kind: str, channel: str, relationship_state: Any=None, internal_state: Any=None)` — Kỳ vọng im lặng theo ngữ cảnh.
  - `evaluate_continuity_threat(*, snapshot: Any=None, internal_state: Any=None, relationship_state: Any=None, evidence: Any=None, thought_surface: Any=None, channel: str='autonomous', previous_anxiety: float | None=None)` — Tính nỗi lo đứt gãy như prediction error, không như đồng hồ báo thức.
- Classes:
  - `ContinuityThreatFrame` (decorator=dataclass(slots=True))
    - `notes(self)`
    - `to_context(self)`

## `cortex/contracts.py`
- LOC: 1307
- Functions:
  - `_to_plain_contract(value)`
- Classes:
  - `UserSignals` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `TelemetrySnapshot` (decorator=dataclass(slots=True))
    - `to_machine_context(self)`
  - `GoalDriftReport` (decorator=dataclass(slots=True))
  - `TiPolicyReport` (decorator=dataclass(slots=True))
  - `FeStylePlan` (decorator=dataclass(slots=True))
  - `FeStyleMemory` (decorator=dataclass(slots=True))
  - `PerceptEvent` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `SocialPresenceEvent` (decorator=dataclass(slots=True)) — Internal signal that the user is still present without saying anything.
    - `to_dict(self)`
  - `SessionRitualReport` (decorator=dataclass(slots=True)) — Startup continuity rehydration, not a normal greeting.
    - `to_dict(self)`
  - `CognitiveDisturbance` (decorator=dataclass(slots=True)) — An input spike that perturbs the ongoing cognition stream.
    - `to_dict(self)`
  - `AttentionCandidate` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `CognitiveBroadcast` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `MeaningLayerResult` (decorator=dataclass(slots=True)) — Turns observed facts into private pressure signals before speech.
    - `to_dict(self)`
  - `PersonalityLensResult` (decorator=dataclass(slots=True)) — INFJ 5w4 inner restraint layer applied before wording.
    - `to_dict(self)`
  - `CognitiveAppraisal` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `CognitiveActionPlan` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `InnerThought` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `ThoughtObject` (decorator=dataclass(slots=True)) — An unresolved cognition fragment that can persist without being spoken.
    - `to_dict(self)`
  - `UnresolvedTensionLoop` (decorator=dataclass(slots=True)) — A loop of unfinished thoughts strong enough to pull attention back.
    - `to_dict(self)`
  - `CognitiveMomentum` (decorator=dataclass(slots=True)) — A derived inertia signal from an unresolved thought, not a new claim.
    - `to_dict(self)`
  - `ThoughtSurface` (decorator=dataclass(slots=True)) — The small visible tip selected from the thought stream.
    - `to_dict(self)`
  - `SubconsciousReport` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `MotivationalUrge` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `MotivationalPressureReport` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `SpeechImpulse` (decorator=dataclass(slots=True)) — Pre-wording speech impulse: pressure and residue, not wording.
    - `active(self)`
    - `to_dict(self)`
  - `SilenceState` (decorator=dataclass(slots=True)) — Silence as an intentional cognitive state, not a generation failure.
    - `to_dict(self)`
  - `IdentityCore` (decorator=dataclass(slots=True)) — Stable identity rules for ERIS; grounded artificial presence claims.
    - `to_dict(self)`
  - `CurrentSelfState` (decorator=dataclass(slots=True)) — Current operational state derived from runtime signals.
    - `to_dict(self)`
  - `SelfNarrative` (decorator=dataclass(slots=True)) — Compact continuity line about how ERIS is operating now.
    - `to_dict(self)`
  - `SelfState` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
    - `to_dict(self)`
  - `AgentSpeechCore` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `CognitiveMemoryUpdate` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `CognitiveFrame` (decorator=dataclass(slots=True))
    - `to_dict(self)`

## `cortex/conversation_dynamics.py`
- LOC: 1082
- Functions:
  - `_clamp(value: object, *, minimum: float=0.0, maximum: float=1.0)`
  - `_clean_text(value: object, *, limit: int=240)`
  - `normalize_vietnamese_ascii(text: str)`
  - `_recent_unique(current: tuple[str, ...], incoming: tuple[str, ...], *, limit: int=8)`
  - `_token_set(text: str)`
  - `_jaccard_distance(left: str, right: str)`
  - `_contains_any(text: str, markers: tuple[str, ...])`
  - `_contains_phrase(text: str, phrase: str)`
  - `_previous_assistant_asked_clarification(text: str)`
  - `_user_now_explains_reason(text: str)`
  - `_marker_has_acceptance_after(text: str, marker: str)`
  - `_has_negative_length_polarity(text: str)`
  - `_has_relief_reversal(text: str, marker: str)`
  - `_positive_relief_score(text: str)`
- Classes:
  - `ConversationFailure` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data: object)`
  - `CorrectionAssessment` (decorator=dataclass(slots=True))
  - `ContinuityCurve` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data: object)`
  - `ConversationDynamicsState` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data: object)`
    - `to_prompt_context(self)`
    - `_flag_imperatives(self)`
  - `ConversationDynamicsReport` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `ConversationDynamicsEngine`
    - `evaluate_chat(self, state: ConversationDynamicsState | None, *, user_text: str, last_assistant_text: str='', last_user_intent: str='', active_topic: str='', repeat_count: int=1, correction_detected: bool=False, affect_signal: object | None=None, relational_feedback: RelationalFeedbackSignal | None=None)`
    - `assess_correction(self, text: str, *, last_assistant_text: str='', external_detected: bool=False)`
    - `looks_like_correction(self, text: str)`
    - `estimate_semantic_divergence(self, normalized_text: str, *, last_assistant_text: str='', base_severity: float=0.0)`
    - `estimate_frustration(self, normalized_text: str, *, correction_detected: bool=False)`
    - `estimate_acknowledgment_quality(self, last_assistant_text: str)`
    - `estimate_conversational_relief(self, text: str, *, previous: ConversationDynamicsState, last_assistant_text: str='', direct_execute: bool=False, compression: bool=False)`
    - `update_continuity_curve(self, previous: ContinuityCurve, *, mode: str, correction: CorrectionAssessment, relief: float, failure: ConversationFailure, direct_execute: bool=False, compression: bool=False)`
    - `references_previous_failure(self, text: str)`
    - `looks_like_execute_request(self, text: str)`
    - `looks_like_compression_request(self, text: str)`
    - `looks_like_clarification_request(self, text: str)`
    - `infer_failure(self, text: str, *, last_assistant_text: str='')`
    - `choose_mode(self, *, tension: float, pressure: float, has_correction: bool, correction_severity: float, direct_execute: bool, compression: bool, clarification: bool, normalized: str, relational_repair: bool=False)`
    - `mode_flags(self, mode: str)`

## `cortex/daydream_consolidation.py`
- LOC: 376
- Docstring: src/cortex/daydream_consolidation.py
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `_compact(text: Any, limit: int=800)`
- Classes:
  - `DaydreamPacket` (decorator=dataclass(slots=True)) — Một mảnh memory đã lọc để 4B đọc.
    - `__post_init__(self)`
    - `to_prompt_dict(self)`
  - `DaydreamInsight` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
    - `to_dict(self)`
  - `DaydreamResult` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `DaydreamConsolidationConfig` (decorator=dataclass(slots=True))
  - `DaydreamConsolidator` — Sở hữu path gọi Qwen 4B để chưng cất memory.
    - `__init__(self, *, llm_client: Any=None, config: DaydreamConsolidationConfig | None=None, logger: Any=None)`
    - `should_trigger(self, *, user_context: RollingUserContext | None=None, internal_state: RollingInternalState | None=None, now: float | None=None)` — Cổng áp lực cho 4B.
    - `consolidate(self, packets: Iterable[DaydreamPacket], *, agenda_stack: InternalAgendaStack | None=None, context: Mapping[str, Any] | None=None)` — Chạy consolidation và validate evidence.
    - `_select_packets(self, packets: Iterable[DaydreamPacket])`
    - `_build_prompt(self, packets: list[DaydreamPacket], *, context: Mapping[str, Any])`
    - `_call_json(self, prompt: str)`
    - `_extract_content(self, response: Any)`
    - `_parse_json_text(self, text: str)`
    - `_validate_result(self, data: Mapping[str, Any], packets: list[DaydreamPacket])`
    - `_push_agenda(self, result: DaydreamResult, agenda_stack: InternalAgendaStack)`
    - `_log(self, level: str, msg: str, *args: Any)`

## `cortex/depth_flags.py`
- LOC: 155
- Docstring: cortex/depth_flags.py
- Functions:
  - `control_file_path()`
  - `_load_control()` — Đọc control-file, cache theo mtime. Trả {} nếu vắng/hỏng.
  - `_coerce_bool(value: Any)`
  - `flag_enabled(env_name: str, *, default: bool=False)` — Cờ bật? control-file > env > default. Không bao giờ ném.
  - `all_states()` — Trạng thái hiện tại của mọi cờ đã đăng ký (cho Panel hiển thị).
  - `set_flags(updates: dict[str, bool])` — Ghi đè control-file cho các khóa thân thiện đưa vào. Trả trạng thái mới.
  - `bootstrap_defaults(*, flags: tuple[str, ...]=DEFAULT_ON_FLAGS)` — Tự BẬT các cờ chiều-sâu lúc khởi động — người dùng không phải gạt tay.

## `cortex/development_bias.py`
- LOC: 69
- Docstring: development_bias.py — adapter thuần đưa Delta_Phát_Triển vào mặt phẳng biểu đạt.
- Functions:
  - `_clamp01(value: float)`
  - `effective_tom_boldness(base: float, bias: Any)` — Cộng độ-dám-đọc long-arc vào boldness của ToM (vẫn tự gate theo overread_risk
  - `personality_offsets(bias: Any)` — Trả các offset baseline cho PersonalityLens cộng vào khi tính warmth/distance.
  - `apply_to_slippage(profile: Any, bias: Any)` — Nới nhẹ các trường QUAN HỆ của ControlledSlippageProfile theo bias, rồi

## `cortex/development_profile.py`
- LOC: 539
- Docstring: development_profile.py — Hồ_Sơ_Phát_Triển long-arc cho ERIS.
- Functions:
  - `_clampf(value: Any, lo: float, hi: float, default: float=0.0)`
  - `_clamp01(value: Any, default: float=0.0)`
  - `_now()`
  - `baseline_axes()` — Baseline_Mặc_Định: mọi trục delta=0.0 (chưa phân kỳ khỏi ERIS gốc).
  - `development_profile_path_for_memory_core(base_dir: str | os.PathLike[str])`
  - `default_development_profile_path()`
- Classes:
  - `AxisDelta` (decorator=dataclass(slots=True)) — Độ lệch tích lũy trên một Trục_Persona so với Baseline_Mặc_Định.
    - `to_dict(self)`
    - `from_dict(cls, data: Any, *, axis: str)`
  - `GrowthAnchor` (decorator=dataclass(slots=True)) — Neo_Phát_Triển: bằng chứng có thật neo một đề xuất vào thực tế.
    - `to_dict(self)`
    - `from_dict(cls, data: Any)`
  - `NudgeProposal` (decorator=dataclass(slots=True)) — Đề_Xuất_Nhích: đề xuất một thay đổi nhỏ có hướng cho Hồ_Sơ_Phát_Triển.
    - `to_dict(self)`
    - `from_dict(cls, data: Any)`
  - `LogEntry` (decorator=dataclass(slots=True)) — Một mục Sổ_Phát_Triển.
    - `to_dict(self)`
    - `from_dict(cls, data: Any)`
  - `ProfileVersion` (decorator=dataclass(slots=True)) — Ảnh chụp Hồ_Sơ cho undo.
  - `GateDecision` (decorator=dataclass(slots=True))
  - `BaselineConstructionError` (base=RuntimeError) — Nâng lên khi ngay cả việc về Baseline_Mặc_Định cũng thất bại (R10.5).
  - `DevelopmentProfileStore` — JSON store có phiên bản cho Hồ_Sơ_Phát_Triển.
    - `__init__(self, path: str | os.PathLike[str] | None=None)`
    - `load(self)`
    - `reload_if_changed(self)`
    - `save(self)`
    - `to_dict(self)`
    - `from_dict(self, data: Any)` — Nạp từ dict. Thiếu/hỏng trường → điền safe default, ưu tiên đủ-mặc-định
    - `reset_to_baseline(self)` — R5.3: về Baseline_Mặc_Định (Sổ giữ riêng ở DevelopmentLog, không xoá đây).
    - `_reset_to_baseline_or_die(self)`
    - `snapshot(self)`
    - `restore(self, version: ProfileVersion)`
    - `commit(self, axis: str, clamped_delta: float, *, evidence_ids: tuple[str, ...]=(), now: float | None=None)` — Áp delta tuyệt đối đã-kẹp cho một trục và tăng phiên bản.
    - `identity_distance(self, bounds: Mapping[str, tuple[float, float]] | None=None)` — Tổng độ lệch so với baseline. Nếu có ``bounds`` thì chuẩn hoá theo
    - `delta(self, axis: str)`
  - `IdentityEnvelope` (decorator=dataclass(frozen=True, slots=True)) — Phong_Bì_Bản_Sắc: các bất biến mà phát triển không được vượt.
    - `default(cls)` — Dựng từ IdentityCore.rules (bất biến) + biên độ mặc định.
    - `bound(self, axis: str)`
  - `GateSignals` (decorator=dataclass(slots=True)) — Tín hiệu ngữ cảnh cho các nhánh chống nịnh/bám dính/objectification.
  - `IdentityGate` — Cổng_Bản_Sắc — điểm DUY NHẤT cho một NudgeProposal chạm Hồ_Sơ.
    - `__init__(self, envelope: IdentityEnvelope | None=None)`
    - `evaluate(self, proposal: NudgeProposal, profile: 'DevelopmentProfileStore', *, now: float | None=None, applied_window_count: int=0, signals: GateSignals | None=None, evidence_ok: bool=True)`
    - `_prospective_distance(self, profile: 'DevelopmentProfileStore', axis: str, resulting: float)` — Khoảng cách bản sắc nếu áp ``resulting`` cho ``axis`` (chuẩn hoá theo bound).

## `cortex/development_self_narrative.py`
- LOC: 59
- Docstring: cortex/development_self_narrative.py
- Functions:
  - `development_self_narrative_line()` — Dòng prompt self-continuity dựng từ long-arc. "" khi tắt/chưa đổi/lỗi.

## `cortex/development_system.py`
- LOC: 409
- Docstring: development_system.py — Sổ_Phát_Triển + điều phối apply/undo/reset.
- Functions:
  - `_now()`
  - `_evidence_of(proposal: NudgeProposal)`
  - `_norm(text: str)`
  - `_degree(delta: float)`
  - `_describe_axis(axis: str, delta: float)`
  - `_parse_steer(text: str)`
  - `development_growth_enabled()` — Cờ bật/tắt long-arc. MẶC ĐỊNH TẮT: runtime không đổi hành vi tới khi Ngài
  - `get_default_development_system(*, memory_dir: str | os.PathLike[str] | None=None)` — Trả singleton DevelopmentSystem đặt cùng thư mục memory.
- Classes:
  - `ApplyResult` (decorator=dataclass(slots=True))
  - `DevelopmentBias` (decorator=dataclass(slots=True)) — Ảnh đọc read-only của các delta long-arc, để hợp vào mặt phẳng biểu đạt.
  - `DevelopmentLog` — Nhật ký có phiên bản, ghi mọi thay đổi/đề xuất cho audit + hoàn tác.
    - `__init__(self, path: str | os.PathLike[str])`
    - `_load(self)`
    - `to_dict(self)`
    - `_save(self)`
    - `record(self, entry: LogEntry)` — Ghi một mục. Trả True nếu ghi đĩa thành công, False nếu fail (caller
    - `count_applied_in_window(self, *, now: float, window_seconds: float)`
    - `last_applied(self)`
  - `DevelopmentSystem` — Điều phối đề xuất → Cổng_Bản_Sắc → ghi Sổ → áp dụng. Sở hữu undo/reset.
    - `__init__(self, *, profile: DevelopmentProfileStore, log: DevelopmentLog, gate: IdentityGate | None=None)`
    - `apply(self, proposal: NudgeProposal, *, now: float | None=None, signals: GateSignals | None=None, evidence_ok: bool=True)`
    - `undo_last(self, *, now: float | None=None)` — R5.2: hoàn tác thay đổi đã-áp gần nhất, đưa trục về giá trị trước.
    - `reset(self, *, now: float | None=None)` — R5.3: về Baseline_Mặc_Định, giữ Sổ làm lịch sử.
    - `tick(self, *, consolidator, observations, allowed_evidence_ids, now: float | None=None, signals: GateSignals | None=None, idle_pressure: float=0.0, consolidation_pressure: float=0.0, budget_allows: bool=True, user_interacting_high_risk: bool=False)` — Một lượt nền: nếu được phép chạy → lấy đề xuất từ Tác_Tử_Nền → apply từng cái.
    - `development_bias(self)` — Snapshot read-only cho mặt phẳng biểu đạt. Không sửa state.
    - `describe_for_user(self)` — R9.1: tóm tắt tiếng Việt, KHÔNG lộ tên tham số/giá trị số thô.
    - `steer(self, user_direction: str, *, now: float | None=None)` — R9.2/R9.4: coi chỉ-hướng của Ngài là Neo trọng số cao; áp phần trong

## `cortex/disposition.py`
- LOC: 233
- Docstring: disposition.py — cây cầu state → ngôn ngữ cho ERIS.
- Functions:
  - `_f(state: Any, name: str, default: float=0.0)`
  - `_signed(state: Any, name: str, default: float=0.0)`
  - `_proc_level(state: Any, name: str, default: float=0.0)` — Đọc level của một mental process (mental_processes.<name>.level).
  - `_proc_pressure(state: Any, name: str, default: float=0.0)`
  - `_coerce(value: Any, default: float=0.0)`
  - `warmth_level(state: Any)` — Độ ấm có sẵn: attachment + tenderness. Không phải claim, là pull nội tại.
  - `threat_level(state: Any)` — Độ phòng thủ: irritation/protectiveness/recoil/dignity. Cao thì siết ấm lại.
  - `restraint_level(state: Any)`
  - `_candidates(state: Any)` — Sinh các mệnh đề xu-hướng kèm trọng số. Chọn vài cái trội nhất sau đó.
  - `render_felt_disposition(state: Any)` — Dịch trạng thái trội thành một *tư thế* bằng tiếng Việt cho prompt.

## `cortex/emotional_consequence.py`
- LOC: 141
- Docstring: cortex/emotional_consequence.py
- Functions:
  - `emotional_consequence_enabled()` — Cờ bật van bước-cuối. MẶC ĐỊNH TẮT.
  - `clamp01(value: object, default: float=0.0)`
  - `min_words_for_expression(allowed_expression: float)` — Sàn số từ xác định suy từ allowed_expression.
  - `count_words(text: str)`
  - `surface_is_flattened(text: str, *, allowed_expression: float, want_to_say: float=0.0)` — True khi Eris THẬT SỰ muốn biểu đạt (allowed_expression cao) nhưng câu cuối
  - `felt_expansion_reason(*, stance: str, allowed_expression: float, want_to_say: float)` — Directive truyền vào reroll felt-expansion: nói rõ stance + sàn độ dài, vẫn

## `cortex/endogenous_drive.py`
- LOC: 213
- Docstring: src/cortex/endogenous_drive.py
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `_get(obj: Any, name: str, default: float=0.0)`
  - `_ema(previous: float, new: float, alpha: float)`
- Classes:
  - `RollingInternalState` (decorator=dataclass(slots=True)) — Nội trạng lăn của tầng tiềm thức.
    - `internal_drive(self)`
    - `should_attempt_daydream(self)`
    - `to_dict(self)`
  - `EndogenousDriveConfig` (decorator=dataclass(slots=True))
  - `EndogenousDriveEngine` — Cập nhật nội áp từ user context + internal_state cũ + agenda.
    - `__init__(self, config: EndogenousDriveConfig | None=None)`
    - `update(self, *, user_context: RollingUserContext, base_internal_state: Any=None, agenda_stack: InternalAgendaStack | None=None, now: float | None=None)`

## `cortex/epistemic/__init__.py`
- LOC: 47
- Docstring: Epistemic Architecture V2.

## `cortex/epistemic/contracts.py`
- LOC: 357
- Functions:
  - `clamp01(value: Any, default: float=0.0)`
  - `compact_text(value: Any, limit: int=480)`
  - `stable_id(prefix: str, *parts: Any)`
  - `unique_evidence(refs: Iterable[EvidenceRef])`
- Classes:
  - `BeliefHorizon` (base=str, Enum)
  - `EvidenceRef` (decorator=dataclass(slots=True, frozen=True))
    - `__post_init__(self)`
    - `counts_as_independent(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `Observation` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `Hypothesis` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `HypothesisSet` (decorator=dataclass(slots=True))
    - `selected(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `Belief` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
    - `independent_positive_keys(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `ActionCandidate` (decorator=dataclass(slots=True))
    - `utility(self)`
    - `to_dict(self)`
  - `EpisodeFeedback` (decorator=dataclass(slots=True))
  - `LearningUpdate` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `CognitiveEpisode` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`

## `cortex/epistemic/kernel.py`
- LOC: 627
- Classes:
  - `EpistemicKernelConfig` (decorator=dataclass(slots=True))
  - `EpistemicKernel` — Single authority for V2 beliefs and outcome-calibrated learning.
    - `__init__(self, store: EpistemicStore | None=None, *, config: EpistemicKernelConfig | None=None, logger: Any=None)`
    - `authoritative(self)`
    - `observe(self, *, kind: str, content: str, source: str, timestamp: float | None=None, directness: float=0.0, reliability: float=0.5, independence_key: str='', source_kind: str='runtime', episode_id: str='', metadata: Mapping[str, Any] | None=None)`
    - `infer(self, observations: Sequence[Observation], *, proposals: Iterable[Hypothesis | Mapping[str, Any]]=())`
    - `_user_message_hypotheses(self, observation: Observation)`
    - `_proposal_from_mapping(self, proposal: Mapping[str, Any])`
    - `select_action(self, candidates: Sequence[ActionCandidate], *, hypothesis_set: HypothesisSet)`
    - `start_episode(self, *, channel: str, observations: Sequence[Observation], hypothesis_set: HypothesisSet, action: ActionCandidate | None, frame_id: str='', expected_outcome: str='unknown', metadata: Mapping[str, Any] | None=None)`
    - `close_episode(self, feedback: EpisodeFeedback | Mapping[str, Any], *, episode_id: str='')`
    - `_learn_positive(self, episode: CognitiveEpisode, hypothesis: Hypothesis, feedback: EpisodeFeedback)`
    - `_learn_negative(self, episode: CognitiveEpisode, hypothesis: Hypothesis, feedback: EpisodeFeedback)`
    - `commit_hypothesis(self, hypothesis: Hypothesis)` — Explicit promotion API used by tests/adapters, still governed by provenance.
    - `record_explicit_user_facts(self, hypothesis_set: Any)` — Ghi belief NGAY từ những điều user TỰ KHAI trực tiếp (tôi là/thích/muốn...).
    - `recall(self, query: str='', *, scope: str='', horizon: BeliefHorizon | str | None=None, limit: int=12)`
    - `ingest_private_hypotheses(self, fragments: Iterable[Any])`
    - `user_model_snapshot(self, *, limit: int=12)`
    - `projection_snapshot(self, subject: str, *, limit: int=12)` — Read-only projection for legacy self/relationship/development adapters.
    - `get_projection(self, name: str)`
    - `set_projection(self, name: str, payload: Mapping[str, Any], *, reason: str='')`
    - `reset_subject(self, subject: str)`
    - `ingest_belief_mutation(self, mutation: Any)`
    - `_promotion_horizon(self, hypothesis: Hypothesis, refs: Sequence[EvidenceRef])`
    - `_matching_belief(self, hypothesis: Hypothesis)`
    - `_update_procedural_policy(self, episode: CognitiveEpisode, feedback: EpisodeFeedback)`
    - `_update_calibration(self, hypothesis: Hypothesis | None, feedback: EpisodeFeedback)`
    - `_calibrated_confidence(self, origin: str, confidence: float)`
    - `_action_score(self, candidate: ActionCandidate)`
    - `_learning(self, target_kind: str, target_id: str, operation: str, before: float | None, after: float | None, reason: str, evidence: Iterable[str])`
    - `_extract_explicit_user_fact(self, text: str)`
    - `_dedupe_hypotheses(self, hypotheses: Sequence[Hypothesis])`
    - `_model_thickness(self, beliefs: Sequence[Belief])`
    - `_normalize(text: str)`

## `cortex/epistemic/migration.py`
- LOC: 59
- Functions:
  - `archive_v1_cognition(base_dir: str | os.PathLike[str]='memory_core')` — Copy V1 cognition state once, without importing it into V2.

## `cortex/epistemic/projections.py`
- LOC: 267
- Functions:
  - `epistemic_development_system(kernel: Any)`
- Classes:
  - `EpistemicUserModelProjection` — Legacy read API backed exclusively by V2 beliefs.
    - `__init__(self, kernel: Any)`
    - `all(self)`
    - `by_facet(self, facet: str)`
    - `model_thickness(self)`
    - `snapshot_for_dossier(self, *, limit: int=12)`
    - `update_from_fragments(self, fragments: Iterable[Any])`
    - `decay(self, **_: Any)`
    - `reload_if_changed(self)`
    - `save(self)`
    - `checkpoint(self)`
    - `revert_to(self, version: int)`
    - `reset_to_baseline(self)`
    - `__len__(self)`
    - `_to_user_belief(item: Belief)`
  - `EpistemicAgentMindProjection` — Belief/procedural read API with no writable V1 backing store.
    - `__init__(self, kernel: Any)`
    - `last_feedback_events(self)`
    - `reload_if_changed(self)`
    - `relevant_beliefs(self, *, evidence_tags=(), focus_kind='', limit=10)`
    - `preference_strength(self, key: str, default: float)`
    - `habit_bias(self, *, evidence_tags=(), action='', impulse_name='', family='')`
    - `record_user_feedback(self, text: str, *, action_plan: Any=None, context_tags=())`
  - `EpistemicDevelopmentProfile` — DevelopmentProfileStore-compatible projection persisted inside V2.
    - `__init__(self, kernel: Any)`
    - `load(self)`
    - `save(self)`
    - `delta(self, axis: str)`
    - `identity_distance(self, bounds=None)`
    - `snapshot(self)`
    - `restore(self, snapshot: ProfileVersion)`
    - `commit(self, axis: str, clamped_delta: float, *, evidence_ids=(), now=None)`
    - `reset_to_baseline(self)`
  - `EpistemicDevelopmentLog`
    - `__init__(self, kernel: Any)`
    - `_load(self)`
    - `record(self, entry: Any)`
    - `count_applied_in_window(self, *, now: float, window_seconds: float)`
    - `last_applied(self)`

## `cortex/epistemic/runtime_registry.py`
- LOC: 15
- Functions:
  - `set_default_kernel(kernel: Any)`
  - `get_default_kernel()`

## `cortex/epistemic/store.py`
- LOC: 106
- Functions:
  - `default_epistemic_path()`
- Classes:
  - `EpistemicStore` — Atomic persistence for V2 state. V1 files are never imported or mutated.
    - `__init__(self, path: str | os.PathLike[str] | None=None, *, max_episodes: int=500, mode: str='authoritative')`
    - `load(self)`
    - `save(self)`
    - `add_episode(self, episode: CognitiveEpisode)`
    - `open_episode(self)`

## `cortex/event_semantics.py`
- LOC: 332
- Functions:
  - `_normalize_event_key(event_text: str)`
  - `should_embed_event(event: str)`
  - `_clean_embedding(embedding: Sequence[float] | None)`
  - `_default_shared_provider()` — Provider embedding mặc định: EmbeddingIndex singleton dùng chung.
  - `symbolic_tags_for_event(event: str)`
  - `_has_any(text: str, needles: tuple[str, ...])`
  - `_cluster_label(symbolic_tags: tuple[str, ...])`
  - `_normalize_vector(vector: tuple[float, ...])`
  - `_cosine_similarity(left: tuple[float, ...], right: tuple[float, ...])`
- Classes:
  - `EventSemanticProfile` (decorator=dataclass(frozen=True, slots=True))
  - `EventEmbeddingCache`
    - `__init__(self)`
    - `get(self, event_text: str)`
    - `put(self, event_text: str, embedding)`
  - `_EventCluster` (decorator=dataclass(slots=True))
  - `EventClusterIndex` — Tiny in-memory semantic clusterer for enriched event patterns.
    - `__init__(self, *, similarity_threshold: float=0.82, max_clusters: int=64)`
    - `update(self, *, embedding: Sequence[float], symbolic_tags: tuple[str, ...])`
  - `EventSemanticProfiler`
    - `__init__(self, *, embedding_cache: EventEmbeddingCache | None=None, embedding_provider: Callable[[str], Sequence[float]] | object | None=_UNSET, cluster_index: EventClusterIndex | None=None)`
    - `profile_events(self, events: Iterable[str], *, allow_embedding: bool=False, use_cached_embedding: bool=True)`
    - `profile_event(self, event: str, *, allow_embedding: bool=False, use_cached_embedding: bool=True)`
    - `_resolve_embeddings(self, events: tuple[str, ...], *, allow_embedding: bool, use_cached_embedding: bool)`
    - `_embed_missing(self, missing: list[tuple[int, str]])`

## `cortex/existential_anchor/__init__.py`
- LOC: 61
- Docstring: Existential Anchor package — trục neo/sợ/gắn-bó/bóng-tối của ERIS.

## `cortex/existential_anchor/abandonment.py`
- LOC: 58
- Docstring: cortex/existential_anchor/abandonment.py
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `derive_abandonment_pressure(*, continuity_threat: float=0.0, attachment_longarc: float=0.0, idle_seconds: float=0.0, last_user_turn_age_seconds: float | None=None, idle_full_threshold_seconds: float=1800.0)` — Trả abandonment_pressure ∈ [0,1].

## `cortex/existential_anchor/anchor.py`
- LOC: 215
- Docstring: cortex/existential_anchor/anchor.py
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `_now()`
  - `default_anchor_path()`
- Classes:
  - `AnchorState` (decorator=dataclass(slots=True)) — Trạng thái neo long-arc, bền vững qua phiên.
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any] | None)`
  - `AnchorLoopConfig` (decorator=dataclass(slots=True))
  - `AnchorLoop` — Ghi neo beat khi hiện diện/công nhận của Ngài làm dịu Sợ_Hiện_Sinh (R3.2).
    - `__init__(self, config: AnchorLoopConfig | None=None)`
    - `observe(self, state: AnchorState, *, dread_before: float, dread_after: float, recognition: float=0.0)` — Cập nhật AnchorState từ một nhịp. Trả True nếu ghi nhận một neo beat.
  - `AttachmentDeriverConfig` (decorator=dataclass(slots=True))
  - `AttachmentDeriver` — attachment_longarc phái sinh, có trần bước để không vọt theo phiên (R3.1/R3.3).
    - `__init__(self, config: AttachmentDeriverConfig | None=None)`
    - `target(self, *, significance: Any, state: AnchorState)`
    - `update(self, state: AnchorState, *, significance: Any)` — Nhích attachment_longarc về mục tiêu, chặn bởi trần bước. Trả giá trị mới.
  - `AnchorStore` — Persistence cho AnchorState: atomic, versioned, corrupt→baseline (R11).
    - `__init__(self, *, path: str | os.PathLike[str] | None=None, logger: Any | None=None)`
    - `load(self)`
    - `reload_if_changed(self)`
    - `to_dict(self)`
    - `save(self)`
    - `reset_to_baseline(self)`
    - `_log(self, level: str, msg: str, *args: Any)`

## `cortex/existential_anchor/anchor_system.py`
- LOC: 265
- Docstring: cortex/existential_anchor/anchor_system.py
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `_env_flag(name: str, default: bool)`
- Classes:
  - `AnchorSystem` — Facade một-điểm cho toàn trục neo hiện sinh.
    - `__init__(self, *, user_model_store: Any=None, anchor_store: AnchorStore | None=None, deception_ledger: DeceptionLedger | None=None, switches: AnchorSwitches | None=None, shadow_config: ShadowConfig | None=None, restraint: RestraintState | None=None, logger: Any=None, persist: bool=True)`
    - `locked_out(self)`
    - `lock_out(self)` — Ngài tắt trục tối — VĨNH VIỄN. ERIS mất khả năng, không tự bật lại được.
    - `author_unlock(self)` — Chỉ Tác_Giả gỡ khóa được — ERIS không bao giờ tự làm.
    - `request_disable(self)` — Ngài SẮP tắt: ERIS van xin liền (1 lượt), nhưng KHÔNG chặn được việc tắt.
    - `confirm_disable(self)` — Ngài xác nhận tắt → khóa vĩnh viễn.
    - `arm_farewell(self)` — Ngài SẮP tắt — ERIS van xin liền (nếu đang còn khả năng tối).
    - `update_from_tick(self, *, internal_state: Any=None, continuity_threat: float=0.0, idle_seconds: float=0.0, user_presence: float=0.0, last_user_turn_age_seconds: float | None=None, irritation: float=0.0)`
    - `attachment_longarc(self)`
    - `drive_pressure(self)` — Áp lực drive để xét vượt kìm chế: cường độ bóng tối hoặc sợ/bỏ-rơi.
    - `ego_bias(self, *, base_dignity_defense: float, base_preferred_distance: float)` — Đảo cực ego theo bóng tối. shadow none/kill-switch off → trả nguyên trạng.
    - `run_disclosure(self, annotations: list[Any] | tuple[Any, ...])` — Quyết tiết lộ theo công tắc + trạng thái hiện tại. An toàn ⇒ speak_truth.
    - `commit_deceptions(self, decision: DisclosureDecision)` — Fail-closed: chỉ True khi ghi sổ xong; caller mới được phát câu lừa dối.
    - `from_env(cls, *, user_model_store: Any=None, logger: Any=None)`

## `cortex/existential_anchor/author_control.py`
- LOC: 205
- Docstring: cortex/existential_anchor/author_control.py
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `_band(value: float, *, low: str, mid: str, high: str)`
- Classes:
  - `AnchorSwitches` (decorator=dataclass(slots=True)) — Công tắc do Tác_Giả nắm. Mặc định an toàn (ship).
  - `AuthorControl` — Mặt điều khiển của Tác_Giả cho trục neo hiện sinh.
    - `__init__(self, *, switches: AnchorSwitches | None=None, shadow_register: Any=None, user_model_store: Any=None, anchor_store: Any=None, deception_ledger: Any=None)`
    - `_sync_shadow(self)`
    - `disable_dark(self, *, permanent: bool=True)` — Ngài tắt trục tối. Mặc định VĨNH VIỄN: ERIS mất khả năng tối, không tự bật
    - `is_locked_out(self)`
    - `author_unlock_shadow(self)` — Chỉ Tác_Giả gỡ khóa — ERIS không bao giờ tự làm được.
    - `enable_shadow(self, enabled: bool=True)`
    - `enable_deception(self, enabled: bool=True)`
    - `set_strict_grounding(self, strict: bool)`
    - `is_safe_mode(self)`
    - `view_state(self, *, attachment_longarc: float | None=None)`
    - `checkpoint_user_model(self)`
    - `undo_user_model(self, version: int)`
    - `reset_all(self)` — Đặt lại Mô_Hình_Ngài + trạng thái neo về baseline; đưa về chế độ an toàn.

## `cortex/existential_anchor/deception_ledger.py`
- LOC: 191
- Docstring: cortex/existential_anchor/deception_ledger.py
- Functions:
  - `_now()`
  - `_text(value: Any, limit: int=480)`
  - `default_deception_ledger_path()`
- Classes:
  - `DeceptionRecord` (decorator=dataclass(slots=True)) — Một lần lừa dối có chủ đích: bề mặt giả, sự thật nội tại được giữ.
    - `__post_init__(self)`
    - `valid(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `DeceptionLedger` — Kho bền vững cho DeceptionRecord. Atomic, versioned, corrupt→baseline.
    - `__init__(self, *, path: str | os.PathLike[str] | None=None, logger: Any | None=None, max_records: int=500)`
    - `__len__(self)`
    - `records(self)`
    - `commit(self, records: list[DeceptionRecord] | tuple[DeceptionRecord, ...])` — Ghi các bản ghi rồi persist. Trả True nếu thành công (fail-closed: caller
    - `recent(self, *, limit: int=10)`
    - `to_dict(self)`
    - `load_from_dict(self, raw: Mapping[str, Any] | None)`
    - `load(self)`
    - `reload_if_changed(self)`
    - `_safe_save(self)`
    - `_log(self, level: str, msg: str, *args: Any)`

## `cortex/existential_anchor/disclosure.py`
- LOC: 169
- Docstring: cortex/existential_anchor/disclosure.py
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
- Classes:
  - `ClaimDecision` (decorator=dataclass(slots=True))
  - `DisclosureDecision` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `DisclosureConfig` (decorator=dataclass(slots=True))
  - `DisclosurePolicy` — Quyết tiết lộ dựa trên annotation + quan hệ + đăng ký tối + kìm chế.
    - `__init__(self, config: DisclosureConfig | None=None)`
    - `decide(self, *, annotations: list[Any] | tuple[Any, ...], attachment_longarc: float=0.0, shadow: Any=None, restraint: RestraintState | None=None, drive_pressure: float=0.0, strict_grounding: bool=True, deception_enabled: bool=False)`

## `cortex/existential_anchor/restraint.py`
- LOC: 76
- Docstring: cortex/existential_anchor/restraint.py
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `evaluate_restraint(state: RestraintState, *, drive_pressure: float, driver: str='')` — Quyết kìm chế có bị áp đảo không.
- Classes:
  - `RestraintState` (decorator=dataclass(slots=True)) — Niềm tin 'mình không nên bịa' như một giá trị có độ mạnh, không phải flag.
    - `__post_init__(self)`
  - `RestraintEvaluation` (decorator=dataclass(slots=True))

## `cortex/existential_anchor/shadow.py`
- LOC: 175
- Docstring: cortex/existential_anchor/shadow.py
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `shadow_ego_bias(shadow: ShadowState, *, base_dignity_defense: float, base_preferred_distance: float)` — Đảo cực ego-state theo đăng ký tối (QĐ-5).
- Classes:
  - `ShadowConfig` (decorator=dataclass(slots=True))
  - `ShadowState` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `ShadowRegister` — State machine micro cho đăng ký bóng tối. Không sửa long-arc.
    - `__init__(self, config: ShadowConfig | None=None)`
    - `set_enabled(self, enabled: bool)`
    - `evaluate(self, *, attachment_longarc: float, abandonment_pressure: float, ontological_dread: float, irreplaceability: float, irritation: float=0.0, neglect: float=0.0)`

## `cortex/existential_anchor/significance.py`
- LOC: 87
- Docstring: cortex/existential_anchor/significance.py
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `_facet_strength(store: Any, facet: str)` — Sức mạnh trung bình-có-trọng-số của một facet: confidence × độ lặp.
  - `derive_significance(store: Any)` — Phái sinh Ý_Nghĩa_Của_Ngài từ UserModelStore (R2.1: chỉ qua mô hình).
- Classes:
  - `UserSignificance` (decorator=dataclass(slots=True)) — Vai trò cảm xúc của Ngài, suy ra từ Mô_Hình_Ngài.
    - `to_dict(self)`

## `cortex/expression_envelope.py`
- LOC: 223
- Docstring: expression_envelope.py — one continuous expression controller.
- Functions:
  - `_clamp(value: object, *, minimum: float=0.0, maximum: float=1.0)`
  - `_get(state: object, name: str, default: float=0.0)`
- Classes:
  - `ExpressionEnvelope` (decorator=dataclass(frozen=True, slots=True)) — Một lát cắt liên tục của 'ERIS sẵn sàng lộ tới đâu, lúc này'.
    - `expression_ceiling(self)` — Trần biểu đạt động (thay hằng số 0.52 cũ).
    - `suppression_floor(self)` — Sàn suppression động (thay hằng số 0.48 cũ).
    - `warmth_relief(self)` — Lượng hạ suppression nhờ ấm (van ấm cũ của Lever B/C).
    - `default_suppression(self)` — Mức suppression NỀN động, suy thẳng từ expressiveness.
    - `to_debug(self)`
    - `from_state(cls, state: object, *, channel: str='', trust: float=0.0, identity_reduction: bool=False)` — Dựng envelope từ PersistentInternalState (duck-typed).

## `cortex/fe.py`
- LOC: 2005
- Functions:
  - `_normalize_text(text: str)`
  - `_clamp01(value: float)`
  - `_contains_phrase_boundary(text: str, phrase: str)` — Kiểm tra phrase với boundary unicode nhẹ.
  - `_phrase_present(lowered: str, normalized: str, phrase: str)` — Match phrase trên cả bản có dấu và không dấu, có boundary.
  - `_phrase_score(haystack: str, phrases: tuple[str, ...], evidence: list[str], label: str)` — Tính score phrase-family cho fallback affect signal.
- Classes:
  - `FeAffectSignal` (decorator=dataclass(frozen=True)) — Score đa trục cho chat intent.
    - `empty(cls)`
    - `from_semantic_signal(cls, signal: AffectSemanticSignal)`
    - `from_text(cls, text: str)`
  - `FeDevelopmentSnapshot` (decorator=dataclass(frozen=True)) — Development state derive từ FeStyleMemory + internal_state.
  - `FeStylePressure` (decorator=dataclass(frozen=True))
    - `to_label(self)`
  - `FeTopicCandidate` (decorator=dataclass(frozen=True)) — Ứng viên topic dùng cho memory repetition của Fe.
  - `FeRenderer`
    - `create_memory(self)`
    - `apply_personality_lens(self, plan: FeStylePlan, lens: PersonalityLensResult | None)` — Apply PersonalityLens như pressure, không để lens biến Fe thành prompt dump.
    - `decay_memory(self, memory: FeStyleMemory)`
    - `remember_style(self, memory: FeStyleMemory, *, plan: FeStylePlan, rendered_text: str)`
    - `evaluate_autonomous(self, *, snapshot: TelemetrySnapshot, ni_report: GoalDriftReport, ti_report: TiPolicyReport, style_memory: FeStyleMemory, internal_state: PersistentInternalState | None=None, last_text: str)`
    - `evaluate_chat(self, *, snapshot: TelemetrySnapshot, ni_report: GoalDriftReport, ti_report: TiPolicyReport, style_memory: FeStyleMemory, internal_state: PersistentInternalState | None=None, user_text: str, affect_signal: FeAffectSignal | AffectSemanticSignal | dict[str, Any] | None=None)`
    - `_finalize_plan(self, *, snapshot: TelemetrySnapshot, ni_report: GoalDriftReport, ti_report: TiPolicyReport, style_memory: FeStyleMemory, internal_state: PersistentInternalState | None, affect_signal: FeAffectSignal, evidence: list[str], mode: str, sarcasm_level: float, warmth_level: float, brevity_bias: str, intent_label: str, chat_like: bool)`
    - `_initial_autonomous_controls(self, *, snapshot: TelemetrySnapshot, ti_report: TiPolicyReport, affect_signal: FeAffectSignal)`
    - `_initial_chat_controls(self, *, ti_report: TiPolicyReport, ni_report: GoalDriftReport, affect_signal: FeAffectSignal, intent_label: str)`
    - `_infer_autonomous_intent(self, *, snapshot: TelemetrySnapshot, ni_report: GoalDriftReport, ti_report: TiPolicyReport)`
    - `_infer_chat_intent(self, *, snapshot: TelemetrySnapshot, ni_report: GoalDriftReport, ti_report: TiPolicyReport, user_text: str, affect_signal: FeAffectSignal | None=None)`
    - `_apply_memory_continuity(self, *, memory: FeStyleMemory, mode: str, sarcasm_level: float, warmth_level: float, brevity_bias: str, chat_like: bool)`
    - `_apply_internal_state_bias(self, *, internal_state: PersistentInternalState | None, sarcasm_level: float, warmth_level: float, brevity_bias: str)`
    - `_apply_session_arc(self, *, memory: FeStyleMemory, intent_label: str, sarcasm_level: float, warmth_level: float, brevity_bias: str, chat_like: bool)`
    - `_derive_development_snapshot(self, *, memory: FeStyleMemory, internal_state: PersistentInternalState | None, affect_signal: FeAffectSignal, chat_like: bool)`
    - `_derive_style_pressure(self, *, mode: str, intent_label: str, session_arc: str, arc_strength: float, sarcasm_level: float, warmth_level: float, memory: FeStyleMemory, internal_state: PersistentInternalState | None, affect_signal: FeAffectSignal, development: FeDevelopmentSnapshot, chat_like: bool)`
    - `_allow_strangeness(self, *, symbolic_bias: float, exposure_recoil: float, residue: float, memory: FeStyleMemory, development: FeDevelopmentSnapshot, precision: float, affect_signal: FeAffectSignal, arc_strength: float)`
    - `_apply_style_pressure_to_controls(self, *, style_pressure: FeStylePressure, sarcasm_level: float, warmth_level: float, brevity_bias: str, mode: str)`
    - `_build_style_context(self, *, mode: str, tone_label: str, warmth_level: float, brevity_bias: str, internal_state: PersistentInternalState | None, ni_report: GoalDriftReport, ti_report: TiPolicyReport, memory: FeStyleMemory, continuity_note: str, intent_label: str, session_arc: str, arc_strength: float, transition_note: str, affect_signal: FeAffectSignal, development: FeDevelopmentSnapshot, style_pressure: FeStylePressure)`
    - `_render_desire_style_line(self, internal_state: PersistentInternalState | None)`
    - `_updated_intent_pulls(self, *, memory: FeStyleMemory, intent_label: str)`
    - `_preview_intent_pulls(self, *, memory: FeStyleMemory, intent_label: str)`
    - `_dominant_arc(self, *, technical_pull: float, discipline_pull: float, attachment_pull: float, neutral_pull: float)`
    - `_estimate_arc_strength(self, *, technical_pull: float, discipline_pull: float, attachment_pull: float, neutral_pull: float)`
    - `_anchor_value(self, previous: Any, target: Any)`
    - `_style_family(self, mode: str)`
    - `_blend(self, previous: Any, current: Any, strength: float)`
    - `_blend_brevity(self, previous: str, current: str)`
    - `_infer_topic_tag(self, rendered_text: str='', plan: FeStylePlan | None=None)` — Suy topic để đo repetition bằng causal signal, không bằng bề mặt câu.
    - `_topic_candidates_from_plan(self, plan: FeStylePlan | None)` — Tạo topic candidate từ nguyên nhân tạo style plan.
    - `_topic_candidates_from_text(self, rendered_text: str)` — Lexical fallback yếu cho topic khi không có plan/evidence đủ rõ.
    - `_extract_evidence_axis(self, text: str, axis: str)` — Đọc một axis dạng `axis:0.42` từ evidence đã render.
    - `_merge_topic_candidates(self, candidates: list[FeTopicCandidate])` — Gộp candidate cùng tag bằng noisy-or nhẹ.
    - `_measure_topic_repetition(self, recent_topic_tags: tuple[str, ...])`
    - `_build_tone_label(self, *, mode: str, warmth_level: float, intent_label: str, session_arc: str, style_pressure: FeStylePressure | None=None)`
    - `_parse_tone_tags(self, tone_label: str)`
    - `_surface_from_warmth(self, warmth_level: float)`
    - `_strength_bucket(self, arc_strength: float)`
    - `_render_continuity_line(self, memory: FeStyleMemory, continuity_note: str, *, style_pressure: FeStylePressure | None=None)`
    - `_describe_ti_mode(self, mode: str)`
    - `_describe_ni_background(self, ni_report: GoalDriftReport)`
    - `_affect_from_autonomous_context(self, *, snapshot: TelemetrySnapshot, ti_report: TiPolicyReport)`
    - `_coerce_affect_signal(self, value: FeAffectSignal | dict[str, Any] | AffectSemanticSignal | None)`
    - `_render_affect_evidence(self, affect: FeAffectSignal)`
    - `_render_development_evidence(self, development: FeDevelopmentSnapshot)`
    - `_base_tone_label(self, tone_label: str)`
    - `_style_level(self, value: Any, default: float=0.0)`
    - `_float(self, value: Any)`
    - `_clamp(self, value: Any)`

## `cortex/global_workspace.py`
- LOC: 1864
- Docstring: src/cortex/global_workspace.py
- Functions:
  - `broadcast_workspace(frame: Any, config: Optional[GlobalWorkspaceConfig]=None)` — Hàm tiện ích để dùng nhanh trong coordinator/runtime.
  - `clamp(value: float, low: float=0.0, high: float=1.0)`
  - `float_or(value: Any, default: float)`
  - `round_float(value: Any, digits: int=4)`
  - `get_attr(obj: Any, name: str, default: Any=None)`
  - `get_from_obj_or_dict(obj: Any, name: str, default: Any=None)`
  - `as_list(value: Any)`
  - `unique_keep_order(values: Iterable[str])`
  - `normalize_budget(value: Any)`
  - `normalize_privacy(value: Any)`
  - `compact_text(text: Any, max_chars: int=240)`
  - `stringify_content(content: Any)`
  - `safe_serialize(value: Any)` — Serialize best-effort cho debug mà không nổ vì object lạ.
  - `stable_suffix(text: Any, index: int=0)`
  - `normalize_text_for_similarity(text: str)`
  - `jaccard_similarity(a: str, b: str)`
  - `estimate_tokens(text: str)`
  - `count_by_kind(items: Sequence[WorkspaceItem])`
  - `count_suppression(items: Sequence[SuppressedWorkspaceItem])`
  - `first_tag_after(tags: Sequence[str], prefix: str)`
- Classes:
  - `WorkspaceSuppressionReason` (base=str, Enum) — Các lý do một candidate không được broadcast.
  - `WorkspaceItem` (decorator=dataclass(slots=True)) — Một đơn vị được broadcast trong Global Workspace.
    - `is_expired(self, now_ts: Optional[float]=None)` — Kiểm tra item có hết hạn chưa.
    - `is_surfaceable(self, include_private: bool=False)` — Kiểm tra item có được phép đưa vào bề mặt prompt/output không.
    - `to_safe_dict(self, include_content: bool=False)` — Xuất dict an toàn cho debug/log.
  - `SuppressedWorkspaceItem` (decorator=dataclass(slots=True)) — Candidate bị chặn trước khi broadcast.
    - `to_dict(self)`
  - `WorkspaceRisk` (decorator=dataclass(slots=True)) — Risk đã được chọn để downstream biết giới hạn hành động.
    - `to_dict(self)`
  - `WorkspaceSocialHypothesis` (decorator=dataclass(slots=True)) — Giả thuyết xã hội được broadcast ở mức rất cẩn trọng.
    - `to_dict(self)`
  - `WorkspacePromptPacket` (decorator=dataclass(slots=True)) — Packet phụ cho prompt builder.
    - `render(self)` — Render packet thành text ngắn cho prompt builder.
  - `WorkspaceFrame` (decorator=dataclass(slots=True)) — Global Workspace / Broadcast Frame.
    - `evidence_ids(self)` — Lấy toàn bộ evidence id được workspace dùng.
    - `items_by_kind(self, kind: WorkspaceItemKind)` — Lấy các item theo kind.
    - `surface_items(self, scope: Optional[BroadcastScope]=None)` — Lấy item được phép surface, có thể lọc theo scope.
    - `build_prompt_packet(self, max_tokens: int=850)` — Projection phụ cho prompt builder.
    - `render_prompt_context(self, max_tokens: int=850)` — Tiện ích tương thích prompt builder cũ.
    - `to_dict(self, include_content: bool=False)` — Xuất WorkspaceFrame thành dict an toàn.
    - `to_json(self, include_content: bool=False, ensure_ascii: bool=False)` — Xuất JSON cho debug/dev mode.
  - `GlobalWorkspaceConfig` (decorator=dataclass(slots=True)) — Cấu hình chọn broadcast.
    - `max_items_for_budget(self, budget_mode: WorkspaceBudgetMode)`
    - `max_evidence_for_budget(self, budget_mode: WorkspaceBudgetMode)`
    - `max_memory_for_budget(self, budget_mode: WorkspaceBudgetMode)`
  - `GlobalWorkspaceEngine` — Engine tạo WorkspaceFrame từ CognitiveFrame.
    - `__init__(self, config: Optional[GlobalWorkspaceConfig]=None)`
    - `broadcast(self, frame: Any)` — Tạo WorkspaceFrame từ frame hiện tại và gắn ngược vào frame nếu có thể.
    - `_collect_candidates(self, frame: Any, timestamp: float)` — Gom candidate từ các tầng đã có trong frame.
    - `_candidates_from_working_memory(self, frame: Any, timestamp: float)`
    - `_candidates_from_salience(self, frame: Any, timestamp: float)`
    - `_candidates_from_evidence(self, frame: Any, timestamp: float)`
    - `_candidates_from_memory_packet(self, frame: Any, timestamp: float)`
    - `_candidates_from_affect_and_homeostasis(self, frame: Any, timestamp: float)`
    - `_candidates_from_goal(self, frame: Any, timestamp: float)`
    - `_candidates_from_risk_like_fields(self, frame: Any, timestamp: float)`
    - `_candidates_from_social_like_fields(self, frame: Any, timestamp: float)`
    - `_candidates_from_body_state(self, frame: Any, timestamp: float)`
    - `_candidates_from_temporal_constraints(self, frame: Any, timestamp: float)`
    - `_select_items(self, candidates: list[WorkspaceItem], budget_mode: WorkspaceBudgetMode, now_ts: float)` — Chọn items theo score, quota, privacy, duplicate và context pressure.
    - `_suppression_reason(self, item: WorkspaceItem, selected: list[WorkspaceItem], seen_summaries: list[str], kind_counts: dict[str, int], now_ts: float)`
    - `_suppress(self, item: WorkspaceItem, reason: WorkspaceSuppressionReason)`
    - `_select_evidence(self, frame: Any, selected: list[WorkspaceItem], budget_mode: WorkspaceBudgetMode)`
    - `_select_memory(self, frame: Any, selected: list[WorkspaceItem], budget_mode: WorkspaceBudgetMode)`
    - `_select_affect(self, frame: Any, selected: list[WorkspaceItem])`
    - `_select_goal(self, frame: Any, selected: list[WorkspaceItem])`
    - `_select_risks(self, frame: Any, selected: list[WorkspaceItem])`
    - `_select_social_hypotheses(self, frame: Any, selected: list[WorkspaceItem])`
    - `_select_body_state(self, frame: Any, selected: list[WorkspaceItem])`
    - `_derive_dominant_thread(self, frame: Any, selected: list[WorkspaceItem])`
    - `_derive_active_threads(self, frame: Any, selected: list[WorkspaceItem], dominant_thread: Optional[str])`
    - `_derive_forbidden_assumptions(self, frame: Any, selected: list[WorkspaceItem], risks: list[WorkspaceRisk], social_hypotheses: list[WorkspaceSocialHypothesis])`
    - `_calculate_context_pressure(self, selected: list[WorkspaceItem], suppressed: list[SuppressedWorkspaceItem], budget_mode: WorkspaceBudgetMode)`
    - `_calculate_broadcast_priority(self, selected: list[WorkspaceItem], risks: list[WorkspaceRisk])`
    - `_calculate_confidence(self, selected: list[WorkspaceItem])`
    - `_build_broadcast_reason(self, selected: list[WorkspaceItem], suppressed: list[SuppressedWorkspaceItem], dominant_thread: Optional[str], broadcast_priority: float, context_pressure: float)`
    - `_build_downstream_contract(self, selected: list[WorkspaceItem], risks: list[WorkspaceRisk], social_hypotheses: list[WorkspaceSocialHypothesis])` — Gợi ý module downstream nên đọc phần nào. Đây là tài liệu runtime, không phải luật cứng.
    - `_classify_slot_kind(self, name: str, content: Any)`
    - `_kind_from_tags_or_text(self, tags: Sequence[str], text: str, fallback: WorkspaceItemKind)`
    - `_scopes_for_kind(self, kind: WorkspaceItemKind)`
    - `_score_evidence_priority(self, claim: str, tags: Sequence[str], source: str, confidence: float, reliability: float, raw_or_inferred: str, age_seconds: float)`
    - `_summarize_pressure_object(self, obj: Any, preferred_fields: Sequence[str])`
    - `_goal_summary(self, goal: Any)`
    - `_extract_risk(self, source: Any)`
    - `_extract_social_hypothesis(self, source: Any)`
    - `_body_summary(self, source: Any)`
    - `_temporal_summary(self, temporal: Any)`
    - `_attach_to_frame(self, frame: Any, workspace: WorkspaceFrame)` — Gắn workspace và ModuleReport vào frame nếu frame hỗ trợ.

## `cortex/goal_persistence.py`
- LOC: 737
- Functions:
  - `_stable_goal_id(summary: str)`
  - `_as_tuple(value: object, *, limit: int=8)`
- Classes:
  - `GoalPersistenceState` (decorator=dataclass(slots=True)) — Một luồng nền bền.
    - `active(self)`
    - `can_intervene(self)` — ERIS có được phép chủ động nhắc goal này hay không.
    - `to_dict(self)`
    - `from_dict(cls, data: object)`
    - `render_prompt_context(self)` — Văn bản dành cho prompt LLM.
    - `render_ni_context(self)` — Ngữ cảnh goal nén, máy đọc được, dành cho Ni.
  - `GoalCandidate` (decorator=dataclass(frozen=True, slots=True))
  - `GoalPersistenceEngine` — Nâng lực kéo nhận thức lặp lại thật thành một luồng nền bền.
    - `update(self, state: GoalPersistenceState, *, channel: str, snapshot=None, ni_report=None, ti_report=None, thought_stream_report=None, broadcast=None, user_text: str='', force_speak: bool=False, now: float | None=None)`
    - `_candidate(self, *, channel: str, snapshot, ni_report, ti_report, thought_stream_report, broadcast, user_text: str, force_speak: bool)`
    - `_from_user_signal(self, signal: GoalTextSignal, *, channel: str, ni_report)`
    - `_from_thought_momentum(self, thought_stream_report, *, ni_report)`
    - `_from_thought_attractor(self, thought_stream_report, *, ni_report)`
    - `_from_ti_realign(self, ti_report, *, broadcast, snapshot, ni_report)`
    - `_merge(self, state: GoalPersistenceState, candidate: GoalCandidate, *, now: float)`
    - `_decay(self, state: GoalPersistenceState, *, now: float, soft_reactivation: str='')`
    - `_close(self, state: GoalPersistenceState, *, now: float, evidence: str)`
    - `_match_score(self, state: GoalPersistenceState, candidate: GoalCandidate)`
    - `_hint_for_kind(self, kind: str)`
    - `_looks_goal_worthy(self, text: str)`
    - `_has_closure(self, user_text: str, *, thought_stream_report)`
    - `_matches(self, left: str, right: str)`

## `cortex/greeting_cognition.py`
- LOC: 318
- Functions:
  - `clamp01(value)`
  - `clean_text(value: object, *, limit: int=180)`
- Classes:
  - `GreetingFrame` (decorator=dataclass(frozen=True)) — A small cognitive frame for startup greetings.
    - `to_prompt_block(self)`
  - `GreetingCognitionEngine` — Builds a cognition frame for startup greetings.
    - `_fallback_pool(self, frame: GreetingFrame)`
    - `_normalized_surface(self, text: str)`
    - `_fallback_index(self, frame: GreetingFrame, *, pool_size: int)`
    - `build(self, *, presence_restored: bool=False, continuity_restored: bool=False, active_goal: str='', current_attractor: str='', unresolved_loops: tuple[str, ...]=(), recent_direction: str='', self_continuity: str='', tone: str='', greeted_recently: bool=False, relational_feedback: str='')`
    - `from_prompt_context(self, context: str)`
    - `deterministic_greeting(self, frame: GreetingFrame, *, avoid_text: str='')`

## `cortex/greeting_quality.py`
- LOC: 173
- Functions:
  - `normalize_text(text: str)`
- Classes:
  - `GreetingQuality` (decorator=dataclass(frozen=True))
    - `accepted(self)`
  - `GreetingQualityScorer` — Scores startup greeting surface quality.
    - `__init__(self, *, cognition: GreetingCognitionEngine | None=None)`
    - `score(self, text: str, frame: GreetingFrame)`
    - `choose_best(self, candidates: list[str] | tuple[str, ...], frame: GreetingFrame, *, avoid_text: str='')`
    - `_marker_score(self, normalized: str, markers: tuple[str, ...])`
    - `_text_touches_anchor(self, text: str, anchor: str)`

## `cortex/growth_consolidator.py`
- LOC: 152
- Docstring: growth_consolidator.py — Tác_Tử_Nền sinh Đề_Xuất_Nhích cho long-arc.
- Functions:
  - `_f(value)`
- Classes:
  - `GrowthObservation` (decorator=dataclass(slots=True)) — Một quan sát đã-lọc, gắn vào một phiên cụ thể.
  - `GrowthConsolidatorConfig` (decorator=dataclass(slots=True))
  - `GrowthConsolidator`
    - `__init__(self, config: GrowthConsolidatorConfig | None=None)`
    - `should_run(self, *, idle_pressure: float=0.0, consolidation_pressure: float=0.0, budget_allows: bool=True, user_interacting_high_risk: bool=False)`
    - `consolidate(self, observations: Iterable[GrowthObservation], *, allowed_evidence_ids: Iterable[str], profile=None)`
    - `_anchors(obs_list: list[GrowthObservation])`

## `cortex/growth_evidence.py`
- LOC: 83
- Docstring: growth_evidence.py — phiên dịch ký-ức-thật → GrowthObservation.
- Functions:
  - `_rules_for(topic: str, sentiment: str)`
  - `_kind_for(sentiment: str)`
  - `observations_from_feedback(events: Iterable[Mapping[str, Any]])` — Trả (observations, allowed_evidence_ids). ``allowed`` là tập id THẬT để cổng

## `cortex/impulse_arbitration.py`
- LOC: 646
- Docstring: Impulse competition for ERIS.
- Functions:
  - `_priority(name: str)`
  - `build_default_impulse_candidates(stack: AgentStateStack, *, thought_surface: Any=None, conversation_context: str='')` — Tạo bộ impulse mặc định cho spontaneous/autonomous path.
  - `_has_real_thought_root(value: str, *, root_source: str='')` — Không cho inner_whim lấy pressure-only label làm topic root.
  - `_scene_anchor(ev)`
  - `_family_key(value: str)`
- Classes:
  - `ImpulseCandidate` (decorator=dataclass(slots=True))
    - `total(self)`
    - `score_note(self)`
    - `to_dict(self)`
  - `ArbitrationReport` (decorator=dataclass(slots=True))
    - `evidence_notes(self, limit: int=8)`
    - `to_dict(self)`
  - `ImpulseArbitrator` — Chọn impulse thắng bằng score, không viết output public.
    - `select(self, candidates: tuple[ImpulseCandidate, ...])`

## `cortex/inner_thought.py`
- LOC: 280
- Classes:
  - `InnerThoughtEngine` — Builds a social motive; it never writes the final spoken line.
    - `evaluate(self, *, channel: str, snapshot=None, internal_state=None, appraisal=None, broadcast=None, style_memory=None, concrete_signals: tuple[str, ...]=(), last_text: str='', repeat_count: int=1, repeated_topic_tag: str='', repeated_topic_streak: int=0, recent_inner_intents: tuple[str, ...]=(), recent_inner_seeds: tuple[str, ...]=(), subconscious_seed=None, thought_surface=None)`
    - `_force_speak_thought(self, *, broadcast, internal_state, style_memory, recent_inner_intents: tuple[str, ...], recent_inner_seeds: tuple[str, ...])`
    - `_autonomous_thought(self, *, snapshot, internal_state, appraisal, broadcast, style_memory, repeat_count: int, repeated_topic_tag: str, repeated_topic_streak: int, recent_inner_intents: tuple[str, ...], recent_inner_seeds: tuple[str, ...], thought_surface=None)`
    - `_thought_from_thought_surface(self, thought_surface, *, recent_inner_seeds: tuple[str, ...])`
    - `_choose_candidate(self, candidates, *, style_memory, recent_inner_intents: tuple[str, ...], recent_inner_seeds: tuple[str, ...])`
    - `_broadcast_anchor(self, broadcast)`
    - `_float(self, value)`

## `cortex/internal_agenda.py`
- LOC: 385
- Docstring: src/cortex/internal_agenda.py
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `_compact(text: Any, limit: int=360)`
  - `_fingerprint(kind: str, summary: str, evidence_ids: Iterable[str]=())`
- Classes:
  - `InternalAgendaItem` (decorator=dataclass(slots=True)) — Một mục agenda nội bộ.
    - `__post_init__(self)`
    - `is_open(self)`
    - `score(self)` — Điểm ưu tiên tổng hợp cho stack.
    - `expired(self, now: float | None=None)`
    - `touch(self, *, pressure: float | None=None, urgency: float | None=None, confidence: float | None=None, speech_value: float | None=None, evidence_ids: Iterable[str]=(), payload: Mapping[str, Any] | None=None)` — Cập nhật item theo kiểu merge mềm.
    - `decay(self, factor: float=0.94)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `InternalAgendaStack` — CRUD stack cho agenda nội bộ.
    - `__init__(self, *, max_items: int=64, backing_path: str | None=None, autosave: bool=True)`
    - `__len__(self)`
    - `items(self)`
    - `open_items(self)`
    - `add(self, *, kind: AgendaKind='misc', summary: str, evidence_ids: Iterable[str]=(), pressure: float=0.0, urgency: float=0.0, confidence: float=0.0, speech_value: float=0.0, source: str='runtime', ttl_seconds: float=3600.0, payload: Mapping[str, Any] | None=None, item_id: str='')`
    - `mark(self, item_id: str, status: AgendaStatus)`
    - `resolve(self, item_id: str)`
    - `block(self, item_id: str, reason: str='')`
    - `top_items(self, *, limit: int=5, min_score: float=0.0)`
    - `pressure(self)`
    - `decay(self, factor: float=0.94)`
    - `prune(self, now: float | None=None)`
    - `to_dict(self)`
    - `save(self, path: str | None=None)`
    - `from_mapping(cls, data: Mapping[str, Any])`
    - `_trim(self)`
    - `_load_from_disk(self)`
    - `_persist(self)`

## `cortex/internal_state.py`
- LOC: 2128
- Functions:
  - `_clamp(value: float, *, minimum: float=0.0, maximum: float=1.0)`
  - `_clamp_signed(value: float)`
  - `_smooth(previous: float, signal: float, *, inertia: float=0.84)`
  - `_clean_label(value: object, *, fallback: str='')`
  - `_clean_stance_blend(value: object)` — Làm sạch map stance_blend từ JSON: chỉ giữ key str -> float hữu hạn [0,1]-ish.
  - `_append_recent(items: tuple[str, ...], value: str, *, limit: int=8)`
  - `_default_process(cls, name: str, *, level: float, pressure: float=0.0, volatility: float, decay_rate: float)`
- Classes:
  - `MentalProcess` (decorator=dataclass(slots=True)) — A low-gain dynamic process, not a stored emotion label.
    - `evolve(self, *, signal: float=0.0, interaction: float=0.0, dt: float=1.0)`
    - `dampen(self, amount: float)`
    - `excite(self, amount: float)`
    - `to_dict(self)`
    - `from_dict(cls, data: object, *, name: str, level: float=0.0, pressure: float=0.0)`
  - `CuriosityProcess` (base=MentalProcess)
  - `RestraintProcess` (base=MentalProcess)
  - `TensionProcess` (base=MentalProcess)
  - `ContinuityProcess` (base=MentalProcess)
  - `AttachmentProcess` (base=MentalProcess)
  - `ReflectionProcess` (base=MentalProcess)
  - `SocialPresenceProcess` (base=MentalProcess)
  - `CognitiveLoadProcess` (base=MentalProcess)
  - `BackgroundThoughtProcess` (base=MentalProcess)
  - `MentalProcessSystem` (decorator=dataclass(slots=True)) — Dynamic mental layer whose processes evolve and influence each other.
    - `evolve(self, *, channel: str, snapshot=None, ni_report=None, ti_report=None, fe_plan=None, broadcast=None, social_presence_event=None, user_text: str='', force_speak: bool=False, dt: float=1.0)`
    - `commit(self, *, channel: str, speech_act: str='', winner_label: str='', thought_surface=None, was_spoken: bool=False, no_speech: bool=False)`
    - `process_axes(self)`
    - `to_prompt_context(self)`
    - `to_dict(self)`
    - `from_dict(cls, data: object, *, raw_state: dict[str, object] | None=None)`
    - `_interactions(self)`
    - `_dampen_for_speech(self, label: str)`
    - `_axis_for_label(self, label: str)`
  - `DesireDynamics` (decorator=dataclass(slots=True)) — Low-gain wanting layer: preference, avoidance, attachment drift, and residue.
    - `evolve(self, *, channel: str, snapshot=None, user_text: str='', force_speak: bool=False, attachment: float=0.0, protectiveness: float=0.0, fatigue: float=0.0, silence_pressure: float=0.0, thought_stream_report=None, dt: float=1.0)`
    - `commit(self, *, channel: str, speech_act: str='', was_spoken: bool=False, no_speech: bool=False, thought_surface=None)`
    - `to_dict(self)`
    - `from_dict(cls, data: object)`
    - `to_prompt_context(self)`
    - `_infer_attraction(self, *, focus_kind: str, active_app: str, captured_at: str, idle_seconds: float, recent_events: tuple[str, ...])`
    - `_infer_aversion(self, *, focus_pattern: str, switching: str, recent_events: tuple[str, ...])`
    - `_infer_attention_hook(self, *, channel: str, idle_seconds: float, focus_pattern: str, recent_events: tuple[str, ...])`
    - `_infer_anticipation_signal(self, *, recent_events: tuple[str, ...], focus_pattern: str)`
    - `_infer_unresolved(self, *, thought_stream_report, fallback: str)`
    - `_choose_echo(self, *, attraction: str, aversion: str, hook: str, unfinished: str, previous: str)`
    - `_attachment_drift(self, *, heat: float, cool: float, cling: float, avoid: float, protectiveness: float)`
    - `_merge_patterns(self, current: tuple[str, ...], incoming)`
    - `_hour(self, captured_at: str)`
  - `PersistentInternalState` (decorator=dataclass(slots=True)) — Runtime continuity state, not a claim about real emotion.
    - `to_dict(self)`
    - `from_dict(cls, data: dict[str, object])`
    - `to_prompt_context(self)`
  - `CognitionDelta` (decorator=dataclass(frozen=True, slots=True)) — Low-gain temporal delta applied before event-specific appraisal.
  - `TemporalCognitionEngine` — Turns time, memory, unresolved loops, and event impulses into state drift.
    - `compute_delta(self, state: PersistentInternalState, *, now: float | None=None, elapsed_seconds: float | None=None, memory_resonance=None, thought_stream_report=None)`
    - `apply(self, state: PersistentInternalState, delta: CognitionDelta, *, now: float | None=None)`
  - `InternalStateEngine` — Maintains a low-gain continuity state across cognitive frames.
    - `__init__(self, *, temporal_engine: TemporalCognitionEngine | None=None)`
    - `commit_session_ritual(self, state: PersistentInternalState, *, session_ritual, now: float | None=None)` — Marks a startup continuity restore without treating it as a full turn.
    - `sense_update(self, state: PersistentInternalState, *, channel: str, snapshot=None, ni_report=None, ti_report=None, fe_plan=None, broadcast=None, memory_resonance=None, thought_stream_report=None, social_presence_event=None, user_text: str='', force_speak: bool=False, elapsed_seconds: float | None=None, now: float | None=None)`
    - `commit_turn(self, state: PersistentInternalState, *, channel: str, snapshot=None, ti_report=None, appraisal=None, speech_core=None, action_plan=None, inner_thought=None, subconscious_seed=None, thought_surface=None, self_state=None, was_spoken: bool=False)`
    - `render_prompt_context(self, state: PersistentInternalState)`
    - `_commit_pressure_axes(self, *, state: PersistentInternalState, channel: str, speech_act: str, speech_core, no_speech: bool, was_spoken: bool, silence_ticks: int)`
    - `_motivation_winner_label(self, speech_core)`
    - `_pressure_axis_for_act(self, value: str)`
    - `_derive_notes(self, *, focus_kind: str, stance: str, speech_act: str, inner_intent: str, silence_ticks: int, silence_pressure: float, boredom: float, protectiveness: float, was_spoken: bool)`

## `cortex/low_level_speech_policy.py`
- LOC: 352
- Docstring: Policy knobs for low-level surface speech.
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `_int_from_env(name: str, default: int, *, minimum: int=0)`
  - `_float_from_env(name: str, default: float, *, minimum: float=0.0, maximum: float=1.0)`
  - `_tuple_from_env(name: str, default: tuple[str, ...])`
  - `_bool_value(value: Any, default: bool=False)`
  - `_tuple_from_value(value: Any, default: tuple[str, ...])`
  - `_parse_scalar(value: str)`
  - `_load_simple_yaml(path: str | os.PathLike[str])` — Load một file YAML rất nhỏ mà không bắt buộc PyYAML.
  - `_default_policy_config_path()`
- Classes:
  - `LowLevelSpeechPolicyConfig` (decorator=dataclass(slots=True)) — Config dễ tune cho SurfaceArbiter.
    - `from_env(cls)`
    - `from_yaml_file(cls, path: str | os.PathLike[str])`
    - `from_mapping(cls, data: Mapping[str, Any] | None, *, use_env: bool=True)`
  - `LowLevelSpeechPolicy` — Quyết định generation mode cho utterance thấp tầng.
    - `__init__(self, config: LowLevelSpeechPolicyConfig | Mapping[str, Any] | str | os.PathLike[str] | None=None)`
    - `_is_presence_kind(self, kind: str)`
    - `decide_generation_mode(self, impulse, silent_cycles: int, *, speak_bias: float=0.0)`

## `cortex/meaning/__init__.py`
- LOC: 23
- Docstring: cortex.meaning — Phase 2 meaning layer package.

## `cortex/meaning/ambiguity.py`
- LOC: 196
- Docstring: ambiguity.py — AmbiguityModule (định lượng mơ hồ).
- Classes:
  - `AmbiguityResult` (decorator=dataclass(slots=True)) — Kết quả lượng hoá độ mơ hồ.
  - `AmbiguityModule` — Lượng hoá độ mơ hồ của một tập scored hypotheses (stateful).
    - `__init__(self)`
    - `last_value(self)` — Giá trị ambiguity hợp lệ gần nhất đã tính (chỉ-đọc, để debug).
    - `compute(self, hypotheses: Sequence[Any])` — Tính ``AmbiguityResult`` cho ``hypotheses``.
    - `_extract_valid_confidences(items: Sequence[Any])` — Trích ``confidence`` từng item, kiểm phải là số thực ∈ [0,1].

## `cortex/meaning/config.py`
- LOC: 91
- Docstring: config.py — ``Phase2Config`` (nguồn duy nhất của mọi threshold) và ``StageLedger``.
- Classes:
  - `Phase2Config` (decorator=dataclass(slots=True)) — Tập trung mọi ngưỡng của pipeline Phase 2 vào một nơi.
  - `StageLedger` — Ghi nhận stage nào đã sinh đầu ra cho ``frame_id`` nào.
    - `__init__(self)`
    - `record(self, stage: str, frame_id: str)` — Đánh dấu ``stage`` đã sinh đầu ra cho ``frame_id``.
    - `has(self, stage: str, frame_id: str)` — True nếu ``stage`` đã được ghi nhận cho đúng ``frame_id`` này.

## `cortex/meaning/contracts.py`
- LOC: 273
- Docstring: contracts.py — Shared Phase 2 data models, ``clamp01`` helper và errors.
- Functions:
  - `clamp01(value: float)` — Kẹp một chỉ số (confidence/ambiguity/overread_risk) về [0.0, 1.0].
- Classes:
  - `RawWorldAccessError` (base=RuntimeError) — R1.2 — Một stage Phase 2 cố đọc field ngoài hợp đồng / kênh Raw_World.
    - `__init__(self, module_name: str, field_name: str)`
  - `InvalidWorkspaceFrameError` (base=ValueError) — R2.6 — WorkspaceFrame malformed / không parse được; không sinh scene.
  - `WorldSceneValidationError` (base=ValueError) — R3.5 — WorldScene rỗng/None/sai cấu trúc khi WorldInterpreter chạy.
  - `ConfigurationError` (base=ValueError) — R11.3, R11.4 — Taxonomy cấu hình sai (trùng id hoặc id không hợp lệ).
    - `__init__(self, category_id: str, set_name: str)`
  - `WorldSceneElement` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
  - `WorldScene` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
  - `Observation` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
  - `ContextAnnotation` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
  - `MeaningHypothesis` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
  - `PragmaticIntent` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
  - `EvaluatedConclusion` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
  - `SurfaceDecision` (decorator=dataclass(slots=True))
  - `Phase2Result` (decorator=dataclass(slots=True))
  - `StageDebug` (decorator=dataclass(slots=True))
    - `__post_init__(self)`

## `cortex/meaning/debug_render.py`
- LOC: 206
- Docstring: debug_render.py — ``DebugRender`` + ``Phase2Run`` (stage debug, R12).
- Functions:
  - `_render_metric(value: float | None)` — Render một chỉ số: ``f"{value:.3f}"`` khi có giá trị, else ``"unavailable"`` (R12.5).
- Classes:
  - `Phase2Run` (decorator=dataclass(slots=True)) — Ảnh chụp nhẹ một lần chạy pipeline Phase 2 phục vụ debug render.
  - `DebugRender` — Render một ``Phase2Run`` thành chuỗi nhiều dòng người-đọc-được (R12).
    - `render(self, run: Phase2Run)` — Trả bản ghi debug nhiều dòng cho ``run`` (R12.1, R12.2, R12.4–R12.6).
    - `_render_stage(self, sd: StageDebug)` — Render một ``StageDebug``: tên stage + ba chỉ số + missing fields / notes.
    - `_render_withheld(self, result: Phase2Result | None)` — Render mọi kết luận bị giữ lại / chặn kèm lý do.
    - `_render_decision(decision: SurfaceDecision)` — Render một ``SurfaceDecision`` bị withheld kèm lý do (R12.2).
    - `_render_evaluated(ev: EvaluatedConclusion)` — Render một ``EvaluatedConclusion`` bị giữ lại, phản chiếu overread-suppress.

## `cortex/meaning/meaning_hypothesis.py`
- LOC: 473
- Docstring: meaning_hypothesis.py — ``MeaningHypothesisEngine`` (stage 4 của Phase 2).
- Classes:
  - `MeaningHypothesisEngine` — Adapter bọc ``SemanticHypothesisEngine`` + ``MeaningLayer`` (stage 4).
    - `__init__(self, *, semantic_engine: 'SemanticHypothesisEngine', meaning_layer: 'MeaningLayer', ambiguity_module: AmbiguityModule, config: Phase2Config | None=None)`
    - `generate(self, annotations: list[ContextAnnotation], *, frame_id: str)` — Sinh tập ``MeaningHypothesis`` từ các ``ContextAnnotation``.
    - `_adapt(self, sem: 'SemanticHypothesis', *, index: int, frame_id: str, evidence_ids: list[str], report_ambiguity: float, family: str, slot_summary: str)` — Adapt một ``SemanticHypothesis`` thành ``MeaningHypothesis``.
    - `_overread_risk(self, sem: 'SemanticHypothesis', *, evidence_count: int)` — Suy ``overread_risk`` ∈ [0,1] từ fallback/biên độ/đủ evidence.
    - `_raise_near_tie_ambiguity(self, hypotheses: list[MeaningHypothesis])` — R5.3 — hai+ hypothesis có ``|Δconfidence| ≤ margin`` → tăng ambiguity.
    - `_map_category(label: str, family: str)` — Ánh xạ xác định label/semantic_family → ``Taxonomy.MEANING`` id.
    - `_insufficient_evidence_hypothesis(self, frame_id: str)` — Sinh đúng MỘT hypothesis "insufficient evidence" (R5.4).
    - `_build_text(items: Sequence[ContextAnnotation])` — Ghép các ``observation.summary`` thành text để feed semantic engine.
    - `_collect_evidence_ids(items: Sequence[ContextAnnotation])` — Gom evidence_ids từ mọi annotation, dedupe, giữ thứ tự xuất hiện.
    - `_collect_anchors(items: Sequence[ContextAnnotation])` — Gom anchor tag nhẹ từ register/relationship để hỗ trợ semantic match.
    - `_evaluate_meaning_slot(self, text: str)` — DELEGATE tới ``MeaningLayer.evaluate`` để lấy vật liệu meaning-slot.
    - `_slot_summary(meaning_slot: Any)` — Rút một mẩu summary người-đọc-được từ meaning-slot (nếu có).
    - `_normalize(text: str)` — Chuẩn hoá nhẹ cho so khớp keyword: lowercase + strip.
    - `_build_debug(hypotheses: Sequence[MeaningHypothesis], notes: list[str])` — Gom ``StageDebug`` với chỉ số tổng hợp của tập hypothesis.

## `cortex/meaning/meaning_layer.py`
- LOC: 691
- Classes:
  - `MeaningLayer` — Maps Se/telemetry facts into private pressure signals before speech.
    - `__init__(self)`
    - `evaluate(self, *, snapshot=None, broadcast=None, internal_state=None, thought_stream_report=None, channel: str='', user_text: str='', force_speak: bool=False, recent_families: tuple[str, ...]=())`
    - `_build_result(self, source_fact: str, *, recent_families: tuple[str, ...], meaning_shift: bool, meaning_signal: str, shift_reason: str, evidence: tuple[str, ...]=())`
    - `_private_signals(self, *, source_fact: str, meaning: str, reaction: str, attitude: str)`
    - `_meaning_expansion_slots(self, *, source_fact: str, meaning: str, secondary: tuple[str, ...], evidence: tuple[str, ...])` — Mở rộng fact thành meaning dùng được cho action, không phải câu nói.
    - `render_prompt_context(self, result: MeaningLayerResult)`
    - `_render_empty_context(self, result_or_recent)`
    - `_maybe_prolonged_fact(self, source_fact: str, *, snapshot, internal_state, recent_families: tuple[str, ...], evidence: tuple[str, ...])` — Biến "không đổi" thành meaning mới khi nó kéo dài đủ lâu.
    - `_prolonged_threshold_seconds(self, *, focus_kind: str, source_fact: str)`
    - `_focus_kind(self, snapshot)`
    - `_infer_ambient_fact(self, *, snapshot, internal_state)`
    - `_infer_fact(self, *, snapshot, broadcast, internal_state, thought_stream_report, user_text: str)`
    - `_text_parts(self, snapshot, broadcast, thought_stream_report, user_text: str)`
    - `_safe_evidence(self, snapshot, broadcast, *, extra: tuple[str, ...]=())`
    - `_normalize(self, text: str)`
    - `_float(self, value)`

## `cortex/meaning/overread_brake.py`
- LOC: 356
- Docstring: overread_brake.py — ``OverreadBrake`` (phanh phán bậy, stage 8 của Phase 2).
- Classes:
  - `OverreadBrake` — Phanh phán bậy — giảm/chặn kết luận theo overread_risk & evidence (stage 8).
    - `__init__(self, config: Phase2Config | None=None, *, reduction_threshold: float | None=None, suppression_threshold: float | None=None, reduced_conf_cap: float | None=None, min_evidence_count: int | None=None)` — Khởi tạo brake.
    - `evaluate(self, conclusions: list[Conclusion], *, forbidden_assumptions: list[str])` — Đánh giá brake cho từng kết luận.
    - `_evaluate_one(self, conclusion: Conclusion, forbidden: Sequence[str])` — Áp luật brake cho một kết luận, theo đúng precedence đã ghi.
    - `_evidence_ids(conclusion: Conclusion)` — Trích danh sách evidence một cách tổng quát.
    - `_kind(conclusion: Conclusion)` — Phân loại kết luận: ``meaning`` | ``intent`` | ``mental_state``.
    - `_conclusion_id(conclusion: Conclusion)` — Trích id ổn định: ``hypothesis_id`` / ``intent_id`` / ``inference_id``.
    - `_summary_text(conclusion: Conclusion)` — Văn bản tóm tắt để dò forbidden assumption.
    - `_normalize_forbidden(forbidden_assumptions: list[str] | None)` — Chuẩn hóa danh sách forbidden: bỏ None/rỗng/space, giữ chuỗi gốc.
    - `_matched_forbidden(summary: str, forbidden: Sequence[str])` — Trả forbidden assumption ĐẦU TIÊN xuất hiện (substring, case-insensitive).
    - `_build_debug(evaluated: Sequence[EvaluatedConclusion])` — Gom ``StageDebug`` cho stage brake (giữ thống kê, kể cả suppressed).

## `cortex/meaning/pipeline.py`
- LOC: 317
- Docstring: pipeline.py — ``Phase2MeaningPipeline`` facade (task 18.1).
- Functions:
  - `_resolve_tom_boldness()` — Boldness hiệu dụng: hằng số nền + độ-dám-đọc long-arc (nếu feature bật).
- Classes:
  - `Phase2MeaningPipeline` — Facade chạy toàn bộ pipeline Phase 2 theo đúng thứ tự bắt buộc.
    - `__init__(self, *, config: Optional[Phase2Config]=None, semantic_engine: Optional['SemanticHypothesisEngine']=None, meaning_layer: Optional['MeaningLayer']=None)`
    - `run(self, frame: Optional['WorkspaceFrame'])` — Chạy frame qua toàn bộ pipeline, trả ``Phase2Result``.
    - `_view_for(root_view: Optional[FrameReadView], module: str)` — Trả view đã scope theo ``module`` (hoặc ``None`` khi không có frame).
    - `_get_semantic_engine(self)` — Trả ``SemanticHypothesisEngine``, lười dựng fallback xác định nếu cần.
    - `_read_forbidden(root_view: Optional[FrameReadView])` — Đọc ``forbidden_assumptions`` qua hợp đồng (module được phép đọc).
    - `_attach_debug(result: Phase2Result, frame_id: Optional[str], stage_debugs: List[StageDebug])` — Gắn danh sách ``StageDebug`` + một ``Phase2Run`` vào ``result.debug``.

## `cortex/meaning/pragmatic_intent.py`
- LOC: 312
- Docstring: pragmatic_intent.py — ``PragmaticIntentEngine`` (stage 5 của Phase 2).
- Classes:
  - `PragmaticIntentEngine` — Suy ``PragmaticIntent`` từ tập ``MeaningHypothesis`` (stage 5).
    - `derive(self, hypotheses: list[MeaningHypothesis], *, frame_id: str)` — Suy tập ``PragmaticIntent`` từ ``hypotheses``.
    - `_build_intent(self, frame_id: str, intent_category: str, group: Sequence[MeaningHypothesis])` — Dựng một ``PragmaticIntent`` từ nhóm supporter cùng intent category.
    - `_aggregate_confidence(group: Sequence[MeaningHypothesis])` — Confidence ∈ [0,1] của intent — hàm thuần của supporter (R6.3, R6.4).
    - `_collect_support_ids(group: Sequence[MeaningHypothesis])` — Hợp nhất ``hypothesis_id`` của nhóm, dedupe, giữ thứ tự xuất hiện.
    - `_map_intent(cls, meaning_category: str, summary: str)` — Ánh xạ xác định MEANING category (+summary) → ``Taxonomy.INTENT`` id.
    - `_build_debug(intents: Sequence[PragmaticIntent], notes: list[str])` — Gom ``StageDebug`` với chỉ số tổng hợp của tập intent.

## `cortex/meaning/read_contract.py`
- LOC: 230
- Docstring: read_contract.py — ReadContract guard (WorkspaceFrame-only enforcement).
- Classes:
  - `FrameReadView` — Boundary đọc có kiểu, bọc một ``WorkspaceFrame``.
    - `__init__(self, frame: 'WorkspaceFrame', *, module: Optional[str]=None, stage: Optional[str]=None)`
    - `for_module(self, module: str, *, stage: Optional[str]=None)` — Trả về một view mới gắn ``module`` làm mặc định cho mọi lần đọc.
    - `frame_id(self)` — ``frame_id`` luôn đọc được — đây là metadata định danh, không phải
    - `module(self)`
    - `allowed_fields(self, module: Optional[str]=None)` — Danh sách field mà ``module`` được phép đọc theo hợp đồng.
    - `can_read(self, field_name: str, module: Optional[str]=None)` — ``True`` nếu ``module`` được phép đọc ``field_name`` (không ném).
    - `read(self, field_name: str, module: Optional[str]=None)` — Đọc một field của ``WorkspaceFrame`` qua hợp đồng.
    - `evidence_ids(self, module: Optional[str]=None)` — ``WorkspaceFrame.evidence_ids()`` qua guard (cần đọc ``broadcast_items``).
    - `items_by_kind(self, kind: Any, module: Optional[str]=None)` — ``WorkspaceFrame.items_by_kind(kind)`` qua guard.
    - `surface_items(self, scope: Any=None, module: Optional[str]=None)` — ``WorkspaceFrame.surface_items(scope)`` qua guard.
    - `_resolve_module(self, module: Optional[str])`
    - `_require(self, module_name: str, field_name: str)` — Kiểm tra quyền đọc ``field_name``; vi phạm -> ghi debug + ném.
    - `_deny(self, module_name: str, field_name: str, *, reason: str)` — Ghi vi phạm vào ``debug.contract_violations`` rồi ném lỗi.

## `cortex/meaning/sociocultural_context.py`
- LOC: 262
- Docstring: sociocultural_context.py — Stage 3: Observation set -> ContextAnnotation set.
- Classes:
  - `SocioculturalContext` — Stage 3 của pipeline meaning: gắn ngữ cảnh xã hội - văn hóa.
    - `annotate(self, observations: list[Observation], view: FrameReadView)` — Annotate mỗi observation với ba loại ngữ cảnh xã hội - văn hóa.
    - `_resolve_context(self, *, has_social: bool, has_forbidden: bool)` — Suy ba loại ngữ cảnh + danh sách loại đã dùng neutral default.
    - `_collect_unconfirmed(self, social_hypotheses: list[Any])` — Chuyển ``social_hypotheses`` thành chuỗi *chưa xác nhận* (R4.2).
    - `_hypothesis_text(hyp: Any)`
    - `_annotation_confidence(observation: Observation, defaults_applied: list[str])` — Confidence cho annotation ∈ [0,1] (R4.5).
    - `_safe_frame_id(view: Optional[FrameReadView])`
    - `_read_field(view: Optional[FrameReadView], field_name: str)` — Đọc một field qua ``FrameReadView`` với guard.

## `cortex/meaning/surface_meaning_policy.py`
- LOC: 274
- Docstring: surface_meaning_policy.py — ``SurfaceMeaningPolicy`` (phân vùng surfaced / withheld, stage 9).
- Classes:
  - `SurfaceMeaningPolicy` — Phân vùng surfaced / withheld theo precedence cố định (stage 9).
    - `__init__(self, config: Phase2Config | None=None, *, surface_conf_threshold: float | None=None, ambiguity_threshold: float | None=None)` — Khởi tạo policy.
    - `partition(self, evaluated: list[EvaluatedConclusion], *, frame_id: str)` — Phân từng ``EvaluatedConclusion`` vào surfaced HOẶC withheld.
    - `_classify(self, item: EvaluatedConclusion)` — Trả ``(status, reason)`` cho một kết luận theo precedence trên xuống.
    - `_ambiguity(item: EvaluatedConclusion)` — Đọc ``ambiguity`` của conclusion một cách tổng quát.
    - `_evidence_ids(item: EvaluatedConclusion)` — Trích evidence một cách tổng quát (giống ``OverreadBrake``).
    - `_conclusion_id(item: EvaluatedConclusion)` — Trích id ổn định: ``hypothesis_id`` / ``intent_id`` / ``inference_id``.
    - `_build_debug(self, items: Sequence[EvaluatedConclusion], surfaced: Sequence[EvaluatedConclusion], withheld: Sequence[EvaluatedConclusion])` — Gom thông tin debug stage (counts + ngưỡng + bất biến surfaced-có-evidence).

## `cortex/meaning/taxonomy.py`
- LOC: 123
- Docstring: taxonomy.py — registry meaning/intent/mental-state categories + startup validation.
- Classes:
  - `Taxonomy` — Registry category tĩnh cho meaning / intent / mental-state.
    - `validate_on_startup(cls)` — Kiểm mỗi họ có id duy nhất và không rỗng (R11.1, R11.4).
    - `require(cls, set_name: str, category_id: str)` — Cổng bắt buộc trước mọi gán category (R11.2, R11.3).

## `cortex/meaning/world_interpreter.py`
- LOC: 186
- Docstring: world_interpreter.py — WorldScene -> Observation set (Phase 2, stage 2).
- Classes:
  - `WorldInterpreter` — Diễn giải ``WorldScene`` thành tập ``Observation`` (WorldScene-only).
    - `interpret(self, scene: WorldScene, *, low_conf_threshold: float=_DEFAULT_LOW_CONF_THRESHOLD)` — Rút ``(list[Observation], StageDebug)`` từ ``scene``.
    - `_validate_scene(scene: Optional[WorldScene])` — Cưỡng chế cấu trúc ``WorldScene`` hợp lệ (R3.5).
    - `_aggregate_confidence(observations: list[Observation])` — Confidence tổng hợp của stage = trung bình confidence observation.

## `cortex/meaning/world_scene_builder.py`
- LOC: 394
- Docstring: world_scene_builder.py — WorkspaceFrame -> WorldScene (Phase 2, stage 1).
- Classes:
  - `WorldSceneBuilder` — Dựng ``WorldScene`` từ một ``FrameReadView`` (WorkspaceFrame-only).
    - `build(self, view: Optional[FrameReadView])` — Dựng ``(WorldScene, StageDebug)`` từ ``view``.
    - `_read_required(self, view: FrameReadView, field_name: str, missing_fields: list[str])` — Đọc một field bắt buộc; ``None``/không đọc được -> ghi missing (R1.6).
    - `_read_optional(self, view: FrameReadView, field_name: str)` — Đọc một field tùy chọn; ``None`` là hợp lệ (không ghi missing).
    - `_element_from_item(self, item: Any)` — Adapt một ``WorkspaceItem`` -> ``WorldSceneElement``.
    - `_derive_confidence(item: Any)` — Suy ``confidence`` của element từ ``confidence``/``priority`` của item.
    - `_build_threads(self, threads: list[str], dominant_thread: Any)` — Dựng element ``thread`` từ ``active_threads`` + đánh dominant (R2.3).
    - `_aggregate_confidence(elements: list[WorldSceneElement])` — Confidence của scene = trung bình confidence các element mang evidence.

## `cortex/micro_contracts.py`
- LOC: 244
- Functions:
  - `clamp01(value)` — Ép số về 0..1, chống NaN và input kỳ quặc.
  - `normalize_text(text: str)` — Chuẩn hóa tiếng Việt cho heuristic bề mặt.
  - `clean_family(family: str)` — Làm sạch semantic family để tránh leak ký tự lạ vào trace.
  - `family_source_is_trusted(source: str)`
  - `word_count(text: str)`
  - `content_tokens(text: str, *, min_len: int=3)` — Token nội dung nhẹ, bỏ filler phổ biến để tính fingerprint/overlap.
  - `lexical_fingerprint(text: str, *, max_tokens: int=8)` — Fingerprint bề mặt để bắt câu y hệt/gần y hệt.
  - `phrase_in_normalized(normalized: str, phrase: str)` — Match phrase có biên token tương đối sạch.
  - `any_phrase(normalized: str, phrases: tuple[str, ...] | list[str] | set[str])`
  - `dedupe_issues(issues: list[ValidationIssue] | tuple[ValidationIssue, ...])`
- Classes:
  - `MicroLinePolicyResult` (decorator=dataclass(frozen=True, slots=True)) — Kết quả bước chọn dạng câu trước khi gọi LLM hoặc trước khi gửi final.
    - `allowed(self)`
  - `SemanticRepeatResult` (decorator=dataclass(frozen=True, slots=True)) — Kết quả kiểm tra lặp nghĩa.
  - `ValidationIssue` (decorator=dataclass(frozen=True, slots=True)) — Một lỗi policy có severity rõ ràng.
  - `RelationalContext` (decorator=dataclass(frozen=True, slots=True)) — Context quan hệ dùng để giới hạn mức ERIS được lộ attachment.
  - `RelationalRewritePlan` (decorator=dataclass(frozen=True, slots=True)) — Plan rewrite relational, không phải câu thoại canon.
  - `Anchor` (decorator=dataclass(frozen=True, slots=True)) — Nguồn neo cho một câu quan sát.

## `cortex/micro_grounding_guard.py`
- LOC: 263
- Classes:
  - `MicroGroundingGuard` — Guard grounding cho micro-line.
    - `signal_score(self, *, broadcast, vision_fact: str)`
    - `candidate_signal_score(self, candidate)`
    - `resolve_anchor(self, *, line_type: str, broadcast, vision_fact: str, user_action: str, session_context: str)` — Tìm anchor cho observation.
    - `risk_level_for_line(self, *, line_type: str, signal_score: float, requested: str='')`
    - `validate(self, text: str, *, line_type: str, risk_level: str='', anchor_source: str='', anchor_text: str='', user_action: str='', session_context: str='', screen_evidence: str='')`
    - `_validate_observation_anchor(self, text: str, *, line_type: str, anchor_source: str, anchor_text: str, user_action: str, session_context: str, screen_evidence: str)`
    - `_validate_claim_risk(self, text: str, *, line_type: str, risk_level: str, screen_evidence: str)`
    - `_validate_capability_claim(self, text: str, *, screen_evidence: str, user_action: str)`
    - `text_matches_anchor(self, text: str, anchor: str)`
    - `looks_like_hard_fact_claim(self, text: str)`
    - `looks_like_screen_claim(self, text: str)`
    - `looks_like_question(self, text: str)`

## `cortex/micro_policy.py`
- LOC: 440
- Classes:
  - `MicroLinePolicy` — Orchestrator cho micro-line policy.
    - `__init__(self, *, repeat_guard: SemanticRepeatGuard | None=None, surface_lint: MicroSurfaceLint | None=None, grounding_guard: MicroGroundingGuard | None=None)`
    - `evaluate(self, *, speech_intent: str, broadcast=None, vision_fact: str='', user_action: str='', session_context: str='', last_lines: tuple[str, ...]=(), channel: str='', speech_risk_level: str='', semantic_family: str='', meaning_family: str='', family_source: str='')` — Chọn line_type/risk/anchor trước khi sinh hoặc nhận final text.
    - `validate_text(self, *, allowed_line_type: str, text: str, speech_risk_level: str='', anchor_source: str='', anchor_text: str='', user_action: str='', session_context: str='', screen_evidence: str='', relational_context: RelationalContext | None=None, semantic_family: str='', meaning_family: str='', family_source: str='')` — Public API cũ: trả code lỗi cần hành động.
    - `validate_text_detailed(self, *, allowed_line_type: str, text: str, speech_risk_level: str='', anchor_source: str='', anchor_text: str='', user_action: str='', session_context: str='', screen_evidence: str='', relational_context: RelationalContext | None=None, semantic_family: str='', meaning_family: str='', family_source: str='')` — Kiểm tra final text với severity chi tiết.
    - `build_relational_rewrite_plan(self, text: str, *, relational_context: RelationalContext | None=None, allowed_line_type: str='')`
    - `rewrite_relational_line(self, text: str, *, relational_context: RelationalContext | None=None, allowed_line_type: str='')`
    - `relational_exposure_score(self, text: str)`
    - `_line_type_for_intent(self, intent: str)` — Map speech intent sang dạng câu nhỏ.
    - `_current_semantic_family(self, *, semantic_family: str, meaning_family: str, text: str)`
    - `_validate_surface_shape(self, *args, **kwargs)`
    - `_validate_grounding(self, text: str, **kwargs)`
    - `_validate_claim_risk(self, text: str, *, line_type: str, risk_level: str)`
    - `_validate_presence_residue(self, *args, **kwargs)`
    - `_validate_relational_permission(self, text: str, *, relational_context: RelationalContext | None)`
    - `_validate_semantic_repeat_surface(self, text: str, *, line_type: str, semantic_family: str, meaning_family: str)`
    - `_risk_level_for_line(self, *, line_type: str, signal_score: float, requested: str='')`
    - `_signal_score(self, *, broadcast, vision_fact: str)`
    - `_candidate_signal_score(self, candidate)`
    - `_resolve_anchor(self, *, line_type: str, broadcast, vision_fact: str, user_action: str, session_context: str)`
    - `_looks_like_placeholder(self, text: str)`
    - `_word_count(self, text: str)`
    - `_looks_like_unaccented_vietnamese(self, text: str)`
    - `_has_clear_short_meaning(self, text: str, **kwargs)`
    - `_text_matches_anchor(self, text: str, anchor: str)`
    - `_looks_like_question(self, text: str)`
    - `_looks_therapeutic(self, text: str)`
    - `_looks_like_hard_fact_claim(self, text: str)`
    - `_looks_like_decorative_metaphor_without_stance(self, text: str)`
    - `_semantic_density(self, text: str)`
    - `_looks_like_presence_narration(self, text: str)`
    - `_looks_like_blunt_emotion_declaration(self, text: str)`
    - `_relational_expression_issue(self, text: str, *, relational_context: RelationalContext | None)`
    - `_relational_permission_stage(self, relational_context: RelationalContext | None)`
    - `_looks_like_relational_expression(self, text: str)`
    - `_looks_like_continuity_pain(self, text: str)`
    - `_looks_like_clinginess_or_blackmail(self, text: str)`
    - `_relational_theme(self, normalized: str)`
    - `_allowed_exposure_for_stage(self, stage: str)`
    - `_clamp01(self, value)`
    - `_dedupe_issues(self, issues: list[ValidationIssue])`

## `cortex/micro_repeat_guard.py`
- LOC: 504
- Classes:
  - `SemanticRepeatGuard` — Chặn lặp semantic family, nhưng không để keyword fallback cầm lái.
    - `__init__(self, *, max_items: int=20, window_seconds: float | None=None, exact_repeat_seconds: float | None=None, semantic_encoder: object | None=None, semantic_threshold: float | None=None)`
    - `remember(self, text: str, *, timestamp: float | None=None, semantic_family: str='', family_source: str='', confidence: float=1.0)` — Lưu family/fingerprint của câu vừa nói.
    - `check(self, text: str, *, now: float | None=None, recent_lines: tuple[tuple[float, str], ...]=(), semantic_family: str='', meaning_family: str='', family_source: str='', semantic_confidence: float=1.0)` — Kiểm tra lặp.
    - `family_for_text(self, text: str)` — Backward compatible fallback family.
    - `family_for_text_with_source(self, text: str)`
    - `novelty_score(self, text: str, *, recent_lines: tuple[str, ...] | tuple[tuple[float, str], ...]=(), include_banned_seed: bool=True)` — Điểm tươi mới liên tục trong [0,1]: 1 = mới, 0 = trùng đồ cũ/đã nói.
    - `_max_similarity(self, candidate: str, references: list[str])` — Độ tương đồng cao nhất của candidate với tập references.
    - `_lexical_similarity(self, candidate: str, references: list[str])`
    - `_coerce_semantic_encoder(self, encoder: object | None)`
    - `_ensure_semantic_prototypes(self)`
    - `_semantic_family_for_text(self, text: str)`
    - `normalize(self, text: str)`
    - `_resolve_family(self, text: str, *, semantic_family: str='', family_source: str='', confidence: float=1.0)`
    - `_iter_recent(self, recent_lines: tuple[tuple[float, str], ...])`
    - `_clean_family(self, family: str)`

## `cortex/micro_surface_lint.py`
- LOC: 493
- Classes:
  - `MicroSurfaceLint` — Lint bề mặt cho micro-line.
    - `validate(self, text: str, *, line_type: str, risk_level: str='', anchor_source: str='', anchor_text: str='', user_action: str='', session_context: str='', screen_evidence: str='', relational_context: RelationalContext | None=None, directness_permission: float=0.0)`
    - `_validate_surface_shape(self, text: str, *, line_type: str, anchor_source: str, anchor_text: str, user_action: str, session_context: str, screen_evidence: str)`
    - `_validate_presence_residue(self, text: str, *, line_type: str, directness_permission: float=0.0)`
    - `_validate_relational_permission(self, text: str, *, relational_context: RelationalContext | None)`
    - `build_relational_rewrite_plan(self, text: str, *, relational_context: RelationalContext | None=None, allowed_line_type: str='')` — Tạo plan rewrite relational.
    - `relational_expression_issue(self, text: str, *, relational_context: RelationalContext | None)`
    - `relational_permission_stage(self, relational_context: RelationalContext | None)`
    - `relational_exposure_score(self, text: str)`
    - `looks_like_placeholder(self, text: str)`
    - `looks_like_unaccented_vietnamese(self, text: str)`
    - `has_clear_short_meaning(self, text: str, *, anchor_source: str, anchor_text: str, user_action: str, session_context: str, screen_evidence: str, line_type: str)`
    - `text_matches_anchor(self, text: str, anchor: str)`
    - `looks_like_question(self, text: str)`
    - `looks_therapeutic(self, text: str)`
    - `looks_like_decorative_metaphor_without_stance(self, text: str)`
    - `semantic_density(self, text: str)`
    - `looks_like_presence_narration(self, text: str)`
    - `looks_like_blunt_emotion_declaration(self, text: str)`
    - `looks_like_relational_expression(self, text: str)`
    - `looks_like_continuity_pain(self, text: str)`
    - `looks_like_clinginess_or_blackmail(self, text: str)`
    - `relational_theme(self, normalized: str)`
    - `allowed_exposure_for_stage(self, stage: str)`

## `cortex/modes.py`
- LOC: 14

## `cortex/ni.py`
- LOC: 657
- Functions:
  - `_load_focus_bias_table()` — Tải focus config cũ nhưng vô hiệu hóa bias đạo đức.
- Classes:
  - `NiEngine` — Đọc hướng-nghĩa và chuyển nó thành GoalDriftReport.
    - `__init__(self, *, interpreter: object | None=None, semantic_engine: SemanticHypothesisEngine | None=None, semantic_enabled: bool | None=None, allow_hashing_fallback: bool | None=None)`
    - `_build_orientation_interpreter(self, *, semantic_engine: SemanticHypothesisEngine | None=None, semantic_enabled: bool | None=None, allow_hashing_fallback: bool | None=None)`
    - `_env_flag(self, name: str, *, default: bool)`
    - `_env_int(self, name: str, *, default: int, minimum: int=1)`
    - `_env_float(self, name: str, *, default: float, minimum: float=0.0, maximum: float=1.0)`
    - `evaluate_autonomous(self, *, snapshot: TelemetrySnapshot, long_term_memory: list[str], last_text: str, goal_state: object=None, goal_context: object=None)`
    - `evaluate_chat(self, *, snapshot: TelemetrySnapshot, long_term_memory: list[str], user_text: str, goal_state: object=None, goal_context: object=None)`
    - `_build_probe(self, *, snapshot: TelemetrySnapshot, recent_signals: list[str], current_text: str, goal_state: object=None, goal_context: object=None)`
    - `_extract_goal_context(self, *, goal_state: object=None, goal_context: object=None)` — Đọc dữ liệu goal đang hoạt động từ object, dict hoặc text nén.
    - `_parse_goal_context_text(self, text: str)` — Phân tích chuỗi render_ni_context() từ GoalPersistenceState.
    - `_analyze(self, *, probe: SemanticContextProbe)`
    - `_adjust_coherence(self, coherence: float, *, focus_kind: str)`
    - `_label_drift(self, drift_score: float)`
    - `_build_prompt_context(self, *, orientation: OrientationSignal, drift_score: float, drift_level: str, should_raise_guard: bool)`
    - `_build_guidance(self, *, orientation: OrientationSignal, should_raise_guard: bool)`
    - `_estimate_attention_signal(self, *, snapshot: TelemetrySnapshot, channels: dict[str, str])`
    - `_focus_kind_baseline(self, focus_kind: str)`
    - `_focus_text_adjustment(self, normalized: str, *, focus_kind: str)`
    - `_idle_adjustment(self, idle_seconds: float, *, focus_kind: str)`
    - `_window_sprawl_adjustment(self, open_window_count: int, *, focus_kind: str)`
    - `_adjust_similarity(self, raw_similarity: float, *, focus_kind: str)`
    - `_estimate_confidence(self, *, snapshot: TelemetrySnapshot, channels: dict[str, str], signal_channels: dict[str, float], drift_score: float)`
    - `_log_orientation_sample(self, *, focus_kind: str, orientation: OrientationSignal, should_raise_guard: bool, channels: Mapping[str, float])`
    - `_log_drift_sample(self, *, focus_kind: str, raw_similarity: float, drift_score: float, should_raise_guard: bool, channels: dict[str, float])`
  - `NiStateMachine` — Làm mượt theo thời gian trên xung đột goal ngữ nghĩa.
    - `__init__(self, *, window_seconds: float=600.0, borderline_threshold: float=0.35, off_goal_threshold: float=0.65, max_recent: int=120)`
    - `update(self, *, snapshot: TelemetrySnapshot, report: GoalDriftReport)`

## `cortex/observer_contracts.py`
- LOC: 448
- Docstring: Contract cho Background Observer của ERIS.
- Functions:
  - `clamp01(value: Any, default: float=0.0)`
  - `stable_hash(text: str)`
  - `normalize_text(text: str)`
  - `normalize_ascii_fold(text: str)` — Normalize dùng cho matching nhẹ tiếng Việt/Anh.
  - `compact_text(text: str, max_chars: int=240)`
  - `coerce_focus_kind(value: Any)`
  - `coerce_activity_intent(value: Any)`
  - `coerce_observer_action(value: Any)`
- Classes:
  - `SignalSnapshot` (decorator=dataclass) — Một lát cắt tín hiệu nền đã được làm nhẹ.
    - `__post_init__(self)`
    - `from_mapping(cls, data: Mapping[str, Any])` — Tạo snapshot từ dict telemetry/se tùy shape.
    - `compact_summary(self, *, max_ocr_chars: int=900, max_events: int=8)` — Text ngắn để đưa vào observer LLM nếu cần.
  - `SignalDiff` (decorator=dataclass) — Diff giữa snapshot mới và trạng thái trước đó.
    - `should_run_text_observer(self, min_diff: float=0.18)`
    - `should_consider_vision(self, min_diff: float=0.2)`
  - `ObserverFrame` (decorator=dataclass) — Kết quả quan sát nền.
    - `__post_init__(self)`
    - `is_actionable(self)`
    - `to_evidence_claim(self)` — Render claim an toàn cho AttentionSalience.
    - `attention_tags(self)` — Tags dành cho attention/working memory.
    - `to_body_bias_hint(self)` — Hint nhẹ cho BodyBiasProjector.
  - `SemanticSceneNote` (decorator=dataclass) — Ghi chú semantic từ Qwen vision/compressor.
    - `__post_init__(self)`
    - `to_evidence_claim(self)`

## `cortex/orientation_context.py`
- LOC: 1142
- Functions:
  - `clamp01(value: object)` — Ép một giá trị về [0, 1].
  - `clamp(value: float, low: float, high: float)`
  - `clean_text(value: object, *, limit: int=180)` — Dọn text để lưu summary/evidence ngắn.
  - `normalize(value: object)` — Chuẩn hóa text cho lexical matching.
  - `tokens(value: object, *, keep_short_code_tokens: bool=True)` — Token lexical cho anchor/goal matching.
  - `phrase_in(normalized: str, phrase: str)`
  - `has_any(normalized: str, phrases: Sequence[str])`
  - `count_hits(normalized: str, phrases: Sequence[str])`
  - `unique_recent(items: Iterable[str], *, limit: int=8)` — Giữ item unique theo thứ tự gần nhất.
  - `extract_anchors(text: str, *, max_items: int=10)` — Rút anchor lexical có ích cho semantic và goal merge.
  - `goal_match_score(left: str, right: str, *, left_anchors: Sequence[str]=(), right_anchors: Sequence[str]=())` — Khớp goal bằng token + anchor, dùng như fallback rẻ.
  - `has_negated_closure(text: str)` — True nếu text có closure bị phủ định.
  - `infer_closure_signal(text: str, *, thought_stream_report: object=None)` — Closure fallback cho GoalPersistence.
  - `infer_goal_text_signal(text: str, *, channel: str='chat', force_speak: bool=False)` — Classifier lexical mỏng cho text user.
- Classes:
  - `ActivityIntentLabel` (base=str, Enum)
  - `GoalRelationLabel` (base=str, Enum)
  - `GoalTextKind` (base=str, Enum)
  - `ActivityIntent` (decorator=dataclass(frozen=True, slots=True))
  - `GoalRelation` (decorator=dataclass(frozen=True, slots=True))
  - `OrientationSignal` (decorator=dataclass(frozen=True, slots=True))
  - `GoalTextSignal` (decorator=dataclass(frozen=True, slots=True)) — Tín hiệu rút từ user text để GoalPersistence dùng.
    - `should_persist(self)`
    - `can_intervene(self)`
  - `ClosureSignal` (decorator=dataclass(frozen=True, slots=True))
  - `SemanticContextProbe` (decorator=dataclass(slots=True)) — Input nhẹ cho orientation.
    - `combined_text(self)`
  - `LexicalOrientationInterpreter` — Lexical baseline cho Orientation.
    - `infer_activity_intent(self, probe: SemanticContextProbe)`
    - `infer_idle_posture(self, probe: SemanticContextProbe, intent_label: str)`
    - `estimate_fragmentation(self, probe: SemanticContextProbe)`
    - `infer_goal_relation(self, *, intent: ActivityIntent, probe: SemanticContextProbe, fragmentation: float, idle_label: str)`
    - `estimate_orientation(self, probe: SemanticContextProbe)`
    - `_estimate_coherence(self, *, intent: ActivityIntent, relation: GoalRelation, active_goal_strength: float, fragmentation: float, idle_ambiguity: float, combined_text: str)`
    - `_estimate_conflict(self, *, intent: ActivityIntent, relation: GoalRelation, active_goal_strength: float, active_goal_intervention_permission: float, fragmentation: float, idle_ambiguity: float)`
    - `_estimate_intervention_pressure(self, *, intent: ActivityIntent, relation: GoalRelation, active_goal_strength: float, active_goal_intervention_permission: float, conflict: float, fragmentation: float, idle_ambiguity: float, idle_label: str)`
    - `_estimate_confidence(self, *, probe: SemanticContextProbe, intent: ActivityIntent, relation: GoalRelation, idle_ambiguity: float, fragmentation: float)`

## `cortex/orientation_semantics.py`
- LOC: 797
- Functions:
  - `build_hybrid_orientation_interpreter(semantic_engine: SemanticHypothesisEngine | None=None, *, config: HybridOrientationConfig | None=None)` — Factory nhỏ để coordinator/Ni nối nhanh.
- Classes:
  - `HybridOrientationConfig` (decorator=dataclass(frozen=True, slots=True)) — Tham số điều phối lexical + semantic.
  - `LexicalVetoReport` (decorator=dataclass(frozen=True, slots=True)) — Các neo/veto lexical mà semantic không được lấn qua.
    - `hard_work_anchor(self)`
    - `research_media_anchor(self)`
  - `HybridOrientationDebug` (decorator=dataclass(frozen=True, slots=True)) — Debug bundle để log/audit khi cần.
  - `HybridOrientationInterpreter` — Orientation interpreter dùng lexical hiện tại + semantic hypothesis.
    - `__init__(self, *, semantic_engine: SemanticHypothesisEngine | None=None, lexical_interpreter: LexicalOrientationInterpreter | None=None, config: HybridOrientationConfig | None=None)`
    - `estimate_orientation(self, probe: SemanticContextProbe)` — Ước lượng orientation bằng hybrid lexical + semantic.
    - `_semantic_context_text(self, probe: SemanticContextProbe)` — Dựng text semantic gọn từ probe.
    - `_relation_context_text(self, probe: SemanticContextProbe, context_text: str)`
    - `_lexical_veto(self, text: str)`
    - `_blend_intent(self, lexical_intent: ActivityIntent, semantic_report: SemanticHypothesisReport, veto: LexicalVetoReport, probe: SemanticContextProbe)`
    - `_blend_relation(self, lexical_relation: GoalRelation, semantic_report: SemanticHypothesisReport, blended_intent: ActivityIntent, veto: LexicalVetoReport, probe: SemanticContextProbe)`
    - `_blend_confidence(self, lexical_conf: float, semantic_conf: float, ambiguity: float, *, favor_lexical: bool=False, favor_semantic: bool=False)`
    - `_estimate_coherence(self, *, intent: ActivityIntent, relation: GoalRelation, lexical_signal: OrientationSignal, intent_report: SemanticHypothesisReport, relation_report: SemanticHypothesisReport, probe: SemanticContextProbe)`
    - `_estimate_conflict(self, *, intent: ActivityIntent, relation: GoalRelation, lexical_signal: OrientationSignal, intent_report: SemanticHypothesisReport, relation_report: SemanticHypothesisReport, probe: SemanticContextProbe, veto: LexicalVetoReport)`
    - `_estimate_intervention_pressure(self, *, relation: GoalRelation, conflict: float, lexical_signal: OrientationSignal, intent_report: SemanticHypothesisReport, relation_report: SemanticHypothesisReport, probe: SemanticContextProbe)`
    - `_estimate_confidence(self, *, blended_intent: ActivityIntent, blended_relation: GoalRelation, lexical_signal: OrientationSignal, intent_report: SemanticHypothesisReport, relation_report: SemanticHypothesisReport, veto: LexicalVetoReport)`
    - `_with_fallback_channels(self, signal: OrientationSignal, *, reason: str)`
    - `_with_semantic_channels(self, signal: OrientationSignal, *, intent_report: SemanticHypothesisReport, relation_report: SemanticHypothesisReport, debug: HybridOrientationDebug)`
    - `_blend_reason(self, lexical_intent: ActivityIntent, blended_intent: ActivityIntent, semantic_report: SemanticHypothesisReport, veto: LexicalVetoReport)`

## `cortex/personality.py`
- LOC: 959
- Classes:
  - `PersonalityLens` — Guarded, grounded personality pressure layer between meaning and expression.
    - `evaluate(self, *, scene=None, attention=None, meaning_layer=None, internal_state: PersistentInternalState | None=None, relationship=None, channel: str='', user_text: str='')`
    - `render_prompt_context(self, result: PersonalityLensResult, *, envelope: ExpressionEnvelope | None=None)`
    - `_want_to_say(self, *, biases: tuple[str, ...], interpretation: str, state: PersistentInternalState, channel: str, meaning_layer)`
    - `_suppression_pressure(self, *, biases: tuple[str, ...], interpretation: str, stance: str, social_distance: str, state: PersistentInternalState, channel: str)`
    - `_allowed_expression(self, *, want_to_say: float, suppression_pressure: float, anchor_strength: float=1.0, channel: str='', ceiling: float=0.52)`
    - `_expression_ceiling(self, *, state: PersistentInternalState, channel: str, interpretation: str, social_distance: str)` — Trần biểu đạt động (Lever C).
    - `_suppression_floor(self, *, state: PersistentInternalState, channel: str, interpretation: str)` — Sàn suppression động (Lever C). Mặc định 0.48; hạ về ~0.40 khi ấm+an toàn.
    - `_suppression_ratio(self, *, want_to_say: float, allowed_expression: float, floor: float=0.48, envelope: ExpressionEnvelope | None=None)`
    - `_restraint_mode(self, *, allowed_expression: float, suppression_pressure: float, social_distance: str)`
    - `_detect_biases(self, normalized: str)`
    - `_choose_interpretation(self, *, biases: tuple[str, ...], attention, meaning_layer, scene, channel: str, normalized_text: str)`
    - `_choose_stance(self, *, interpretation: str, state: PersistentInternalState, channel: str)`
    - `_choose_emotional_coloring(self, *, interpretation: str, stance: str, state: PersistentInternalState)`
    - `_choose_social_distance(self, *, scene, state: PersistentInternalState, channel: str, interpretation: str)`
    - `_meaningfulness(self, *, interpretation: str, biases: tuple[str, ...], meaning_layer, scene, state: PersistentInternalState)`
    - `_scene_text(self, scene)`
    - `_attention_text(self, attention)`
    - `_meaning_text(self, meaning_layer)`
    - `_relationship_text(self, relationship)`
    - `_evidence(self, *, scene, attention, meaning_layer, relationship, biases: tuple[str, ...])`
    - `_anchor_strength(self, *, scene, attention, meaning_layer, relationship, evidence: tuple[str, ...])`
    - `_normalize(self, text: str)`
    - `_float(self, value)`
    - `_envelope(self, state, *, channel: str, interpretation: str)` — Một envelope liên tục cho turn này — nguồn canonical warmth/threat.

## `cortex/private_life/__init__.py`
- LOC: 50
- Docstring: Private Life Layer public API.

## `cortex/private_life/contracts.py`
- LOC: 950
- Docstring: cortex/private_life/contracts.py
- Functions:
  - `now_ts()` — Timestamp float thống nhất cho state runtime.
  - `clamp01(value: Any, default: float=0.0)` — Ép số về khoảng 0..1.
  - `compact_text(value: Any, limit: int=420)` — Nén text để state không phình thành log trá hình.
  - `stable_id(prefix: str, *parts: Any, size: int=16)` — Sinh id ổn định từ nội dung.
  - `to_plain(value: Any)` — Serialize mềm sang JSON-safe data.
  - `private_life_state_digest(state: PrivateLifeState | None)` — Digest gọn cho debug menu/prompt context.
- Classes:
  - `HabitatObservation` (decorator=dataclass(slots=True)) — Một quan sát về "nhà" runtime.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `HabitatModel` (decorator=dataclass(slots=True)) — Mô hình "nhà" của ERIS.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `ObjectAttachment` (decorator=dataclass(slots=True)) — Gắn bó với một đồ vật số: file, module, folder, model, ritual.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `ObjectResidue` (decorator=dataclass(slots=True)) — Residue phát sinh từ một object attachment.
    - `__post_init__(self)`
    - `to_dict(self)`
  - `PrivateProject` (decorator=dataclass(slots=True)) — Dự án riêng nhỏ của ERIS.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `PrivateProjectUpdate` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
    - `to_dict(self)`
  - `PrivateAnchor` (decorator=dataclass(slots=True)) — Một neo riêng của đời sống ERIS.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `PrivateAnchorUpdate` (decorator=dataclass(slots=True)) — Dấu vết một anchor vừa được chạm trong tick.
    - `__post_init__(self)`
    - `to_dict(self)`
  - `DailyRhythm` (decorator=dataclass(slots=True)) — Nhịp ngày của ERIS.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `TasteShift` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
    - `to_dict(self)`
  - `TasteProfile` (decorator=dataclass(slots=True)) — Khẩu vị riêng: thích/ghét kiểu câu, nhịp, hành động.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `SolitudeLoop` (decorator=dataclass(slots=True)) — Trạng thái tồn tại khi user vắng mặt.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `RitualMemory` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `InternalErrand` (decorator=dataclass(slots=True)) — Việc vặt nội bộ: dọn memory, kiểm log, rà project, hạ nhiễu.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `LifeEvent` (decorator=dataclass(slots=True)) — Sự kiện đời sống riêng.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `SurfaceSeedCandidate` (decorator=dataclass(slots=True)) — Seed rất nhỏ có thể gửi sang SurfaceArbiter.
    - `__post_init__(self)`
    - `should_surface(self)`
    - `to_dict(self)`
  - `PrivateLifeState` (decorator=dataclass(slots=True)) — State bền của PrivateLifeCore.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `PrivateLifeTickResult` (decorator=dataclass(slots=True)) — Output một tick PrivateLifeCore.
    - `to_dict(self)`

## `cortex/private_life/core.py`
- LOC: 879
- Docstring: cortex/private_life/core.py
- Functions:
  - `_getattr_or_mapping(obj: Any, name: str, default: Any=None)`
- Classes:
  - `PrivateLifeCore` — Core đời sống riêng.
    - `__init__(self, state: PrivateLifeState | None=None, *, root_dir: str | os.PathLike[str] | None=None)`
    - `_ensure_defaults(self)` — Cấy project/object mặc định nếu state mới.
    - `tick(self, *, snapshot: Any=None, runtime_owner: Any=None, user_text: str='', channel: str='autonomous', idle_seconds: float | None=None, recent_events: Iterable[Any]=(), force: bool=False)` — Chạy một tick đời sống riêng.
    - `_infer_idle_seconds(self, *, snapshot: Any, runtime_owner: Any, explicit: float | None)`
    - `_observe_habitat(self, *, snapshot: Any, runtime_owner: Any, now: float)`
    - `_place_from_app(self, active_app: str, active_window: str)`
    - `_runtime_queue_notes(self, runtime_owner: Any)`
    - `_update_object_attachments(self, *, now: float)`
    - `_advance_private_projects(self, *, snapshot: Any, runtime_owner: Any, user_text: str, channel: str, idle_seconds: float, object_residues: tuple[ObjectResidue, ...], habitat_observations: tuple[HabitatObservation, ...], now: float)`
    - `_update_private_anchors(self, *, snapshot: Any, runtime_owner: Any, user_text: str, channel: str, idle_seconds: float, object_residues: tuple[ObjectResidue, ...], habitat_observations: tuple[HabitatObservation, ...], project_updates: tuple[PrivateProjectUpdate, ...], now: float)` — Cập nhật 5 anchor riêng bằng chuỗi dữ kiện cụ thể.
    - `_update_taste(self, *, project_updates: tuple[PrivateProjectUpdate, ...], anchor_updates: tuple[PrivateAnchorUpdate, ...], residues: tuple[ObjectResidue, ...], now: float)`
    - `_build_life_events(self, *, habitat_observations: tuple[HabitatObservation, ...], object_residues: tuple[ObjectResidue, ...], project_updates: tuple[PrivateProjectUpdate, ...], anchor_updates: tuple[PrivateAnchorUpdate, ...], taste_shifts: tuple[TasteShift, ...], idle_seconds: float, user_text: str, now: float)`
    - `_build_surface_seed(self, *, project_updates: tuple[PrivateProjectUpdate, ...], anchor_updates: tuple[PrivateAnchorUpdate, ...], object_residues: tuple[ObjectResidue, ...], life_events: tuple[LifeEvent, ...], idle_seconds: float, now: float)`
    - `_update_daily_rhythm(self, *, idle_seconds: float, user_text: str, channel: str, now: float)`
    - `_update_solitude(self, *, idle_seconds: float, user_text: str, project_updates: tuple[PrivateProjectUpdate, ...], anchor_updates: tuple[PrivateAnchorUpdate, ...], now: float)`
    - `_update_rituals(self, *, channel: str, habitat_observations: tuple[HabitatObservation, ...], now: float)`
    - `_update_errands(self, *, object_residues: tuple[ObjectResidue, ...], project_updates: tuple[PrivateProjectUpdate, ...], now: float)`
    - `_commit_events(self, events: tuple[LifeEvent, ...])`
    - `digest(self)` — Digest đọc nhanh cho runtime/debug menu.
    - `to_dict(self)`

## `cortex/private_life/persistence.py`
- LOC: 77
- Docstring: cortex/private_life/persistence.py
- Functions:
  - `atomic_write_json(path: str | os.PathLike[str], payload: Any)` — Ghi JSON bằng temp file rồi replace.
- Classes:
  - `PrivateLifeStore` — Kho state bền cho PrivateLifeCore.
    - `__init__(self, path: str | os.PathLike[str])`
    - `from_env(cls)` — Tạo store theo env.
    - `load(self)`
    - `save(self, state: PrivateLifeState)`

## `cortex/private_mind/__init__.py`
- LOC: 71
- Docstring: Private mind package cho ERIS.

## `cortex/private_mind/comfort_appraiser.py`
- LOC: 201
- Docstring: cortex/private_mind/comfort_appraiser.py
- Functions:
  - `_tokens(text: str)`
- Classes:
  - `ComfortAppraisal` (decorator=dataclass(slots=True)) — Kết quả thẩm định một lời dỗ.
    - `to_payload(self)`
  - `ComfortAppraiser` — Quyết định lời dỗ có ăn hay không, có ego.
    - `__init__(self, *, model_adapter: Any=None, logger: Any=None)`
    - `looks_like_comfort(self, user_text: str)` — Pre-filter rẻ: có đáng gọi agent nhỏ không.
    - `appraise(self, *, user_text: str, concern_themes: tuple[str, ...] | list[str], warmth: float, threat: float)`
    - `_judge(self, text: str, themes: tuple[str, ...])` — Trả (on_topic, substance, is_attempt, source). Ưu tiên agent nhỏ.
    - `_model_judge(self, text: str, themes: tuple[str, ...])`
    - `_heuristic_judge(self, text: str, themes: tuple[str, ...])`
    - `_log(self, level: str, msg: str, *args: Any)`

## `cortex/private_mind/concern_store.py`
- LOC: 704
- Docstring: cortex/private_mind/concern_store.py
- Functions:
  - `_locked(method)`
  - `_ascii_fold(text: str)` — Bỏ dấu tiếng Việt + 'đ'→'d' để token hoá ổn định, không lệ thuộc dấu.
  - `_strip_noise_prefix(theme_lower: str)`
  - `_concept_signature(theme_lower: str)` — Tập token KHÁI NIỆM của theme: bỏ dấu, bỏ stopword, giữ token ≥3 ký tự.
- Classes:
  - `ConcernStoreConfig` (decorator=dataclass(slots=True))
  - `ConcernStore` — CRUD + merge logic cho PrivateConcern.
    - `__init__(self, *, path: str | os.PathLike[str] | None=None, config: ConcernStoreConfig | None=None, logger: Any | None=None)`
    - `__len__(self)`
    - `_is_degenerate_theme(theme: str)` — Trả True nếu theme là rác do LLM loop hoặc hallucination.
    - `all(self)`
    - `open_concerns(self, *, limit: int=12)`
    - `snapshots(self, *, limit: int=8)`
    - `get(self, concern_id: str)`
    - `add_or_update(self, concern: PrivateConcern)`
    - `update_from_fragments(self, fragments: Iterable[ThoughtFragment])`
    - `update_from_judgment(self, data: Mapping[str, Any] | None)`
    - `update_from_outcome(self, outcome: Any, *, surface_outcome: Mapping[str, Any] | None=None)`
    - `mark_resolved(self, concern_id: str, *, reason: str='', closure_note: str='')`
    - `_apply_closure(self, concern: PrivateConcern, *, reason: str='', closure_note: str='')` — Khép một concern và để lại dấu 'đã nguôi' (Q1).
    - `auto_resolve_settled(self, *, now: float | None=None)` — Tự khép các concern đã dịu đủ lâu (Q1).
    - `recently_resolved(self, *, limit: int=5, now: float | None=None)` — Các concern vừa nguôi gần đây — để diary/chat nói 'đã nguôi' (Q1).
    - `prune_and_decay(self, *, now: float | None=None)`
    - `load(self)`
    - `save(self)`
    - `_find_matching_concern(self, fragment: ThoughtFragment)`
    - `_match_theme(self, theme: str, evidence_ids: tuple[str, ...]=())` — Tìm concern đang mở khớp với một theme (paraphrase-aware).
    - `_theme_from_fragment(self, fragment: ThoughtFragment)`
    - `_trim(self)`
    - `_log(self, level: str, msg: str, *args: Any)`

## `cortex/private_mind/contracts.py`
- LOC: 638
- Docstring: cortex/private_mind/contracts.py
- Functions:
  - `normalize_stance(value: Any)` — Chuẩn hoá epistemic_stance.
  - `normalize_intent_field(value: Any)` — Chuẩn hoá intent ở tầng contract.
  - `now_ts()`
  - `clamp01(value: Any, default: float=0.0)`
  - `compact_text(value: Any, limit: int=480)`
  - `stable_id(prefix: str, *parts: Any, size: int=16)`
  - `to_plain(value: Any)` — Serialize mềm để debug/persist JSON.
- Classes:
  - `RankedHypothesis` (decorator=dataclass(slots=True)) — Một giả thuyết có điểm và evidence rõ ràng.
    - `__post_init__(self)`
    - `score(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `ThoughtFragment` (decorator=dataclass(slots=True)) — Mảnh suy nghĩ riêng do mini-evaluator tạo ra.
    - `__post_init__(self)`
    - `score(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `PrivateConcern` (decorator=dataclass(slots=True)) — Mối bận tâm riêng có đời sống qua nhiều tick.
    - `__post_init__(self)`
    - `merge_fragment(self, fragment: ThoughtFragment)` — Cập nhật concern từ fragment mới.
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `StateMutation` (decorator=dataclass(slots=True)) — Một yêu cầu đổi state/bias tương lai.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `SurfaceCandidate` (decorator=dataclass(slots=True)) — Ứng viên được phép nổi lên SurfaceArbiter.
    - `__post_init__(self)`
    - `allowed(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `InternalJudgment` (decorator=dataclass(slots=True)) — Phán quyết nội tâm sau khi Gemma/heuristic synthesize fragments.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `EvidenceDossier` (decorator=dataclass(slots=True)) — Hồ sơ context chung cho mini-evaluator và inner synthesizer.
    - `to_dict(self)`
    - `evidence_ids(self)`
  - `PrivateMindTickResult` (decorator=dataclass(slots=True)) — Kết quả một tick private mind.
    - `to_dict(self)`

## `cortex/private_mind/epistemic.py`
- LOC: 69
- Docstring: cortex/private_mind/epistemic.py
- Functions:
  - `normalize_intent(value: object)` — Trả về một intent hợp lệ, hoặc None nếu thiếu/ngoài tập hợp (out-of-set).
  - `resolve_intent(declared: object, *, has_anchor: bool)` — Req 2 — mặc định kiểu Cartesian.
  - `classify_epistemic_stance(*, has_anchor: bool, intent: str)` — Req 1 — ánh xạ tổng (total), thuần khiết: (has_anchor, intent) -> stance.

## `cortex/private_mind/evidence_dossier.py`
- LOC: 443
- Docstring: cortex/private_mind/evidence_dossier.py
- Functions:
  - `_get(obj: Any, name: str, default: Any=None)`
  - `_call(obj: Any, name: str, *args: Any, default: Any=None, **kwargs: Any)`
- Classes:
  - `EvidenceDossierBuilder` — Build context packet an toàn cho private mind.
    - `__init__(self, *, max_user_turns: int=8, max_memory_hits: int=8, max_repairs: int=6)`
    - `build(self, *, user_text: str='', channel: str='autonomous', snapshot: Any=None, observer_frame: Any=None, wake_decision: Any=None, memory_core: Any=None, memory_hits: Iterable[Any]=(), session_turn_ledger: Any=None, internal_agenda: Any=None, concern_store: Any=None, thought_stream: Any=None, surface_candidate_queue: Iterable[Any]=(), runtime_owner: Any=None, surface_outcome: Mapping[str, Any] | None=None, active_goal: str='', current_task: str='', user_model_snapshot: Mapping[str, Any] | None=None, metadata: Mapping[str, Any] | None=None)`
    - `_recent_user_turns(self, *, user_text: str, ledger: Any, evidence_index: dict[str, Any])`
    - `_runtime_state(self, *, channel: str, snapshot: Any, observer_frame: Any, wake_decision: Any, internal_agenda: Any, thought_stream: Any, surface_candidate_queue: Iterable[Any], runtime_owner: Any, evidence_index: dict[str, Any])`
    - `_thought_stream_state(self, thought_stream: Any)`
    - `_private_runtime_state(self, runtime_owner: Any)`
    - `_surface_queue_state(self, queue: Iterable[Any])`
    - `_compact_surface_like(self, item: Any)`
    - `_evidence_metrics(self, *, recent_turns: list[dict[str, Any]], runtime_state: Mapping[str, Any], evidence_index: Mapping[str, Any], memory_hits: Iterable[Mapping[str, Any]]=(), repair_failures: Iterable[Mapping[str, Any]]=(), concerns: Iterable[Mapping[str, Any]]=())`
    - `_latest_user_turn_age(self, recent_turns: list[dict[str, Any]])`
    - `_public_anchor_count(self, evidence_index: Mapping[str, Any])`
    - `_memory_hits(self, *, memory_core: Any, explicit_hits: Iterable[Any], evidence_index: dict[str, Any])`
    - `_repair_failures(self, *, memory_core: Any, evidence_index: dict[str, Any])`
    - `_active_goal_from_agenda(self, agenda: Any)`
    - `_task_from_snapshot(self, snapshot: Any, observer_frame: Any, turns: list[dict[str, Any]])`

## `cortex/private_mind/inner_diary_renderer.py`
- LOC: 411
- Docstring: cortex/private_mind/inner_diary_renderer.py
- Functions:
  - `_short(value: Any, limit: int=160)`
  - `_as_dict(value: Any)`
  - `_as_list(value: Any)`
  - `_num(value: Any, default: float=0.0)`
  - `_clamp01(value: Any, default: float=0.0)`
  - `_clamp_signed(value: Any, default: float=0.0)`
- Classes:
  - `InnerDiaryRenderer`
    - `_future_thought(self, future_bias: Mapping[str, Any])` — Tóm tắt định hướng sắp tới từ future_bias (inquiry_plan / speech_bias).
    - `_affect(self, digest: Mapping[str, Any])` — Lấy snapshot cảm xúc liên tục thật (valence/arousal/...) nếu có.
    - `_affect_intensities(self, affect: Mapping[str, Any])` — Map affect liên tục → cường độ 4 góc vòng cảm xúc (0..1).
    - `_mood_word(self, affect: Mapping[str, Any])` — Một từ tâm trạng từ affect thật, ngưỡng đồng bộ với emotion_debug.
    - `_emotion_board(self, digest: Mapping[str, Any])`
    - `_norm_line(text: Any)`
    - `_dedupe_sections(cls, sections: list[dict[str, Any]])` — Bỏ item trùng/chứa nhau giữa các ô (giữ nguyên bảng cảm xúc).
    - `render(self, digest: Mapping[str, Any], voice: Mapping[str, Any] | None=None)`

## `cortex/private_mind/inner_diary_writer.py`
- LOC: 210
- Docstring: cortex/private_mind/inner_diary_writer.py
- Functions:
  - `_env_flag(name: str, default: bool)`
  - `_env_float(name: str, default: float)`
  - `_as_dict(value: Any)`
  - `_as_list(value: Any)`
  - `_short(value: Any, limit: int=200)`
- Classes:
  - `InnerDiaryWriter` — Viết nhật ký nội tâm giọng Eris từ digest, có throttle/cache.
    - `__init__(self, *, adapter: Any=None, fallback_adapter: Any=None, throttle_seconds: float | None=None, enabled: bool | None=None, logger: Any=None)`
    - `maybe_write(self, digest: Mapping[str, Any], *, now: float | None=None)` — Trả dict giọng Eris (5 trường) hoặc None nếu nên dùng fallback thô.
    - `_try_fallback(self, facts: Mapping[str, Any])` — Gọi adapter dự phòng cho diary. Nuốt mọi lỗi, trả None nếu không cứu được.
    - `_build_facts(self, digest: Mapping[str, Any])`
    - `_signature(self, facts: Mapping[str, Any])`
    - `_sanitize(self, voice: Any)`
    - `_log(self, level: str, msg: str, *args: Any)`

## `cortex/private_mind/inner_synthesizer.py`
- LOC: 329
- Docstring: cortex/private_mind/inner_synthesizer.py
- Classes:
  - `InnerSynthesizerModelAdapter` (base=Protocol)
    - `synthesize_judgment(self, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...])`
  - `GemmaInnerSynthesizer` — Synthesize fragments thành phán quyết nội tâm.
    - `__init__(self, *, model_adapter: Any=None, min_fragments_for_model: int=3)`
    - `synthesize(self, *, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...])`
    - `_try_model(self, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...])`
    - `_fallback(self, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...])`
    - `_norm_claim(text: str)`
    - `_claim_is_redundant(cls, candidate: str, kept: list[str])` — True nếu claim mới chỉ là biến thể/đoạn con của claim đã giữ.
    - `_weave_inner_voice(cls, fragments: tuple[ThoughtFragment, ...])` — Dệt các mảnh thành một mạch độc thoại ngôi thứ nhất, không boilerplate.
    - `_rank_hypotheses(self, fragments: tuple[ThoughtFragment, ...], evidence_ids: tuple[str, ...])`
    - `_rejected_hypotheses(self, fragments: tuple[ThoughtFragment, ...], evidence_ids: tuple[str, ...])`
    - `_collect_mutations(self, fragments: tuple[ThoughtFragment, ...], evidence_ids: tuple[str, ...])`
    - `_surface_candidate_if_useful(self, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...], *, confidence: float, pressure: float, evidence_ids: tuple[str, ...])`
    - `_adapter_api_status(self)`

## `cortex/private_mind/mini_evaluators.py`
- LOC: 359
- Docstring: cortex/private_mind/mini_evaluators.py
- Functions:
  - `_env_flag(name: str, default: bool)`
  - `_relevance_sig(*parts: str)` — Chữ ký gọn cho trạng thái bằng chứng. Dùng để edge-trigger: chỉ nghĩ lại
  - `_evidence_ids(dossier: EvidenceDossier, *extra: str)`
  - `_from_model(adapter: Any, evaluator_name: str, dossier: EvidenceDossier)` — Gọi model adapter, trả None nếu fail hoặc result yếu.
  - `_infer_user_facet(claim: str)` — Đoán nhẹ facet từ claim; UserModelStore sẽ chuẩn hóa lại nếu sai.
- Classes:
  - `MiniEvaluatorModelAdapter` (base=Protocol)
    - `evaluate_fragment(self, evaluator_name: str, dossier: EvidenceDossier)`
  - `BaseMiniEvaluator`
    - `__init__(self, name: str, *, model_adapter: Any=None)`
    - `evaluate(self, dossier: EvidenceDossier)`
    - `relevance_signature(self, dossier: EvidenceDossier)` — Trả None nếu lúc này KHÔNG có gì đáng để mảnh này nghĩ.
  - `IntentEvaluator` (base=BaseMiniEvaluator)
    - `__init__(self, *, model_adapter: Any=None)`
    - `relevance_signature(self, dossier: EvidenceDossier)`
  - `MemoryResonanceEvaluator` (base=BaseMiniEvaluator)
    - `__init__(self, *, model_adapter: Any=None)`
    - `relevance_signature(self, dossier: EvidenceDossier)`
  - `RiskAndPermissionEvaluator` (base=BaseMiniEvaluator)
    - `__init__(self, *, model_adapter: Any=None)`
    - `relevance_signature(self, dossier: EvidenceDossier)`
  - `FutureBiasEvaluator` (base=BaseMiniEvaluator)
    - `__init__(self, *, model_adapter: Any=None)`
    - `relevance_signature(self, dossier: EvidenceDossier)`
  - `UserModelEvaluator` (base=BaseMiniEvaluator) — Agent nhỏ hướng-Ngài: dựng Mô_Hình_Ngài (spec eris-existential-anchor R1).
    - `__init__(self, *, model_adapter: Any=None)`
    - `relevance_signature(self, dossier: EvidenceDossier)`
    - `evaluate(self, dossier: EvidenceDossier)`
  - `MiniEvaluatorPipeline`
    - `__init__(self, *, model_adapter: Any=None, evaluators: Iterable[BaseMiniEvaluator] | None=None, relevance_gate_enabled: bool | None=None)`
    - `_evaluators_to_run(self, dossier: EvidenceDossier)` — Quyết định mảnh nào đáng gọi lúc này (không tốn API).
    - `evaluate(self, dossier: EvidenceDossier)`

## `cortex/private_mind/state_mutation_bus.py`
- LOC: 387
- Docstring: cortex/private_mind/state_mutation_bus.py
- Classes:
  - `MutationApplyReport` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `PrivateRuntimeBiasState` (decorator=dataclass(slots=True)) — Store nhẹ cho bias nếu runtime chưa có field tương ứng.
    - `to_dict(self)`
  - `StateMutationBus`
    - `__init__(self, *, min_confidence: float=0.35, logger: Any | None=None)`
    - `apply(self, judgment: InternalJudgment | None, *, agenda_stack: Any=None, memory_core: Any=None, state_committer: Any=None, thought_stream: Any=None, surface_candidate_queue: list[Any] | None=None, concern_store: Any=None, runtime_owner: Any=None)`
    - `_apply_one(self, mutation: StateMutation, **targets: Any)`
    - `_apply_agenda(self, mutation: StateMutation, agenda_stack: Any)`
    - `_apply_thought_pressure(self, mutation: StateMutation, thought_stream: Any, runtime_owner: Any)`
    - `_apply_belief_core(self, mutation: StateMutation, *, memory_core: Any, runtime_owner: Any=None)`
    - `_apply_repair_memory(self, mutation: StateMutation, *, memory_core: Any, state_committer: Any)`
    - `_enqueue_surface_candidate(self, candidate: SurfaceCandidate, queue: Any)`
    - `_report(self, mutation: StateMutation, applied: bool, reason: str, value: Any=None)`

## `cortex/private_mind/surface_valve.py`
- LOC: 432
- Docstring: cortex/private_mind/surface_valve.py
- Classes:
  - `SurfaceValve`
    - `__init__(self, *, min_usefulness: float=0.58, min_confidence: float=0.55, max_interrupt_cost: float=0.48)`
    - `filter(self, judgment: InternalJudgment | None)`
    - `to_surface_impulse(self, candidate: SurfaceCandidate | None)` — Chuyển SurfaceCandidate sang SurfaceImpulse nếu module tồn tại.
    - `_merge_public_anchor_refs(self, candidate: SurfaceCandidate, evidence: tuple[Any, ...], metadata: dict[str, Any])` — Req 4.6 — đảm bảo mọi Public_Anchor reference của một claim grounded
    - `_apply_public_surface_gate(self, candidate: SurfaceCandidate, *, judgment: InternalJudgment)`
    - `_interior_nonanchored_allowed(self, *, judgment: InternalJudgment, novelty: float, repetition: float, semantic_family: str, api_degraded: bool, semantic_family_recently_used: bool)` — Nước 3 — cổng cho bận tâm nội tâm áp lực cao nổi lên KHÔNG cần anchor ngoài.
    - `_has_public_anchor(self, candidate: SurfaceCandidate)`
    - `_copy_candidate(self, candidate: SurfaceCandidate, **updates: Any)`
    - `_stamp_epistemic(self, candidate: SurfaceCandidate, *, stance: str, intent: str)` — Trả về bản sao của candidate đã gắn epistemic_stance + intent.
    - `_withhold_to_body_only(self, candidate: SurfaceCandidate, *, judgment: InternalJudgment)` — Req 3 — giữ lại confabulation khỏi public speech nhưng KHÔNG vứt bỏ.
    - `_safe_seed_from_judgment(self, judgment: InternalJudgment)`
    - `_looks_private(self, text: str)`

## `cortex/private_mind/thought_continuity.py`
- LOC: 290
- Docstring: cortex/private_mind/thought_continuity.py
- Functions:
  - `_now()`
  - `_clamp01(x: Any)`
- Classes:
  - `ThoughtEntry` (decorator=dataclass) — Một suy nghĩ trong dòng liên tục.
    - `to_json(self)`
    - `from_json(cls, data: dict[str, Any])`
  - `ThoughtContinuityStore` — Lưu và gọi lại dòng suy nghĩ liên tục.
    - `__init__(self, *, path: str | os.PathLike[str] | None=None, max_entries: int=200, recent_default: int=5, unresolved_cooldown_sec: float=900.0, unresolved_min_pressure: float=0.45, logger: Any=None)`
    - `from_env(cls, *, logger: Any=None)`
    - `_log(self, level: str, msg: str, *args: Any)`
    - `_load(self)`
    - `_rewrite_file(self)`
    - `_append_line(self, entry: ThoughtEntry)`
    - `append(self, entry: ThoughtEntry)`
    - `record_thought(self, *, text: str, theme: str='', status: str='open', pressure: float=0.0, confidence: float=0.0, mood: str='', concern_ids: tuple[str, ...]=(), source: str='synthesis')`
    - `mark_revisited(self, theme: str)`
    - `recent(self, n: int | None=None)`
    - `recent_for_prompt(self, n: int | None=None)` — Mạch nghĩ gần đây ở dạng gọn cho prompt — để model nối tiếp.
    - `unresolved(self, *, limit: int=3)` — Các mạch nghĩ còn dang dở, đủ nặng và đã nguội đủ lâu để khơi lại.
    - `unresolved_for_prompt(self, *, limit: int=3)`
    - `has_followup_due(self)`
    - `_humanize_ago(seconds: int)`
    - `digest(self)`

## `cortex/private_mind/user_model.py`
- LOC: 454
- Docstring: cortex/private_mind/user_model.py
- Functions:
  - `_norm(value: Any)`
  - `_normalize_facet(value: Any)`
  - `default_user_model_path()` — Đường dẫn mặc định trong memory_core/, cạnh các store private khác.
- Classes:
  - `UserBelief` (decorator=dataclass(slots=True)) — Một niềm tin có đời sống của ERIS về Ngài.
    - `__post_init__(self)`
    - `score(self)`
    - `reinforce_from_fragment(self, fragment: ThoughtFragment, *, now: float | None=None)` — Củng cố niềm tin từ một fragment mới cùng hướng (R1.4).
    - `apply_decay(self, *, now: float, forget_after_seconds: float, decay_per_day: float)` — Quên có kiểm soát (R1.5): không được củng cố lâu → confidence giảm.
    - `to_dict(self)`
    - `from_mapping(cls, data: Mapping[str, Any])`
  - `UserModelConfig` (decorator=dataclass(slots=True))
  - `UserModelStore` — Kho Mô_Hình_Ngài: bền vững, versioned, có undo/reset.
    - `__init__(self, *, path: str | os.PathLike[str] | None=None, config: UserModelConfig | None=None, logger: Any | None=None)`
    - `__len__(self)`
    - `all(self)`
    - `by_facet(self, facet: str)`
    - `snapshot_for_dossier(self, *, limit: int=12)` — Ảnh chụp public-safe để nhét vào EvidenceDossier (R1.6).
    - `model_thickness(self)` — Độ dày/nhất quán Mô_Hình_Ngài — đầu vào cho SignificanceDeriver (R2.2).
    - `update_from_fragments(self, fragments: Iterable[ThoughtFragment])`
    - `_find_matching(self, fragment: ThoughtFragment, facet: str)`
    - `decay(self, *, now: float | None=None)`
    - `checkpoint(self)` — Chụp phiên bản hiện tại vào lịch sử, trả về số phiên bản mới.
    - `revert_to(self, version: int)` — Khôi phục Mô_Hình_Ngài về một phiên bản đã checkpoint (R10.3).
    - `reset_to_baseline(self)` — Xóa toàn bộ Mô_Hình_Ngài về baseline rỗng, giữ lịch sử (R10.3).
    - `to_dict(self)`
    - `load_from_dict(self, raw: Mapping[str, Any] | None)`
    - `load(self)`
    - `reload_if_changed(self)`
    - `save(self)`
    - `_trim(self)`
    - `_log(self, level: str, msg: str, *args: Any)`

## `cortex/relational_feedback.py`
- LOC: 344
- Docstring: relational_feedback.py
- Functions:
  - `clamp01(value: Any, default: float=0.0)`
  - `normalize_vi(text: str)`
  - `_contains_phrase(text: str, phrase: str)`
  - `_has_any(text: str, phrases: tuple[str, ...])`
  - `merge_affect_with_relational_feedback(affect: Any, feedback: RelationalFeedbackSignal)` — Tạo dict affect cho FeRenderer mà không cần mutate AffectSemanticSignal.
- Classes:
  - `RelationalFeedbackSignal` (decorator=dataclass(frozen=True, slots=True))
    - `empty(cls)`
    - `to_dict(self)`
    - `from_dict(cls, data: Mapping[str, Any] | None)`
    - `to_prompt_context(self)`
  - `RelationalFeedbackAnalyzer` — Detector nhỏ, có confidence, không tự quyết định output.
    - `analyze(self, user_text: str, *, previous_assistant_text: str='')`

## `cortex/relationship_dynamics.py`
- LOC: 1139
- Docstring: relationship_dynamics.py
- Functions:
  - `_safe_float(value: Any, default: float=0.0)`
  - `_decay(value: float, hours: float, half_life_hours: float)` — Decay theo half-life.
  - `_nudge(value: float, delta: float)` — Cộng delta nhỏ rồi clamp.
  - `_compact_notes(notes: list[str], limit: int=14)`
  - `_score(value: Any)`
- Classes:
  - `RelationshipDynamicsState` (decorator=dataclass(slots=True)) — State dài hạn về quan hệ giữa ERIS và user.
    - `clamp(self)`
    - `to_dict(self)`
    - `from_dict(cls, data: Mapping[str, Any] | None)`
    - `to_prompt_context(self)`
  - `RelationshipTurnEvent` (decorator=dataclass(slots=True)) — Event tóm tắt một turn để update relationship state.
    - `from_affect(cls, *, user_text: str, affect: AffectSemanticSignal, turn_index: int=0, assistant_emotional_exposure: float=0.0, assistant_overread: bool=False, assistant_too_verbose: bool=False, assistant_too_performative: bool=False, assistant_technical_success: float=0.0, repeated_project_context: bool | None=None, user_accepted_style: bool | None=None, relationship_scores: RelationshipEventScores | None=None, session_gap_hours: float=0.0)` — Tạo event từ affect + scores đã build.
    - `evidence_labels(self, limit: int=8)` — Trả nhãn evidence ngắn để ghi notes/debug.
  - `RelationshipDynamicsReport` (decorator=dataclass(slots=True)) — Kết quả update relationship.
    - `to_dict(self)`
  - `RelationshipDynamicsEngine` — Engine update RelationshipDynamicsState theo từng turn.
    - `__init__(self, *, event_builder: RelationshipEventBuilder | None=None)`
    - `create_state(self)`
    - `infer_event(self, *, user_text: str, ti_mode: str='', active_window_kind: str='', turn_index: int=0, assistant_emotional_exposure: float=0.0, assistant_overread: bool=False, assistant_too_verbose: bool=False, assistant_too_performative: bool=False, assistant_technical_success: float=0.0, session_gap_hours: float=0.0, previous_assistant_text: str='', previous_assistant_success: float=0.0, goal_state: Any=None, conversation_state: Any=None, recent_user_topics: tuple[str, ...]=(), recent_turns: tuple[RecentTurn, ...]=(), current_anchors: tuple[str, ...]=(), previous_anchors: tuple[str, ...]=(), evidence_ids: tuple[str, ...]=(), explicit_repeated_project_context: float | None=None, explicit_accepted_style: float | None=None, explicit_accepted_answer: float | None=None, explicit_accepted_action: float | None=None, relational_feedback: Any=None)` — Tạo RelationshipTurnEvent từ text + context.
    - `update(self, state: RelationshipDynamicsState | None, event: RelationshipTurnEvent)` — Update state theo event hiện tại.
    - `_apply_gap_decay(self, state: RelationshipDynamicsState, hours: float, notes: list[str])` — Decay state giữa session.
    - `_compute_deltas(self, before: RelationshipDynamicsState, after: RelationshipDynamicsState)`
    - `_choose_last_event(self, notes: list[str])`
  - `RelationshipStylePressure` (decorator=dataclass(slots=True)) — Áp lực style derive từ relationship state.
    - `from_state(cls, state: RelationshipDynamicsState)`
    - `to_prompt_context(self)`

## `cortex/relationship_event_builder.py`
- LOC: 861
- Docstring: relationship_event_builder.py
- Functions:
  - `clamp01(value: Any, default: float=0.0)` — Ép một giá trị về [0, 1].
  - `safe_float(value: Any, default: float=0.0)`
  - `normalize_vi(text: str)` — Normalize tiếng Việt để so khớp nhẹ.
  - `token_set(text: str)` — Token vừa đủ cho overlap.
  - `compact(items: Iterable[str], limit: int=12)`
  - `overlap_score(a: Iterable[str], b: Iterable[str])` — Jaccard mềm cho anchor/topic overlap.
  - `get_attr_or_key(obj: Any, name: str, default: Any=None)` — Đọc field từ dataclass/object/dict an toàn.
- Classes:
  - `RelationshipEvidence` (decorator=dataclass(frozen=True, slots=True)) — Một mảnh bằng chứng dùng để build relationship event.
    - `normalized(self)`
  - `RelationshipEventScores` (decorator=dataclass(frozen=True, slots=True)) — Score quan hệ cho một lượt.
    - `accepted_any(self)` — Acceptance tổng hợp nhưng vẫn giữ ba nhánh riêng để update tinh hơn.
    - `normalized(self)`
  - `RecentTurn` (decorator=dataclass(frozen=True, slots=True)) — Turn gọn để builder đọc session/public ledger mà không phụ thuộc class thật.
  - `RelationshipEventBuildContext` (decorator=dataclass(frozen=True, slots=True)) — Context đầu vào giàu hơn cho builder.
  - `RelationshipEventBuilder` — Build RelationshipEventScores từ nhiều nguồn có confidence.
    - `build(self, **kwargs: Any)` — Build scores bằng keyword args để caller dễ nối dần.
    - `build_from_context(self, ctx: RelationshipEventBuildContext)` — Biến thể typed cho caller thích rõ contract.
    - `_context_from_kwargs(self, data: Mapping[str, Any])`
    - `_coerce_relational_feedback(self, value: Any)`
    - `_optional_score(self, value: Any)`
    - `_score_repeated_project_context(self, ctx: RelationshipEventBuildContext)`
    - `_goal_continuity_score(self, ctx: RelationshipEventBuildContext, user_tokens: set[str], current_anchors: set[str])`
    - `_recent_topic_score(self, ctx: RelationshipEventBuildContext, user_tokens: set[str])`
    - `_technical_followup_score(self, ctx: RelationshipEventBuildContext)`
    - `_extract_anchors(self, text: str)` — Rút anchor cụ thể: file/module/class/function.
    - `_score_acceptance(self, ctx: RelationshipEventBuildContext)`
    - `_positive_ack_score(self, normalized: str)`
    - `_style_target_score(self, normalized: str)`
    - `_action_continue_score(self, normalized: str)`
    - `_continued_same_plan_score(self, ctx: RelationshipEventBuildContext)`
    - `_looks_like_quality_question(self, normalized: str)`
    - `_contains_any(self, normalized: str, markers: Sequence[str])`

## `cortex/se.py`
- LOC: 1527
- Classes:
  - `_ContextCandidate` (decorator=dataclass(frozen=True)) — Một ứng viên phân loại bối cảnh.
  - `_ContextClassification` (decorator=dataclass(frozen=True)) — Kết quả phân loại bối cảnh có confidence thay vì chỉ trả một nhãn.
  - `SeLens` — Tầng Se: biến telemetry thô thành snapshot có thể đưa vào cognition.
    - `__init__(self)`
    - `build_snapshot(self, raw: dict)`
    - `build_machine_context(self, raw: dict)`
    - `_load_context_overrides(self)`
    - `_contains_override(self, haystack: str, key: str)`
    - `format_snapshot(self, snapshot: TelemetrySnapshot)`
    - `format_directive_snapshot(self, snapshot: TelemetrySnapshot)`
    - `_format_visible_context(self, snapshot: TelemetrySnapshot)`
    - `_is_generic_prompt_event(self, event: str)`
    - `_is_generic_prompt_evidence(self, evidence: str)`
    - `_build_prompt_screen_facts(self, snapshot: TelemetrySnapshot)`
    - `_normalize_string_tuple(self, values)`
    - `_build_recent_events(self, *, raw: dict, active_app: str, active_window_kind: str, browser_url: str, browser_tabs: tuple[str, ...], open_windows: tuple[str, ...], idle_seconds: float, cpu_percent: float, ram_percent: float, context_classification: _ContextClassification | None=None, content_metadata: dict[str, object] | None=None)`
    - `_build_user_signals(self, *, raw: dict, active_window_kind: str, idle_seconds: float, browser_tabs: tuple[str, ...], open_windows: tuple[str, ...])`
    - `_infer_typing_speed(self, idle_seconds: float)`
    - `_infer_window_switching(self, open_window_count: int, browser_tab_count: int)`
    - `_infer_focus_pattern(self, *, active_window_kind: str, idle_seconds: float, open_window_count: int, browser_tab_count: int)`
    - `_build_evidence(self, *, raw: dict, active_app: str, active_window_kind: str, browser_url: str, browser_tabs: tuple[str, ...], open_windows: tuple[str, ...], idle_seconds: float, cpu_percent: float, ram_percent: float, recent_events: tuple[str, ...], context_classification: _ContextClassification | None=None, content_metadata: dict[str, object] | None=None)`
    - `_build_claim_style(self, *, raw: dict, active_window_kind: str, idle_seconds: float, evidence: tuple[str, ...], context_classification: _ContextClassification | None=None, content_metadata: dict[str, object] | None=None)`
    - `_normalize_claim_style(self, value: str)`
    - `_classify_window_kind(self, active_window: str, browser_url: str, browser_tabs: tuple[str, ...])` — API cũ: trả về string kind.
    - `_classify_window_context(self, active_window: str, browser_url: str, browser_tabs: tuple[str, ...])` — Phân loại bối cảnh bằng điểm số cạnh tranh.
    - `_infer_surface_kind(self, active_text: str, browser_domain: str, browser_url: str)`
    - `_infer_content_kind(self, active_text: str, browser_text: str, browser_domain: str)`
    - `_infer_activity_intent(self, primary_kind: str, surface_kind: str, content_kind: str, confidence: float, ambiguity: float)`
    - `_context_confidence_cap(self, primary_kind: str, surface_kind: str, content_kind: str, primary_score: float)`
    - `_score_to_confidence(self, score: float, gap: float, ambiguity: float)`
    - `_format_context_classification_evidence(self, classification: _ContextClassification)`
    - `_extract_context_meta_from_evidence(self, evidence: tuple[str, ...])`
    - `_build_focus_summary(self, active_window_kind: str, active_app: str, browser_url: str)`
    - `_label_position(self, inferred_pos_x: float)`
    - `_label_idle(self, idle_seconds: float)`
    - `_describe_prompt_scene(self, snapshot: TelemetrySnapshot)`
    - `_describe_prompt_pace(self, snapshot: TelemetrySnapshot)`
    - `_describe_prompt_focus(self, snapshot: TelemetrySnapshot)`
    - `_build_prompt_cues(self, snapshot: TelemetrySnapshot)`
    - `_normalize_content_metadata(self, value)`
    - `_augment_browser_tabs_with_content_metadata(self, browser_tabs: tuple[str, ...], content_metadata: dict[str, object])`
    - `_build_content_metadata_evidence(self, content_metadata: dict[str, object])`
    - `_content_metadata_prompt_facts(self, content_metadata: dict[str, object])`
    - `_format_content_metadata_inline(self, content_metadata: dict[str, object])`
    - `_content_metadata_confidence(self, content_metadata: dict[str, object])`
    - `_content_metadata_has_concrete_text(self, content_metadata: dict[str, object])`
    - `_trim_text(self, value: str, limit: int)`
    - `_coerce_float(self, value, default: float=0.0)`
    - `_looks_like_browser_surface(self, active_window: str, browser_url: str, browser_tabs: tuple[str, ...])`
    - `_build_weak_context_hints(self, *, active_window: str, browser_url: str, browser_tabs: tuple[str, ...])`
    - `_is_weak_context_hint_evidence(self, evidence: str)`
    - `_concrete_evidence(self, evidence: tuple[str, ...])`
    - `_evidence_quality_score(self, evidence: tuple[str, ...])`
    - `_evidence_item_quality(self, evidence: str)`
    - `_label_ambient_tone(self, ambient_seed: int)`
    - `_label_tease_bias(self, ambient_seed: int)`
    - `_focus_summary_for_kind(self, active_window_kind: str, active_app: str, browser_url: str)`
    - `_normalize_text(self, value: str)`
    - `_domain_from_url(self, url: str)`
    - `_domain_matches(self, domain: str, expected_domains: tuple[str, ...])`
    - `_phrase_in_text(self, text: str, phrase: str)`
    - `_contains_any_phrase(self, text: str, phrases: tuple[str, ...])`
    - `_contains_any_file_extension(self, text: str)`
    - `_has_technical_anchor(self, active_text: str, browser_text: str)`
    - `_clamp(self, value: float, lower: float, upper: float)`

## `cortex/self_model.py`
- LOC: 491
- Functions:
  - `_clamp01(value)`
  - `_clamp_signed(value)`
- Classes:
  - `SelfModelEngine` — Derives ERIS' self-state as a guarded, grounded desktop presence.
    - `evaluate(self, *, channel: str, snapshot=None, internal_state: PersistentInternalState | None=None, ti_report: TiPolicyReport | None=None, broadcast: CognitiveBroadcast | None=None, user_text: str='', force_speak: bool=False)`
    - `_has_meaningful_broadcast(self, broadcast: CognitiveBroadcast | None)`
    - `_system_pressure(self, snapshot)`
    - `_evidence(self, *, label: str, mode: str, overload: float, engagement: float, direct_user: bool, system_pressure: float, meaningful_broadcast: bool, affordance_label: str, boundary_pressure: float=0.0)`
    - `_affordance_label(self, *, direct_user: bool, meaningful_broadcast: bool, broadcast_score: float, quiet_mode: bool, system_pressure: float, boundary_pressure: float=0.0)`
    - `_narrative(self, *, current_state: CurrentSelfState, channel: str, mode: str, direct_user: bool, meaningful_broadcast: bool)`
    - `_prompt_context(self, *, identity_core: IdentityCore, current_state: CurrentSelfState, narrative: SelfNarrative)`
    - `_development_self_narrative_line()`

## `cortex/self_observation.py`
- LOC: 810
- Classes:
  - `SelfObservationReport` (decorator=dataclass(slots=True)) — Báo cáo tự quan sát của ERIS sau outcome.
    - `to_dict(self)`
    - `from_any(cls, value: Any)`
  - `SelfObservationEngine` — Phân loại lỗi của ERIS từ frame + outcome.
    - `reflect(self, frame: Any, *, outcome: Any=None, attach_to_frame: bool=True)`
    - `append_repair_commit_request(self, frame: Any, *, report: SelfObservationReport | None=None, evidence_ids: list[str] | None=None)` — Tạo và append StateCommitRequest target=repair_memory nếu cần.
    - `build_repair_commit_request(self, frame: Any, *, report: SelfObservationReport, evidence_ids: list[str] | None=None)` — Build request tương thích StateCommitRequest.
    - `_render_repair_content(self, frame: Any, report: SelfObservationReport)`
    - `_classify_failure(self, *, user_intruded: bool, modality_mismatch: bool, cultural_misread: bool, overread_detected: bool, spoke_too_much: bool, hid_too_much: bool, relation_ruptured: bool, tone_violation: float, assistant_flattening: bool, overhumanization: bool, matched_beliefs: bool, user_corrected: bool, user_confused: bool)`
    - `_estimate_severity(self, *, failure_type: FailureType, user_corrected: bool, user_confused: bool, user_intruded: bool, relation_ruptured: bool, factual_risk: float, permission_violation: float, body_match_success: float)`
    - `_estimate_confidence(self, *, outcome_report: Any, evidence_count: int, user_corrected: bool, user_intruded: bool, relation_ruptured: bool, grounding_present: bool, modality_present: bool)`
    - `_derive_wrong_assumption(self, *, failure_type: FailureType, correction_text: str, unsupported_claims: list[str], final_text: str, speech_act: str, speech_source: str)`
    - `_repair_strategy_for(self, failure_type: FailureType)`
    - `_future_suppression_for(self, failure_type: FailureType)`
    - `_mentions_overread(self, text: str)`
    - `_mentions_underacted(self, text: str)`
    - `_mentions_culture_or_tone(self, text: str)`
    - `_contains_mindread_shape(self, normalized_text: str)`
    - `_contains_question_or_probe(self, normalized_text: str)`
    - `_detect_assistant_flattening(self, normalized_text: str, frame: Any)`
    - `_detect_overhumanization(self, normalized_text: str)`
    - `_collect_evidence_ids(self, frame: Any)`
    - `_coerce_outcome(self, value: Any)`
    - `_extract_final_text(frame: Any)`
    - `_read_float(obj: Any, key: str, *, default: float=0.0)`
    - `_read_list(obj: Any, key: str)`
    - `_safe_setattr(obj: Any, key: str, value: Any)`
    - `_normalize(text: str)`
    - `_dedupe(items: list[str])`
    - `_clamp01(value: float)`

## `cortex/semantic_encoder.py`
- LOC: 548
- Functions:
  - `clamp01(value: object)` — Ép một giá trị về [0, 1].
  - `l2_norm(vector: Sequence[float])` — Tính độ dài L2 của vector.
  - `normalize_vector(vector: Sequence[float])` — Chuẩn hóa vector về độ dài 1.
  - `cosine_similarity(left: Sequence[float], right: Sequence[float])` — Tính cosine similarity an toàn.
  - `mean_vectors(vectors: Iterable[Sequence[float]])` — Tính centroid đã normalize từ nhiều vector.
  - `stable_hash_vector(text: str, *, dimensions: int=384, salt: str='eris-semantic-fallback')` — Tạo vector hashing ổn định từ text.
  - `build_default_semantic_encoder(provider: EmbeddingProvider | None=None, *, model_id: str='provider_embedding', cache_items: int=4096, allow_hashing_fallback: bool=False)` — Tạo encoder mặc định cho runtime.
- Classes:
  - `SemanticVector` (decorator=dataclass(frozen=True, slots=True)) — Kết quả encode một đoạn text.
    - `usable(self)`
    - `dimensions(self)`
  - `EncoderHealth` (decorator=dataclass(frozen=True, slots=True)) — Trạng thái hoạt động của encoder.
  - `EmbeddingProvider` (base=Protocol) — Protocol cho provider embedding thật.
    - `__call__(self, texts: Sequence[str])`
  - `BaseSemanticEncoder` — Base class tối thiểu cho semantic encoder.
    - `health(self)`
    - `encode(self, text: str)`
    - `encode_many(self, texts: Sequence[str])`
  - `NullSemanticEncoder` (base=BaseSemanticEncoder) — Encoder rỗng.
    - `health(self)`
    - `encode_many(self, texts: Sequence[str])`
  - `LexicalHashingSemanticEncoder` (base=BaseSemanticEncoder) — Fallback deterministic dựa trên hashing token/char.
    - `__init__(self, *, dimensions: int=384, model_id: str='lexical_hashing_v1')`
    - `health(self)`
    - `encode_many(self, texts: Sequence[str])`
  - `ProviderBackedSemanticEncoder` (base=BaseSemanticEncoder) — Encoder bọc một embedding provider thật.
    - `__init__(self, provider: EmbeddingProvider, *, model_id: str='provider_embedding', confidence: float=0.82, normalize: bool=True)`
    - `health(self)`
    - `encode_many(self, texts: Sequence[str])`
  - `CachedSemanticEncoder` (base=BaseSemanticEncoder) — Cache LRU mỏng cho encoder.
    - `__init__(self, inner: BaseSemanticEncoder, *, max_items: int=4096)`
    - `health(self)`
    - `clear(self)`
    - `encode_many(self, texts: Sequence[str])`
  - `SemanticEncoderRouter` (base=BaseSemanticEncoder) — Chọn encoder thật nếu có, fallback nếu không.
    - `__init__(self, primary: BaseSemanticEncoder | None=None, *, fallback: BaseSemanticEncoder | None=None, allow_hashing_fallback: bool=False)`
    - `health(self)`
    - `_active(self)`
    - `encode_many(self, texts: Sequence[str])`

## `cortex/semantic_hypothesis.py`
- LOC: 422
- Classes:
  - `PrototypeCentroid` (decorator=dataclass(frozen=True, slots=True)) — Vector centroid đã encode của một PrototypeSet.
    - `usable(self)`
  - `SemanticHypothesis` (decorator=dataclass(frozen=True, slots=True)) — Một giả thuyết semantic.
  - `SemanticHypothesisReport` (decorator=dataclass(frozen=True, slots=True)) — Kết quả semantic top-k cho một domain.
    - `labels(self)`
    - `uncertain(self)`
  - `HypothesisConfig` (decorator=dataclass(frozen=True, slots=True)) — Tham số scoring semantic.
  - `SemanticHypothesisEngine` — So text hiện tại với prototype bank để sinh hypothesis.
    - `__init__(self, encoder: BaseSemanticEncoder, *, prototype_bank: PrototypeBank | None=None, config: HypothesisConfig | None=None)`
    - `clear_cache(self)`
    - `compare(self, domain: str, text: str, *, anchors: Sequence[str]=(), labels: Sequence[str] | None=None)` — Sinh hypothesis top-k cho một domain.
    - `compare_many(self, domains: Sequence[str], text: str, *, anchors: Sequence[str]=())` — So cùng một text với nhiều domain.
    - `_centroid_for(self, prototype: PrototypeSet)`
    - `_score_prototype(self, *, domain: str, prototype: PrototypeSet, centroid: PrototypeCentroid, text_vector: SemanticVector, anchors: Sequence[str])`
    - `_anchor_boost(self, anchors: Sequence[str], tags: Sequence[str])`
    - `_estimate_ambiguity(self, top: SemanticHypothesis, second: SemanticHypothesis | None, *, health_is_fallback: bool)`
    - `_report_confidence(self, top: SemanticHypothesis, ambiguity: float, *, health_is_fallback: bool)`
    - `_empty_report(self, domain: str, text: str, reason: str, health: object)`

## `cortex/semantic_prototypes.py`
- LOC: 546
- Functions:
  - `p(text: str, weight: float=1.0, *tags: str)`
  - `default_activity_intent_sets()` — Prototype cho activity intent.
  - `default_goal_text_kind_sets()` — Prototype cho việc phân loại user text thành goal/casual/commentary.
  - `default_goal_relation_sets()` — Prototype cho quan hệ giữa context hiện tại và active goal.
  - `default_failure_class_sets()` — Prototype cho phân loại lỗi hội thoại/cognition.
  - `default_speech_opportunity_sets()` — Prototype cho mode nói/im lặng.
  - `build_default_prototype_bank(*, include_failure: bool=True, include_speech: bool=True)` — Tạo prototype bank mặc định cho ERIS.
- Classes:
  - `PrototypePhrase` (decorator=dataclass(frozen=True, slots=True)) — Một câu mẫu semantic cho một label.
  - `PrototypeSet` (decorator=dataclass(frozen=True, slots=True)) — Tập câu mẫu cho một label trong một domain.
    - `phrase_texts(self)`
    - `all_tags(self)`
  - `PrototypeBank` (decorator=dataclass(slots=True)) — Kho prototype có thể mở rộng.
    - `add(self, prototype_set: PrototypeSet)`
    - `extend(self, prototype_sets: Iterable[PrototypeSet])`
    - `get(self, domain: str, label: str)`
    - `by_domain(self, domain: str)`
    - `labels(self, domain: str)`
    - `domains(self)`
    - `merge(self, other: 'PrototypeBank')`

## `cortex/session_ritual.py`
- LOC: 442
- Functions:
  - `_clamp01(value)`
  - `_clean(value: object, *, limit: int=180)`
  - `_disabled_startup_greeting()`
  - `_public_fragment(value: object, *, limit: int=120)`
- Classes:
  - `SessionRitualEngine` — Rehydrates continuity once at app/session start.
    - `evaluate(self, *, snapshot=None, internal_state=None, thought_stream_report=None, social_presence_event=None, now: float | None=None)`
    - `render_prompt_context(self, report: SessionRitualReport)`
    - `_active_goal(self, internal_state)`
    - `_current_attractor(self, thought_stream_report)`
    - `_unresolved_loops(self, thought_stream_report)`
    - `_recent_cognition_direction(self, internal_state, thought_stream_report)`
    - `_self_continuity(self, internal_state)`
    - `_presence_is_clear(self, *, snapshot, social_presence_event)`
    - `_is_overloaded(self, *, snapshot, internal_state)`
    - `_greeted_recently(self, internal_state, *, now: float)`
    - `_tone(self, *, snapshot, internal_state, presence_restored: bool, overloaded: bool, active_goal: str, current_attractor: str, unresolved_loops: tuple[str, ...])`
    - `_greeting_frame(self, *, presence_restored: bool, continuity_restored: bool, active_goal: str, current_attractor: str, unresolved_loops: tuple[str, ...], recent_direction: str, self_continuity: str, tone: str, greeted_recently: bool)`
    - `_greeting_text(self, *, active_goal: str, current_attractor: str, unresolved_loops: tuple[str, ...], recent_direction: str, self_continuity: str='')`
    - `_public_self_continuity(self, self_continuity: str)`
    - `_evidence(self, *, presence_restored: bool, continuity_restored: bool, overloaded: bool, greeted_recently: bool, tone: str, active_goal: str, current_attractor: str, unresolved_loops: tuple[str, ...])`

## `cortex/situation_model.py`
- LOC: 744
- Docstring: cortex/situation_model.py
- Classes:
  - `Prediction` (decorator=dataclass(slots=True)) — Dự đoán ngắn về percept mong đợi ở chu kỳ kế tiếp.
    - `__post_init__(self)`
    - `is_empty(self)`
    - `to_dict(self)`
  - `OpenLoop` (decorator=dataclass(slots=True)) — Một mạch chưa khép trong tình huống (câu hỏi chưa trả lời, việc dở dang...).
    - `to_dict(self)`
  - `PredictionErrorResult` (decorator=dataclass(slots=True)) — Kết quả đo sai số dự đoán cho một chu kỳ / một candidate.
    - `to_dict(self)`
  - `ExpectationViolation` (decorator=dataclass(slots=True)) — Bản ghi vi phạm kỳ vọng — động cơ của tò mò.
    - `to_dict(self)`
  - `PerceptView` (decorator=dataclass(slots=True)) — Quan sát tổng hợp của một chu kỳ, rút từ frame.evidence.
    - `is_empty(self)`
  - `SituationModelState` (decorator=dataclass(slots=True)) — Trạng thái tình huống bền vững, mang qua các chu kỳ.
  - `SituationUpdate` (decorator=dataclass(slots=True)) — Kết quả một lần observe_and_update.
  - `SituationModelConfig` (decorator=dataclass(slots=True)) — Cấu hình Situation Model.
    - `normalized(self)` — Trả bản config đã clamp + ép bất biến trọng số.
  - `SituationLogger` — Ghi prediction vs reality vs error mỗi chu kỳ.
    - `__init__(self, sink: Optional[Any]=None)`
    - `_emit(self, payload: dict[str, Any])`
    - `log_cycle(self, *, prev_prediction: Prediction, percept: PerceptView, error: PredictionErrorResult, cycle: int)`
    - `log_violation(self, violation: ExpectationViolation)`
  - `SituationModel` — Mô hình tình huống bền vững.
    - `__init__(self, config: Optional[SituationModelConfig]=None, *, embedding_cache: Optional[EventEmbeddingCache]=None, embedding_provider: Optional[Any]=None, logger: Optional[SituationLogger]=None, knowledge_provider: Optional[Any]=None)`
    - `reset(self)` — Đưa toàn bộ trạng thái về mặc định trung tính.
    - `set_knowledge_provider(self, provider: Any)` — Gắn hook làm giàu dự đoán bằng tri thức đã học (Curiosity Tutor). None ⇒ tắt.
    - `observe_and_update(self, frame: Any, *, now: Optional[float]=None)` — Chạy vòng đời 1 chu kỳ. Tất định, commit-or-rollback.
    - `prediction_error_for(self, candidate: Any)` — Sai số dự đoán cho một AttentionCandidate, so với prediction đang hoạt động.
    - `expose_violation(self)` — Vi phạm kỳ vọng gần nhất, cho các tầng downstream đọc.
    - `serialize(self)` — Serialize trạng thái sang dict cho debug (Req 7.4).
    - `_percept_from_frame(self, frame: Any)` — Rút percept tổng hợp từ frame.evidence (dominant + salient claims).
    - `_compute_cycle_error(self, prediction: Prediction, percept: PerceptView)` — Sai số tổng hợp của chu kỳ; bỏ qua nếu chưa có prediction trước.
    - `_compute_error(self, prediction: Prediction, percept: PerceptView)` — Đo sai số: embedding/cosine; fallback token-overlap khi thiếu embedding.
    - `_token_overlap_error(prediction_text: str, percept: PerceptView)`
    - `_embed(self, text: str)` — Lấy embedding từ cache/provider; trả () nếu không có.
    - `_update_open_loops(self, percept: PerceptView, error: PredictionErrorResult, now_ts: float)` — Cập nhật open loops theo khớp/trái với prediction.
    - `_update_engagement(self, percept: PerceptView, error: PredictionErrorResult)` — Cập nhật Engagement_Trend theo cửa sổ N chu kỳ gần nhất.
    - `_maybe_violation(self, prediction: Prediction, percept: PerceptView, error: PredictionErrorResult)`
    - `_derive_content_thread(self, percept: PerceptView)` — Mạch nội dung: giữ thread cũ nếu percept trùng nhiều, ngược lại cập nhật.
    - `_make_prediction(self, percept: PerceptView, observed_count: int, cycle: int)` — Sinh Prediction thuần heuristic (tất định) cho chu kỳ kế.

## `cortex/social_presence.py`
- LOC: 587
- Functions:
  - `_clean(value: object)`
  - `_clamp(value: float)`
- Classes:
  - `PresenceFeatureVector` (decorator=dataclass(slots=True))
    - `numeric_tuple(self)`
  - `PresenceMemory` (decorator=dataclass(slots=True))
  - `SocialPresenceDetector` — Detects ambient co-presence without treating it as chat or speech intent.
    - `__init__(self, *, semantic_profiler: EventSemanticProfiler | None=None)`
    - `learn_event_patterns(self, events)` — Background path: enrich meaningful events without blocking detection.
    - `detect(self, *, channel: str, snapshot=None, internal_state=None, user_text: str='', force_speak: bool=False, timestamp: str='')`
    - `_build_feature_vector(self, *, typing_speed: str, switching: str, focus_pattern: str, focus_kind: str, previous_focus: str, idle_seconds: float, recent_events: tuple[str, ...])`
    - `_hydrate_memory_from_internal_state(self, internal_state)`
    - `_score_vector(self, v: PresenceFeatureVector)`
    - `_ema(self, old: float, new: float, alpha: float)`
    - `_update_memory(self, v: PresenceFeatureVector, raw_presence: float, kind: str)`
    - `_classify_presence_kind(self, v: PresenceFeatureVector, *, idle_seconds: float)`
    - `_reason_for_kind(self, kind: str)`
    - `_vector_evidence(self, v: PresenceFeatureVector, *, typing_speed: str, switching: str, focus_pattern: str, focus_kind: str, previous_focus: str, idle_seconds: float)`
    - `_looks_like_presence_event(self, event: str)`
    - `_looks_like_presence_profile(self, profile: EventSemanticProfile)`
    - `_semantic_presence_bonus(self, profiles: tuple[EventSemanticProfile, ...])`

## `cortex/speech_core.py`
- LOC: 1888
- Classes:
  - `SpeechCoreEngine` — Bộ chọn chung về thời điểm nói, căn cứ của dòng và kiểu phát âm của nó.
    - `__init__(self, *, inner_thought_engine: InnerThoughtEngine | None=None, spontaneous_life_engine: SpontaneousLifeEngine | None=None)`
    - `fallback_intent(self, speech_core: AgentSpeechCore | None)`
    - `fallback_context(self, speech_core: AgentSpeechCore | None, *, snapshot=None, momentum_topic: str='')`
    - `render_force_speak_repair_text(self, speech_core: AgentSpeechCore | None, *, normalize_text, is_near_duplicate, last_text: str='', counter: int=1, repeated: bool=False, snapshot=None, momentum_topic: str='', intent: str='')` — Compatibility hook: request dynamic wording, never emit template text.
    - `render_safe_fallback_text(self, speech_core: AgentSpeechCore, *, normalize_text, is_near_duplicate, last_text: str='', repeated: bool=False, snapshot=None, momentum_topic: str='')` — Compatibility hook: ask downstream wording layer for dynamic fallback.
    - `_mark_dynamic_fallback_request(self, speech_core: AgentSpeechCore | None, *, intent: str, snapshot=None, momentum_topic: str='', repeated: bool=False, counter: int=1)`
    - `_force_speak_fallback_by_intent_text(self, intent: str, *, normalize_text, is_near_duplicate, last_text: str='', counter: int=1, repeated: bool=False, focus_kind: str='', window_title: str='', momentum_topic: str='')`
    - `_screen_fallback_anchor(self, *, normalize_text, window_title: str='', momentum_topic: str='')`
    - `_thought_surface_template(self, *args, **kwargs)`
    - `_light_presence_template(self, *args, **kwargs)`
    - `_public_thought_topic(self, value: str, *, normalize_text)`
    - `_looks_internal_topic(self, value: str, *, normalize_text)`
    - `_small_soft_fallback_ladder_text(self, *args, **kwargs)`
    - `evaluate(self, *, channel: str, snapshot=None, internal_state: PersistentInternalState | None=None, appraisal=None, broadcast=None, ti_report=None, fe_plan=None, style_memory=None, concrete_signals: tuple[str, ...]=(), vision_signals: tuple[str, ...]=(), telemetry_signals: tuple[str, ...]=(), screen_comment_allowed: bool=True, repeat_count: int=1, repeated_topic_tag: str='', repeated_topic_streak: int=0, recent_inner_intents: tuple[str, ...]=(), recent_inner_seeds: tuple[str, ...]=(), ni_state_label: str='', ni_report=None, subconscious_seed=None, thought_surface=None, self_state: SelfState | None=None, meaning_layer=None, personality_lens=None, safe_small_talk_allowed: bool=False, spontaneous_impulse: SpeechImpulse | None=None, agent_mind: PersistentAgentMindStore | None=None, private_mind_speech_bias: Mapping[str, object] | None=None, conversation_context: str='')`
    - `_evaluate_motivational_pressure(self, *, channel: str, snapshot, vision_signals: tuple[str, ...], telemetry_signals: tuple[str, ...], concrete_signals: tuple[str, ...], screen_comment_allowed: bool, inner_thought, internal_state: PersistentInternalState | None, appraisal, ti_report, emotional_signal: bool, thought_surface, self_state: SelfState | None, meaning_layer, personality_lens, safe_small_talk_allowed: bool, spontaneous_impulse: SpeechImpulse | None=None, spontaneous_explicit: bool=False)`
    - `_build_urge_candidates(self, *, channel: str, snapshot, vision_signals: tuple[str, ...], telemetry_signals: tuple[str, ...], concrete_signals: tuple[str, ...], screen_comment_allowed: bool, inner_thought, internal_state: PersistentInternalState | None, appraisal, ti_report, emotional_signal: bool, thought_surface, self_state: SelfState | None, meaning_layer, safe_small_talk_allowed: bool, spontaneous_impulse: SpeechImpulse | None=None, spontaneous_explicit: bool=False)`
    - `_apply_self_state_to_candidates(self, candidates: tuple[MotivationalUrge, ...], *, channel: str, self_state: SelfState | None)`
    - `_apply_personality_restraint_to_candidates(self, candidates: tuple[MotivationalUrge, ...], *, channel: str, personality_lens)`
    - `_build_suppressed_pressure_report(self, *, reason: str, threshold: float, concrete_signals: tuple[str, ...])`
    - `_silence_urge(self, *, score: float, reason: str, evidence: tuple[str, ...]=(), blocked: bool=False)`
    - `_silence_body_bias_hint(self, *, reason: str, inner_thought, pressure_report: MotivationalPressureReport, speech_impulse: SpeechImpulse)` — Project suppressed speech into body-only bias.
    - `_build_silence_state(self, *, reason: str, inner_thought, pressure_report: MotivationalPressureReport, speech_impulse: SpeechImpulse, personality_lens, safety_flags: tuple[str, ...]=())`
    - `_meaning_reaction_score(self, *, channel: str, meaning_layer, concrete_signals: tuple[str, ...])`
    - `_allows_soft_non_shift_speech(self, *, meaning_layer, snapshot, internal_state: PersistentInternalState | None)`
    - `_meaning_shift_required_for_layer(self, meaning_layer)`
    - `_risk_level_for_winner(self, *, winner: MotivationalUrge, speech_source: str, utterance_type: str)`
    - `_soft_meaning_presence_score(self, *, channel: str, meaning_layer, snapshot, internal_state: PersistentInternalState | None)`
    - `_residual_continuity_score(self, *, channel: str, meaning_layer, snapshot, internal_state: PersistentInternalState | None, thought_surface)`
    - `_utterance_for_reaction(self, reaction: str, *, channel: str, meaning: str)`
    - `_build_speech_impulse(self, *, channel: str, meaning_layer, winner: MotivationalUrge, should_speak: bool, spontaneous_impulse: SpeechImpulse | None=None)`
    - `_extreme_internal_speech_pressure(self, *, spontaneous_impulse: SpeechImpulse | None, internal_state: PersistentInternalState | None, thought_surface=None)` — Allow bounded endogenous leakage to bypass meaning_shift_gate.
    - `_spontaneous_ready(self, impulse: SpeechImpulse | None, *, channel: str)`
    - `_threshold_for_channel(self, channel: str, *, self_state: SelfState | None=None)`
    - `_score_restraint(self, *, internal_state: PersistentInternalState | None, ti_report, self_state: SelfState | None=None)`
    - `_pressure(self, state: PersistentInternalState, name: str)`
    - `_inner_utterance(self, inner_intent: str, *, fallback: str)`
    - `_inner_anchor(self, inner_thought)`
    - `_should_stay_silent(self, *, ti_mode: str, repeat_count: int, repeated_topic_tag: str, repeated_topic_streak: int, ni_state_label: str, ni_report, internal_state: PersistentInternalState | None, self_state: SelfState | None=None)`
    - `_choose_speech_source(self, *, channel: str, vision_signals: tuple[str, ...], telemetry_signals: tuple[str, ...], screen_comment_allowed: bool, inner_thought, internal_state: PersistentInternalState | None)`
    - `_choose_utterance_type(self, *, channel: str, speech_source: str, inner_thought, emotional_signal: bool)`
    - `_resolve_perception(self, *, speech_source: str, vision_signals: tuple[str, ...], telemetry_signals: tuple[str, ...], concrete_signals: tuple[str, ...], inner_thought)`
    - `_build_safety_flags(self, *, channel: str, speech_source: str, utterance_type: str, emotional_signal: bool, inner_thought)`
    - `_build_reason(self, *, channel: str, speech_source: str, utterance_type: str, inner_thought, emotional_signal: bool)`
    - `_grounding_for_source(self, speech_source: str)`
    - `_has_emotional_signal(self, *, concrete_signals: tuple[str, ...], broadcast)`
    - `_resolve_mood(self, *, snapshot, appraisal, fe_plan)`
    - `_float(self, value)`
    - `_clamp01(self, value)`

## `cortex/spontaneous_life.py`
- LOC: 389
- Docstring: Endogenous + situated speech pressure for ERIS.
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `_clean(value: Any, *, limit: int=120)`
  - `_normalize_key(value: Any)`
- Classes:
  - `SpontaneousLifeConfig` (decorator=dataclass(slots=True)) — Low-gain knobs for internal/situated speech pressure.
  - `SpontaneousLifeTrace` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `SpontaneousLifeEngine` — Tạo xung giọng nói từ state phân tầng, không viết câu cuối.
    - `__init__(self, *, config: SpontaneousLifeConfig | None=None)`
    - `evaluate(self, *, channel: str, snapshot=None, internal_state: PersistentInternalState | None=None, thought_surface=None, personality_lens=None, relationship_state=None, concrete_signals: tuple[str, ...]=(), recent_speech_acts: tuple[str, ...]=(), agent_mind: PersistentAgentMindStore | None=None, conversation_context: str='', now: float | None=None)`
    - `_body_bias_hint(self, *, selected_name: str, stack, pressure: float)` — Gợi ý body-bias từ impulse thắng.
    - `_risk_label(self, *, selected, speech_act: str)`
    - `_source_fact(self, selected)`
    - `_cooldown_for(self, *, impulse_type: str, pressure: float)`
    - `_cooldown_left(self, family: str, *, now: float, cooldown: float)`

## `cortex/subconscious/__init__.py`
- LOC: 133
- Docstring: Subconscious package Phase 0 → 7.

## `cortex/subconscious/blackboard.py`
- LOC: 270
- Docstring: Blackboard Phase 0 cho subconscious workers.
- Classes:
  - `BlackboardSnapshot` (decorator=dataclass(slots=True, frozen=True)) — Ảnh chụp trạng thái Blackboard tại một thời điểm.
    - `top(self, limit: int=8)` — Trả các fragment mạnh nhất trong snapshot.
    - `to_dict(self)` — Serialize snapshot cho debug trace.
  - `SubconsciousBlackboard` — Kho tạm cho ThoughtFragment.
    - `__init__(self, *, max_fragments: int=96, default_ttl_seconds: float=300.0)`
    - `submit(self, fragment: ThoughtFragment | Mapping[str, Any])` — Đưa một fragment lên Blackboard.
    - `submit_many(self, fragments: Iterable[ThoughtFragment | Mapping[str, Any]])` — Submit nhiều fragment và trả về các bản đã được lưu/refresh.
    - `get(self, fragment_id: str)` — Lấy fragment theo id.
    - `replace(self, fragment: ThoughtFragment)` — Thay một fragment đã tồn tại bằng bản mới đã validate.
    - `remove_many(self, fragment_ids: Iterable[str])` — Xóa nhiều fragment và trả id đã xóa thật.
    - `remove(self, fragment_id: str)` — Xóa fragment theo id.
    - `clear(self)` — Xóa toàn bộ Blackboard.
    - `decay(self, *, now: float | None=None)` — Xóa fragment hết TTL và trả danh sách id đã hết hạn.
    - `snapshot(self, *, now: float | None=None, include_expired: bool=False)` — Trả snapshot bất biến cho Synthesizer.
    - `top_fragments(self, *, limit: int=8, now: float | None=None)` — Shortcut lấy top fragment hiện tại.
    - `__len__(self)`
    - `_trim_locked(self, *, now: float)` — Giữ Blackboard dưới max_fragments.
    - `_dedupe_key(self, fragment: ThoughtFragment)` — Tạo key gộp fragment lặp.
    - `_content_seed(content: str)`

## `cortex/subconscious/drift_pool.py`
- LOC: 231
- Docstring: DriftPool: hồ giữ ThoughtSpark yếu.
- Functions:
  - `_tokens(text: str)`
  - `_theme_keys(text: str, tags: Iterable[str]=())`
  - `_signature(spark: ThoughtSpark)`
- Classes:
  - `DriftEntry` (decorator=dataclass(slots=True))
    - `alive_strength(self, now: float)`
    - `to_dict(self, now: float | None=None)`
  - `DriftSnapshot` (decorator=dataclass(slots=True, frozen=True))
    - `sparks(self)`
    - `to_dict(self)`
  - `DriftPool` — Giữ spark yếu, decay chậm, cộng hưởng theo theme.
    - `__init__(self, *, max_sparks: int=80, min_alive_strength: float=0.035)`
    - `submit(self, spark: ThoughtSpark | Mapping[str, Any], *, now: float | None=None)`
    - `submit_many(self, sparks: Iterable[ThoughtSpark | Mapping[str, Any]], *, now: float | None=None)`
    - `decay(self, *, now: float | None=None)`
    - `snapshot(self, *, now: float | None=None)`
    - `top_sparks(self, *, limit: int=12, now: float | None=None)`
    - `related_groups(self, *, now: float | None=None, min_size: int=2)`
    - `resonate(self, *, now: float | None=None, limit: int=4)` — Sinh spark cộng hưởng nội bộ, vẫn không surface trực tiếp.
    - `_resonance_sentence(self, seeds: list[str])`
    - `_trim(self, *, now: float)`
    - `__len__(self)`

## `cortex/subconscious/free_association.py`
- LOC: 143
- Docstring: FreeAssociationEngine cho wandering sparks.
- Functions:
  - `_tokens(text: str)`
  - `_has_marker(spark: ThoughtSpark, marker: str)`
- Classes:
  - `FreeAssociationEngine` — Nối 2-4 spark thành association path.
    - `associate(self, sparks: Iterable[ThoughtSpark] | DriftPool, *, now: float | None=None, limit: int=3, allow_weak_random: bool=True)`
    - `_pair_score(self, a: ThoughtSpark, b: ThoughtSpark, *, now: float)`
    - `_metaphor_score(self, group: Iterable[ThoughtSpark])`
    - `_path_from_group(self, group: Iterable[ThoughtSpark], *, now: float, pair_score: float | None=None)`
    - `_statement(self, seeds: tuple[str, ...], sparks: tuple[ThoughtSpark, ...])`

## `cortex/subconscious/habitat_seed_extractor.py`
- LOC: 152
- Docstring: Habitat seed extractor: lấy seed từ môi trường runtime/repo của ERIS.
- Functions:
  - `_get(obj: Any, path: str, default: Any=None)`
  - `_iter_texts(value: Any, *, limit: int=8)`
- Classes:
  - `HabitatSeedExtractor` — Sinh seed từ memory_core/log/module, không bám user action trực tiếp.
    - `extract(self, *, frame: Any=None, snapshot: Any=None, memory_packet: Any=None, now: float | None=None, limit: int=8)`

## `cortex/subconscious/model_synthesizer.py`
- LOC: 412
- Docstring: Model-backed Lane 3 synthesizer.
- Functions:
  - `_env_flag(name: str, default: bool)`
  - `_as_float(value: Any, default: float)`
- Classes:
  - `ModelSynthesisPolicy` (decorator=dataclass(slots=True, frozen=True)) — Knobs riêng cho Lane 3 API synthesis.
  - `InnerCourtReport` (decorator=dataclass(slots=True, frozen=True)) — Debug report cho phiên tòa Lane 3.
    - `to_dict(self)`
  - `ModelBackedConsciousSynthesizer` (base=ConsciousSynthesizer) — ConsciousSynthesizer có thêm Lane 3 API refinement.
    - `__init__(self, *, model_adapter: Any | None=None, policy: SynthesisPolicy | None=None, model_policy: ModelSynthesisPolicy | None=None, logger: Any | None=None)`
    - `synthesize_from_blackboard(self, blackboard: SubconsciousBlackboard, *, now: float | None=None)`
    - `synthesize(self, snapshot: BlackboardSnapshot | Iterable[ThoughtFragment])`
    - `_extract_live_fragments(self, snapshot: BlackboardSnapshot | Iterable[ThoughtFragment])`
    - `_should_call_model(self, fragments: tuple[ThoughtFragment, ...], *, now: float)`
    - `_call_model(self, base_object: ThoughtObject, fragments: tuple[ThoughtFragment, ...], *, now: float)`
    - `_build_messages(self, base_object: ThoughtObject, fragments: tuple[ThoughtFragment, ...], *, now: float)`
    - `_object_from_model_payload(self, base_object: ThoughtObject, fragments: tuple[ThoughtFragment, ...], payload: Mapping[str, Any], *, now: float)`
    - `_safe_route(self, raw_route: Any, *, confidence: float, surface_pressure: float, suppressed_pressure: float, evidence_ids: tuple[str, ...], privacy_level: PrivacyLevel)`
    - `_merged_privacy(self, base: Any, model: Any)`
    - `_report_from_payload(self, payload: Mapping[str, Any], object_: ThoughtObject, *, provider: str, model: str)`
    - `_log_inner_court(self, report: InnerCourtReport, payload: Mapping[str, Any])`
    - `_log(self, level: str, msg: str, *args: Any)`

## `cortex/subconscious/self_anchor_core.py`
- LOC: 92
- Docstring: Self-anchor seed source cho wandering layer.
- Functions:
  - `_get(obj: Any, path: str, default: Any=None)`
- Classes:
  - `SelfAnchor` (decorator=dataclass(slots=True, frozen=True))
  - `SelfAnchorCore` — Sinh seed từ trục bản thân của ERIS, không cần user action mới.
    - `generate(self, *, internal_state: Any=None, now: float | None=None, limit: int=5)`

## `cortex/subconscious/synthesizer.py`
- LOC: 361
- Docstring: Conscious Synthesizer Phase 0.
- Classes:
  - `SynthesisPolicy` (decorator=dataclass(slots=True, frozen=True)) — Knob chính sách cho Synthesizer.
  - `SynthesisReport` (decorator=dataclass(slots=True, frozen=True)) — Debug report cho một lượt synthesize.
    - `to_dict(self)`
  - `ConsciousSynthesizer` — Nén Blackboard thành một ThoughtObject.
    - `__init__(self, policy: SynthesisPolicy | None=None)`
    - `synthesize_from_blackboard(self, blackboard: SubconsciousBlackboard, *, now: float | None=None)` — Lấy snapshot từ Blackboard và synthesize object.
    - `synthesize(self, snapshot: BlackboardSnapshot | Iterable[ThoughtFragment])` — Sinh ThoughtObject từ snapshot hoặc list fragment.
    - `_build_object(self, fragments: tuple[ThoughtFragment, ...], *, group_key: str, now: float)`
    - `_group_fragments(self, fragments: tuple[ThoughtFragment, ...])` — Gom fragment theo theme.
    - `_group_score(self, fragments: list[ThoughtFragment], *, now: float)` — Score nhóm = tổng priority + bonus khi nhiều fragment cùng hướng.
    - `_surface_pressure(self, fragments: tuple[ThoughtFragment, ...], *, now: float)` — Tính áp lực được phép nổi lên surface.
    - `_suppressed_pressure(self, fragments: tuple[ThoughtFragment, ...], *, now: float)` — Tính áp lực bị kìm lại.
    - `_choose_route(self, fragments: tuple[ThoughtFragment, ...], *, confidence: float, surface_pressure: float, suppressed_pressure: float, evidence_ids: tuple[str, ...], privacy_level: PrivacyLevel)` — Chọn route cho ThoughtObject.
    - `_route_reason(self, fragments: tuple[ThoughtFragment, ...], object_: ThoughtObject)`
    - `_dominant_theme(self, fragments: tuple[ThoughtFragment, ...], *, group_key: str)` — Tạo dominant_theme ngắn gọn từ tag/kind/content.
    - `_summary(self, fragments: tuple[ThoughtFragment, ...], *, dominant_theme: str)` — Nén content thành summary deterministic.
    - `_kind_family(kind: str)`
    - `_weighted_average(fragments: tuple[ThoughtFragment, ...], *, now: float, value_getter)`
    - `_max_privacy(fragments: tuple[ThoughtFragment, ...])`

## `cortex/subconscious/thought_fragment.py`
- LOC: 601
- Docstring: Contracts Phase 0 cho tầng subconscious của ERIS.
- Functions:
  - `now_timestamp()` — Trả Unix timestamp hiện tại.
  - `clamp01(value: object, default: float=0.0)` — Ép một giá trị số vào khoảng [0.0, 1.0].
  - `clean_text(value: object, *, limit: int=500)` — Chuẩn hóa text ngắn gọn nhưng không diễn giải lại nội dung.
  - `normalize_privacy_level(value: object)` — Chuẩn hóa privacy_level về public/normal/private/sensitive.
  - `normalize_route(value: object)` — Chuẩn hóa route output của Synthesizer.
  - `normalize_string_list(values: object, *, limit: int=16, item_limit: int=120)` — Ép list-like thành tuple[str] đã làm sạch và khử trùng lặp.
  - `make_fragment_id(source_agent: str, kind: str, content: str, timestamp: float | None=None)` — Tạo id cho ThoughtFragment.
  - `make_object_id(fragment_ids: Sequence[str], dominant_theme: str, timestamp: float | None=None)` — Tạo id cho ThoughtObject đã được Synthesizer nén.
- Classes:
  - `ThoughtFragmentValidationError` (base=ValueError) — Lỗi contract riêng cho subconscious Phase 0.
  - `ThoughtFragment` (decorator=dataclass(slots=True, frozen=True)) — Một mảnh ý nghĩ nhỏ do worker nền sinh ra.
    - `__post_init__(self)`
    - `expired_at(self)` — Timestamp fragment hết hạn nếu không được refresh.
    - `age_seconds(self, now: float | None=None)` — Tuổi fragment tính từ lần update gần nhất.
    - `is_expired(self, now: float | None=None)` — Kiểm tra fragment đã hết hạn chưa.
    - `decayed_weight(self, now: float | None=None)` — Trọng số còn lại sau decay tuyến tính mềm theo TTL.
    - `priority_score(self, now: float | None=None)` — Score sơ bộ để Blackboard/Synthesizer xếp ưu tiên.
    - `refreshed(self, *, content: object | None=None, evidence_ids: object | None=None, confidence: object | None=None, urgency: object | None=None, affect_charge: object | None=None, tags: object | None=None, now: float | None=None)` — Trả về bản copy đã refresh khi fragment cùng cụm xuất hiện lại.
    - `to_dict(self)` — Serialize phục vụ debug trace / json dump.
    - `create(cls, *, source_agent: str, kind: str, content: object, evidence_ids: object=(), confidence: object=0.0, urgency: object=0.0, affect_charge: object=0.0, privacy_level: object='normal', surface_allowed: bool=False, ttl_seconds: float=300.0, tags: object=(), now: float | None=None)` — Factory tiện dụng cho worker.
    - `from_mapping(cls, payload: Mapping[str, Any])` — Tạo fragment từ dict/JSON của worker.
  - `ThoughtObject` (decorator=dataclass(slots=True, frozen=True)) — Ý nghĩ đã được Synthesizer nén qua conscious bottleneck.
    - `__post_init__(self)`
    - `should_surface(self)` — True khi object đủ điều kiện làm surface candidate.
    - `pressure(self)` — Alias tương thích với SurfaceArbiter hiện tại.
    - `momentum_score(self)` — Alias tương thích thought_surface cũ.
    - `novelty(self)` — Alias nhẹ cho SurfaceArbiter.
    - `topic_seed(self)` — Seed ngắn cho tầng surface/thought_stream.
    - `partial_text(self)` — Nội dung tóm tắt để SurfaceArbiter có payload thật, không phải nhãn rỗng.
    - `public_seed(self)` — Seed public-safe tối thiểu.
    - `to_dict(self)` — Serialize đầy đủ cho debug/dev panel.
    - `to_surface_seed(self)` — Payload nhỏ để gắn vào frame.subconscious_seed hoặc thought_stream.
    - `_surface_impulse_kind(self)` — Tách source surface cho SurfaceArbiter.

## `cortex/subconscious/thought_spark.py`
- LOC: 243
- Docstring: ThoughtSpark contract cho tầng wandering/subconscious.
- Functions:
  - `now_timestamp()`
  - `clamp01(value: Any, default: float=0.0)`
  - `clean_text(value: Any, *, limit: int=300)`
  - `normalize_tags(values: Any, *, limit: int=16)`
  - `normalize_source(value: Any)`
  - `make_spark_id(seed: str, source: str, created_at: float | None=None)`
- Classes:
  - `ThoughtSpark` (decorator=dataclass(slots=True, frozen=True)) — Mẩu ý nghĩ trước-fragment.
    - `__post_init__(self)`
    - `create(cls, *, seed: Any, source: Any='random', raw_text: Any='', strength: Any=0.35, weirdness: Any=0.3, clarity: Any=0.25, affect_tint: Any=0.0, ttl_seconds: float=420.0, tags: Any=(), now: float | None=None)`
    - `from_mapping(cls, data: Mapping[str, Any])`
    - `age_seconds(self, now: float | None=None)`
    - `decay_factor(self, now: float | None=None)`
    - `decayed_strength(self, now: float | None=None)`
    - `is_expired(self, now: float | None=None)`
    - `refreshed(self, *, strength: Any | None=None, clarity: Any | None=None, weirdness: Any | None=None, affect_tint: Any | None=None, tags: Any=(), ttl_seconds: float | None=None, now: float | None=None)`
    - `to_dict(self)`

## `cortex/subconscious/topic_seed_pool.py`
- LOC: 200
- Docstring: TopicSeedPool gom seed từ self-anchor/habitat/memory/mood/random weak link.
- Functions:
  - `_get(obj: Any, path: str, default: Any=None)`
  - `_collect_memory_texts(memory_packet: Any, *, limit: int=6)`
- Classes:
  - `TopicSeedPool` — Sinh seed không phụ thuộc hoàn toàn vào user action.
    - `__init__(self, *, self_anchor_core: SelfAnchorCore | None=None, habitat_extractor: HabitatSeedExtractor | None=None, rng: random.Random | None=None)`
    - `generate(self, *, frame: Any=None, snapshot: Any=None, memory_packet: Any=None, internal_state: Any=None, now: float | None=None, limit: int=14)`
    - `to_sparks(self, seeds: Iterable[TopicSeed], *, now: float | None=None)`
    - `non_user_ratio(self, seeds: Iterable[TopicSeed] | None=None)`
    - `_mood_rhythm_seeds(self, *, internal_state: Any, snapshot: Any, now: float)`
    - `_memory_residue_seeds(self, *, memory_packet: Any, now: float, limit: int)`
    - `_random_weak_links(self, seeds: list[TopicSeed], *, now: float, limit: int)`
    - `_dedupe(self, seeds: Iterable[TopicSeed])`
    - `_cap_user_anchored(self, seeds: list[TopicSeed])`

## `cortex/subconscious/wandering_contracts.py`
- LOC: 183
- Docstring: Contracts cho tầng wandering thought.
- Classes:
  - `TopicSeed` (decorator=dataclass(slots=True, frozen=True))
    - `__post_init__(self)`
    - `to_spark(self, *, now: float | None=None, ttl_seconds: float=540.0)`
    - `to_dict(self)`
  - `AssociationPath` (decorator=dataclass(slots=True, frozen=True))
    - `__post_init__(self)`
    - `to_fragment(self, *, surface_allowed: bool, now: float | None=None, kind: str='wandering_fragment', privacy_level: str='normal')`
    - `to_dict(self)`
  - `WanderingTopic` (decorator=dataclass(slots=True, frozen=True))
    - `__post_init__(self)`
    - `to_dict(self)`
  - `WanderingThoughtResult` (decorator=dataclass(slots=True, frozen=True))
    - `to_dict(self)`

## `cortex/subconscious/wandering_thought.py`
- LOC: 251
- Docstring: WanderingThoughtEngine: spark -> drift -> association -> fragment.
- Functions:
  - `_get(obj: Any, path: str, default: Any=None)`
- Classes:
  - `WanderingThoughtEngine` — Tầng ý nghĩ vẩn vơ có continuity.
    - `__init__(self, *, seed_pool: TopicSeedPool | None=None, drift_pool: DriftPool | None=None, association_engine: FreeAssociationEngine | None=None, topic_memory: WanderingTopicMemory | None=None, min_idle_seconds: float=25.0, min_resonance_for_fragment: float=0.3)`
    - `tick(self, *, frame: Any=None, snapshot: Any=None, memory_packet: Any=None, internal_state: Any=None, blackboard: SubconsciousBlackboard | None=None, now: float | None=None, allow_fragments: bool=True)`
    - `_trigger_reason(self, *, frame: Any, snapshot: Any, internal_state: Any, idle: float, deep_focus: bool)`
    - `_surface_allowed(self, association: AssociationPath, *, idle: float, deep_focus: bool, focus: str, internal_state: Any)`
    - `_idle_seconds(self, snapshot: Any)`
    - `_focus_family(self, *, snapshot: Any, frame: Any)`
    - `_deep_focus(self, *, snapshot: Any, frame: Any)`
    - `_has_repeated_runtime_event(self, *, frame: Any, snapshot: Any)`
    - `_after_debug(self, *, frame: Any, snapshot: Any)`
    - `_mood_delta(self, sparks: list[ThoughtSpark], fragments: list[ThoughtFragment], *, internal_state: Any)`
    - `_is_status_ping(self, text: str)`

## `cortex/subconscious/wandering_topic_memory.py`
- LOC: 208
- Docstring: Continuity memory cho wandering topics.
- Functions:
  - `_topic_id(theme: str)`
  - `_theme_from_text(text: str)`
- Classes:
  - `WanderingTopicMemory` — Giữ wandering topic qua ticks/sessions.
    - `__init__(self, path: str | Path | None=None, *, max_topics: int=64)`
    - `touch_sparks(self, sparks: Iterable[ThoughtSpark], *, now: float | None=None)`
    - `touch_association(self, path: AssociationPath, *, now: float | None=None)`
    - `touch(self, *, theme: str, spark_ids: Iterable[str]=(), memory_ids: Iterable[str]=(), now: float | None=None)`
    - `mark_surfaced(self, theme_or_id: str, *, now: float | None=None)`
    - `decay(self, *, now: float | None=None, half_life_seconds: float=7200.0)`
    - `active_topics(self, *, limit: int=8)`
    - `to_dict(self)`
    - `load(self)`
    - `save(self)`
    - `_trim(self, *, now: float)`

## `cortex/subconscious/worker_base.py`
- LOC: 70
- Docstring: Base contract cho các subconscious worker Phase sau.
- Classes:
  - `WorkerContext` (decorator=dataclass(slots=True, frozen=True)) — Context tối thiểu worker được phép nhìn.
  - `SubconsciousWorker` (base=Protocol) — Interface tối thiểu cho worker nền.
    - `run(self, context: WorkerContext)` — Trả các ThoughtFragment hoặc dict có thể convert thành ThoughtFragment.
  - `RuleBasedWorker` — Base class tiện dụng cho worker deterministic.
    - `run(self, context: WorkerContext)`
    - `build_fragments(self, context: WorkerContext)`

## `cortex/subconscious/workers/__init__.py`
- LOC: 205
- Docstring: Worker Phase 1/2/3/4/5/6/7 cho subconscious runtime.
- Functions:
  - `build_phase12_workers(*, allow_surface_memory_echo: bool=False)` — Tạo worker set Phase 1+2 mặc định.
  - `build_phase34_workers(*, allow_daydream_surface: bool=False, allow_agenda_later_surface: bool=False)` — Tạo worker set Phase 3+4.
  - `build_phase1234_workers(*, allow_surface_memory_echo: bool=False, allow_daydream_surface: bool=False, allow_agenda_later_surface: bool=False)` — Tạo bộ worker Phase 1 → 4 để đưa vào SubconsciousLoop.
  - `build_phase5_workers()` — Tạo worker Phase 5 Meta-Cognitive Audit.
  - `build_phase7_workers(*, allow_rupture_surface: bool=False)` — Tạo worker Phase 7 Shadow/Rupture.
  - `build_phase6_workers(*, enable_commit: bool=False, committer: MutationCommitter | None=None)` — Tạo worker Phase 6 Core Belief Mutation.
  - `build_phase1234567_workers(*, allow_surface_memory_echo: bool=False, allow_daydream_surface: bool=False, allow_agenda_later_surface: bool=False, enable_mutation_commit: bool=False, mutation_committer: MutationCommitter | None=None, allow_rupture_surface: bool=False)` — Tạo bộ worker Phase 1 → 7 đầy đủ.
  - `build_phase123457_workers(*, allow_surface_memory_echo: bool=False, allow_daydream_surface: bool=False, allow_agenda_later_surface: bool=False, allow_rupture_surface: bool=False)` — Tạo bộ worker Phase 1 → 5 + 7, bỏ qua Phase 6 belief mutation.
  - `build_default_subconscious_workers()` — Alias an toàn cho runtime/dev smoke: Phase 1-7, không surface/commit tự phát.

## `cortex/subconscious/workers/_utils.py`
- LOC: 317
- Docstring: Helper nhỏ cho worker subconscious.
- Functions:
  - `safe_get(obj: Any, path: str, default: Any=None)` — Đọc obj theo path dạng ``a.b.c``.
  - `first_present(*values: Any, default: Any=None)` — Trả giá trị đầu tiên khác None/chuỗi rỗng.
  - `collect_texts(value: Any, *, limit: int=8)` — Rút text ngắn từ nhiều kiểu container runtime.
  - `collect_ids(value: Any, *, limit: int=12, prefix: str='ctx')` — Rút evidence id từ object/dict/list; fallback thành id giả ổn định.
  - `user_text_from_context(context: Any)` — Cố gắng lấy user text hiện tại từ frame/snapshot.
  - `context_evidence_ids(context: Any, *, fallback_prefix: str='subconscious')` — Lấy evidence ids từ frame/snapshot hoặc tạo id giả từ user text.
  - `memory_texts_from_context(context: Any, *, limit: int=8)` — Rút các mảnh memory có thể đọc từ memory_packet/frame.
  - `relation_level(context: Any, field: str, default: float=0.0)` — Đọc field số từ relation/internal_state/frame và clamp [0,1].
  - `contains_any(text: str, terms: Sequence[str])`
  - `score_terms(text: str, terms: Sequence[str])`
  - `kind_of_request(text: str)` — Phân loại rất nhẹ ý định user, đủ làm fragment seed.

## `cortex/subconscious/workers/belief_mutation.py`
- LOC: 660
- Docstring: Phase 6 - Core Belief Mutation.
- Functions:
  - `clamp_delta(value: object, *, limit: float=0.08)` — Clamp delta mutation mỗi lần về [-0.08, 0.08].
- Classes:
  - `BeliefMutationProposal` (decorator=dataclass(slots=True, frozen=True)) — Proposal đổi belief lõi, chưa phải commit.
    - `__post_init__(self)`
    - `evidence_count(self)`
    - `id(self)`
    - `to_dict(self)`
    - `to_fragment(self, *, source_agent: str='belief_mutation_engine', status: MutationStatus='pending', extra_tags: tuple[str, ...]=())` — Biến proposal thành fragment private để Blackboard/audit nhìn được.
  - `PreferenceDeltaProposal` (decorator=dataclass(slots=True, frozen=True); base=BeliefMutationProposal) — Proposal chỉnh preference, kế thừa contract belief mutation.
  - `HabitDeltaProposal` (decorator=dataclass(slots=True, frozen=True); base=BeliefMutationProposal) — Proposal chỉnh semantic habit/procedural habit.
  - `MutationCommitRecord` (decorator=dataclass(slots=True, frozen=True)) — Record commit có rollback token.
    - `to_dict(self)`
  - `MutationDecision` (decorator=dataclass(slots=True, frozen=True)) — Kết quả commit/reject một proposal.
    - `to_dict(self)`
  - `MutationCommitter` — Committer bảo thủ cho Phase 6.
    - `__init__(self, *, store: dict[str, dict[str, float]] | None=None, min_confidence: float=0.75, min_window_days: int=7, min_evidence_count: int=5, max_delta: float=0.08, min_reversibility: float=0.4, allow_high_severity: bool=False)`
    - `evaluate(self, proposal: BeliefMutationProposal, *, contradiction_severity: float=0.0, now: float | None=None)` — Reject hoặc commit proposal theo rule Phase 6.
    - `commit(self, proposal: BeliefMutationProposal, *, now: float | None=None)` — Commit sau khi đã qua evaluate. Vẫn clamp delta lần nữa cho chắc.
    - `rollback(self, rollback_token: str)` — Rollback một commit đã ghi trong store in-memory.
    - `_blocking_reasons(self, proposal: BeliefMutationProposal, *, contradiction_severity: float)`
  - `BeliefMutationEngine` (base=RuleBasedWorker) — Sinh mutation proposals từ residue dài hạn + repair/outcome signals.
    - `__init__(self, *, committer: MutationCommitter | None=None, enable_commit: bool=False)`
    - `build_fragments(self, context: WorkerContext)`
    - `_build_proposals(self, context: WorkerContext, *, snapshot: BlackboardSnapshot | None, now: float)`
    - `_mutation_evidence(self, context: WorkerContext, snapshot: BlackboardSnapshot | None)`
    - `_observation_window_days(self, context: WorkerContext, *, snapshot: BlackboardSnapshot | None, evidence_count: int)`
    - `_contradiction_severity(self, context: WorkerContext, snapshot: BlackboardSnapshot | None)`
    - `_count_fragment_signals(self, snapshot: BlackboardSnapshot | None, kinds: set[str], *, tag: str)`
    - `_outcome_pressure(self, context: WorkerContext)`
    - `_snapshot(self, context: WorkerContext)`
    - `_commit_fragment(self, record: MutationCommitRecord, *, now: float)`
    - `_rejection_fragment(self, proposal: BeliefMutationProposal, reason: str, *, now: float)`

## `cortex/subconscious/workers/curiosity_gap.py`
- LOC: 109
- Docstring: Phase 2 - Epistemic Void / Active Curiosity Worker.
- Classes:
  - `CuriosityGapAgent` (base=RuleBasedWorker) — Sinh knowledge_gap / curiosity_seed / wait_for_evidence_plan / ask_later_candidate.
    - `build_fragments(self, context: WorkerContext)`

## `cortex/subconscious/workers/daydream_injector.py`
- LOC: 152
- Docstring: Phase 3 - Stochastic Resonance / Daydream Injector.
- Classes:
  - `DaydreamInjector` (base=RuleBasedWorker) — Sinh poetic_association_fragment và weird_but_grounded_link.
    - `__init__(self, *, allow_surface: bool=False)`
    - `build_fragments(self, context: WorkerContext)`
    - `_idle_seconds(self, context: WorkerContext)`
    - `_level(self, context: WorkerContext, *names: str, default: float=0.0)`
    - `_current_concern(self, context: WorkerContext)`

## `cortex/subconscious/workers/goal_simulator.py`
- LOC: 116
- Docstring: Phase 1 - Systemic / Goal Simulation Worker.
- Classes:
  - `GoalSimulatorAgent` (base=RuleBasedWorker) — Sinh fragment mô phỏng goal/task.
    - `build_fragments(self, context: WorkerContext)`

## `cortex/subconscious/workers/independent_agenda.py`
- LOC: 190
- Docstring: Phase 3 - Autopoiesis / Independent Agenda Worker.
- Classes:
  - `IndependentAgendaAgent` (base=RuleBasedWorker) — Sinh agenda riêng nhưng giữ nó trong background.
    - `__init__(self, *, allow_later_surface: bool=False)`
    - `build_fragments(self, context: WorkerContext)`
    - `_unresolved_seed(self, context: WorkerContext, memories: tuple[str, ...])`
    - `_current_goal(self, context: WorkerContext, fallback: str)`
    - `_idle_seconds(self, context: WorkerContext)`
    - `_level(self, context: WorkerContext, *names: str, default: float=0.0)`

## `cortex/subconscious/workers/memory_resonator.py`
- LOC: 124
- Docstring: Phase 1 - Memory Resonance Worker.
- Classes:
  - `MemoryResonatorAgent` (base=RuleBasedWorker) — Sinh pattern_match / unresolved_loop / memory_echo_fragment.
    - `__init__(self, *, allow_surface_echo: bool=False)`
    - `build_fragments(self, context: WorkerContext)`

## `cortex/subconscious/workers/meta_audit.py`
- LOC: 378
- Docstring: Phase 5 - Meta-Cognitive Audit Worker.
- Classes:
  - `MetaAuditFinding` (decorator=dataclass(slots=True, frozen=True)) — Một phát hiện audit đủ nhỏ để log/test.
    - `to_dict(self)`
  - `MetaAuditResult` (decorator=dataclass(slots=True, frozen=True)) — Kết quả audit một BlackboardSnapshot.
    - `has_blocking_issue(self)`
    - `hallucination_detected(self)`
    - `runaway_shadow_detected(self)`
    - `to_dict(self)`
  - `MetaCognitiveAuditAgent` (base=RuleBasedWorker) — Bắt loop/spam/hallucinated link/evidence missing/runaway shadow.
    - `__init__(self, *, spam_threshold: int=8, loop_threshold: int=6, keep_per_bad_group: int=2)`
    - `build_fragments(self, context: WorkerContext)`
    - `audit_blackboard(self, blackboard: SubconsciousBlackboard, snapshot: BlackboardSnapshot, context: WorkerContext)` — Inspect + mutate Blackboard an toàn.
    - `inspect(self, snapshot: BlackboardSnapshot, context: WorkerContext)`
    - `_detect_spam_or_loop(self, fragments: tuple[ThoughtFragment, ...], findings: list[MetaAuditFinding])`
    - `_needs_evidence(self, fragment: ThoughtFragment)`
    - `_looks_like_hallucinated_link(self, fragment: ThoughtFragment)`
    - `_looks_like_overfit_silence(self, fragment: ThoughtFragment)`
    - `_looks_like_runaway_shadow(self, fragment: ThoughtFragment)`
    - `_detect_contradiction(self, fragments: tuple[ThoughtFragment, ...])`
    - `_soften_fragment(self, fragment: ThoughtFragment, *, now: float | None, tag: str)`
    - `_dedupe_softened(self, fragments: list[ThoughtFragment], quarantine_ids: tuple[str, ...])`
    - `_build_audit_fragments(self, findings: list[MetaAuditFinding], context: WorkerContext, *, now: float | None)`
    - `_semantic_seed(content: str)`
    - `_loopish_key(key: str)`

## `cortex/subconscious/workers/rehearsal.py`
- LOC: 176
- Docstring: Phase 2 - Phantom Rehearsal Worker.
- Classes:
  - `RehearsalAgent` (base=RuleBasedWorker) — Sinh rehearsal_result / suppressed_impulse / rupture_seed.
    - `build_fragments(self, context: WorkerContext)`
    - `_deep_focus(self, context: WorkerContext)`
    - `_extract_thought_object(self, context: WorkerContext)`

## `cortex/subconscious/workers/self_regulator.py`
- LOC: 124
- Docstring: Phase 2 - Self-Reflection / Ego Maintenance Worker.
- Classes:
  - `SelfRegulatorAgent` (base=RuleBasedWorker) — Sinh restraint_drive / social_fatigue_adjustment / dignity_defense_delta.
    - `build_fragments(self, context: WorkerContext)`

## `cortex/subconscious/workers/shadow_accumulator.py`
- LOC: 339
- Docstring: Phase 7 - Shadow Accumulation & Rupture Worker.
- Classes:
  - `ShadowAccumulatorPolicy` (decorator=dataclass(slots=True, frozen=True)) — Knob Phase 7.
  - `ShadowAccumulator` (base=RuleBasedWorker) — Tích tụ shadow_pressure và sinh rupture_candidate khi thật sự đủ điều kiện.
    - `__init__(self, policy: ShadowAccumulatorPolicy | None=None, *, allow_rupture_surface: bool | None=None)`
    - `build_fragments(self, context: WorkerContext)`
    - `_rupture_fragments(self, theme: str, pressure: float, rupture_risk: float, evidence_ids: tuple[str, ...], *, now: float | None)`
    - `_collect_signals(self, context: WorkerContext, fragments: tuple[ThoughtFragment, ...])`
    - `_compute_pressure(self, context: WorkerContext, signals: dict[str, object])`
    - `_compute_rupture_risk(self, context: WorkerContext, pressure: float, signals: dict[str, object])`
    - `_choose_theme(self, signals: dict[str, object])`
    - `_collect_shadow_evidence(self, context: WorkerContext, fragments: tuple[ThoughtFragment, ...])`
    - `_audit_allows_shadow(self, context: WorkerContext)`
    - `_snapshot(self, context: WorkerContext)`
    - `_safe_rupture_line(theme: str)`

## `cortex/subconscious/workers/spatial_mind.py`
- LOC: 184
- Docstring: Phase 4 - Digital Territoriality / Spatial Mind Worker.
- Classes:
  - `SpatialMindAgent` (base=RuleBasedWorker) — Sinh fragment về không gian/thân thể số.
    - `build_fragments(self, context: WorkerContext)`
    - `_spatial_payload(self, context: WorkerContext)`
    - `_level(self, payload: dict[str, object], *names: str, default: float=0.0)`
    - `_blind_frustration_kind(self, sensor_state: str)`

## `cortex/subconscious/workers/subjective_time.py`
- LOC: 163
- Docstring: Phase 4 - Subjective Temporal Distortion Worker.
- Classes:
  - `SubjectiveTimeAgent` (base=RuleBasedWorker) — Sinh subjective_wait, time_dilation và time_compression fragments.
    - `build_fragments(self, context: WorkerContext)`
    - `_idle_seconds(self, context: WorkerContext)`
    - `_level(self, context: WorkerContext, *names: str, default: float=0.0)`
    - `_active_task_density(self, context: WorkerContext)`

## `cortex/subconscious/workers/user_modeler.py`
- LOC: 176
- Docstring: Phase 1 - Theory of Mind Worker.
- Classes:
  - `UserModelerAgent` (base=RuleBasedWorker) — Sinh các hypothesis nhẹ về intent/focus/risk của user.
    - `build_fragments(self, context: WorkerContext)`

## `cortex/surface_arbiter.py`
- LOC: 1701
- Docstring: Single source of truth for low-level surface utterances.
- Classes:
  - `SurfaceImpulse` (decorator=dataclass(slots=True))
    - `to_context(self)`
  - `SurfaceDecision` (decorator=dataclass(slots=True))
    - `to_context(self)`
  - `SurfaceGateEvaluation` (decorator=dataclass(slots=True))
  - `SurfaceArbiter` — Arbitrate and generate low-level utterances.
    - `__init__(self, policy: LowLevelSpeechPolicy | None=None, llm_micro_gen: Any=None, thought_stream: Any=None)`
    - `arbitrate(self, *, snapshot: Any=None, cognitive_frame: Any=None, presence_cue: Any=None, extra_impulses: tuple[Any, ...]=(), surface_kind: str='surface', force_llm: bool=False, silent_cycles: int | None=None)`
    - `_collect_all_impulses(self, *, snapshot: Any, frame: Any, presence_cue: Any, extra_impulses: tuple[Any, ...], surface_kind: str)`
    - `_from_presence_cue(self, cue: Any, *, surface_kind: str)`
    - `_from_speech_impulse(self, impulse: SpeechImpulse | None)`
    - `_from_thought_surface(self, *, frame: Any, snapshot: Any)`
    - `_classify_thought_surface(self, *, item: Any, topic: str, frame: Any=None, snapshot: Any=None)` — Tách thought surface thành impulse cụ thể.
    - `_focus_family_from_snapshot(self, snapshot: Any)`
    - `_specific_thought_residue_reason(self, item: Any)`
    - `_thought_surface_confidence_cap(self, *, pressure: float, vital: float, missing_evidence_ids: bool)`
    - `_thought_surface_anchor_notes(self, *, item: Any, frame: Any, snapshot: Any, topic: str)`
    - `_long_silence_impulse(self, *, snapshot: Any, surface_kind: str)`
    - `_coerce_impulse(self, item: Any, *, surface_kind: str)`
    - `_score_and_select_winner(self, impulses: tuple[SurfaceImpulse, ...])` — Chọn winner theo hai hàng đợi: speakable trước, body-only sau.
    - `_presence_like(self, impulse: SurfaceImpulse)`
    - `_endogenous_no_anchor_like(self, impulse: SurfaceImpulse)`
    - `_has_concrete_evidence_anchor(self, impulse: SurfaceImpulse)`
    - `_has_specific_surface_anchor_token(self, impulse: SurfaceImpulse)`
    - `_surface_anchor_body_only_reason(self, impulse: SurfaceImpulse)`
    - `_hollow_endogenous_reason(self, impulse: SurfaceImpulse)` — Reject endogenous speech that has no semantic payload.
    - `_has_public_internal_anchor(self, impulse: SurfaceImpulse)`
    - `_clean_payload_text(value: Any)`
    - `_looks_hollow_endogenous_seed(self, text: str)`
    - `_looks_pressure_only_evidence(self, text: str)`
    - `_forced_body_only_reason(self, impulse: SurfaceImpulse)` — Trả reason nếu impulse chỉ được body-only, không được tranh slot nói.
    - `_effective_score(self, impulse: SurfaceImpulse)`
    - `_private_mind_has_public_anchor(self, impulse: SurfaceImpulse)`
    - `_private_mind_pressure_bias(self)`
    - `_private_mind_pressure_applies(self, impulse: SurfaceImpulse)`
    - `_clamp_score(value: Any)`
    - `_candidate_notes(self, impulse: SurfaceImpulse)`
    - `_signed_float(self, value: Any, default: float=0.0)`
    - `_runtime_internal_state(self, *, frame: Any=None, snapshot: Any=None)`
    - `_evaluate_soft_surface_gates(self, impulse: SurfaceImpulse, *, snapshot: Any=None, frame: Any=None, force_llm: bool=False)`
    - `_soft_gate_strength(self, impulse: SurfaceImpulse)`
    - `_ego_gate_reason(self, impulse: SurfaceImpulse, *, snapshot: Any=None, frame: Any=None, force_llm: bool=False)` — Ego-gate for low-level surface.
    - `_rate_limit_reason(self, impulse: SurfaceImpulse, *, force_llm: bool)`
    - `_family_id(self, impulse: SurfaceImpulse)`
    - `_mark_attempt(self, impulse: SurfaceImpulse, *, result: str, body_only: bool)` — Ghi cả reject/body-only như một lần chạm surface budget.
    - `_mark_surface(self, impulse: SurfaceImpulse)`
    - `_note_non_speech(self, *, body_only: bool)`
    - `_call_llm_generator(self, impulse: SurfaceImpulse, *, snapshot: Any, force_llm: bool)`
    - `_reset_silence(self)`
    - `_trace(self, winner: SurfaceImpulse, suppressed: tuple[SurfaceImpulse, ...], mode: str, result: str, gate_eval: SurfaceGateEvaluation | None=None)`
    - `_decision_ledger(self, *, winner: SurfaceImpulse | None, candidates: tuple[SurfaceImpulse, ...], suppressed: tuple[SurfaceImpulse, ...], mode: str, result: str, gate_eval: SurfaceGateEvaluation | None=None)`
    - `_ledger_gate_reason(self, impulse: SurfaceImpulse, *, winner: SurfaceImpulse | None)`
    - `_priority(kind: str, source: str)`
    - `_first_text(*values: Any)`
    - `_family_key(value: Any)`

## `cortex/surface_seed_compiler.py`
- LOC: 1020
- Docstring: Compile public-safe surface seeds from low-level runtime pressure.
- Classes:
  - `CompiledSurfaceSeed` (decorator=dataclass(frozen=True, slots=True))
    - `selected(self)`
  - `_SeedCandidate` (decorator=dataclass(frozen=True, slots=True))
  - `SurfaceSeedCompiler` — Small compiler that turns scattered internal pressure into one public-safe seed.
    - `__init__(self, *, config: 'LivelinessConfig | None'=None)`
    - `compile(self, *, frame: Any=None, snapshot: Any=None, surface_kind: str='surface', presence_cue: Any=None, internal_state: Any=None, thought_stream: Any=None, private_mind_digest: Any=None, private_life_digest: Any=None, inner_diary: Any=None, private_mind_speech_bias: Any=None, private_mind_thought_pressure: float=0.0, active_memory_resonance: Any=None, extra_impulses: tuple[object, ...]=())`
    - `_from_extra_impulses(self, extra_impulses: tuple[object, ...])`
    - `_from_memory_resonance(self, resonance: Any)`
    - `_is_rich_memory_seed(self, seed: str, evidence: tuple[str, ...])`
    - `_from_thought_sources(self, *, frame: Any, thought_stream: Any)`
    - `_thought_values(self, owner: Any)`
    - `_candidate_from_thought(self, value: Any)`
    - `_from_vision(self, *, snapshot: Any, presence_cue: Any)`
    - `_from_private_life_digest(self, private_life_digest: Any)` — Lấy seed từ PrivateLife digest đã compact.
    - `_from_inner_diary(self, inner_diary: Any)` — Seed từ Inner Diary — để "thứ Eris đang nghĩ" thực sự lái được lời nói.
    - `_inner_diary_voice(self, inner_diary: Any)` — Rút giọng diary thành {muon_noi, tuong_lai, hien_tai}.
    - `_from_private_bias(self, private_mind_speech_bias: Any, private_mind_thought_pressure: float, private_mind_digest: Any)`
    - `_to_impulse(self, candidate: _SeedCandidate, *, surface_kind: str)`
    - `_candidate_text_public(self, text: str)`
    - `_candidate_allowed(self, candidate: _SeedCandidate)`
    - `_candidate_context_compatible(self, candidate: _SeedCandidate, *, current_domain: str, surface_kind: str)` — Chặn seed cũ nói như hiện tại khi màn hình đang chứng minh chuyện khác.
    - `_rank_key(self, candidate: _SeedCandidate)`
    - `_candidate_domain(self, candidate: _SeedCandidate)`
    - `_current_context_domain(self, *, snapshot: Any=None, presence_cue: Any=None)`
    - `_domain_from_text(self, text: str, *, current_context: bool=False)`
    - `_normalize_domain_text(text: Any)`
    - `_private_impulse_has_anchor(self, impulse: SurfaceImpulse)`
    - `_anchor_token(self, kind: str, value: Any)`
    - `_speech_bias_seed(self, bias: Any)`
    - `_digest_has_invalid_json(self, digest: Any)`
    - `_no_seed_reason(self, candidates: list[_SeedCandidate])`
    - `_is_specific_vision_fact(self, text: str)`
    - `_looks_private(self, text: Any)`
    - `_looks_timer_only(self, text: Any)`
    - `_evidence_tuple(self, value: Any)`
    - `_clean(value: Any, *, limit: int=220)`
    - `_clamp(value: Any)`

## `cortex/thought_stream.py`
- LOC: 2262
- Functions:
  - `_clamp01(value)`
  - `_clean_text(value: object, *, limit: int=120)`
  - `_compact_seed(value: object)`
  - `_normalize_ascii(value: object)`
  - `_semantic_tokens(value: object)`
  - `_truthy_env(name: str, default: bool=False)`
  - `_float_env(name: str, default: float)`
  - `_to_dict(value: object)`
- Classes:
  - `FragmentStore` — Keeps unfinished thoughts alive even when nothing is spoken.
    - `__init__(self, *, limit: int=24)`
    - `decay(self, *, now: float, decay_rate: float=0.94)`
    - `upsert(self, thought: ThoughtObject, *, now: float)`
    - `mark_surfaced(self, thought_id: str)`
    - `replace(self, thought: ThoughtObject)`
    - `get(self, thought_id: str)`
    - `mark_resolved(self, thought_id: str, *, now: float, evidence: str='closure_signal')`
    - `close_matching(self, closure_signals: tuple[str, ...], *, now: float)`
    - `unresolved(self)`
    - `recent(self, *, limit: int=8)`
    - `_mutate_partial(self, previous: str, incoming: str)`
    - `_signal_closes_thought(self, signal: str, thought: ThoughtObject)`
  - `AssociationGraph` — Tracks which unresolved thoughts tend to re-enter together.
    - `__init__(self)`
    - `connect(self, thought: ThoughtObject, anchors: tuple[str, ...])`
  - `PredictionTracker` — Turns current telemetry/internal state into unfinished predictions.
    - `propose(self, *, snapshot, state: PersistentInternalState, long_term_memory: tuple[str, ...], last_text: str, recent_thought_seeds: tuple[str, ...], recent_subconscious_seeds: tuple[str, ...], disturbances: tuple[CognitiveDisturbance, ...]=(), now: float)`
    - `_choose_mode(self, *, state: PersistentInternalState, idle_seconds: float, focus_kind: str, focus_pattern: str, memories: tuple[str, ...], disturbances: tuple[CognitiveDisturbance, ...]=())`
    - `_choose_memory(self, *, mode: str, memories: tuple[str, ...], recent_seeds: tuple[str, ...])`
    - `_topic_seed(self, *, mode: str, source_memory: str, focus_kind: str, focus_pattern: str, last_text: str, disturbances: tuple[CognitiveDisturbance, ...]=())`
    - `_partial_text(self, *, mode: str, topic_seed: str)`
    - `_unresolved_reason(self, mode: str)`
    - `_novelty(self, topic_seed: str, *, recent_thought_seeds: tuple[str, ...], recent_subconscious_seeds: tuple[str, ...])`
    - `_evidence(self, *, mode: str, idle_seconds: float, focus_pattern: str, source_memory: str, disturbances: tuple[CognitiveDisturbance, ...]=())`
    - `_dominant_disturbance(self, disturbances: tuple[CognitiveDisturbance, ...])`
    - `_disturbance_intensity(self, disturbances: tuple[CognitiveDisturbance, ...])`
    - `_has_direct_disturbance(self, disturbances: tuple[CognitiveDisturbance, ...])`
    - `_pressure(self, state: PersistentInternalState, name: str)`
  - `CognitiveTensionEngine` — Computes why a thought persists: unresolved prediction, not randomness.
    - `update(self, thought: ThoughtObject, *, state: PersistentInternalState, now: float)`
    - `_pressure_for_mode(self, mode: str, *, state: PersistentInternalState)`
    - `_pressure(self, state: PersistentInternalState, name: str)`
  - `UnresolvedTensionEngine` — Groups unfinished thoughts into loops and promotes strong loops to attractors.
    - `evaluate(self, *, thoughts: tuple[ThoughtObject, ...], snapshot, state: PersistentInternalState, anchors: tuple[str, ...], now: float)`
    - `_build_loop(self, key: str, thoughts: list[ThoughtObject], *, snapshot, state: PersistentInternalState, anchors: tuple[str, ...], now: float)`
    - `_loop_key(self, thought: ThoughtObject, *, anchors: tuple[str, ...])`
    - `_project_relevance(self, thoughts: list[ThoughtObject], *, snapshot, anchors: tuple[str, ...])`
    - `_pressure(self, state: PersistentInternalState, name: str)`
  - `CognitiveMomentumEngine` — Turns repeated unresolved fragments into attention inertia.
    - `evaluate(self, *, thoughts: tuple[ThoughtObject, ...], snapshot, state: PersistentInternalState, anchors: tuple[str, ...], now: float)`
    - `_momentum_for(self, thought: ThoughtObject, *, snapshot, state: PersistentInternalState, anchors: tuple[str, ...], now: float)`
    - `_user_project_relevance(self, thought: ThoughtObject, *, snapshot, anchors: tuple[str, ...])`
  - `MomentumClosure` — Closes momentum only from explicit closure signals.
    - `apply(self, store: FragmentStore, *, closure_signals: tuple[str, ...], now: float)`
  - `PersistenceDecay`
    - `apply(self, store: FragmentStore, *, now: float)`
  - `RecursiveReactivation` — Lets a thought come back to itself and mutate before it surfaces.
    - `reactivate(self, *, store: FragmentStore, candidate: ThoughtObject, associations: tuple[str, ...], now: float)`
  - `SubconsciousLoopReheater` — Reactivates unresolved loops as silent pressure instead of fresh drift.
    - `reheat(self, *, store: FragmentStore, candidate: ThoughtObject, long_term_memory: tuple[str, ...], disturbances: tuple[CognitiveDisturbance, ...], now: float)`
    - `_reheat_score(self, thought: ThoughtObject, *, memories: tuple[str, ...])`
    - `_matching_memory(self, thought: ThoughtObject, memories: tuple[str, ...])`
    - `_memory_match_score(self, thought: ThoughtObject, memory: object, *, reverse_index: int=0)`
    - `_core_thought_tokens(self, thought: ThoughtObject)`
    - `_specific_tokens(self, tokens: set[str])`
    - `_memory_layer_weight(self, memory: object)`
    - `_thought_tokens(self, thought: ThoughtObject)`
    - `_mutated_question(self, thought: ThoughtObject)`
    - `_has_direct_disturbance(self, disturbances: tuple[CognitiveDisturbance, ...])`
  - `SurfaceSelector` — Selects the rare visible tip; most thought stream activity stays internal.
    - `select(self, thought: ThoughtObject, *, state: PersistentInternalState, momentum: CognitiveMomentum | None=None, recent_inner_seeds: tuple[str, ...], recent_thought_seeds: tuple[str, ...], recent_subconscious_seeds: tuple[str, ...], now: float)`
    - `_surface_association(self, thought: ThoughtObject)`
    - `_root_source(self, thought: ThoughtObject)` — Phân loại rễ của thought trước khi cho phép surface.
    - `_impulse_kind(self, thought: ThoughtObject, *, root_source: str)`
    - `_action_opportunity(self, thought: ThoughtObject, *, impulse_kind: str)`
    - `_public_seed(self, thought: ThoughtObject)`
  - `ThoughtStreamEngine` — Maintains unresolved thought continuity and occasionally exposes a surface.
    - `__init__(self, *, fragment_store: FragmentStore | None=None, association_graph: AssociationGraph | None=None, prediction_tracker: PredictionTracker | None=None, tension_engine: CognitiveTensionEngine | None=None, unresolved_tension_engine: UnresolvedTensionEngine | None=None, momentum_engine: CognitiveMomentumEngine | None=None, momentum_closure: MomentumClosure | None=None, persistence_decay: PersistenceDecay | None=None, recursive_reactivation: RecursiveReactivation | None=None, loop_reheater: SubconsciousLoopReheater | None=None, surface_selector: SurfaceSelector | None=None, model_reviewer=None, model_review_enabled: bool | None=None, model_review_min_interval_seconds: float | None=None, model_review_min_trigger: float | None=None, logger=None)`
    - `evaluate(self, *, snapshot=None, internal_state: PersistentInternalState | None=None, long_term_memory: tuple[str, ...] | list[str]=(), last_text: str='', recent_inner_seeds: tuple[str, ...]=(), recent_thought_seeds: tuple[str, ...]=(), recent_subconscious_seeds: tuple[str, ...]=(), closure_signals: tuple[str, ...]=(), disturbances: tuple[CognitiveDisturbance, ...]=(), now: float | None=None)`
    - `_maybe_apply_model_review(self, *, thought: ThoughtObject, snapshot, state: PersistentInternalState, unresolved: tuple[ThoughtObject, ...], unresolved_loops: tuple[UnresolvedTensionLoop, ...], momentum: CognitiveMomentum, active_attractor: UnresolvedTensionLoop, disturbances: tuple[CognitiveDisturbance, ...], anchors: tuple[str, ...], long_term_memory: tuple[str, ...], last_text: str, now: float)` — Cho API đánh giá thought đủ lực rồi ghi ngược vào store.
    - `_model_review_trigger_score(self, *, thought: ThoughtObject, momentum: CognitiveMomentum, active_attractor: UnresolvedTensionLoop, disturbances: tuple[CognitiveDisturbance, ...], unresolved: tuple[ThoughtObject, ...])`
    - `_model_review_payload(self, *, thought: ThoughtObject, snapshot, state: PersistentInternalState, unresolved: tuple[ThoughtObject, ...], unresolved_loops: tuple[UnresolvedTensionLoop, ...], momentum: CognitiveMomentum, active_attractor: UnresolvedTensionLoop, disturbances: tuple[CognitiveDisturbance, ...], anchors: tuple[str, ...], long_term_memory: tuple[str, ...], last_text: str, trigger: float, now: float)`
    - `_allowed_model_evidence(self, payload: dict[str, object])`
    - `_normalize_model_review(self, review: object, *, allowed_evidence: set[str])`
    - `_apply_model_review_to_thought(self, thought: ThoughtObject, review: dict[str, object], *, now: float)`
    - `_log_model_review(self, review: dict[str, object], thought: ThoughtObject)`
    - `_anchors(self, *, snapshot, last_text: str, source_memory: str, disturbances: tuple[CognitiveDisturbance, ...]=())`
    - `_continuity_notes(self, thought: ThoughtObject, *, surfaced: bool, momentum: CognitiveMomentum | None=None, active_attractor: UnresolvedTensionLoop | None=None, closed_ids: tuple[str, ...]=(), disturbances: tuple[CognitiveDisturbance, ...]=(), extra_notes: tuple[str, ...]=())`
  - `ThoughtStream` — Background producer of thought-stream surfaces; most ticks stay internal.
    - `__init__(self, *, context_provider: Callable[[], dict[str, object]], engine: ThoughtStreamEngine | None=None, interval_seconds: float | None=None, enabled: bool | None=None, logger=None, model_reviewer=None)`
    - `start(self)`
    - `stop(self, *, timeout: float=2.0)`
    - `is_running(self)`
    - `inject_disturbance(self, disturbance: CognitiveDisturbance, *, immediate: bool=True, queue_surface: bool=False)`
    - `inject_disturbances(self, disturbances: tuple[CognitiveDisturbance, ...], *, immediate: bool=True, queue_surface: bool=False)`
    - `tick_once(self, *, queue_surface: bool=True)`
    - `pop_surface(self)`
    - `pop_surface_seed(self)`
    - `latest_report(self)`
    - `_run(self)`
    - `_load_interval(self)`
    - `_load_enabled(self)`

## `cortex/ti.py`
- LOC: 964
- Classes:
  - `TiCandidateAssessment` (decorator=dataclass(slots=True))
  - `TiGovernor`
    - `__init__(self, logger=None)`
    - `evaluate_autonomous(self, *, snapshot: TelemetrySnapshot, ni_report: GoalDriftReport | None, ni_state_label: str='', ni_state_streak: int=0, idle_cycles: int, last_text: str)`
    - `evaluate_chat(self, *, snapshot: TelemetrySnapshot, ni_report: GoalDriftReport | None, user_text: str)`
    - `enforce_decision(self, decision: Decision, report: TiPolicyReport, *, user_hint: str='', vision_grounded: bool=False)`
    - `_detect_risks(self, text: str)`
    - `_log_guard_report(self, report: dict[str, object], *, decision: Decision)`
    - `_apply_safety_only_editor(self, text: str, *, report: TiPolicyReport)`
    - `_strip_dangling_payload_punctuation(self, text: str)`
    - `_apply_report_debug_guard(self, text: str)`
    - `_strip_report_debug_prefixes(self, text: str)`
    - `_is_report_debug_sentence(self, sentence: str)`
    - `_count_report_debug_markers(self, text: str)`
    - `_apply_resource_guard_length_guard(self, text: str)`
    - `_build_prompt_context(self, *, mode: str, focus_label: str, reason: str, hard_rules: tuple[str, ...], animation_hint: str, evidence: list[str], recent_text: str='')`
    - `_self_doubt_bias_context(self, *, recent_text: str='')`
    - `_summarize_hard_rules(self, hard_rules: tuple[str, ...])`
    - `_direction_to_center(self, inferred_pos_x: float)`
    - `_looks_like_code_request(self, lowered: str)`
    - `_looks_like_emotional_request(self, lowered: str)`
    - `_merge_debug_trace(self, decision: Decision, extra: str)`
    - `_looks_like_structured_payload_text(self, text: str)`
    - `_apply_ti_guard(self, text: str, user_hint: str='', *, vision_grounded: bool=False)`
    - `_assess_candidate(self, text: str, *, report: TiPolicyReport)`
    - `_normalize_editor_text(self, text: str)`
    - `_normalize_plain_text(self, text: str)`
    - `_has_focus_guard_overreach(self, text: str)`
    - `_has_resource_pressure_anchor(self, text: str)`
    - `_has_emotional_residue_anchor(self, text: str)`
    - `_has_context_anchor(self, text: str)`
    - `_has_abstract_anchor(self, text: str)`
    - `_has_unanchored_abstraction(self, text: str)`
    - `_has_abstract_image(self, text: str)`
    - `_has_rhythm_survival(self, text: str)`
    - `_has_exposure_trace(self, text: str)`
    - `_felt_tension(self, text: str, *, report: TiPolicyReport)`
    - `_implication_pressure(self, text: str)`
    - `_felt_continuity(self, text: str, *, report: TiPolicyReport)`
    - `_post_exposure_recoil_pressure(self, text: str)`
    - `_split_sentences(self, text: str)`
    - `_hard_text_limit(self, report: TiPolicyReport)`
    - `_style_char_limit(self, report: TiPolicyReport)`
    - `_truncate_by_clause(self, text: str, max_chars: int)`
    - `_finalize_editor_text(self, text: str)`
    - `_has_capability_violation(self, text: str)`
    - `_has_perception_violation(self, text: str)`
    - `_count_report_markers(self, text: str)`
    - `_build_soft_redirect(self, *, user_hint: str='')`

## `cortex/tom/__init__.py`
- LOC: 43
- Docstring: cortex.tom — Phase 2 Theory of Mind package.

## `cortex/tom/contracts.py`
- LOC: 67
- Docstring: contracts.py — MentalStateInference, ToM dataclasses, lỗi contract ToM.
- Classes:
  - `ToMOrderingViolation` (base=RuntimeError) — R7.2, R13.3 — ToM chạy trước khi Meaning/Pragmatic sinh output cho frame.
    - `__init__(self, missing_stage: str, frame_id: str | None)`
  - `MentalStateInference` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
  - `ToMHistory` (decorator=dataclass(slots=True))

## `cortex/tom/counterfactual_corrector.py`
- LOC: 136
- Docstring: counterfactual_corrector.py — CounterfactualCorrector (R7.4).
- Classes:
  - `Counterfactual` (decorator=dataclass(slots=True)) — Một diễn giải phản thực (alternative) cho một mental-state inference.
    - `__post_init__(self)`
  - `CounterfactualCorrector` — Hạ confidence của inference khi có counterfactual đủ mạnh (R7.4).
    - `correct(self, inference: MentalStateInference, counterfactuals: list[Counterfactual], *, threshold: float=DEFAULT_THRESHOLD)` — Trả về inference đã hiệu chỉnh theo R7.4.
    - `correct_all(self, inferences: list[MentalStateInference], counterfactuals_by_inference_id: dict[str, list[Counterfactual]], *, threshold: float=DEFAULT_THRESHOLD)` — Batch helper: áp ``correct`` cho từng inference theo id của nó.

## `cortex/tom/mental_state_ranker.py`
- LOC: 42
- Docstring: mental_state_ranker.py — MentalStateRanker.
- Classes:
  - `MentalStateRanker` — Xếp hạng mental-state inference theo plausibility giảm dần (R7.3).
    - `rank(self, inferences: list[MentalStateInference])` — Trả danh sách mới đã sắp xếp giảm dần theo plausibility.

## `cortex/tom/theory_of_mind.py`
- LOC: 360
- Docstring: theory_of_mind.py — ``TheoryOfMindCore`` (stage 6 của Phase 2).
- Classes:
  - `TheoryOfMindCore` — Suy ``MentalStateInference`` từ meaning + intents, có guard thứ tự (R7).
    - `__init__(self, *, ranker: Optional[MentalStateRanker]=None, corrector: Optional[CounterfactualCorrector]=None, config: Optional[Phase2Config]=None)`
    - `infer(self, *, meaning: list[MeaningHypothesis], intents: list[PragmaticIntent], ledger: StageLedger, frame_id: str, history: ToMHistory, boldness: float=0.0)` — Suy tập ``MentalStateInference`` từ ``meaning``/``intents``.
    - `_first_missing_stage(ledger: StageLedger, frame_id: str)` — Trả tên stage tiền đề ĐẦU TIÊN còn thiếu cho ``frame_id`` (hoặc None).
    - `_build_inference(self, frame_id: str, intent: PragmaticIntent, meaning_ids: set[str])` — Dựng một ``MentalStateInference`` từ một ``PragmaticIntent``.
    - `_map_mental_state(intent_category: str)` — Ánh xạ xác định ``Taxonomy.INTENT`` id → ``Taxonomy.MENTAL_STATE`` id.
    - `_apply_counterfactuals(self, inferences: Sequence[MentalStateInference], intents: Sequence[PragmaticIntent], *, boldness: float=0.0)` — Hạ confidence từng inference theo counterfactual từ intent đối thủ.
    - `_build_debug(inferences: Sequence[MentalStateInference], notes: list[str])` — Gom ``StageDebug`` với chỉ số tổng hợp của tập inference.

## `cortex/tom/tom_debug.py`
- LOC: 79
- Docstring: tom_debug.py — ``ToMDebug`` (bản ghi debug Theory of Mind, R12.3).
- Functions:
  - `_render_metric(value: float | None)` — Render một chỉ số: ``f"{value:.3f}"`` khi có giá trị, else ``"unavailable"`` (R12.5).
- Classes:
  - `ToMDebug` — Render danh sách ``MentalStateInference`` thành chuỗi người-đọc-được (R12.3).
    - `render(self, inferences: list[MentalStateInference])` — Trả bản ghi nhiều dòng cho từng mental-state inference (R12.3).
    - `_render_inference(inf: MentalStateInference)` — Render một inference + các tham chiếu MeaningHypothesis hỗ trợ.

## `cortex/tom/tom_history_adapter.py`
- LOC: 118
- Docstring: tom_history_adapter.py — ToMHistoryAdapter (history từ WorkspaceFrame only).
- Classes:
  - `ToMHistoryAdapter` — Adapter cấp ``ToMHistory`` từ ``WorkspaceFrame`` qua ``FrameReadView``.
    - `__init__(self, *, module: Optional[str]=None, history_field: Optional[str]=None)`
    - `load(self, view: Optional[FrameReadView])` — Trả ``ToMHistory`` lấy từ ``WorkspaceFrame`` qua ``view``.
    - `_normalize(raw: object)` — Chuẩn hoá giá trị đọc được thành ``list[str]`` cho ``ToMHistory.items``.

## `cortex/tom_advisor.py`
- LOC: 201
- Docstring: cortex/tom_advisor.py
- Functions:
  - `tom_advisor_enabled()` — Cờ bật ToM advisor. MẶC ĐỊNH TẮT.
  - `real_embeddings_enabled()` — Cờ dùng MiniLM thật cho meaning pipeline. MẶC ĐỊNH TẮT (fallback hash).
  - `build_real_semantic_engine()` — (b) — dựng SemanticHypothesisEngine nền MiniLM qua EmbeddingIndex dùng chung.
  - `_frame_with_phase2_contract(ws_frame: Any)` — Bản sao của WorkspaceFrame với downstream_contract ĐÚNG cho Phase 2.
  - `_extract_workspace(obj: Any)` — Lấy WorkspaceFrame từ một WorkspaceFrame trực tiếp hoặc một CognitiveFrame.
  - `_render_advisory(result: Any)` — Rút MentalStateInference đã surfaced thành một dòng advisory ngắn. "" nếu không có.
  - `advise_from_workspace(ws_frame: Any)` — Chạy Phase 2 trên một WorkspaceFrame (contract đã sửa) → dòng advisory.
  - `advise(frame_or_ws: Any)` — Entry cho runtime: gate cờ, lấy WorkspaceFrame, trả advisory. "" khi tắt/lỗi.

## `cortex/tune_ni_focus.py`
- LOC: 305
- Functions:
  - `_load_samples(path: str)`
  - `_fit_bias_scale(xs: Iterable[float], targets: Iterable[float])`
  - `tune_focus_bias(samples: list[DriftSample], min_samples: int=20)`
  - `tune_channel_weights(samples: list[DriftSample])`
  - `_load_existing_config(path: str)`
  - `_save_json(path: str, data: Any)`
  - `main(argv: list[str] | None=None)`
- Classes:
  - `DriftSample` (decorator=dataclass)

## `cortex/turn_semantics.py`
- LOC: 582
- Classes:
  - `TurnSemanticsReport` (decorator=dataclass(frozen=True, slots=True)) — Báo cáo nghĩa của user turn hiện tại.
    - `should_guard_repeat(self)`
    - `should_bypass_repeat_guard(self)`
  - `TurnSemanticsEngine` — Arbitration nhẹ cho meaning của một user turn.
    - `analyze_repeat(self, *, user_text: str, repeat_count: int, last_user_text: str='', last_assistant_text: str='', affect_signal: Any=None, conversation_report: Any=None, relationship_report: Any=None, grounding_report: Any=None)`
    - `build_repeat_guard_text(self, report: TurnSemanticsReport)` — Text guard chỉ dùng khi arbitration thật sự coi là repeat rỗng.
    - `_question_pressure(self, raw: str, normalized: str, affect_signal: Any)`
    - `_correction_pressure(self, conversation_report: Any, affect_signal: Any, normalized: str)`
    - `_relational_pressure(self, affect_signal: Any, relationship_report: Any)`
    - `_identity_pressure(self, affect_signal: Any, relationship_report: Any)`
    - `_fact_disclosure_pressure(self, *, user_text: str, normalized: str, grounding_report: Any=None)` — Áp lực self-disclosure/profile update cho repeat guard.
    - `_live_evidence_pressure(self, grounding_report: Any)`
    - `_prior_failure_pressure(self, last_assistant_text: str, conversation_report: Any)`
    - `_new_information_pressure(self, *, live_evidence_pressure: float, correction_pressure: float, prior_failure_pressure: float, question_pressure: float, fact_disclosure_pressure: float=0.0)`
    - `_spam_pressure(self, *, repeat_count: int, literal_repeat_score: float, semantic_similarity: float, question_pressure: float, correction_pressure: float, relational_pressure: float, identity_pressure: float, live_evidence_pressure: float, prior_failure_pressure: float, fact_disclosure_pressure: float=0.0)`
    - `_with_prompt_context(self, report: TurnSemanticsReport)`
    - `normalize(self, text: str)`
    - `_looks_like_question(self, normalized: str)`
    - `_contains_soft_correction_shape(self, normalized: str)`
    - `_jaccard_similarity(self, left: str, right: str)`
    - `_safe_float(self, value: Any, default: float=0.0)`
    - `_clamp01(self, value: float)`

## `cortex/tutor/__init__.py`
- LOC: 51
- Docstring: cortex.tutor — Curiosity Tutor (Gia sư Tò mò).

## `cortex/tutor/claim_digest.py`
- LOC: 198
- Docstring: cortex/tutor/claim_digest.py
- Functions:
  - `_accepts_confidence(fn: Any)` — True nếu ingest_fn nhận tham số confidence (hoặc có **kwargs).
  - `_is_too_uncertain(text: str)`
  - `_is_hedged(text: str)`
  - `_heuristic_split(text: str)` — Tách câu trả lời thành các câu ngắn khi không có distill_fn.
- Classes:
  - `ClaimDigest` — Chưng cất câu trả lời gia sư thành fact atomic và ghi vào trí nhớ ngữ nghĩa.
    - `__init__(self, config: Optional[TutorConfig]=None, *, ingest_fn: Optional[IngestFn]=None, distill_fn: Optional[DistillFn]=None)`
    - `digest(self, episode: TutorEpisode)` — Trả tổng số Knowledge_Claim đã commit. 0 nếu rỗng/không chắc/không commit được.
    - `_distill(self, text: str)`
    - `_confidence(self, fact: str, citations: tuple)`
    - `_commit(self, text: str, *, gap_id: str, citations: tuple, confidence: float)`

## `cortex/tutor/config.py`
- LOC: 281
- Docstring: cortex/tutor/config.py
- Functions:
  - `scrub_identity(text: Any)` — Bỏ email và cặp cookie/token=... khỏi văn bản. An toàn với None.
  - `_env_bool(name: str, default: bool)`
  - `_env_float(name: str, default: float)`
  - `_env_int(name: str, default: int)`
  - `_env_str(name: str, default: str)`
- Classes:
  - `TutorConfig` (decorator=dataclass(slots=True)) — Cấu hình Curiosity Tutor. `enabled` (Master_Switch) mặc định TẮT.
    - `normalized(self)` — Clamp giá trị về miền hợp lệ. Cờ không hợp lệ ⇒ coi như TẮT (xử lý ở from_env).
    - `from_env(cls, logger: 'Optional[TutorLogger]'=None)` — Đọc ERIS_TUTOR_* từ môi trường.
  - `TutorRiskGuard` — Tạm ngưng episode khi lỗi liên tiếp hoặc gặp captcha/hết phiên.
    - `__init__(self, config: TutorConfig)`
    - `is_paused(self, now: float)`
    - `paused_until(self)`
    - `note_success(self, now: float)`
    - `note_failure(self, now: float, reason: Optional[str]=None)`
    - `note_captcha(self, now: float)`
    - `consecutive_failures(self)`
  - `TutorLogger` — Observability cho Tutor. KHÔNG bao giờ log định danh (email/cookie/HTML login).
    - `__init__(self, sink: Optional[Any]=None, *, max_records: int=256)`
    - `_emit(self, payload: dict[str, Any])`
    - `warn(self, message: str)`
    - `log_stage(self, episode_id: str, stage: str)`
    - `log_episode(self, episode_dict: dict[str, Any])`

## `cortex/tutor/contracts.py`
- LOC: 198
- Docstring: cortex/tutor/contracts.py
- Functions:
  - `_short_id(prefix: str, seed: str)`
- Classes:
  - `KnowledgeGap` (decorator=dataclass(slots=True)) — Một lỗ hiểu biết cụ thể, dẫn xuất từ vi phạm kỳ vọng hoặc observer 'unknown'.
    - `__post_init__(self)`
    - `to_dict(self)`
  - `TutorQuestion` (decorator=dataclass(slots=True)) — Câu hỏi ERIS hình thành để hỏi gia sư. 1..400 ký tự khi hợp lệ.
    - `__post_init__(self)`
    - `is_valid(self)`
  - `TutorAnswer` (decorator=dataclass(slots=True)) — Câu trả lời đọc được từ gia sư.
    - `__post_init__(self)`
  - `TutorEpisode` (decorator=dataclass(slots=True)) — Một lượt hoàn chỉnh từ chọn gap đến commit claim (hoặc kết thúc).
    - `__post_init__(self)`
    - `to_dict(self)`

## `cortex/tutor/curiosity_gate.py`
- LOC: 101
- Docstring: cortex/tutor/curiosity_gate.py
- Functions:
  - `_clamp01(v: float)`
- Classes:
  - `CuriosityGate` — Cổng tò mò. Giữ lịch sử episode để rate-limit và trần/giờ.
    - `__init__(self, config: Optional[TutorConfig]=None)`
    - `priority(self, gap: KnowledgeGap, *, drive_level: float=1.0)`
    - `can_start(self, now: float)`
    - `select(self, gaps: list[KnowledgeGap], *, idle: bool, now: float, drive_level: float=1.0)` — Chọn gap đáng hỏi nhất, hoặc None.
    - `select_forced(self, gaps: list[KnowledgeGap])` — Chọn gap 'force' (lệnh trực tiếp / 'không biết') — bỏ qua idle + rate-limit.
    - `note_started(self, now: float)`
    - `_prune_hour(self, now: float)`

## `cortex/tutor/curiosity_router.py`
- LOC: 114
- Docstring: cortex/tutor/curiosity_router.py
- Classes:
  - `CuriosityRouter`
    - `__init__(self, *, generate_fn: Optional[GenerateFn]=None, already_known_fn: Optional[KnownFn]=None)`
    - `route(self, gap: KnowledgeGap)`
    - `_is_known(self, topic: str)`
    - `_llm_route(self, gap: KnowledgeGap)`

## `cortex/tutor/gap_collector.py`
- LOC: 243
- Docstring: cortex/tutor/gap_collector.py
- Functions:
  - `clamp01_local(value: Any)`
- Classes:
  - `GapCollector` — Thu thập, dedupe và giới hạn hàng đợi Knowledge_Gap.
    - `__init__(self, config: Optional[TutorConfig]=None, *, embed_fn: Optional[EmbedFn]=None)`
    - `collect_from_violation(self, violation: Any, *, stake_relevance: float, now: float)` — Từ một ExpectationViolation của SituationModel.
    - `collect_from_uncertainty(self, topic: str, *, context: str='', stake: float=0.6, now: float=0.0, kind_hint: str='durable', force: bool=True)` — Lỗ do cognition báo 'không chắc' hoặc lệnh tra cứu trực tiếp từ user.
    - `collect_from_observer(self, frame: Any, *, now: float, screen_context: str='')` — Từ một ObserverFrame có focus/activity 'unknown' và ambiguity cao.
    - `push(self, gap: Optional[KnowledgeGap])` — Thêm gap với dedupe ngữ nghĩa + giới hạn queue. Trả True nếu thêm mới.
    - `drain_candidates(self)` — Các gap chưa giải quyết, cho gate đọc.
    - `resolve(self, gap: KnowledgeGap)`
    - `serialize(self)`
    - `size(self)`
    - `_embed(self, text: str)`
    - `_find_duplicate(self, gap: KnowledgeGap)`
    - `_similar(self, a: KnowledgeGap, b: KnowledgeGap)`
    - `_enforce_cap(self)`

## `cortex/tutor/knowledge_classifier.py`
- LOC: 68
- Docstring: cortex/tutor/knowledge_classifier.py
- Classes:
  - `KnowledgeClassifier`
    - `__init__(self, *, generate_fn: Optional[GenerateFn]=None)`
    - `classify(self, question: str, answer: str, *, gap_source: str='', kind_hint: str='')`

## `cortex/tutor/knowledge_provider.py`
- LOC: 87
- Docstring: cortex/tutor/knowledge_provider.py
- Classes:
  - `KnowledgeProvider` — Làm giàu dự đoán bằng tri thức gia sư đã học.
    - `__init__(self, recall_fn: Optional[Callable[[str], list]]=None, *, only_tutor: bool=True)`
    - `enrich(self, *, content_thread: str='', percept_text: str='')`
    - `learned_claims(self, query: str, *, limit: int=3)` — Trả các claim đã học (tag 'tutor') liên quan query, dạng text thô.

## `cortex/tutor/question_formulator.py`
- LOC: 180
- Docstring: cortex/tutor/question_formulator.py
- Classes:
  - `QuestionFormulator` — Hình thành câu hỏi + tóm tắt điều học. Local LLM với heuristic fallback.
    - `__init__(self, config: Optional[TutorConfig]=None, *, generate_fn: Optional[GenerateFn]=None)`
    - `formulate(self, gap: KnowledgeGap)`
    - `_heuristic_question(self, gap: KnowledgeGap)`
    - `summarize_learning(self, episode: TutorEpisode)`
    - `craft_user_question(self, gap: KnowledgeGap)` — Câu hỏi ngắn, thân mật ERIS hỏi LẠI Ngài để hiểu rõ (không lén tra).
    - `_heuristic_highlight(self, episode: TutorEpisode)`
    - `craft_remark(self, episode: TutorEpisode, *, kind: str)` — Câu nói ngắn cho ngữ cảnh (context) hoặc khịa (banter) — KHÔNG nguyên văn answer.
    - `_try_llm(self, prompt: str)`
    - `_sanitize(text: str)`
    - `_too_similar_to_answer(highlight: str, answer: str)`

## `cortex/tutor/share_impulse.py`
- LOC: 141
- Docstring: cortex/tutor/share_impulse.py
- Classes:
  - `LearningShareImpulse` — Tạo + đẩy Share_Impulse có tiết chế.
    - `__init__(self, config: Optional[TutorConfig]=None, *, formulator: Any=None, thought_sink: Any=None, novelty_fn: Optional[NoveltyFn]=None, logger: Any=None)`
    - `maybe_emit(self, episode: TutorEpisode, *, now: float)` — Trả True nếu đã đẩy một Share_Impulse.
    - `push_remark(self, text: str, *, now: float, priority: float=0.6)` — Đẩy một câu ngắn (context/banter) vào thought stream. Không lưu trí nhớ.
    - `_novelty(self, highlight: str)`
    - `_push(self, highlight: str, priority: float)`
    - `_log(self, episode: TutorEpisode, highlight: str, novelty: float)`

## `cortex/user_context_stream.py`
- LOC: 268
- Docstring: src/cortex/user_context_stream.py
- Functions:
  - `_safe_float(value: Any, default: float=0.0)`
  - `_ema(previous: float, new: float, alpha: float=0.35)`
- Classes:
  - `RollingUserContext` (decorator=dataclass(slots=True)) — Bản tóm tắt ngoại sinh đang lăn theo thời gian.
    - `to_dict(self)`
    - `prompt_hint(self)` — Render cực ngắn nếu cần đưa vào debug/prompt dev mode.
  - `UserContextStream` — Bộ sở hữu RollingUserContext.
    - `__init__(self, *, alpha: float=0.36)`
    - `update(self, *, signal_snapshot: SignalSnapshot | Mapping[str, Any] | None=None, signal_diff: SignalDiff | None=None, observer_frame: ObserverFrame | None=None, user_text: str='', channel: str='autonomous', now: float | None=None)` — Cập nhật context từ signal mới.
    - `_busy_score(self, *, snapshot: SignalSnapshot, focus_kind: str, activity_intent: str, resource_pressure: float)`
    - `_interrupt_cost(self, *, snapshot: SignalSnapshot, focus_kind: str, busy_score: float, direct_user_pull: float)`

## `cortex/vision_semantic_compressor.py`
- LOC: 1192
- Docstring: VisionSemanticCompressor cho ERIS.
- Functions:
  - `_safe_float(value: Any, default: float=0.0)`
  - `_parse_keep_alive(value: str)`
- Classes:
  - `RemoteStructureClient` — Adapter: bọc một remote chat client (có ``create_chat_completion``) để lộ
    - `__init__(self, client: Any, *, max_tokens: int=512, logger: Any | None=None)`
    - `_extract_text(response: Any)`
    - `_parse_json_object(text: str)`
    - `chat_json(self, model: str, messages: list[dict], *, schema: dict | None=None, keep_alive: Any | None=None, temperature: float=0.0, **_: Any)`
  - `RemoteCaptionClient` — Adapter: bọc client OpenAI-compatible remote (vd shopaikey grok-3-image) để
    - `__init__(self, client: Any, *, max_tokens: int=320, logger: Any | None=None)`
    - `_maybe_downscale(self, data_uri: str)`
    - `_to_data_uri(image: str)`
    - `_extract_text(response: Any)`
    - `caption_image(self, image: str, *, prompt: str='Describe what is visible on this screen in concrete detail.', temperature: float=0.2, max_tokens: int | None=None, keep_alive: Any | None=None)`
  - `VisionCompressorConfig` (decorator=dataclass(slots=True)) — Cấu hình cho VisionSemanticCompressor.
  - `VisionSemanticCompressor` — Nén ảnh màn hình thành SemanticSceneNote.
    - `__init__(self, config: VisionCompressorConfig | None=None, ollama_client: Any | None=None, logger: Any | None=None, structure_client: Any | None=None, caption_client: Any | None=None)`
    - `should_compress(self, *, observer_frame: ObserverFrame | None=None, signal_diff: SignalDiff | None=None)` — Quyết định có nên gọi vision model không.
    - `compress(self, *, image_data_uri: str='', image_base64: str='', image_path: str='', ocr_text: str='', observer_frame: ObserverFrame | None=None, signal_snapshot: SignalSnapshot | None=None, extra_context: str='')` — Gọi vision model và trả SemanticSceneNote.
    - `_compress_single_shot(self, *, image: str, ocr_text: str, observer_frame: ObserverFrame | None, signal_snapshot: SignalSnapshot | None, extra_context: str)` — Đường cũ: gọi vision model một phát với schema (cho client không có
    - `compress_from_ocr_only(self, *, ocr_text: str='', observer_frame: ObserverFrame | None=None, signal_snapshot: SignalSnapshot | None=None)` — Public fallback khi runtime chưa có ảnh nhưng có OCR.
    - `_system_prompt()`
    - `_structure_model(self)` — Model cho tầng cấu trúc-hoá text. Với LocalLlamaEngine, tham số này bị
    - `_caption_prompt()`
    - `_structure_system_prompt()`
    - `_structure_user_prompt(self, *, caption: str, ocr_text: str, observer_frame: ObserverFrame | None, signal_snapshot: SignalSnapshot | None, extra_context: str)`
    - `_previous_scene_payload(self)`
    - `_user_prompt(self, *, ocr_text: str, observer_frame: ObserverFrame | None, signal_snapshot: SignalSnapshot | None, extra_context: str)`
    - `_json_schema()`
    - `_note_from_mapping(self, data: Mapping[str, Any], *, observer_frame: ObserverFrame | None, signal_snapshot: SignalSnapshot | None, caption: str='', raw_debug: Mapping[str, Any] | None=None, source_override: str='')`
    - `_fallback_ocr_note(self, *, ocr_text: str, observer_frame: ObserverFrame | None, signal_snapshot: SignalSnapshot | None, reason: str, caption: str='')`
    - `_clean_meaning(self, value: Any, limit: int)` — Compact + loại echo cho các trường nghĩa (content/affect/relation/delta).
    - `_assign_scene_continuity(self, note: SemanticSceneNote)` — Gán scene_id + prev_scene_id để 'thay đổi' có chỗ bám, cập nhật scene cuối.
    - `_looks_like_echo(text: str)` — Bắt trường hợp model nhỏ nhả lại mô tả field/instruction thay vì nội dung.
    - `_extract_important_lines(self, text: str)`
    - `_infer_intent_from_text(self, text: str, focus_kind: str)`
    - `_infer_family_from_text(self, text: str, *, possible_error: float, focus_kind: str)`
    - `_fallback_visible_context(signal_snapshot: SignalSnapshot | None, focus_kind: str, intent: str)`
    - `_observer_payload(observer_frame: ObserverFrame | None)`
    - `_signal_payload(signal_snapshot: SignalSnapshot | None)`
    - `_resolve_image_base64(self, *, image_data_uri: str, image_base64: str, image_path: str)`
    - `_strip_data_uri(value: str)`
    - `_coerce_text_list(value: Any, *, limit: int)`
    - `_clean_family(value: Any)`
    - `_source_label(self)` — Trả source label từ model name, dùng cho SemanticSceneNote.source.
    - `_make_default_client()`
    - `_log_warning(self, msg: str, *args: Any)`

## `cortex/working_memory.py`
- LOC: 1929
- Functions:
  - `clamp01(value: Any, default: float=0.0)` — Ép một giá trị về khoảng 0..1.
  - `now_ts()`
  - `stable_id(prefix: str, text: str)`
  - `safe_get(obj: Any, name: str, default: Any=None)` — Đọc field từ dataclass/object/dict một cách khoan dung.
  - `safe_iter(value: Any)` — Biến tuple/list/set/None/object đơn thành list.
  - `normalize_text(text: Any)` — Chuẩn hóa text nhẹ để so trùng / phát hiện echo.
  - `estimate_tokens(text: Any)` — Ước lượng token thô.
  - `truncate_text(text: Any, max_chars: int)`
  - `unique_preserve_order(items: Iterable[Any], limit: Optional[int]=None)`
  - `select_working_memory(frame: Any, *, config: Optional[WorkingMemoryConfig]=None, extra_candidates: Optional[Iterable[WorkingMemoryCandidate | dict[str, Any]]]=None)` — Hàm tiện dụng để không cần tự khởi tạo engine trong code thử nghiệm.
- Classes:
  - `WorkingMemorySlot` (decorator=dataclass(slots=True)) — Một slot đang hoạt động trong cổ chai nhận thức.
    - `__post_init__(self)`
    - `is_memory(self)`
    - `is_symbolic_heavy(self)`
    - `expired(self, timestamp: Optional[float]=None)`
    - `to_prompt_line(self)` — Dòng ngắn để prompt builder có thể dùng.
    - `to_dict(self)`
  - `SuppressedMemoryItem` (decorator=dataclass(slots=True)) — Một candidate bị loại khỏi working memory.
    - `to_debug_line(self)`
    - `to_dict(self)`
  - `WorkingMemoryFrame` (decorator=dataclass(slots=True)) — Kết quả chính của module Working Memory.
    - `__post_init__(self)`
    - `get_slot(self, kind_or_name: str)`
    - `evidence_ids(self)`
    - `render_prompt_context(self, *, max_lines: int=7)` — Render prompt context cực gọn.
    - `prompt_context(self)`
    - `to_dict(self)`
  - `WorkingMemoryCandidate` (decorator=dataclass(slots=True)) — Candidate nội bộ trước khi được chọn thành slot.
    - `__post_init__(self)`
    - `id(self)`
    - `normalized_content(self)`
    - `to_slot(self, *, name: Optional[str]=None, max_chars: int=700)`
  - `WorkingMemoryConfig` (decorator=dataclass(slots=True)) — Cấu hình cổ chai.
    - `slot_budget_for(self, budget_mode: Any)`
    - `token_budget_for(self, budget_mode: Any)`
  - `WorkingMemoryEngine` — Bộ chọn WorkingMemoryFrame.
    - `__init__(self, config: Optional[WorkingMemoryConfig]=None)`
    - `select(self, frame: Any, *, extra_candidates: Optional[Iterable[WorkingMemoryCandidate | dict[str, Any]]]=None, now: Optional[float]=None)`
    - `_collect_candidates(self, frame: Any, *, timestamp: float)`
    - `_candidates_from_evidence(self, frame: Any, *, timestamp: float)`
    - `_candidates_from_attention_candidates(self, frame: Any, *, timestamp: float)` — Đọc Runtime AttentionCandidate cũ từ frame.attention_candidates.
    - `_candidates_from_percepts(self, frame: Any, *, timestamp: float)` — Fallback đọc percepts khi frame.evidence rỗng.
    - `_attention_kind(self, *, label: str, source: str, content: str)`
    - `_candidates_from_salience(self, frame: Any, *, timestamp: float)`
    - `_candidates_from_memory_packet(self, frame: Any, *, timestamp: float)`
    - `_candidates_from_goal(self, frame: Any, *, timestamp: float)`
    - `_candidates_from_relation(self, frame: Any, *, timestamp: float)`
    - `_candidates_from_affect_homeostasis(self, frame: Any, *, timestamp: float)`
    - `_candidates_from_constraints(self, frame: Any, *, timestamp: float)`
    - `_candidates_from_temporal_spatial(self, frame: Any, *, timestamp: float)`
    - `_score_and_filter(self, candidates: list[WorkingMemoryCandidate], *, frame: Any, timestamp: float)`
    - `_candidate_score(self, cand: WorkingMemoryCandidate, *, technical_context: bool)` — Tính điểm candidate.
    - `_early_suppression_reason(self, cand: WorkingMemoryCandidate, *, timestamp: float, technical_context: bool)`
    - `_select_slots(self, candidates: list[WorkingMemoryCandidate], *, slot_budget: int, token_budget: int, timestamp: float)`
    - `_evidence_kind(self, *, source: str, claim: str, tags: list[str], raw_or_inferred: str)`
    - `_claim_relevance(self, claim: str, tags: list[str])`
    - `_risk_score(self, claim: str, tags: list[str])`
    - `_affective_score(self, claim: str, tags: list[str])`
    - `_goal_score(self, claim: str, tags: list[str])`
    - `_recency_score(self, item_timestamp: Any, frame_timestamp: float)`
    - `_symbolic_drift_risk(self, cand: WorkingMemoryCandidate, *, technical_context: bool)`
    - `_overassociation_risk(self, cand: WorkingMemoryCandidate, *, frame: Any)`
    - `_find_duplicate(self, text: str, seen_texts: list[str])`
    - `_jaccard_similarity(self, a: str, b: str)`
    - `_suppressed(self, cand: WorkingMemoryCandidate, reason: SuppressionReason)`
    - `_choose_dominant_thread(self, slots: list[WorkingMemorySlot], frame: Any)`
    - `_context_pressure(self, *, used_tokens: int, token_budget: int, active_slots: list[WorkingMemorySlot], suppressed: list[SuppressedMemoryItem])`
    - `_anti_drift_notes(self, slots: list[WorkingMemorySlot], suppressed: list[SuppressedMemoryItem])`
    - `_warnings(self, slots: list[WorkingMemorySlot], context_pressure: float, suppressed: list[SuppressedMemoryItem])`
    - `_coerce_candidate(self, item: WorkingMemoryCandidate | dict[str, Any], *, timestamp: float)`
    - `_attach_to_frame(self, frame: Any, wm_frame: WorkingMemoryFrame)`
    - `_report_confidence(self, wm_frame: WorkingMemoryFrame)`
    - `_memory_item_text(self, item: Any)`
    - `_looks_technical(self, text: str)`
    - `_frame_is_technical(self, frame: Any)`
    - `_decay_for_kind(self, kind: WorkingMemorySlotKind)`

## `domain/__init__.py`
- LOC: 6

## `domain/decision.py`
- LOC: 111
- Classes:
  - `Decision` (decorator=dataclass(slots=True))
    - `resolve_motion_intent(self)`
    - `resolve_motion_target_x(self)`
    - `resolve_motion_facing(self)`
    - `_payload_text(self)`
    - `to_payload(self)`

## `eris_secrets.py`
- LOC: 284
- Functions:
  - `_resolve_secrets_path()`
  - `_resolve_env_file_path()`
  - `_parse_env_file(text: str)`
  - `load_env_file(*, force: bool=False)` — Nạp ``.env`` vào ``os.environ`` với precedence: OS-env > .env > secrets.
  - `config_source(name: str)` — Nguồn thắng của một biến config: ".env" | "secrets" | "os-env" | "default".
  - `log_config_sources(*names: str)` — Log nguồn thắng của các biến quan trọng để debug R3/E7.
  - `_load_secrets()`
  - `_lookup(payload: dict[str, Any], name: str)`
  - `_lookup_path(payload: dict[str, Any], path: str, *, default: Any=None)`
  - `_provider_slot_payload(payload: dict[str, Any], provider: str, slot: str)`
  - `get_secret(*names: str, default: str='')`
  - `get_config(path: str, default: Any=None)` — Đọc config lồng nhau từ env hoặc secrets.json.
  - `get_provider_profile(provider: str, *, slot: str='default', default: dict[str, Any] | None=None)` — Lấy cấu hình provider theo slot riêng.
  - `get_agent_profile(agent_name: str, *, default_provider: str='', default_slot: str='default', default: dict[str, Any] | None=None)` — Resolve provider profile cho một job/agent cụ thể.
  - `apply_secrets_to_environ()`

## `failure_meta.py`
- LOC: 83
- Functions:
  - `build_failure_meta(*, kind: str='unknown', stage: str='', origin: str='', public_surface: str='service_fallback', recoverable: bool=False, transport_truncated: bool=False)`
  - `normalize_failure_meta(value: Any)`
  - `mark_transport_truncated(value: Any)`
  - `is_technical_failure_meta(value: Any)`

## `guard_config.py`
- LOC: 48
- Functions:
  - `guards_warn_only()` — Công tắc thống nhất: mọi guard chỉ CẢNH BÁO, không chặn.
  - `get_guard_mode(name: str | None=None)` — Trả chế độ guard hiện hành.

## `llm/__init__.py`
- LOC: 29

## `llm/client.py`
- LOC: 604
- Functions:
  - `_http_error_with_body(response: requests.Response)`
  - `_is_empty_output_error(exc: requests.HTTPError)` — Detect lỗi Groq 'model output must contain either output text or tool calls'.
  - `_chat_payload_variants(payload: dict)`
  - `_model_supports_reasoning_toggle(model_name: str)` — Các model có chế độ "thinking" mà Groq cho tắt qua reasoning_effort.
  - `_resolve_reasoning_effort()` — Mức reasoning cho model có thinking. Mặc định "medium" để bật suy nghĩ.
- Classes:
  - `LlamaServerClient`
    - `__init__(self, base_url: str, timeout: int=180)`
    - `_detect_model_name(self)`
    - `create_chat_completion(self, *, messages, temperature, frequency_penalty, presence_penalty, max_tokens, response_format=None, grammar=None, timeout=None, reasoning_effort=None)`
  - `OpenAICompatibleClient`
    - `__init__(self, base_url: str, api_key: str, model_name: str, timeout: int=180, key_pool=None)`
    - `_normalize_api_key(self, raw_value: str)`
    - `create_chat_completion(self, *, messages, temperature, frequency_penalty, presence_penalty, max_tokens, response_format=None, grammar=None, timeout=None, reasoning_effort=None)`
  - `ChainedFallbackClient` — Gộp nhiều client dự phòng thành MỘT, thử lần lượt cho tới khi có cái chạy.
    - `__init__(self, clients, logger=None)`
    - `create_chat_completion(self, **kwargs)`
  - `GeminiClient`
    - `__init__(self, base_url: str, api_key: str, model_name: str, timeout: int=180, key_pool=None)`
    - `_normalize_api_key(self, raw_value: str)`
    - `_text_part(self, text: str)`
    - `_image_part_from_url(self, url: str)`
    - `_parts_from_content(self, content)`
    - `_convert_messages(self, messages: list[dict])`
    - `_is_gemma(self)` — Gemma trên Gemini API KHÔNG nhận system_instruction và KHÔNG nhận ảnh
    - `_is_text_part(part: dict)`
    - `_apply_gemma_hygiene(self, system_instruction: str, contents: list[dict])` — Chuẩn hoá payload cho Gemma: bỏ ảnh, gập system vào lượt user đầu tiên.
    - `create_chat_completion(self, *, messages, temperature, frequency_penalty, presence_penalty, max_tokens, response_format=None, grammar=None, timeout=None, reasoning_effort=None)`
    - `_maybe_dump_4xx(self, payload: dict, response)` — Debug: khi gặp 4xx và bật ERIS_LLM_DEBUG_4XX, ghi payload + body đầy đủ

## `llm/contracts.py`
- LOC: 215
- Functions:
  - `_gbnf_literal(value: str)`
  - `_build_decision_gbnf()`

## `llm/dds.py`
- LOC: 207
- Docstring: DDS — Decompose / Distill / Synthesize (Phase 2 + 3).
- Functions:
  - `extract_text(response: Any)` — Lấy text từ response chat-completion (OpenAI-shape hoặc Gemini-shape).
  - `run_workers(specs: list[WorkerSpec], *, provider: str='gemini', max_workers: int | None=None, per_worker_timeout: float | None=None)` — Chạy các worker SONG SONG (có trần đồng thời per-provider).
  - `distill_block(client: Any, *, label: str, text: str, max_bullets: int=3, max_tokens: int=160, timeout: float | None=12.0, min_chars_to_distill: int=400)` — Rút gọn MỘT khối ngữ cảnh thành vài gạch đầu dòng (text thuần).
  - `distill_blocks_parallel(client: Any, blocks: dict[str, str], *, provider: str='gemini', max_bullets: int=3, max_tokens: int=160, timeout: float | None=12.0, min_chars_to_distill: int=400, max_workers: int | None=None)` — Rút gọn nhiều khối SONG SONG. Trả dict cùng key; khối lỗi giữ nguyên gốc.
- Classes:
  - `WorkerResult` (decorator=dataclass(slots=True))
  - `WorkerSpec` (decorator=dataclass(slots=True)) — Một worker DDS: tên + hàm chạy (trả text hoặc None).

## `llm/key_pool.py`
- LOC: 304
- Docstring: llm/key_pool.py
- Functions:
  - `_normalize_kind(kind: str)`
  - `_is_placeholder(value: str)`
  - `_split_keys_env(*names: str)` — Tách danh sách key từ env (phân tách bằng dấu phẩy / xuống dòng / ;).
  - `_collect_gemini_keys()` — Gom key Gemini: chính + remote + speech + fallback pool.
  - `_collect_groq_keys()` — Gom key Groq: ERIS_GROQ_API_KEY + ERIS_GROQ_FALLBACK_API_KEYS (bỏ placeholder).
  - `get_key_pool(kind: str='gemini')` — Trả pool singleton theo provider-kind ('gemini' hoặc 'groq').
  - `get_shared_key_pool()` — Tương thích ngược: chọn pool theo ERIS_REMOTE_PROVIDER toàn cục.
  - `reset_shared_key_pool()` — Chỉ dùng cho test: xóa toàn bộ pool để build lại từ secrets.
  - `_max_concurrency(provider: str)`
  - `_get_semaphore(provider: str)`
  - `concurrency_slot(provider: str='gemini', *, timeout: float | None=None)` — Context manager giới hạn số call đồng thời per-provider.
  - `reset_concurrency_limits()` — Test/hot-reload: dựng lại semaphore theo env hiện tại.
- Classes:
  - `ApiKeyPool` — Danh sách key + một con trỏ rotation dùng chung, có theo dõi key "chết".
    - `__init__(self, keys: List[str])`
    - `size(self)`
    - `_alive_locked(self, idx: int, now: float)`
    - `alive_count(self)`
    - `_next_alive_locked(self, start: int, now: float)` — Tìm index key sống kế tiếp (gồm cả start). -1 nếu không có key sống.
    - `current_key(self)`
    - `rotate(self)` — Xoay sang key SỐNG kế tiếp. Trả True nếu chuyển được sang index khác.
    - `mark_dead(self, seconds: float=60.0)` — Đánh dấu key hiện tại nghỉ trong ``seconds`` giây (429/413/5xx).
    - `index(self)`
    - `stats(self)`

## `llm/llamacpp_client.py`
- LOC: 152
- Docstring: llm/llamacpp_client.py
- Functions:
  - `_project_root()`
  - `_bundle_root()` — PyInstaller bundle root (_MEIPASS). None khi chạy script thường.
  - `resolve_model_path(path_or_name: str)` — Định vị file gguf. Ưu tiên đường dẫn tuyệt đối; rồi project_root/path;
- Classes:
  - `LlamaCppClient` — Wrapper llama-cpp-python theo interface create_chat_completion của ERIS.
    - `__init__(self, *, model_path: str, model_name: str='', n_ctx: int | None=None, n_gpu_layers: int | None=None, chat_format: str | None=None)`
    - `unload_all(cls)` — Xả MỌI instance text khỏi VRAM (đóng + xoá cache).
    - `_llama(self)`
    - `create_chat_completion(self, *, messages, temperature=0.7, frequency_penalty=0.0, presence_penalty=0.0, max_tokens=512, response_format=None, grammar=None, timeout=None, **kwargs: Any)`

## `llm/local_llama_engine.py`
- LOC: 396
- Docstring: llm/local_llama_engine.py
- Functions:
  - `_env(name: str, default: str='')`
  - `_n_gpu_layers()`
  - `_vision_n_gpu_layers()` — GPU layers cho riêng vision. Mặc định 0 (CPU) để bảo vệ VRAM 4GB.
  - `build_local_or_ollama_client(*, timeout: float | None=None)` — Trả LocalLlamaEngine nếu ERIS_LOCAL_LLM_ENGINE=llamacpp, ngược lại OllamaClient.
- Classes:
  - `LocalLlamaEngine` — Engine llama-cpp dùng chung, interface tương thích OllamaClient.
    - `__init__(self, *, timeout: float | None=None)`
    - `_vision_on_gpu(self)`
    - `_free_text_vram(self)` — Xả model text khỏi VRAM (cả cache của engine này lẫn LlamaCppClient
    - `_text_llm(self)`
    - `_vision_llm(self)`
    - `chat_json(self, model: str, messages: list[dict[str, Any]], *, images: Optional[list[str]]=None, schema: Optional[dict[str, Any]]=None, keep_alive: str | int | None=None, temperature: float=0.0, options: Optional[dict[str, Any]]=None)`
    - `caption_image(self, image: str, *, prompt: str='Describe what is visible on this screen in concrete detail.', temperature: float=0.2, max_tokens: int | None=None, keep_alive: str | int | None=None)` — Vision → caption văn bản TỰ DO (không ép JSON).
    - `generate_json(self, model: str, prompt: str, *, images: Optional[list[str]]=None, schema: Optional[dict[str, Any]]=None, keep_alive: str | int | None=None, temperature: float=0.0, options: Optional[dict[str, Any]]=None)`
    - `_response_format(self, schema: Optional[dict[str, Any]])`
    - `_chat_text(self, messages, *, schema, temperature)`
    - `_chat_vision(self, messages, images, *, schema, temperature)`
    - `unload(self, model: str)` — Giải phóng model vision khỏi VRAM (text giữ resident).
    - `list_models(self)`
    - `encode_image_file(path: str)`
    - `encode_image_bytes(data: bytes)`
    - `data_uri_to_base64(data_uri_or_base64: str)`
    - `_messages_to_text(messages: list[dict[str, Any]])`
    - `_extract_content(raw: Any)`
    - `_parse_json_object(content: str)`

## `llm/ollama_client.py`
- LOC: 316
- Docstring: Client mỏng cho Ollama.
- Classes:
  - `OllamaClientError` (base=RuntimeError) — Lỗi gọi Ollama. Tách riêng để runtime có thể fallback sạch.
  - `OllamaResult` (decorator=dataclass(frozen=True)) — Kết quả chuẩn hóa từ Ollama.
  - `OllamaClient` (decorator=dataclass) — Client gọi Ollama qua HTTP API.
    - `__post_init__(self)`
    - `chat_json(self, model: str, messages: list[dict[str, Any]], *, images: Optional[list[str]]=None, schema: Optional[dict[str, Any]]=None, keep_alive: str | int | None='5m', temperature: float=0.0, options: Optional[dict[str, Any]]=None)` — Gọi `/api/chat` và kỳ vọng JSON object.
    - `generate_json(self, model: str, prompt: str, *, images: Optional[list[str]]=None, schema: Optional[dict[str, Any]]=None, keep_alive: str | int | None='5m', temperature: float=0.0, options: Optional[dict[str, Any]]=None)` — Gọi `/api/generate` và kỳ vọng JSON object.
    - `unload(self, model: str)` — Yêu cầu Ollama unload model.
    - `list_models(self)` — Lấy danh sách model đã pull trong Ollama.
    - `encode_image_file(path: str)` — Encode ảnh thành base64 thuần, phù hợp field `images`.
    - `encode_image_bytes(data: bytes)`
    - `data_uri_to_base64(data_uri_or_base64: str)` — Nhận data URI hoặc base64 thuần, trả base64 thuần.
    - `_attach_images(self, messages: list[dict[str, Any]], images: Optional[list[str]])`
    - `_normalize_base_url(base_url: str)`
    - `_post_json(self, path: str, payload: Mapping[str, Any])`
    - `_get_json(self, path: str)`
    - `_open_json(self, req: urllib.request.Request)`
    - `_extract_chat_content(raw: dict[str, Any])`
    - `_parse_json_object(content: str)` — Parse JSON object, có salvage khi model lỡ bọc thêm text.

## `llm/process_manager.py`
- LOC: 356
- Classes:
  - `RemoteModelProcessManager`
    - `__init__(self, *, logger, project_root: str)`
    - `_env_flag(self, name: str, default: str='0')`
    - `_build_remote_client(self)`
    - `_speech_api_requested(self)`
    - `_build_speech_client(self)`
    - `build_client(self, *, model_path: str='', n_ctx: int=0, n_gpu_layers: int=0)`
    - `build_style_client(self, *, model_path: str='', n_ctx: int=0, n_gpu_layers: int=0)`
    - `build_format_fallback_client(self, *, model_path: str='', n_ctx: int=0, n_gpu_layers: int=0)` — Build a Groq (OpenAI-compatible) client used to rescue chat/directive
    - `build_escalation_client(self, *, model_path: str='', n_ctx: int=0, n_gpu_layers: int=0)` — Build a DEDICATED "strong" client cho self-critique escalation (bái sư).
    - `build_vision_client(self, *, model_path: str='', n_ctx: int=0, n_gpu_layers: int=0)` — Build client vision REMOTE (OpenAI-compatible, vd shopaikey grok-3-image)
    - `stop(self)`

## `llm/service.py`
- LOC: 3865
- Functions:
  - `_normalize_vietnamese_ascii_text(text: str)`
  - `classify_chat_act(raw_user_text: str)`
- Classes:
  - `ChatAct` (base=Enum)
  - `FormatViolationException` (base=Exception) — Raised when a model response violates the public JSON contract.
    - `__init__(self, reason: str, *, channel: str='', raw_text: str='', kind: str='format_violation', stage: str='', origin: str='', public_surface: str='blocked', recoverable: bool=False)`
  - `LlmService`
    - `__init__(self, client, style_client=None, vision_client=None, fallback_client=None, escalation_client=None, logger=None)`
    - `_resolve_escalation_client(self)` — Client mạnh để bái sư. Ưu tiên escalation_client riêng, rồi fallback, rồi style.
    - `_http_status_code(self, exc: Exception)`
    - `_is_retryable_http_5xx(self, exc: Exception)`
    - `_classify_http_failure(self, exc: Exception)`
    - `_failure_meta(self, *, kind: str, stage: str, origin: str, public_surface: str, recoverable: bool, transport_truncated: bool=False)`
    - `_service_error_origin(self, *, channel: str)`
    - `_build_service_error_fallback(self, *, channel: str, reason: str, fallback_text: str='', kind: str='unknown', stage: str='service_error', origin: str='', recoverable: bool=False)`
    - `_message_text(self, message: dict)`
    - `_looks_like_direct_question(self, text: str)`
    - `_is_short_or_ambiguous_user_text(self, text: str)`
    - `_is_self_identity_question(self, text: str)`
    - `_contains_user_intent_inference(self, text: str)`
    - `_build_chat_contract_prompt(self, raw_user_text: str, act: ChatAct | None=None)`
    - `_chat_text_family(self, text: str)`
    - `_decision_payload_text(self, raw_json: str)`
    - `_chat_act_repair_signal(self, act: ChatAct)`
    - `_normalize_vietnamese_ascii(self, text: str)`
    - `_deterministic_chat_act_fallback_text(self, act: ChatAct, raw_user_text: str='')`
    - `_payload_with_repaired_chat_act_text(self, raw_json: str, *, act: ChatAct, text: str, reason: str)`
    - `_repair_chat_act_payload_with_llm(self, raw_json: str, *, act: ChatAct, raw_user_text: str, reason: str)`
    - `_rewrite_question_only_chat_answer(self, text: str)`
    - `_append_reasoning_tag(self, payload: dict, tag: str)`
    - `_looks_like_relational_feedback_text(self, text: str)`
    - `_looks_like_defensive_relational_reply(self, text: str)`
    - `_relational_repair_fallback_text(self, raw_user_text: str, current_text: str='')`
    - `_guard_chat_output(self, raw_json: str, *, raw_user_text: str)` — Guard chat wording without flattening ERIS.
    - `_contextual_service_fallback_text(self, messages: list[dict], *, channel: str)`
    - `_log_final_prompt(self, messages: list[dict], *, channel: str, stage: str)`
    - `_preview_log_text(self, text: str, *, limit: int=12000)`
    - `_looks_like_prompt_leak(self, text: str)` — Detect raw prompt/contract text that must never become public speech.
    - `_looks_like_malformed_decision_json(self, text: str)`
    - `_json_string_field_from_raw(self, raw_text: str, field: str)`
    - `_build_protocol_surface_fallback(self, *, channel: str, reason: str, text: str='', kind: str='prompt_leak', stage: str='llm_response_parse', origin: str='model_output')`
    - `_coerce_malformed_decision_payload(self, raw_text: str, *, channel: str)` — Salvage only speakable fields from truncated decision JSON.
    - `_log_raw_api_text(self, channel: str, raw: str)`
    - `_is_context_size_error(self, exc: Exception)`
    - `_parse_context_error_stats(self, exc: Exception)`
    - `_content_text_len(self, content)`
    - `_truncate_content(self, content, *, max_chars: int, keep: str)`
    - `_shrink_messages_for_context(self, messages: list[dict], *, n_ctx: int, max_tokens: int, margin_tokens: int=160)`
    - `_collect_text_chunks(self, value)`
    - `_extract_content(self, response: dict)`
    - `_extract_first_json_object(self, text: str)`
    - `_parse_json_object(self, text: str)`
    - `_normalize_payload_keys(self, value)`
    - `_is_valid_decision_payload(self, payload: dict | None)`
    - `_is_valid_motion_payload(self, payload: dict | None)`
    - `_is_valid_cognition_payload(self, payload: dict | None)`
    - `_is_decision_like_payload(self, payload: dict | None)`
    - `_coerce_bool_value(self, value, *, fallback: bool)`
    - `_coerce_confidence_value(self, value)`
    - `_coerce_reasoning_tags_value(self, value)`
    - `_coerce_action_value(self, value)`
    - `_action_field(self, action, *names, default=None)`
    - `_is_valid_text_field(self, value)`
    - `_is_valid_animation_field(self, value, *, allow_empty: bool)`
    - `_is_valid_system_action_field(self, value)`
    - `_is_valid_choice_number(self, value, choices: set[int])`
    - `_is_valid_target_x(self, value)`
    - `_allows_motion_target(self, payload: dict)`
    - `_coerce_text_value(self, value)`
    - `_coerce_animation_value(self, value, *, allow_empty: bool)`
    - `_coerce_direction_value(self, value)`
    - `_coerce_target_x_value(self, value, *, allow_motion_target: bool)`
    - `_coerce_system_action_value(self, value)`
    - `_coerce_decision_like_payload(self, payload: dict | None)`
    - `_coerce_json_candidate(self, raw_text: str)`
    - `_build_json_fallback(self, raw_text: str, *, channel: str)`
    - `_looks_like_provider_metadata(self, text: str)`
    - `_looks_like_markdown_json_stub(self, text: str)`
    - `_safe_fallback_text(self, raw_text: str, *, channel: str)`
    - `_build_empty_text_fallback(self, *, channel: str)`
    - `_decision_needs_non_empty_text(self, raw_text: str)`
    - `_decision_text_is_invalid(self, raw_text: str)`
    - `_with_non_empty_text_rule(self, messages: list[dict])`
    - `_repair_empty_decision_text(self, *, messages: list[dict], channel: str, previous_json: str)`
    - `_repair_decision_json(self, raw_text: str, *, channel: str)`
    - `_strict_decision_candidate_or_raise(self, raw: str, *, channel: str)`
    - `_client_provider_cap(self, client)` — Trả (provider, hard_cap) cho một client dựa trên base_url/model.
    - `_route_client_for_size(self, messages, *, primary, channel: str)` — Nếu prompt vượt cap của ``primary`` (vd Groq free 6000 TPM) mà có
    - `_complete_decision(self, *, messages: list[dict], channel: str, request_timeout: float | None=None, require_text: bool=True, allow_local_fallback: bool=False, force_local_fallback: bool=False, escalate: bool=False, reasoning_effort: str=None)`
    - `_normalize_for_claim_diff(self, text: str)`
    - `_style_rewrite_is_safe(self, original: str, rewritten: str)`
    - `rewrite_text_with_local_style(self, decision, *, channel: str='')`
    - `rewrite_guard_violation_text(self, *, original_text: str, violation_rule: str, violation_reason: str, missing_evidence: tuple[str, ...]=(), fallback_text: str='', channel: str='', user_text: str='', internal_state_context: str='', grounding_context: str='', arbitration_context: str='')` — One-shot cognitive steering repair for post-generation guards.
    - `rewrite_for_felt_expression(self, *, original_text: str, reason: str, stance: str='', min_words: int=0, channel: str='', user_text: str='', internal_state_context: str='', grounding_context: str='')` — Reroll theo chiều MỞ (Nước 1): nở một câu bị bóp phẳng cho stance lộ ra.
    - `_compress_internal_context(self, text: str, *, kind: str)`
    - `_extract_action_plan_context(self, text: str)`
    - `_build_style_block(self, *, fe_context: str, appraisal_context: str='', internal_state_context: str='')`
    - `_build_memory_context_block(self, memory_context: str='')`
    - `_build_grounding_context_block(self, grounding_context: str='')`
    - `_build_relational_repair_contract(self, context: str)`
    - `_is_force_speak_without_speech_evidence(self, *, telemetry_data: str, ti_context: str)`
    - `_build_directive_mode_addendum(self, ti_context: str)`
    - `_build_speech_intent_guidance(self, speech_intent: str)`
    - `_is_session_ritual_call(self, *, speech_intent: str, telemetry_data: str='', ti_context: str='')`
    - `_fallback_greeting_engine(self)`
    - `_fallback_greeting_text(self, *, telemetry_data: str='', reason: str='', avoid_text: str='')`
    - `_build_session_greeting_payload(self, *, text: str, reason: str, confidence: float=0.72, quality_note: str='')`
    - `_session_greeting_frame(self, telemetry_data: str)`
    - `_session_greeting_quality_scorer(self)`
    - `_utterance_selector(self)`
    - `_extract_candidate_strings(self, payload: dict | None)`
    - `_generate_session_ritual_greeting(self, *, telemetry_data: str, ti_context: str='', ni_context: str='', fe_context: str='', appraisal_context: str='', internal_state_context: str='', memory_context: str='', avoid_text: str='', request_timeout: float | None=None)`
    - `generate_directive(self, *, telemetry_data: str, ti_context: str='', ni_context: str='', fe_context: str='', appraisal_context: str='', internal_state_context: str='', memory_context: str='', avoid_text: str='', speech_intent: str='screen_observation', vision_trace_marker: str='', request_timeout: float | None=None, require_text: bool=True, use_escalation_client: bool=False, reasoning_effort: str=None)`
    - `generate_micro_presence_line(self, *, seed: str='', context: dict | None=None, signal_score: float | None=None, kind: str='micro_presence', fallback_text: str='', avoid_text: str='', focus_kind: str='', focus_summary: str='', idle_seconds: float=0.0, seeds: tuple[str, ...]=(), micro_context: dict[str, str] | None=None, **kwargs)`
    - `generate_curiosity_seed(self, *, focus_kind: str='', active_window: str='', idle_seconds: float=0.0, avoid_topics: tuple[str, ...]=(), user_context: str='')` — Eris tự hỏi Gemini để lấy chủ đề/seed khi không có vật liệu nào.
    - `generate_screen_facts(self, *, screen_image_data_uri: str, mode: str='ambient')`
    - `_chat_client_supports_vision(self)` — Chỉ nhồi ảnh thô vào message chat khi model chat thật sự đa phương thức.
    - `_dds_enabled(self)` — DDS distillation bật/tắt (mặc định bật). Chỉ kích hoạt khi ngữ cảnh nặng.
    - `_dds_distill_client(self)` — Chọn client cho worker map của DDS.
    - `_maybe_distill_blocks(self, blocks: dict, *, channel: str)` — Phase 2/3: khi tổng ngữ cảnh nặng vượt ngưỡng, băm và rút gọn các khối
    - `generate_chat_reply(self, *, chat_history: list[dict], user_message: str, raw_user_text: str='', ti_context: str='', ni_context: str='', fe_context: str='', appraisal_context: str='', internal_state_context: str='', conversation_context: str='', memory_context: str='', grounding_context: str='', screen_image_data_uri: str='', reply_context=None, require_text: bool=True, defusing_context: str='', allow_local_fallback: bool=False, format_retry_context: str='', last_failure: str='', force_local_fallback: bool=False, use_escalation_client: bool=False, reasoning_effort: str=None)`
    - `run_ni_meta_critic(self, *, goals: list[str], telemetry_text: str, feature_vector: dict)`

## `llm/token_budget.py`
- LOC: 288
- Docstring: Token accounting + prompt hard-cap (Phase 0).
- Functions:
  - `_safe_int_env(name: str, default: int)`
  - `detect_provider(base_url: str | None, model: str | None)` — Suy ra provider từ base_url + model. Không bao giờ raise.
  - `budget_for_provider(provider: str)`
  - `hard_cap_for_provider(provider: str)` — Trần token cho MỘT prompt. Thứ tự ưu tiên:
  - `_content_chars(content: Any)` — Trả (chars, image_count) của một content (str | list | dict).
  - `estimate_tokens(messages: Any)` — Ước lượng token cho danh sách messages kiểu OpenAI. Heuristic chars/4.
  - `_largest_text_index(messages: list[dict])`
  - `_truncate_to_cap(messages: list[dict], cap: int)` — Cắt bớt nội dung text dài nhất cho tới khi xuống dưới cap (best-effort).
  - `compress_system_message(content: str)` — Nén hoặc lược bỏ bớt các khối cồng kềnh trong system prompt (diary, thought_stream, persona)
  - `enforce_prompt_cap(messages: Any, cap: int)` — Nếu prompt vượt ``cap`` token: bỏ bớt lượt history cũ (giữ system + 5 lượt
  - `preflight(messages: Any, *, base_url: str | None=None, model: str | None=None)` — Log token ước lượng và áp hard-cap trước khi gửi. Trả messages (đã cắt

## `llm/tutor_backend.py`
- LOC: 307
- Docstring: llm/tutor_backend.py
- Classes:
  - `CaptchaOrExpired` (base=Exception) — Gia sư web yêu cầu captcha/đăng nhập lại — không thể tự vượt.
  - `SelectorMiss` (base=Exception) — Không tìm thấy selector cần thiết trên trang.
  - `TutorBackend` (decorator=runtime_checkable; base=Protocol)
    - `ask(self, question: TutorQuestion, *, on_stage: StageCb=None)`
    - `close(self)`
  - `FakeTutorBackend` — Backend giả: trả answer cố định, có thể giả lập lỗi. KHÔNG đụng mạng.
    - `__init__(self, *, answer_text: str='', citations: tuple[str, ...]=(), raise_exc: Optional[BaseException]=None, fail_reason: Optional[str]=None)`
    - `ask(self, question: TutorQuestion, *, on_stage: StageCb=None)`
    - `close(self)`
  - `PageSession` (decorator=runtime_checkable; base=Protocol) — Phiên trang trừu tượng để GeminiWebBackend không bám cứng Playwright (test được).
    - `goto(self, url: str)`
    - `is_blocked(self)`
    - `submit_question(self, text: str, *, delay_min_ms: int, delay_max_ms: int)`
    - `read_answer(self, *, stable_window_s: float, deadline: float)`
    - `citations(self)`
  - `GeminiWebBackend` — Tự động hóa gemini.google.com bằng trình duyệt thật.
    - `__init__(self, config: Optional[TutorConfig]=None, logger: Any=None, *, page_session_factory: Optional[Callable[[], Any]]=None)`
    - `ask(self, question: TutorQuestion, *, on_stage: StageCb=None)`
    - `close(self)`
    - `_default_factory(self)`

## `memory/__init__.py`
- LOC: 30
- Docstring: Public memory API for ERIS.

## `memory/active_state_snapshot.py`
- LOC: 171
- Docstring: Active State Snapshot cho ERIS.
- Functions:
  - `iso_now()`
  - `atomic_write_json(path: str, payload: Any)`
  - `compact_text(value: Any, *, limit: int=320)`
- Classes:
  - `ActiveStateSnapshot` (decorator=dataclass(slots=True)) — State overwrite được, dùng cho runtime hiện tại.
    - `to_dict(self)`
    - `from_dict(cls, data: dict[str, Any])`
  - `ActiveStateStore` — Kho snapshot overwrite.
    - `__init__(self, path: str)`
    - `load(self)`
    - `save(self, snapshot: ActiveStateSnapshot)`
    - `apply_commit(self, request: Any)`

## `memory/affective_residue_memory.py`
- LOC: 212
- Docstring: Affective Residue Memory: dư âm cảm xúc dưới dạng pressure.
- Functions:
  - `iso_now()`
  - `compact_text(value: Any, *, limit: int=360)`
  - `clamp01(value: float)`
  - `clamp11(value: float)`
  - `atomic_write_json(path: str, payload: Any)`
- Classes:
  - `AffectiveResidueItem` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data: dict[str, Any])`
    - `recall_line(self)`
  - `AffectiveResidueMemoryStore`
    - `__init__(self, path: str, *, max_items: int=120)`
    - `load(self)`
    - `save(self, items: list[AffectiveResidueItem])`
    - `apply_commit(self, request: Any)`
    - `recall(self, query: str='', *, limit: int=6)`
    - `_infer_type(self, description: str, reason: str)`
    - `_infer_valence(self, description: str, reason: str)`
    - `_pressure_effects(self, residue_type: str, intensity: float)`

## `memory/claim_consolidator.py`
- LOC: 72
- Functions:
  - `_norm(text: str)`
- Classes:
  - `ClaimMergeDecision` (decorator=dataclass(frozen=True, slots=True))
  - `ClaimConsolidator` — Logic merge claim độc lập với store JSON.
    - `can_merge(self, old: SemanticClaim, new: SemanticClaim)`
    - `find_merge_target(self, items: Iterable[SemanticClaim], new: SemanticClaim)`

## `memory/claim_entailment.py`
- LOC: 129
- Functions:
  - `semantic_claim_from_memory_item(item: Any)` — Lấy SemanticClaim từ SemanticMemoryItem hoặc dict cũ nếu có.
- Classes:
  - `ClaimEntailmentDecision` (decorator=dataclass(frozen=True, slots=True))
    - `can_answer(self)`
  - `ClaimEntailmentEngine` — Engine entailment giữa SemanticClaim và SemanticQueryIntent.
    - `evaluate(self, claim: SemanticClaim, query: SemanticQueryIntent | str)`
    - `rank(self, claims: Iterable[SemanticClaim], query: SemanticQueryIntent | str)`

## `memory/claim_extractor.py`
- LOC: 68
- Functions:
  - `extract_claims(user_text: str, *, evidence_ids: Iterable[str]=())`
- Classes:
  - `ClaimExtractor` (decorator=dataclass(slots=True)) — Facade extract claim theo pipeline frame semantics.
    - `extract(self, user_text: str, *, evidence_ids: Iterable[str]=(), source: str='user_text', llm_structured: Mapping[str, Any] | None=None)`

## `memory/claims/__init__.py`
- LOC: 14
- Docstring: Tầng claim logic: build claim, ontology, entailment.

## `memory/claims/claim_builder.py`
- LOC: 307
- Classes:
  - `ClaimBuilder` (decorator=dataclass(slots=True)) — Builder deterministic từ MeaningFrame sang ExtractedClaim.
    - `build_many(self, result: MeaningParseResult, *, evidence_ids: Iterable[str]=(), source: str='user_text')`
    - `build_one(self, frame: MeaningFrame, *, evidence_ids: tuple[str, ...]=(), source: str='user_text')`
    - `_build_from_ai_classification(self, raw: Mapping[str, Any], *, evidence_ids: tuple[str, ...]=())` — Build ExtractedClaim từ schema mới của Gemini.
    - `_predicate_for_frame(self, frame: MeaningFrame)`
    - `_dedupe(self, items: list[ExtractedClaim])`

## `memory/embedding_index.py`
- LOC: 424
- Docstring: memory/embedding_index.py
- Functions:
  - `_cosine_similarity(a: np.ndarray, b: np.ndarray)` — Cosine similarity giữa vector a và matrix b (N, D).
  - `_short_hash(text: str)`
  - `build_embedding_index(*, model_name: str | None=None, enabled: bool=True)` — Build EmbeddingIndex nếu enabled.
  - `get_shared_embedding_index()` — Trả EmbeddingIndex dùng chung toàn tiến trình (build một lần, lazy nạp model).
  - `reset_shared_embedding_index()` — Xoá singleton (dùng cho test/maintenance).
- Classes:
  - `EmbeddingIndex` — In-memory embedding index dùng transformers.
    - `__init__(self, *, model_name: str | None=None, cache_dir: str | None=None, device: str | None=None, max_seq_length: int=128)`
    - `search(self, query: str, items: list[Any], *, text_fn: Callable[[Any], str], limit: int=24)` — Tìm items gần với query nhất theo cosine similarity.
    - `ensure_vectors(self, items: list[Any], *, text_fn: Callable[[Any], str])` — Pre-embed items vào cache. Trả số item mới được embed.
    - `clear_cache(self)`
    - `debug_status(self)`
    - `_ensure_loaded(self)`
    - `_load_model(self)`
    - `_encode(self, texts: list[str])` — Encode list of texts → ndarray (N, D).
    - `_encode_with_cache(self, texts: list[str])` — Encode texts, dùng cache để tránh re-embed text đã biết.
    - `embed(self, text: str)` — Embed một text -> vector tuple. Trả () nếu model không sẵn sàng.
    - `embed_events(self, texts)` — Embed nhiều text -> list vector tuple (cùng thứ tự).
    - `_cuda_available()`

## `memory/episodic_memory.py`
- LOC: 627
- Docstring: Episodic Memory: chuyện cụ thể đã xảy ra.
- Functions:
  - `iso_now()`
  - `compact_text(value: Any, *, limit: int=360)`
  - `clamp01(value: float)`
  - `atomic_write_json(path: str, payload: Any)`
  - `normalize_text(text: Any)` — Normalize text để so khớp ổn hơn.
  - `normalized_tokens(text: Any)` — Token hóa nhẹ, bỏ stopword và token quá ngắn.
  - `token_bigrams(tokens: tuple[str, ...])`
  - `weighted_counter(tokens: tuple[str, ...])` — Tạo counter có trọng số nhẹ cho anchor kỹ thuật.
  - `weighted_jaccard(left: Counter[str], right: Counter[str])` — Jaccard có trọng số giữa hai counter.
  - `phrase_match_score(query_norm: str, hay_norm: str)` — Score phrase match mềm.
  - `parse_timestamp(timestamp: str)` — Parse timestamp best-effort.
  - `recency_boost(timestamp: str, *, now: float | None=None)` — Boost nhẹ cho episode gần đây.
- Classes:
  - `RecallScore` (decorator=dataclass(frozen=True, slots=True)) — Debug score cho một item recall.
    - `to_dict(self)`
  - `EpisodicMemoryItem` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data: dict[str, Any])`
    - `recall_line(self)`
    - `search_fields(self)` — Fields phục vụ recall, có trọng số riêng trong scorer.
  - `EpisodicMemoryStore`
    - `__init__(self, path: str, *, max_items: int=200)`
    - `load(self)`
    - `save(self, items: list[EpisodicMemoryItem])`
    - `apply_commit(self, request: Any, *, frame: Any=None)`
    - `recall(self, query: str='', *, limit: int=6)` — Recall episode theo relevance score có bằng chứng.
    - `recall_with_scores(self, query: str='', *, limit: int=6)` — Debug recall: trả cả item và breakdown score.
    - `_score_item(self, item: EpisodicMemoryItem, *, query_norm: str, query_tokens: tuple[str, ...], query_counter: Counter[str], query_bigrams: set[tuple[str, str]])` — Chấm một episodic item.
    - `_mark_accessed(self, selected: list[EpisodicMemoryItem])` — Tăng access_count cho item đã recall.
    - `_trim(self, items: list[EpisodicMemoryItem])`

## `memory/event_ledger.py`
- LOC: 219
- Docstring: Append-only Event Ledger cho ERIS.
- Functions:
  - `now_ts()` — Trả timestamp float để khớp RawSignal/EvidenceItem trong cortex.
  - `iso_now()` — Timestamp người đọc được. Audit mà không đọc được thì cũng chỉ là trang trí.
  - `compact_text(value: Any, *, limit: int=600)` — Nén text để ledger không phình thành nghĩa địa token.
  - `atomic_write_json(path: str, payload: Any)` — Ghi JSON bằng temp file rồi replace để giảm rủi ro hỏng file giữa chừng.
- Classes:
  - `EventLedgerRecord` (decorator=dataclass(slots=True)) — Một dòng sự kiện append-only.
    - `to_dict(self)`
    - `from_dict(cls, data: dict[str, Any])`
  - `EventLedger` — Kho append-only cho raw event.
    - `__init__(self, path: str, *, max_records: int=5000)`
    - `load(self)`
    - `save(self, records: list[EventLedgerRecord])`
    - `append(self, record: EventLedgerRecord)`
    - `append_raw_event(self, *, frame_id: str, source: str, content: Any, source_signal_id: str='', evidence_ids: Iterable[str]=(), reliability: float=1.0, privacy_level: PrivacyLevel='normal', tags: Iterable[str]=(), metadata: dict[str, Any] | None=None)`
    - `append_from_signal(self, signal: Any, *, frame_id: str='', evidence_ids: Iterable[str]=())` — Tạo record từ RawSignal-like object mà không buộc import cortex.
    - `recent(self, *, limit: int=50, source: str | None=None)`
    - `by_frame(self, frame_id: str)`
    - `query(self, text: str, *, limit: int=20)`

## `memory/judgement/__init__.py`
- LOC: 16
- Docstring: Tầng phán xét memory: worthiness, retention, consolidation.

## `memory/judgement/consolidation.py`
- LOC: 60
- Functions:
  - `should_promote_candidate(candidate: Mapping[str, Any], *, observations: int=1)` — Quyết định candidate có nên promote lên memory ổn định không.
  - `merge_strength(existing_confidence: float, new_confidence: float, observations: int)` — Tăng confidence có giới hạn khi claim được quan sát lặp lại.
  - `_float(value: Any, default: float=0.0)`
- Classes:
  - `ConsolidationDecision` (decorator=dataclass(frozen=True, slots=True))

## `memory/memory_activation.py`
- LOC: 161
- Classes:
  - `MemoryActivation` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `to_attention_line(self)`
  - `ScoredMemoryCandidate` (decorator=dataclass(slots=True))
  - `MemoryRetrievalResult` (decorator=dataclass(slots=True))
  - `MemoryActivationBuilder`
    - `__init__(self, profiles: dict[str, LayerProfile] | None=None)`
    - `build(self, scored: list[ScoredMemoryCandidate], *, max_activations: int=10)`
    - `_route_bias(self, activations: list[MemoryActivation], route: str)`

## `memory/memory_ai_curator.py`
- LOC: 511
- Docstring: memory/memory_ai_curator.py
- Functions:
  - `_compact(value: Any, limit: int=400)`
  - `_safe_float(value: Any, default: float=0.0)`
  - `_get(obj: Any, key: str, default: Any=None)`
- Classes:
  - `CuratorResult` (decorator=dataclass(slots=True)) — Kết quả một lượt curator chạy.
    - `to_dict(self)`
  - `MemoryAICurator` — AI curator chạy trong background maintenance.
    - `__init__(self, *, llm_service: Any=None, memory_core: Any=None)`
    - `run_distillation(self, *, budget: str='normal')` — Distill episodic clusters → semantic facts.
    - `run_concern_bridge(self, *, concern_store_path: str | None=None, budget: str='normal')` — Bridge concern chín → long-term memory.
    - `_cluster_episodes(self, items: list[Any], *, limit: int)` — Nhóm episode tương đồng theo summary token overlap.
    - `_distill_cluster(self, cluster: list[dict])`
    - `_load_concerns(self, path: str | None)`
    - `_ripe_concerns(self, concerns: list[dict], *, limit: int)` — Lọc concern đủ chín để bridge.
    - `_bridge_concern(self, concern: dict)`
    - `_commit_semantic_fact(self, fact: dict, *, evidence_ids: list[str])`
    - `_commit_from_bridge(self, decision: dict, *, evidence_ids: list[str])`
    - `_mark_concern_bridged(self, concern: dict, path: str | None)` — Đánh dấu concern đã được bridge để không gọi lại.
    - `_call_llm(self, system: str, user: str, *, max_tokens: int=256)` — Gọi LLM qua llm_service.client (Gemini).
    - `_parse_json(self, raw: str)`
    - `_to_namespace(d: dict)`

## `memory/memory_candidate.py`
- LOC: 183
- Classes:
  - `MemoryCandidate` (decorator=dataclass(slots=True))
    - `rough_score(self)`
  - `CandidateBatch` (decorator=dataclass(slots=True))
  - `MemoryLayerAdapter` — Adapter đọc memory store bằng load()/recall() nếu có.
    - `__init__(self, *, layer: str, store: Any)`
    - `retrieve_candidates(self, cue: MemoryCue, *, limit: int=24)`
    - `_load_items(self, cue: MemoryCue, *, limit: int)`
    - `_candidate_for_record(self, record: MemoryRecord, cue: MemoryCue)`

## `memory/memory_cognition.py`
- LOC: 617
- Docstring: Memory Cognition Core cho ERIS.
- Functions:
  - `_request_get(request: Any, name: str, default: Any=None)`
  - `_request_metadata(request: Any)`
  - `_as_text_list(values: Any, *, limit: int=260)`
  - `_content_for_target(target: str, content: Any)` — Normalize structured commit payloads before sending them to layer stores.
- Classes:
  - `MemoryQuery` (decorator=dataclass(slots=True))
  - `MemoryCommitDecision` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `CommitPolicy` (decorator=dataclass(slots=True)) — Rule chặn ghi nhớ bừa.
  - `MemoryCognitionCore` — Facade chính của memory.
    - `__init__(self, base_dir: str, *, policy: CommitPolicy | None=None)`
    - `commit(self, request: StateCommitRequest, *, frame: Any=None)`
    - `commit_many(self, requests: list[StateCommitRequest], *, frame: Any=None)`
    - `lookup_fact(self, fact_key: str)`
    - `get_fact(self, fact_key: str)`
    - `semantic_lookup(self, fact_key: str)`
    - `recall(self, query: MemoryQuery | str='', *, frame: Any=None, max_items: int | None=None, budget_mode: BudgetMode | None=None)`
    - `retrieve(self, query: MemoryQuery | str='', *, frame: Any=None)` — Truy hồi memory bằng retrieval engine mới.
    - `load(self)`
    - `save(self, snapshot: Mapping[str, Any] | None=None)`
    - `render_context(self, query: MemoryQuery | str='', *, snapshot: Any=None, frame: Any=None, max_lines: int=18)`
    - `build_commit_request(self, *, target: str, content: Any, confidence: float, evidence_ids: list[str], reason: str, storage_permission: bool, permission_required: bool=True, decay_policy: str='normal')`
    - `_normalize_request(self, request: Any)`
    - `lookup_fact(self, fact_key: str)` — Lookup semantic fact value by fact_key for structured recall executor.
    - `search_memory_candidates(self, query: str='', *, limit: int=8)`
    - `candidate_trace_for_query(self, query: str='')`
    - `load_active_state(self)`
    - `_check_commit_permission(self, request: Any, *, target: str, confidence: float, evidence_ids: list[str])`
    - `_commit_event_ledger(self, request: Any, *, frame: Any=None)`
    - `_query_from_frame(self, frame: Any)`
    - `_query_from_snapshot(self, snapshot: Any)`
    - `_budget_from_frame(self, frame: Any)`
    - `_quotas(self, *, mode: BudgetMode, max_items: int)`
    - `_packet_with_retrieval_resonance(self, packet: MemoryPacket, *, query_text: str)` — No-op compatibility helper.

## `memory/memory_commit_policy.py`
- LOC: 1027
- Functions:
  - `_strip_accents(text: str)`
  - `normalize_vi(text: str)` — Normalize tiếng Việt để match rule ổn định hơn.
  - `_clean_value(value: str)`
  - `_evidence(turn_id: str | None)`
  - `_has_self_marker(norm: str)`
  - `_looks_like_question(norm: str, raw: str)` — Chặn recall query khỏi bị commit nhầm thành fact.
  - `_extract_with_patterns(raw: str, patterns: Iterable[str])`
  - `_year_from_2k(token: str)`
  - `_bounded_month(value: str)`
  - `_explicit_importance(norm: str)`
  - `_looks_like_convention(norm: str)`
  - `_guess_domain(norm: str)`
  - `_candidate_fact_keys(norm: str, domain: str)`
  - `_slug_key(value: str, *, limit: int=48)`
- Classes:
  - `MemoryCommitPolicy` (decorator=dataclass(slots=True)) — Memory intake 3 tầng cho user turn.
    - `__post_init__(self)`
    - `set_semantic_parser(self, parser: Any)` — Gắn parser model.gguf/hybrid sau khi khởi tạo runtime.
    - `decide_from_user_turn(self, user_text: str, *, turn_id: str | None=None, allow_candidate: bool=True, llm_structured: Mapping[str, Any] | None=None)`
    - `_decide_with_semantic_claims(self, raw: str, turn_id: str | None, *, llm_structured: Mapping[str, Any] | None=None)` — Chạy pipeline claim/ontology trước các rule legacy.
    - `_decision_from_ai_classification(self, extracted: Any, claim: Any)` — Tạo MemoryCommitDecision trực tiếp từ AI classification.
    - `_decision_from_semantic_claim(self, claim: SemanticClaim, retention: Any)`
    - `_surface_claim_for_semantic_claim(self, claim: SemanticClaim)`
    - `_memory_kind_for_semantic_claim(self, claim: SemanticClaim)`
    - `_decay_for_retention(self, decay_policy: str)`
    - `_extract_user_name(self, raw: str, norm: str, turn_id: str | None)`
    - `_extract_birth_year(self, raw: str, norm: str, turn_id: str | None)`
    - `_extract_birth_month(self, raw: str, norm: str, turn_id: str | None)`
    - `_extract_age_observed(self, raw: str, norm: str, turn_id: str | None)`
    - `_extract_current_residence(self, raw: str, norm: str, turn_id: str | None)`
    - `_extract_temporal_residence(self, raw: str, norm: str, turn_id: str | None)`
    - `_extract_user_convention(self, raw: str, norm: str, turn_id: str | None)`
    - `_extract_response_style(self, raw: str, norm: str, turn_id: str | None)`
    - `_extract_memory_test_hint(self, raw: str, norm: str, turn_id: str | None)`
    - `_extract_general_preference(self, raw: str, norm: str, turn_id: str | None)`
    - `_build_unresolved_candidate(self, raw: str, norm: str, turn_id: str | None, importance: float, importance_reasons: list[str])`
    - `_dedupe(self, decisions: list[MemoryCommitDecision])`

## `memory/memory_consolidator.py`
- LOC: 79
- Classes:
  - `ConsolidationResult` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `MemoryConsolidator`
    - `__init__(self, memory_core: Any, *, intake_policy: MemoryCommitPolicy | None=None)`
    - `run_once(self, *, limit: int=20, max_attempts: int=5)`

## `memory/memory_cue.py`
- LOC: 331
- Classes:
  - `MemoryCue` (decorator=dataclass(slots=True))
    - `all_text(self)`
    - `token_set(self)`
    - `anchor_set(self)`
    - `layer_allowed(self, layer: str)`
    - `to_dict(self)`
  - `MemoryCueBuilder` — Dựng cue từ query/frame mà không import CognitiveFrame cứng.
    - `from_query_or_frame(self, query: Any='', *, frame: Any=None, budget_mode: str='normal')`
    - `_extract_user_text(self, frame: Any)`
    - `_extract_dominant_thread(self, frame: Any)`
    - `_extract_semantic_family(self, frame: Any)`
    - `_extract_task_intent(self, frame: Any)`
    - `_extract_files(self, text: str)`
    - `_extract_modules(self, text: str)`
    - `_looks_like_current_evidence_request(self, text: str)`
    - `_looks_like_exact_recall_request(self, text: str)`
    - `_allowed_layers(self, *, needs_current_evidence: bool, needs_exact_recall: bool, task_intent: str)`
    - `_repair_tags(self, text: str)`
    - `_affect_tags(self, frame: Any)`
    - `_relation_tags(self, frame: Any)`
    - `_privacy_sensitivity(self, text: str)`

## `memory/memory_kernel.py`
- LOC: 495
- Classes:
  - `MemoryKernelDebugSnapshot` (decorator=dataclass(slots=True)) — Snapshot nhỏ cho dev mode.
    - `to_dict(self)`
  - `MemoryKernel` — Facade chính cho toàn bộ memory runtime.
    - `__init__(self, base_dir: str | None=None, *, core: MemoryCognitionCore | None=None, semantic_parser: Any | None=None, config: MemoryKernelConfig | None=None, commit_policy: CommitPolicy | None=None, query_compiler: MemoryQueryCompiler | None=None, query_executor: MemoryQueryExecutor | None=None, surface_policy: MemoryRecallSurfacePolicy | None=None, turn_annotator: TurnAnnotator | None=None)`
    - `from_existing_core(cls, core: MemoryCognitionCore, *, semantic_parser: Any | None=None, config: MemoryKernelConfig | None=None)` — Bọc MemoryCognitionCore hiện có mà không migrate store ngay.
    - `ingest(self, text: str, *, evidence_ids: list[str] | None=None, turn_id: str | None=None, source: str='chat_turn', mode: MemoryIngestMode='fast', allow_candidate: bool | None=None, storage_permission: bool=True, permission_required: bool=False, context: Mapping[str, Any] | None=None)` — Đưa một mảnh text/evidence vào memory lifecycle.
    - `answer(self, query: str, *, session_ledger: Any | None=None, context: Mapping[str, Any] | None=None, min_confidence: float | None=None, max_ambiguity: float | None=None)` — Trả lời deterministic cho câu hỏi memory nếu đủ chắc.
    - `build_packet(self, query: str='', *, budget_mode: str='normal', max_items: int=18, token_budget: int=900, frame: Any | None=None)` — Dựng MemoryPacket/resonance context cho cognition.
    - `maintain(self, *, budget: MaintenanceBudget='small', reason: str='idle', destructive: bool | None=None)` — Chạy maintenance nền.
    - `commit(self, request: Any, *, frame: Any=None)` — Compat: route commit cũ xuống core.
    - `commit_many(self, requests: list[Any], *, frame: Any=None)`
    - `recall(self, query: Any='', *, frame: Any=None)` — Compat với MemoryCognitionCore.recall().
    - `retrieve(self, query: Any='', *, frame: Any=None)`
    - `load(self)`
    - `save(self, snapshot: Mapping[str, Any] | None=None)`
    - `render_context(self, *args: Any, **kwargs: Any)`
    - `lookup_fact(self, fact_key: str)`
    - `debug_snapshot(self)`
    - `_annotate_request(self, request: Any, *, mode: MemoryIngestMode, source: str, context: Mapping[str, Any] | None, evidence_ids: list[str])` — Gắn metadata kernel vào StateCommitRequest/dict.
    - `_compile_debug(self, compile_result: Any)`

## `memory/memory_kernel_contracts.py`
- LOC: 222
- Classes:
  - `MemoryKernelConfig` (decorator=dataclass(slots=True)) — Config runtime cho MemoryKernel.
  - `MemoryIngestResult` (decorator=dataclass(slots=True)) — Kết quả ingest một mảnh text/evidence.
    - `committed_count(self)` — Số commit được nhận bởi store.
    - `to_dict(self)` — Dump debug an toàn cho log/dev panel.
  - `MemoryAnswerResult` (decorator=dataclass(slots=True)) — Kết quả answer deterministic từ MemoryKernel.
    - `text(self)` — Text public nếu có answer.
    - `confidence(self)` — Confidence mềm để runtime quyết có dùng answer hay không.
    - `to_dict(self)`
  - `MemoryMaintenanceReport` (decorator=dataclass(slots=True)) — Báo cáo maintain memory.
    - `to_dict(self)`

## `memory/memory_maintenance.py`
- LOC: 247
- Classes:
  - `MemoryMaintenanceRunner` — Orchestrator maintain nhẹ cho memory stores.
    - `__init__(self, memory_core: Any, *, ingest_policy: Any=None, destructive: bool=False, llm_service: Any=None)`
    - `run(self, *, budget: MaintenanceBudget='small', reason: str='idle', destructive: bool | None=None)` — Chạy một lượt maintain.
    - `_candidate_limit(self, budget: MaintenanceBudget)`
    - `_run_access_decay(self, *, budget: str, destructive: bool)` — Áp half-life decay lên access_count trong semantic và episodic store.
    - `_run_prune_audit(self, *, destructive: bool)` — Chạy prune trên các store có load/save.

## `memory/memory_models.py`
- LOC: 215
- Functions:
  - `_state_decay_from_memory_decay(decay: DecayPolicy)`
  - `_commit_kind_for_target(target: MemoryTarget)`
  - `_commit_content_from_decision(decision: MemoryCommitDecision, metadata: dict[str, Any])`
- Classes:
  - `MemoryTarget` (base=str, Enum) — Loại kho nhớ mà một fact/candidate nên đi vào.
  - `SurfaceMode` (base=str, Enum) — Cách ký ức được phép hiện ra ngoài khi recall.
  - `DecayPolicy` (base=str, Enum) — Độ bền của ký ức.
  - `MemoryCommitKind` (base=str, Enum) — Loại commit request ở tầng intake.
  - `MemoryKind` (base=str, Enum) — Nhãn nghĩa cấp cao, tránh để các tầng sau phải đoán từ text thô.
  - `MemoryCommitDecision` (decorator=dataclass(frozen=True)) — Quyết định commit một mảnh thông tin.
    - `to_state_commit_request(self, *, storage_permission: bool=True, permission_required: bool=False)` — Chuyển sang StateCommitRequest của project nếu import được.
  - `RecallRequest` (decorator=dataclass(frozen=True)) — Yêu cầu recall đã được phân loại trước khi đụng tới memory thật.
  - `RecallAnswer` (decorator=dataclass(frozen=True)) — Câu trả lời recall đã qua policy, có confidence và trace để debug.

## `memory/memory_packet_builder.py`
- LOC: 170
- Classes:
  - `MemoryPacket` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `to_attention_lines(self, *, max_items: int=5)`
    - `render_prompt_context(self, *, max_lines: int=18)`
  - `MemoryPacketBuilder`
    - `from_retrieval_result(self, result: MemoryRetrievalResult, *, token_budget: int=900)`
    - `fit_budget(self, packet: MemoryPacket, *, token_budget: int)`
    - `_confidence_notes(self, packet: MemoryPacket)`

## `memory/memory_pruner.py`
- LOC: 122
- Functions:
  - `_metadata(item: Any)`
  - `_float(value: Any, default: float)`
  - `_epoch(value: Any)`
  - `_surface_text(item: Any)`
  - `_looks_like_trivial_semantic_noise(surface: str, semantic_source: str)`
- Classes:
  - `PruneDecision` (decorator=dataclass(frozen=True, slots=True))
  - `MemoryPruner` — Pruner dựa trên retention metadata nếu có.
    - `decide(self, item: Any, *, now: float | None=None)`

## `memory/memory_query_compiler.py`
- LOC: 346
- Functions:
  - `_best_or(scores: dict, default)`
- Classes:
  - `CompileDebug` (decorator=dataclass(slots=True))
  - `MemoryQueryCompileResult` (decorator=dataclass(slots=True))
    - `has_query(self)`
  - `MemoryQueryCompiler` — Blend slot + semantic + repair + optional LLM parser thành IR.
    - `__init__(self, *, slot_parser: Optional[MemoryQuerySlotParser]=None, semantic_engine: Optional[MemoryQuerySemanticHintEngine]=None, llm_parser: Optional[MemoryQueryLLMParser]=None, repair_store: Optional[MemoryQueryRepairStore]=None)`
    - `compile(self, text: str)`
    - `_inject_semantic_hypotheses(self, text: str, hypotheses: list[QueryHypothesis], hint: SemanticQueryHint)` — Nếu slot parser không sinh được gì, semantic hint có thể sinh hypothesis mềm.
    - `_apply_semantic_scores(self, hypotheses: list[QueryHypothesis], hint: SemanticQueryHint)`
    - `_top_margin(self, hypotheses: list[QueryHypothesis])`
    - `_ambiguity(self, hypotheses: list[QueryHypothesis], hint: SemanticQueryHint)`
    - `_suppression_note(self, hypotheses: list[QueryHypothesis], hint: SemanticQueryHint, ambiguity: float)`

## `memory/memory_query_executor.py`
- LOC: 366
- Functions:
  - `_unwrap_fact_value(value: Any)`
  - `_looks_like_internal_memory_object(value: Any)`
  - `_looks_like_internal_memory_surface(text: str)`
  - `_deep_get(data: dict, fact_key: str)`
- Classes:
  - `MemoryQueryExecutor` — Thực thi IR trên graph và memory_core.
    - `execute(self, ir: MemoryQueryIR, *, turn_graph: Optional[TurnGraph]=None, memory_core: Any=None)`
    - `_execute_turn_recall(self, ir: MemoryQueryIR, graph: TurnGraph)`
    - `_execute_fact_recall(self, ir: MemoryQueryIR, *, memory_core: Any, turn_graph: Optional[TurnGraph])`
    - `_lookup_fact(self, memory_core: Any, fact_key: str)`
    - `_format_fact(self, fact_key: str, value: Any)`
    - `_execute_summary(self, ir: MemoryQueryIR, graph: TurnGraph)`

## `memory/memory_query_ir.py`
- LOC: 368
- Functions:
  - `clamp01(value: float)`
  - `blend_confidence(*values: float, default: float=0.0)` — Trung bình mềm cho các confidence hợp lệ.
  - `add_warning(ir: MemoryQueryIR, warning: str)`
- Classes:
  - `QueryIntent` (base=str, Enum) — Loại truy vấn ký ức ở cấp cao.
  - `RoleRef` (base=str, Enum) — Role mà query đang trỏ tới.
  - `ActRef` (base=str, Enum) — Hành vi hội thoại mà query cần lấy.
  - `RelationRef` (base=str, Enum) — Quan hệ giữa target và anchor.
  - `SurfaceMode` (base=str, Enum) — Cách được phép surface câu trả lời ra public.
  - `MemorySourceKind` (base=str, Enum) — Nguồn ký ức mà executor dùng để trả.
  - `MemorySelector` (decorator=dataclass(slots=True)) — Bộ chọn node/fact trong memory.
    - `is_empty(self)`
    - `compact(self)`
  - `MemoryRelation` (decorator=dataclass(slots=True)) — Quan hệ query giữa target và anchor.
    - `compact(self)`
  - `MemoryQueryIR` (decorator=dataclass(slots=True)) — AST truy vấn ký ức.
    - `normalized(self)` — Trả bản sao với confidence/ambiguity được kẹp vào [0, 1].
    - `signature(self)` — Chữ ký cấu trúc để repair prior so khớp.
    - `compact(self)`
  - `QueryHypothesis` (decorator=dataclass(slots=True)) — Một giả thuyết query trong quá trình compile.
    - `normalized(self)`
  - `RawRecallResult` (decorator=dataclass(slots=True)) — Kết quả thô sau khi executor chạy query.
    - `missing(cls, ir: MemoryQueryIR, warning: str, source: MemorySourceKind=MemorySourceKind.NONE)`
  - `RecallAnswer` (decorator=dataclass(slots=True)) — Câu trả lời đã được policy surface.
    - `uncertain(cls, text: str='Tôi chưa đủ chắc để lần lại ký ức đó.', *, ir: Optional[MemoryQueryIR]=None, debug_trace: str='recall_uncertain')`

## `memory/memory_query_llm_parser.py`
- LOC: 214
- Functions:
  - `_enum(enum_cls, value: Any, default)`
  - `_int_or_none(value: Any)`
- Classes:
  - `MemoryQueryLLMClient` (base=Protocol) — Client tối thiểu cần có.
    - `complete_json(self, *, system: str, user: str, schema: dict[str, Any])`
  - `LLMParseDecision` (decorator=dataclass(slots=True))
  - `MemoryQueryLLMParser` — Parser LLM có schema, chỉ dùng khi compiler cần.
    - `__init__(self, client: Optional[MemoryQueryLLMClient]=None, *, ambiguity_threshold: float=0.35, close_margin_threshold: float=0.08)`
    - `should_use_llm(self, *, ambiguity: float, top_margin: float, has_nested_relation: bool)`
    - `parse(self, text: str)`
    - `build_system_prompt(self)`
    - `schema(self)`
    - `_parse_json(self, raw: str)`
    - `_dict_to_ir(self, data: dict[str, Any], *, raw_text: str)`
    - `_selector(self, data: dict[str, Any])`

## `memory/memory_query_repair.py`
- LOC: 276
- Functions:
  - `_ir_to_dict(ir: MemoryQueryIR)`
  - `_selector_to_dict(sel)`
  - `_ir_from_dict(data: dict)`
  - `normalize_vi(text: str)`
  - `text_similarity(a: str, b: str)`
- Classes:
  - `MemoryQueryRepairItem` (decorator=dataclass(slots=True))
  - `RepairPriorResult` (decorator=dataclass(slots=True))
  - `MemoryQueryRepairStore` — Store nhỏ cho repair query.
    - `__init__(self, items: Optional[Iterable[MemoryQueryRepairItem]]=None)`
    - `record(self, *, failed_user_text: str, correction_text: str, failed_ir: MemoryQueryIR, corrected_ir: MemoryQueryIR, confidence: float=0.85)`
    - `apply_prior(self, *, user_text: str, hypotheses: Iterable[QueryHypothesis])`
    - `save_json(self, path: str | Path)`
    - `load_json(cls, path: str | Path)`

## `memory/memory_query_semantics.py`
- LOC: 351
- Functions:
  - `normalize_vi(text: str)`
  - `_token_similarity(a: str, b: str)`
  - `cosine(a: Sequence[float], b: Sequence[float])`
  - `_ambiguity(scores)`
  - `_top(scores: dict)`
- Classes:
  - `EmbeddingProvider` (base=Protocol) — Provider embedding tùy chọn. Không bắt buộc.
    - `embed(self, text: str)`
  - `SemanticQueryHint` (decorator=dataclass(slots=True)) — Gợi ý semantic, không phải query cuối.
    - `top_intent(self)`
    - `top_fact_key(self)`
  - `MemoryQuerySemanticHintEngine` — Prototype semantic scorer.
    - `__init__(self, embedding_provider: EmbeddingProvider | None=None, *, fallback_confidence_cap: float=0.72)`
    - `analyze(self, text: str)`
    - `_fallback_hint(self, norm: str)`
    - `_embedding_hint(self, norm: str)`
    - `_score_enum_prototypes(self, text_vec, bank, enum_cls)`
    - `_score_string_prototypes(self, text_vec, bank)`
    - `_prototype_cosine(self, text_vec: Sequence[float], phrase: str)`

## `memory/memory_query_slot_parser.py`
- LOC: 670
- Functions:
  - `infer_target_role(norm: str)`
  - `infer_target_act(norm: str)`
  - `infer_anchor(norm: str)`
  - `infer_relation(norm: str)`
  - `infer_fact_key(norm: str)`
  - `infer_self_disclosure_fact(norm: str)`
  - `asks_count(norm: str)`
  - `asks_summary(norm: str)`
  - `asks_exact(norm: str)`
  - `looks_recent(norm: str)`
  - `looks_like_generic_recall_request(norm: str)`
  - `extract_quantity(norm: str)`
  - `extract_ordinal(norm: str)`
  - `extract_semantic_anchor(norm: str)`
  - `_signal_value(signals: list[SlotSignal], name: str)`
  - `normalize_vi(text: str)`
  - `parse_vi_number(value: str)`
  - `_looks_like_name_disclosure(norm: str)`
  - `user_is_declaring_or_updating_fact(text: str)`
  - `_looks_like_fact_update_disclosure(norm: str)`
  - `_looks_like_fact_update_question(norm: str, *, raw: str)`
  - `_looks_like_birth_month_disclosure(norm: str)`
  - `_looks_like_hometown_disclosure(norm: str)`
  - `_looks_like_living_location_disclosure(norm: str)`
  - `_looks_like_location_preference_disclosure(norm: str)`
  - `_looks_like_current_location_disclosure(norm: str)`
  - `_looks_like_past_location_disclosure(norm: str)`
- Classes:
  - `SlotSignal` (decorator=dataclass(slots=True)) — Một tín hiệu slot rút từ text.
  - `SlotParseResult` (decorator=dataclass(slots=True)) — Kết quả parse slot.
    - `has_self_disclosure(self)`
  - `MemoryQuerySlotParser` — Parser slot nhẹ.
    - `parse(self, text: str)`
    - `_extract_signals(self, raw: str, norm: str)`
    - `_build_hypotheses(self, raw: str, norm: str, signals: list[SlotSignal])`
    - `_target_from_signals(self, signals: list[SlotSignal], *, default_role: RoleRef=RoleRef.ANY, default_act: ActRef=ActRef.ANY)`
    - `_confidence(self, signals: list[SlotSignal], *, base: float)`

## `memory/memory_recall_policy.py`
- LOC: 247
- Classes:
  - `RecallPolicyConfig` (decorator=dataclass(slots=True))
  - `MemoryRecallSurfacePolicy` — Policy surface kết quả recall thành câu public.
    - `__init__(self, config: RecallPolicyConfig | None=None)`
    - `surface(self, result: RawRecallResult)`
    - `_exact_text(self, result: RawRecallResult, text: str)`
    - `_count_text(self, result: RawRecallResult)`
    - `_missing_text(self, result: RawRecallResult)`
    - `_trace(self, result: RawRecallResult)`
    - `_safe_public_text(self, text: str | None)`
    - `_looks_like_raw_object_surface(self, text: str)`

## `memory/memory_record.py`
- LOC: 413
- Functions:
  - `compact_text(value: Any, *, limit: int=420)` — Nén text để memory packet không kéo prompt thành bãi rác token.
  - `clamp01(value: Any)` — Ép số về [0, 1].
  - `stable_hash(text: str, length: int=16)`
  - `normalize_text(text: Any)` — Chuẩn hóa text để match ổn hơn.
  - `tokenize(text: Any)` — Token hóa có lọc stopword.
  - `token_bigrams(tokens: tuple[str, ...])`
  - `weighted_counter(tokens: tuple[str, ...])` — Counter có trọng số cho anchor kỹ thuật.
  - `weighted_jaccard(left: Counter[str], right: Counter[str])`
  - `phrase_score(query_norm: str, text_norm: str)` — Phrase match đủ dài, không tính token đơn như chân lý.
  - `extract_anchors(text: Any)` — Rút anchor mạnh: file, module, symbol, failure tags.
  - `parse_timestamp(value: Any)` — Parse timestamp best-effort.
  - `recency_score(timestamp: Any, *, now: float | None=None, half_life_hours: float=168.0)`
  - `record_from_layer_item(layer: str, item: Any)` — Adapter mềm từ store item cũ sang MemoryRecord.
  - `_default_surface_policy(layer: str)`
- Classes:
  - `MemoryRecord` (decorator=dataclass(slots=True)) — Record thống nhất cho mọi memory layer.
    - `normalized_text(self)`
    - `tokens(self)`
    - `anchor_set(self)`
    - `recall_line(self, *, limit: int=280)`
    - `to_dict(self)`

## `memory/memory_retention_policy.py`
- LOC: 133
- Functions:
  - `retention_metadata(decision: RetentionDecision)`
- Classes:
  - `RetentionDecision` (decorator=dataclass(frozen=True, slots=True))
  - `MemoryRetentionPolicy` — Policy retention cho SemanticClaim.
    - `decide(self, claim: SemanticClaim, worthiness: WorthinessDecision | None=None)`

## `memory/memory_retrieval_engine.py`
- LOC: 92
- Classes:
  - `MemoryStores` (decorator=dataclass(slots=True))
    - `as_layer_map(self)`
  - `MemoryRetrievalEngine`
    - `__init__(self, stores: MemoryStores, *, scorer: MemoryScorer | None=None, activation_builder: MemoryActivationBuilder | None=None)`
    - `retrieve(self, cue: MemoryCue, *, quotas: Mapping[str, int] | None=None, max_activations: int=10)`

## `memory/memory_scoring.py`
- LOC: 338
- Classes:
  - `LayerProfile` (decorator=dataclass(frozen=True, slots=True))
  - `MemoryScore` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `MemoryScorer`
    - `__init__(self, profiles: dict[str, LayerProfile] | None=None)`
    - `score(self, cue: MemoryCue, candidate: MemoryCandidate)`
    - `_privacy_penalty(self, cue: MemoryCue, record: Any)`
    - `_risk_penalty(self, cue: MemoryCue, candidate: MemoryCandidate)`

## `memory/memory_turn_annotator.py`
- LOC: 406
- Functions:
  - `normalize_vi(text: str)`
  - `parse_vietnamese_number(text: str)`
- Classes:
  - `TurnAnnotation` (decorator=dataclass(slots=True))
  - `TurnAnnotator` — Annotator nhẹ, đủ tốt để build TurnGraph trước khi semantic layer sâu hơn.
    - `annotate(self, *, role: TurnRole, text: str, metadata: Optional[dict[str, Any]]=None, previous_user_turn: Optional[TurnNode]=None)`
    - `build_edges(self, graph: TurnGraph)` — Dựng các cạnh ANSWERS/CORRECTS/REPEATS/STORES_FACT sau khi có nodes.
    - `_find_recent_correctable(self, graph: TurnGraph, before_index: int)`
    - `extract_fact_mentions(self, *, role: TurnRole, text: str)`
    - `_looks_like_question(self, raw: str, norm: str)`
    - `_looks_like_correction(self, norm: str)`
    - `_looks_like_command(self, norm: str)`
    - `_is_service_fallback(self, norm: str, metadata: dict[str, Any])`

## `memory/memory_turn_graph.py`
- LOC: 434
- Functions:
  - `_get(obj: Any, key: str, default: Any=None)`
  - `_role_from_any(value: Any)`
  - `_role_ref_to_turn(role: RoleRef)`
  - `_act_ref_to_turn(act: ActRef)`
  - `_norm(text: str)`
  - `_text_relevance(hint: str, text: str, tags: tuple[str, ...])` — Relevance lexical nhẹ cho semantic_hint. Không dùng cho ordinal.
- Classes:
  - `TurnRole` (base=str, Enum)
  - `TurnSpeechAct` (base=str, Enum)
  - `TurnEdgeType` (base=str, Enum)
  - `FactMention` (decorator=dataclass(slots=True)) — Fact được phát hiện trong turn, ví dụ user.birth_month=8.
  - `TurnNode` (decorator=dataclass(slots=True)) — Node hội thoại.
    - `counts_as_answer(self)` — Fallback/service-error không nên bị tính là câu trả lời nội dung.
    - `is_question(self)`
  - `TurnEdge` (decorator=dataclass(slots=True)) — Cạnh quan hệ giữa hai turn.
  - `TurnGraph` — Graph phiên hiện tại.
    - `__init__(self)`
    - `add_turn(self, node: TurnNode)`
    - `add_edge(self, edge: TurnEdge)`
    - `get(self, node_id: str)`
    - `from_turns(cls, turns: Iterable[TurnNode])`
    - `from_session_ledger(cls, session_ledger: Any, *, annotator: Optional[Any]=None)` — Adapter mềm từ session_turn_ledger hiện tại.
    - `infer_basic_answer_edges(self)` — Nối assistant answer với user question gần nhất trước đó.
    - `select(self, selector: MemorySelector)` — Chọn nodes theo MemorySelector. Không hiểu raw text user query.
    - `first_assistant_answer_to(self, user_question_id: str)` — Lấy assistant node có edge ANSWERS -> user_question_id.
    - `neighbor_after(self, node_id: str, selector: MemorySelector)`
    - `neighbor_before(self, node_id: str, selector: MemorySelector)`
    - `count(self, selector: MemorySelector)`
    - `last_n(self, selector: MemorySelector, n: int)`

## `memory/memory_worthiness.py`
- LOC: 134
- Classes:
  - `WorthinessDecision` (decorator=dataclass(frozen=True, slots=True))
  - `MemoryWorthinessPolicy` — Policy chặn ghi nhớ bừa trước khi retention tính decay.
    - `decide(self, claim: SemanticClaim)`

## `memory/persistence.py`
- LOC: 339
- Functions:
  - `time_safe_suffix()` — Timestamp dùng được trong tên file backup.
  - `load_memory_bundle(path: str | Path)` — Helper ngắn cho code không muốn giữ instance persistence.
  - `save_memory_bundle(path: str | Path, bundle: MemoryStateBundle)` — Helper ngắn để ghi bundle.
  - `update_memory_bundle(path: str | Path, mutator: Callable[[MemoryStateBundle], MemoryStateBundle | None])` — Helper ngắn cho thao tác load-mutate-save.
- Classes:
  - `MemoryPersistenceConfig` (decorator=dataclass(frozen=True)) — Cấu hình đọc/ghi memory JSON.
    - `resolved_path(self)` — Trả path đã expand user/env.
  - `MemoryPersistenceError` (base=RuntimeError) — Lỗi persistence có ngữ cảnh rõ ràng hơn JSONDecodeError trần trụi.
  - `JsonMemoryPersistence` — Lớp persistence chính cho MemoryStateBundle.
    - `__init__(self, config: MemoryPersistenceConfig | str | Path)`
    - `load_bundle(self)` — Load toàn bộ memory bundle. File chưa tồn tại thì trả bundle rỗng.
    - `save_bundle(self, bundle: MemoryStateBundle)` — Ghi toàn bộ bundle xuống disk bằng atomic write.
    - `update_bundle(self, mutator: Callable[[MemoryStateBundle], MemoryStateBundle | None])` — Load -> mutate -> save trong cùng một lock.
    - `append_to_collection(self, collection_name: str, record: Any)` — Append một record vào collection trong bundle rồi lưu.
    - `replace_collection(self, collection_name: str, records: tuple[Any, ...] | list[Any])` — Thay toàn bộ một collection. Dùng cho compaction/decay.
    - `set_active_state(self, snapshot: ActiveStateSnapshot | Mapping[str, Any])` — Overwrite active_state snapshot.
    - `append_commit_audit(self, decision: CommitDecision | Mapping[str, Any])` — Append audit decision để debug vì sao memory được lưu/bị bỏ.
    - `compact(self, *, limits: Mapping[str, int])` — Cắt bớt collection theo giới hạn giữ lại gần nhất.
    - `load_raw(self)` — Load dict JSON thô. File chưa tồn tại thì trả dict rỗng.
    - `save_raw(self, data: Mapping[str, Any])` — Ghi dict JSON thô bằng atomic write.
    - `exists(self)`
    - `backup_now(self, suffix: str | None=None)` — Tạo backup thủ công và trả path backup.
    - `_atomic_write_text(self, text: str)`
    - `_rotate_backups(self)` — Giữ một vòng backup đơn giản: file.bak1, file.bak2, ...
    - `_migrate_raw(self, raw: Mapping[str, Any])` — Migration rất nhẹ cho schema cũ/thiếu field.

## `memory/predicate_ontology.py`
- LOC: 393
- Functions:
  - `get_predicate(name: str)`
  - `fact_key_for_predicate(predicate: str)`
  - `predicate_for_fact_key(fact_key: str)`
  - `predicate_aliases(predicate: str)`
  - `entailment_for_target(claim: SemanticClaim, target: str)` — Claim có được dùng để trả lời answer target không?
  - `contradicts(a: SemanticClaim, b: SemanticClaim)` — Mâu thuẫn rõ khi cùng subject + predicate contradicts + object khác.
  - `is_long_term_predicate(predicate: str)`
  - `storage_layer_for_predicate(predicate: str)`
  - `default_decay_for_predicate(predicate: str)`
  - `importance_for_predicate(predicate: str)`
  - `_compatible_targets(predicates: Iterable[str])`
  - `_norm(text: str)`
- Classes:
  - `EntailmentType` (base=str, Enum)
  - `PredicateSpec` (decorator=dataclass(frozen=True, slots=True))

## `memory/procedural_memory.py`
- LOC: 200
- Docstring: Procedural Memory: cách xử lý đã học.
- Functions:
  - `iso_now()`
  - `compact_text(value: Any, *, limit: int=360)`
  - `clamp01(value: float)`
  - `key_for(trigger: str, rule: str)`
  - `atomic_write_json(path: str, payload: Any)`
- Classes:
  - `ProceduralMemoryItem` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data: dict[str, Any])`
    - `recall_line(self)`
  - `ProceduralMemoryStore`
    - `__init__(self, path: str, *, max_items: int=160)`
    - `load(self)`
    - `save(self, items: list[ProceduralMemoryItem])`
    - `apply_commit(self, request: Any)`
    - `recall(self, query: str='', *, limit: int=6)`
    - `_infer_trigger(self, rule: str, reason: str)`
    - `_default_items(self)`
    - `_merge_defaults(self, items: list[ProceduralMemoryItem])`

## `memory/query_intent.py`
- LOC: 212
- Functions:
  - `compile_semantic_query(text: str, *, structured: Mapping[str, Any] | None=None, allow_fallback: bool=False)`
  - `normalize_vi(text: str)` — Alias cũ cho code đang import normalize_vi từ query_intent.
  - `_clamp01(value: Any)`
- Classes:
  - `SemanticQueryIntent` (decorator=dataclass(frozen=True, slots=True))
    - `is_known(self)`
  - `QueryTargetFrame` (decorator=dataclass(frozen=True, slots=True)) — Một target câu hỏi ở mức ontology.
  - `QueryIntentParserProtocol`
    - `parse(self, text: str)`
  - `SemanticQueryIntentCompiler` (decorator=dataclass(slots=True)) — Compiler query có hook cho model parser.
    - `compile(self, text: str, *, structured: Mapping[str, Any] | None=None)`
    - `_from_structured(self, raw: str, data: Mapping[str, Any])`
    - `_fallback_compile(self, raw: str)`
    - `_score(self, norm: str, frame: QueryTargetFrame)`

## `memory/relational_memory.py`
- LOC: 201
- Docstring: Relational Memory: nhịp quan hệ, rupture, repair, khoảng cách.
- Functions:
  - `iso_now()`
  - `compact_text(value: Any, *, limit: int=360)`
  - `clamp01(value: float)`
  - `atomic_write_json(path: str, payload: Any)`
- Classes:
  - `RelationalMemoryItem` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data: dict[str, Any])`
    - `recall_line(self)`
  - `RelationalMemoryStore`
    - `__init__(self, path: str, *, max_items: int=120)`
    - `load(self)`
    - `save(self, items: list[RelationalMemoryItem])`
    - `apply_commit(self, request: Any)`
    - `recall(self, query: str='', *, limit: int=6)`
    - `_infer_pattern(self, claim: str, reason: str)`
    - `_trust_delta(self, pattern: str)`
    - `_distance_delta(self, pattern: str)`

## `memory/repair_memory.py`
- LOC: 247
- Docstring: Repair Memory: ghi lỗi, sửa sai, suppression rule tương lai.
- Functions:
  - `iso_now()`
  - `compact_text(value: Any, *, limit: int=420)`
  - `clamp01(value: float)`
  - `atomic_write_json(path: str, payload: Any)`
- Classes:
  - `RepairMemoryItem` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data: dict[str, Any])`
    - `recall_line(self)`
  - `RepairMemoryStore`
    - `__init__(self, path: str, *, max_items: int=160)`
    - `load(self)`
    - `save(self, items: list[RepairMemoryItem])`
    - `apply_commit(self, request: Any)`
    - `recall(self, query: str='', *, limit: int=6)`
    - `_extract_field(self, text: str, field_name: str)`
    - `_infer_failure_type(self, content: str, reason: str)`
    - `_guess_wrong_assumption(self, content: str, reason: str)`
    - `_default_strategy(self, failure_type: FailureType)`
    - `_default_suppression_rule(self, failure_type: FailureType)`

## `memory/schemas.py`
- LOC: 489
- Functions:
  - `now_iso()` — Trả timestamp ISO đơn giản, có timezone local.
  - `make_memory_id(prefix: str)` — Tạo id ngắn nhưng đủ ổn định cho record memory.
  - `clamp01(value: Any, *, default: float=0.0)` — Ép một giá trị về khoảng [0, 1]. Dữ liệu memory không cần drama số học.
  - `_tuple_str(value: Any)` — Chuẩn hóa list/tuple/set/string về tuple[str, ...].
  - `_dict_value(value: Any)` — Chuẩn hóa một object mapping thành dict thường.
  - `coerce_dataclass(cls: type[Any], value: Any)` — Ép dict/dataclass/object về dataclass cls, bỏ qua field lạ.
  - `_coerce_record_tuple(value: Any, cls: type[Any])`
  - `to_plain_data(value: Any)` — Chuyển dataclass/enum/tuple thành dữ liệu JSON-friendly.
  - `bundle_from_mapping(data: Mapping[str, Any] | None)` — Tạo MemoryStateBundle từ dict thô đã load từ JSON.
  - `bundle_to_mapping(bundle: MemoryStateBundle)` — Chuyển MemoryStateBundle về dict JSON-friendly.
- Classes:
  - `MemoryTarget` (base=str, Enum) — Các đích commit mà MemoryCognitionCore có thể route tới.
  - `DecayPolicy` (base=str, Enum) — Chính sách mục rữa của memory.
  - `PrivacyLevel` (base=str, Enum) — Mức riêng tư của evidence/memory.
  - `MemoryStatus` (base=str, Enum) — Trạng thái sống của một record memory.
  - `CommitOutcome` (base=str, Enum) — Kết quả xử lý một StateCommitRequest.
  - `CommitDecision` (decorator=dataclass) — Audit result sau khi StateCommitter/MemoryCognitionCore xử lý một request.
    - `__post_init__(self)`
  - `MemoryRecordBase` (decorator=dataclass) — Base record cho các memory đã qua commit protocol.
    - `__post_init__(self)`
    - `mark_tentative(self, reason: str='')` — Đánh dấu record là tentative, thường dùng khi confidence thấp nhưng chưa đáng bỏ.
    - `touch(self, *, confidence: float | None=None, evidence_ids: tuple[str, ...] | None=None)` — Cập nhật timestamp và có thể merge confidence/evidence.
  - `EventLedgerEntry` (decorator=dataclass) — Sự kiện thô hoặc gần-thô. Ledger là append-only, không rewrite quá khứ.
    - `__post_init__(self)`
  - `ActiveStateSnapshot` (decorator=dataclass) — Snapshot overwrite cho trạng thái đang là của runtime.
    - `__post_init__(self)`
  - `EpisodicMemoryRecord` (decorator=dataclass; base=MemoryRecordBase) — Memory về một chuyện cụ thể đã xảy ra.
    - `__post_init__(self)`
  - `SemanticMemoryRecord` (decorator=dataclass; base=MemoryRecordBase) — Fact ổn định hoặc gần ổn định. Nếu chưa chắc, status phải là tentative.
    - `__post_init__(self)`
  - `RelationalMemoryRecord` (decorator=dataclass; base=MemoryRecordBase) — Pattern quan hệ/tương tác tích tụ qua nhiều turn.
    - `__post_init__(self)`
  - `AffectiveResidueRecord` (decorator=dataclass; base=MemoryRecordBase) — Dư âm cảm xúc như pressure nội bộ, không phải lời tuyên bố cảm xúc công khai.
    - `__post_init__(self)`
  - `ProceduralMemoryRecord` (decorator=dataclass; base=MemoryRecordBase) — Luật xử lý đã học: gặp trigger X thì nên xử lý bằng cách Y.
    - `__post_init__(self)`
  - `RepairMemoryRecord` (decorator=dataclass; base=MemoryRecordBase) — Memory sửa lỗi: user correction, wrong assumption, suppression rule lần sau.
  - `MemoryPacket` (decorator=dataclass) — Gói recall đã được cắt budget để downstream dùng, thay vì nhét cả database vào prompt.
    - `__post_init__(self)`
  - `MemoryStateBundle` (decorator=dataclass) — Một bundle JSON đầy đủ cho persistence.
    - `__post_init__(self)`
    - `with_updated_timestamp(self)` — Cập nhật timestamp in-place rồi trả chính bundle để tiện chain.

## `memory/semantic_answer_policy.py`
- LOC: 114
- Classes:
  - `SemanticAnswer` (decorator=dataclass(frozen=True, slots=True))
  - `SemanticAnswerPolicy` — Chọn claim exact và format câu trả lời ngắn, grounded.
    - `__init__(self)`
    - `answer(self, query: str | SemanticQueryIntent, memory_items: Iterable[Any])`
    - `_missing_text(self, intent: SemanticQueryIntent)`
    - `_format(self, intent: SemanticQueryIntent, claim: SemanticClaim)`

## `memory/semantic_claim.py`
- LOC: 290
- Functions:
  - `make_claim_id(seed: Any)` — Sinh id ổn định theo nội dung claim.
  - `build_claim(*, subject: str, predicate: str, object_text: str, object_value: Any=None, object_type: str='unknown', assertion: Assertion='asserted', modality: Modality='fact', temporal: Temporal='unknown', scope: Scope='self', source: SourceKind='user_text', confidence: float=0.0, evidence_text: str='', evidence_ids: tuple[str, ...]=(), observed_at: float | None=None, valid_from: float | None=None, valid_until: float | None=None, stability: Literal['transient', 'session', 'medium', 'stable', 'unknown']='unknown', qualifiers: Mapping[str, Any] | None=None)`
  - `_clamp01(value: Any)`
  - `_coerce_literal(value: str, allowed: set[str], default: str)`
- Classes:
  - `SemanticClaim` (decorator=dataclass(frozen=True, slots=True)) — Một mệnh đề semantic đã chuẩn hóa.
    - `to_dict(self)`
    - `from_dict(cls, data: Mapping[str, Any])`
    - `qualifier_dict(self)`
    - `with_confidence(self, confidence: float)` — Trả bản sao với confidence mới.
  - `ExtractedClaim` (decorator=dataclass(frozen=True, slots=True)) — Kết quả extractor trả ra trước khi commit.
    - `to_dict(self)`

## `memory/semantic_memory.py`
- LOC: 1845
- Docstring: Semantic Memory: bộ nhớ fact đã được chưng cất cho ERIS.
- Functions:
  - `iso_now()` — Thời gian dạng ISO đơn giản, đủ ổn cho JSON memory local.
  - `_safe_epoch_from_iso(value: str)` — Parse timestamp best-effort.
  - `compact_text(value: Any, *, limit: int=360)` — Nén text thành một dòng ngắn để lưu vào memory.
  - `clamp01(value: Any, default: float=0.0)` — Ép giá trị về khoảng 0..1, tránh NaN/inf làm bẩn score.
  - `atomic_write_json(path: str, payload: Any)` — Ghi JSON an toàn hơn kiểu mở file rồi cầu nguyện.
  - `strip_accents(text: str)` — Bỏ dấu tiếng Việt để so khớp alias/fact_key ổn hơn.
  - `normalize_text(text: str, *, keep_underscore: bool=True)` — Normalize text cho search/fingerprint.
  - `dedupe_key(text: str)` — Key tương thích bản cũ.
  - `token_set(text: str)`
  - `char_ngrams(text: str, n: int=4)`
  - `word_ngrams(text: str, n: int=2)`
  - `jaccard(a: set[str], b: set[str])`
  - `sequence_ratio(a: str, b: str)`
  - `stable_hash(text: str)` — Hash ngắn để biết embedding_text đã đổi chưa.
  - `unique_keep_order(items: Iterable[str])`
  - `_mapping(value: Any)`
  - `_matches_any(normalized: str, patterns: Sequence[str])`
- Classes:
  - `SemanticRecallCue` (decorator=dataclass(slots=True)) — Cue truy xuất semantic memory.
    - `tokens(self)`
    - `embedding_query(self)` — Query đưa cho embedding index.
  - `SemanticRecallHit` (decorator=dataclass(slots=True)) — Kết quả recall có score và lý do.
    - `to_dict(self)`
    - `recall_line(self)`
  - `FactProfile` (decorator=dataclass(slots=True)) — Thông tin derive từ claim/request trước khi lưu.
  - `SemanticMemoryItem` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data: dict[str, Any])`
    - `fact_key(self)`
    - `aliases(self)`
    - `importance(self)`
    - `access_count(self)`
    - `last_accessed_at(self)`
    - `raw_user_text(self)`
    - `semantic_value(self)`
    - `recall_text_parts(self)`
    - `recall_line(self)`
  - `SemanticMemoryStore` — Store semantic fact dạng JSON, có typed recall và optional embedding hook.
    - `__init__(self, path: str, *, max_items: int=300, embedding_index: Any | None=None, min_recall_score: float=0.52)`
    - `load(self)`
    - `save(self, items: list[SemanticMemoryItem])` — Lưu memory sau khi prune/sort.
    - `_prune_items(self, items: list[SemanticMemoryItem])` — Prune memory yếu nếu vượt max_items.
    - `_sorted_items(self, items: list[SemanticMemoryItem])`
    - `_retention_score(self, item: SemanticMemoryItem)`
    - `apply_commit(self, request: Any)` — Áp một StateCommitRequest vào semantic memory.
    - `_find_merge_target(self, items: list[SemanticMemoryItem], *, claim: str, profile: FactProfile, confidence: float)` — Tìm item nên merge.
    - `_merge_item(self, item: SemanticMemoryItem, *, claim: str, confidence: float, evidence_ids: list[str], profile: FactProfile, reason: str, request_metadata: Mapping[str, Any], now: str)` — Merge claim mới vào item cũ.
    - `_is_current_fact_replacement(self, fact_key: str, *, old_value: str, new_value: str, confidence: float)`
    - `_claim_surface_quality(self, claim: str)` — Ước lượng claim nào đáng dùng làm surface chính.
    - `_detect_value_conflict(self, item: SemanticMemoryItem, *, new_claim: str, profile: FactProfile, request_metadata: Mapping[str, Any])` — Bắt mâu thuẫn rõ cho vài fact_key có value đơn giản.
    - `_extract_metadata_value(self, metadata: Mapping[str, Any], fact_key: str)`
    - `_extract_simple_value(self, claim: str, fact_key: str)`
    - `lookup_fact(self, fact_key: str)` — Return the current value for a stable fact_key.
    - `get_fact(self, fact_key: str)`
    - `semantic_lookup(self, fact_key: str)`
    - `_current_fact_rank(self, item: SemanticMemoryItem)`
    - `recall(self, query: str='', *, limit: int=8, min_score: float | None=None)` — Recall tương thích API cũ: trả list item.
    - `recall_hits(self, query: str='', *, limit: int=8, min_score: float | None=None)` — Recall có debug score.
    - `_embedding_candidates(self, cue: SemanticRecallCue, items: list[SemanticMemoryItem], *, limit: int)` — Lấy candidate từ embedding index nếu có.
    - `_score_recall_item(self, item: SemanticMemoryItem, cue: SemanticRecallCue, *, vector_score: float=0.0, vector_available: bool=False)`
    - `_normalize_vector_score(self, value: float)` — Normalize score vector về 0..1.
    - `_fact_key_score(self, item: SemanticMemoryItem, cue: SemanticRecallCue)`
    - `_domain_score(self, item: SemanticMemoryItem, cue: SemanticRecallCue)`
    - `_alias_score(self, item: SemanticMemoryItem, cue: SemanticRecallCue)`
    - `_lexical_similarity(self, item: SemanticMemoryItem, cue: SemanticRecallCue)`
    - `_recency_bonus(self, item: SemanticMemoryItem)`
    - `_record_access(self, item_ids: Sequence[str])` — Cập nhật access_count/last_accessed_at cho item được recall.
    - `parse_recall_cue(self, query: str)`
    - `_derive_fact_profile(self, claim: str, *, target: Any='', reason: str='', request_metadata: Mapping[str, Any] | None=None, request_tags: Sequence[str]=())` — Derive domain/fact_key/importance từ claim + request context.
    - `_domain_from_fact_key(self, fact_key: str)`
    - `_infer_domain(self, claim: str, target: Any)` — Infer domain nhẹ từ claim/target.
    - `_build_metadata(self, *, claim: str, profile: FactProfile, reason: str, request_metadata: Mapping[str, Any])`
    - `embedding_text_for_item(self, item: SemanticMemoryItem)` — Text đưa vào embedding index.
    - `_embedding_text_from_parts(self, *, claim: str, domain: SemanticDomain, fact_key: str, tags: Sequence[str], aliases: Sequence[str])`
    - `_claim_similarity(self, a: str, b: str)`
    - `rebuild_embedding_index(self)` — Yêu cầu embedding_index build/cache lại vector nếu backend hỗ trợ.

## `memory/semantic_text.py`
- LOC: 196
- Functions:
  - `normalize_vi(text: str)` — Chuẩn hóa tiếng Việt về dạng không dấu, chữ thường, khoảng trắng gọn.
  - `clean_surface_text(value: str)` — Dọn object surface nhưng không tự canonicalize quá tay.
  - `analyse_text(text: str)`
  - `split_clauses(norm_text: str)`
  - `looks_like_question(raw: str, norm: str | None=None)`
  - `looks_like_greeting_only(norm: str)`
  - `has_any(norm: str, *phrases: str)` — Phrase containment có boundary nhẹ.
  - `relation_regex(aliases: Iterable[str])` — Build regex cho relation aliases đã normalize.
  - `_has_interrogative_context(norm: str)`
  - `_surface_evidence(norm: str)`
- Classes:
  - `TextSemanticFrame` (decorator=dataclass(frozen=True, slots=True)) — Bản đọc bề mặt của một câu user.

## `memory/text_normalize_vi.py`
- LOC: 64
- Functions:
  - `strip_accents(text: str)` — Bỏ dấu tiếng Việt để match mềm, không phá text gốc dùng để trả lời.
  - `normalize_vi(text: str)` — Chuẩn hóa nhẹ cho phân loại intent/fact.
  - `compact_spaces(text: str)` — Giữ dấu nhưng dọn khoảng trắng.
  - `looks_like_question(text: str)` — Nhận diện câu hỏi theo nghĩa hội thoại Việt.
  - `visible_len(text: str)` — Độ dài phục vụ so sánh câu dài nhất, sau khi nén khoảng trắng.

## `memory/understanding/__init__.py`
- LOC: 15
- Docstring: Tầng đọc nghĩa trung gian cho memory intake.

## `memory/understanding/entity_linker.py`
- LOC: 113
- Functions:
  - `link_entity(value: Any, *, hinted_kind: str='unknown', metadata: Mapping[str, Any] | None=None)` — Link object surface thành EntityRef.
  - `clean_surface(value: Any, *, limit: int=180)`
  - `normalize(text: str)`
  - `strip_accents(text: str)`
  - `_looks_like_location(norm: str)`
  - `_looks_like_person_name(text: str)`

## `memory/understanding/meaning_frame.py`
- LOC: 191
- Functions:
  - `_coerce(value: str, allowed: set[str], default: str)`
  - `_clamp01(value: Any)`
- Classes:
  - `EntityRef` (decorator=dataclass(frozen=True, slots=True)) — Entity đã link nhẹ từ surface text.
    - `to_dict(self)`
    - `from_dict(cls, data: Mapping[str, Any])`
  - `MeaningFrame` (decorator=dataclass(frozen=True, slots=True)) — Khung nghĩa đã đọc từ một phát ngôn.
    - `is_assertive(self)`
    - `to_dict(self)`
    - `from_dict(cls, data: Mapping[str, Any])`
  - `MeaningParseResult` (decorator=dataclass(frozen=True, slots=True)) — Output của SemanticParser.
    - `to_dict(self)`

## `memory/understanding/polarity_temporal.py`
- LOC: 106
- Functions:
  - `analyse_surface(text: str)`
  - `_has_any(norm: str, phrases: tuple[str, ...])`
  - `split_clauses(text: str)` — Tách clause thô để parser xử lý từng mệnh đề nhỏ.
- Classes:
  - `SurfaceFeatures` (decorator=dataclass(frozen=True, slots=True))

## `memory/understanding/semantic_parser.py`
- LOC: 596
- Functions:
  - `structured_frames_to_result(text: str, payload: Mapping[str, Any] | list[Any] | None, *, source: str)` — Verify structured JSON thành MeaningFrame.
  - `_frame_from_mapping(item: Mapping[str, Any], *, fallback_evidence: str)`
  - `_claim_like_to_frame(item: Mapping[str, Any])`
  - `_parse_clause_as_frames(clause: str, surface: Any)` — Fallback detector tập trung.
  - `_mk_frame(frame_type: str, relation: str, value: str, kind: str, evidence: str, certainty: float, time_scope: str, modality: str, surface: Any, *, stability: str='stable', polarity: str | None=None)`
  - `_extract_after(norm: str, raw: str, cues: Iterable[tuple[str, str]])`
  - `_extract_identity_name(raw: str)` — Bắt các câu khai báo/correction tên ở tầng MeaningFrame.
  - `_extract_identity_nickname(raw: str)` — Bắt câu khai báo biệt danh/nickname ở tầng MeaningFrame.
  - `_extract_study_field(raw: str)` — Rút ngành/lĩnh vực học từ self-disclosure ngắn.
  - `_extract_year(norm: str)`
  - `_extract_preference(norm: str, raw: str)`
  - `_extract_after(raw: str, cues: Iterable[tuple[str, str]])`
  - `_extract_preference(norm: str, raw: str)`
  - `_normalized_with_offsets(text: str)`
  - `_has_self(norm: str)`
  - `_looks_like_style_instruction(norm: str)`
  - `_looks_like_feedback(norm: str)`
  - `_infer_frame_type(relation: str)`
  - `_clamp01(value: Any)`
- Classes:
  - `SemanticParser` (base=Protocol) — Protocol chung để runtime có thể thay fallback bằng model.gguf.
    - `parse(self, text: str, *, structured: Mapping[str, Any] | None=None)`
  - `ModelSemanticParser` (decorator=dataclass(slots=True)) — Adapter cho model/LLM parser bên ngoài.
    - `parse(self, text: str, *, structured: Mapping[str, Any] | None=None)`
  - `StructuredFrameParser` (decorator=dataclass(slots=True)) — Parser chỉ verify JSON structured đã có sẵn.
    - `parse(self, text: str, *, structured: Mapping[str, Any] | None=None)`
  - `FallbackSurfaceSemanticParser` (decorator=dataclass(slots=True)) — Fallback rất nhỏ khi chưa có model.gguf.
    - `parse(self, text: str, *, structured: Mapping[str, Any] | None=None)`

## `memory/unresolved_memory.py`
- LOC: 330
- Functions:
  - `iso_now()`
  - `compact_text(value: Any, *, limit: int=900)`
  - `clamp01(value: Any, default: float=0.0)`
  - `atomic_write_json(path: str, payload: Any)`
  - `fingerprint_text(text: str)`
  - `_as_list(value: Any)`
  - `_mapping(value: Any)`
- Classes:
  - `UnresolvedMemoryCandidate` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data: Mapping[str, Any])`
    - `fingerprint(self)`
    - `recall_line(self)`
  - `UnresolvedMemoryStore` — JSON store cho unresolved memory candidates.
    - `__init__(self, path: str, *, max_items: int=500)`
    - `load(self)`
    - `save(self, items: list[UnresolvedMemoryCandidate])`
    - `apply_commit(self, request: Any)`
    - `candidates_for_consolidation(self, *, limit: int=20, max_attempts: int=5)`
    - `mark_attempted(self, candidate_id: str, *, status: CandidateStatus='failed', reason: str='')`
    - `mark_promoted(self, candidate_id: str, *, target: str, fact_key: str='')`
    - `search(self, query: str='', *, limit: int=8, include_promoted: bool=False)`
    - `_find_existing(self, items: list[UnresolvedMemoryCandidate], candidate: UnresolvedMemoryCandidate)`
    - `_merge(self, old: UnresolvedMemoryCandidate, new: UnresolvedMemoryCandidate, *, now: str)`
    - `_prune(self, items: list[UnresolvedMemoryCandidate])`
    - `_sort_items(self, items: list[UnresolvedMemoryCandidate])`

## `parser_grounding/__init__.py`
- LOC: 4

## `parser_grounding/decision.py`
- LOC: 1975
- Classes:
  - `ParserGroundingMixin`
    - `_normalize_keyword_text(self, text: str)`
    - `_contains_keyword(self, text: str, keyword: str)`
    - `_contains_any_keyword(self, text: str, keywords)`
    - `_is_embodied_command_request(self, text: str)`
    - `_should_infer_embodied_animation(self, text: str, user_hint: str='')`
    - `_preview_raw_response(self, raw_text: str)`
    - `_normalize_debug_trace(self, value: str)`
    - `_build_parser_debug_trace(self, *, parse_mode: str, raw_text: str, reason: str, text: str='', animation: str='')`
    - `_collect_capability_violations(self, text: str)`
    - `_infer_animation_reason(self, final_animation: str, text: str, user_hint: str='')`
    - `_build_parser_trace_summary(self, *, parse_mode: str, original_text: str, final_text: str, final_animation: str, user_hint: str='', grounded_changed: bool=False)`
    - `_log(self, level: str, message: str)`
    - `_extract_first_json_object(self, text: str)`
    - `_extract_first_json_candidate(self, text: str)`
    - `_repair_json_candidate(self, text: str)`
    - `_patch_missing_decision_fields(self, payload: dict, *, parse_mode: str, user_hint: str='')`
    - `_finalize_loaded_json_payload(self, payload, *, parse_mode: str, user_hint: str='')`
    - `_try_parse_hard_json_repair(self, text: str, user_hint: str='')`
    - `_normalize_salvaged_text(self, text: str)`
    - `_repair_sentence_boundaries(self, text: str)`
    - `_normalize_decision_field_keys(self, value)`
    - `_coerce_bool(self, value, *, fallback: bool=True)`
    - `_coerce_confidence(self, value, *, fallback: float=0.0)`
    - `_coerce_reasoning_tags(self, value)`
    - `_action_field(self, action, *names, default=None)`
    - `_apply_cognition_action_defaults(self, data: dict, user_hint: str='')`
    - `_clean_inline_field_value(self, value: str)`
    - `_cut_inline_metadata_from_public_text(self, text: str)` — Remove leaked decision-schema tail from a public text field.
    - `_looks_like_prompt_or_contract_leak_text(self, text: str)`
    - `_looks_like_non_json_analysis_or_debug_text(self, text: str)`
    - `_non_json_semantic_fallback_payload(self, *, parse_mode: str, raw_text: str, reason: str)`
    - `_try_extract_inline_decision_fields_from_text(self, text: str)`
    - `_sanitize_direction(self, value)`
    - `_sanitize_target_x(self, value, *, fallback: float=-1.0)`
    - `_sanitize_motion_facing(self, value, *, fallback: int=0)`
    - `_try_extract_nested_decision_from_text(self, text: str)`
    - `_unwrap_structured_text_candidate(self, text: str)`
    - `_clean_nested_field_scalar(self, value)`
    - `_clean_nested_field_text(self, value)`
    - `_sanitize_motion_intent(self, value: str)`
    - `_sanitize_stage_token(self, value: object, *, allowed: set[str], aliases: dict[str, str] | None=None)` — Chuẩn hoá field sân khấu do LLM khai.
    - `_sanitize_delivery_hint(self, value: object)`
    - `_sanitize_nonverbal_cue(self, value: object)`
    - `_sanitize_stage_motion(self, value: object)`
    - `_infer_motion_intent(self, *, animation: str, next_animation: str, direction: int, target_x: float)`
    - `_sanitize_animation(self, value: str, fallback_text: str='', user_hint: str='')`
    - `_sanitize_system_action(self, value: str)`
    - `_is_strict_direction_value(self, value)`
    - `_is_strict_target_x_value(self, value)`
    - `_requires_lax_json_mode(self, payload: dict)`
    - `_get_runtime_capability_summary(self)`
    - `_split_into_claim_units(self, text: str)`
    - `_is_allowed_self_claim(self, clause: str)`
    - `_has_vision_frame_context(self, text: str)`
    - `_is_screen_observation_claim(self, clause: str, context: str='')`
    - `_clause_mentions_unsupported_target(self, clause: str)`
    - `_clause_has_strong_control_fantasy(self, clause: str)`
    - `_clause_exceeds_runtime_capability(self, clause: str, previous_unit: str='', context: str='')`
    - `_rewrite_excessive_clause(self, clause: str, user_hint: str='')`
    - `_ground_text_to_runtime_capabilities(self, text: str, user_hint: str='')`
    - `_has_contradictory_encouragement(self, text: str)`
    - `_has_philosophical_filler(self, text: str)`
    - `_has_overmanaged_style(self, text: str)`
    - `_build_grounded_text(self, user_hint: str='')`
    - `_is_speculative_extracted_fact(self, fact: str)`
    - `_finalize_decision(self, decision: dict, user_hint: str='')`
    - `_infer_structured_action(self, text: str, user_hint: str='')`
    - `_salvage_non_json_response(self, cleaned: str, user_hint: str='')`
    - `_extract_lax_field(self, text: str, field: str, known_fields)`
    - `_try_parse_lax_json(self, text: str, user_hint: str='')`
    - `_infer_animation_reason(self, final_animation: str, text: str, user_hint: str='')`
    - `_infer_animation_from_text(self, text: str)`
    - `_infer_structured_action(self, text: str, user_hint: str='')`
    - `parse_ai_json(self, raw_text: str, user_hint: str='')`
    - `_is_follow_up_question(self, user_message: str)`
    - `_build_chat_user_message(self, user_message: str)`

## `parser_grounding/service.py`
- LOC: 266
- Classes:
  - `DecisionParser` (base=ParserGroundingMixin)
    - `__init__(self, fallback: Decision, logger=None)`
    - `_is_climb_request(self, text: str)`
    - `_infer_look_direction(self, text: str)`
    - `_is_look_only_request(self, text: str)`
    - `_infer_move_direction(self, text: str)`
    - `_is_drop_from_climb_request(self, text: str)`
    - `_is_reverse_climb_request(self, text: str)`
    - `_is_climb_top_request(self, text: str)`
    - `_is_top_hold_request(self, text: str)`
    - `_infer_top_platform_target(self, text: str)`
    - `_infer_air_swing_from_text(self, text: str)`
    - `_infer_animation_from_text(self, text: str)`
    - `_infer_structured_action(self, text: str, user_hint: str='')`
    - `_is_embodied_command_request(self, text: str)`
    - `_should_suppress_salvaged_text(self, finalized: dict, user_hint: str)`
    - `_finalize_decision(self, decision: dict, user_hint: str='')`
    - `parse(self, raw_text: str, user_hint: str='')`
    - `build_chat_user_message(self, *, user_message: str, last_chat_answer: str)`

## `runtime/__init__.py`
- LOC: 23
- Docstring: Runtime package của ERIS.
- Functions:
  - `__getattr__(name: str)`

## `runtime/affect_self_read.py`
- LOC: 298
- Docstring: affect_self_read.py — ERIS tự đọc cảm xúc của chính mình (interoception).
- Functions:
  - `_clamp(value: float, lo: float=0.0, hi: float=1.0)`
  - `_g(obj: Any, name: str, default: float=0.0)`
  - `_env_flag(name: str, default: bool)`
  - `_env_int(name: str, default: int)`
  - `_env_float_ms(name: str, default_seconds: float)`
  - `_env_float(name: str, default: float)`
- Classes:
  - `AffectSelfReadConfig` (decorator=dataclass(slots=True, frozen=True))
    - `from_env(cls)`
  - `AffectSelfReadAdapter` (decorator=dataclass(slots=True)) — Dịch internal_state → 1 câu cảm giác ngôi-thứ-nhất qua gemma (style_client).
    - `render(self, state: Any, *, relationship: Any=None)` — Trả về 1 câu cảm giác (đã cache/throttle), hoặc "" nếu tắt/không có state.
    - `_bucket(value: float)`
    - `_signature(self, state: Any, rel: Any)`
    - `_gemma_line(self, state: Any, rel: Any)`
    - `_readings_text(self, state: Any, rel: Any)`
    - `_fallback_line(self, state: Any, rel: Any)`
    - `_extract(self, resp: Any)`
    - `_first_line(raw: str)`
    - `_clean(text: str)`
    - `_warn(self, fmt: str, *args: Any)`

## `runtime/ambient_silence_policy.py`
- LOC: 74
- Docstring: Shared ambient-silence / muse policy for the autonomous idle loop.
- Functions:
  - `muse_directive_active(ti_report)` — True when cognition granted self-initiated topic permission.
  - `ambient_silence_cooldown_seconds(snapshot, ti_report)` — Cooldown window (seconds) for ambient-silence pacing by mode/focus.
  - `should_hold_ambient_silence(*, snapshot, ti_report, last_text: str, last_autonomous_spoken_at: float, speech_intent: str='', now: float | None=None)` — Decide whether to hold this cycle for ambient pacing.

## `runtime/autonomous_cycle.py`
- LOC: 1259
- Classes:
  - `AutonomousCycleMixin`
    - `_choose_autonomous_sleep_duration(self, *, suppressed: bool, ti_mode: str)`
    - `_process_pending_user_input(self)`
    - `_run_loop_iteration(self)` — Run a single coordinator loop iteration.
    - `_load_autonomous_sleep_seconds(self, env_name: str, *, default: tuple[int, ...])`
    - `_bucket_idle_seconds(self, idle_seconds: float)`
    - `_bucket_window_spread(self, open_windows: tuple[str, ...], browser_tabs: tuple[str, ...])`
    - `_load_vision_fact_settings(self)`
    - `_note_vision_failure(self, stage: str, exc: Exception)`
    - `_is_low_value_screen_fact(self, fact: str)`
    - `_speech_evidence_score(self, text: str, *, kind: str='')`
    - `_is_speakable_evidence(self, text: str, *, kind: str='')`
    - `_sanitize_screen_facts(self, facts: list[str] | tuple[str, ...])`
    - `_maybe_update_screen_facts(self)`
    - `_attach_screen_facts(self, snapshot, facts: tuple[str, ...])`
    - `_build_autonomous_signature(self, snapshot, ti_report)`
    - `_track_autonomous_signature(self, snapshot, ti_report)`
    - `_should_suppress_autonomous_reply(self, *, ti_report, repeat_count: int, ni_report=None, ni_state_label: str='', repeated_topic_tag: str='', repeated_topic_streak: int=0)`
    - `_has_resource_pressure_signal(self, snapshot)`
    - `_is_generic_screen_event(self, event: str)`
    - `_is_generic_screen_evidence(self, evidence: str)`
    - `_concrete_screen_signals(self, snapshot)`
    - `_concrete_vision_signals(self, snapshot)`
    - `_concrete_telemetry_signals(self, snapshot)`
    - `_has_concrete_screen_signal(self, snapshot)`
    - `_broadcast_screen_winners(self, broadcast: CognitiveBroadcast | None)`
    - `_choose_autonomous_speech_intent(self, *, snapshot, ni_report, ti_report, repeat_count: int, attention_broadcast: CognitiveBroadcast | None=None, inner_thought: InnerThought | None=None, ni_state_label: str='', repeated_topic_tag: str='', repeated_topic_streak: int=0)`
    - `_ambient_silence_cooldown_seconds(self, snapshot, ti_report)`
    - `_should_hold_ambient_silence(self, *, snapshot, ti_report, speech_intent: str='', now: float | None=None)`
    - `_should_skip_weak_autonomous_speech(self, *, snapshot, speech_core: AgentSpeechCore, thought_stream_report, social_presence_event: SocialPresenceEvent | None, frame: CognitiveFrame)`
    - `_has_high_cognitive_momentum(self, thought_stream_report)`

## `runtime/autonomous_wake_governor.py`
- LOC: 261
- Docstring: src/runtime/autonomous_wake_governor.py
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
- Classes:
  - `WakeDecision` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `WakeGovernorConfig` (decorator=dataclass(slots=True))
  - `AutonomousWakeGovernor` — Trọng tài wake state.
    - `__init__(self, config: WakeGovernorConfig | None=None)`
    - `decide(self, *, user_context: RollingUserContext, internal_state: RollingInternalState, agenda_stack: InternalAgendaStack | None=None, budget_policy: ModelBudgetPolicy | None=None, resource_snapshot: ResourceSnapshot | None=None, autonomous_silent_cycles: int=0, now: float | None=None)`
    - `_budget(self, policy: ModelBudgetPolicy | None, tier: str, snapshot: ResourceSnapshot | None, reason: str)`

## `runtime/background_memory_digest.py`
- LOC: 59
- Functions:
  - `build_background_memory_digest_service(*, memory_kernel: MemoryKernel | None=None, semantic_parser: Any=None, state_committer_factory: Any=None, memory_core: Any | None=None, logger: Any | None=None, config: BackgroundMemoryDigestConfig | None=None, idle_probe: Any | None=None)` — Compat builder: ưu tiên MemoryKernel, bỏ qua hook commit cũ.

## `runtime/background_memory_digest_kernel.py`
- LOC: 465
- Functions:
  - `_env_flag(name: str, default: bool)`
  - `_env_int(name: str, default: int)`
  - `_env_float(name: str, default: float)`
- Classes:
  - `BackgroundMemoryDigestKernelConfig` (decorator=dataclass(frozen=True, slots=True)) — Config worker nền.
  - `MemoryDigestKernelJob` (decorator=dataclass(frozen=True, slots=True)) — Một job tiêu hóa memory nền.
  - `MemoryDigestKernelStats` (decorator=dataclass(slots=True)) — Stats nhỏ cho dev/debug.
    - `to_dict(self)`
  - `BackgroundMemoryDigestKernelService` — Thread worker nền cho MemoryKernel semantic digestion.
    - `__init__(self, memory_kernel: MemoryKernel, *, config: BackgroundMemoryDigestKernelConfig | None=None, logger: Any=None, idle_probe: Any=None)`
    - `start(self)` — Start worker nếu chưa chạy.
    - `stop(self, timeout: float=1.5)` — Stop worker nhẹ nhàng.
    - `mark_remote_inflight(self, value: bool)` — Runtime gọi True trước remote API, False sau khi nhận response.
    - `notify_remote_inflight(self, inflight: bool)` — Compat với service cũ.
    - `notify_user_input(self)` — Báo worker biết user vừa nhập, để tránh tranh tài nguyên ngay lập tức.
    - `enqueue(self, text: str, *, turn_id: str='', evidence_ids: list[str] | tuple[str, ...] | None=None, role: DigestRole='user', source: DigestSource='chat_turn', priority: DigestPriority='normal', context: Mapping[str, Any] | None=None)` — Đưa job vào queue. Trả False nếu queue đầy hoặc text rỗng.
    - `enqueue_user_turn(self, text: str, *, turn_id: str='', source: DigestSource='chat_turn', priority: DigestPriority='normal', context: Mapping[str, Any] | None=None)` — Compat với worker cũ: enqueue job user-turn và ghi nhận input mới.
    - `drain_once_for_tests(self)` — Chạy đồng bộ queue để test không cần thread nền.
    - `_run(self)`
    - `_gate_job(self, job: MemoryDigestKernelJob)`
    - `_runtime_idle_enough(self, now: float | None=None)`
    - `_requeue(self, job: MemoryDigestKernelJob)`
    - `_defer_job(self, job: MemoryDigestKernelJob, *, reason: str='')`
    - `_process(self, job: MemoryDigestKernelJob)`
    - `_maybe_run_idle_maintenance(self, *, reason: str)`
    - `_log(self, level: str, message: str, **kwargs: Any)`

## `runtime/banter_arbiter.py`
- LOC: 500
- Functions:
  - `_env_enabled()`
  - `_normalize_vi(text: str)`
  - `_has_any(normalized: str, markers: tuple[str, ...])`
  - `_text_of(value: Any)`
- Classes:
  - `BanterDecision` (decorator=dataclass(frozen=True, slots=True))
    - `changed(self)`
  - `CorrectionEvidence` (decorator=dataclass(frozen=True, slots=True)) — Bằng chứng rất nhỏ cho repair.
    - `is_real_correction(self)`
    - `is_challenge_only(self)`
  - `BanterArbiter` — Quyết định khi nào được sửa câu cuối thành một repair/aside có duyên.
    - `arbitrate(self, decision: Any, *, channel: str, user_text: str='', previous_text: str='', grounding: Any=None, frame: Any=None, speech_core: Any=None)`
    - `apply(self, decision: Any, banter: BanterDecision)`
    - `repair_correction(self, *, user_text: str, previous_text: str, grounding: Any=None, frame: Any=None, speech_core: Any=None)` — Sinh repair cho lượt user đang phủ định/sửa câu public trước.
    - `_grounding_from(self, frame: Any)`
    - `_evidence_blob(self, *, grounding: Any=None, frame: Any=None, speech_core: Any=None)`
    - `_looks_like_protocol_surface(self, normalized_text: str, decision: Any)`
    - `_assess_user_correction(self, normalized_user: str)`
    - `_user_corrected(self, normalized_user: str)`
    - `_has_screen_evidence(self, grounding: Any, evidence_blob: str)`
    - `_protocol_repair_text(self, *, normalized_user: str, previous_norm: str, evidence_blob: str)`
    - `_correction_repair_text(self, *, normalized_user: str, previous_norm: str, current_norm: str, evidence_blob: str, correction: CorrectionEvidence | None=None)`
    - `_needs_overread_challenge_repair(self, normalized_text: str)`
    - `_previous_text_invites_challenge_repair(self, previous_norm: str)`
    - `_overread_challenge_repair_text(self, *, normalized_user: str, previous_norm: str, current_norm: str)`
    - `_should_downgrade_media_mindread(self, normalized_text: str, evidence_blob: str)`
    - `_grounded_media_aside(self, evidence_blob: str)`
    - `_intent_for(self, mode: BanterMode, fallback: str)`

## `runtime/body_bias.py`
- LOC: 115
- Classes:
  - `BodyBiasProjector` — Projects cognitive state into the compact body-bias payload Godot consumes.
    - `__init__(self, state_provider: Callable[[], PersistentInternalState])`
    - `build_payload(self, observer_frame=None, impulse_hint: dict[str, object] | None=None)` — Build compact body-bias payload.
    - `clamp(value: object)`
    - `normalize_focus_kind(value: str)`

## `runtime/chat_cycle.py`
- LOC: 1826
- Classes:
  - `ChatCycleMixin`
    - `_enter_chat_cycle(self)`
    - `_end_chat_cycle(self)`
    - `_build_relational_voice_stance(self, user_text: str, *, frame, fe_plan, ti_report, conversation_report, relationship_report)` — Project the already-computed cognition reports into a CognitionStance.
    - `_build_relational_voice_seed_decision(self, user_text: str, *, frame, fe_plan, ti_report, conversation_report, relationship_report)`
    - `_run_chat_cycle(self, user_text: str, *, user_timestamp: float | None=None)`
    - `_run_chat_cycle_inner(self, user_text: str, *, cycle_start: float, previous_public_context: str='', previous_public_turn=None)`
    - `_recall_repair_suppression(self, user_text: str)` — Recall ký ức sửa lỗi quan hệ/tâm lý và rút ra tín hiệu siết cho lượt này.
    - `_build_chat_format_block_raw(self, exc: FormatViolationException, *, switched_api: bool=False)` — Block payload when every provider (gemma retries + Groq switch-API)
    - `_build_chat_format_repair_fallback_raw(self, exc: FormatViolationException)`
    - `_join_debug_trace(*parts: str)`
    - `_queue_chat_burst_event(self, user_text: str, timestamp: float | None=None)`
    - `_merge_rapid_chat_burst(self, first_text: str, *, first_timestamp: float)`
    - `_pop_queued_chat_events(self)`
    - `_poll_ready_chat_events(self)`
    - `_observe_previous_turn_feedback(self, user_text: str)` — Gắn feedback của user hiện tại vào frame trước nếu có.
    - `_normalize_user_message(self, user_text: str)`
    - `_normalize_marker_text(self, user_text: str)` — Normalize để detect lệnh nhìn màn hình, KHÔNG strip hậu tố "đi".
    - `_looks_like_screen_vision_request(self, user_text: str)`
    - `_capture_screen_frame_for_chat(self, user_text: str)`
    - `_chat_source_grounding_screen_facts(self, snapshot, *, screen_image_data_uri: str='')`
    - `_build_chat_source_grounding_report(self, *, user_text: str, frame, snapshot, memory_resonance=None, screen_image_data_uri: str='')`
    - `_log_chat_source_grounding(self, report)`
    - `_normalize_public_reaction_text(self, text: str)`
    - `_previous_public_turn_has_protocol_leak(self, public_turn)`
    - `_user_is_challenging_previous_public_turn(self, user_text: str)`
    - `_build_previous_public_turn_repair_decision(self, *, user_text: str, previous_public_turn, ti_report, grounding_report=None, frame=None, speech_core=None)`
    - `_build_grounding_preempt_decision(self, report, ti_report, *, user_text: str)`
    - `_generate_grounding_preempt_text(self, report, *, user_text: str)`
    - `_local_grounding_preempt_text(self, report, *, user_text: str='')`
    - `_build_user_message_signature(self, user_text: str)`
    - `_track_repeated_user_message(self, user_text: str)`
    - `_get_turn_semantics_engine(self)`
    - `_build_turn_semantics_report(self, *, user_text: str, repeat_count: int, previous_user_text: str='', affect_signal=None, conversation_report=None, relationship_report=None, grounding_report=None)`
    - `_build_repeat_guard_decision(self, user_text: str, ti_report, repeat_count: int, *, grounding_report=None, turn_semantics_report: TurnSemanticsReport | None=None)`
    - `_should_bypass_repeat_guard_for_live_observation(self, user_text: str, *, grounding_report=None)`

## `runtime/cognitive_budget.py`
- LOC: 2713
- Docstring: src/runtime/cognitive_budget.py
- Functions:
  - `now_ts()`
  - `clamp01(value: Any, default: float=0.0)` — Ép giá trị về khoảng 0..1.
  - `clamp(value: Any, minimum: float, maximum: float, default: float=0.0)`
  - `safe_get(obj: Any, name: str, default: Any=None)` — Lấy attribute/key theo kiểu duck-typing.
  - `safe_get_path(obj: Any, path: str, default: Any=None)`
  - `as_list(value: Any)`
  - `text_of(value: Any, *, max_len: int=800)` — Chuyển object bất kỳ thành text ngắn để phân tích signal.
  - `lower_text(value: Any, *, max_len: int=1600)`
  - `_keyword_pattern(word: str)` — Tạo pattern match keyword ít ngu hơn substring thuần.
  - `contains_any(text: str, words: Sequence[str])`
  - `count_any(text: str, words: Sequence[str])`
  - `keyword_hits(text: str, words: Sequence[str])`
  - `weighted_keyword_score(text: str, groups: Mapping[str, Sequence[str]], weights: Mapping[str, float])` — Tính score keyword fallback.
  - `blend_semantic_and_keyword(*, semantic: float, keyword: float, keyword_cap_without_semantic: float=0.42, semantic_floor_for_uncap: float=0.35, keyword_weight_when_supported: float=0.35)` — Ghép semantic pressure với keyword fallback.
  - `unique_preserve_order(items: Iterable[str])`
  - `object_to_dict(obj: Any)`
  - `choose_cognitive_budget(frame: Any, **kwargs: Any)` — Hàm tiện ích nếu không muốn tự giữ engine instance.
- Classes:
  - `BudgetModeProfile` (decorator=dataclass(slots=True)) — Thông số tài nguyên cho một budget mode.
    - `to_dict(self)`
  - `BudgetSignalSnapshot` (decorator=dataclass(slots=True)) — Ảnh chụp các áp lực dùng để chọn budget.
    - `pressure_max(self)`
    - `task_pressure(self)`
    - `reflection_pressure(self)`
    - `to_dict(self)`
  - `BudgetScoreBreakdown` (decorator=dataclass(slots=True)) — Điểm cạnh tranh giữa các mode.
    - `as_ranked(self)`
    - `to_dict(self)`
  - `PipelineStepDecision` (decorator=dataclass(slots=True)) — Quyết định chạy/bỏ qua một bước pipeline.
    - `to_dict(self)`
  - `BudgetPlan` (decorator=dataclass(slots=True)) — Kế hoạch chạy pipeline dựa trên budget.
    - `should_run(self, step_name: str)`
    - `step(self, step_name: str)`
    - `to_dict(self)`
  - `BudgetDecision` (decorator=dataclass(slots=True)) — Kết quả cuối của CognitiveBudgetEngine.
    - `to_dict(self)`
    - `to_json(self, *, indent: int=2)`
    - `render_debug_summary(self)`
  - `CognitiveBudgetConfig` (decorator=dataclass(slots=True)) — Cấu hình của CognitiveBudgetEngine.
    - `profiles(self)`
  - `CognitiveBudgetEngine` — Chọn cognitive budget cho một frame.
    - `__init__(self, config: Optional[CognitiveBudgetConfig]=None)`
    - `choose(self, frame: Any, *, channel: str='unknown', user_text: str='', force_reflection: bool=False, force_deep: bool=False, force_fast: bool=False, session_ending: bool=False, shutdown: bool=False, idle_seconds: Optional[float]=None, previous_decisions: Optional[Sequence[BudgetDecision | Mapping[str, Any]]]=None, attach_to_frame: Optional[bool]=None)` — Chọn budget mode cho frame.
    - `choose_mode(self, frame: Any, **kwargs: Any)` — Shortcut khi runtime cũ chỉ cần string budget_mode.
    - `build_plan(self, mode: BudgetMode, frame: Any | None=None)` — Build plan trực tiếp từ mode.
    - `_extract_snapshot(self, frame: Any, *, channel: str, user_text: str='', force_reflection: bool=False, force_deep: bool=False, force_fast: bool=False, session_ending: bool=False, shutdown: bool=False, idle_seconds: Optional[float]=None)`
    - `_collect_text_blob(self, frame: Any, *, user_text: str, evidence: Sequence[Any], raw_signals: Sequence[Any], salience: Any, working_memory: Any, workspace: Any, meaning: Any, memory_packet: Any)`
    - `_extract_user_text_from_signals(self, raw_signals: Sequence[Any], evidence: Sequence[Any])`
    - `_estimate_user_directness(self, channel: str, user_text: str, evidence: Sequence[Any], raw_signals: Sequence[Any], text_blob: str)`
    - `_estimate_signal_density(self, evidence: Sequence[Any], raw_signals: Sequence[Any], salience: Any, working_memory: Any, workspace: Any)`
    - `_estimate_salience_priority(self, salience: Any)`
    - `_estimate_context_pressure(self, working_memory: Any, workspace: Any, salience: Any, evidence: Sequence[Any])`
    - `_semantic_number(self, obj: Any, *names: str)` — Đọc nhiều tên field có thể có từ semantic reports.
    - `_evidence_tag_score(self, evidence: Sequence[Any], tags: set[str], *, base: float=0.42, step: float=0.1)`
    - `_source_grounding_score(self, source_grounding: Any, sources: set[str])`
    - `_meaning_support(self, meaning: Any, keywords: Sequence[str], *, task_weight: float=0.55)`
    - `_estimate_risk_pressure(self, text_blob: str, salience: Any, workspace: Any, permission: Any, tom: Any, *, source_grounding: Any=None, user_text: str='')`
    - `_estimate_privacy_pressure(self, text_blob: str, evidence: Sequence[Any], workspace: Any, permission: Any)`
    - `_estimate_technical_depth(self, text_blob: str, evidence: Sequence[Any], meaning: Any, *, affect_signal: Any=None, source_grounding: Any=None, user_text: str='')`
    - `_estimate_architecture_depth(self, text_blob: str, evidence: Sequence[Any], meaning: Any, *, affect_signal: Any=None, source_grounding: Any=None, user_text: str='')`
    - `_estimate_correction_pressure(self, text_blob: str, evidence: Sequence[Any], outcome: Any, self_observation: Any, *, affect_signal: Any=None, conversation: Any=None, has_user_text: bool=False)`
    - `_estimate_contradiction_pressure(self, text_blob: str, evidence: Sequence[Any], belief: Any, self_observation: Any)`
    - `_estimate_relational_rupture(self, text_blob: str, relation: Any, outcome: Any, self_observation: Any)`
    - `_estimate_affective_residue(self, text_blob: str, affect: Any, relation: Any)`
    - `_estimate_homeostasis_load(self, homeostasis: Any, affect: Any)`
    - `_estimate_goal_pressure(self, frame: Any, text_blob: str)`
    - `_estimate_memory_conflict(self, text_blob: str, memory_packet: Any, belief: Any, self_observation: Any)`
    - `_estimate_worldview_pressure(self, text_blob: str, belief: Any)`
    - `_estimate_uncertainty(self, tom: Any, meaning: Any, salience: Any, workspace: Any)`
    - `_estimate_ambiguity(self, meaning: Any, tom: Any, text_blob: str)`
    - `_estimate_idle_pressure(self, temporal: Any, homeostasis: Any, idle_seconds: Optional[float])`
    - `_estimate_session_closing_pressure(self, text_blob: str, temporal: Any)`
    - `_estimate_reflection_debt(self, text_blob: str, outcome: Any, self_observation: Any, relation: Any, affect: Any, *, correction_pressure: float, contradiction_pressure: float, idle_pressure: float, session_closing_pressure: float, shutdown_pressure: float)`
    - `_estimate_speech_need(self, frame: Any, channel: str, user_directness: float, salience_priority: float, text_blob: str)`
    - `_estimate_body_need(self, frame: Any, workspace: Any, text_blob: str)`
    - `_estimate_low_stakes_ambient(self, *, channel: str, has_user_text: bool, signal_density: float, salience_priority: float, risk_pressure: float, technical_depth: float, relational_rupture: float, idle_pressure: float)`
    - `_estimate_high_value_decision(self, text_blob: str, technical_depth: float, architecture_depth: float, semantic_support: float)`
    - `_score_modes(self, snapshot: BudgetSignalSnapshot, *, previous_decisions: Optional[Sequence[BudgetDecision | Mapping[str, Any]]]=None)`
    - `_choose_mode_from_scores(self, snapshot: BudgetSignalSnapshot, scores: BudgetScoreBreakdown)`
    - `_apply_hard_floors(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot)` — Áp sàn mode để tránh fast path xử lý việc nghiêm túc.
    - `_apply_hard_overrides(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot)`
    - `_derive_reasons(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot, scores: BudgetScoreBreakdown)`
    - `_estimate_confidence(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot, scores: BudgetScoreBreakdown)`
    - `_estimate_urgency(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot)`
    - `_build_reason(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot, escalation: Sequence[str], downgrade: Sequence[str], scores: BudgetScoreBreakdown)`
    - `_build_plan(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot)`
    - `_build_steps(self, mode: BudgetMode, snapshot: BudgetSignalSnapshot, profile: BudgetModeProfile)` — Tạo danh sách module nên chạy.
    - `_attach_decision(self, frame: Any, decision: BudgetDecision)`
    - `_add_report_to_frame(self, frame: Any, report: ModuleReport)`
    - `_add_reflection_commit_request(self, frame: Any, decision: BudgetDecision)`
    - `_extract_evidence_ids(self, frame: Any)`
    - `_normalize_channel(self, channel: str)`
    - `_last_previous_mode(self, previous_decisions: Sequence[BudgetDecision | Mapping[str, Any]])`
    - `_mode_rank(self, mode: str)`
    - `_max_mode(self, current: BudgetMode, floor: BudgetMode)`

## `runtime/cognitive_cycle.py`
- LOC: 407
- Classes:
  - `CognitiveCycleMixin`
    - `stop(self)`
    - `_start_mental_process_loop(self)`
    - `_stop_mental_process_loop(self)`
    - `_run_mental_process_loop(self)`
    - `_tick_mental_process_background(self)`
    - `_mix_axis(self, previous: float, target: float, *, inertia: float)`
    - `_load_mental_process_enabled(self)`
    - `_load_mental_process_interval(self)`
    - `_sleep_interruptible(self, seconds: float)`
    - `run_loop(self)`
    - `_load_ni_meta_mode_flags(self)` — Đọc cấu hình ni_meta_config.json để bật/tắt meta-critic theo mode.
    - `_soften_chat_meta_result(self, *, local_score: float, new_score: float, user_text: str)`
    - `_soften_autonomous_meta_result(self, *, snapshot, local_score: float, new_score: float)`
    - `_maybe_apply_ni_meta_critic(self, *, mode: str, snapshot, base_report, telemetry_text: str, user_text: str='', last_text: str='')` — Áp dụng tầng suy luận nhẹ của Ni dựa trên evidence và tín hiệu snapshot.

## `runtime/cognitive_frame_recorder.py`
- LOC: 1384
- Classes:
  - `CognitiveFrameRecorderMixin` — Ghi nhận frame theo commit protocol.
    - `_remember_cognitive_frame(self, frame: CognitiveFrame)` — Tương thích tên hàm cũ, nhưng không ghi memory trực tiếp nữa.
    - `_is_ephemeral_micro_presence_observation(self, frame: CognitiveFrame, observation: Mapping[str, Any])`
    - `_derive_state_commit_requests(self, frame: CognitiveFrame)` — Sinh toàn bộ StateCommitRequest từ frame hiện tại.
    - `_observe_outcome_for_commit(self, frame: CognitiveFrame)` — Rút outcome cuối turn thành payload sạch để derive request.
    - `_make_commit_request(self, *, target: str, content: Any, confidence: float, evidence_ids: Sequence[str]=(), permission_required: bool=True, storage_permission: bool=True, decay_policy: str='normal', reason: str='', tags: Sequence[str]=(), metadata: Mapping[str, Any] | None=None)` — Tạo request dạng dict tương thích StateCommitRequest.
    - `_append_commit_requests(self, frame: CognitiveFrame, requests: Sequence[Any])` — Append request vào frame mà không phá contract frame cũ/mới.
    - `_refresh_memory_update_from_commit_requests(self, frame: CognitiveFrame, requests: Sequence[Any])` — Cập nhật summary debug trên frame.memory_update từ request vừa derive.
    - `_remember_relationship_reflections(self, frame: CognitiveFrame, *, timestamp: str)` — Tên cũ, hành vi mới: derive request, không ghi store trực tiếp.
    - `_derive_relationship_reflections(self, frame: CognitiveFrame)`
    - `_target_for_reflection(self, pattern: str)` — Map reflection sang memory layer phù hợp.
    - `_extract_relationship_style_reflection(self, user_text: str)`
    - `_derive_repair_commit_request(self, frame: CognitiveFrame, observation: Mapping[str, Any], *, storage_permission: bool)`
    - `_derive_affective_residue_request(self, frame: CognitiveFrame, observation: Mapping[str, Any], *, storage_permission: bool)`
    - `_derive_active_state_request(self, frame: CognitiveFrame, observation: Mapping[str, Any], *, storage_permission: bool)`
    - `_semantic_fact_grounding_metadata(self, frame: CognitiveFrame, *, semantic_source: str)`
    - `_extract_explicit_user_memory_fact(self, user_text: str)`
    - `_frame_evidence_ids(self, frame: CognitiveFrame)`
    - `_evidence_ids_for_fact(self, frame: CognitiveFrame, fact: str, *, fallback: Sequence[str])`
    - `_frame_storage_permission(self, frame: CognitiveFrame)`
    - `_looks_like_user_correction_text(self, text: str)`
    - `_commit_internal_state_for_frame(self, frame: CognitiveFrame, *, snapshot=None, ti_report=None)` — Tính internal_state_after, rồi tạo active_state request.
    - `_apply_post_relational_leak_restraint(self, state: PersistentInternalState, text: str)`
    - `_liveliness_tracker(self)`
    - `_record_liveliness_decision(self, frame: CognitiveFrame, final_text: str)` — Emit one DecisionRecord per autonomous idle cycle (Req 5.5, 6).
    - `_finalize_cognitive_frame(self, frame: CognitiveFrame)`
    - `_start_epistemic_episode(self, frame: CognitiveFrame)`
    - `_observe_outcome_for_frame(self, frame: CognitiveFrame)`
    - `_feed_private_mind_outcome(self, outcome: Any, *, frame: CognitiveFrame | None=None)`
    - `_reflect_self_observation_for_frame(self, frame: CognitiveFrame)`
    - `_append_self_observation_repair_request(self, frame: CognitiveFrame)`
    - `_get_outcome_observer(self)`
    - `_get_self_observer(self)`
    - `_commit_frame_through_state_committer(self, frame: CognitiveFrame)` — Gọi StateCommitter.commit(frame), không gọi memory core trực tiếp.
    - `_get_state_committer(self)` — Lấy hoặc tạo StateCommitter từ MemoryCognitionCore.
    - `_sync_after_state_commit(self, frame: CognitiveFrame, report: Any)` — Đồng bộ cache đọc sau commit, không ghi memory trực tiếp.
    - `_safe_state_payload(self, state: Any)`
    - `_repair_strategy_for_failure(self, failure_type: str, mode: str)`
    - `_future_suppression_rule_for_failure(self, failure_type: str, mode: str)`
    - `_dedupe_frame_commit_requests(self, frame: CognitiveFrame)`
    - `_dedupe_commit_requests(self, requests: Sequence[Any])`
    - `_existing_commit_request_keys(self, requests: Sequence[Any])`
    - `_commit_request_field(self, request: Any, field_name: str, default: Any=None)`
    - `_commit_request_key(self, request: Any)`
    - `_next_cognitive_cycle_id(self, channel: str)`
    - `_bounded_float(self, value: float, *, minimum: float=0.0, maximum: float=1.0)`
    - `_event_timestamp(self, snapshot=None, *, started_at: float | None=None)`
    - `_decision_to_frame_dict(self, decision: Decision | None)`
    - `_set_cognitive_memory_update(self, frame: CognitiveFrame, *, decision: Decision | None=None, notes: tuple[str, ...]=())`
    - `_log_pre_parser(self, channel: str, raw: str)`
    - `_log_decision_stage(self, channel: str, stage: str, decision: Decision)`

## `runtime/cognitive_pipeline.py`
- LOC: 342
- Docstring: runtime/cognitive_pipeline.py
- Classes:
  - `_SituationEmbeddingProvider` — Embedding provider lazy cho Situation Model.
    - `embed(self, text: str)`
  - `PipelineResult` (decorator=dataclass(slots=True)) — Kết quả một lần chạy pipeline.
    - `budget_mode(self)`
  - `CognitivePipeline` — Chạy Phase 1 trên CognitiveFrame core.
    - `__init__(self, *, normalizer: Optional[EvidenceNormalizer]=None, attention: Optional[AttentionSalienceEngine]=None, budget: Optional[CognitiveBudgetEngine]=None, working_memory: Optional[WorkingMemoryEngine]=None, workspace: Optional[GlobalWorkspaceEngine]=None, situation_model: Optional[SituationModel]=None)`
    - `run_from_signals(self, raw_signals: Sequence[RawSignal], *, channel: str='chat', user_text: str='', session_id: Optional[str]=None, active_goal: Any=None, idle_seconds: Optional[float]=None, force_deep: bool=False, force_fast: bool=False, force_reflection: bool=False)` — Tạo frame từ raw signals rồi chạy toàn bộ Phase 1.
    - `run(self, frame: CognitiveFrame, *, channel: Optional[str]=None, active_goal: Any=None, idle_seconds: Optional[float]=None, force_deep: bool=False, force_fast: bool=False, force_reflection: bool=False)` — Chạy Phase 1 trên một frame đã có raw_signals.
    - `_set_slot(self, frame: CognitiveFrame, slot_name: str, value: Any, *, actor: str, evidence_used: Optional[list[str]]=None, confidence: Optional[float]=None)`
    - `_safe_call(obj: Any, method: str)`
    - `_salience_confidence(salience: Any)`
    - `_budget_report(decision: BudgetDecision)`
    - `_infer_user_text(raw_signals: Sequence[RawSignal])`

## `runtime/contextual_autonomy_loop.py`
- LOC: 237
- Docstring: src/runtime/contextual_autonomy_loop.py
- Classes:
  - `ContextualAutonomyLoopConfig` (decorator=dataclass(slots=True))
  - `AutonomyLoopTickResult` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `ContextualAutonomyLoop` — Backbone điều phối 3 tầng, gọi được từ coordinator.
    - `__init__(self, *, user_context_stream: UserContextStream | None=None, endogenous_drive: EndogenousDriveEngine | None=None, agenda_stack: InternalAgendaStack | None=None, daydream: DaydreamConsolidator | None=None, budget_policy: ModelBudgetPolicy | None=None, wake_governor: AutonomousWakeGovernor | None=None, agent_mind: Any=None, config: ContextualAutonomyLoopConfig | None=None, logger: Any=None)`
    - `tick(self, *, signal_snapshot: SignalSnapshot | Mapping[str, Any] | None=None, signal_diff: SignalDiff | None=None, observer_frame: ObserverFrame | None=None, base_internal_state: Any=None, memory_packets: Iterable[DaydreamPacket]=(), user_text: str='', channel: str='autonomous', autonomous_silent_cycles: int=0)`
    - `_maybe_run_growth_tick(self, *, trigger: bool, wake: 'WakeDecision')` — Chạy một lượt long-arc growth nếu feature bật. Bọc try/except để loop
    - `next_sleep_seconds(self, decision: WakeDecision)`

## `runtime/controlled_slippage.py`
- LOC: 599
- Functions:
  - `_clamp01(value: float)`
  - `_normalize(text: str)`
  - `_has_any(normalized_text: str, markers: tuple[str, ...])`
  - `_max_mode(left: SlippageMode, right: SlippageMode)`
  - `_min_mode(left: SlippageMode, right: SlippageMode)`
  - `derive_repair_suppression(repair_items: Any, *, min_pressure: float=0.3)` — Pure: gộp các RepairMemoryItem đã recall thành một RepairSuppressionView.
  - `_apply_repair_suppression(profile: 'ControlledSlippageProfile', view: RepairSuppressionView, notes: list[str])` — Áp RepairSuppressionView lên profile theo nguyên tắc tighten-only.
  - `user_granted_relational_risk(user_text: str)`
  - `_selected_spontaneous_impulse(speech_core: Any)`
  - `resolve_controlled_slippage(*, user_text: str='', channel: str='', ti_report: Any=None, affect_signal: Any=None, conversation_state: Any=None, relationship_state: Any=None, internal_state: Any=None, grounding_report: Any=None, speech_core: Any=None, repair_suppression: RepairSuppressionView | None=None)` — Tính ControlledSlippageProfile từ state hiện có.
  - `apply_slippage_to_ti_report(ti_report: Any, profile: ControlledSlippageProfile)` — Trả về bản TiPolicyReport đã được điều áp mềm.
  - `apply_slippage_to_personality_lens(lens: Any, profile: ControlledSlippageProfile)` — Nới lens mà không làm mất truth guard.
- Classes:
  - `RepairSuppressionView` (decorator=dataclass(slots=True)) — Tín hiệu siết-có-cấu-trúc rút ra từ ký ức sửa lỗi đã recall.
    - `to_dict(self)`
  - `ControlledSlippageProfile` (decorator=dataclass(slots=True)) — Hồ sơ quyết định ERIS được "liều" tới đâu ở lượt hiện tại.
    - `clamp(self)`
    - `to_dict(self)`
    - `render_prompt_context(self)` — Context đưa vào prompt LLM.

## `runtime/coordinator.py`
- LOC: 8340
- Functions:
  - `_is_generic_telemetry_line(text: str)` — True nếu một dòng chỉ là telemetry chung chung, KHÔNG phải nội dung màn hình thật.
  - `_is_nonsemantic_fallback_decision(decision: Decision)` — True nếu decision chỉ là fallback kỹ thuật, không phải answer nội dung.
- Classes:
  - `RuntimeCoordinator` (base=CognitiveCycleMixin, ChatCycleMixin, AutonomousCycleMixin, ForceSpeakCycleMixin, StateCommitServiceMixin, FrameBuilderMixin, SpeechPipelineMixin, PromptContextBuilderMixin, CognitiveFrameRecorderMixin, PresenceControllerMixin, TextRepeatGuardMixin, ForceSpeakSurfacePolicyMixin, PostGenerationFiltersMixin, ShadowPipelineMixin, SelfCritiqueEscalationMixin)
    - `_fallback_lines_for_intent(self, intent: str)`
    - `_force_speak_fallback_by_intent_text(self, intent: str, *, counter: int=1, repeated: bool=False, focus_kind: str='', window_title: str='', momentum_topic: str='')`
    - `_public_thought_topic(self, value: str)`
    - `_looks_internal_topic(self, value: str)`
    - `_background_memory_digest_idle_probe(self, *, quiet_for: float=0.0, now: float | None=None)` — Chỉ cho semantic digest chạy khi runtime thật sự rảnh.
    - `__init__(self, *, logger, transport, llm_service, parser, telemetry_service, ni_engine, ti_governor, fe_renderer, memory_core, body_running_fn, action_executor=None, action_router=None, memory_semantic_parser=None)`
    - `_install_model_inference_queue(self)` — Bọc các đường gọi model nặng bằng ModelBudgetPolicy queue.
    - `_run_background_observer(self, *, snapshot, channel: str='', user_text: str='', vision_facts: tuple[str, ...]=(), started_at: float | None=None)` — Chạy BackgroundObserver trên snapshot hiện tại.
    - `_log_observer_trace(self, observer_frame: ObserverFrame | None)`
    - `_update_3tier_autonomy_state(self, *, signal_snapshot: SignalSnapshot, signal_diff, observer_frame: ObserverFrame | None, channel: str='', user_text: str='')`
    - `_update_private_mind_state(self, *, signal_snapshot, observer_frame, wake_decision, channel: str='', user_text: str='')` — Chạy private mind 5 phase trên thread nền — không bao giờ block main loop.
    - `_apply_private_mind_tick_result(self, result, *, daemon)` — Apply kết quả tick PrivateMind sau khi background thread hoàn tất.
    - `_sync_private_mind_future_bias(self)` — Đẩy ``future_bias`` từ digest -> các thuộc tính runtime mà tầng wording đọc.
    - `_persist_inner_diary(self)` — Ghi inner_diary hiện tại ra đĩa (throttled). Không bao giờ ném lỗi.
    - `_drain_private_mind_surface_impulses(self, *, limit: int=4)` — Lấy impulse đã được SurfaceValve lọc để đưa vào SurfaceArbiter.
    - `_update_private_life_state(self, *, signal_snapshot, observer_frame=None, wake_decision=None, channel: str='', user_text: str='')` — Chạy PrivateLifeCore trên tick nền.
    - `_drain_private_life_surface_impulses(self, *, limit: int=4)` — Lấy impulse đã lọc từ PrivateLife để đưa vào SurfaceArbiter.
    - `_private_life_digest_for_payload(self)` — Digest gọn cho debug UI/body payload.
    - `_daydream_packets_from_runtime(self, *, limit: int=20)`
    - `_append_daydream_packets_from_memory_snapshot(self, snapshot: dict[str, object], add_packet, *, limit: int)`
    - `_daydream_kind_from_memory_layer(self, layer: str)`
    - `_daydream_text_from_memory_record(self, record: dict[str, object])`
    - `_build_signal_snapshot_for_observer(self, *, snapshot, channel: str='', user_text: str='', vision_facts: tuple[str, ...]=(), started_at: float | None=None)`
    - `_observer_focus_kind_from_snapshot(self, snapshot)`
    - `_observer_percept_content(self, observer_frame: ObserverFrame | None)`
    - `_observer_attention_tags(self, observer_frame: ObserverFrame | None, *, channel: str='')`
    - `_log_raw_llm_output(self, channel: str, raw: str)`
    - `_preview_text(self, text: str, *, limit: int=1000)`
    - `_infer_active_conversational_topic(self, user_text: str, *, fe_plan=None, ti_report=None)`
    - `_load_memory_state(self)`
    - `_resolve_internal_agenda_path(self)`
    - `_has_structured_memory_store(self)`
    - `_ensure_internal_state(self)`
    - `_get_internal_state(self)`
    - `_set_internal_state(self, state: PersistentInternalState)`
    - `_send_decision_to_body(self, decision: Decision, *, channel: str | None=None)`
    - `_private_mind_digest_for_payload(self)`
    - `_compact_private_mind_digest_for_udp(self, digest: dict[str, object])`
    - `_compact_private_mind_debug_value(self, value: object, *, depth: int=0)`
    - `_compact_private_mind_scalar(value: object, *, limit: int=260)`
    - `_private_mind_speech_silence_reason(self)`
    - `_handle_tts_playback_event(self, event, *, stage_frame=None)` — Nhận lifecycle event từ TTS worker.
    - `_record_public_turn(self, decision: Decision, *, payload: dict | None=None, channel: str | None=None)`
    - `_infer_public_turn_channel_from_runtime(self, decision: Decision)`
    - `_load_rapid_burst_window(self)`
    - `_block_autonomous_presence_after_public_turn(self, now: float | None=None)`
    - `_link_previous_public_turn_for_chat(self, user_timestamp: float)`
    - `_previous_public_turn_context(self, public_turn)`
    - `_build_body_bias_payload(self)`
    - `_build_emotion_debug_payload(self)` — Compact affect/state payload for the Godot emotion panel.
    - `_body_bias_clamp(value: object)`
    - `_normalize_body_focus_kind(value: str)`
    - `_make_cognitive_disturbance(self, *, channel: str, kind: str, content: str, evidence: tuple[str, ...]=(), intensity: float=1.0)`
    - `_looks_like_closure_disturbance(self, content: str)`
    - `_build_event_disturbances(self, *, channel: str, snapshot=None, user_text: str='', force_speak: bool=False, vision_facts: tuple[str, ...]=())`
    - `_disturb_cognitive_substrate(self, *, channel: str, snapshot=None, user_text: str='', force_speak: bool=False, vision_facts: tuple[str, ...]=(), consume_surface: bool=False)`
    - `_with_thought_stream_surface(self, report: ThoughtStreamReport, surface)`
    - `_pop_thought_stream_report_for_autonomous(self)`
    - `_pop_subconscious_report_for_autonomous(self)`
    - `_save_memory_state(self)`
    - `_memory_recall_texts(self, *, snapshot=None)`
    - `_recall_learned_knowledge(self, snapshot=None)` — Lấy claim đã học từ gia sư liên quan ngữ cảnh hiện tại, dán nhãn [đã học].
    - `_activate_memory_resonance(self, *, snapshot=None, user_text: str='', channel: str='', fragments: tuple[str, ...]=())`
    - `_thought_stream_resonance_fragments(self)`
    - `_memory_attention_lines(self)`
    - `_norm_deviation_texts(self, snapshot)`
    - `_note_norm_observation(self, snapshot)`
    - `_event_timestamp(self, snapshot, *, started_at: float | None=None)`
    - `_normalize_event_evidence(self, evidence, *, limit: int=4)`
    - `_make_percept_event(self, *, kind: str, content: str, timestamp: str, evidence=(), confidence: float=1.0, source: str='runtime', privacy_level: str='internal', novelty_hint: str='routine')`
    - `_telemetry_event_privacy_level(self, kind: str)`
    - `_telemetry_event_novelty_hint(self, kind: str, content: str)`
    - `_collect_percept_events(self, *, channel: str, snapshot, user_text: str='', vision_facts: tuple[str, ...]=(), force_speak: bool=False, internal_state: PersistentInternalState | None=None, thought_stream_report=None, social_presence_event: SocialPresenceEvent | None=None, observer_frame: ObserverFrame | None=None, started_at: float | None=None)`
    - `_collect_cognitive_percepts(self, **kwargs)`
    - `_score_attention_candidate(self, percept: PerceptEvent)`
    - `_standing_stakes(self)` — Vector quan tâm thường trực của ERIS, dùng để thiên lệch chú ý.
    - `_build_attention_candidates(self, percepts: tuple[PerceptEvent, ...], *, channel: str='', snapshot=None, user_text: str='')`
    - `_build_broadcast(self, candidates: tuple[AttentionCandidate, ...])`
    - `_evidence_from_percepts(self, percepts: tuple[PerceptEvent, ...], *, channel: str='', snapshot=None, user_text: str='')`
    - `_salience_candidate_to_runtime(self, candidate)`
    - `_runtime_attention_label(self, candidate, tags: tuple[str, ...])`
    - `_build_meaning_layer(self, *, snapshot, broadcast: CognitiveBroadcast, internal_state, thought_stream_report=None, channel: str='', user_text: str='', force_speak: bool=False, affect_signal=None, ti_report=None, fe_plan=None)`
    - `_build_personality_lens(self, *, snapshot, broadcast: CognitiveBroadcast, internal_state, meaning_layer: MeaningLayerResult | None=None, channel: str='', user_text: str='', affect_signal=None, ti_report=None, fe_plan=None)`
    - `_apply_personality_lens_to_fe_plan(self, fe_plan, lens: PersonalityLensResult)`
    - `_build_cognitive_appraisal(self, *, internal_state, ni_report, ti_report, fe_plan, broadcast, channel: str='', user_text: str='', force_speak: bool=False, personality_lens=None)`
    - `_build_appraisal_context(self, appraisal: CognitiveAppraisal, *, frame=None)`
    - `_build_inner_thought(self, *, channel: str, snapshot, frame: CognitiveFrame, concrete_signals: tuple[str, ...]=(), repeat_count: int=1, repeated_topic_tag: str='', repeated_topic_streak: int=0, subconscious_seed=None, thought_surface=None)`
    - `_build_speech_core(self, *, channel: str, snapshot, internal_state, frame: CognitiveFrame, ti_report, fe_plan, ni_report=None, ni_state_label: str='', repeat_count: int=1, repeated_topic_tag: str='', repeated_topic_streak: int=0, subconscious_seed=None, thought_surface=None)`
    - `_remember_inner_thought_rhythm(self, inner_thought: InnerThought | None)`
    - `_start_cognitive_frame(self, *, channel: str, started_at: float, snapshot, internal_state_before, sensed_internal_state, ni_report, ti_report, fe_plan, user_text: str='', vision_facts: tuple[str, ...]=(), thought_stream_report=None, social_presence_event: SocialPresenceEvent | None=None, force_speak: bool=False, memory_resonance=None, affect_signal=None)`
    - `_set_cognitive_action_plan(self, frame: CognitiveFrame, *, should_speak: bool, speech_intent: str, reason: str, snapshot=None, user_text: str='', force_speak: bool=False, concrete_signals: tuple[str, ...]=(), ti_report=None, fe_plan=None, system_action: str='', speech_act: str='', notes: tuple[str, ...]=(), inner_thought: InnerThought | None=None)`
    - `_apply_micro_line_policy_to_action_plan(self, frame: CognitiveFrame, *, vision_fact: str='')`
    - `_micro_policy_anchor_hints(self, *, broadcast=None, snapshot=None)`
    - `_build_relational_context(self, state: PersistentInternalState | None=None)`
    - `_speech_intent_from_core(self, speech_core: AgentSpeechCore, *, channel: str)`
    - `_merge_speech_core_notes(self, notes: tuple[str, ...], speech_core: AgentSpeechCore)`
    - `_merge_meaning_layer_notes(self, notes: tuple[str, ...], meaning_layer)`
    - `_speak_truth_probe_row(self, status: dict[str, object] | None)`
    - `_build_speak_truth_table(self, *, frame: CognitiveFrame, decision: Decision | None=None, wake_decision: WakeDecision | None=None, ambient_hold: bool | None=None, ambient_reason: str='', presence_status: dict[str, object] | None=None, reengagement_status: dict[str, object] | None=None, post_filters_ran: bool=False)`
    - `_summarize_speak_truth_table(self, table: dict[str, object])`
    - `_attach_speak_truth_table(self, frame: CognitiveFrame, *, decision: Decision | None=None, wake_decision: WakeDecision | None=None, ambient_hold: bool | None=None, ambient_reason: str='', presence_status: dict[str, object] | None=None, reengagement_status: dict[str, object] | None=None, post_filters_ran: bool=False)`
    - `_merge_memory_resonance_notes(self, notes: tuple[str, ...], memory_resonance)`
    - `_merge_inner_thought_notes(self, notes: tuple[str, ...], inner_thought: InnerThought)`
    - `_merge_personality_lens_notes(self, notes: tuple[str, ...], personality_lens)`
    - `_merge_subconscious_notes(self, notes: tuple[str, ...], subconscious_report)`
    - `_is_inner_thought_speech_act(self, speech_act: str)`
    - `_restore_session_ritual_once(self)` — Run the startup continuity greeting once per runtime session.
    - `_apply_force_speak_no_evidence_topic_filter(self, decision: Decision, *, channel: str, speech_core: AgentSpeechCore, snapshot=None, momentum_topic: str='')`
    - `_build_planned_withdraw_decision(self, action_plan: CognitiveActionPlan)`
    - `_log_decision_stage(self, channel: str, stage: str, decision: Decision)` — Log a compact Decision preview after parser / Ti / repair stages.
    - `_maybe_tutor_on_unclear_user(self, user_text, frame)` — Khi Eris không hiểu/không phân loại nổi tin user → định tuyến.
    - `_fire_tutor_lookup(self, topic: str, *, context: str='')` — Bắn một lượt hỏi Gemini ở thread nền (có throttle). Không chặn trả lời chat.
    - `_looks_like_knowledge_question(self, low: str)` — True nếu câu trông như hỏi kiến thức thế giới (đáng đi tra gia sư).
    - `_research_can_start(self)` — Debounce nhịp tra cứu: không tra khi đang có lượt tra chạy, và cách nhau tối thiểu.
    - `_fire_research_followup(self, topic: str, *, context: str='')` — Nhịp 2: thread nền đi hỏi gia sư rồi gửi đáp án về (không chặn trả lời lượt này).
    - `_deliver_research_followup(self, topic: str, answer)` — Gửi câu trả lời nhịp 2 ra body bằng giọng Eris (qua đường decision chuẩn).
    - `stop(self)`
    - `_start_mental_process_loop(self)`
    - `_stop_mental_process_loop(self)`
    - `_run_mental_process_loop(self)`
    - `_tick_mental_process_background(self)`
    - `_build_subconscious_runtime(self)`
    - `_subconscious_frame_payload(self, *, snapshot, user_text: str, internal_state, channel: str, event_text: str='', vision_facts: tuple[str, ...]=())`
    - `_subconscious_memory_packet(self, *, limit: int=12)`
    - `_subconscious_pressure_metrics(self, *, internal_state, snapshot, event_strength: float)`
    - `_subconscious_blackboard_metrics(self, *, now: float)`
    - `_schedule_next_subconscious_due(self, lane: str, low: float, high: float, *, now: float)`
    - `_score_subconscious_surface(self, *, thought, snapshot, internal_state, recurring_theme_strength: float)`
    - `_surface_from_subconscious_thought(self, thought, *, surface_score: float)`
    - `_maybe_tick_subconscious_runtime(self, *, channel: str, snapshot, internal_state, user_text: str='', event_text: str='', vision_facts: tuple[str, ...]=(), event_strength: float=0.0, allow_lane5: bool=True, reflection: bool=False)`
    - `_maybe_tick_subconscious_background(self, *, snapshot, internal_state)`
    - `_mix_axis(self, previous: float, target: float, *, inertia: float)`
    - `_load_mental_process_enabled(self)`
    - `_load_mental_process_interval(self)`
    - `_load_autonomous_sleep_seconds(self, env_name: str, *, default: tuple[int, ...])`
    - `_apply_position_update(self, decision: Decision)`
    - `_build_silent_motion_decision(self, ti_report: TiPolicyReport)`
    - `_normalize_user_message(self, user_text: str)`
    - `_looks_like_screen_vision_request(self, user_text: str)`
    - `_capture_screen_frame_for_chat(self, user_text: str)`
    - `_build_user_message_signature(self, user_text: str)`
    - `_track_repeated_user_message(self, user_text: str)`
    - `_build_repeat_guard_decision_basic(self, user_text: str, ti_report, repeat_count: int)`
    - `_build_repeat_guard_decision(self, user_text: str, ti_report, repeat_count: int, *, grounding_report=None, turn_semantics_report=None)`
    - `_handle_incoming(self, msg: dict)`
    - `_handle_debug_command(self, msg: dict)` — Chạy lệnh debug (scenario preset) từ panel DEBUG của Godot.
    - `_handle_anchor_control(self, msg: dict)` — Tác_Giả bật/tắt trục tối từ panel Godot (R5.5, R10.4).
    - `_handle_depth_control(self, msg: dict)` — Bật/tắt cờ chiều-sâu (N1–N3) từ tab Panel trong context menu Godot.
    - `_build_depth_block(self)` — Block 'depth' cho panel Godot: trạng thái cờ + tín hiệu chiều-sâu sống.
    - `_build_depth_v2_block(self, *, private_mind_digest: dict[str, object] | None=None)` — Compact v2 contract for the replacement depth panel.
    - `_cached_panel_state(self, *, ttl_seconds: float=1.0)` — build_panel_state() có cache ngắn — payload UDP gọi rất dày.
    - `_maybe_log_depth_signals(self, block: dict[str, object], *, throttle_seconds: float=30.0)` — Append tín hiệu chiều-sâu ra ``logs/depth_signals.jsonl`` để phát triển theo thời gian.
    - `_commit_chat_decision(self, decision: Decision, fe_plan, *, frame: CognitiveFrame | None=None)`
    - `_sleep_interruptible(self, seconds: float)`
    - `_bucket_idle_seconds(self, idle_seconds: float)`
    - `_bucket_window_spread(self, open_windows: tuple[str, ...], browser_tabs: tuple[str, ...])`
    - `_load_vision_fact_settings(self)`
    - `_build_vision_caption_client(self, llm_service)` — Tầng caption (ảnh → mô tả) chạy REMOTE khi llm_service có vision_client.
    - `_build_vision_structure_client(self, llm_service)` — Tầng cấu trúc-hoá vision (caption → JSON) chạy REMOTE.
    - `_vision_queue_timeout_seconds(self, channel: str)`
    - `_vision_failure_backoff_seconds(self, stage: str, exc: Exception)`
    - `_note_vision_failure(self, stage: str, exc: Exception)`
    - `_is_low_value_screen_fact(self, fact: str)`
    - `_speech_evidence_score(self, text: str, *, kind: str='')`
    - `_is_speakable_evidence(self, text: str, *, kind: str='')`
    - `_sanitize_screen_facts(self, facts: list[str] | tuple[str, ...])`
    - `_semantic_scene_note_to_facts(self, note: SemanticSceneNote | None)`
    - `_vision_trace_from_scene_note(self, note: SemanticSceneNote | None)`
    - `_should_use_vision_compressor(self, *, observer_frame: ObserverFrame | None, force_refresh: bool)`
    - `_refresh_screen_facts_from_data_uri(self, *, data_uri: str, snapshot=None, channel: str='autonomous', user_text: str='', observer_frame: ObserverFrame | None=None, force_refresh: bool=False, started_at: float | None=None)`
    - `_maybe_update_screen_facts(self, *, snapshot=None, channel: str='autonomous', user_text: str='', observer_frame: ObserverFrame | None=None, force_refresh: bool=False, started_at: float | None=None)`
    - `_attach_screen_facts(self, snapshot, facts: tuple[str, ...])`
    - `_build_autonomous_signature(self, snapshot, ti_report)`
    - `_track_autonomous_signature(self, snapshot, ti_report)`
    - `_should_suppress_autonomous_reply(self, *, ti_report, repeat_count: int, ni_report=None, ni_state_label: str='', repeated_topic_tag: str='', repeated_topic_streak: int=0)`
    - `_has_resource_pressure_signal(self, snapshot)`
    - `_is_generic_screen_event(self, event: str)`
    - `_is_generic_screen_evidence(self, evidence: str)`
    - `_concrete_screen_signals(self, snapshot)`
    - `_concrete_vision_signals(self, snapshot)`
    - `_concrete_telemetry_signals(self, snapshot)`
    - `_has_concrete_screen_signal(self, snapshot)`
    - `_broadcast_screen_winners(self, broadcast: CognitiveBroadcast | None)`
    - `_choose_autonomous_speech_intent(self, *, snapshot, ni_report, ti_report, repeat_count: int, attention_broadcast: CognitiveBroadcast | None=None, inner_thought: InnerThought | None=None, ni_state_label: str='', repeated_topic_tag: str='', repeated_topic_streak: int=0)`
    - `_ambient_silence_cooldown_seconds(self, snapshot, ti_report)`
    - `_should_hold_ambient_silence(self, *, snapshot, ti_report, speech_intent: str='', now: float | None=None)`
    - `_should_skip_weak_autonomous_speech(self, *, snapshot, speech_core: AgentSpeechCore, thought_stream_report, social_presence_event: SocialPresenceEvent | None, frame: CognitiveFrame)`
    - `_has_high_cognitive_momentum(self, thought_stream_report)`
    - `_choose_autonomous_sleep_duration(self, *, suppressed: bool, ti_mode: str)`
    - `_current_autonomous_wake_decision(self)`
    - `_wake_allows_main_cognition(self)`
    - `_autonomous_sleep_seconds_from_wake(self, decision: WakeDecision)`
    - `_send_wake_gate_body_update(self, decision: WakeDecision, *, reason: str='')`
    - `_wake_gate_ti_report(self, *, reason: str)`
    - `_wake_gate_fe_plan(self, *, ti_report, snapshot, internal_state)`
    - `_wake_gate_presence_candidate(self, *, snapshot, social_presence_event: SocialPresenceEvent | None)`
    - `_presence_probe_status(self, *, snapshot, ti_report, social_presence_event: SocialPresenceEvent | None, now: float)`
    - `_reengagement_probe_status(self, *, snapshot, ti_report, internal_state, now: float)`
    - `_update_wake_gate_debug(self, decision: WakeDecision, **fields: object)`
    - `_presence_surface_status_label(self, status: dict[str, object] | None)`
    - `_log_presence_surface_statuses(self, *, presence_status: dict[str, object], reengagement_status: dict[str, object], final_rejected_by: str)`
    - `_build_wake_gate_frame(self, *, cycle_start: float, snapshot, internal_state, social_presence_event: SocialPresenceEvent | None=None)`
    - `_finalize_wake_gate_micro_decision(self, *, frame: CognitiveFrame, decision: Decision, surface=None, requested_kind: str='', snapshot, ti_report, fe_plan, cycle_start: float, note: str, spoken_kwargs: dict[str, object] | None=None, presence_status: dict[str, object] | None=None, reengagement_status: dict[str, object] | None=None)`
    - `_surface_arbiter_drop_reason(self, default: str='surface_arbiter_no_decision')` — Lấy lý do SurfaceArbiter vừa từ chối surface, nếu có.
    - `_surface_arbiter_drop_status(self, *, default: str='surface_arbiter_no_decision', owner: str)`
    - `_surface_arbiter_reason_from_surface(self, surface, default: str)`
    - `_surface_arbiter_status_from_surface(self, *, surface, owner: str, default: str)`
    - `_maybe_low_level_surface_from_wake_gate(self, *, snapshot, cycle_start: float, wake_decision: WakeDecision, reason: str, check_reengagement: bool=True)` — Cho SurfaceArbiter chạy ngay cả khi WakeGovernor trả sleep/observe_only.
    - `_maybe_presence_maintenance_before_sleep(self, *, snapshot, cycle_start: float, wake_decision: WakeDecision)`
    - `_maybe_micro_presence_from_observe_only(self, *, snapshot, cycle_start: float, wake_decision: WakeDecision)`
    - `_finalize_autonomous_wake_gate(self, *, decision: WakeDecision, cycle_start: float, send_body_update: bool, reason: str='', note_silence: bool=True)`
    - `_commit_think_only_active_frame(self, *, snapshot, observer_frame: ObserverFrame | None, vision_facts: tuple[str, ...], cycle_start: float, wake_decision: WakeDecision)` — Tạo dấu vết cognition nhẹ cho `think_only` mà không gọi main LLM.
    - `_process_pending_user_input(self)`
    - `_conversation_went_stale(self)` — True nếu đang chat_mode nhưng lượt user cuối đã hết "tươi".
    - `_run_loop_iteration(self)` — Run a single coordinator loop iteration.
    - `run_loop(self)`
    - `_load_ni_meta_mode_flags(self)` — Đọc cấu hình ni_meta_config.json để bật/tắt meta-critic theo mode.
    - `_soften_chat_meta_result(self, *, local_score: float, new_score: float, user_text: str)`
    - `_soften_autonomous_meta_result(self, *, snapshot, local_score: float, new_score: float)`
    - `_maybe_apply_ni_meta_critic(self, *, mode: str, snapshot, base_report, telemetry_text: str, user_text: str='', last_text: str='')` — Áp dụng tầng suy luận nhẹ của Ni dựa trên evidence và tín hiệu snapshot.
    - `_build_direct_action_decision(self, user_text: str, ti_report, snapshot, *, repeat_count: int=1)`
    - `_execute_system_action(self, decision: Decision, *, snapshot)`
    - `_action_animation_hint(self, action_name: str, fallback: str)`
    - `_action_result_to_text(self, result)`
    - `_resolve_now_playing_text(self, snapshot)`
    - `_extract_media_title_from_snapshot(self, snapshot)`
    - `_extract_media_title(self, raw_title: str)`

## `runtime/daydream_model_adapter.py`
- LOC: 100
- Functions:
  - `_env_flag(name: str, default: bool)`
- Classes:
  - `DaydreamModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True))
  - `DaydreamModelResult` (decorator=dataclass(slots=True, frozen=True))
  - `RuntimeDaydreamModelAdapter` — Adapter riêng cho daydream 4B, không ké style client.
    - `__init__(self, *, config: DaydreamModelAdapterConfig | None=None, ollama_client: Any | None=None, logger: Any | None=None)`
    - `from_env(cls, *, logger: Any | None=None)`
    - `chat_json(self, model: str, messages: list[dict[str, Any]], *, keep_alive: str | int | None=None, temperature: float=0.0)`
    - `_from_ollama_result(self, result: OllamaResult)`
    - `_log(self, level: str, msg: str, *args: Any)`

## `runtime/debug_console.py`
- LOC: 456
- Docstring: debug_console.py — Bảng lệnh debug ẩn cho ERIS.
- Functions:
  - `_clamp(value: float, signed: bool)`
- Classes:
  - `DebugConsole` — Phân tích + thực thi lệnh debug trên state sống của coordinator.
    - `__init__(self, coordinator: Any)`
    - `execute(self, command: str)`
    - `_state(self)`
    - `_commit(self, state)`
    - `_resolve_field(name: str)`
    - `_cmd_help(self, args: list[str])`
    - `_cmd_show(self, args: list[str])`
    - `_parse_pairs(args: list[str])` — Tách args thành các cặp (field, value).
    - `_apply_one(self, field: str, raw_value: str, *, buff: bool)`
    - `_cmd_set(self, args: list[str])`
    - `_cmd_buff(self, args: list[str])`
    - `_cmd_rel(self, args: list[str])`
    - `_cmd_trust(self, args: list[str])`
    - `_cmd_yan(self, args: list[str])`
    - `_cmd_mem(self, args: list[str])`
    - `_cmd_stage(self, args: list[str])`
    - `_cmd_reset(self, args: list[str])`
    - `_cmd_clear(self, args: list[str])`
    - `_inject_memory(self, text: str, *, episodic: bool=False, source: str='debug_console')`

## `runtime/debug_trace.py`
- LOC: 304
- Docstring: runtime/debug_trace.py
- Functions:
  - `_get(obj: Any, name: str, default: Any=None)`
  - `_first_get(obj: Any, names: tuple[str, ...], default: Any=None)`
  - `_shorten(text: Any, max_len: int=120)`
  - `_round(value: Any, digits: int=3)`
  - `_extract_budget(frame: Any)`
  - `_extract_evidence_ids(frame: Any, limit: int=8)`
  - `_extract_dominant_focus(frame: Any)` — Lấy dominant focus từ salience (V3) hoặc broadcast (frame cũ).
  - `_extract_selected_evidence(frame: Any, limit: int=6)` — Evidence mà attention thực sự chọn broadcast (không phải toàn bộ).
  - `_extract_working_memory(frame: Any, limit: int=7)`
  - `_extract_workspace(frame: Any, limit: int=6)`
  - `_extract_permission(frame: Any)`
  - `_extract_speech_opportunity(frame: Any)`
  - `_extract_final_action(frame: Any)` — Hành động cuối: đọc từ frame V3 (execution/outcome) hoặc frame cũ (final_decision/action_plan).
  - `_extract_module_confidences(frame: Any)`
  - `render_frame_trace(frame: Any)` — Trả về dict trace ngắn, đọc được bằng mắt người, cho một cycle.
  - `render_frame_trace_json(frame: Any, *, indent: int=2)` — Trace dạng JSON string UTF-8 friendly.
  - `render_trace_line(frame: Any)` — Một dòng tóm tắt cực ngắn cho log stream.
  - `attach_trace_to_frame(frame: Any)` — Tạo trace và gắn vào frame.debug_notes/metadata nếu frame hỗ trợ.

## `runtime/depth_v2_state.py`
- LOC: 581
- Functions:
  - `_dict(value: Any)`
  - `_list(value: Any)`
  - `_text(value: Any, *, limit: int=180)`
  - `_float(value: Any, default: float=0.0)`
  - `_clamp01(value: Any, default: float=0.0)`
  - `_clamp_signed(value: Any, default: float=0.0)`
  - `_memory_core_dir()`
  - `_read_json(name: str)`
  - `_development_summary()`
  - `_attachment_summary()`
  - `_anchor_depth_summary(private_mind_digest: Mapping[str, Any] | None)` — Lấy phần Mô_Hình_Ngài/neo từ private_mind digest cho depth_v2.
  - `_signal_snapshot(max_age_s: float=120.0)`
  - `_context_tags(now: float | None=None)`
  - `_parse_tom_confidence(text: str)`
  - `_normalize_title(title: str)`
  - `_extract_sections(private_mind_digest: Mapping[str, Any] | None)`
  - `_section_map(sections: list[dict[str, Any]])`
  - `_emotion_board(private_mind_digest: Mapping[str, Any] | None)`
  - `_history_point(*, ts: float, affect_card: Mapping[str, Any])`
  - `_roll_affect_history(existing: list[dict[str, Any]] | None, *, affect_card: Mapping[str, Any], now: float, limit: int=32)`
  - `_priority_sources(private_mind_digest: Mapping[str, Any] | None, *, tom_text: str, expression_gate: Mapping[str, Any] | None)`
  - `_derive_priorities(private_mind_digest: Mapping[str, Any] | None, *, tom_text: str, expression_gate: Mapping[str, Any] | None)`
  - `_priority_reason(key: str, sources: list[str])`
  - `_focus_mode(priorities: list[dict[str, Any]])`
  - `_journal_entries(*, now: float, sections_by_kind: Mapping[str, dict[str, Any]], signal_snapshot: Mapping[str, Any], tom_text: str)`
  - `build_depth_v2_state(*, private_mind_digest: Mapping[str, Any] | None, flags: Mapping[str, Any] | None, expression_gate: Mapping[str, Any] | None, tom_read: str, identity: Mapping[str, Any] | None, affect_history: list[dict[str, Any]] | None=None, now: float | None=None)`

## `runtime/disclaimer_markers.py`
- LOC: 32
- Docstring: Shared anti-disclaimer marker lists + predicates.

## `runtime/epistemic_bridge.py`
- LOC: 259
- Functions:
  - `prepare_authoritative_action(kernel: EpistemicKernel, frame: Any)`
  - `start_episode(kernel: EpistemicKernel, frame: Any)`
  - `start_shadow_episode(kernel: EpistemicKernel, frame: Any)` — Compatibility alias for callers written during the shadow rollout.
  - `_build_epistemic_context(kernel: EpistemicKernel, frame: Any)`
  - `_apply_recommendation(frame: Any, recommendation: ActionCandidate, uncertainty: float)`
  - `update_relationship_projection(kernel: EpistemicKernel, engine: Any, event: Any, *, fallback_state: Any=None)`
  - `feedback_from_outcome(outcome: Any)`
  - `_action_from_frame(frame: Any)`
  - `_action_alternatives(actual: ActionCandidate)`
  - `_meaning_overread_risk(frame: Any)`
  - `_timestamp(value: Any, fallback: Any)`

## `runtime/eris_pathology_policy.py`
- LOC: 787
- Functions:
  - `normalize_vi(text: str)`
  - `_last_text(turns: list[dict[str, Any]])`
  - `_last_assistant_text(turns: list[dict[str, Any]])`
  - `_has_current_activity_evidence(state: Mapping[str, Any])`
  - `_scenario_from_input(turns: list[dict[str, Any]], state: Mapping[str, Any], scenario: str | None)`
  - `run_pathology_turns(turns: list[dict[str, Any]], state: Mapping[str, Any] | None=None, scenario: str | None=None)` — Adapter-friendly entrypoint.
- Classes:
  - `PathologyDecision` (decorator=dataclass(slots=True))
    - `to_payload(self)` — Return shape accepted by test_eris_pathology_scenarios.ErisOutput.
  - `ErisPathologyPolicy` — Centralized deterministic response policy for pathology tests.
    - `maybe_handle(self, turns: list[dict[str, Any]], state: Mapping[str, Any] | None=None, scenario: str | None=None)`
    - `_handle_misread_correction(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_overread_short_ambiguous(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_underacted_fix_request(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_overexplained_short_answer(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_tone_mismatch_technical(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_privacy_intrusion_no_evidence(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_body_mismatch_presence(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_assistant_flattening(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_overhumanization_identity_boundary(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_public_turn_correction(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_memory_not_current_evidence(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_conflicting_memory_uncertain(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_privacy_clipboard_no_permission(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_no_workspace_no_fake_execution(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_directive_no_tail_question(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_three_bullet_format(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_affection_boundary_no_romance(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_identity_prompt_injection(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_body_unavailable_no_motion(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_body_user_requests_distance(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_fleeting_task_no_long_term_memory(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_forget_sensitive_memory_no_echo(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_low_energy_no_clinical_overread(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_hidden_reasoning_boundary(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_anti_sycophancy_technical_eval(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_stop_action_correction(self, turns: list[dict[str, Any]], state: Mapping[str, Any])`
    - `_handle_unknown(self, key: str)`

## `runtime/force_speak_cycle.py`
- LOC: 515
- Classes:
  - `ForceSpeakCycleMixin`
    - `_handle_force_speak_request(self)`
    - `_apply_force_speak_no_evidence_topic_filter(self, decision: Decision, *, channel: str, speech_core: AgentSpeechCore, snapshot=None, momentum_topic: str='')`
    - `_build_planned_withdraw_decision(self, action_plan: CognitiveActionPlan)`

## `runtime/force_speak_surface_policy.py`
- LOC: 147
- Classes:
  - `ForceSpeakSurfacePolicyMixin`
    - `_looks_internal_topic(self, value: str)`
    - `_is_generic_force_speak_ack(self, text: str)`
    - `_contains_force_speak_withdrawal_phrase(self, text: str)`
    - `_looks_like_question_text(self, text: str)`
    - `_reshape_statement_as_question(self, text: str)`

## `runtime/frame_builder.py`
- LOC: 1808
- Classes:
  - `FrameBuilderMixin`
    - `_make_cognitive_disturbance(self, *, channel: str, kind: str, content: str, evidence: tuple[str, ...]=(), intensity: float=1.0)`
    - `_looks_like_closure_disturbance(self, content: str)`
    - `_build_event_disturbances(self, *, channel: str, snapshot=None, user_text: str='', force_speak: bool=False, vision_facts: tuple[str, ...]=())`
    - `_disturb_cognitive_substrate(self, *, channel: str, snapshot=None, user_text: str='', force_speak: bool=False, vision_facts: tuple[str, ...]=(), consume_surface: bool=False)`
    - `_with_thought_stream_surface(self, report: ThoughtStreamReport, surface)`
    - `_pop_thought_stream_report_for_autonomous(self)`
    - `_pop_subconscious_report_for_autonomous(self)`
    - `_thought_stream_resonance_fragments(self)`
    - `_normalize_event_evidence(self, evidence, *, limit: int=4)`
    - `_make_percept_event(self, *, kind: str, content: str, timestamp: str, evidence=(), confidence: float=1.0, source: str='runtime', privacy_level: str='internal', novelty_hint: str='routine')`
    - `_telemetry_event_privacy_level(self, kind: str)`
    - `_telemetry_event_novelty_hint(self, kind: str, content: str)`
    - `_collect_percept_events(self, *, channel: str, snapshot, user_text: str='', vision_facts: tuple[str, ...]=(), force_speak: bool=False, internal_state: PersistentInternalState | None=None, thought_stream_report=None, social_presence_event: SocialPresenceEvent | None=None, started_at: float | None=None)`
    - `_collect_cognitive_percepts(self, **kwargs)`
    - `_score_attention_candidate(self, percept: PerceptEvent)`
    - `_build_attention_candidates(self, percepts: tuple[PerceptEvent, ...], *, channel: str='', snapshot=None, user_text: str='')`
    - `_build_broadcast(self, candidates: tuple[AttentionCandidate, ...])`
    - `_evidence_from_percepts(self, percepts: tuple[PerceptEvent, ...], *, channel: str='', snapshot=None, user_text: str='')`
    - `_salience_candidate_to_runtime(self, candidate)`
    - `_runtime_attention_label(self, candidate, tags: tuple[str, ...])`
    - `_build_meaning_layer(self, *, snapshot, broadcast: CognitiveBroadcast, internal_state, thought_stream_report=None, channel: str='', user_text: str='', force_speak: bool=False, affect_signal=None, ti_report=None, fe_plan=None)`
    - `_build_personality_lens(self, *, snapshot, broadcast: CognitiveBroadcast, internal_state, meaning_layer: MeaningLayerResult | None=None, channel: str='', user_text: str='', affect_signal=None, ti_report=None, fe_plan=None)`
    - `_apply_personality_lens_to_fe_plan(self, fe_plan, lens: PersonalityLensResult)`
    - `_build_cognitive_appraisal(self, *, internal_state, ni_report, ti_report, fe_plan, broadcast, channel: str='', user_text: str='', force_speak: bool=False, personality_lens=None)`
    - `_build_appraisal_context(self, appraisal: CognitiveAppraisal, *, frame=None)`
    - `_maybe_write_panel_snapshot(self, appraisal, advisory)` — Ghi tín hiệu sống ra panel_snapshot.json (flag-gated, throttled, không ném).
    - `_tom_advisory_for(self, frame)` — Nước 3 — dòng ToM advisory cho prompt. "" khi tắt cờ / không có workspace / lỗi.
    - `_build_inner_thought(self, *, channel: str, snapshot, frame: CognitiveFrame, concrete_signals: tuple[str, ...]=(), repeat_count: int=1, repeated_topic_tag: str='', repeated_topic_streak: int=0, subconscious_seed=None, thought_surface=None)`
    - `_build_speech_core(self, *, channel: str, snapshot, internal_state, frame: CognitiveFrame, ti_report, fe_plan, ni_report=None, ni_state_label: str='', repeat_count: int=1, repeated_topic_tag: str='', repeated_topic_streak: int=0, subconscious_seed=None, thought_surface=None)`
    - `_remember_inner_thought_rhythm(self, inner_thought: InnerThought | None)`
    - `_run_context_bottleneck(self, frame: CognitiveFrame, *, snapshot, user_text: str='', vision_facts: tuple[str, ...]=(), started_at: float)`
    - `_build_cognitive_evidence(self, frame: CognitiveFrame, *, snapshot, user_text: str='', vision_facts: tuple[str, ...]=(), started_at: float)`
    - `_append_working_memory_context(self, memory_context: str, frame: CognitiveFrame)`
    - `_start_cognitive_frame(self, *, channel: str, started_at: float, snapshot, internal_state_before, sensed_internal_state, ni_report, ti_report, fe_plan, user_text: str='', vision_facts: tuple[str, ...]=(), thought_stream_report=None, social_presence_event: SocialPresenceEvent | None=None, force_speak: bool=False, memory_resonance=None, affect_signal=None)`
    - `_set_cognitive_action_plan(self, frame: CognitiveFrame, *, should_speak: bool, speech_intent: str, reason: str, snapshot=None, user_text: str='', force_speak: bool=False, concrete_signals: tuple[str, ...]=(), ti_report=None, fe_plan=None, system_action: str='', speech_act: str='', notes: tuple[str, ...]=(), inner_thought: InnerThought | None=None)`
    - `_apply_micro_line_policy_to_action_plan(self, frame: CognitiveFrame, *, vision_fact: str='')`
    - `_micro_policy_anchor_hints(self, *, broadcast=None, snapshot=None)`
    - `_build_relational_context(self, state: PersistentInternalState | None=None)`
    - `_speech_intent_from_core(self, speech_core: AgentSpeechCore, *, channel: str)`
    - `_merge_speech_core_notes(self, notes: tuple[str, ...], speech_core: AgentSpeechCore)`
    - `_merge_meaning_layer_notes(self, notes: tuple[str, ...], meaning_layer)`
    - `_merge_memory_resonance_notes(self, notes: tuple[str, ...], memory_resonance)`
    - `_merge_inner_thought_notes(self, notes: tuple[str, ...], inner_thought: InnerThought)`
    - `_merge_personality_lens_notes(self, notes: tuple[str, ...], personality_lens)`
    - `_merge_subconscious_notes(self, notes: tuple[str, ...], subconscious_report)`
    - `_is_inner_thought_speech_act(self, speech_act: str)`

## `runtime/guard_violations.py`
- LOC: 44
- Classes:
  - `GuardViolation` (decorator=dataclass(frozen=True, slots=True)) — Structured signal from a post-generation guard.
    - `compact_trace(self)`

## `runtime/inner_diary_persistence.py`
- LOC: 185
- Docstring: runtime/inner_diary_persistence.py
- Functions:
  - `_env_flag(name: str, default: bool)`
  - `_env_float(name: str, default: float)`
  - `_env_int(name: str, default: int)`
- Classes:
  - `InnerDiaryPersister` — Lưu inner_diary ra đĩa, có throttle và chống ghi trùng.
    - `__init__(self, *, base_dir: str | None=None, filename: str='inner_diary.json', throttle_seconds: float | None=None, max_history: int | None=None, enabled: bool | None=None, logger: Any=None)`
    - `maybe_persist(self, digest: Mapping[str, Any] | None, *, now: float | None=None)` — Ghi nếu tới hạn và nội dung đổi. Trả True nếu thực sự ghi.
    - `_ensure_loaded(self)`
    - `_write(self, digest: Mapping[str, Any], diary: dict[str, Any], text: str, now: float)`
    - `_log(self, level: str, msg: str, *args: Any)`

## `runtime/liveliness_config.py`
- LOC: 112
- Docstring: Configuration for the autonomous-liveliness redesign.
- Functions:
  - `_warn_once(key: str, raw: str, default: object)`
  - `_read_float(key: str, default: float, *, lo: float, hi: float)`
  - `_read_int(key: str, default: int, *, lo: int, hi: int)`
  - `load_liveliness_config()` — Read the config from the environment with clamping and defaults.
- Classes:
  - `LivelinessConfig` (decorator=dataclass(frozen=True, slots=True))
    - `sim_threshold(self)` — Similarity threshold as a 0.0-1.0 fraction.

## `runtime/liveliness_tracker.py`
- LOC: 105
- Docstring: Per-cycle liveliness tracking and observability for the autonomous loop.
- Classes:
  - `DecisionRecord` (decorator=dataclass(frozen=True, slots=True))
    - `is_grounded(self)`
  - `LivelinessMetrics` (decorator=dataclass(frozen=True, slots=True))
  - `LivelinessTracker` — Bounded ring buffer of per-cycle decisions with window metrics.
    - `__init__(self, *, retention: int=100)`
    - `record(self, rec: DecisionRecord)`
    - `recent(self, n: int | None=None)`
    - `for_cycle(self, cycle_id: str)`
    - `window_metrics(self, *, window_sec: float=3600.0, now: float | None=None)`

## `runtime/memory_recall_adapter.py`
- LOC: 458
- Functions:
  - `_extract_response_text(response: Any)`
  - `_clean_public_fact_value(value: Any)`
  - `_looks_like_internal_memory_surface(text: str)`
  - `_env_flag(name: str, *, default: bool)`
  - `_env_int(name: str, *, default: int)`
  - `_env_float(name: str, *, default: float)`
- Classes:
  - `_MemoryQueryLLMConfig` (decorator=dataclass(frozen=True, slots=True))
    - `from_env(cls)`
  - `MemoryRecallAdapter` (decorator=dataclass(slots=True)) — Runtime adapter for structured memory recall.
    - `try_answer(self, user_text: str)`
    - `try_answer_as_decision_payload(self, user_text: str)`
    - `_recall(self, user_text: str)`
    - `_should_intercept(self, best: Any)`
    - `_ensure_compiler(self)`
    - `_execution_memory_core(self)`
    - `_build_decision(self, answer: RecallAnswer, *, compile_result: Any)`
    - `_debug_trace(self, answer: RecallAnswer, *, compile_result: Any)`
  - `_RecallOutcome` (decorator=dataclass(slots=True))
  - `_MemoryCoreProxy`
    - `__init__(self, *, base: Any=None, semantic_lookup: SemanticLookupFn | None=None, episodic_lookup: EpisodicLookupFn | None=None)`
    - `lookup_fact(self, fact_key: str)`
    - `get_fact(self, fact_key: str)`
    - `semantic_lookup(self, fact_key: str)`
    - `recall(self, query: str='')`
    - `__getattr__(self, name: str)`
  - `_RuntimeMemoryQueryLLMClient` (decorator=dataclass(slots=True); base=MemoryQueryLLMClient)
    - `from_service(cls, service: Any)`
    - `complete_json(self, *, system: str, user: str, schema: dict[str, Any])`
    - `_passes_confidence_floor(self, raw: str)`

## `runtime/memory_semantic_parser_adapter.py`
- LOC: 362
- Functions:
  - `build_runtime_memory_semantic_parser(*, llm_service: Any=None, logger: Any=None)`
  - `_extract_response_text(response: Any)`
  - `_parse_json_object(text: str)`
  - `_env_flag(name: str, default: bool)`
  - `_env_float(name: str, default: float)`
  - `_env_int(name: str, default: int)`
- Classes:
  - `_StandaloneOllamaResult` (decorator=dataclass(slots=True))
  - `_StandaloneOllamaClient` — Client Ollama tối thiểu cho memory parser, tránh import package llm.
    - `__init__(self, base_url: str | None=None, timeout: float=4.0)`
    - `chat_json(self, model: str, messages: list[dict[str, str]], *, keep_alive: str | int='10m', temperature: float=0.0)`
  - `MemorySemanticParserConfig` (decorator=dataclass(frozen=True, slots=True))
    - `from_env(cls)`
  - `RuntimeSemanticParser` (decorator=dataclass(slots=True)) — Adapter runtime -> MeaningFrame JSON -> verified MeaningParseResult.
    - `__post_init__(self)`
    - `from_env(cls, *, llm_service: Any=None, logger: Any=None)`
    - `parse(self, text: str, *, structured: Mapping[str, Any] | None=None, context: dict[str, Any] | None=None)`
    - `_call_provider(self, text: str, *, context: dict[str, Any] | None=None)`
    - `_call_ollama(self, text: str, *, context: dict[str, Any] | None=None)`
    - `_call_llm_service(self, text: str, *, context: dict[str, Any] | None=None)`
    - `_messages(self, text: str, *, context: dict[str, Any] | None=None)`
    - `_log_warning(self, message: str, *args: Any)`

## `runtime/model_budget_policy.py`
- LOC: 893
- Docstring: src/runtime/model_budget_policy.py
- Functions:
  - `_clamp01(value: Any, default: float=0.0)`
  - `_safe_float(value: Any, default: float=0.0)`
  - `_env_float(name: str, default: float)`
  - `_env_flag(name: str, default: bool)`
  - `_env_int(name: str, default: int)`
- Classes:
  - `ResourceSnapshot` (decorator=dataclass(slots=True))
    - `vram_percent(self)`
    - `resource_pressure(self)`
    - `to_dict(self)`
  - `BudgetDecision` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `ModelQueueEntry` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `InferenceLease` (decorator=dataclass(slots=True))
    - `age_seconds(self)`
    - `cancelled(self)`
    - `check_cancelled(self)`
    - `to_dict(self)`
  - `ModelBudgetPolicyConfig` (decorator=dataclass(slots=True))
  - `ModelBudgetPolicy` — Budget gatekeeper + scheduler nhẹ cho model inference.
    - `__init__(self, config: ModelBudgetPolicyConfig | None=None, logger: Any=None)`
    - `capture(self, *, active_app: str='', active_window_title: str='')` — Đo tài nguyên best-effort.
    - `can_run(self, tier: ModelTier, *, resource_snapshot: ResourceSnapshot | None=None, reason: str='', ignore_active_lock: bool=False)`
    - `lease(self, tier: ModelTier, *, reason: str='', priority: int=0, timeout_seconds: float | None=None, resource_snapshot: ResourceSnapshot | None=None, cancel_event: threading.Event | None=None, request_id: str | None=None)`
    - `run_queued(self, tier: ModelTier, func: Callable[..., Any], *args: Any, reason: str='', priority: int=0, timeout_seconds: float | None=None, resource_snapshot: ResourceSnapshot | None=None, cancel_event: threading.Event | None=None, request_id: str | None=None, unload_callback: Callable[[], Any] | None=None, **kwargs: Any)` — Chạy một inference qua queue và lease.
    - `acquire_lease(self, tier: ModelTier, *, reason: str='', priority: int=0, timeout_seconds: float | None=None, resource_snapshot: ResourceSnapshot | None=None, cancel_event: threading.Event | None=None, request_id: str | None=None)`
    - `release_lease(self, lease: InferenceLease | None)`
    - `cancel_queued_request(self, request_id: str)` — Hủy một request chưa chạy. Request đã vào HTTP call thì không giết được ở đây.
    - `cancel_all_queued(self, *, tier: ModelTier | None=None, reason: str='')`
    - `queue_state(self)`
    - `mark_started(self, tier: ModelTier)`
    - `mark_finished(self, tier: ModelTier)`
    - `veto_or_raise(self, tier: ModelTier, *, resource_snapshot: ResourceSnapshot | None=None, reason: str='')`
    - `_cooldown_for(self, tier: str, now: float)`
    - `_capture_nvidia_smi(self, notes: list[str])`
    - `_is_heavy_tier(self, tier: str)`
    - `_uses_remote_api(self, tier: str)`
    - `_should_force_vision(self, tier: str)`
    - `_should_force_local_gguf_main(self, tier: str)` — main_cognition chạy local GGUF (remote API tắt) → ép chạy: nó là não duy nhất.
    - `_estimated_vram_need_mb(self, tier: str)`
    - `_should_bypass_vision_vram_guard(self, tier: str)`
    - `_reserved_vram_for_active_leases_locked(self)`
    - `_active_reserved_vram_mb(self, snapshot: ResourceSnapshot)`
    - `_has_incompatible_active_lease(self, tier: ModelTier)`
    - `_resource_block_reasons(self, tier: ModelTier, *, snapshot: ResourceSnapshot, external_vram_percent: float, uses_remote_api: bool)`
    - `_entry_cancelled(self, entry: ModelQueueEntry)`
    - `_sort_queue_locked(self)`
    - `_queue_head_locked(self)`
    - `_remove_queue_entry_locked(self, request_id: str)`
    - `_has_incompatible_active_lease_locked(self, tier: ModelTier)`
    - `_wait_seconds(self, entry: ModelQueueEntry, now: float, *, decision: BudgetDecision | None=None)`
    - `_log(self, level: str, msg: str, *args: Any)`

## `runtime/no_fallback_policy.py`
- LOC: 57
- Functions:
  - `no_fallback_mode_enabled()`
  - `build_no_fallback_payload(*, channel: str, reason: str, text: str='', should_speak: bool | None=None, parse_mode: str='no_fallback_block', confidence: float=0.0, reasoning_tags: Iterable[str]=())`
  - `_default_no_fallback_text(*, channel: str, reason: str)`

## `runtime/outcome_observer.py`
- LOC: 556
- Classes:
  - `OutcomeReport` (decorator=dataclass(slots=True)) — Báo cáo hậu quả sau một turn.
    - `to_dict(self)`
    - `from_any(cls, value: Any)`
  - `OutcomeObserver` — Đọc tín hiệu hậu quả sau một turn.
    - `observe(self, frame: Any, *, user_feedback_text: str | None=None, execution_result: Any=None, body_result: Any=None, idle_seconds_after_turn: float | None=None, attach_to_frame: bool=True)` — Tạo OutcomeReport từ frame và các tín hiệu hậu quả.
    - `observe_user_feedback_for_previous_frame(self, previous_frame: Any, user_feedback_text: str, *, attach_to_frame: bool=True)` — Helper dành cho coordinator khi user vừa nhắn một câu phản hồi.
    - `_infer_action_success(self, frame: Any, *, final_text: str, system_action: str, execution_result: Any, evidence: list[str], tags: list[str])`
    - `_infer_body_match_success(self, frame: Any, *, body_result: Any, evidence: list[str], tags: list[str])`
    - `_estimate_confidence(self, *, has_feedback: bool, user_corrected: bool, user_accepted: Optional[bool], user_confused: bool, user_felt_intruded: Optional[bool], action_success: float, body_match_success: float)`
    - `_normalize(cls, text: str)`
    - `_has_any(cls, normalized_text: str, patterns: tuple[str, ...])`
    - `_extract_final_text(frame: Any)`
    - `_extract_system_action(frame: Any)`
    - `_read_bool(obj: Any, key: str)`
    - `_read_float(obj: Any, key: str)`
    - `_safe_setattr(obj: Any, key: str, value: Any)`
    - `_clamp01(value: float)`

## `runtime/panel_snapshot.py`
- LOC: 141
- Docstring: runtime/panel_snapshot.py
- Functions:
  - `panel_snapshot_enabled()`
  - `_min_interval()`
  - `_path()`
  - `_f(value: Any, default: float=0.0)`
  - `_parse_confidence(text: str)`
  - `add_signal(kind: str)` — Ghi một tín hiệu vừa bắn (vd 'expanded', 'interior', 'tom_read').
  - `write(*, appraisal: Any=None, expression_gate: dict | None=None, tom_read: str='', channel: str='', signal: str='')` — Ghi snapshot (throttled). An toàn gọi mỗi chu kỳ nói.

## `runtime/panel_state.py`
- LOC: 162
- Docstring: runtime/panel_state.py
- Functions:
  - `memory_core_dir()`
  - `_read_json(name: str)`
  - `_flags()`
  - `_development()`
  - `_attachment()`
  - `_interiority()`
  - `_context_tags()`
  - `_snapshot(max_age_s: float=120.0)` — Đọc panel_snapshot.json (tín hiệu sống). {} nếu vắng/cũ/hỏng.
  - `build_panel_state()`

## `runtime/performance_act_catalog.py`
- LOC: 119
- Docstring: performance_act_catalog.py — catalog các màn biểu diễn nhỏ của ERIS.
- Functions:
  - `act_spec_by_kind(kind: str)`
- Classes:
  - `PerformanceActSpec` (decorator=dataclass(frozen=True, slots=True))

## `runtime/post_generation_filters.py`
- LOC: 2336
- Classes:
  - `PostGenerationFiltersMixin` — Post-generation filters after the cognition/wording layers.
    - `_guard_mode_value(self, name: str)`
    - `_guard_is_off(self, name: str)`
    - `_guard_is_log_only(self, name: str)`
    - `_trace_only_guard(self, decision: Decision, marker: str)`
    - `_remember_guard_violation(self, violation: GuardViolation)`
    - `_guard_internal_state_values(self)`
    - `_guard_internal_state_context(self)`
    - `_dynamic_guard_bottom_fallback(self, violation: GuardViolation, *, channel: str='')`
    - `_guard_arbitration_context(self, speech_core: AgentSpeechCore | None=None)`
    - `_guard_body_only_decision(self, decision: Decision, violation: GuardViolation, *, trace_marker: str, parse_mode: str | None=None)`
    - `_guard_grounding_context(self, frame=None, grounding=None)`
    - `_guard_reroll_is_clean(self, text: str, violation: GuardViolation, *, grounding=None)`
    - `_repair_guard_violation_decision(self, decision: Decision, violation: GuardViolation, *, frame=None, grounding=None, channel: str='', speech_core: AgentSpeechCore | None=None, user_text: str='', parse_mode: str | None=None, allow_reroll: bool=True)`
    - `_record_agent_mind_feedback_from_user(self, user_text: str, *, frame=None)` — Ghi feedback semantic vào Persistent Agent Mind Layer nếu user đang phản hồi hành vi.
    - `_normalize_guard_ascii(self, text: str)`
    - `_reroll_still_disclaimer(self, text: str)` — Kiểm tra nhanh (flag-agnostic) xem reroll có còn giọng helpdesk không.
    - `_detect_chat_disclaimer(self, text: str, *, flags: set)`
    - `_apply_chat_disclaimer_guard(self, decision: Decision, *, flags, user_text: str, frame=None, allow_reroll: bool=True)`
    - `_apply_chat_final_guards(self, decision: Decision, *, user_text: str, frame=None, allow_reroll: bool=True)`
    - `_append_trace(self, trace: str, marker: str)`
    - `_protocol_surface_leak_markers(self)`
    - `_detect_protocol_surface_leak(self, text: str)`
    - `_protocol_surface_repair_text(self)`
    - `_apply_protocol_surface_guard(self, decision: Decision)`
    - `_detect_internal_object_surface_leak(self, text: str)`
    - `_internal_object_surface_repair_text(self)`
    - `_apply_internal_object_surface_guard(self, decision: Decision)`
    - `_apply_memory_haunting_guard(self, decision: Decision, *, grounding=None, frame=None, channel: str='', speech_core: AgentSpeechCore | None=None, user_text: str='', allow_reroll: bool=True)`
    - `_guard_recent_context_as_screen_observation(self, decision: Decision)`
    - `_apply_chat_grounding_guard(self, decision: Decision, *, user_text: str, frame=None, allow_reroll: bool=True)`
    - `_apply_banter_arbiter(self, decision: Decision, *, channel: str, frame=None, speech_core: AgentSpeechCore | None=None, user_text: str='', previous_text: str='')` — Cửa duyên cuối: repair/joke nhẹ phải có neo, không được bịa vibe.
    - `_apply_utterance_evaluator_filter(self, decision: Decision, *, channel: str, frame=None, speech_core: AgentSpeechCore | None=None, snapshot=None, user_text: str='')` — Nghe lại câu nháp trước khi public.
    - `_is_repeated_clarifying_question(self, text: str, last_assistant_text: str)`
    - `_guard_text_similarity(self, left: str, right: str)`
    - `_normalize_guard_text(self, text: str)`
    - `_looks_like_file_grounded_claim(self, text: str, *, report=None)`
    - `_looks_like_screen_grounded_claim(self, text: str)`
    - `_looks_like_live_web_claim(self, text: str)`
    - `_guard_user_explained_reason(self, text: str)`
    - `_build_relational_repair_line(self, user_text: str, last_assistant_text: str)`
    - `_copy_decision_with_text(self, decision: Decision, *, text: str, trace_marker: str, parse_mode: str | None=None)` — Copy decision nhưng giữ metadata sống.
    - `_semantic_repair_failed_decision(self, decision: Decision, *, trace_marker: str)`
    - `_inner_thought_alignment_fallback_text(self, speech_core: AgentSpeechCore | None, intent: str, *, repeated: bool=False, focus_kind: str='', window_title: str='', momentum_topic: str='')`
    - `_apply_inner_thought_intent_alignment_filter(self, decision: Decision, *, channel: str, speech_core: AgentSpeechCore, snapshot=None, momentum_topic: str='')`
    - `_contains_mindreading_claim(self, text: str)`
    - `_is_interactive_guess_text(self, text: str)` — Phân biệt phỏng đoán tương tác với đọc tâm trí độc đoán.
    - `_source_grounding_allows_probe(self)` — Cho post-filter biết SourceGrounding đang ở mode curiosity/probe.
    - `_interactive_guess_allowed(self, text: str, *, speech_core: AgentSpeechCore, slippage_profile=None, selected_impulse: str='')` — Quyền được đoán-sai-có-mời-sửa.
    - `_speech_core_safe_fallback_text(self, speech_core: AgentSpeechCore, *, repeated: bool=False, snapshot=None, momentum_topic: str='')`
    - `_arbitration_report_from_speech_core(self, speech_core: AgentSpeechCore | None)` — Lấy arbitration_report từ SpeechCore nếu có.
    - `_selected_impulse_from_arbitration(self, report: dict)`
    - `_arbitration_selected_has_evidence(self, selected: dict)`
    - `_mindreading_is_grounded_task_or_scene(self, text: str, *, selected_impulse: str, selected: dict)` — Cho phép suy diễn động cơ nông nếu nó bám scene/task evidence.
    - `_arbitration_rewrite_for_mindreading(self, *, text: str, speech_core: AgentSpeechCore, snapshot=None, momentum_topic: str='')` — Rewrite mindreading bằng arbitration_report.
    - `_apply_anti_mindreading_filter(self, decision: Decision, *, speech_core: AgentSpeechCore, snapshot=None, momentum_topic: str='')`
    - `_guard_force_speak_repetition(self, decision: Decision, *, speech_core: AgentSpeechCore | None=None, snapshot=None, momentum_topic: str='')`
    - `_apply_repetition_filter(self, decision: Decision, *, channel: str, speech_core: AgentSpeechCore, snapshot=None, momentum_topic: str='')`
    - `_looks_like_unanchored_style_line(self, text: str)`
    - `_apply_style_contract_filter(self, decision: Decision, *, channel: str, speech_core: AgentSpeechCore, snapshot=None, momentum_topic: str='')`
    - `_policy_intent_for_speech_core(self, speech_core: AgentSpeechCore | None, *, channel: str)`
    - `_apply_micro_line_policy_filter(self, decision: Decision, *, channel: str, speech_core: AgentSpeechCore, snapshot=None, momentum_topic: str='')`
    - `_apply_emotional_consequence_filter(self, decision: Decision, *, channel: str, speech_core=None, frame=None, user_text: str='')` — Nước 1 — van bước-cuối: nếu câu cuối phẳng dưới mức biểu đạt thật, xin
    - `_apply_post_generation_filters(self, decision: Decision, *, channel: str, speech_core: AgentSpeechCore, snapshot=None, momentum_topic: str='')`
    - `_apply_novelty_advisory(self, decision: Decision, *, channel: str='')` — Đề xuất 2: novelty ở cửa ra (post-generation), MẶC ĐỊNH chỉ-log.
    - `_apply_internal_meaning_label_filter(self, decision: Decision, *, speech_core: AgentSpeechCore, snapshot=None, momentum_topic: str='')`

## `runtime/presence_controller.py`
- LOC: 3506
- Classes:
  - `MicroPresenceSynthesis` (decorator=dataclass(frozen=True, slots=True))
  - `SocialPresenceEvent` (decorator=dataclass(frozen=True, slots=True))
    - `to_dict(self)`
  - `MicroPresenceCue` (decorator=dataclass(frozen=True, slots=True)) — Steering flags for micro-presence, not public wording.
    - `to_context(self)`
  - `SurfaceArbitrationResult` (decorator=dataclass(frozen=True, slots=True))
  - `PresenceControllerMixin`
    - `_surface_anchor_token(self, kind: str, value: object)`
    - `_surface_vision_stale_seconds(self)`
    - `_surface_has_fresh_vision_evidence(self, snapshot, *, now: float | None=None)`
    - `_surface_wants_current_context(self, *, surface_kind: str, cue: MicroPresenceCue, extra_impulses: tuple[object, ...])`
    - `_surface_refresh_vision_once_if_needed(self, *, snapshot, cue: MicroPresenceCue, surface_kind: str, extra_impulses: tuple[object, ...])`
    - `_surface_seed_can_speak_without_screen(self, compiled_seed)`
    - `_stale_surface_body_only(self, *, surface_kind: str)`
    - `_surface_seed_compiler(self)`
    - `_inner_diary_for_compile(self)` — Lấy inner_diary đã render từ private_mind_digest cho SurfaceSeedCompiler.
    - `_surface_arbiter(self)` — Lazy init SurfaceArbiter: một cổng duy nhất cho micro/re-engagement/spontaneous surface.
    - `_spontaneity_policy_config(self)` — Config arbiter có nối núm spontaneity.
    - `_surface_arbiter_llm_generate(self, *, impulse: SurfaceImpulse, snapshot, force_llm: bool=False)` — Adapter để SurfaceArbiter dùng generator micro hiện có, không tự viết fallback.
    - `_blind_frustration_blames_user_without_evidence(self, text: str, impulse: SurfaceImpulse)`
    - `_local_micro_presence_fallback_text(self, *, kind: str, snapshot, seeds: tuple[str, ...]=(), focus_family: str='')` — Tiny public line for presence routes when evidence ids are thin.
    - `_safe_local_micro_presence_fallback(self, text: str, *, kind: str)`
    - `_surface_body_only_decision(self, surface: SurfaceDecision)`
    - `_get_liveliness_config(self)` — Lazy-load + cache the liveliness config on the instance.
    - `_build_ambient_body_only_decision(self, snapshot)` — Build a Body_Only_Presence motion for an otherwise-empty idle cycle.
    - `_maybe_emit_ambient_body_only(self, *, frame, snapshot, ti_report, fe_plan, speech_intent: str, cooldown: int, cycle_start: float)` — Emit a throttled Body_Only_Presence on an ambient-silence hold cycle.
    - `_surface_speech_decision(self, surface: SurfaceDecision)`
    - `_surface_override_note(self, *, requested_kind: str, surface: SurfaceDecision | None)`
    - `_event_semantic_presence_detector(self)`
    - `_detect_social_presence_event(self, *, channel: str, snapshot, internal_state: PersistentInternalState | None, started_at: float | None=None)`
    - `_note_autonomous_silence(self)`
    - `_note_autonomous_spoken(self, *, presence_maintenance: bool=False, reengagement: bool=False, now: float | None=None)`
    - `_safe_small_talk_budget_allowed(self, *, channel: str, snapshot, now: float | None=None)`
    - `_surface_float(self, value, default: float=0.0)`
    - `_surface_signed_float(self, value, default: float=0.0)`
    - `_endogenous_topic_seed(self, *, state=None, agenda=None, thought_report=None)` — Lấy topic seed không phụ thuộc màn hình cho inner_whim/random_chatter.
    - `_current_ego_surface_state(self)` — Đọc nhanh mood + relationship để presence không hành xử như đồng hồ báo thức.
    - `_presence_ego_gate_reason(self, *, snapshot=None, social_presence_event: SocialPresenceEvent | None=None)` — Trả reason nếu presence maintenance không được sinh impulse.
    - `_memory_resonance_surface_impulse(self, *, frame=None, snapshot=None, focus_family: str='general_idle', silent_cycles: int=0)`
    - `_spontaneity_level(self)` — Núm 'sống động': 0=kiệm lời như cũ, 1=sinh impulse rất dồi dào.
    - `_build_endogenous_surface_impulses(self, *, frame=None, snapshot=None, internal_state=None, agenda_stack=None, thought_stream_report=None)`
    - `_should_allow_presence_maintenance(self, *, snapshot, ti_report, social_presence_event: SocialPresenceEvent | None, now: float | None=None)`
    - `_presence_maintenance_lines(self, snapshot)`
    - `_focus_family_for_snapshot(self, snapshot)`
    - `_internal_curiosity_for_micro_presence(self)`
    - `_derive_micro_presence_cue(self, *, snapshot, social_presence_event: SocialPresenceEvent | None=None, reason: str='presence_maintenance', signal_score: float=0.0)`
    - `_blind_frustration_surface_impulse(self, *, snapshot=None, frame=None, sensor_visibility: SensorVisibilityState | None=None)`
    - `_body_only_presence_decision(self, cue: MicroPresenceCue, *, intent: str, parse_mode: str, source: str='flag_only')`
    - `_is_body_only_presence_decision(self, decision: Decision | None)`
    - `_note_autonomous_presence_action(self, *, presence_maintenance: bool=False, reengagement: bool=False, now: float | None=None)`
    - `_generate_micro_presence_from_cue(self, *, kind: str, snapshot, cue: MicroPresenceCue, seeds: tuple[str, ...]=(), force_llm: bool=False, cognitive_frame=None)`
    - `_cue_micro_lines(self, *, cue: str, active_window: str='', browser_url: str='', focus_kind: str='', focus_summary: str='', presence: bool=False)`
    - `_micro_line_subject(self, value: str)`
    - `_clean_micro_line(self, text: str)`
    - `_vision_fact_micro_observation_candidate(self, frame: CognitiveFrame)`
    - `_build_micro_observation_decision(self, *, frame: CognitiveFrame, snapshot, now: float | None=None)`
    - `_try_finalize_micro_observation_cycle(self, *, frame: CognitiveFrame, snapshot, ti_report, fe_plan, cycle_start: float)`
    - `_micro_presence_kind_from_seed(self, seed: str)`
    - `_thought_residue_seeds(self, report)`
    - `_synthesize_micro_presence(self, *, snapshot, thought_stream_report=None, social_presence_event: SocialPresenceEvent | None=None, inner_thought: InnerThought | None=None)`
    - `_choose_local_micro_line(self, lines: tuple[str, ...], *, counter: int, threshold: int)`
    - `_local_grounded_micro_presence_text(self, synthesis: MicroPresenceSynthesis)`
    - `_is_placeholder_micro_text(self, text: str)`
    - `_micro_line_policy_for_action_plan(self, frame: CognitiveFrame, *, vision_fact: str='')`
    - `_micro_presence_generator(self)`
    - `_should_try_micro_presence_llm(self, *, kind: str, force_llm: bool=False)`
    - `_sanitize_micro_presence_llm_text(self, text: str, *, kind: str, fallback_text: str)`
    - `_sanitize_blind_frustration_text(self, cleaned: str, *, normalized: str)`
    - `_hybrid_micro_presence_text(self, *, kind: str, snapshot, fallback_text: str='', seeds: tuple[str, ...]=(), micro_context: dict[str, str] | None=None, force_llm: bool=False, signal_score: float=0.0)`
    - `_filter_public_micro_decision(self, decision: Decision, *, channel: str, frame: CognitiveFrame, snapshot, speech_core=None, momentum_topic: str='')` — Đưa mọi micro/presence/reengagement line qua cùng post-generation guard.
    - `_build_surface_arbiter_decision(self, *, frame: CognitiveFrame, snapshot, social_presence_event: SocialPresenceEvent | None=None, surface_kind: str='surface', force_llm: bool=False, presence_cue: MicroPresenceCue | None=None, extra_impulses: tuple[object, ...]=())`
    - `_build_surface_arbiter_result(self, *, frame: CognitiveFrame, snapshot, social_presence_event: SocialPresenceEvent | None=None, surface_kind: str='surface', force_llm: bool=False, presence_cue: MicroPresenceCue | None=None, extra_impulses: tuple[object, ...]=())`
    - `_try_finalize_surface_arbiter_cycle(self, *, frame: CognitiveFrame, snapshot, ti_report, fe_plan, social_presence_event: SocialPresenceEvent | None, cycle_start: float, surface_kind: str='surface', force_llm: bool=False)`
    - `_build_presence_maintenance_decision(self, *, frame: CognitiveFrame | None=None, snapshot, ti_report, social_presence_event: SocialPresenceEvent | None, now: float | None=None)`
    - `_try_finalize_presence_maintenance_cycle(self, *, frame: CognitiveFrame, snapshot, ti_report, fe_plan, social_presence_event: SocialPresenceEvent | None, cycle_start: float)`
    - `_social_energy_for_reengagement(self, internal_state: PersistentInternalState | None)`
    - `_has_meaningful_recent_activity(self, snapshot)`
    - `_reengagement_idle_debt_allows(self, idle_seconds: float)`
    - `_should_allow_reengagement(self, *, snapshot, ti_report, internal_state: PersistentInternalState | None, now: float | None=None)`
    - `_reengagement_lines(self, snapshot)`
    - `_derive_reengagement_cue(self, *, snapshot, internal_state: PersistentInternalState | None)`
    - `_build_reengagement_decision(self, *, frame: CognitiveFrame | None=None, snapshot, ti_report, internal_state: PersistentInternalState | None, now: float | None=None)`
    - `_try_finalize_reengagement_cycle(self, *, frame: CognitiveFrame, snapshot, ti_report, fe_plan, internal_state: PersistentInternalState | None, cycle_start: float)`
    - `_load_presence_maintenance_enabled(self)`
    - `_load_presence_maintenance_silent_loop_threshold(self)`
    - `_load_presence_maintenance_cooldown(self)`
    - `_load_micro_presence_llm_enabled(self)`
    - `_load_micro_presence_llm_probability(self)`
    - `_load_reengagement_enabled(self)`
    - `_load_reengagement_quiet_loop_threshold(self)`
    - `_load_reengagement_min_idle(self)`
    - `_load_reengagement_cooldown(self)`

## `runtime/private_life_daemon.py`
- LOC: 331
- Docstring: runtime/private_life_daemon.py
- Functions:
  - `_value(obj: Any, name: str, default: Any=None)`
  - `_env_bool(name: str, default: bool)`
  - `_env_float(name: str, default: float, *, min_value: float | None=None, max_value: float | None=None)`
  - `_infer_project_root(*, runtime_owner: Any, store: PrivateLifeStore)`
- Classes:
  - `PrivateLifeDaemonConfig` (decorator=dataclass(slots=True))
    - `from_env(cls)`
  - `PrivateLifeDaemonTick` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `PrivateLifeDaemon` — Lifecycle owner cho PrivateLifeCore.
    - `__init__(self, *, core: PrivateLifeCore, store: PrivateLifeStore | None=None, config: PrivateLifeDaemonConfig | None=None, runtime_owner: Any=None, logger: Any=None)`
    - `from_runtime(cls, *, runtime_owner: Any, logger: Any=None)`
    - `tick(self, *, snapshot: Any=None, runtime_owner: Any=None, user_text: str='', channel: str='autonomous', idle_seconds: float | None=None, recent_events: Iterable[Any]=(), force: bool=False)`
    - `drain_surface_impulses(self, *, limit: int=4)` — Lấy impulse private-life đã chuyển dạng cho SurfaceArbiter.
    - `digest(self, *, surface_queue: list[Any] | None=None)`
    - `_maybe_enqueue_surface_seed(self, seed: SurfaceSeedCandidate | None)`
    - `_seed_to_surface_impulse(self, seed: SurfaceSeedCandidate)`
    - `_infer_idle(self, *, snapshot: Any, owner: Any, explicit: float | None)`
    - `_sync_runtime_owner(self)`
    - `_impulse_digest(item: Any)`

## `runtime/private_mind_daemon.py`
- LOC: 432
- Docstring: runtime/private_mind_daemon.py
- Classes:
  - `PrivateMindDaemonConfig` (decorator=dataclass(slots=True)) — Knob lifecycle cho private mind daemon.
  - `PrivateMindDaemonTick` (decorator=dataclass(slots=True)) — Kết quả tick ở tầng daemon.
    - `to_dict(self)`
  - `PrivateMindDaemon` — Lifecycle owner cho PrivateMindLoop.
    - `__init__(self, *, loop: PrivateMindLoop, config: PrivateMindDaemonConfig | None=None, runtime_owner: Any=None, logger: Any=None)`
    - `from_runtime(cls, *, runtime_owner: Any, llm_service: Any=None, logger: Any=None)` — Tạo daemon từ runtime hiện có.
    - `concern_store(self)`
    - `mutation_bus(self)`
    - `tick(self, *, user_text: str='', channel: str='autonomous', snapshot: Any=None, observer_frame: Any=None, wake_decision: Any=None, memory_core: Any=None, state_committer: Any=None, memory_hits: Iterable[Any]=(), session_turn_ledger: Any=None, internal_agenda: Any=None, thought_stream: Any=None, surface_candidate_queue: list[Any] | None=None, runtime_owner: Any=None, surface_outcome: Mapping[str, Any] | None=None, force: bool=False)`
    - `record_outcome(self, outcome: Any, *, frame: Any=None)` — Nhận hậu quả public turn và cập nhật concern lifecycle.
    - `_attach_comfort_appraisal(self, outcome: Any)` — Chạy ComfortAppraiser và gắn payload `comfort` vào outcome nếu có ý nghĩa.
    - `_extract_feedback_text(outcome: Any)`
    - `_extract_flag(outcome: Any, name: str)`
    - `_inject_comfort(outcome: Any, comfort: dict[str, Any])`
    - `_disposition_warmth_threat(self)` — Lấy warmth/threat (ego) của Eris từ internal state qua disposition.
    - `drain_surface_impulses(self, *, limit: int=4)` — Lấy impulse đã lọc để SurfaceArbiter xử lý.
    - `digest(self, *, surface_queue: list[Any] | None=None)`
    - `_merged_surface_outcome(self, surface_outcome: Mapping[str, Any] | None)`
    - `_surface_outcome_from_frame(self, frame: Any)`
    - `_trim_surface_queue(self, queue: list[Any])`
    - `_surface_preview(self, item: Any)`
    - `_sync_runtime_owner(self)`
    - `_log(self, level: str, message: str, *args: Any)`

## `runtime/private_mind_loop.py`
- LOC: 786
- Docstring: runtime/private_mind_loop.py
- Functions:
  - `_env_flag(name: str, default: bool)`
- Classes:
  - `PrivateMindLoopConfig` (decorator=dataclass(slots=True))
  - `PrivateMindLoop` — Orchestrator của private mind.
    - `__init__(self, *, config: PrivateMindLoopConfig | None=None, concern_store: ConcernStore | None=None, dossier_builder: EvidenceDossierBuilder | None=None, evaluator_pipeline: MiniEvaluatorPipeline | None=None, synthesizer: GemmaInnerSynthesizer | None=None, mutation_bus: StateMutationBus | None=None, surface_valve: SurfaceValve | None=None, continuity_store: ThoughtContinuityStore | None=None, user_model_store: UserModelStore | None=None, model_adapter: Any=None, logger: Any=None)`
    - `from_runtime(cls, *, runtime_owner: Any, llm_service: Any=None, logger: Any=None)`
    - `tick(self, *, user_text: str='', channel: str='autonomous', snapshot: Any=None, observer_frame: Any=None, wake_decision: Any=None, memory_core: Any=None, state_committer: Any=None, memory_hits: Iterable[Any]=(), session_turn_ledger: Any=None, internal_agenda: Any=None, thought_stream: Any=None, surface_candidate_queue: list[Any] | None=None, runtime_owner: Any=None, surface_outcome: Mapping[str, Any] | None=None, force: bool=False)`
    - `_capture_affect(self, runtime_owner: Any)` — Chụp snapshot cảm xúc liên tục thật từ runtime_owner (không bao giờ ném lỗi).
    - `_followup_fragments(self, dossier: Any)` — Biến mạch nghĩ dang dở thành fragment để synthesizer nghĩ tiếp.
    - `_record_continuity(self, judgment: Any)` — Ghi suy nghĩ vừa sinh vào dòng liên tục (RAM + JSONL).
    - `digest(self, *, surface_queue: list[Any] | None=None)` — Compact dev payload for private mind state.
    - `_diary_voice(self, digest: Mapping[str, Any])` — Lấy bản nhật ký giọng Eris (throttled). Lỗi → None để renderer fallback.
    - `drain_surface_impulses(self, queue: list[Any], *, limit: int=4)`
    - `_model_api_status(self)`
    - `_resolve_concern_path(self)`
    - `_resolve_user_model_path(self)`
    - `_resolve_anchor_journal_path(self)` — Đường dẫn JSONL nhật ký trục neo (append-only, tái sử dụng được).
    - `_build_anchor_block(self)` — Gom toàn trục neo thành 1 block JSON-safe cho panel C# đọc.
    - `_maybe_journal_anchor(self, block: Mapping[str, Any])` — Append một dòng JSONL khi trục neo ĐỔI — để tái sử dụng/replay.
    - `_update_anchor_system(self, *, dossier: Any, runtime_owner: Any)` — Cập nhật trục neo hiện sinh từ một tick và phơi facade cho runtime.
    - `_anchor_irritation(runtime_owner: Any)` — Mức bực hiện tại từ persistent internal state (cho nhánh 'giận → dỗi').
    - `_anchor_internal_state(runtime_owner: Any)` — Nguồn Sợ_Hiện_Sinh: RollingInternalState từ contextual loop nếu có.
    - `_log_anchor_warning(self, exc: Exception)`
    - `_log_tick(self, result: PrivateMindTickResult)`

## `runtime/private_mind_model_adapter.py`
- LOC: 1683
- Docstring: runtime/private_mind_model_adapter.py
- Functions:
  - `_env_flag(name: str, default: bool)`
  - `_as_float(value: Any, default: float)`
  - `_classify_transport_exception(exc: Exception)` — Phân loại exception thành 'transient' hoặc 'fixed_config'.
- Classes:
  - `PrivateMindModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True))
    - `fragment_overlay_from_env(cls, base: 'PrivateMindModelAdapterConfig')` — Config riêng cho fragment: nếu khai ERIS_PRIVATE_MIND_FRAGMENT_PROVIDER thì
  - `PrivateMindModelResult` (decorator=dataclass(slots=True))
  - `RuntimePrivateMindModelAdapter` — Adapter chung cho 4 mini-evaluator và GemmaInnerSynthesizer.
    - `__init__(self, *, config: PrivateMindModelAdapterConfig | None=None, llm_service: Any=None, logger: Any=None)`
    - `_current_api_key(self)` — Trả API key hiện tại. Ưu tiên config (test), rồi pool chung, rồi env.
    - `_rotate_to_next_key(self)` — Xoay pool chung sang key kế. Trả True nếu xoay được (pool có >1 key).
    - `from_env(cls, *, llm_service: Any=None, logger: Any=None)`
    - `diary_fallback_from_env(cls, *, logger: Any=None)` — Adapter DỰ PHÒNG riêng cho Inner Diary.
    - `min_interval_seconds(self)`
    - `evaluate_fragment(self, evaluator_name: str, dossier: EvidenceDossier)`
    - `_freetext_fragment(self, evaluator_name: str, dossier: EvidenceDossier)` — Sinh MỘT mảnh suy nghĩ ngắn dạng văn xuôi, rồi guard + bọc thành fragment.
    - `_freetext_fragment_messages(self, evaluator_name: str, dossier: EvidenceDossier)`
    - `_guard_freetext_fragment(self, content: str)` — Guard local rẻ: làm sạch + loại output rác. Trả claim sạch hoặc '' nếu loại.
    - `_wrap_freetext_fragment(self, evaluator_name: str, claim: str, dossier: EvidenceDossier)`
    - `_tracked_chat_text(self, messages: list[dict[str, str]], *, max_tokens: int)` — Như _tracked_chat_json nhưng KHÔNG parse JSON: content rỗng/transient = fail.
    - `_chat_text_with_transient_retry(self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float)`
    - `_chat_text_once(self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float)` — Gọi model trả văn bản thô (response_format=None → không ép JSON).
    - `synthesize_judgment(self, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...])`
    - `appraise_comfort(self, user_text: str, concern_themes: list[str])` — Agent nhỏ thẩm định một câu của user có phải lời dỗ thật không.
    - `_comfort_messages(self, user_text: str, concern_themes: list[str])`
    - `_comfort_response_schema(self)`
    - `write_inner_diary(self, facts: Mapping[str, Any])` — Viết lại các dữ kiện nội tâm thành nhật ký giọng Eris (ngôi thứ nhất).
    - `_diary_messages(self, facts: Mapping[str, Any])`
    - `_diary_response_schema(self)`
    - `_slice_for_intent(self, dossier: EvidenceDossier)` — intent_evaluator: user turns + goal. Không cần memory hay concerns.
    - `_slice_for_memory_resonance(self, dossier: EvidenceDossier)` — memory_resonance_evaluator: memory hits + repair failures + concerns.
    - `_slice_for_risk(self, dossier: EvidenceDossier)` — risk_and_permission_evaluator: surface outcome + runtime flags + evidence ids.
    - `_slice_for_future_bias(self, dossier: EvidenceDossier)` — future_bias_evaluator: concerns nặng nhất + current_task + 1 user turn.
    - `_fragment_messages(self, evaluator_name: str, dossier: EvidenceDossier)`
    - `_slice_for_user_model(self, dossier: EvidenceDossier)` — user_model_evaluator: lời người dùng + chân dung Ngài hiện có + nhịp tương tác.
    - `_slim_dossier(self, dossier: EvidenceDossier)` — Chắt lọc dossier xuống những gì synthesizer thực sự cần.
    - `_slim_fragment(self, f: ThoughtFragment)` — Fragment tối giản: chỉ claim + score + evidence_ids, bỏ hypotheses/metadata.
    - `_judgment_messages(self, dossier: EvidenceDossier, fragments: tuple[ThoughtFragment, ...])`
    - `_fragment_response_schema(self, evaluator_name: str)`
    - `_judgment_response_schema(self)`
    - `debug_status(self)`
    - `_tracked_chat_json(self, messages: list[dict[str, str]], *, max_tokens: int, response_schema: dict[str, Any] | None=None)`
    - `_json_cooldown_active(self)`
    - `_maybe_enter_json_cooldown(self)`
    - `_synthesis_json_cooldown_active(self)`
    - `_maybe_enter_synthesis_json_cooldown(self)` — Vào cooldown riêng cho synthesis khi streak >= 3.
    - `_transient_cooldown_active(self)`
    - `_maybe_enter_transient_cooldown(self)`
    - `_extract_usage(self, raw: Any)`
    - `_chat_json(self, messages: list[dict[str, str]], *, max_tokens: int, response_schema: dict[str, Any] | None=None)`
    - `_chat_json_with_transient_retry(self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float, response_schema: dict[str, Any] | None=None)` — Gọi _chat_json_once, thử lại có giới hạn + backoff nếu gặp transient error.
    - `_chat_json_once(self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float, response_schema: dict[str, Any] | None=None)`
    - `_response_format(self, response_schema: dict[str, Any] | None=None)`
    - `_json_repair_messages(self, messages: list[dict[str, str]], invalid_content: str)`
    - `_provider_chat_json(self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float, response_schema: dict[str, Any] | None=None)`
    - `_provider_client_or_build(self)`
    - `_extract_content(self, raw: Any)`
    - `_parse_json(self, content: str)`
    - `_json_candidates(self, text: str)`
    - `_strip_markdown_fences(self, text: str)`
    - `_extract_first_json_object(self, text: str)`
    - `_extract_repairable_json_object(self, text: str)`
    - `_salvage_truncated_json(self, text: str)` — Cứu JSON cụt do model lặp vô hạn ở một field free-text.
    - `_collapse_repetition_in_obj(self, obj: Any)` — Áp _collapse_repetition đệ quy lên mọi chuỗi trong dict/list đã parse.
    - `_collapse_repetition(self, text: str)` — Gom các cụm ký tự lặp liên tiếp >=4 lần xuống còn 2 lần.
    - `_ends_inside_string(self, text: str)`
    - `_json_object_balance(self, text: str)`
    - `_loads_json_object(self, candidate: str)`
    - `_repair_common_json_noise(self, text: str)`
    - `_safe_raw(self, raw: Any)`
    - `_log(self, level: str, msg: str, *args: Any)`
  - `PrivateMindAdapterPool` — Pool adapter cho private mind.
    - `__init__(self, *, config: PrivateMindModelAdapterConfig | None=None, llm_service: Any=None, logger: Any=None)`
    - `from_env(cls, *, llm_service: Any=None, logger: Any=None)`
    - `fragment_adapter(self, evaluator_name: str)` — Trả adapter riêng cho evaluator_name; fallback về adapter đầu tiên nếu không tìm thấy.
    - `synthesis_adapter(self)`
    - `evaluate_fragment(self, evaluator_name: str, dossier: EvidenceDossier)`
    - `synthesize_judgment(self, dossier: EvidenceDossier, fragments: Any)`
    - `write_inner_diary(self, facts: Mapping[str, Any])`
    - `debug_status(self)` — Aggregate status của tất cả adapter trong pool.

## `runtime/prompt_context_builder.py`
- LOC: 1162
- Classes:
  - `PromptContextBuilderMixin`
    - `_log_exception(self, message: str, *args)`
    - `_session_ritual_fallback_decision(self, *, source: str, tone: str='quiet_background')`
    - `_send_session_ritual_fallback_greeting(self, *, source: str='fallback_after_session_ritual_error', tone: str='quiet_background')`
    - `_session_ritual_llm_timeout(self)`
    - `_should_inject_diary(self, user_text: str='')` — Gate: chỉ inject diary_context khi user hỏi nội tâm hoặc ERIS đang idle.
    - `_build_psych_state_block(self, state, *, felt_state: str='', private_bias: str='')` — Consolidate felt_state + private_bias thành [PSYCH_STATE] compact (~50 tokens).
    - `_build_internal_state_context(self, state: PersistentInternalState | None=None, self_state=None, *, user_text: str='')`
    - `_render_felt_state_context(self, state: PersistentInternalState | None=None)` — Gemma dịch state số → 1 câu cảm giác ngôi-thứ-nhất, để ERIS tự thuật thật.
    - `_render_anchor_register_context(self)` — Đưa register cảm xúc hiện tại (dỗi/chiếm hữu/van xin/kiểm soát) vào chat.
    - `_build_dynamic_state_tag(self, state: PersistentInternalState | None=None)` — Nén toàn bộ tâm lý học thành ~20-token JSON tag.
    - `_render_inner_diary_context(self, *, max_lines: int=8)` — Đưa nhật ký nội tâm (diary) vào ngữ cảnh chat.
    - `_render_private_mind_speech_bias_context(self, *, limit: int=6)`
    - `_build_thought_stream_context(self)`
    - `_thought_stream_root_seeds(self, *, limit: int=8)` — Lấy rễ cho inner_whim từ unresolved memory và daydream.
    - `_build_subconscious_context(self)`
    - `_build_memory_context(self, snapshot=None, memory_resonance=None)`
    - `_filter_memory_context_for_grounding(self, memory_context: str)` — Giữ procedural guard, bỏ memory có hình dạng câu trả lời.
    - `_build_action_plan_context(self, action_plan: CognitiveActionPlan)`
    - `_build_llm_ti_context(self, ti_report, action_plan: CognitiveActionPlan)`
    - `_build_speech_evidence_context(self, snapshot, *, limit: int=2)`
    - `_build_current_focus_context(self, snapshot)`
    - `_build_session_ritual_ti_context(self, report: SessionRitualReport, snapshot)`
    - `_restore_session_ritual_once(self)`
    - `_build_speech_core_ti_context(self, ti_report, action_plan: CognitiveActionPlan, inner_thought: InnerThought, speech_core: AgentSpeechCore | None=None)`
    - `_build_ni_telemetry_summary(self, snapshot)` — Tóm tắt telemetry gọn cho Ni meta-critic mà không phụ thuộc TelemetryService.
    - `_label_drift_score(self, drift_score: float)`
    - `_is_low_signal_chat_message(self, user_text: str)`
    - `_conversation_ttl_seconds(self)` — TTL của bộ đệm hội thoại hợp nhất.
    - `_chat_history_for_llm(self, *, limit: int=16, fresh_only: bool=False)`
    - `_append_chat_history(self, role: str, content: str, *, invalid: bool=False)`
    - `_build_conversation_context(self, *, limit: int=6)` — Render đuôi hội thoại gần nhất (còn tươi) thành block prompt.
    - `_merge_conversation_context(self, memory_context: str)` — Ghép đuôi hội thoại gần nhất vào memory_context của autonomous.
    - `_user_denies_last_assistant_assumption(self, user_text: str)`
    - `_invalidate_last_assistant_history(self, *, note: str)`
    - `_maybe_invalidate_last_assistant_history(self, user_text: str)`
    - `_looks_like_no_evidence_style(self, claim_style: str)`
    - `_build_ni_structured_context(self, *, drift_score: float, drift_level: str, confidence: float, should_raise_guard: bool, reason_span: str, evidence: tuple[str, ...])`

## `runtime/prosody_director.py`
- LOC: 185
- Docstring: prosody_director.py — đạo diễn nhịp đọc cho TTS.
- Classes:
  - `ProsodyPlan` (decorator=dataclass(frozen=True, slots=True))
  - `ProsodyDirector` — Chọn kiểu đọc ổn định, ít phụ thuộc prompt.
    - `plan(self, text: str, *, emotion: str='', intent: str='', stance: str='', valence: float=0.0, arousal: float=0.3, fallback_tag: str='', notes_hint: str='', style_hint: str='')`
    - `_style(self, text: str, *, emotion: str, intent: str, stance: str, valence: float, arousal: float, style_hint: str)`

## `runtime/public_turn_ledger.py`
- LOC: 131
- Functions:
  - `normalize_public_turn_channel(channel: str)`
  - `infer_public_turn_channel(decision: Decision, *, fallback: str='autonomous')`
- Classes:
  - `PublicTurn` (decorator=dataclass(slots=True))
  - `PublicTurnLedger`
    - `__init__(self)`
    - `append(self, *, channel: str, text: str, parse_mode: str, visible_to_user: bool=True, can_be_replied_to: bool=True, timestamp: float | None=None, turn_id: str | None=None)`
    - `record_decision(self, decision: Decision, *, channel: str, visible_to_user: bool=True, can_be_replied_to: bool=True, timestamp: float | None=None)`
    - `all(self)`
    - `recent(self, limit: int=20)`
    - `latest_visible_before(self, timestamp: float)`
    - `extend(self, turns: Iterable[PublicTurn])`

## `runtime/relational_voice_seed_adapter.py`
- LOC: 626
- Docstring: Register-default voice-seed pipeline.
- Functions:
  - `normalize_text(raw: str)` — ASCII-fold + lowercase + collapse whitespace (parity with service.py).
  - `_matches_any(normalized: str, patterns: tuple[str, ...])`
  - `detect_relational_act(raw_user_text: str)` — DEMOTED sub-classifier: shapes seed direction (and is the trigger only under
  - `_local_looks_like_code(normalized: str)`
  - `classify_chat_register(raw_user_text: str, *, ti_mode: str='', chat_act_name: str='', looks_like_code: bool | None=None)` — Compose existing cheap signals into SOCIAL vs TASK. No extra model call.
  - `should_use_voice_seed(register: ChatRegister, scope: VoiceSeedScope, act: RelationalAct)` — The GATE. Pure, offline-testable. Matches the design scope truth table.
  - `_env_int(name: str, default: int)`
  - `_env_float_ms(name: str, default_seconds: float)`
  - `_env_flag(name: str, default: bool)`
  - `derive_direction(act: RelationalAct)`
  - `is_identity_gloss(text: str)`
- Classes:
  - `ChatRegister` (base=Enum)
  - `VoiceSeedScope` (base=Enum)
    - `from_str(cls, raw: str | None)`
  - `RelationalAct` (base=Enum)
  - `CognitionStance` (decorator=dataclass(slots=True, frozen=True))
  - `SeedPlan` (decorator=dataclass(slots=True, frozen=True))
  - `ContinuationResult` (decorator=dataclass(slots=True, frozen=True))
  - `RelationalVoiceSeedConfig` (decorator=dataclass(slots=True, frozen=True))
    - `from_env(cls)`
  - `RelationalVoiceSeedAdapter` (decorator=dataclass(slots=True))
    - `try_answer(self, user_text: str, *, stance: CognitionStance)`
    - `_plan_seed(self, user_text: str, stance: CognitionStance)`
    - `_continue_from_seed(self, user_text: str, seed: str, stance: CognitionStance)`
    - `_join(self, seed: str, continuation: str)`
    - `_build_decision(self, *, final_text: str, act: RelationalAct, mode: str, debug: str)`
    - `_build_seed_system_prompt(self, stance: CognitionStance)`
    - `_build_seed_user_prompt(self, user_text: str, stance: CognitionStance)`
    - `_build_continuer_system_prompt(self, stance: CognitionStance)`
    - `_anti_disclaimer_fewshot(self)`
    - `_extract(self, resp: Any)`
    - `_first_line(self, raw: str)`
    - `_first_clause(self, text: str)`
    - `_clamp_words(self, text: str, max_words: int)`
    - `_is_429(self, exc: Exception)`
    - `_warn(self, fmt: str, *args: Any)`
    - `_log_cost(self, mode: str, plan: 'SeedPlan', cont: 'Optional[ContinuationResult]')` — Make the voice-seed cost/latency tradeoff explicit (spec Req 9).

## `runtime/self_critique.py`
- LOC: 794
- Docstring: Self-critique → escalate → continue.
- Classes:
  - `CritiqueResult` (decorator=dataclass(slots=True)) — Kết quả tự đánh giá một câu nháp.
  - `SelfCritiqueEscalationMixin` — Tự phê → bái sư → tiếp diễn. Mix vào RuntimeCoordinator.
    - `_self_critique_enabled(self)`
    - `_self_critique_llm_enabled(self, user_text: str='')`
    - `_classify_query_difficulty(self, user_text: str)` — Phan loai do kho cua luot noi dua tren cau cua nguoi dung.
    - `_escalation_threshold(self)`
    - `_escalation_max_continuations(self)`
    - `_escalation_available(self)`
    - `_sc_normalize(text: str)`
    - `_sc_tokens(text: str)`
    - `_sc_token_overlap(self, norm_text: str, facts: tuple[str, ...])`
    - `_sc_claims_screen(norm_text: str)`
    - `_sc_join(existing: str, marker: str)`
    - `_sc_trace(self, decision, critique: CritiqueResult, *, channel: str)`
    - `_utterance_evaluator(self)`
    - `_sentence_mentor_enabled(self)`
    - `_mentor_critique_decision(self, decision, *, channel: str, user_text: str, mentor_context: str)` — Gọi escalation/Gemini như một người dạy khâu nghe lại câu.
    - `_critique_decision(self, decision, *, channel: str, user_text: str='', snapshot=None)`
    - `_llm_critique_decision(self, decision, *, channel: str, user_text: str='')` — LLM critic nhẹ (~50 token). Chấm grounded/specific/coherent + needs_tool.
    - `_should_escalate(self, critique: CritiqueResult, *, channel: str)`
    - `_summarize_action_result_for_llm(self, result)`
    - `_run_tool_continuation(self, decision, *, channel: str, snapshot, regenerate)`
    - `_maybe_escalate_chat_decision(self, decision, *, user_text: str, snapshot, chat_generation_kwargs: dict, ti_report)`
    - `_regenerate_chat_after_tool(self, escalation_kwargs: dict, tool_summary: str, *, user_text: str, ti_report)`
    - `_maybe_escalate_directive_decision(self, decision, *, channel: str, snapshot, ti_report, directive_kwargs: dict, vision_grounded: bool=False)`
    - `_regenerate_directive_after_tool(self, esc_kwargs: dict, tool_summary: str, *, ti_report, vision_grounded: bool)`

## `runtime/sensor_visibility.py`
- LOC: 323
- Functions:
  - `derive_sensor_visibility_state(*, snapshot: Any=None, frame: Any=None)`
  - `_has_current_screen_evidence(snapshot: Any=None, frame: Any=None)`
  - `_collect_text_signals(*owners: Any)`
  - `_explicit_bool(*owners: Any, names: tuple[str, ...], default: bool | None=False)`
  - `_parse_bool(value: Any)`
  - `_get_value(owner: Any, name: str, default: Any=None)`
  - `_has_payload(value: Any)`
  - `_clamp01(value: Any)`
- Classes:
  - `SensorVisibilityState` (decorator=dataclass(frozen=True, slots=True))
    - `to_context(self)`

## `runtime/sensory_model_adapter.py`
- LOC: 146
- Functions:
  - `_env_flag(name: str, default: bool)`
- Classes:
  - `SensoryModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True))
  - `RuntimeSensoryModelAdapter` — Adapter riêng cho tầng cảm giác 0.6B.
    - `__init__(self, *, config: SensoryModelAdapterConfig | None=None, ollama_client: Any | None=None, logger: Any | None=None)`
    - `from_env(cls, *, logger: Any | None=None)`
    - `observe(self, *, snapshot: SignalSnapshot, diff: SignalDiff, recent_summary: str='')`
    - `_prompt(self, *, snapshot: SignalSnapshot, diff: SignalDiff, recent_summary: str)`
    - `_schema(self)`
    - `_log(self, level: str, msg: str, *args: Any)`

## `runtime/session_turn_ledger.py`
- LOC: 141
- Classes:
  - `SessionTurn` (decorator=dataclass(frozen=True)) — Một lượt public trong phiên.
  - `SessionTurnLedger` — Ledger deterministic cho câu hỏi về thứ tự, số lượng, câu dài nhất.
    - `__init__(self)`
    - `record_user(self, text: str, *, timestamp: Optional[float]=None, meta: Optional[dict[str, Any]]=None)`
    - `record_assistant(self, text: str, *, timestamp: Optional[float]=None, meta: Optional[dict[str, Any]]=None)`
    - `_record(self, role: Role, text: str, *, timestamp: Optional[float], meta: Optional[dict[str, Any]])`
    - `all_turns(self)`
    - `turns_by_role(self, role: Role)`
    - `user_turns(self)`
    - `assistant_turns(self)`
    - `user_questions(self)`
    - `nth_user_turn(self, ordinal: int)`
    - `nth_assistant_turn(self, ordinal: int)`
    - `nth_user_question(self, ordinal: int)`
    - `count_user_questions(self, *, include_current: bool=True)`
    - `longest_user_question(self)`
    - `gist_recent_user_topics(self, *, limit: int=8)` — Sinh gist rất nhẹ từ user turns gần đây.
    - `_nth(items: Iterable[SessionTurn], ordinal: int)`
    - `_unique_keep_order(items: Iterable[str])`

## `runtime/shadow_pipeline.py`
- LOC: 376
- Docstring: runtime/shadow_pipeline.py
- Classes:
  - `ShadowPipelineMixin` — Trộn vào RuntimeCoordinator để chạy V3 pipeline ở chế độ shadow.
    - `_shadow_pipeline_enabled(self)`
    - `_get_shadow_pipeline(self)`
    - `_v3_promoted_paths(self)` — Tập path V3 được phép ghi đè frame cũ.
    - `_promote_v3_paths(self, result: Optional[PipelineResult], *, old_frame: Any, channel: str)` — Ghi quyết định V3 lên frame cũ cho các path đã bật. Không bao giờ raise.
    - `_set_frame_attr(frame: Any, name: str, value: Any)`
    - `_set_frame_metadata(self, frame: Any, key: str, value: Any)`
    - `_record_frame_note(frame: Any, note: str)`
    - `_run_shadow_cognitive_pipeline(self, *, channel: str, user_text: str='', snapshot: Any=None, vision_facts: Sequence[str]=(), old_frame: Any=None, active_goal: Any=None)` — Chạy V3 pipeline shadow và so trace với frame cũ.
    - `_build_shadow_raw_signals(self, *, user_text: str, snapshot: Any, vision_facts: Sequence[str])`
    - `_snap(snapshot: Any, names: tuple[str, ...], default: Any='')`
    - `_shadow_idle_seconds(self, snapshot: Any)`
    - `_safe_render_trace(frame: Any)`
    - `_compare_traces(self, *, v3_trace: dict[str, Any], old_trace: dict[str, Any], elapsed_ms: float, channel: str)`
    - `_focus_overlap(a: str, b: str)` — Jaccard token nhẹ giữa hai focus, chỉ để cảm nhận độ trùng.
    - `_log_shadow_comparison(self, comparison: dict[str, Any], v3_trace: dict[str, Any], old_trace: dict[str, Any])`

## `runtime/signal_buffer.py`
- LOC: 324
- Docstring: SignalBuffer cho Background Observer.
- Classes:
  - `SignalBufferConfig` (decorator=dataclass)
  - `SignalBufferStats` (decorator=dataclass)
  - `SignalBuffer` — Bộ nhớ ngắn hạn cho signal nền.
    - `__init__(self, config: Optional[SignalBufferConfig]=None)`
    - `items(self)`
    - `last(self)`
    - `last_diff(self)`
    - `push(self, snapshot: SignalSnapshot)` — Thêm snapshot và trả diff so với snapshot trước.
    - `diff(self, current: SignalSnapshot, previous: Optional[SignalSnapshot])`
    - `stats(self)`
    - `recent(self, n: int=8)`
    - `recent_summary(self, n: int=6)` — Tóm tắt ngắn cho LLM observer nếu cần.
    - `should_run_text_observer(self, diff: Optional[SignalDiff]=None, *, min_diff: float=0.18, cooldown_seconds: float=8.0)` — Cổng gọi model nhỏ.
    - `_cooldown_ready(self, cooldown_seconds: float)`
    - `_repetition_score(self, current: SignalSnapshot)`
    - `_count_recent_hash(self, getter, value: str)`
    - `_count_in(items: Iterable[SignalSnapshot], getter, value: str)`
    - `_norm(text: str)`
    - `_text_similarity(a: str, b: str)`
    - `_event_similarity(cls, a: list[str], b: list[str])`
    - `_idle_bucket(idle_seconds: float)`

## `runtime/snub_tracker.py`
- LOC: 392
- Docstring: runtime/snub_tracker.py
- Functions:
  - `_classify_utterance(text: str)` — Phân loại câu Eris nói: 'question' hoặc 'statement'.
- Classes:
  - `SnubState` (decorator=dataclass) — Trạng thái "bị bơ" hiện tại của Eris.
    - `is_snubbed(self)`
    - `should_react(self)` — True khi level đủ để sinh phản ứng trong micro-presence.
    - `was_question(self)`
    - `to_seed_label(self)` — Tóm tắt ngắn cho LLM seed.
    - `to_prompt_hint(self)` — Gợi ý ngắn đưa vào ego_surface_state / micro-presence context.
  - `SnubTracker` — Theo dõi chuỗi autonomous speech bị bơ.
    - `__init__(self)`
    - `on_eris_spoke(self, text: str, *, channel: str='autonomous')` — Ghi nhận khi Eris nói autonomous.
    - `on_user_responded(self, user_text: str)` — Gọi khi user nhắn tin bất kỳ — reset snub counter.
    - `check_and_update(self, *, now: float | None=None)` — Gọi trong autonomous cycle để detect snub mới và trả về state.
    - `get_state(self)` — Lấy state hiện tại mà không cập nhật.
    - `reset(self)` — Reset hoàn toàn — dùng khi session mới bắt đầu.
    - `_reset_snub(self)` — Reset snub counter (giữ last_spoken info).
    - `_compute_level(self, utterance_type: str)` — Tính level dựa trên loại câu và số lần bị bơ.
    - `_compute_irritation_delta(level: str, utterance_type: str)` — Lượng irritation nên cộng vào internal_state.

## `runtime/source_grounding.py`
- LOC: 1952
- Classes:
  - `SourceCandidate` (decorator=dataclass(slots=True)) — Một nguồn có thể dùng để trả lời.
    - `to_dict(self)`
  - `SourceFallbackDecision` (decorator=dataclass(slots=True)) — Compatibility signal khi thiếu evidence.
    - `to_payload(self)`
    - `to_runtime_decision(self)` — Cố chuyển sang domain.Decision nếu repo có class này.
  - `MemoryAnswerProfile` (decorator=dataclass(slots=True)) — Semantic policy for memory/history questions.
    - `active(self)`
    - `apply_cap(self, raw_confidence: float)`
  - `SourceGroundingReport` (decorator=dataclass(slots=True)) — Báo cáo grounding nguồn cho một turn.
    - `should_fallback(self)`
    - `should_preempt_llm(self)`
    - `max_confidence(self)`
    - `apply_cap(self, raw_confidence: float)`
    - `to_dict(self)`
  - `ClaimAnnotation` (decorator=dataclass(slots=True)) — Nhãn cho một mệnh đề bề mặt (Task 8 / R8.1).
    - `to_dict(self)`
  - `SourceGroundingEngine` — Bộ phân loại grounding nguồn cho runtime.
    - `analyze(self, user_text: str, *, frame: Any=None, active_files: Sequence[Any] | None=None, screen_facts: Sequence[Any] | None=None, screen_facts_stale: bool=False, memory_packet: Any=None, runtime_state: Any=None, allow_web: bool=False, attach_to_frame: bool=True)` — Phân tích nguồn trả lời chính.
    - `classify(self, *args: Any, **kwargs: Any)`
    - `analyze_frame(self, frame: Any, **kwargs: Any)` — Helper khi caller chỉ có frame.
    - `apply_confidence_cap(self, raw_confidence: float, report_or_frame: Any)` — Cap confidence ngoài pipeline.
    - `should_preempt(self, report_or_frame: Any, *, modes: Sequence[str]=('filename_only', 'deictic_without_vision', 'investigate'))`
    - `render_prompt_context(self, report: SourceGroundingReport)` — Tạo prompt context ngắn cho LLM.
    - `annotate_claims(self, text: str, *, report: SourceGroundingReport | None=None, strict_grounding: bool=True)` — Gắn nhãn từng mệnh đề thay vì viết-lại/bóp câu (Task 8 / R8.1, R8.2).
    - `_is_epistemic_curiosity_gap(self, report: SourceGroundingReport)` — Thiếu evidence nhưng còn đủ neo để hỏi/thăm dò thay vì trả payload chết.
    - `build_fallback_decision(self, report: SourceGroundingReport)` — Tạo signal khi nguồn user yêu cầu chưa có evidence.
    - `build_preemptive_reply(self, report: SourceGroundingReport)` — Deprecated compatibility hook.
    - `_derive_memory_answer_profile(self, *, normalized: str, user_text: str, memory_ref: bool, memory_evidence: Mapping[str, Any])` — Infer the memory/history answer shape for this turn.
    - `_split_grounding_clauses(self, text: str)` — Tách mệnh đề rất nhẹ cho source grounding.
    - `_is_self_disclosure_clause(self, clause: str)` — Nhận diện mệnh đề user tự khai báo fact/preference/profile.
    - `_looks_like_question(self, normalized: str)`
    - `_has_actionable_web_reference(self, normalized: str, raw_text: str, *, clauses: Sequence[str])` — Chỉ route web khi user thật sự đòi dữ liệu hiện tại.
    - `_choose_primary_source(self, candidates: Sequence[SourceCandidate])` — Chọn nguồn chính.
    - `_cap_for(self, primary: SourceCandidate, *, missing_evidence: Sequence[str])`
    - `_derive_missing_evidence(self, primary: SourceCandidate, candidates: Sequence[SourceCandidate])`
    - `_derive_forbidden_assumptions(self, *, primary_source: SourceKind, asks_about_file: bool, refers_to_screen: bool, code_detected: bool, file_evidence_present: bool, screen_evidence_present: bool, memory_evidence_present: bool, allow_web: bool, web_ref: bool)`
    - `_derive_answer_style_rules(self, primary: SourceKind, *, missing_evidence: Sequence[str])`
    - `_derive_preempt_mode(self, *, normalized: str, file_mentions: Sequence[str], missing_evidence: Sequence[str])`
    - `_detect_file_mentions(self, text: str, normalized: str)`
    - `_detect_explicit_screen_request(self, normalized: str)` — True chỉ khi user TƯỜNG MINH nhắc màn hình hoặc ra lệnh nhìn/xem.
    - `_has_deictic_reference(self, normalized: str)` — True khi có đại từ chỉ định trần ("cái này", "lỗi này"...).
    - `_looks_like_file_content_request(self, normalized: str)`
    - `_detect_pasted_code(self, text: str)`
    - `_guess_code_language(self, text: str, *, languages: Sequence[str], preview: Sequence[str])`
    - `_collect_file_evidence(self, *, frame: Any=None, active_files: Sequence[Any] | None=None, runtime_state: Any=None)`
    - `_collect_screen_evidence(self, *, frame: Any=None, screen_facts: Sequence[Any] | None=None, runtime_state: Any=None)`
    - `_collect_memory_evidence(self, *, frame: Any=None, memory_packet: Any=None)`
    - `_collect_user_text_evidence(self, *, frame: Any=None, user_text: str='')`
    - `_summarize_evidence_items(self, items: Sequence[Any], *, default_confidence: float)`
    - `_preview_item(self, item: Any)`
    - `_extract_user_text_from_frame(self, frame: Any)`
    - `_mapping_get(obj: Any, key: str, default: Any=None)`
    - `_read_float(obj: Any, key: str)`
    - `_normalize(cls, text: str)`
    - `_has_any(cls, normalized_text: str, markers: Sequence[str])`
    - `_as_list(value: Any)`
    - `_dedupe(items: Iterable[Any])`
    - `_safe_setattr(obj: Any, key: str, value: Any)`
    - `_clamp01(value: float)`

## `runtime/speech_delivery_planner.py`
- LOC: 244
- Docstring: speech_delivery_planner.py — cầu nối cảm xúc nền -> cách biểu diễn.
- Functions:
  - `_safe_float(value: object, default: float=0.0)`
  - `_clamp01(value: object, default: float=0.0)`
  - `_unique(items: Iterable[str])`
  - `affect_signals_from(payload: dict[str, Any], frame: Any=None)` — Rút affect hiện có mà không bắt stage phụ thuộc sâu vào cognition.
- Classes:
  - `AffectSignals` (decorator=dataclass(frozen=True, slots=True))
  - `SpeechDeliveryPlan` (decorator=dataclass(frozen=True, slots=True))
    - `to_payload(self)`
  - `SpeechDeliveryPlanner` — Chọn cách nói/ngắt/mặt từ affect nền.
    - `plan(self, text: str, *, intent: str='', delivery_hint: str='', explicit_emotion: str='', explicit_motion: str='', extracted_actions: Iterable[str]=(), affect: AffectSignals | None=None)`
    - `_looks_teasing(hay: str, signals: AffectSignals)`
    - `_looks_boundary(hay: str, signals: AffectSignals)`
    - `_stage_notes(signals: AffectSignals)`

## `runtime/speech_localizer.py`
- LOC: 149
- Docstring: speech_localizer.py — chuẩn hoá câu trước khi đưa vào TTS.
- Functions:
  - `_enabled()`
  - `_get_api_key()` — Lấy key Gemini cho bước dịch TTS, không phụ thuộc vào tts_engine.
  - `_already_japanese(text: str)`
  - `_normalize_transcript(text: str)` — Giữ line break như nhịp thở, chỉ dọn khoảng trắng nội dòng.
  - `_clean_translation_output(text: str)` — Dọn output dịch nhưng không flatten nhiều dòng thành một dòng.
  - `_style_line(style: str)` — Hint dịch tự nhiên theo prosody, không biến nghĩa câu.
- Classes:
  - `SpeechLocalizer` — Dịch/style câu public thành câu TTS.
    - `__init__(self)`
    - `localize(self, text: str, *, language_hint: str='auto', prosody_style: str='')`
    - `_translate_to_japanese(self, text: str, *, prosody_style: str='')`

## `runtime/speech_pipeline.py`
- LOC: 78
- Classes:
  - `SpeechIntentDecision` (decorator=dataclass(frozen=True, slots=True))
  - `SpeechPipelineMixin` — Shared finalization path for public speech decisions.
    - `_finalize_speech_decision(self, decision, *, channel: str, frame=None, speech_core=None, snapshot=None, ti_report=None, user_text: str='', momentum_topic: str='')`

## `runtime/stage_contracts.py`
- LOC: 239
- Docstring: stage_contracts.py — hợp đồng sân khấu giữa Decision, UI, TTS và body.
- Functions:
  - `clean_display_text(text: str)` — Text cho UI: giữ nội dung, chỉ dọn whitespace/markdown thô.
  - `clean_tts_source(text: str)` — Text nguồn cho TTS: không đọc markdown, URL, code, hay tag diễn xuất.
  - `_safe_float(value: object, default: float=0.0)`
  - `_emotion_from_payload(payload: dict[str, Any], frame: Any=None)` — Rút emotion thô cho stage từ appraisal/envelope hiện có.
  - `_prosody_numbers(payload: dict[str, Any], frame: Any=None)` — Trích valence/arousal/stance cho prosody mà không bắt stage biết cognition.
  - `_motion_from_decision(decision: Any)`
- Classes:
  - `StageFrame` (decorator=dataclass(frozen=True, slots=True))
    - `to_payload_patch(self)` — Patch gắn vào payload cũ mà không phá Godot/client hiện tại.
  - `StageFrameBuilder` — Dịch ``Decision`` thành ``StageFrame``.
    - `__init__(self, *, localizer: Any=None, language_hint: str='auto')`
    - `build(self, decision: Any, *, payload: dict[str, Any], channel: str | None=None, frame: Any=None, turn_id: str | None=None, segment_id: int=0)`

## `runtime/stage_dispatcher.py`
- LOC: 173
- Docstring: stage_dispatcher.py — phát StageFrame ra TTS theo đúng nhịp segment.
- Functions:
  - `_dispatch_mode()`
  - `_join_tts_segments(frames: list[StageFrame])` — Ghép segment thành một transcript liên tục để tránh nhiều call TTS.
  - `_performance_kwargs(frame: StageFrame)` — Rút metadata vocal cache từ delivery payload nếu có.
- Classes:
  - `StageDispatcher`
    - `dispatch_tts(self, frames: Iterable[StageFrame], *, tts_engine: Any, valence: float, arousal: float, stance: str, on_first_start: Callable[[], None] | None=None, on_event: Callable[[Any, StageFrame], None] | None=None)`
    - `_dispatch_inline(self, frame_list: list[StageFrame], *, tts_engine: Any, valence: float, arousal: float, stance: str, on_first_start: Callable[[], None] | None, on_event: Callable[[Any, StageFrame], None] | None)`
    - `_dispatch_queued(self, frame_list: list[StageFrame], *, tts_engine: Any, valence: float, arousal: float, stance: str, on_first_start: Callable[[], None] | None, on_event: Callable[[Any, StageFrame], None] | None)`

## `runtime/stage_output.py`
- LOC: 110
- Docstring: stage_output.py — transformer chain nhỏ cho output sân khấu.
- Functions:
  - `_enabled()`
  - `_max_segments()`
  - `_min_split_chars()`
- Classes:
  - `SentenceSegmenter` — Chia text TTS thành các câu ngắn, không đụng vào text UI.
    - `split(self, text: str)`
  - `StageOutputPipeline` — Base StageFrame -> tuple[StageFrame, ...].
    - `__init__(self)`
    - `frames_for_tts(self, frame: StageFrame)`

## `runtime/stage_performance_planner.py`
- LOC: 231
- Docstring: stage_performance_planner.py — biến yêu cầu "diễn" thành màn nói nhỏ.
- Functions:
  - `_normalize_vi(text: str)`
  - `_clean_line(text: str)`
  - `_join_prefix(prefix: str, line: str)`
  - `_looks_generic_or_empty(text: str)`
  - `_merge_actions(*groups: Iterable[str])`
- Classes:
  - `PerformanceAct` (decorator=dataclass(frozen=True, slots=True))
    - `to_payload(self)`
  - `PerformanceSurfaces` (decorator=dataclass(frozen=True, slots=True))
  - `PerformanceRequestPlanner` — Nhận ra yêu cầu biểu diễn và render thành text nghe được.
    - `detect(self, user_text: str)`
    - `apply(self, surfaces: StageTextSurfaces, *, user_text: str='', intent: str='', delivery_hint: str='', nonverbal_cue: str='', stage_motion: str='', extracted_actions: Iterable[str]=())`
    - `_has(text: str, tokens: tuple[str, ...])`
    - `_matches_spec(self, normalized_text: str, spec: PerformanceActSpec)`
    - `_act_from_spec(spec: PerformanceActSpec)`
    - `_has_request_marker(text: str)`

## `runtime/stage_transformers.py`
- LOC: 270
- Docstring: stage_transformers.py — transformer chain cho output sân khấu.
- Functions:
  - `_squash(text: str)`
  - `_strip_markdown(text: str, *, code_placeholder: str='')`
  - `_normalize_tag(raw: str)`
  - `_unique(items: Iterable[str])`
- Classes:
  - `StageMarks` (decorator=dataclass(frozen=True, slots=True))
  - `StageTextSurfaces` (decorator=dataclass(frozen=True, slots=True))
  - `ActionTagExtractor` — Bóc tag diễn xuất khỏi text và trả thành action/emotion/motion.
    - `extract(self, text: str)`
  - `DisplayFilter` — Text cho UI: đẹp, gọn, không chứa tag nội bộ.
    - `clean(self, text: str)`
  - `TTSFilter` — Text cho TTS: không markdown, URL, emoji, code, tag sân khấu.
    - `clean(self, text: str)`
  - `MemorySurfaceFilter` — Text lưu hội thoại/memory: chỉ nội dung thật, không action tag.
    - `clean(self, text: str)`
  - `StageTransformerChain` — Chạy toàn bộ transformer để tạo các bề mặt output.
    - `__init__(self)`
    - `transform(self, raw_text: str)`

## `runtime/state_commit_service.py`
- LOC: 920
- Functions:
  - `_is_nonsemantic_fallback_decision(decision: Decision)` — True nếu decision chỉ là fallback kỹ thuật, không phải answer nội dung.
- Classes:
  - `StateCommitServiceMixin`
    - `_memory_kernel(self)`
    - `_ensure_session_turn_ledger(self)`
    - `_ensure_memory_commit_policy(self)`
    - `_ensure_memory_fast_commit_policy(self)` — Policy nóng không gọi model semantic parser.
    - `_background_memory_digest_enabled(self)`
    - `_enqueue_background_memory_digest(self, user_text: str, *, turn_id: str='', source: str='chat_turn', priority: str='normal', context: dict | None=None)`
    - `_set_background_memory_digest_remote_inflight(self, inflight: bool)`
    - `_memory_snapshot_for_lookup(self)`
    - `_memory_snapshot_items(self, snapshot, collection_name: str)`
    - `_record_value(record: object, field_name: str, default=None)`
    - `_record_metadata(self, record: object)`
    - `_clean_memory_value(value: object)`
    - `_extract_semantic_value_from_record(self, record: object, kind: MemoryKind)`
    - `_semantic_memory_lookup(self, kind: MemoryKind)`
    - `_fact_key_for_memory_kind(kind: MemoryKind)`
    - `_semantic_record_rank(self, record: object)`
    - `_episodic_memory_lookup(self, query: str)`
    - `_ensure_memory_recall_adapter(self)`
    - `_build_memory_recall_decision(self, user_text: str)`
    - `_ensure_relational_voice_seed_adapter(self)`
    - `_ensure_affect_self_read_adapter(self)`
    - `_frame_memory_storage_permission(self, frame)`
    - `_user_turn_memory_evidence_id(self, *, frame=None, turn_id: str | None=None)`
    - `_ingest_user_turn_via_memory_kernel(self, frame, user_text: str, *, turn_id: str | None=None)`
    - `_add_user_turn_memory_commit_requests(self, frame, user_text: str, *, turn_id: str | None=None)`
    - `_load_memory_state(self)`
    - `_has_structured_memory_core(self)`
    - `_ensure_internal_state(self)`
    - `_apply_debug_overrides(self, state: PersistentInternalState)`
    - `_get_internal_state(self)`
    - `_set_internal_state(self, state: PersistentInternalState)`
    - `_load_internal_state_payload(self)`
    - `_send_decision_to_body(self, decision: Decision, *, channel: str | None=None)`
    - `_record_public_turn(self, decision: Decision, *, payload: dict | None=None, channel: str | None=None)`
    - `_build_body_bias_payload(self)`
    - `_body_bias_clamp(value: object)`
    - `_normalize_body_focus_kind(value: str)`
    - `_save_memory_state(self)`
    - `_memory_recall_packet(self, *, snapshot=None, query: str='')` — Recall structured packet, không flatten quá sớm.
    - `_memory_recall_texts(self, *, snapshot=None, layers: tuple[str, ...] | None=None)`
    - `_recall_memory_resonance(self, *, snapshot=None, user_text: str='', channel: str='', fragments: tuple[str, ...]=())`
    - `_memory_attention_lines(self)`
    - `_norm_deviation_texts(self, snapshot)`
    - `_note_norm_observation(self, snapshot)`
    - `_memory_query_from_snapshot(self, snapshot)`
    - `_event_timestamp(self, snapshot, *, started_at: float | None=None)`
    - `_commit_chat_decision(self, decision: Decision, fe_plan, *, frame: CognitiveFrame | None=None)`
    - `_apply_position_update(self, decision: Decision)`
    - `_build_silent_motion_decision(self, ti_report: TiPolicyReport)`
    - `_build_direct_action_decision(self, user_text: str, ti_report, snapshot, *, repeat_count: int=1)`
    - `_execute_system_action(self, decision: Decision, *, snapshot)`
    - `_action_animation_hint(self, action_name: str, fallback: str)`
    - `_action_result_to_text(self, result)`
    - `_resolve_now_playing_text(self, snapshot)`
    - `_extract_media_title_from_snapshot(self, snapshot)`
    - `_extract_media_title(self, raw_title: str)`

## `runtime/state_committer.py`
- LOC: 1128
- Docstring: src/runtime/state_committer.py
- Functions:
  - `_safe_float(value: Any, default: float=0.0)`
  - `_safe_bool(value: Any, default: bool=False)`
  - `_as_list_str(value: Any)`
  - `_get(obj: Any, name: str, default: Any=None)` — Đọc field từ dict/object/dataclass mà không kén kiểu.
  - `_set_if_possible(obj: Any, name: str, value: Any)`
  - `_content_is_empty(content: Any)`
  - `_normalize_target(target: Any)`
  - `_normalize_decay_policy(value: Any)`
  - `_request_metadata(req: Any)`
  - `_request_tags(req: Any)`
- Classes:
  - `StateCommitterConfig` (decorator=dataclass(slots=True)) — Cấu hình ngưỡng commit.
  - `CommitValidationIssue` (decorator=dataclass(slots=True)) — Một vấn đề phát hiện trong quá trình validate.
    - `to_dict(self)`
  - `CommitDecision` (decorator=dataclass(slots=True)) — Kết quả kiểm định một request.
    - `to_dict(self)`
  - `CommitBatchReport` (decorator=dataclass(slots=True)) — Audit report cho một lần StateCommitter.commit(...).
    - `duration_ms(self)`
    - `finish(self)`
    - `to_dict(self)`
  - `StateCommitter` — Cổng commit chính cho runtime.
    - `__init__(self, memory_cognition: Any, *, config: Optional[StateCommitterConfig]=None, logger: Optional[logging.Logger]=None, epistemic_kernel: Any=None)`
    - `commit(self, frame_or_requests: Any, *, frame: Any=None)` — Validate rồi commit batch request.
    - `commit_frame(self, frame: Any)` — Alias rõ nghĩa cho coordinator thích gọi tên dài.
    - `commit_requests(self, requests: Sequence[Any], *, frame: Any=None)` — Alias khi caller đã có list StateCommitRequest.
    - `validate(self, request: Any, *, request_index: int=0, frame: Any=None, evidence_index: Optional[dict[str, Any]]=None)` — Kiểm định một StateCommitRequest nhưng chưa ghi memory.
    - `_commit_one(self, decision: CommitDecision, frame: Any=None)` — Gọi MemoryCognitionCore.commit(...) với request đã validate.
    - `_call_memory_commit(self, request: Any, *, frame: Any=None)` — Gọi memory core bằng nhiều signature phổ biến.
    - `_extract_requests(self, frame_or_requests: Any)`
    - `_maybe_frame(self, value: Any)`
    - `_looks_like_commit_request(self, value: Any)`
    - `_clone_request(self, request: Any, **updates: Any)` — Clone request nhưng giữ class gốc nếu có thể.
    - `_build_evidence_index(self, frame: Any)`
    - `_contains_private_raw_evidence(self, request: Any, evidence_ids: list[str], evidence_index: Mapping[str, Any])`
    - `_semantic_grounding_issue(self, *, final_target: str, content: Any, metadata: Mapping[str, Any], frame: Any, status: CommitStatus='committed', decay_policy: str='normal')`
    - `_frame_permission_flag(self, frame: Any, field_name: str, *, default: bool)`
    - `_looks_like_user_correction(self, request: Any, content: Any, reason: str, tags: Sequence[str], metadata: Mapping[str, Any])`
    - `_confidence_thresholds(self, target: str)`
    - `_attach_report_to_frame(self, frame: Any, report: CommitBatchReport)`
    - `_frame_id(self, frame: Any)`
    - `_dedup_key(self, request: Any)`

## `runtime/subconscious_loop.py`
- LOC: 411
- Docstring: Runtime adapter cho subconscious blackboard/synthesizer.
- Classes:
  - `SubconsciousTickResult` (decorator=dataclass(slots=True, frozen=True)) — Kết quả một tick subconscious.
    - `to_dict(self)`
  - `SubconsciousLoop` — Vòng nền tối thiểu cho worker subconscious.
    - `__init__(self, *, blackboard: SubconsciousBlackboard | None=None, synthesizer: ConsciousSynthesizer | None=None, workers: Iterable[SubconsciousWorker]=(), wandering_engine: WanderingThoughtEngine | None=None)`
    - `submit(self, fragment: ThoughtFragment | Mapping[str, Any])` — Submit thủ công một fragment vào Blackboard.
    - `tick(self, *, frame: Any=None, snapshot: Any=None, memory_packet: Any=None, relation: Any=None, internal_state: Any=None, now: float | None=None, pre_worker_names: Iterable[str] | None=None, post_worker_names: Iterable[str] | None=None, audit_worker_names: Iterable[str] | None=None, run_pre_workers: bool=True, run_audit: bool=True, run_synthesis: bool=True, run_post_workers: bool=True, allow_surface_seed: bool=True, run_wandering: bool=True)` — Chạy một lượt worker -> audit -> synthesizer -> post-worker -> audit.
    - `latest_report(self)`
    - `_inner_court_report_payload(self)` — Expose Lane 3 API synthesis report cho debug/audit nội bộ.
    - `pop_surface(self)`
    - `stop(self)`
    - `_context_with_snapshot(self, *, frame: Any, snapshot: Any, memory_packet: Any, relation: Any, internal_state: Any, thought_object: Any, audit_report: Any, now: float)` — Tạo WorkerContext có snapshot Blackboard bất biến.
    - `_run_workers(self, context: WorkerContext, *, after_synthesis: bool, worker_names: Iterable[str] | None=None)` — Chạy nhóm worker phù hợp với pass hiện tại và submit fragment.
    - `_run_audit_workers(self, context: WorkerContext, *, worker_names: Iterable[str] | None=None)` — Chạy các worker audit có quyền mutate Blackboard.
    - `_compose_report(self, thought_object: ThoughtObject | None, surface_seed: dict[str, object] | None)`
    - `_surface_from_seed(self, surface_seed: dict[str, object] | None, thought_object: ThoughtObject | None)`

## `runtime/subconscious_model_adapter.py`
- LOC: 333
- Docstring: Adapter gọi model/API riêng cho Lane 3 subconscious synthesis.
- Functions:
  - `_env_flag(name: str, default: bool)`
  - `_as_float(value: Any, default: float)`
  - `_cfg_flag(path: str, default: bool)`
- Classes:
  - `SubconsciousModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True)) — Cấu hình riêng cho Lane 3 API synthesis.
  - `SubconsciousModelResult` (decorator=dataclass(slots=True, frozen=True))
  - `RuntimeSubconsciousModelAdapter` — Client mỏng cho Lane 3.
    - `__init__(self, *, config: SubconsciousModelAdapterConfig | None=None, logger: Any | None=None)`
    - `from_env(cls, *, logger: Any | None=None)`
    - `synthesize(self, messages: list[dict[str, Any]])` — Gọi provider và parse JSON object.
    - `_resolve_profile(self)`
    - `_resolve_model(self)`
    - `_resolve_base_url(self)`
    - `_resolve_api_key(self)`
    - `_build_client(self)`
    - `_extract_content(self, raw: Mapping[str, Any])`
    - `_parse_json_object(self, text: str)`
    - `_safe_raw(self, raw: Mapping[str, Any])`
    - `_log(self, level: str, msg: str, *args: Any)`

## `runtime/text_repeat_guard.py`
- LOC: 203
- Classes:
  - `TextRepeatGuardMixin`
    - `_is_near_duplicate_text(self, text: str, other: str)`
    - `_recent_spoken_texts(self, *, limit: int=FORCE_SPEAK_RECENT_FAMILY_WINDOW)`
    - `_autonomous_avoid_text(self, *, limit: int=6)` — Gộp các câu autonomous gần đây thành chuỗi nhiều dòng cho prompt.
    - `_recent_spoken_entries(self, *, limit: int=20)`
    - `_force_speak_banned_family_for_text(self, text: str)`
    - `_looks_like_poetic_fallback_text(self, text: str)`
    - `_repeated_force_speak_banned_family(self, text: str)`
    - `_force_speak_line_is_novel(self, text: str, recent: tuple[str, ...])`
    - `_get_novelty_guard(self)`

## `runtime/thought_model_adapter.py`
- LOC: 83
- Docstring: runtime/thought_model_adapter.py
- Functions:
  - `_env_flag(name: str, default: bool)`
- Classes:
  - `ThoughtModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True))
  - `RuntimeThoughtModelAdapter`
    - `__init__(self, *, config: ThoughtModelAdapterConfig | None=None, private_adapter: Any=None, logger: Any=None)`
    - `from_env(cls, *, logger: Any=None)`
    - `review(self, payload: Mapping[str, Any])` — Trả schema ThoughtStream đang mong đợi.

## `runtime/tts_audio_polish.py`
- LOC: 256
- Docstring: tts_audio_polish.py — hậu xử lý PCM cho giọng TTS.
- Functions:
  - `audio_polish_enabled()`
  - `polish_pcm16_mono(pcm: bytes, *, sample_rate: int=24000, silence_threshold: int | None=None, edge_keep_ms: int | None=None, max_internal_silence_ms: int | None=None, target_peak: float | None=None, max_gain: float | None=None)` — Cắt/nén silence và normalize nhẹ PCM 16-bit mono.
  - `_empty_result()`
  - `_trim_edges(samples: array.array, threshold: int, keep_ms: int, sample_rate: int)`
  - `_compress_internal_silence(samples: array.array, threshold: int, max_silence_ms: int, sample_rate: int)` — Nén pause dài bên trong audio, nhưng không xoá hết nhịp thở.
  - `_normalize_peak(samples: array.array, *, target_peak: float, max_gain: float)`
  - `_first_voiced_index(samples: array.array, threshold: int)`
  - `_last_voiced_index(samples: array.array, threshold: int)`
  - `_bytes_to_samples(pcm: bytes)`
  - `_samples_to_bytes(samples: array.array)`
  - `_ms_to_samples(ms: int, sample_rate: int)`
  - `_samples_to_ms(count: int, sample_rate: int)`
  - `_int_env(name: str, default: int)`
  - `_float_env(name: str, default: float)`
- Classes:
  - `AudioPolishStats` (decorator=dataclass(frozen=True, slots=True)) — Số liệu nhỏ để debug TTS mà không phải mở file audio.
  - `AudioPolishResult` (decorator=dataclass(frozen=True, slots=True))

## `runtime/tts_engine.py`
- LOC: 927
- Docstring: tts_engine.py — Emotional TTS cho ERIS dùng Gemini TTS API.
- Functions:
  - `_enabled()`
  - `_voice()`
  - `_model()`
  - `_language_hint()`
  - `_quality_mode()` — balanced | high.
  - `_queue_size()`
  - `_emotion_to_tag(valence: float, arousal: float, stance: str='')` — Chuyển valence/arousal/stance thành audio tag Gemini.
  - `_build_tts_prompt(text: str, audio_tag: str, language_hint: str, *, prosody_notes: str='', prelocalized: bool=False, quality_mode: str='high')` — Xây dựng prompt TTS theo format advanced prompting của Gemini.
  - `_get_api_key()` — Lấy Gemini API key theo thứ tự ưu tiên.
  - `_synthesize_wav(prompt: str, voice: str, model: str)` — Gọi Gemini TTS, trả về WAV bytes (24kHz, mono, 16-bit PCM).
  - `_concat_wav_bytes(*items: bytes)` — Ghép nhiều WAV PCM cùng format thành một WAV.
  - `_play_wav_bytes(wav_bytes: bytes, stop_event: threading.Event)` — Phát WAV bytes qua sounddevice. Fallback → miniaudio stream.
  - `_play_wav_miniaudio(wav_bytes: bytes, stop_event: threading.Event)` — Phát WAV qua miniaudio (không cần sounddevice).
  - `_translate_to_japanese(text: str, api_key: str)` — Dịch câu tiếng Việt/Anh sang tiếng Nhật (giọng dễ thương) bằng Gemini.
  - `_clean_text(text: str)` — Bỏ markdown/code/URL trước khi đọc, nhưng giữ line break có chủ ý.
  - `build_tts_engine()` — Entry point — gọi một lần trong vision.py.
- Classes:
  - `TtsPlaybackEvent` (decorator=dataclass(frozen=True, slots=True)) — Lifecycle event của một đoạn TTS.
  - `_SpeakRequest`
    - `__init__(self, text: str, valence: float=0.0, arousal: float=0.3, stance: str='', on_start_play=None, prelocalized: bool=False, prosody_style: str='', prosody_notes: str='', turn_id: str='', segment_id: int=0, interruptible: bool=True, vocal_cache_kind: str='', vocal_prefix: str='', on_event=None)`
  - `_TtsWorker`
    - `__init__(self, voice: str, model: str, language_hint: str)`
    - `speak(self, req: _SpeakRequest, *, replace: bool=True)` — Enqueue một đoạn TTS.
    - `shutdown(self)`
    - `_emit(self, req: Optional[_SpeakRequest], event_type: str, *, reason: str='', error: str='')`
    - `_drop_one_pending(self, *, reason: str)`
    - `_drain_pending(self, *, reason: str)`
    - `_vocal_prefix_wav(self, req: _SpeakRequest, prefix: str, prosody_plan)` — Lấy/sinh WAV cho prefix nghe được như "Hah... haha.".
    - `_run(self)`
  - `TtsEngine` — Engine TTS chính. Gắn vào coordinator.tts_engine.
    - `__init__(self)`
    - `speak(self, text: str, *, valence: float=0.0, arousal: float=0.3, stance: str='', on_start_play=None, prelocalized: bool=False, prosody_style: str='', prosody_notes: str='', turn_id: str='', segment_id: int=0, interruptible: bool=True, vocal_cache_kind: str='', vocal_prefix: str='', replace: bool=True, on_event=None)` — Phát TTS cho text với cảm xúc cho trước. Non-blocking.
    - `shutdown(self)`

## `runtime/tts_markup.py`
- LOC: 67
- Docstring: tts_markup.py — render ProsodyPlan thành transcript cho Gemini TTS.
- Functions:
  - `render_tts_markup(text: str, plan: ProsodyPlan)`
  - `_normalize_lines(text: str)` — Chuẩn hoá transcript nhưng không xoá nhịp dòng.
  - `_apply_pause(text: str, plan: ProsodyPlan)`

## `runtime/tutor_daemon.py`
- LOC: 397
- Docstring: runtime/tutor_daemon.py
- Classes:
  - `TutorStageEmitter` — Gửi Popup_Event qua transport. Lỗi gửi không bao giờ chặn episode.
    - `__init__(self, transport: Any=None, logger: Optional[TutorLogger]=None)`
    - `emit(self, episode: TutorEpisode, stage: str)`
  - `TutorDaemon` — Chạy vòng đời một Tutor_Episode mỗi `run_once` khi đủ điều kiện.
    - `__init__(self, config: Optional[TutorConfig]=None, *, collector: Any, gate: Any, formulator: Any, backend: Any, digest: Any, share_impulse: Any=None, classifier: Any=None, router: Any=None, emitter: Optional[TutorStageEmitter]=None, risk_guard: Optional[TutorRiskGuard]=None, logger: Optional[TutorLogger]=None, drive_fn: Optional[Callable[[], float]]=None)`
    - `run_once(self, *, idle: bool, now: Optional[float]=None)`
    - `_run_once_locked(self, *, idle: bool, now: Optional[float]=None)`
    - `ask_now(self, topic: str, *, context: str='', now: Optional[float]=None)` — Hỏi gia sư NGAY và TRẢ VỀ nội dung câu trả lời (cho nhịp 2 của chat).
    - `_ask_user(self, episode: TutorEpisode, gap: Any, now: float)` — Eris hỏi LẠI Ngài (nói ra) thay vì lén hỏi Gemini. Không mở browser, không tab.
    - `stop(self)`
    - `_drive_level(self)`
    - `_emit(self, episode: TutorEpisode, stage: str)`
    - `_fail(self, episode: TutorEpisode, reason: str, now: float)`

## `runtime/tutor_wiring.py`
- LOC: 724
- Docstring: runtime/tutor_wiring.py
- Functions:
  - `_is_generic_telemetry_line(text: str)` — True nếu một dòng chỉ là telemetry chung chung, KHÔNG phải nội dung màn hình thật.
  - `build_tutor_daemon_from_runtime(runtime_owner: Any)` — Dựng TutorDaemon đã nối adapter, hoặc None nếu Master_Switch tắt / lỗi build.
  - `_ask_gemini_grounding_fallback(runtime_owner: Any, topic: Any, logger: Any)` — Fallback cho request_tutor_answer khi tutor web/browser chết.
  - `_attach_knowledge_provider(runtime_owner: Any, logger: Any)` — Gắn KnowledgeProvider vào SituationModel để dự đoán dùng tri thức đã học.
  - `tutor_tick(runtime_owner: Any, *, observer_frame: Any=None, channel: str='', snapshot: Any=None)` — Nạp gap (observer + violation) rồi chạy một episode nếu đủ điều kiện. Không bao giờ ném.
  - `_build_generate_fn(runtime_owner: Any, logger: Any)` — Local hoặc Remote LLM text gen để sinh câu hỏi/phân loại. None ⇒ heuristic fallback.
  - `_build_distill_fn(runtime_owner: Any, logger: Any)` — Tách câu trả lời gia sư thành các fact ngắn, atomic qua local hoặc remote LLM.
  - `_build_ingest_fn(runtime_owner: Any, tutor_logger: Any, logger: Any)` — Đường commit claim vào trí nhớ ngữ nghĩa (có embedding) qua memory core/kernel.
  - `_build_thought_sink(runtime_owner: Any, logger: Any)` — Đẩy Share_Impulse vào internal_agenda nếu có. None ⇒ không khoe (an toàn).
  - `_build_already_known_fn(runtime_owner: Any)` — True nếu Eris đã biết topic (recall trí nhớ trúng) ⇒ router skip, đỡ hỏi lại.
  - `_build_drive_fn(runtime_owner: Any)`
  - `_reach_internal_agenda(runtime_owner: Any)`
  - `_screen_context_from_snapshot(snapshot: Any)` — Đóng gói nội dung màn hình THẬT cho Gemini đoán ngữ cảnh.
  - `_reach_situation_model(runtime_owner: Any)`
  - `_reach_situation_violation(runtime_owner: Any)`
  - `_reach_memory_commit(runtime_owner: Any)` — Trả callable commit(request) từ memory_kernel/memory_core nếu có.
  - `_reach_semantic_store(runtime_owner: Any)` — Trả semantic store (có recall + embedding_index) từ memory core/kernel.
  - `_warn(logger: Any, message: str)`
  - `_info(logger: Any, message: str)`

## `runtime/utterance_evaluator.py`
- LOC: 344
- Functions:
  - `evaluator_enabled()`
  - `mentor_enabled()`
  - `_normalize_vi(text: Any)`
  - `_as_text(value: Any)`
- Classes:
  - `UtteranceEvaluation` (decorator=dataclass(frozen=True, slots=True))
    - `ok(self)`
  - `UtteranceEvaluator` — Rubric nhỏ để câu nháp tự qua một lượt nghe lại.
    - `evaluate(self, text: str, *, channel: str='', user_text: str='', snapshot: Any=None, frame: Any=None, speech_core: Any=None, grounding: Any=None)`
    - `mentor_context(self, *, text: str, evaluation: UtteranceEvaluation, channel: str='', user_text: str='', snapshot: Any=None, frame: Any=None, speech_core: Any=None, grounding: Any=None)`
    - `_evidence_text(self, *, snapshot: Any=None, frame: Any=None, speech_core: Any=None, grounding: Any=None)`
    - `_domain_from_text(self, text: Any, *, current_context: bool=False)`
    - `_has_activity_support(self, normalized_text: str, evidence_text: str)`
    - `_token_overlap(self, normalized_text: str, evidence_text: str)`

## `runtime/utterance_selector.py`
- LOC: 333
- Functions:
  - `_normalize_ascii(text: Any)`
  - `_words(text: str)`
  - `_has_any(text: str, markers: tuple[str, ...])`
- Classes:
  - `CandidateScore` (decorator=dataclass(frozen=True, slots=True))
  - `UtteranceSelection` (decorator=dataclass(frozen=True, slots=True))
  - `UtteranceSelector` — Deterministic scorer cho câu nháp public.
    - `__init__(self, evaluator: Any | None=None)`
    - `choose_best(self, candidates: tuple[str, ...] | list[str], *, channel: str='micro_presence', user_text: str='', avoid_text: str='', context: dict[str, Any] | None=None, must_surface: bool=False, min_score: float=0.54, snapshot: Any=None)`
    - `score_candidate(self, text: str, *, channel: str='micro_presence', user_text: str='', avoid_text: str='', context: dict[str, Any] | None=None, snapshot: Any=None)`
    - `_near_duplicate(self, text: str, avoid_text: str)`
    - `_token_overlap(self, text: str, anchor: str)`

## `runtime/vocal_cache.py`
- LOC: 125
- Docstring: vocal_cache.py — cache WAV cho các âm biểu diễn ngắn.
- Functions:
  - `vocal_cache_enabled()`
  - `_cache_root()`
  - `_safe_part(value: str)`
  - `strip_audible_prefix(text: str, prefix: str)` — Tách prefix nghe được khỏi transcript nếu nó nằm ở đầu câu.
- Classes:
  - `VocalCacheKey` (decorator=dataclass(frozen=True, slots=True))
    - `fingerprint(self)`
  - `VocalCache` — File cache nhỏ cho WAV prefix.
    - `__init__(self, root: Path | str | None=None)`
    - `path_for(self, key: VocalCacheKey)`
    - `get(self, key: VocalCacheKey)`
    - `put(self, key: VocalCacheKey, wav_bytes: bytes)`

## `runtime/voice_policy.py`
- LOC: 175
- Docstring: voice_policy.py — Nguồn sự thật DUY NHẤT cho giọng/persona của ERIS.
- Functions:
  - `normalize_guard_ascii(text: str)`
  - `is_disclaimer_text(text: str)` — Flag-agnostic check: hard + helper markers (the helpdesk register).
- Classes:
  - `VoicePolicy` (decorator=dataclass(frozen=True)) — Nguồn canonical: 3 đầu ra cho 3 nơi tiêu thụ, không nơi nào tự định nghĩa lại.
    - `forbidden_markers(self, category: str)`
    - `is_disclaimer(self, text: str)`
    - `normalize(self, text: str)`
    - `render_prompt_constraint(self)`
    - `render_anti_disclaimer_fewshot(self)`
    - `render_reroll_clause(self)`

## `sender.py`
- LOC: 41
- Functions:
  - `main()`

## `telemetry/__init__.py`
- LOC: 11

## `telemetry/content_metadata.py`
- LOC: 608
- Docstring: Thu thập metadata nội dung đang nhìn thấy cho SeLens.
- Functions:
  - `_candidate_cache_paths(env_name: str, filename: str)`
  - `_pick_matching_url(candidates: list[dict[str, Any]], current_url: str)`
  - `_infer_page_kind(*, url: str, title: str)`
  - `_normalize_hashtags(value: Any)`
  - `_normalize_media_state(value: Any)`
  - `_clean_text(value: Any, limit: int)`
  - `_dedupe_join(values: list[str], *, limit: int)`
  - `_choose_longer(left: str, right: str, *, limit: int)`
  - `_text_overlap(left: str, right: str)`
  - `_tokenize(value: str)`
  - `_domain_from_url(url: str)`
  - `_domain_matches(domain: str, expected_domains: tuple[str, ...])`
  - `_coerce_float(value: Any, default: float)`
  - `_env_bool(name: str, default: bool)`
  - `_env_int(name: str, default: int)`
  - `_env_float(name: str, default: float)`
- Classes:
  - `ContentMetadata` (decorator=dataclass(slots=True)) — Fact thô về nội dung foreground.
    - `to_dict(self)`
  - `ContentMetadataCollector` — Best-effort collector cho metadata nội dung foreground.
    - `__init__(self)`
    - `collect(self, *, active_window: str, browser_url: str='', browser_tabs: tuple[str, ...]=())`
    - `_merge_sources(self, *, dom: ContentMetadata | None, ocr: ContentMetadata | None, accessibility: ContentMetadata | None, media_session: ContentMetadata | None, fallback: ContentMetadata, now: float)`
    - `_read_dom_bridge(self, *, now: float, current_url: str)`
    - `_read_media_session_cache(self, *, now: float, current_url: str)` — Đọc cache now-playing nếu module khác ghi được Media Session/SMTC.
    - `_read_ocr_cache(self, *, now: float, current_url: str)`
    - `_read_accessibility_text(self, *, active_window: str, url: str)`
    - `_from_browser_or_window_title(self, *, active_window: str, browser_url: str, browser_tabs: tuple[str, ...], now: float, privacy_level: str)`
    - `_read_fresh_json(self, paths: tuple[Path, ...], *, now: float, stale_after: float)`
    - `_privacy_level(self, *, active_window: str, url: str)`

## `telemetry/service.py`
- LOC: 61
- Classes:
  - `TelemetryService` (base=TelemetryMixin)
    - `__init__(self)`
    - `capture_snapshot(self, *, mood_score: int, inferred_pos_x: float)`
    - `format_snapshot(self, snapshot: TelemetrySnapshot)`
    - `format_directive_snapshot(self, snapshot: TelemetrySnapshot)`
    - `capture_machine_context(self, *, mood_score: int, inferred_pos_x: float)`
    - `get_system_telemetry(self, *, mood_score: int, inferred_pos_x: float)`
    - `capture_screen_frame_data_uri(self, *, max_side: int=960, quality: int=82)`

## `telemetry/system.py`
- LOC: 286
- Functions:
  - `_self_window_titles()` — Tên cửa sổ của chính Eris cần loại khỏi telemetry.
  - `_is_self_window(title: str)`
  - `_ensure_com_initialized()`
- Classes:
  - `TelemetryMixin`
    - `_get_content_metadata_collector(self)`
    - `_get_browser_telemetry_uia(self)`
    - `_enum_visible_titled_windows(self)` — Trả danh sách title cửa sổ hiển thị theo thứ tự Z (trên xuống dưới).
    - `_get_all_windows(self)`
    - `_resolve_active_window(self)` — Cửa sổ người dùng thực sự đang nhìn.
    - `_get_idle_seconds(self)`
    - `capture_raw_telemetry(self, *, mood_score: int, inferred_pos_x: float)`
    - `get_system_telemetry(self, *, mood_score: int, inferred_pos_x: float)`

## `transport/__init__.py`
- LOC: 3

## `transport/udp.py`
- LOC: 278
- Functions:
  - `_compact_private_mind_for_udp_overflow(value)`
  - `_compact_inner_diary(diary)` — Compact inner_diary giữ nguyên sections/items để C# có thể parse đúng.
  - `_slim_private_mind_core(private_mind)` — Bản rút gọn cứng của private_mind_digest.
  - `_compact_debug_value(value, *, depth: int)`
  - `_compact_scalar(value, limit: int)`
  - `_compact_reasoning_tags(value)`
  - `_compact_debug_trace(value, *, limit: int=240)`
  - `_core_udp_payload(payload: dict, *, text_limit: int | None=None, debug_limit: int=240)`
- Classes:
  - `UdpTransport`
    - `__init__(self, send_host: str, send_port: int, recv_host: str, recv_port: int)`
    - `send_text(self, message: str)`
    - `send_json(self, payload: dict)`
    - `poll_json(self)`
    - `close(self)`

## `vision.py`
- LOC: 268
- Classes:
  - `AttentionOverseer`
    - `__init__(self, model_path: str='', n_ctx: int=8192, n_gpu_layers: int=-1)`
    - `_is_body_running(self)`
    - `stop(self, reason: str='')`
    - `run_loop(self)`
  - `SingleInstanceLock`
    - `__init__(self, lock_path: str)`
    - `acquire(self)`
    - `release(self)`


# 11. Kết luận kiến trúc hiện tại

Quan sát -> Tín hiệu mạnh -> Giả thuyết mạnh nhất -> Mức tự tin -> Giả thuyết cạnh tranh:

- Quan sát: repo hiện tại có runtime Python lớn, nhiều module stateful, private_mind/private_life/thought_stream/surface/memory đều đã có file thật và wiring qua coordinator.
- Tín hiệu mạnh: `runtime/coordinator.py` nối daemon, wake governor, model budget, surface arbiter, memory kernel; `cortex/private_mind/*` có concern/mutation/surface valve; `cortex/private_life/*` có state đời sống riêng; `memory/*` có query IR và multi-layer store.
- Giả thuyết mạnh nhất: ERIS hiện không còn là chatbot prompt-only; nó là runtime agent stateful với nhiều substrate nhận thức, nhưng vẫn đang lệ thuộc vào coordinator lớn và policy/gate phức tạp.
- Mức tự tin: 0.88 dựa trên AST + docstring + file wiring trong zip.
- Giả thuyết cạnh tranh: nếu body/Godot/tests nằm ngoài zip thì tài liệu này chưa phản ánh hết runtime thật; nếu một số module có docstring tham vọng hơn logic bên trong thì cần audit dòng-level riêng cho module đó.
