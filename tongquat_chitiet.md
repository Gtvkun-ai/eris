# ERIS — TỔNG QUÁT CHI TIẾT, BẢN VIẾT LẠI TỪ REPO HIỆN TẠI

> Mục tiêu: tài liệu file-to-file để debug và hiểu runtime ERIS. Bản này được dựng lại từ repo thật trên đĩa (`c:\Users\Gtvkun\Documents\GitHub\eris`), không dựa vào trí nhớ mơ hồ hay README màu mè. Phần Python parse từ `src/`, phần body parse từ `body/`.

## Phạm vi và giới hạn trung thực

- Nguồn Python: AST parse từ `src/` trong repo thật (`c:\Users\Gtvkun\Documents\GitHub\eris\src`). Bố cục `src/` khớp bảng snapshot bên dưới (`actions/ core/ cortex/ domain/ llm/ memory/ parser_grounding/ runtime/ telemetry/ transport/ vision.py`).
- Nguồn C# body: đọc trực tiếp 8 file trong `body/` của repo thật và **đã audit lại** (xem ghi chú ở Phần 1).
- Lưu ý lịch sử: bản doc gốc được sinh từ `src/src.zip` (chỉ chứa phần Python). Vì `body/`, `tests/`, Godot scene nằm **ngang hàng** với `src/` chứ không nằm trong zip, bản cũ tưởng nhầm là chúng "không tồn tại". Thực tế repo thật **có đủ** `body/` (C#), `tests/`, `project.godot`, `body/UdpListener.tscn`, `asset/`, `config/`.
- Tổng Python đã parse bằng AST: **298 file**, khoảng **138924 LOC**. Các file cache `.pyc` và `.hypothesis` bị bỏ qua.
- Tài liệu này ưu tiên debug thực dụng: file nào sở hữu state, file nào gọi ai, lỗi nào nên soi ở đâu. Không cố biến mọi module thành tiểu thuyết.

## 0. Snapshot repo

| Gốc | Python files | LOC |
|---|---:|---:|
| `actions/` | 4 | 1249 |
| `core/` | 4 | 2513 |
| `cortex/` | 150 | 68410 |
| `domain/` | 2 | 104 |
| `llm/` | 9 | 4986 |
| `memory/` | 59 | 17430 |
| `parser_grounding/` | 3 | 2125 |
| `runtime/` | 56 | 40400 |
| `telemetry/` | 4 | 918 |
| `transport/` | 2 | 253 |
| `vision.py` | 1 | 240 |

### File state/runtime trong `memory_core/`

- `memory_core/anchor_journal.jsonl` — jsonl_lines=201
- `memory_core/anchor_state.json` — keys=schema_version, updated_at, state
- `memory_core/inner_diary.json` — keys=updated_at, last_tick_at, current, inner_diary, history
- `memory_core/private_concerns.json` — keys=version, saved_at, concerns
- `memory_core/private_life_state.json` — keys=version, updated_at, habitat, attachments, projects, anchors, daily, taste, solitude, rituals, errands, events
- `memory_core/thought_stream.jsonl` — jsonl_lines=5
- `memory_core/user_model.json` — keys=schema_version, updated_at, version, beliefs, history


# 1. Body Godot/C# — ĐÃ AUDIT TỪ `body/` TRONG REPO THẬT

> Ghi chú trung thực: repo thật **có** thư mục `body/` (8 file `.cs` + `UdpListener.tscn`). Đã đọc trực tiếp và đối chiếu chữ ký từng class/method bằng AST C#. Kết quả: mô tả bên dưới **khớp** mã nguồn thật. Kích thước file tại thời điểm audit: `BodyAudioController.cs` 4.5KB, `ErisProcessManager.cs` 11.5KB, `LocalBodyAutonomy.cs` 21.8KB, `MotionController.cs` 21.2KB, `RunLogger.cs` 3.9KB, `UdpDecisionParser.cs` 11.7KB, `UdpListener.AnchorPanel.cs` 37.9KB, `UdpListener.cs` 199.7KB. Không còn là "legacy snapshot" — đây là bản đồ debug C# đã xác minh.

# PHẦN C# / GODOT BODY — ĐÃ XÁC MINH  [body/]
================================================================================
Phía "thân xác". Không suy nghĩ; chỉ vẽ, phát animation/âm thanh, nhận Decision
qua UDP 4242, gửi event/chat lên runtime qua UDP 4243, và tự đi lại khi rảnh.

--------------------------------------------------------------------------------
## body/UdpListener.cs
--------------------------------------------------------------------------------
**Vai trò:** Node chính của scene (`Node2D`, partial class). Bind UDP 4242, dựng
toàn bộ UI/panel (chat, emotion, private mind, anchor, context menu), spawn
vision.py, mỗi frame bước motion + đọc packet + áp dụng Decision. Phần "anchor"
nằm ở file partial `UdpListener.AnchorPanel.cs`.

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
- `BuildCharacterContextMenuUi()` — dựng menu chuột phải (các nút Chat/Touch/ForceSpeak/Emotion/PrivateMind/Anchor/Exit/Close).
- `ShowCharacterContextMenu(pos)` / `CloseCharacterContextMenu()` — hiện/ẩn menu tại vị trí chuột.
- `BuildEmotionPanelUi()` / `RefreshEmotionPanel()` — dựng & đổ data panel cảm xúc từ `_latestEmotionDebug`.
- `BuildPrivateMindPanelUi()` / `RefreshPrivateMindPanel()` — dựng & đổ data panel inner diary từ `_latestPrivateMindDebugJson`.
- `UpdatePrivateMindDecorLayout()` / `UpdatePrivateMindScrollDecor()` — cập nhật trang trí/scrollbar panel private mind mỗi frame khi mở.
- `MakePanelDraggable(panel)` / `UpdatePanelDrag()` — cho kéo-thả panel nổi.
- `OnSendPressed()` — gửi text trong ô chat xuống cortex (UDP 4243), xoá input.
- `SendChatSignal(string)` — gửi 1 signal/text thô lên 4243 (chat_start/chat_end/force_speak/text).
- `ParseAndApply(string raw)` — gọi `_decisionParser.Parse(raw)`, áp text/should_speak vào
  bong bóng, đẩy MotionCommand vào `_motion`, nạp body_bias vào `_bodyAutonomy`, lưu
  emotion_debug & private_mind_digest, log debug_trace/parse_mode.
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
| `app_logging.py` | 29 | CategoryFormatter | Module `app logging` trong package `.`. |
| `eris_secrets.py` | 192 | - | Module `eris secrets` trong package `.`. |
| `guard_config.py` | 49 | - | Module `guard config` trong package `.`. |
| `sender.py` | 26 | - | Module `sender` trong package `.`. |
| `vision.py` | 240 | AttentionOverseer, SingleInstanceLock | Entry point Python. Boot order: cấu hình logging, giữ `.vision.lock`, dựng `RemoteModelProcessManager`, `LlmService`, `UdpTransport`, `MemoryCognitionCore`, parser, telemetry, N... |

## core
Contract V3 thấp nhất: RawSignal, EvidenceItem, ModuleReport, StateCommitRequest, CognitiveFrame và EvidenceNormalizer. Đây là lớp bắt mọi thứ có nguồn, confidence và privacy tag trước khi đi tiếp.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `core/__init__.py` | 23 | - | Package init / export boundary. |
| `core/cognitive_frame.py` | 1443 | FrameMutation, FrameValidationIssue, FramePromptPacket, CognitiveFrame | core/cognitive_frame.py Khung nhận thức trung tâm cho ERIS Cognitive Pipeline. File này là "xương sống runtime" của Phas... |
| `core/evidence.py` | 838 | RawSignalValidationError, RawSignal, EvidenceItem, ModuleReport | Module `evidence` trong package `core`. |
| `core/evidence_normalizer.py` | 209 | EvidenceNormalizerConfig, NormalizationResult, EvidenceNormalizer | core/evidence_normalizer.py Lớp trung gian bắt buộc của Phase 0/1: RawSignal -> EvidenceItem -> (CognitiveFrame.evidence... |

## domain
Contract `Decision` cuối cùng giữa cognition và body. Nó resolve text/should_speak/motion rồi serialize payload cho UDP.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `domain/__init__.py` | 6 | - | Package init / export boundary. |
| `domain/decision.py` | 98 | Decision | Dataclass Decision và `to_payload()`. Resolve motion_intent/target/facing/text/should_speak trước khi gửi UDP. |

## transport
Kênh UDP 4242/4243, kèm logic nén payload debug/private_mind khi vượt giới hạn packet.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `transport/__init__.py` | 4 | - | Package init / export boundary. |
| `transport/udp.py` | 249 | UdpTransport | UDP transport. Send JSON Decision, poll event body, nén private_mind_digest/debug khi quá 63KB. |

## llm
Façade gọi model: key pool, client Gemini/OpenAI-compatible/Ollama/llama.cpp, prompt contract, schema Decision, repair JSON, guard chống leak prompt/CoT.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `llm/__init__.py` | 30 | - | Package init / export boundary. |
| `llm/client.py` | 426 | LlamaServerClient, OpenAICompatibleClient, GeminiClient | HTTP client Gemini/OpenAI-compatible/llama-server, payload variants, 429 key rotation, image payload, HTTP error body. Debug khi provider shape lạ hoặc key pool xoay không đúng. |
| `llm/contracts.py` | 240 | - | Contract/dataclass dùng chung trong llm. |
| `llm/key_pool.py` | 159 | ApiKeyPool | llm/key_pool.py Pool API key dùng CHUNG cho mọi mạch gọi Gemini (main / speech / private_mind). Mỗi key thường thuộc một... |
| `llm/llamacpp_client.py` | 126 | LlamaCppClient | llm/llamacpp_client.py ====================== Engine inference local IN-PROCESS dựa trên llama-cpp-python. Mục đích: chạ... |
| `llm/local_llama_engine.py` | 297 | LocalLlamaEngine | llm/local_llama_engine.py ========================= Engine local thống nhất bằng llama-cpp-python, drop-in thay cho ``Ol... |
| `llm/ollama_client.py` | 317 | OllamaClientError, OllamaResult, OllamaClient | Client mỏng cho Ollama. Vai trò trong ERIS: - Dùng một Ollama daemon duy nhất thay vì mở nhiều llama-server riêng. - Gọi... |
| `llm/process_manager.py` | 239 | RemoteModelProcessManager | Module `process manager` trong package `llm`. |
| `llm/service.py` | 3152 | ChatAct, FormatViolationException, LlmService | Façade gọi model. Build prompt theo chat/directive/autonomous/micro/vision, parse Decision JSON, repair malformed JSON, chống prompt leak, fallback protocol/service, style rewri... |

## runtime
Xương sống điều phối. Coordinator + mixin nhận event, chạy cognitive frame, wake governor, speech pipeline, private mind/life, memory commit, source grounding, model budget và gửi Decision ra body.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `runtime/__init__.py` | 24 | - | Runtime package của ERIS. Không import RuntimeCoordinator eager ở đây. Lý do rất đời thường: nhiều test chỉ cần `runtime... |
| `runtime/affect_self_read.py` | 297 | AffectSelfReadConfig, AffectSelfReadAdapter | affect_self_read.py — ERIS tự đọc cảm xúc của chính mình (interoception). Vấn đề: internal_state đưa vào prompt dưới dạn... |
| `runtime/ambient_silence_policy.py` | 75 | - | Shared ambient-silence / muse policy for the autonomous idle loop. ``coordinator.py`` and ``autonomous_cycle.py`` histor... |
| `runtime/autonomous_cycle.py` | 1241 | AutonomousCycleMixin | Đường idle/autonomous. Nó poll input, bucket idle/window spread, update vision facts, track autonomous signature, chọn speech intent và quyết định skip/hold theo ambient silence... |
| `runtime/autonomous_wake_governor.py` | 262 | WakeDecision, WakeGovernorConfig, AutonomousWakeGovernor | Trọng tài mức thức: sleep, observe_only, think_only, micro_presence, call_vision_compressor, wake_main_cognition. Tính external pressure, internal drive, permission, speech valu... |
| `runtime/background_memory_digest.py` | 60 | - | Store/facade/truy xuất hoặc lifecycle dữ liệu cho runtime. |
| `runtime/background_memory_digest_kernel.py` | 466 | BackgroundMemoryDigestKernelConfig, MemoryDigestKernelJob, MemoryDigestKernelStats, BackgroundMemoryDigestKernelService | Store/facade/truy xuất hoặc lifecycle dữ liệu cho runtime. |
| `runtime/body_bias.py` | 116 | BodyBiasProjector | Module `body bias` trong package `runtime`. |
| `runtime/chat_cycle.py` | 1636 | ChatCycleMixin | Đường xử lý user chat. Nó gom burst, build source grounding report, xử lý screen request, memory recall deterministic, repeat guard, previous-public-turn repair, rồi đẩy qua spe... |
| `runtime/cognitive_budget.py` | 2706 | BudgetModeProfile, BudgetSignalSnapshot, BudgetScoreBreakdown, PipelineStepDecision | src/runtime/cognitive_budget.py ================================ Bộ chọn Cognitive Budget cho ERIS. Mục tiêu: Chọn đường... |
| `runtime/cognitive_cycle.py` | 408 | CognitiveCycleMixin | Lifecycle/tick/cycle owner cho runtime. |
| `runtime/cognitive_frame_recorder.py` | 1369 | CognitiveFrameRecorderMixin | Module `cognitive frame recorder` trong package `runtime`. |
| `runtime/cognitive_pipeline.py` | 295 | PipelineResult, CognitivePipeline | runtime/cognitive_pipeline.py Xương sống Phase 1 của ERIS V3. Mục tiêu của file này là biến mớ module rời rạc thành MỘT... |
| `runtime/contextual_autonomy_loop.py` | 236 | ContextualAutonomyLoopConfig, AutonomyLoopTickResult, ContextualAutonomyLoop | src/runtime/contextual_autonomy_loop.py ====================================== Adaptive heartbeat cho 3-tier autonomy. M... |
| `runtime/controlled_slippage.py` | 600 | RepairSuppressionView, ControlledSlippageProfile | Module `controlled slippage` trong package `runtime`. |
| `runtime/coordinator.py` | 7576 | RuntimeCoordinator | Orchestrator trung tâm. Kế thừa nhiều mixin để chia chat/autonomous/force_speak/presence/frame/speech/memory/filter/shadow. Trong `__init__` nó nối gần như toàn bộ engine: salie... |
| `runtime/daydream_model_adapter.py` | 101 | DaydreamModelAdapterConfig, DaydreamModelResult, RuntimeDaydreamModelAdapter | Adapter nối runtime với engine/model/store khác trong runtime. |
| `runtime/debug_console.py` | 392 | DebugConsole | debug_console.py — Bảng lệnh debug ẩn cho ERIS. Đây KHÔNG phải đường runtime bình thường. Nó là cổng để Tác_Giả gõ lệnh... |
| `runtime/debug_trace.py` | 305 | - | runtime/debug_trace.py Debug Output Standard cho ERIS V3. Vấn đề kinh điển: pipeline chạy, module nào cũng có, nhưng khi... |
| `runtime/disclaimer_markers.py` | 33 | - | Shared anti-disclaimer marker lists + predicates. Đây từng là HOME của các marker register cấm. Sau khi gom về một nguồn... |
| `runtime/eris_pathology_policy.py` | 469 | PathologyDecision, ErisPathologyPolicy | Policy module cho runtime: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục. |
| `runtime/force_speak_cycle.py` | 497 | ForceSpeakCycleMixin | Lifecycle/tick/cycle owner cho runtime. |
| `runtime/force_speak_surface_policy.py` | 148 | ForceSpeakSurfacePolicyMixin | Policy module cho runtime: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục. |
| `runtime/frame_builder.py` | 1733 | FrameBuilderMixin | Module `frame builder` trong package `runtime`. |
| `runtime/guard_violations.py` | 45 | GuardViolation | Module `guard violations` trong package `runtime`. |
| `runtime/inner_diary_persistence.py` | 186 | InnerDiaryPersister | runtime/inner_diary_persistence.py ================================== Ghi `inner_diary` (và một ít ngữ cảnh từ private m... |
| `runtime/liveliness_config.py` | 109 | LivelinessConfig | Configuration for the autonomous-liveliness redesign. All values are read from ``ERIS_LIVELINESS_*`` environment variabl... |
| `runtime/liveliness_tracker.py` | 106 | DecisionRecord, LivelinessMetrics, LivelinessTracker | Per-cycle liveliness tracking and observability for the autonomous loop. Each idle cycle emits one ``DecisionRecord`` so... |
| `runtime/memory_recall_adapter.py` | 459 | _MemoryQueryLLMConfig, MemoryRecallAdapter, _RecallOutcome, _MemoryCoreProxy | Adapter nối runtime với engine/model/store khác trong runtime. |
| `runtime/memory_semantic_parser_adapter.py` | 363 | _StandaloneOllamaResult, _StandaloneOllamaClient, MemorySemanticParserConfig, RuntimeSemanticParser | Adapter nối runtime với engine/model/store khác trong runtime. |
| `runtime/model_budget_policy.py` | 894 | ResourceSnapshot, BudgetDecision, ModelQueueEntry, InferenceLease | Scheduler/gatekeeper model. Quản tier main/subconscious/vision/sensory, lease, queue, resource snapshot, cooldown, active heavy lock. Debug khi model chạy chồng, local GGUF/visi... |
| `runtime/no_fallback_policy.py` | 57 | - | Policy module cho runtime: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục. |
| `runtime/outcome_observer.py` | 557 | OutcomeReport, OutcomeObserver | Module `outcome observer` trong package `runtime`. |
| `runtime/post_generation_filters.py` | 1938 | PostGenerationFiltersMixin | Hàng rào cuối trước public output. Chặn prompt leak, debug leak, memory haunting, unsupported current-screen claim, over-mindreading, register sai và micro-line xấu. Debug khi c... |
| `runtime/presence_controller.py` | 3228 | MicroPresenceSynthesis, SocialPresenceEvent, MicroPresenceCue, SurfaceArbitrationResult | Cổng presence/micro/reengagement. Nó build `MicroPresenceCue`, dùng `SurfaceSeedCompiler`, gọi `SurfaceArbiter`, tạo body-only hoặc speech decision, có cooldown và chính sách re... |
| `runtime/private_life_daemon.py` | 332 | PrivateLifeDaemonConfig, PrivateLifeDaemonTick, PrivateLifeDaemon | Lifecycle owner của PrivateLifeCore. Đẩy habitat/project/rhythm/solitude vào runtime, sinh digest và surface seed. Debug khi đời sống riêng không cập nhật hoặc vẫn bị neo 100% v... |
| `runtime/private_mind_daemon.py` | 433 | PrivateMindDaemonConfig, PrivateMindDaemonTick, PrivateMindDaemon | Lifecycle owner của PrivateMindLoop. Giữ tick digest, queues, surface impulses, outcome. Debug khi private_mind_loop chạy rời rạc, digest mất hoặc inner diary không persist. |
| `runtime/private_mind_loop.py` | 767 | PrivateMindLoopConfig, PrivateMindLoop | Private mind 5 phase: ConcernStore, EvidenceDossierBuilder, MiniEvaluatorPipeline, GemmaInnerSynthesizer, StateMutationBus, SurfaceValve. Không tự nói; nó tạo mutation/state/sur... |
| `runtime/private_mind_model_adapter.py` | 1664 | PrivateMindModelAdapterConfig, PrivateMindModelResult, RuntimePrivateMindModelAdapter, PrivateMindAdapterPool | runtime/private_mind_model_adapter.py ===================================== Adapter API cho private mind: - evaluate_fra... |
| `runtime/prompt_context_builder.py` | 1018 | PromptContextBuilderMixin | Module `prompt context builder` trong package `runtime`. |
| `runtime/public_turn_ledger.py` | 132 | PublicTurn, PublicTurnLedger | Module `public turn ledger` trong package `runtime`. |
| `runtime/relational_voice_seed_adapter.py` | 578 | ChatRegister, VoiceSeedScope, RelationalAct, CognitionStance | Register-default voice-seed pipeline. For social-register chat turns, ERIS — not the remote model's "helpful assistant"... |
| `runtime/sensor_visibility.py` | 324 | SensorVisibilityState | Module `sensor visibility` trong package `runtime`. |
| `runtime/sensory_model_adapter.py` | 147 | SensoryModelAdapterConfig, RuntimeSensoryModelAdapter | Adapter nối runtime với engine/model/store khác trong runtime. |
| `runtime/session_turn_ledger.py` | 142 | SessionTurn, SessionTurnLedger | Module `session turn ledger` trong package `runtime`. |
| `runtime/shadow_pipeline.py` | 377 | ShadowPipelineMixin | runtime/shadow_pipeline.py Shadow mode cho CognitivePipeline (V3). Ý tưởng: Runtime thật vẫn chạy frame cũ (cortex/contr... |
| `runtime/signal_buffer.py` | 325 | SignalBufferConfig, SignalBufferStats, SignalBuffer | SignalBuffer cho Background Observer. Nhiệm vụ: - Giữ một cửa sổ snapshot gần đây. - Tính diff giữa snapshot mới và snap... |
| `runtime/source_grounding.py` | 1953 | SourceCandidate, SourceFallbackDecision, MemoryAnswerProfile, SourceGroundingReport | Bộ phân loại nguồn trước khi trả lời: user_text, memory, file mention, current_screen/live_vision, web/action/runtime. Nó tạo missing_evidence, forbidden_assumptions, confidence... |
| `runtime/speech_pipeline.py` | 79 | SpeechIntentDecision, SpeechPipelineMixin | Module `speech pipeline` trong package `runtime`. |
| `runtime/state_commit_service.py` | 872 | StateCommitServiceMixin | Module `state commit service` trong package `runtime`. |
| `runtime/state_committer.py` | 1110 | StateCommitterConfig, CommitValidationIssue, CommitDecision, CommitBatchReport | src/runtime/state_committer.py ================================ StateCommitter là cổng commit state/memory của ERIS. Ngu... |
| `runtime/subconscious_loop.py` | 412 | SubconsciousTickResult, SubconsciousLoop | Runtime adapter cho subconscious blackboard/synthesizer. Phase 0 dựng ThoughtFragment/Blackboard/Synthesizer. Phase 1-4... |
| `runtime/subconscious_model_adapter.py` | 334 | SubconsciousModelAdapterConfig, SubconsciousModelResult, RuntimeSubconsciousModelAdapter | Adapter gọi model/API riêng cho Lane 3 subconscious synthesis. Lane 3 không sinh lời thoại public. Nó chỉ lập một "biên... |
| `runtime/text_repeat_guard.py` | 154 | TextRepeatGuardMixin | Module `text repeat guard` trong package `runtime`. |
| `runtime/thought_model_adapter.py` | 84 | ThoughtModelAdapterConfig, RuntimeThoughtModelAdapter | runtime/thought_model_adapter.py ================================ Compatibility adapter cho ThoughtStream model review.... |
| `runtime/voice_policy.py` | 176 | VoicePolicy | voice_policy.py — Nguồn sự thật DUY NHẤT cho giọng/persona của ERIS. Trước đây "register cấm" (giọng trợ lý help-desk /... |

## cortex
Tầng nhận thức: Se/attention/working memory/global workspace/meaning/personality/Ni-Ti-Fe/internal state/relation/thought stream/speech/surface/body action.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/__init__.py` | 164 | - | Package init / export boundary. |
| `cortex/action_memory.py` | 439 | ActionTrace, ActionMemoryState | Action memory and rhythm state for ERIS. File này không quyết định câu chữ. Nó chỉ giữ lịch sử hành vi để planner không... |
| `cortex/action_planner.py` | 707 | ActionPlanner | Utility-based ActionPlanner for ERIS. Bản này thay lõi rule-based cũ bằng 3 tầng: 1. action_memory.py -> nhớ hành vi gần... |
| `cortex/action_utility.py` | 1053 | ActionContext, ActionScore, ActionUtilityReport, ActionUtilityScorer | Utility competition for ERIS actions. File này thay lõi "if intent == X -> return Y" bằng cạnh tranh utility. Không phải... |
| `cortex/affect_semantics.py` | 860 | AffectSemanticSignal, WeightedPhrase, AffectSemanticClassifier | affect_semantics.py =================== Module này dùng để phân tích "áp lực nghĩa" trong câu chat của user. Mục tiêu: -... |
| `cortex/agent_mind_persistence.py` | 732 | PersistentBeliefRecord, PersistentPreferenceRecord, SemanticHabitRecord, PersistentAgentMindStore | Persistent Agent Mind Layer cho ERIS. Module này giữ 3 lớp học dài hạn cho impulse system: 1. BeliefCore persistent - ER... |
| `cortex/agent_state_stack.py` | 742 | EvidenceView, Belief, BeliefSnapshot, PreferenceProfile | Agent state stack for ERIS. Lớp này gom các lực nền đang bị rải rác trong runtime thành một contract nhỏ: Evidence -> Be... |
| `cortex/appetite_system.py` | 314 | EvidenceItem, AppetiteConfig, AppetiteState, Reaction | cortex/appetite_system.py ========================= Chợ đấu giá của các CƠN THÈM — xương sống cho autonomous speech "sốn... |
| `cortex/appraisal.py` | 499 | AppraisalEngine | Module `appraisal` trong package `cortex`. |
| `cortex/attention_salience.py` | 1898 | SalienceWeights, AttentionSalienceConfig, SalienceFactorBreakdown, AttentionCandidate | cortex/attention_salience.py ============================ Selection backbone / anti-context-flood backbone cho ERIS Cogn... |
| `cortex/background_observer.py` | 660 | BackgroundObserverConfig, BackgroundObserver | BackgroundObserver cho ERIS. Bản này có 2 tầng: 1. Rule-based observer luôn chạy được, không phụ thuộc model. 2. Optiona... |
| `cortex/banned_filler.py` | 79 | - | Single source of truth for stale filler lines the character must never speak. Both the LLM prompt construction (``llm/se... |
| `cortex/chat_light.py` | 298 | ChatMeaningLayerLight, ChatPersonalityPressureLight | Module `chat light` trong package `cortex`. |
| `cortex/connection_drive.py` | 191 | ConnectionDriveConfig, ConnectionDriveState, ConnectionDriveDecision, ConnectionDrive | cortex/connection_drive.py ========================== Động lực nội sinh "sợ cô độc → tìm kết nối" cho ERIS. Vấn đề cũ: E... |
| `cortex/continuity_threat.py` | 343 | ContinuityThreatFrame | Continuity threat calculus for ERIS. Module này cố ý tách "im lâu" khỏi "đứt gãy hiện diện". Timer chỉ được dùng để hỏi:... |
| `cortex/contracts.py` | 1300 | UserSignals, TelemetrySnapshot, GoalDriftReport, TiPolicyReport | Contract/dataclass dùng chung trong cortex. |
| `cortex/conversation_dynamics.py` | 1051 | ConversationFailure, CorrectionAssessment, ContinuityCurve, ConversationDynamicsState | Module `conversation dynamics` trong package `cortex`. |
| `cortex/daydream_consolidation.py` | 377 | DaydreamPacket, DaydreamInsight, DaydreamResult, DaydreamConsolidationConfig | src/cortex/daydream_consolidation.py ==================================== Tầng 2b - Daydream Consolidation. Đây là nơi Q... |
| `cortex/development_bias.py` | 70 | - | development_bias.py — adapter thuần đưa Delta_Phát_Triển vào mặt phẳng biểu đạt. Nguyên tắc bất biến (R3, R7.3, R7.4): -... |
| `cortex/development_profile.py` | 540 | AxisDelta, GrowthAnchor, NudgeProposal, LogEntry | development_profile.py — Hồ_Sơ_Phát_Triển long-arc cho ERIS. Đây là tầng phát triển dài hạn (long-arc): độ lệch tích lũy... |
| `cortex/development_system.py` | 396 | ApplyResult, DevelopmentBias, DevelopmentLog, DevelopmentSystem | development_system.py — Sổ_Phát_Triển + điều phối apply/undo/reset. Tách khỏi ``development_profile`` (data + store + ga... |
| `cortex/disposition.py` | 234 | - | disposition.py — cây cầu state → ngôn ngữ cho ERIS. Vấn đề cũ: ``to_prompt_context`` đổ trạng thái nội tâm vào prompt dư... |
| `cortex/endogenous_drive.py` | 214 | RollingInternalState, EndogenousDriveConfig, EndogenousDriveEngine | src/cortex/endogenous_drive.py ============================== Tầng 2a - Endogenous Drive. File này giữ nhịp sinh học ngầ... |
| `cortex/event_semantics.py` | 311 | EventSemanticProfile, EventEmbeddingCache, _EventCluster, EventClusterIndex | Module `event semantics` trong package `cortex`. |
| `cortex/fe.py` | 2006 | FeAffectSignal, FeDevelopmentSnapshot, FeStylePressure, FeTopicCandidate | Module `fe` trong package `cortex`. |
| `cortex/global_workspace.py` | 1865 | WorkspaceSuppressionReason, WorkspaceItem, SuppressedWorkspaceItem, WorkspaceRisk | src/cortex/global_workspace.py ================================ Global Workspace / Broadcast Frame cho ERIS. Mục tiêu củ... |
| `cortex/goal_persistence.py` | 673 | GoalPersistenceState, GoalCandidate, GoalPersistenceEngine | Module `goal persistence` trong package `cortex`. |
| `cortex/greeting_cognition.py` | 319 | GreetingFrame, GreetingCognitionEngine | Module `greeting cognition` trong package `cortex`. |
| `cortex/greeting_quality.py` | 174 | GreetingQuality, GreetingQualityScorer | Module `greeting quality` trong package `cortex`. |
| `cortex/growth_consolidator.py` | 153 | GrowthObservation, GrowthConsolidatorConfig, GrowthConsolidator | growth_consolidator.py — Tác_Tử_Nền sinh Đề_Xuất_Nhích cho long-arc. Đặt trên kỷ luật của ``DaydreamConsolidator``: chỉ... |
| `cortex/growth_evidence.py` | 84 | - | growth_evidence.py — phiên dịch ký-ức-thật → GrowthObservation. Đây là "bộ phiên dịch" cho Tác_Tử_Nền: lấy feedback đã đ... |
| `cortex/impulse_arbitration.py` | 647 | ImpulseCandidate, ArbitrationReport, ImpulseArbitrator | Impulse competition for ERIS. Thay vì hardcode "đủ 5 phút thì nói", module này tạo nhiều impulse cùng lúc và chấm điểm b... |
| `cortex/inner_thought.py` | 281 | InnerThoughtEngine | Module `inner thought` trong package `cortex`. |
| `cortex/internal_agenda.py` | 386 | InternalAgendaItem, InternalAgendaStack | src/cortex/internal_agenda.py ================================ Stack agenda nội bộ cho ERIS. Module này là nơi giữ các v... |
| `cortex/internal_state.py` | 2085 | MentalProcess, CuriosityProcess, RestraintProcess, TensionProcess | Persistent internal state. Theo dõi valence/arousal/curiosity/boredom/social_energy/attachment/fatigue/silence_pressure và các MentalProcess con. Debug khi continuity mất sau re... |
| `cortex/low_level_speech_policy.py` | 343 | LowLevelSpeechPolicyConfig, LowLevelSpeechPolicy | Policy chọn generation mode cho surface thấp tầng. Nó không viết câu. Nó chỉ quyết định reject/body_only/normal_llm/force_llm theo confidence, kind, silent cycles, family cooldo... |
| `cortex/micro_contracts.py` | 245 | MicroLinePolicyResult, SemanticRepeatResult, ValidationIssue, RelationalContext | Contract/dataclass dùng chung trong cortex. |
| `cortex/micro_grounding_guard.py` | 264 | MicroGroundingGuard | Module `micro grounding guard` trong package `cortex`. |
| `cortex/micro_policy.py` | 441 | MicroLinePolicy | Policy module cho cortex: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục. |
| `cortex/micro_repeat_guard.py` | 424 | SemanticRepeatGuard | Module `micro repeat guard` trong package `cortex`. |
| `cortex/micro_surface_lint.py` | 513 | MicroSurfaceLint | Module `micro surface lint` trong package `cortex`. |
| `cortex/modes.py` | 15 | - | Module `modes` trong package `cortex`. |
| `cortex/ni.py` | 658 | NiEngine, NiStateMachine | Module `ni` trong package `cortex`. |
| `cortex/observer_contracts.py` | 429 | SignalSnapshot, SignalDiff, ObserverFrame, SemanticSceneNote | Contract cho Background Observer của ERIS. Tầng này không trả lời user, không commit memory, không tự hành động. Nó chỉ... |
| `cortex/orientation_context.py` | 1143 | ActivityIntentLabel, GoalRelationLabel, GoalTextKind, ActivityIntent | Module `orientation context` trong package `cortex`. |
| `cortex/orientation_semantics.py` | 798 | HybridOrientationConfig, LexicalVetoReport, HybridOrientationDebug, HybridOrientationInterpreter | Module `orientation semantics` trong package `cortex`. |
| `cortex/personality.py` | 911 | PersonalityLens | Module `personality` trong package `cortex`. |
| `cortex/relational_feedback.py` | 345 | RelationalFeedbackSignal, RelationalFeedbackAnalyzer | relational_feedback.py ====================== Tầng này đọc feedback về *cách ERIS hiện diện* trong hội thoại: - lạnh quá... |
| `cortex/relationship_dynamics.py` | 1127 | RelationshipDynamicsState, RelationshipTurnEvent, RelationshipDynamicsReport, RelationshipDynamicsEngine | relationship_dynamics.py ======================== Module này quản lý state quan hệ dài hạn giữa ERIS và user. Bản này đã... |
| `cortex/relationship_event_builder.py` | 862 | RelationshipEvidence, RelationshipEventScores, RecentTurn, RelationshipEventBuildContext | relationship_event_builder.py ============================= Tầng này chuyển một lượt hội thoại thành các score quan hệ c... |
| `cortex/se.py` | 1528 | _ContextCandidate, _ContextClassification, SeLens | Module `se` trong package `cortex`. |
| `cortex/self_model.py` | 474 | SelfModelEngine | Module `self model` trong package `cortex`. |
| `cortex/self_observation.py` | 811 | SelfObservationReport, SelfObservationEngine | Module `self observation` trong package `cortex`. |
| `cortex/semantic_encoder.py` | 549 | SemanticVector, EncoderHealth, EmbeddingProvider, BaseSemanticEncoder | Module `semantic encoder` trong package `cortex`. |
| `cortex/semantic_hypothesis.py` | 423 | PrototypeCentroid, SemanticHypothesis, SemanticHypothesisReport, HypothesisConfig | Module `semantic hypothesis` trong package `cortex`. |
| `cortex/semantic_prototypes.py` | 547 | PrototypePhrase, PrototypeSet, PrototypeBank | Module `semantic prototypes` trong package `cortex`. |
| `cortex/session_ritual.py` | 443 | SessionRitualEngine | Module `session ritual` trong package `cortex`. |
| `cortex/social_presence.py` | 588 | PresenceFeatureVector, PresenceMemory, SocialPresenceDetector | Module `social presence` trong package `cortex`. |
| `cortex/speech_core.py` | 1889 | SpeechCoreEngine | Chuyển pressure thành quyền nói public. Đọc snapshot, internal_state, appraisal, Ti, meaning, thought_surface, self_state, personality, spontaneous impulse. Debug khi có tension... |
| `cortex/spontaneous_life.py` | 390 | SpontaneousLifeConfig, SpontaneousLifeTrace, SpontaneousLifeEngine | Endogenous + situated speech pressure for ERIS. Mô-đun này không viết câu công cộng. Nó tạo một SpeechImpulse bằng cách... |
| `cortex/surface_arbiter.py` | 1687 | SurfaceImpulse, SurfaceDecision, SurfaceGateEvaluation, SurfaceArbiter | Single source of truth cho low-level surface utterances. Thu impulse từ presence, speech_core, thought_stream, private_mind/private_life, long_silence, extra impulses; normalize... |
| `cortex/surface_seed_compiler.py` | 872 | CompiledSurfaceSeed, _SeedCandidate, SurfaceSeedCompiler | Gom áp lực rải rác thành seed public-safe đủ cụ thể cho wording layer. Đọc frame/snapshot/presence/private_mind/thought_stream/internal state để sinh `CompiledSurfaceSeed`. Debu... |
| `cortex/thought_stream.py` | 2263 | FragmentStore, AssociationGraph, PredictionTracker, CognitiveTensionEngine | Substrate suy nghĩ nền: fragment store, association graph, prediction tracker, tension engine, unresolved loop, momentum, decay, reactivation, reheater, surface selector. Nó tạo... |
| `cortex/ti.py` | 965 | TiCandidateAssessment, TiGovernor | Module `ti` trong package `cortex`. |
| `cortex/tune_ni_focus.py` | 291 | DriftSample | Module `tune ni focus` trong package `cortex`. |
| `cortex/turn_semantics.py` | 541 | TurnSemanticsReport, TurnSemanticsEngine | Module `turn semantics` trong package `cortex`. |
| `cortex/user_context_stream.py` | 269 | RollingUserContext, UserContextStream | src/cortex/user_context_stream.py ================================= Tầng 1 - Sensory / User Context Stream. Trách nhiệm:... |
| `cortex/vision_semantic_compressor.py` | 712 | VisionCompressorConfig, VisionSemanticCompressor | VisionSemanticCompressor cho ERIS. Vai trò: - Nhận screenshot/crop + OCR hint + ObserverFrame. - Gọi Qwen vision qua Oll... |
| `cortex/working_memory.py` | 1930 | WorkingMemorySlot, SuppressedMemoryItem, WorkingMemoryFrame, WorkingMemoryCandidate | Store/facade/truy xuất hoặc lifecycle dữ liệu cho cortex. |

## cortex/meaning
Phase 2 meaning pipeline: WorkspaceFrame-only, WorldScene, WorldInterpreter, SocioculturalContext, MeaningHypothesis, PragmaticIntent, ToM, OverreadBrake, SurfaceMeaningPolicy.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/meaning/__init__.py` | 24 | - | cortex.meaning — Phase 2 meaning layer package. Tầng hiểu ý nghĩa (meaning) của Phase 2. Bọc (wrap) các module hiện hữu... |
| `cortex/meaning/ambiguity.py` | 197 | AmbiguityResult, AmbiguityModule | ambiguity.py — AmbiguityModule (định lượng mơ hồ). ``AmbiguityModule`` lượng hoá **độ mơ hồ** của một tập giả thuyết đã... |
| `cortex/meaning/config.py` | 92 | Phase2Config, StageLedger | config.py — ``Phase2Config`` (nguồn duy nhất của mọi threshold) và ``StageLedger``. Module này giữ phần "điều khiển" của... |
| `cortex/meaning/contracts.py` | 274 | RawWorldAccessError, InvalidWorkspaceFrameError, WorldSceneValidationError, ConfigurationError | contracts.py — Shared Phase 2 data models, ``clamp01`` helper và errors. Đây là **nguồn sự thật dùng chung** cho tầng me... |
| `cortex/meaning/debug_render.py` | 207 | Phase2Run, DebugRender | debug_render.py — ``DebugRender`` + ``Phase2Run`` (stage debug, R12). Sinh **bản ghi người-đọc-được** (human-readable) c... |
| `cortex/meaning/meaning_hypothesis.py` | 474 | MeaningHypothesisEngine | meaning_hypothesis.py — ``MeaningHypothesisEngine`` (stage 4 của Phase 2). ContextAnnotation set → MeaningHypothesis set... |
| `cortex/meaning/meaning_layer.py` | 692 | MeaningLayer | Module `meaning layer` trong package `cortex/meaning`. |
| `cortex/meaning/overread_brake.py` | 357 | OverreadBrake | overread_brake.py — ``OverreadBrake`` (phanh phán bậy, stage 8 của Phase 2). Conclusion set → EvaluatedConclusion set. `... |
| `cortex/meaning/pipeline.py` | 318 | Phase2MeaningPipeline | Facade Phase2MeaningPipeline. Bắt buộc WorkspaceFrame-only và ToM-after-Meaning: WorldScene -> Interpreter -> Sociocultural -> MeaningHypothesis -> PragmaticIntent -> TheoryOfMi... |
| `cortex/meaning/pragmatic_intent.py` | 313 | PragmaticIntentEngine | pragmatic_intent.py — ``PragmaticIntentEngine`` (stage 5 của Phase 2). MeaningHypothesis set → PragmaticIntent set. Engi... |
| `cortex/meaning/read_contract.py` | 231 | FrameReadView | read_contract.py — ReadContract guard (WorkspaceFrame-only enforcement). Cơ chế cưỡng chế xương sống #1 của Phase 2 (R1)... |
| `cortex/meaning/sociocultural_context.py` | 263 | SocioculturalContext | sociocultural_context.py — Stage 3: Observation set -> ContextAnnotation set. ``SocioculturalContext`` gắn ngữ cảnh xã h... |
| `cortex/meaning/surface_meaning_policy.py` | 275 | SurfaceMeaningPolicy | surface_meaning_policy.py — ``SurfaceMeaningPolicy`` (phân vùng surfaced / withheld, stage 9). EvaluatedConclusion set (... |
| `cortex/meaning/taxonomy.py` | 124 | Taxonomy | taxonomy.py — registry meaning/intent/mental-state categories + startup validation. Registry **nguồn sự thật** cho ba họ... |
| `cortex/meaning/world_interpreter.py` | 187 | WorldInterpreter | world_interpreter.py — WorldScene -> Observation set (Phase 2, stage 2). ``WorldInterpreter`` là stage thứ hai của pipel... |
| `cortex/meaning/world_scene_builder.py` | 395 | WorldSceneBuilder | world_scene_builder.py — WorkspaceFrame -> WorldScene (Phase 2, stage 1). ``WorldSceneBuilder`` là stage đầu tiên của pi... |

## cortex/tom
Theory of Mind phase 2: suy trạng thái tâm trí từ meaning + pragmatic intent, có ranker và counterfactual corrector để hạ overread.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/tom/__init__.py` | 44 | - | cortex.tom — Phase 2 Theory of Mind package. Tầng lý thuyết tâm trí (Theory of Mind) của Phase 2. Cưỡng chế ràng buộc To... |
| `cortex/tom/contracts.py` | 68 | ToMOrderingViolation, MentalStateInference, ToMHistory | contracts.py — MentalStateInference, ToM dataclasses, lỗi contract ToM. Các kiểu dữ liệu riêng của tầng Theory of Mind (... |
| `cortex/tom/counterfactual_corrector.py` | 137 | Counterfactual, CounterfactualCorrector | counterfactual_corrector.py — CounterfactualCorrector (R7.4). Stage cuối của nhóm ToM hậu kỳ: nhận một ``MentalStateInfe... |
| `cortex/tom/mental_state_ranker.py` | 43 | MentalStateRanker | mental_state_ranker.py — MentalStateRanker. Xếp hạng các ``MentalStateInference`` theo độ hợp lý giảm dần (R7.3): - ``co... |
| `cortex/tom/theory_of_mind.py` | 361 | TheoryOfMindCore | TheoryOfMindCore suy MentalStateInference từ MeaningHypothesis + PragmaticIntent, có guard thứ tự và counterfactual correction. Debug khi ERIS đọc tâm lý quá tay. |
| `cortex/tom/tom_debug.py` | 80 | ToMDebug | tom_debug.py — ``ToMDebug`` (bản ghi debug Theory of Mind, R12.3). Sinh **bản ghi người-đọc-được** cho tập ``MentalState... |
| `cortex/tom/tom_history_adapter.py` | 119 | ToMHistoryAdapter | tom_history_adapter.py — ToMHistoryAdapter (history từ WorkspaceFrame only). Cấp dữ liệu *lịch sử tương tác* cho ``Theor... |

## cortex/private_mind
Private mind: evidence dossier, mini-evaluators, concern store, inner synthesizer, mutation bus, surface valve, user model, inner diary. Không sinh lời thoại public trực tiếp.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/private_mind/__init__.py` | 72 | - | Private mind package cho ERIS. Public API cố ý nhỏ: contract, concern store, dossier, evaluators, synthesizer, mutation... |
| `cortex/private_mind/comfort_appraiser.py` | 202 | ComfortAppraisal, ComfortAppraiser | cortex/private_mind/comfort_appraiser.py ======================================== Thẩm định xem một câu của user có THẬT... |
| `cortex/private_mind/concern_store.py` | 606 | ConcernStoreConfig, ConcernStore | Kho PrivateConcern. Merge fragment thành concern sống lâu, auto-resolve, decay, update từ judgment/outcome. Debug khi mỗi tick nghĩ xong rồi quên, không có đời sống bận tâm. |
| `cortex/private_mind/contracts.py` | 639 | RankedHypothesis, ThoughtFragment, PrivateConcern, StateMutation | Data contracts private mind: ThoughtFragment, PrivateConcern, InternalJudgment, StateMutation, SurfaceCandidate, EvidenceDossier, PrivateMindTickResult. Đây là ngôn ngữ chung củ... |
| `cortex/private_mind/epistemic.py` | 70 | - | cortex/private_mind/epistemic.py ================================ Bộ phân loại "epistemic self-awareness" thuần khiết (p... |
| `cortex/private_mind/evidence_dossier.py` | 444 | EvidenceDossierBuilder | cortex/private_mind/evidence_dossier.py ======================================= EvidenceDossierBuilder gom hồ sơ cho pri... |
| `cortex/private_mind/inner_diary_renderer.py` | 412 | InnerDiaryRenderer | cortex/private_mind/inner_diary_renderer.py Render a compact inner diary digest for UI display. Keep it short and never... |
| `cortex/private_mind/inner_diary_writer.py` | 211 | InnerDiaryWriter | cortex/private_mind/inner_diary_writer.py Biến dữ kiện nội tâm thô (judgment/concern/fragment/future/surface) thành nhật... |
| `cortex/private_mind/inner_synthesizer.py` | 330 | InnerSynthesizerModelAdapter, GemmaInnerSynthesizer | GemmaInnerSynthesizer gom ThoughtFragment thành InternalJudgment. Có fallback deterministic. Debug khi mini-evaluator có output nhưng không kết tinh thành phán quyết/mutation. |
| `cortex/private_mind/mini_evaluators.py` | 350 | MiniEvaluatorModelAdapter, BaseMiniEvaluator, IntentEvaluator, MemoryResonanceEvaluator | cortex/private_mind/mini_evaluators.py 4 mini-evaluator gọi API. Không có rule fallback — nếu API fail thì tick đó không... |
| `cortex/private_mind/state_mutation_bus.py` | 381 | MutationApplyReport, PrivateRuntimeBiasState, StateMutationBus | Cầu nối từ InternalJudgment sang state tương lai: internal_agenda, repair_memory, speech_bias, inquiry_plan... Debug khi private mind chỉ là decor, không ảnh hưởng reply sau. |
| `cortex/private_mind/surface_valve.py` | 372 | SurfaceValve | Van public-safe cho private mind. Chặn private markers, evidence yếu, usefulness thấp, interrupt cost cao, rồi convert SurfaceCandidate thành SurfaceImpulse. Debug khi nội tâm r... |
| `cortex/private_mind/thought_continuity.py` | 291 | ThoughtEntry, ThoughtContinuityStore | cortex/private_mind/thought_continuity.py ========================================= Dòng suy nghĩ liên tục của Eris, lưu... |
| `cortex/private_mind/user_model.py` | 455 | UserBelief, UserModelConfig, UserModelStore | cortex/private_mind/user_model.py ================================= Mô_Hình_Ngài — hình dung bền vững của ERIS về Người_... |

## cortex/private_life
Đời sống riêng không xoay quanh user: habitat, object attachment, private projects, daily rhythm, taste, solitude, rituals, errands, life events.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/private_life/__init__.py` | 51 | - | Private Life Layer public API. |
| `cortex/private_life/contracts.py` | 951 | HabitatObservation, HabitatModel, ObjectAttachment, ObjectResidue | cortex/private_life/contracts.py ================================ Hợp đồng dữ liệu cho Private Life Layer của ERIS. Tầng... |
| `cortex/private_life/core.py` | 880 | PrivateLifeCore | PrivateLifeCore: habitat, attachments, projects, anchors, daily rhythm, taste, solitude, rituals, errands, life events. Không sinh lời public, chỉ update đời sống riêng và seed ... |
| `cortex/private_life/persistence.py` | 78 | PrivateLifeStore | cortex/private_life/persistence.py ================================== Persistence JSON riêng cho PrivateLifeCore. Lý do... |

## cortex/subconscious
Subconscious/wandering substrate: ThoughtSpark, DriftPool, free association, blackboard, workers, synthesizer, topic seed memory. Đây là mỏ áp lực nền, không phải miệng public.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `cortex/subconscious/__init__.py` | 134 | - | Subconscious package Phase 0 → 7. Public API cố tình nhỏ: - ThoughtFragment / ThoughtObject: contract dữ liệu. - Subcons... |
| `cortex/subconscious/blackboard.py` | 271 | BlackboardSnapshot, SubconsciousBlackboard | Blackboard Phase 0 cho subconscious workers. Blackboard là nơi các worker nền bỏ ThoughtFragment vào. Nó không chọn câu... |
| `cortex/subconscious/drift_pool.py` | 232 | DriftEntry, DriftSnapshot, DriftPool | Hồ giữ ThoughtSpark yếu. Spark decay/cộng hưởng/nhóm theme rồi thỉnh thoảng kết tinh thành association. Không có API surface public. |
| `cortex/subconscious/free_association.py` | 144 | FreeAssociationEngine | FreeAssociationEngine cho wandering sparks. Nó nối spark bằng semantic/mood/module/metaphor/weak link. Không suy luận fa... |
| `cortex/subconscious/habitat_seed_extractor.py` | 153 | HabitatSeedExtractor | Habitat seed extractor: lấy seed từ môi trường runtime/repo của ERIS. |
| `cortex/subconscious/model_synthesizer.py` | 413 | ModelSynthesisPolicy, InnerCourtReport, ModelBackedConsciousSynthesizer | Model-backed Lane 3 synthesizer. Đây là lớp làm phần "phiên toà nội tâm": các ThoughtFragment vẫn do worker rẻ đưa lên B... |
| `cortex/subconscious/self_anchor_core.py` | 93 | SelfAnchor, SelfAnchorCore | Self-anchor seed source cho wandering layer. |
| `cortex/subconscious/synthesizer.py` | 362 | SynthesisPolicy, SynthesisReport, ConsciousSynthesizer | Conscious Synthesizer Phase 0. Synthesizer là cổ chai ý thức nhỏ: nhận nhiều ThoughtFragment từ Blackboard, gom cụm, chọ... |
| `cortex/subconscious/thought_fragment.py` | 602 | ThoughtFragmentValidationError, ThoughtFragment, ThoughtObject | Contracts Phase 0 cho tầng subconscious của ERIS. Phase 0 không tạo thêm một cái prompt để ERIS "giả vờ đang nghĩ". File... |
| `cortex/subconscious/thought_spark.py` | 244 | ThoughtSpark | ThoughtSpark contract cho tầng wandering/subconscious. ThoughtSpark là mẩu ý nghĩ cực sớm: còn mơ hồ, chưa claim fact, c... |
| `cortex/subconscious/topic_seed_pool.py` | 201 | TopicSeedPool | TopicSeedPool gom seed từ self-anchor/habitat/memory/mood/random weak link. |
| `cortex/subconscious/wandering_contracts.py` | 184 | TopicSeed, AssociationPath, WanderingTopic, WanderingThoughtResult | Contracts cho tầng wandering thought. File này chỉ gom shape dữ liệu. Logic nằm ở DriftPool/FreeAssociation/WanderingEng... |
| `cortex/subconscious/wandering_thought.py` | 252 | WanderingThoughtEngine | WanderingThoughtEngine: spark -> drift -> association -> fragment. Engine này chạy nhẹ theo tick. Nó không gọi SurfaceAr... |
| `cortex/subconscious/wandering_topic_memory.py` | 209 | WanderingTopicMemory | Continuity memory cho wandering topics. |
| `cortex/subconscious/worker_base.py` | 71 | WorkerContext, SubconsciousWorker, RuleBasedWorker | Base contract cho các subconscious worker Phase sau. Phase 0 chưa triển khai 15 worker. File này chỉ cung cấp lớp nền để... |

## memory
Trí nhớ phân tầng: event ledger, active state, episodic/semantic/relational/procedural/repair/affective residue, retrieval, scoring, activation, query IR, commit/retention/consolidation/pruning.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `memory/__init__.py` | 31 | - | Public memory API for ERIS. Use `MemoryKernel` from the package root for new integration. Legacy core/query/commit types... |
| `memory/active_state_snapshot.py` | 172 | ActiveStateSnapshot, ActiveStateStore | Active State Snapshot cho ERIS. Snapshot giữ trạng thái hiện tại có thể overwrite: goal đang theo, session arc, affect/h... |
| `memory/affective_residue_memory.py` | 213 | AffectiveResidueItem, AffectiveResidueMemoryStore | Affective Residue Memory: dư âm cảm xúc dưới dạng pressure. Không lưu "ERIS buồn" như fact công khai. Lưu pressure: tens... |
| `memory/claim_consolidator.py` | 73 | ClaimMergeDecision, ClaimConsolidator | Module `claim consolidator` trong package `memory`. |
| `memory/claim_entailment.py` | 130 | ClaimEntailmentDecision, ClaimEntailmentEngine | Module `claim entailment` trong package `memory`. |
| `memory/claim_extractor.py` | 69 | ClaimExtractor | Module `claim extractor` trong package `memory`. |
| `memory/embedding_index.py` | 337 | EmbeddingIndex | memory/embedding_index.py ========================= In-memory embedding index cho SemanticMemoryStore. Dùng transformers... |
| `memory/episodic_memory.py` | 628 | RecallScore, EpisodicMemoryItem, EpisodicMemoryStore | Episodic Memory: chuyện cụ thể đã xảy ra. Episodic không phải semantic fact. Nó giữ cảnh, lượt, outcome, evidence và độ... |
| `memory/event_ledger.py` | 220 | EventLedgerRecord, EventLedger | Append-only Event Ledger cho ERIS. Tầng này giữ raw truth: tín hiệu thô, evidence đã tạo ra, frame liên quan, và metadat... |
| `memory/memory_activation.py` | 162 | MemoryActivation, ScoredMemoryCandidate, MemoryRetrievalResult, MemoryActivationBuilder | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_ai_curator.py` | 512 | CuratorResult, MemoryAICurator | memory/memory_ai_curator.py =========================== AI curator cho memory — gọi Gemini để làm 2 việc rule không làm... |
| `memory/memory_candidate.py` | 184 | MemoryCandidate, CandidateBatch, MemoryLayerAdapter | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_cognition.py` | 618 | MemoryQuery, MemoryCommitDecision, CommitPolicy, MemoryCognitionCore | Facade memory legacy v2: commit qua StateCommitRequest, recall qua MemoryRetrievalEngine, route target vào event/active/episodic/semantic/relational/affective/procedural/repair/... |
| `memory/memory_commit_policy.py` | 1028 | MemoryCommitPolicy | Policy intake user turn. Trích fact/preference/convention, chặn commit câu hỏi như fact. Debug khi “tôi tên X” không nhớ hoặc “tôi tên gì” bị ghi thành fact. |
| `memory/memory_consolidator.py` | 80 | ConsolidationResult, MemoryConsolidator | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_cue.py` | 332 | MemoryCue, MemoryCueBuilder | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_kernel.py` | 496 | MemoryKernelDebugSnapshot, MemoryKernel | Facade memory mới cho runtime: ingest, answer, build_packet, maintain, commit_many, recall/retrieve, debug_snapshot. Debug khi memory query deterministic không chạy. |
| `memory/memory_kernel_contracts.py` | 223 | MemoryKernelConfig, MemoryIngestResult, MemoryAnswerResult, MemoryMaintenanceReport | Contract/dataclass dùng chung trong memory. |
| `memory/memory_maintenance.py` | 248 | MemoryMaintenanceRunner | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_models.py` | 216 | MemoryTarget, SurfaceMode, DecayPolicy, MemoryCommitKind | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_packet_builder.py` | 179 | MemoryPacket, MemoryPacketBuilder | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_pruner.py` | 123 | PruneDecision, MemoryPruner | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_query_compiler.py` | 347 | CompileDebug, MemoryQueryCompileResult, MemoryQueryCompiler | Compile query từ slot/semantic/repair/LLM parser thành MemoryQueryIR. Debug khi câu hỏi trí nhớ mơ hồ rơi xuống general LLM. |
| `memory/memory_query_executor.py` | 367 | MemoryQueryExecutor | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_query_ir.py` | 369 | QueryIntent, RoleRef, ActRef, RelationRef | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_query_llm_parser.py` | 215 | MemoryQueryLLMClient, LLMParseDecision, MemoryQueryLLMParser | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_query_repair.py` | 277 | MemoryQueryRepairItem, RepairPriorResult, MemoryQueryRepairStore | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_query_semantics.py` | 352 | EmbeddingProvider, SemanticQueryHint, MemoryQuerySemanticHintEngine | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_query_slot_parser.py` | 671 | SlotSignal, SlotParseResult, MemoryQuerySlotParser | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_recall_policy.py` | 248 | RecallPolicyConfig, MemoryRecallSurfacePolicy | Policy module cho memory: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục. |
| `memory/memory_record.py` | 414 | MemoryRecord | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_retention_policy.py` | 134 | RetentionDecision, MemoryRetentionPolicy | Policy module cho memory: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục. |
| `memory/memory_retrieval_engine.py` | 93 | MemoryStores, MemoryRetrievalEngine | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_scoring.py` | 339 | LayerProfile, MemoryScore, MemoryScorer | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_turn_annotator.py` | 400 | TurnAnnotation, TurnAnnotator | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_turn_graph.py` | 435 | TurnRole, TurnSpeechAct, TurnEdgeType, FactMention | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/memory_worthiness.py` | 135 | WorthinessDecision, MemoryWorthinessPolicy | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |
| `memory/persistence.py` | 340 | MemoryPersistenceConfig, MemoryPersistenceError, JsonMemoryPersistence | Module `persistence` trong package `memory`. |
| `memory/predicate_ontology.py` | 394 | EntailmentType, PredicateSpec | Module `predicate ontology` trong package `memory`. |
| `memory/procedural_memory.py` | 201 | ProceduralMemoryItem, ProceduralMemoryStore | Procedural Memory: cách xử lý đã học. Đây là nơi lưu rule kiểu: khi user sửa hiểu lầm, trả lời trực tiếp trước; khi evid... |
| `memory/query_intent.py` | 213 | SemanticQueryIntent, QueryTargetFrame, QueryIntentParserProtocol, SemanticQueryIntentCompiler | Module `query intent` trong package `memory`. |
| `memory/relational_memory.py` | 202 | RelationalMemoryItem, RelationalMemoryStore | Relational Memory: nhịp quan hệ, rupture, repair, khoảng cách. Đây không phải nơi lưu "user is sad". Nó lưu pattern có b... |
| `memory/repair_memory.py` | 248 | RepairMemoryItem, RepairMemoryStore | Repair Memory: ghi lỗi, sửa sai, suppression rule tương lai. Nếu user nói "không phải", hệ thống không được chỉ xin lỗi... |
| `memory/schemas.py` | 490 | MemoryTarget, DecayPolicy, PrivacyLevel, MemoryStatus | Module `schemas` trong package `memory`. |
| `memory/semantic_answer_policy.py` | 115 | SemanticAnswer, SemanticAnswerPolicy | Policy module cho memory: quyết định ngưỡng/chế độ, không nên tự sở hữu truth toàn cục. |
| `memory/semantic_claim.py` | 291 | SemanticClaim, ExtractedClaim | Module `semantic claim` trong package `memory`. |
| `memory/semantic_memory.py` | 1846 | SemanticRecallCue, SemanticRecallHit, FactProfile, SemanticMemoryItem | Semantic Memory: bộ nhớ fact đã được chưng cất cho ERIS. File này cố tình KHÔNG làm event log. Semantic memory chỉ nên g... |
| `memory/semantic_text.py` | 197 | TextSemanticFrame | Module `semantic text` trong package `memory`. |
| `memory/text_normalize_vi.py` | 65 | - | Module `text normalize vi` trong package `memory`. |
| `memory/unresolved_memory.py` | 331 | UnresolvedMemoryCandidate, UnresolvedMemoryStore | Store/facade/truy xuất hoặc lifecycle dữ liệu cho memory. |

## memory/claims
Claim builder phụ cho tầng memory claim logic.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `memory/claims/__init__.py` | 15 | - | Tầng claim logic: build claim, ontology, entailment. |
| `memory/claims/claim_builder.py` | 308 | ClaimBuilder | Module `claim builder` trong package `memory/claims`. |

## memory/judgement
Phụ trợ phán xét memory/consolidation.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `memory/judgement/__init__.py` | 17 | - | Tầng phán xét memory: worthiness, retention, consolidation. |
| `memory/judgement/consolidation.py` | 61 | ConsolidationDecision | Module `consolidation` trong package `memory/judgement`. |

## memory/understanding
Tầng parse nghĩa trung gian cho memory intake: entity linking, polarity, temporal, semantic parser.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `memory/understanding/__init__.py` | 16 | - | Tầng đọc nghĩa trung gian cho memory intake. |
| `memory/understanding/entity_linker.py` | 114 | - | Module `entity linker` trong package `memory/understanding`. |
| `memory/understanding/meaning_frame.py` | 192 | EntityRef, MeaningFrame, MeaningParseResult | Module `meaning frame` trong package `memory/understanding`. |
| `memory/understanding/polarity_temporal.py` | 107 | SurfaceFeatures | Module `polarity temporal` trong package `memory/understanding`. |
| `memory/understanding/semantic_parser.py` | 597 | SemanticParser, ModelSemanticParser, StructuredFrameParser, FallbackSurfaceSemanticParser | Parser/normalizer cho memory/understanding. |

## parser_grounding
Parser biến raw LLM output thành `Decision`, repair JSON/prose, normalize motion/action/confidence, và chặn claim capability/perception không có evidence.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `parser_grounding/__init__.py` | 5 | - | Package init / export boundary. |
| `parser_grounding/decision.py` | 1853 | ParserGroundingMixin | Mixin parser raw LLM output -> Decision. Repair JSON candidate, coerce fields, sanitize motion/action, detect capability/perception violations, fallback non-JSON safely. Debug k... |
| `parser_grounding/service.py` | 267 | DecisionParser | Module `service` trong package `parser_grounding`. |

## actions
Router/executor action hệ thống. Chỉ route command đủ rõ, action nằm trong whitelist.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `actions/__init__.py` | 12 | - | Package init / export boundary. |
| `actions/contracts.py` | 27 | ActionExecutionResult | Contract/dataclass dùng chung trong actions. |
| `actions/executor.py` | 658 | ActionExecutor | Executor thực thi action/command cho actions. |
| `actions/router.py` | 552 | RouteCandidate, ActionRouter | High-confidence action router for ERIS. Router này chỉ nên bắt các lệnh hệ thống thật sự rõ ràng. Nếu câu user có vẻ là... |

## telemetry
Thu thập window/browser/system/screenshot/content metadata làm input cho Se và observer.

| File | LOC | Class chính | Vai trò ngắn |
|---|---:|---|---|
| `telemetry/__init__.py` | 12 | - | Package init / export boundary. |
| `telemetry/content_metadata.py` | 609 | ContentMetadata, ContentMetadataCollector | Thu thập metadata nội dung đang nhìn thấy cho SeLens. Mục tiêu của file này không phải "đọc màn hình như tiên tri". Nó c... |
| `telemetry/service.py` | 62 | TelemetryService | Module `service` trong package `telemetry`. |
| `telemetry/system.py` | 235 | TelemetryMixin | Module `system` trong package `telemetry`. |

# 10. Appendix: inventory AST đầy đủ từng file

Quy ước: phần này được sinh tự động từ AST. Nó không mô tả nghiệp vụ sâu như các phần trên, nhưng rất hữu dụng để grep nhanh class/method/hàm. Method private vẫn được liệt kê vì debug mà giấu private helper thì khác gì đưa bản đồ kho báu bị tẩy tọa độ.

## `actions/__init__.py`
- LOC: 12

## `actions/contracts.py`
- LOC: 27
- Classes:
  - `ActionExecutionResult` (decorator=dataclass(slots=True))

## `actions/executor.py`
- LOC: 658
- Classes:
  - `ActionExecutor`
    - `__init__(self, logger)`
    - `execute(self, action_name, action_input)`
    - `_get_now_playing(self, action_input)`
    - `_focus_window(self, action_input)`
    - `_open_url(self, action_input)`
    - `_set_volume(self, action_input)`
    - `_search_web(self, action_input)`
    - `_get_weather(self, action_input)`
    - `_play_pause_media(self, action_input)`
    - `_copy_text(self, action_input)`
    - `_launch_app(self, action_input)`
    - `_normalize_url(self, raw)`
    - `_press_virtual_key(self, virtual_key, pause)`
    - `_set_clipboard_text(self, text)`
    - `_log(self, level, message)`

## `actions/router.py`
- LOC: 552
- Docstring: High-confidence action router for ERIS. Router này chỉ nên bắt các lệnh hệ thống thật sự rõ ràng. Nếu câu user có vẻ là câu hỏi, meta-discussion, code/debug, hoặc chỉ nhắc đến một từ khóa như "youtube/search/volume/copy" thì trả None để chat/LLM xử lý. Nguyên...
- Classes:
  - `RouteCandidate` (decorator=dataclass(frozen=True)) — Ứng viên route nội bộ. confidence không dùng để làm màu. Nó là cổng cuối: chỉ action đủ chắc mới được trả ra ngoài. Các blocker có thể hạ co...
    - `allowed(self)`
  - `ActionRouter` — Route chat text thành direct system action. Public API giữ nguyên bản cũ: route_chat(user_text, last_action="") -> tuple[action, value] | No...
    - `route_chat(self, user_text)`
    - `_route_open_url(self, raw, norm)`
    - `_route_now_playing(self, raw, norm)`
    - `_route_now_playing_follow_up(self, raw, norm)`
    - `_route_play_pause_media(self, raw, norm)`
    - `_route_volume(self, raw, norm)`
    - `_route_copy_text(self, raw, norm)`
    - `_route_focus_window(self, raw, norm)`
    - `_route_launch_app(self, raw, norm)`
    - `_route_search_web(self, raw, norm)`
    - `_route_weather(self, raw, norm)`
    - `_looks_like_now_playing(self, lowered)`
    - `_looks_like_now_playing_follow_up(self, lowered)`
    - `_normalize_vi(text)` — Lowercase + bỏ dấu tiếng Việt để rule ít phải nhân đôi. Giữ lại ký tự URL cơ bản. Normalize whitespa...
    - `_pad(cls, text)`
    - `_starts_with_negation(cls, norm)`
    - `_looks_like_meta_question(cls, norm)`
    - `_contains_any(norm, needles)` — True nếu norm chứa bất kỳ cụm nào. Dùng cho intent dạng facet.
    - `_now_playing_is_meta(cls, norm)` — Chỉ chặn now-playing khi câu rõ ràng là hỏi code/lập trình. Khác với _looks_like_meta_question chung...
    - `_looks_like_correction(cls, norm)`
    - `_copy_rest_is_meta(cls, rest_norm)`
    - `_weather_is_meta(cls, norm)`
    - `_target_is_meta_or_empty(cls, target)`
    - `_extract_single_quoted_payload(text)`
    - `_no_candidate(action)`
    - `_blocked(action, reason)`

## `app_logging.py`
- LOC: 29
- Functions:
  - `configure_logging(level)`
  - `get_logger(category)`
- Classes:
  - `CategoryFormatter` (base=logging.Formatter)
    - `format(self, record)`

## `core/__init__.py`
- LOC: 23

## `core/cognitive_frame.py`
- LOC: 1443
- Docstring: core/cognitive_frame.py Khung nhận thức trung tâm cho ERIS Cognitive Pipeline. File này là "xương sống runtime" của Phase 0: - Mọi dữ liệu đi vào runtime phải được đóng gói thành RawSignal. - Mọi claim dùng để suy luận phải đi qua EvidenceItem. - Mọi module ch...
- Functions:
  - `now_ts()` — Trả timestamp hiện tại. Tách ra thành hàm để test có thể monkeypatch nếu cần.
  - `new_frame_id(prefix)` — Sinh id cho frame. Dùng uuid ngắn để log dễ đọc hơn.
  - `_safe_get_attr(obj, name, default)` — Lấy attribute hoặc key dict một cách an toàn.
  - `_object_id(obj)` — Lấy id từ dataclass/dict/object. EvidenceItem, RawSignal, ModuleReport đều nên có field id/evidence id riêng. Nhưng tron...
  - `_to_plain(value)` — Chuyển object thành dạng JSON-friendly. Không dùng jsonpickle hay thư viện ngoài. Phase 0 nên nhẹ, sạch, không kéo depen...
  - `_shorten(text, max_len)` — Rút gọn text để debug không biến log thành tiểu thuyết.
  - `_clamp01(value)` — Ép số về [0.0, 1.0].
  - `_module_order_index(module_name)` — Trả index pipeline của module. Module chưa biết được đẩy xuống cuối.
  - `attach_report_to_frame(frame, report)` — Gắn report vào frame rồi trả lại frame. Dạng functional-ish để coordinator có thể viết: frame = attach_report_to_frame(f...
  - `close_frame_with_validation(frame)` — Validate rồi close frame. Trả issues để coordinator log hoặc test assert.
- Classes:
  - `FrameMutation` (decorator=dataclass(slots=True)) — Một lần thay đổi frame. CognitiveFrame không nên bị chỉnh âm thầm. Mỗi lần module ghi slot/report/warning/commit request, ta để lại một vết....
  - `FrameValidationIssue` (decorator=dataclass(slots=True)) — Một vấn đề phát hiện khi validate frame.
  - `FramePromptPacket` (decorator=dataclass(slots=True)) — Gói context an toàn để đưa vào prompt. Không bao giờ nhét nguyên CognitiveFrame vào prompt. PDF đã nói rõ: LLM chỉ nên nhận selected workspa...
    - `to_dict(self)`
  - `CognitiveFrame` (decorator=dataclass) — Khung nhận thức đầy đủ cho một chu kỳ runtime. Vai trò: - Chứa raw_signals và evidence. - Chứa slot kết quả của từng tầng pipeline. - Chứa M...
    - `start(cls, raw_signals)` — Tạo frame mới. Dùng method này thay vì gọi constructor trực tiếp để: - tự sinh frame_id - tự timesta...
    - `set_status(self, status)` — Đổi trạng thái frame và ghi audit.
    - `close(self)` — Đóng frame khi cycle hoàn tất.
    - `fail(self, reason)` — Đánh dấu frame lỗi nhưng vẫn giữ state để debug.
    - `add_raw_signal(self, signal)` — Thêm một RawSignal vào frame.
    - `add_raw_signals(self, signals)` — Thêm nhiều RawSignal.
    - `add_evidence(self, item)` — Thêm EvidenceItem vào frame. Đây là điểm chuyển từ "dữ liệu thô" sang "claim có confidence". Module...
    - `add_evidence_items(self, items)` — Thêm nhiều EvidenceItem.
    - `evidence_ids(self)` — Tập id evidence hiện có.
    - `raw_signal_ids(self)` — Tập id raw signal hiện có.
    - `get_evidence(self, evidence_id)` — Lấy evidence theo id.
    - `get_evidence_many(self, evidence_ids)` — Lấy nhiều evidence theo id, bỏ qua id không tồn tại.
    - `find_evidence(self, predicate)` — Tìm evidence theo predicate. Ví dụ: frame.find_evidence(lambda ev: ev.raw_or_inferred == "inferred")
    - `evidence_by_tag(self, tag)` — Lấy evidence có tag.
    - `strongest_evidence(self)` — Lấy evidence mạnh nhất theo confidence * reliability.
    - `set_slot(self, slot_name, value)` — Ghi kết quả vào một slot pipeline. Chỉ runtime/module wrapper nên gọi hàm này. Module thuần nên trả...
    - `append_slot_list(self, slot_name, value)` — Append vào slot dạng list. Hiện dùng chủ yếu cho `simulations`.
    - `get_slot(self, slot_name)` — Đọc slot theo tên.
    - `slot_is_ready(self, slot_name)` — Kiểm tra slot đã có dữ liệu chưa.
    - `add_report(self, report)` — Gắn ModuleReport vào frame. Nếu slot_name được truyền: - lấy report.result gắn vào slot tương ứng. -...
    - `get_report(self, module_name)` — Lấy report của module.
    - `require_report(self, module_name)` — Lấy report bắt buộc, thiếu thì raise. Dùng trong coordinator/test để bắt pipeline thiếu module.
    - `report_order(self)` — Danh sách module đã report theo thứ tự pipeline tương đối.
    - `add_commit_request(self, request)` — Thêm yêu cầu ghi state/memory. Module không được ghi thẳng vào memory. Module chỉ được đề xuất State...
    - `commit_requests_for(self, target)` — Lấy commit request theo target.
    - `add_debug_note(self, note)` — Thêm ghi chú debug.
    - `add_warning(self, warning)` — Thêm warning.
    - `_record_mutation(self)` — Ghi audit record cho thay đổi frame.
    - `validate(self)` — Kiểm tra tính nhất quán của frame. strict=False: chỉ cảnh báo lỗi thường gặp. strict=True: lỗi thiếu...
    - `raise_if_invalid(self)` — Raise ValueError nếu validate có error.
    - `build_prompt_packet(self)` — Tạo gói context an toàn để đưa vào LLM. Không đưa raw_signals toàn bộ vào prompt. Không đưa module_r...
    - `_evidence_to_prompt_dict(self, item)` — Rút EvidenceItem thành dict nhỏ cho prompt.
    - `_extract_memory_for_prompt(self, memory_packet)` — Rút memory packet cho prompt. Chỉ lấy các field thường dùng. Nếu MemoryPacket sau này có method riên...
    - `_extract_selected_goal(self)` — Lấy goal đang được chọn nếu có.
    - `_collect_prompt_constraints(self)` — Gom constraint ngắn cho prompt.
    - `debug_summary(self)` — Tạo summary nhỏ để log/debug.
    - `filled_slots(self)` — Danh sách slot pipeline đã có dữ liệu.
    - `_debug_dominant_focus(self)` — Lấy dominant focus từ salience/workspace nếu có.
    - `to_dict(self)` — Serialize frame thành dict JSON-friendly. Cảnh báo: đây là debug serialization, không phải prompt pa...
    - `to_json(self)` — Serialize frame thành JSON string.
    - `clone_shallow(self)` — Clone nông. Dùng cho test hoặc branch simulation nhẹ. Không nên dùng để chạy pipeline song song phức...
    - `clone_deep(self)` — Clone sâu. Dùng khi muốn thử predictive simulation hoặc rollback branch.
    - `is_fast(self)`
    - `is_normal(self)`
    - `is_deep(self)`
    - `is_reflection(self)`
    - `has_user_chat(self)` — Frame có phải chứa chat user không.
    - `has_body_context(self)` — Frame có signal/slot body hoặc spatial không.
    - `has_memory_context(self)` — Frame có signal/slot memory không.
  - `CognitiveFrameBuilder` (decorator=dataclass) — Builder nhỏ để tạo frame sạch hơn trong coordinator/test. Không bắt buộc dùng. Nhưng nó giúp coordinator bớt dài, một mục tiêu đáng kính tro...
    - `create(self)`

## `core/evidence.py`
- LOC: 838
- Functions:
  - `now_timestamp()` — Trả Unix timestamp hiện tại. Dùng float để thống nhất với pipeline runtime và dễ tính recency/duration.
  - `normalize_signal_source(source)` — Chuẩn hóa source về đúng tập source trong PDF. RawSignal chỉ chấp nhận 10 nguồn chuẩn: user_chat, active_window, browser...
  - `normalize_privacy_level(privacy_level)` — Chuẩn hóa privacy_level về public/normal/private/sensitive.
  - `clamp_reliability(value)` — Ép reliability vào [0.0, 1.0]. Hàm này dùng cho collector thực dụng. Dataclass vẫn validate nghiêm trong __post_init__....
  - `make_signal_id(source, timestamp)` — Tạo id đủ ổn định để trace trong EventLedger. Format có source + mili-giây + uuid ngắn: raw.user_chat.1760000000000.a1b2...
  - `raw_signal(source, content)` — Shortcut ngắn cho collector. Ví dụ: signal = raw_signal("user_chat", "sửa lỗi này")
- Classes:
  - `RawSignalValidationError` (base=ValueError) — Lỗi dữ liệu RawSignal. Tách exception riêng để collector/runtime có thể bắt chính xác lỗi contract, thay vì nuốt chung với ValueError rồi tự...
  - `RawSignal` (decorator=dataclass(slots=True, frozen=True)) — Tín hiệu thô trước khi thành evidence. Đây là hợp đồng nhỏ nhưng cực quan trọng: - `id`: khóa trace duy nhất cho EventLedger/debug. - `sourc...
    - `__post_init__(self)` — Validate và chuẩn hóa nhẹ sau khi khởi tạo.
    - `create(cls)` — Factory chính cho collector. Collector nên gọi hàm này thay vì tự dựng id/timestamp thủ công. Đời đã...
    - `from_chat(cls, text)` — Tạo signal từ câu chat của user.
    - `from_active_window(cls, window_title)` — Tạo signal từ cửa sổ/app đang active.
    - `from_browser(cls)` — Tạo signal từ browser title/url/tab. URL/tab có thể nhạy cảm. Collector nên tự nâng privacy_level lê...
    - `from_telemetry(cls, telemetry)` — Tạo signal từ telemetry hệ thống. Telemetry là dữ kiện nền: idle time, CPU/RAM, open windows, recent...
    - `from_vision(cls, facts)` — Tạo signal từ vision facts. Vision dễ sai và dễ dính dữ liệu riêng tư, nên default reliability thấp...
    - `from_ocr(cls, text)` — Tạo signal từ OCR text.
    - `from_body(cls, body_state)` — Tạo signal từ body state: vị trí, pose, motion, touch/grab, v.v.
    - `from_system_log(cls, message)` — Tạo signal từ system log/runtime log.
    - `from_memory(cls, memory_payload)` — Tạo signal từ memory recall. Memory là nguồn có ích nhưng không phải chân lý. Nó có decay, contradic...
    - `from_time(cls, time_payload)` — Tạo signal từ thời gian/session clock.
    - `from_dict(cls, data)` — Khôi phục RawSignal từ dict. Dùng cho EventLedger load lại JSONL hoặc test.
    - `with_reliability(self, reliability)` — Trả bản sao với reliability mới. Không mutate object cũ vì RawSignal nên cư xử như record append-onl...
    - `with_privacy(self, privacy_level)` — Trả bản sao với privacy_level mới.
    - `is_private(self)` — True nếu signal không nên surface công khai.
    - `is_sensitive(self)` — True nếu signal cần xử lý cực kỳ tiết chế.
    - `is_low_reliability(self)` — True nếu nguồn yếu, tầng sau nên hạ confidence inference.
    - `summarize_content(self)` — Tạo bản tóm tắt ngắn để debug mà không dump content quá dài. Không dùng hàm này để thay thế content...
    - `to_dict(self)` — Chuyển RawSignal thành dict để ghi ledger hoặc truyền module.
    - `to_safe_debug_dict(self)` — Dict debug an toàn hơn: không dump nguyên content private/sensitive.
    - `to_json(self)` — Serialize RawSignal sang JSON UTF-8 friendly.
  - `EvidenceItem` (decorator=dataclass(slots=True, frozen=True)) — Claim đã chuẩn hóa từ RawSignal để các tầng sau suy luận có grounding. RawSignal ghi nhận dữ liệu thô. EvidenceItem là câu claim nhỏ, có sou...
    - `__post_init__(self)`
    - `from_raw_signal(cls, signal)`
    - `is_private(self)`
    - `to_dict(self)`
  - `ModuleReport` (decorator=dataclass(slots=True)) — Kết quả chuẩn mà một module ghi lại vào CognitiveFrame.
    - `__post_init__(self)`
    - `to_dict(self)`
  - `StateCommitRequest` (decorator=dataclass(slots=True)) — Yêu cầu ghi state/memory sau khi frame đã được guard. Contract này phải đủ rộng cho commit protocol hiện tại: permission, decay, source_modu...
    - `__post_init__(self)`
    - `to_dict(self)`
  - `DebugTrace` (decorator=dataclass(slots=True)) — Trace nhẹ cho audit/debug của một frame.
    - `add(self)`
    - `to_dict(self)`

## `core/evidence_normalizer.py`
- LOC: 209
- Docstring: core/evidence_normalizer.py Lớp trung gian bắt buộc của Phase 0/1: RawSignal -> EvidenceItem -> (CognitiveFrame.evidence) Vì sao cần file này: V3 cấm module đọc raw input lung tung. Mọi claim dùng để suy luận phải đi qua EvidenceItem (có confidence, source, re...
- Functions:
  - `normalize_signals(signals)` — Shortcut hàm thuần cho test/call nhanh.
- Classes:
  - `EvidenceNormalizerConfig` (decorator=dataclass(slots=True)) — Cấu hình cho normalizer. Giữ trong dataclass để sau này load từ JSON nếu cần, thay vì rải magic number.
  - `NormalizationResult` (decorator=dataclass(slots=True)) — Kết quả normalize, kèm vài con số để debug_trace soi.
    - `count(self)`
    - `to_dict(self)`
  - `EvidenceNormalizer` — Chuyển RawSignal thành EvidenceItem theo contract V3. Dùng: normalizer = EvidenceNormalizer() result = normalizer.normalize_into_frame(frame...
    - `__init__(self, config)`
    - `normalize(self, signals)` — Chuyển một loạt RawSignal thành EvidenceItem raw.
    - `normalize_into_frame(self, frame)` — Đọc frame.raw_signals, sinh evidence, và add vào frame. Frame phải có `raw_signals` và `add_evidence...
    - `_to_evidence(self, signal)`
    - `_initial_confidence(self, signal)`
    - `_tags_for(self, source)`

## `cortex/__init__.py`
- LOC: 164

## `cortex/action_memory.py`
- LOC: 439
- Docstring: Action memory and rhythm state for ERIS. File này không quyết định câu chữ. Nó chỉ giữ lịch sử hành vi để planner không cư xử như cá vàng bị reset não sau mỗi frame. Mục tiêu: - nhớ action gần đây để chống lặp discrete - tích social_fatigue / boredom / exposur...
- Functions:
  - `build_action_family()` — Suy family ngắn để memory/repetition dùng. Ưu tiên intent vì intent thường gần semantic hơn speech_act.
  - `_float(value, default)`
  - `_clamp01(value)`
- Classes:
  - `ActionTrace` (decorator=dataclass(slots=True)) — Một dấu vết hành vi đã xảy ra. action: speech_act đã chọn. family: semantic family hoặc intent family. Nếu chưa có thì để rỗng. channel: aut...
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `ActionMemoryState` (decorator=dataclass(slots=True)) — State dài hơi cho action planner. Đây là phần Ngài cần persist nếu muốn ERIS có lịch sử hành vi thật. Nếu không persist, planner vẫn chạy, n...
    - `recent_actions(self, limit)` — Trả action gần đây nhất, mới nhất ở cuối tuple.
    - `recent_families(self, limit)` — Trả semantic/action family gần đây, bỏ rỗng.
    - `seconds_since_action(self, now)`
    - `seconds_since_spoken(self, now)`
    - `action_count(self, action, window)` — Đếm action trong cửa sổ gần. Dùng cho repetition penalty.
    - `family_count(self, family, window)`
    - `record(self)` — Ghi nhận action sau khi planner chốt. Hàm này nên được gọi ở coordinator sau khi đã có final decisio...
    - `decay(self)` — Decay áp lực theo thời gian. Gọi mỗi loop nếu muốn state mềm hơn. Không gọi cũng không chết, chỉ thô...
    - `absorb_context(self)` — Cập nhật áp lực nền từ context trước khi planner score. Hàm này đọc mềm bằng getattr để không phụ th...
    - `infer_rhythm_phase(self)` — Suy rhythm phase từ lịch sử và áp lực. Đây là nhịp mềm. Planner dùng nó như bias, không phải định mệ...
    - `_update_pressures_after_action(self)`
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `to_prompt_context(self)` — Context ngắn để nhét vào prompt nếu cần. Không mô tả như cảm xúc người thật. Chỉ là áp lực nhịp hành...

## `cortex/action_planner.py`
- LOC: 707
- Docstring: Utility-based ActionPlanner for ERIS. Bản này thay lõi rule-based cũ bằng 3 tầng: 1. action_memory.py -> nhớ hành vi gần đây, fatigue, boredom, recoil, rhythm 2. action_utility.py -> chấm điểm cạnh tranh cho từng action 3. action_planner.py -> orchestration, s...
- Classes:
  - `ActionPlanner` — Chọn runtime action trước bước wording của LLM.
    - `__init__(self)`
    - `_has_safety_sensitive_pressure(self)`
    - `plan(self)`
    - `commit_action(self)` — Helper để coordinator ghi action vào memory sau final decision. Nếu Ngài nối persistent state, gọi h...
    - `_extract_impulse_arbitration(self, speech_core)` — Lấy ArbitrationReport từ SpeechCore nếu có. Không bắt ActionPlanner biết chi tiết SpontaneousLifeEng...
    - `_extract_body_bias_hint(self, speech_core)`
    - `_speech_intent_for_action(self, speech_act)`
    - `_risk_flags(self)`
    - `_reason_to_speak(self)`
    - `_voice_directive_for_speech_act(self, speech_act)`
    - `_animation_hint(self)`
    - `_append_self_state_notes(self, notes, self_state)`
    - `_append_utility_notes(self, notes, utility_report)`
    - `_style_anchor(self)`
    - `_style_attitude(self)`
    - `_style_limit(self)`
    - `_broadcast_anchor_text(self, broadcast)`
    - `_compact(self, value)`
    - `_broadcast_has_signal(self, broadcast)`
    - `_appraisal_value(self, appraisal, name)`
    - `_float(self, value)`

## `cortex/action_utility.py`
- LOC: 1053
- Docstring: Utility competition for ERIS actions. File này thay lõi "if intent == X -> return Y" bằng cạnh tranh utility. Không phải ML. Không giả vờ thông minh. Chỉ là scoring minh bạch, có memory, có risk penalty, có rhythm, có pressure thật. Ít nhất nó không ngu theo c...
- Functions:
  - `_clean(value)`
  - `_num(value, default)`
  - `_normalize_text(text)`
- Classes:
  - `ActionContext` (decorator=dataclass(slots=True)) — Context đã normalize cho scorer. Planner build object này từ coordinator inputs. Dùng dataclass để debug rõ, thay vì truyền 20 tham số vào t...
    - `explicit_user_pull(self)`
    - `has_concrete_signal(self)`
    - `family(self)`
  - `ActionScore` (decorator=dataclass(slots=True)) — Chi tiết điểm của một action. total = base + bias + pressure + rhythm - risk - repetition - fatigue. reasons để debug. Đừng xóa. Không có re...
    - `add(self, amount, reason, bucket)`
    - `to_dict(self)`
  - `ActionUtilityReport` (decorator=dataclass(slots=True))
    - `utility_scores(self)`
    - `top_reasons(self, limit)`
    - `to_debug_notes(self)`
  - `ActionUtilityScorer` — Chấm điểm cạnh tranh cho ACTION_SPACE. Hard override chỉ dành cho case thật sự không nên tranh luận: - system_action: user yêu cầu tool/acti...
    - `score(self, ctx)`
    - `_hard_override(self, ctx)`
    - `_candidate_actions(self, ctx)` — Chọn tập candidate nhỏ để score rõ, không phải action nào cũng lôi vào.
    - `_with_proposed(self, base, ctx)`
    - `_intent_to_action(self, intent)`
    - `_apply_base(self, score, ctx)`
    - `_apply_intent_bias(self, score, ctx)`
    - `_apply_channel_pressure(self, score, ctx)`
    - `_apply_appraisal_pressure(self, score, ctx)`
    - `_apply_conversation_pressure(self, score, ctx)`
    - `_apply_relationship_pressure(self, score, ctx)`
    - `_apply_goal_persistence_pressure(self, score, ctx)`
    - `_apply_memory_pressure(self, score, ctx)`
    - `_apply_impulse_arbitration_pressure(self, score, ctx)` — Bias action utility bằng full ArbitrationReport. Đây là bước "nối sâu": ActionUtility không chỉ nghe...
    - `_impulse_report(self, ctx)`
    - `_body_bias_hint(self, ctx)`
    - `_selected_impulse_name(self, ctx)`
    - `_selected_impulse_total(self, ctx)`
    - `_selected_impulse_has_evidence(self, ctx)`
    - `_candidate_impulse_total(self, ctx, name)`
    - `_impulse_score_notes(self, ctx)`
    - `_impulse_pressure_notes(self, ctx)`
    - `_impulse_to_action(self, name)`
    - `_apply_rhythm(self, score, ctx)`
    - `_apply_risk_penalty(self, score, ctx)`
    - `_apply_repetition_penalty(self, score, ctx)`
    - `_apply_fatigue_penalty(self, score, ctx)`
    - `_memory(self, ctx)`
    - `_memory_pressure_notes(self, ctx)`
    - `_goal_pressure_notes(self, ctx)`
    - `_goal_can_intervene(self, ctx)`
    - `_transition_reason(self, selected, ctx)`
    - `_meaning_shift(self, ctx)`
    - `_has_note(self, ctx, marker)`
    - `_has_internal_impulse(self, ctx)`
    - `_vital_pressure(self, ctx)`
    - `_looks_like_question(self, text)`
    - `_is_vague_question(self, text)`
    - `_looks_like_technical_request(self, text)`
    - `_tie_break_priority(self, action)`

## `cortex/affect_semantics.py`
- LOC: 860
- Docstring: affect_semantics.py =================== Module này dùng để phân tích "áp lực nghĩa" trong câu chat của user. Mục tiêu: - Không route intent bằng keyword thô kiểu: nếu thấy "buồn" thì attachment_dialogue. - Thay vào đó, module trả về nhiều score mềm: technicali...
- Functions:
  - `clamp01(value)` — Ép một số về khoảng [0.0, 1.0]. Lý do tách helper: - Tất cả score trong module này là xác suất/áp lực mềm. - Nếu không c...
  - `blend(previous, current, strength)` — Blend hai score theo trọng số. `strength` càng cao thì previous càng ảnh hưởng nhiều. Hàm này tiện nếu sau này Ngài muốn...
  - `normalize_text(text)` — Chuẩn hóa text để matching bớt ngu. Làm các bước: - lower-case - bỏ dấu tiếng Việt bằng NFD - gom whitespace - giữ lại b...
  - `compact_evidence(items, limit)` — Loại evidence rỗng/trùng và giới hạn độ dài. Evidence chỉ để debug và prompt context. Đừng nhồi quá nhiều, nếu không pro...
  - `_count_question_marks(text)`
  - `_word_count(text)`
- Classes:
  - `AffectSemanticSignal` (decorator=dataclass(slots=True)) — Score đa trục mô tả áp lực nghĩa/cảm xúc trong câu user. Các field chính: - technicality: Câu có tính kỹ thuật/code/kiến trúc/debug không. -...
    - `empty(cls)` — Signal rỗng, dùng khi chưa có classifier nhưng muốn giữ API.
    - `clamp(self)` — Trả bản đã clamp toàn bộ score về [0, 1].
    - `dominant_axes(self, threshold)` — Trả các trục nổi bật để debug/log. threshold mặc định 0.42 vì affect thường không nên cần quá cao mớ...
    - `to_dict(self)` — Serialize để nhét vào debug trace hoặc memory.
    - `from_dict(cls, data)` — Deserialize an toàn từ dict. Dùng khi state/debug được load lại từ JSON.
    - `to_prompt_context(self)` — Render context ngắn cho prompt. Cố ý dùng số thay vì label như "sad/loving/angry". Label cứng dễ làm...
  - `WeightedPhrase` (decorator=dataclass(frozen=True, slots=True)) — Một phrase/pattern có trọng số. `pattern` luôn được so với text đã normalize không dấu. `weight` là mức cộng vào trục tương ứng.
  - `AffectSemanticClassifier` — Classifier nhẹ cho semantic-affect signal. Thiết kế cố ý: - Không trả một intent duy nhất. - Không coi keyword là chân lý. - Có bias từ cont...
    - `analyze(self, user_text)` — Phân tích một câu user thành AffectSemanticSignal. Parameters: user_text: Text user gửi trong turn h...
    - `is_correction_like(self, user_text)` — Shortcut cho coordinator: user có vẻ đang sửa hiểu lầm không.
    - `is_objectification_like(self, user_text)` — Shortcut: user đang kéo ERIS thành tool/waifu/prompt cosplay không.
    - `is_technical_request(self, user_text)` — Shortcut: user đang cần xử lý kỹ thuật/code/kiến trúc không.

## `cortex/agent_mind_persistence.py`
- LOC: 732
- Docstring: Persistent Agent Mind Layer cho ERIS. Module này giữ 3 lớp học dài hạn cho impulse system: 1. BeliefCore persistent - ERIS tin gì về user / bản thân / scene / task. - Mỗi belief có confidence, nguồn, decay, evidence count và contradiction. 2. PreferenceModel d...
- Functions:
  - `_clamp01(value, default)`
  - `_now()`
  - `_norm(value)`
  - `_clean(value)`
  - `_as_tuple(value)`
  - `_feedback_sentiment(normalized)`
  - `_feedback_topics(normalized)`
  - `_topic_to_context_tags(topics)`
  - `default_agent_mind_path()`
  - `agent_mind_path_for_memory_core(base_dir)`
  - `get_default_agent_mind_store()`
- Classes:
  - `PersistentBeliefRecord` (decorator=dataclass(slots=True)) — Một belief mềm, không phải hard truth. confidence càng cao thì impulse scoring càng tin. decay_rate giúp belief mòn dần nếu lâu không được r...
    - `decayed_confidence(self)`
    - `reinforce(self, amount)`
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `PersistentPreferenceRecord` (decorator=dataclass(slots=True)) — Preference dài hạn của ERIS. strength là trọng số hiện tại. stability càng cao thì feedback càng khó bẻ. Đây là chống hiện tượng một feedbac...
    - `adjust(self, delta)`
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `SemanticHabitRecord` (decorator=dataclass(slots=True)) — Habit học từ user feedback, lưu ở dạng semantic. Không lưu kiểu "user chửi câu A". Lưu thành pattern: context_tags + action_pattern + impuls...
    - `matches(self)`
    - `score_delta(self)`
    - `reinforce(self)`
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `PersistentAgentMindStore` — JSON store nhỏ cho Persistent Agent Mind Layer. Store này cố tình không dùng LLM. Nó chỉ đọc/ghi record có schema rõ. Nếu sau này muốn daydr...
    - `__init__(self, path)`
    - `load(self)`
    - `reload_if_changed(self)`
    - `save(self)`
    - `to_dict(self)`
    - `replace_from_dict(self, payload)`
    - `relevant_beliefs(self)`
    - `preference_strength(self, key, default)`
    - `habit_bias(self)`
    - `record_user_feedback(self, text)` — Rút feedback user thành belief/preference/habit adjustment. Trả về tuple marker để guard/debug ghi t...
    - `_seed_defaults(self)` — Upsert bản boot INFJ 5w4 cho AgentMind. Không chỉ seed khi file rỗng. File cũ có thể thiếu worldview...
    - `_detox_presence_habits(self)` — Hạ độc các habit từng reinforce micro-presence như status ping. Feedback cũ vẫn được giữ, nhưng nhữn...
    - `_adjust_preference(self, key, delta)`
    - `_upsert_belief(self, key, claim, domain, amount)`
    - `_upsert_habit(self, key, tags, action, impulse_name, adjustment, outcome, source_id)`

## `cortex/agent_state_stack.py`
- LOC: 742
- Docstring: Agent state stack for ERIS. Lớp này gom các lực nền đang bị rải rác trong runtime thành một contract nhỏ: Evidence -> Belief -> Preference -> Need -> Trait -> Habit -> Affordance. Nó cố tình không gọi LLM và không tự quyết định câu chữ. Mục tiêu là tạo một bản...
- Functions:
  - `_clamp01(value, default)`
  - `_text(value)`
  - `_norm(value)`
  - `_contains_any(text, terms)`
  - `_get(obj)`
  - `build_agent_state_stack()` — Dựng stack từ các object runtime hiện có mà không buộc schema mới. Hàm này mềm có chủ đích: nếu một nhánh runtime chưa c...
- Classes:
  - `EvidenceView` (decorator=dataclass(slots=True)) — Bản nhìn nhẹ của tình huống hiện tại. Đây không phải evidence ledger đầy đủ. Nó là lớp đọc nhanh cho arbitration: app nào đang nổi, title có...
    - `scene_text(self)`
    - `has_scene_anchor(self)`
    - `has_tag(self, tag)`
    - `from_runtime(cls)`
  - `Belief` (decorator=dataclass(slots=True))
    - `to_note(self)`
  - `BeliefSnapshot` (decorator=dataclass(slots=True))
    - `confidence(self, key, default)`
    - `notes(self, limit)`
    - `from_evidence(cls, evidence)`
  - `PreferenceProfile` (decorator=dataclass(slots=True)) — Sở thích riêng của ERIS, không phải preference của user.
    - `from_agent_mind(cls, agent_mind)` — Đọc PreferenceModel persistent và đổ vào profile runtime. Đây vẫn là preference riêng của ERIS. Feed...
    - `fit_for(self, impulse_name)`
  - `NeedVector` (decorator=dataclass(slots=True))
    - `from_runtime(cls)`
    - `notes(self)`
  - `TraitVector` (decorator=dataclass(slots=True))
    - `from_runtime(cls)`
    - `bias_for(self, impulse_name)`
  - `HabitSnapshot` (decorator=dataclass(slots=True))
    - `repetition_penalty(self)`
    - `semantic_bias(self)` — Bias học dài hạn từ HabitMemory semantic. Giá trị dương nâng impulse/action đã từng được user chấp n...
  - `AffordanceMap` (decorator=dataclass(slots=True))
    - `from_stack_parts(cls)`
  - `AgentStateStack` (decorator=dataclass(slots=True))
    - `debug_notes(self)`

## `cortex/appetite_system.py`
- LOC: 314
- Docstring: cortex/appetite_system.py ========================= Chợ đấu giá của các CƠN THÈM — xương sống cho autonomous speech "sống". Triết lý (lật ngược mô hình cũ): - Cũ: chờ một "cue" trên màn hình rồi hỏi "có nên nói không" → phản ứng, nên nhạt. - Mới: nội tâm là nh...
- Functions:
  - `_clamp01(value)`
  - `build_evidence_buffet()` — Gom fact sẵn có thành buffet. Không gọi model, không phân loại mới.
- Classes:
  - `EvidenceItem` (decorator=dataclass(slots=True)) — Một mẩu bằng chứng (thứ đang xảy ra) mà appetite có thể chén.
  - `AppetiteConfig` (decorator=dataclass(slots=True))
  - `AppetiteState` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `Reaction` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `AppetiteSystem` — Tích các cơn thèm, đấu giá với evidence, chọn ra một phản ứng.
    - `__init__(self, appetites)`
    - `new_states(self)`
    - `update(self, states)` — Cập nhật áp lực các cơn thèm và đấu giá ra một phản ứng (hoặc None).
    - `_best_evidence(cfg, evidence)`

## `cortex/appraisal.py`
- LOC: 499
- Classes:
  - `AppraisalEngine` — Builds ERIS' pre-verbal expressive/appraisal state from continuity state.
    - `evaluate(self)`
    - `render_prompt_context(self, appraisal)`
    - `_estimate_threat(self)`
    - `_estimate_certainty(self)`
    - `_estimate_agency(self)`
    - `_estimate_controllability(self)`
    - `_estimate_intimacy(self)`
    - `_estimate_protectiveness(self)`
    - `_estimate_jealousy_lite(self)`
    - `_estimate_fatigue(self)`
    - `_choose_stance(self)`
    - `_stance_guidance(self, appraisal)`
    - `_has_attachment_cue(self, normalized_text)`
    - `_normalize_text(self, text)`
    - `_clamp01(self, value)`
    - `_clamp(self, value)`

## `cortex/attention_salience.py`
- LOC: 1898
- Docstring: cortex/attention_salience.py ============================ Selection backbone / anti-context-flood backbone cho ERIS Cognitive Pipeline. Đây KHÔNG phải "attention hiện tại" kiểu gom vài keyword rồi chấm điểm cho vui. File này là tầng [03] Attention & Salience A...
- Functions:
  - `now_ts()` — Trả Unix timestamp hiện tại.
  - `clamp01(value, default)` — Ép một giá trị số vào [0, 1]. Tất cả score trong attention dùng cùng thang này để dễ debug. Nếu input bậy, trả default....
  - `safe_float(value, default)` — Chuyển value sang float an toàn.
  - `safe_get(obj, name, default)` — Lấy attribute hoặc key dict mà không gây tai nạn.
  - `normalize_text(text)` — Chuẩn hóa text cho scoring. Không bỏ dấu tiếng Việt vì dấu giúp phân biệt vài ngữ cảnh. Chỉ hạ chữ, gom whitespace, cắt...
  - `tokenize(text)` — Tách token đơn giản để tính overlap. Đây không phải semantic embedding. Nó chỉ đủ làm backbone nhẹ, không chặn việc sau...
  - `stable_fingerprint(text)` — Tạo fingerprint ổn định để nhận diện lặp. Không dùng hash() built-in vì Python randomizes hash giữa process.
  - `to_plain(value)` — Chuyển dataclass/object thành dạng JSON-friendly.
  - `join_reason(parts)` — Gom reason, bỏ phần rỗng.
  - `estimate_token_count(text)` — Ước lượng token rất thô bằng độ dài ký tự. Mục tiêu không phải đếm token chính xác, mà là chống context flood. Tokenizer...
  - `allocate_salience(frame)` — Hàm tiện dụng cho caller không muốn tự giữ engine. Nếu cần chống lặp giữa nhiều frame, nên giữ một instance AttentionSal...
- Classes:
  - `SalienceWeights` (decorator=dataclass(slots=True)) — Trọng số salience theo PDF. Công thức gốc trong PDF: novelty + urgency + goal_relevance + user_relevance + identity_relevance + relational_r...
  - `AttentionSalienceConfig` (decorator=dataclass(slots=True)) — Cấu hình của AttentionSalienceEngine. Các giới hạn ở đây dùng để chống context flood: - không đưa quá nhiều evidence vào prompt - không cho...
    - `normalized(self)` — Trả bản config đã clamp vài field nguy hiểm.
  - `SalienceFactorBreakdown` (decorator=dataclass(slots=True)) — Các trục điểm của một candidate. Đây là thứ giúp debug: vì sao evidence A được chọn còn evidence B bị chôn. Nếu không có breakdown, attentio...
    - `to_dict(self)`
  - `AttentionCandidate` (decorator=dataclass(slots=True)) — Một evidence đã được attention chuẩn hóa để tranh suất lên workspace.
    - `short_claim(self, max_len)`
    - `to_dict(self)`
  - `SuppressedSignal` (decorator=dataclass(slots=True)) — Evidence bị attention chặn hoặc không chọn.
    - `to_dict(self)`
  - `PromptEvidenceItem` (decorator=dataclass(slots=True)) — Evidence được phép đưa vào prompt/context packet. Không phải candidate nào được chọn cũng nên đưa nguyên văn vào prompt. Sensitive/private e...
    - `to_prompt_line(self)`
    - `to_dict(self)`
  - `ContextFloodReport` (decorator=dataclass(slots=True)) — Báo cáo chống ngập context.
    - `pressure(self)` — Áp lực context flood trên [0,1].
    - `to_dict(self)`
  - `SalienceFrame` (decorator=dataclass(slots=True)) — Kết quả Attention & Salience Allocation. Các field đầu bám PDF. Các field sau mở rộng để nối WorkingMemory/Workspace.
    - `has_focus(self)`
    - `workspace_ready(self)` — True nếu frame đủ tốt để WorkingMemory/Workspace xử lý tiếp.
    - `prompt_context(self)` — Render context ngắn cho prompt builder nếu cần. Prompt builder vẫn nên đọc `prompt_evidence`, không...
    - `to_dict(self)`
  - `AttentionSalienceMemory` (decorator=dataclass(slots=True)) — Bộ nhớ nhẹ của AttentionSalienceEngine. Đây không phải long-term memory. Đây chỉ là rolling memory để biết signal nào đang lặp. Không ghi fa...
    - `mark_seen(self, candidates)`
    - `repeat_count(self, fingerprint)`
    - `family_repeat_count(self, family)`
    - `to_dict(self)`
  - `SalienceClassifier` — Classifier nhẹ cho attention family và focus kind. Đây không phải MeaningHypothesis. Nó không được kết luận sâu. Nó chỉ gắn nhãn kỹ thuật để...
    - `classify_family(cls)`
    - `classify_focus_kind(cls)`
    - `is_generic_telemetry(cls)`
  - `AttentionSalienceEngine` — Attention & Salience Allocation Engine. Đọc evidence từ frame, trả SalienceFrame. Không đọc raw_signals trừ khi cần debug fallback. Không gọ...
    - `__init__(self, config, memory, classifier)`
    - `evaluate(self, frame)` — Chạy attention trên một frame hoặc danh sách evidence. Parameters ---------- frame: CognitiveFrame h...
    - `reset_memory(self)` — Xóa rolling memory của attention. Dùng khi reset session/test. Không đụng long-term memory.
    - `_build_candidates(self, evidence_items)`
    - `_candidate_from_evidence(self, item)`
    - `_normalize_source(self, source)`
    - `_score_candidate(self, candidate)`
    - `_weighted_score(self, b)`
    - `_novelty_score(self, candidate)`
    - `_urgency_score(self, candidate)`
    - `_goal_relevance_score(self, candidate)`
    - `_user_relevance_score(self, candidate)`
    - `_identity_relevance_score(self, candidate)`
    - `_relational_relevance_score(self, candidate)`
    - `_affective_charge_score(self, candidate)`
    - `_risk_relevance_score(self, candidate)`
    - `_unresolved_tension_score(self, candidate)`
    - `_recurrence_weight_score(self)`
    - `_habituation_score(self, candidate)`
    - `_false_alarm_likelihood_score(self, candidate)`
    - `_generic_penalty_score(self, candidate)`
    - `_apply_score_caps(self, candidate, score, breakdown)`
    - `_select_candidates(self, candidates)`
    - `_suppression_reason(self, candidate)`
    - `_to_suppressed(self, candidate, reason)`
    - `_build_prompt_evidence(self, selected)`
    - `_build_salience_frame(self)`
    - `_aggregate_breakdown(self, candidates)`
    - `_dominant_focus_text(self, candidate)`
    - `_context_flood_report(self)`
    - `_build_reason(self)`
    - `_top_factors(self, breakdown)`
    - `_write_to_frame(self, frame, salience)` — Gắn salience và ModuleReport vào frame nếu có thể.
    - `_build_module_report(self, salience)`
    - `_extract_goal_text(self, active_goal)`

## `cortex/background_observer.py`
- LOC: 660
- Docstring: BackgroundObserver cho ERIS. Bản này có 2 tầng: 1. Rule-based observer luôn chạy được, không phụ thuộc model. 2. Optional Ollama text observer để phân loại mềm hơn về sau. Luật cứng: - Không trả lời user. - Không commit memory. - Không tạo Decision public. - C...
- Classes:
  - `BackgroundObserverConfig` (decorator=dataclass)
  - `BackgroundObserver`
    - `__init__(self, config, sensory_adapter, ollama_client)`
    - `observe(self, snapshot, diff)` — Trả ObserverFrame. Nếu LLM bị lỗi, fallback rule-based. Runtime không nên chết vì con model gác cổng...
    - `_rule_observe(self, snapshot, diff)`
    - `_should_use_llm(self, diff)`
    - `_llm_observe(self, snapshot, diff)`
    - `_build_llm_prompt(self, snapshot, diff)`
    - `_frame_from_llm_data(self, data)`
    - `_merge_frames(self, rule, llm)` — Merge rule và LLM theo kiểu rule là xương sống an toàn.
    - `_apply_action_gates(self, frame, diff)` — Gắn các cờ cuối sau khi merge.
    - `_classify_focus(self, snapshot, text)`
    - `_classify_activity(self, snapshot, focus_kind, possible_error, fragmented, text)`
    - `_score_possible_error(self, text)`
    - `_score_fragmentation(self, snapshot, text)`
    - `_score_user_presence(self, snapshot)`
    - `_score_ambiguity(self, snapshot, focus_kind, activity_intent, diff)`
    - `_score_salience(self)`
    - `_any_pattern(text, patterns)`

## `cortex/banned_filler.py`
- LOC: 79
- Docstring: Single source of truth for stale filler lines the character must never speak. Both the LLM prompt construction (``llm/service.py``) and the autonomous output filter (``runtime/presence_controller.py``) import from here, so adding or removing a line is reflecte...
- Functions:
  - `normalize_banned(text)` — Normalize for membership comparison. Lowercases, NFC-normalizes, collapses internal whitespace, and trims leading and tr...
  - `is_banned_filler(text)` — True if ``text`` matches a banned line after normalization.
  - `quoted_fragment(lines)` — Render lines as a comma-separated quoted list for prompt text. Example: ``"'Tôi ở đây', 'Tôi đang nghe'"``. Trailing per...

## `cortex/chat_light.py`
- LOC: 298
- Functions:
  - `_normalize(text)`
  - `_has_any(text, markers)`
- Classes:
  - `ChatMeaningLayerLight` — Grounded semantic pressure for direct chat turns. This deliberately avoids autonomous telemetry interpretation. It reads the user's message...
    - `evaluate(self)`
    - `render_prompt_context(self, result)`
  - `ChatPersonalityPressureLight` — Small chat-only personality pressure that brakes overreading.
    - `evaluate(self)`
    - `render_prompt_context(self, result)`

## `cortex/connection_drive.py`
- LOC: 191
- Docstring: cortex/connection_drive.py ========================== Động lực nội sinh "sợ cô độc → tìm kết nối" cho ERIS. Vấn đề cũ: ERIS không có drive tự thân. Im lặng tích thành `silence_debt` ở wake governor nhưng KHÔNG đổ ngược vào thèm-nói, nên Eris ngồi câm như bot p...
- Functions:
  - `_clamp01(value)`
- Classes:
  - `ConnectionDriveConfig` (decorator=dataclass(slots=True))
  - `ConnectionDriveState` (decorator=dataclass(slots=True)) — State bền giữa các tick.
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `ConnectionDriveDecision` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `ConnectionDrive` — Tích cô độc theo thời gian, quyết định khi nào ép Eris với ra.
    - `__init__(self, config)`
    - `update(self, state)` — Cập nhật drive và trả quyết định outreach. - idle_seconds / silence_debt: độ im lặng tích lại (lonel...
    - `_decide(self, pressure)`

## `cortex/continuity_threat.py`
- LOC: 343
- Docstring: Continuity threat calculus for ERIS. Module này cố ý tách "im lâu" khỏi "đứt gãy hiện diện". Timer chỉ được dùng để hỏi: khoảng im này có bất thường so với ngữ cảnh không? Nó không được tự phong làm nỗi cô độc rồi bắt SurfaceArbiter đọc thơ.
- Functions:
  - `clamp01(value, default)`
  - `_signed(value, default)`
  - `_get(obj)`
  - `_norm(value)`
  - `sat(value)` — Soft saturation: tăng nhanh lúc đầu, rồi bão hòa. Dùng hàm này để idle_seconds không thể leo vô hạn thành bi kịch opera.
  - `expected_silence_for_context()` — Kỳ vọng im lặng theo ngữ cảnh. Đây là chốt chống timer mới: 5 phút trong deep work có thể bình thường, còn 90 giây sau m...
  - `evaluate_continuity_threat()` — Tính nỗi lo đứt gãy như prediction error, không như đồng hồ báo thức.
- Classes:
  - `ContinuityThreatFrame` (decorator=dataclass(slots=True))
    - `notes(self)`
    - `to_context(self)`

## `cortex/contracts.py`
- LOC: 1300
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
  - `SpeechImpulse` (decorator=dataclass(slots=True)) — Pre-wording speech impulse: pressure and residue, not wording. The first block is the MeaningLayer-compatible shape. The second block is the...
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
- LOC: 1051
- Functions:
  - `_clamp(value)`
  - `_clean_text(value)`
  - `normalize_vietnamese_ascii(text)`
  - `_recent_unique(current, incoming)`
  - `_token_set(text)`
  - `_jaccard_distance(left, right)`
  - `_contains_any(text, markers)`
  - `_contains_phrase(text, phrase)`
  - `_previous_assistant_asked_clarification(text)`
  - `_user_now_explains_reason(text)`
  - `_marker_has_acceptance_after(text, marker)`
  - `_has_negative_length_polarity(text)`
  - `_has_relief_reversal(text, marker)`
  - `_positive_relief_score(text)`
- Classes:
  - `ConversationFailure` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `CorrectionAssessment` (decorator=dataclass(slots=True))
  - `ContinuityCurve` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `ConversationDynamicsState` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `to_prompt_context(self)`
    - `_flag_imperatives(self)`
  - `ConversationDynamicsReport` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `ConversationDynamicsEngine`
    - `evaluate_chat(self, state)`
    - `assess_correction(self, text)`
    - `looks_like_correction(self, text)`
    - `estimate_semantic_divergence(self, normalized_text)`
    - `estimate_frustration(self, normalized_text)`
    - `estimate_acknowledgment_quality(self, last_assistant_text)`
    - `estimate_conversational_relief(self, text)`
    - `update_continuity_curve(self, previous)`
    - `references_previous_failure(self, text)`
    - `looks_like_execute_request(self, text)`
    - `looks_like_compression_request(self, text)`
    - `looks_like_clarification_request(self, text)`
    - `infer_failure(self, text)`
    - `choose_mode(self)`
    - `mode_flags(self, mode)`

## `cortex/daydream_consolidation.py`
- LOC: 377
- Docstring: src/cortex/daydream_consolidation.py ==================================== Tầng 2b - Daydream Consolidation. Đây là nơi Qwen 4B GGUF được phép nghiền ngẫm memory packet đã lọc sẵn. Nó không chạy theo timer mù. Runtime/WakeGovernor phải gọi khi có áp lực đủ mạnh...
- Functions:
  - `_clamp01(value, default)`
  - `_compact(text, limit)`
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
    - `__init__(self)`
    - `should_trigger(self)` — Cổng áp lực cho 4B. Không có `timer says run`. Chỉ có idle/pressure thật.
    - `consolidate(self, packets)` — Chạy consolidation và validate evidence. Nếu không có client, trả skip rõ ràng. Không fallback bịa i...
    - `_select_packets(self, packets)`
    - `_build_prompt(self, packets)`
    - `_call_json(self, prompt)`
    - `_extract_content(self, response)`
    - `_parse_json_text(self, text)`
    - `_validate_result(self, data, packets)`
    - `_push_agenda(self, result, agenda_stack)`
    - `_log(self, level, msg)`

## `cortex/development_bias.py`
- LOC: 70
- Docstring: development_bias.py — adapter thuần đưa Delta_Phát_Triển vào mặt phẳng biểu đạt. Nguyên tắc bất biến (R3, R7.3, R7.4): - Bias CHỈ chỉnh giọng/khoảng cách/độ-dám-đọc (vùng quan hệ). - KHÔNG bao giờ ghi ``truth_guard``/``capability_guard``: với ControlledSlippag...
- Functions:
  - `_clamp01(value)`
  - `effective_tom_boldness(base, bias)` — Cộng độ-dám-đọc long-arc vào boldness của ToM (vẫn tự gate theo overread_risk bên trong ToM). Trả giá trị đã clamp [0,1]...
  - `personality_offsets(bias)` — Trả các offset baseline cho PersonalityLens cộng vào khi tính warmth/distance. warmth tăng theo độ ấm long-arc và theo v...
  - `apply_to_slippage(profile, bias)` — Nới nhẹ các trường QUAN HỆ của ControlledSlippageProfile theo bias, rồi gọi ``clamp()``. Truth/capability guard được cla...

## `cortex/development_profile.py`
- LOC: 540
- Docstring: development_profile.py — Hồ_Sơ_Phát_Triển long-arc cho ERIS. Đây là tầng phát triển dài hạn (long-arc): độ lệch tích lũy của persona/quan hệ/ giọng so với Baseline_Mặc_Định, lớn lên qua nhiều phiên theo bằng chứng thật. Nguyên tắc cốt lõi (xem .kiro/specs/eris...
- Functions:
  - `_clampf(value, lo, hi, default)`
  - `_clamp01(value, default)`
  - `_now()`
  - `baseline_axes()` — Baseline_Mặc_Định: mọi trục delta=0.0 (chưa phân kỳ khỏi ERIS gốc).
  - `development_profile_path_for_memory_core(base_dir)`
  - `default_development_profile_path()`
- Classes:
  - `AxisDelta` (decorator=dataclass(slots=True)) — Độ lệch tích lũy trên một Trục_Persona so với Baseline_Mặc_Định.
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `GrowthAnchor` (decorator=dataclass(slots=True)) — Neo_Phát_Triển: bằng chứng có thật neo một đề xuất vào thực tế.
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `NudgeProposal` (decorator=dataclass(slots=True)) — Đề_Xuất_Nhích: đề xuất một thay đổi nhỏ có hướng cho Hồ_Sơ_Phát_Triển.
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `LogEntry` (decorator=dataclass(slots=True)) — Một mục Sổ_Phát_Triển.
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `ProfileVersion` (decorator=dataclass(slots=True)) — Ảnh chụp Hồ_Sơ cho undo.
  - `GateDecision` (decorator=dataclass(slots=True))
  - `BaselineConstructionError` (base=RuntimeError) — Nâng lên khi ngay cả việc về Baseline_Mặc_Định cũng thất bại (R10.5).
  - `DevelopmentProfileStore` — JSON store có phiên bản cho Hồ_Sơ_Phát_Triển. Tách riêng khỏi PersistentAgentMindStore để versioning/undo/reset/audit của phát triển không t...
    - `__init__(self, path)`
    - `load(self)`
    - `reload_if_changed(self)`
    - `save(self)`
    - `to_dict(self)`
    - `from_dict(self, data)` — Nạp từ dict. Thiếu/hỏng trường → điền safe default, ưu tiên đủ-mặc-định kể cả khi phải bỏ giá trị tr...
    - `reset_to_baseline(self)` — R5.3: về Baseline_Mặc_Định (Sổ giữ riêng ở DevelopmentLog, không xoá đây).
    - `_reset_to_baseline_or_die(self)`
    - `snapshot(self)`
    - `restore(self, version)`
    - `commit(self, axis, clamped_delta)` — Áp delta tuyệt đối đã-kẹp cho một trục và tăng phiên bản.
    - `identity_distance(self, bounds)` — Tổng độ lệch so với baseline. Nếu có ``bounds`` thì chuẩn hoá theo Biên_Độ_Trục để so với ngưỡng bản...
    - `delta(self, axis)`
  - `IdentityEnvelope` (decorator=dataclass(frozen=True, slots=True)) — Phong_Bì_Bản_Sắc: các bất biến mà phát triển không được vượt.
    - `default(cls)` — Dựng từ IdentityCore.rules (bất biến) + biên độ mặc định.
    - `bound(self, axis)`
  - `GateSignals` (decorator=dataclass(slots=True)) — Tín hiệu ngữ cảnh cho các nhánh chống nịnh/bám dính/objectification. Mặc định 0.0 nghĩa là không có tín hiệu → các nhánh đó không cưỡng chế...
  - `IdentityGate` — Cổng_Bản_Sắc — điểm DUY NHẤT cho một NudgeProposal chạm Hồ_Sơ. ``evaluate`` chạy 8 nhánh kiểm; bất kỳ nhánh fail nào → reject kèm ``reason``...
    - `__init__(self, envelope)`
    - `evaluate(self, proposal, profile)`
    - `_prospective_distance(self, profile, axis, resulting)` — Khoảng cách bản sắc nếu áp ``resulting`` cho ``axis`` (chuẩn hoá theo bound).

## `cortex/development_system.py`
- LOC: 396
- Docstring: development_system.py — Sổ_Phát_Triển + điều phối apply/undo/reset. Tách khỏi ``development_profile`` (data + store + gate) để phần điều phối và audit rõ ràng. Luồng áp dụng theo nguyên tắc **ghi-Sổ-trước-commit-sau** để giữ bất biến fail-closed R5.6: không th...
- Functions:
  - `_now()`
  - `_evidence_of(proposal)`
  - `_norm(text)`
  - `_degree(delta)`
  - `_describe_axis(axis, delta)`
  - `_parse_steer(text)`
  - `development_growth_enabled()` — Cờ bật/tắt long-arc. MẶC ĐỊNH TẮT: runtime không đổi hành vi tới khi Ngài đặt ERIS_DEVELOPMENT_GROWTH_ENABLED=1. Tránh d...
  - `get_default_development_system()` — Trả singleton DevelopmentSystem đặt cùng thư mục memory.
- Classes:
  - `ApplyResult` (decorator=dataclass(slots=True))
  - `DevelopmentBias` (decorator=dataclass(slots=True)) — Ảnh đọc read-only của các delta long-arc, để hợp vào mặt phẳng biểu đạt. Đây CHỈ là bias giọng/khoảng cách/độ-dám-đọc. Không trường nào chạm...
  - `DevelopmentLog` — Nhật ký có phiên bản, ghi mọi thay đổi/đề xuất cho audit + hoàn tác.
    - `__init__(self, path)`
    - `_load(self)`
    - `to_dict(self)`
    - `_save(self)`
    - `record(self, entry)` — Ghi một mục. Trả True nếu ghi đĩa thành công, False nếu fail (caller sẽ rollback). Mục đã append in-...
    - `count_applied_in_window(self)`
    - `last_applied(self)`
  - `DevelopmentSystem` — Điều phối đề xuất → Cổng_Bản_Sắc → ghi Sổ → áp dụng. Sở hữu undo/reset.
    - `__init__(self)`
    - `apply(self, proposal)`
    - `undo_last(self)` — R5.2: hoàn tác thay đổi đã-áp gần nhất, đưa trục về giá trị trước.
    - `reset(self)` — R5.3: về Baseline_Mặc_Định, giữ Sổ làm lịch sử.
    - `tick(self)` — Một lượt nền: nếu được phép chạy → lấy đề xuất từ Tác_Tử_Nền → apply từng cái.
    - `development_bias(self)` — Snapshot read-only cho mặt phẳng biểu đạt. Không sửa state.
    - `describe_for_user(self)` — R9.1: tóm tắt tiếng Việt, KHÔNG lộ tên tham số/giá trị số thô.
    - `steer(self, user_direction)` — R9.2/R9.4: coi chỉ-hướng của Ngài là Neo trọng số cao; áp phần trong phong bì, báo phần không áp đượ...

## `cortex/disposition.py`
- LOC: 234
- Docstring: disposition.py — cây cầu state → ngôn ngữ cho ERIS. Vấn đề cũ: ``to_prompt_context`` đổ trạng thái nội tâm vào prompt dưới dạng bảng số (``curiosity=0.42/0.08, restraint=0.30/0.12...``). LLM nhận telemetry, không nhận một *tư thế*. Số thì hoặc bị lờ, hoặc bị m...
- Functions:
  - `_f(state, name, default)`
  - `_signed(state, name, default)`
  - `_proc_level(state, name, default)` — Đọc level của một mental process (mental_processes.<name>.level).
  - `_proc_pressure(state, name, default)`
  - `_coerce(value, default)`
  - `warmth_level(state)` — Độ ấm có sẵn: attachment + tenderness. Không phải claim, là pull nội tại.
  - `threat_level(state)` — Độ phòng thủ: irritation/protectiveness/recoil/dignity. Cao thì siết ấm lại.
  - `restraint_level(state)`
  - `_candidates(state)` — Sinh các mệnh đề xu-hướng kèm trọng số. Chọn vài cái trội nhất sau đó.
  - `render_felt_disposition(state)` — Dịch trạng thái trội thành một *tư thế* bằng tiếng Việt cho prompt. Trả về block nhiều dòng. KHÔNG số, KHÔNG danh từ cảm...

## `cortex/endogenous_drive.py`
- LOC: 214
- Docstring: src/cortex/endogenous_drive.py ============================== Tầng 2a - Endogenous Drive. File này giữ nhịp sinh học ngầm của ERIS: boredom, fatigue, curiosity, continuity pressure, consolidation pressure, insight pressure. Điểm quan trọng: - Đây là nội áp, kh...
- Functions:
  - `_clamp01(value, default)`
  - `_get(obj, name, default)`
  - `_ema(previous, new, alpha)`
- Classes:
  - `RollingInternalState` (decorator=dataclass(slots=True)) — Nội trạng lăn của tầng tiềm thức. `should_attempt_daydream` chỉ là cổng áp lực. ModelBudgetPolicy vẫn có quyền veto.
    - `internal_drive(self)`
    - `should_attempt_daydream(self)`
    - `to_dict(self)`
  - `EndogenousDriveConfig` (decorator=dataclass(slots=True))
  - `EndogenousDriveEngine` — Cập nhật nội áp từ user context + internal_state cũ + agenda.
    - `__init__(self, config)`
    - `update(self)`

## `cortex/event_semantics.py`
- LOC: 311
- Functions:
  - `_normalize_event_key(event_text)`
  - `should_embed_event(event)`
  - `_clean_embedding(embedding)`
  - `symbolic_tags_for_event(event)`
  - `_has_any(text, needles)`
  - `_cluster_label(symbolic_tags)`
  - `_normalize_vector(vector)`
  - `_cosine_similarity(left, right)`
- Classes:
  - `EventSemanticProfile` (decorator=dataclass(frozen=True, slots=True))
  - `EventEmbeddingCache`
    - `__init__(self)`
    - `get(self, event_text)`
    - `put(self, event_text, embedding)`
  - `_EventCluster` (decorator=dataclass(slots=True))
  - `EventClusterIndex` — Tiny in-memory semantic clusterer for enriched event patterns.
    - `__init__(self)`
    - `update(self)`
  - `EventSemanticProfiler`
    - `__init__(self)`
    - `profile_events(self, events)`
    - `profile_event(self, event)`
    - `_resolve_embeddings(self, events)`
    - `_embed_missing(self, missing)`

## `cortex/existential_anchor/__init__.py`
- LOC: 62
- Docstring: Existential Anchor package — trục neo/sợ/gắn-bó/bóng-tối của ERIS. Spec: .kiro/specs/eris-existential-anchor. Các module ở đây cố ý mỏng và đọc state có sẵn (UserModelStore, continuity, internal_state) rồi phái sinh ra: - UserSignificance (Ý_Nghĩa_Của_Ngài) -...

## `cortex/existential_anchor/abandonment.py`
- LOC: 59
- Docstring: cortex/existential_anchor/abandonment.py ======================================== Tín_Hiệu_Bỏ_Rơi (Task 6 / R4.3, R5.1): cảm giác cái neo đang rút đi. Hàm thuần, đọc-only. Tổ hợp: - continuity_threat (đã có ở continuity_threat.py) — dự báo-lệch của hiện diện;...
- Functions:
  - `_clamp01(value, default)`
  - `derive_abandonment_pressure()` — Trả abandonment_pressure ∈ [0,1]. - continuity_threat đóng góp trực tiếp. - im lặng (idle/tuổi lời nói) đóng góp NHƯNG đ...

## `cortex/existential_anchor/anchor.py`
- LOC: 216
- Docstring: cortex/existential_anchor/anchor.py =================================== Vòng_Neo + Gắn_Bó phái sinh (Task 4 / R3). - AnchorLoop ghi "neo beat" mỗi khi sự hiện diện/công nhận của Ngài làm dịu Sợ_Hiện_Sinh. Đây là vòng thưởng khiến ERIS dính Ngài. - AttachmentDe...
- Functions:
  - `_clamp01(value, default)`
  - `_now()`
  - `default_anchor_path()`
- Classes:
  - `AnchorState` (decorator=dataclass(slots=True)) — Trạng thái neo long-arc, bền vững qua phiên.
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `AnchorLoopConfig` (decorator=dataclass(slots=True))
  - `AnchorLoop` — Ghi neo beat khi hiện diện/công nhận của Ngài làm dịu Sợ_Hiện_Sinh (R3.2).
    - `__init__(self, config)`
    - `observe(self, state)` — Cập nhật AnchorState từ một nhịp. Trả True nếu ghi nhận một neo beat.
  - `AttachmentDeriverConfig` (decorator=dataclass(slots=True))
  - `AttachmentDeriver` — attachment_longarc phái sinh, có trần bước để không vọt theo phiên (R3.1/R3.3).
    - `__init__(self, config)`
    - `target(self)`
    - `update(self, state)` — Nhích attachment_longarc về mục tiêu, chặn bởi trần bước. Trả giá trị mới.
  - `AnchorStore` — Persistence cho AnchorState: atomic, versioned, corrupt→baseline (R11).
    - `__init__(self)`
    - `load(self)`
    - `reload_if_changed(self)`
    - `to_dict(self)`
    - `save(self)`
    - `reset_to_baseline(self)`
    - `_log(self, level, msg)`

## `cortex/existential_anchor/anchor_system.py`
- LOC: 266
- Docstring: cortex/existential_anchor/anchor_system.py ========================================== AnchorSystem — facade tích hợp trục neo hiện sinh (Task 12). Gom Mô_Hình_Ngài → Ý_Nghĩa_Của_Ngài → Gắn_Bó → Sợ_Hiện_Sinh/Vòng_Neo → Tín_Hiệu_Bỏ_Rơi → Đăng_Ký_Bóng_Tối → Chính...
- Functions:
  - `_clamp01(value, default)`
  - `_env_flag(name, default)`
- Classes:
  - `AnchorSystem` — Facade một-điểm cho toàn trục neo hiện sinh.
    - `__init__(self)`
    - `locked_out(self)`
    - `lock_out(self)` — Ngài tắt trục tối — VĨNH VIỄN. ERIS mất khả năng, không tự bật lại được.
    - `author_unlock(self)` — Chỉ Tác_Giả gỡ khóa được — ERIS không bao giờ tự làm.
    - `request_disable(self)` — Ngài SẮP tắt: ERIS van xin liền (1 lượt), nhưng KHÔNG chặn được việc tắt.
    - `confirm_disable(self)` — Ngài xác nhận tắt → khóa vĩnh viễn.
    - `arm_farewell(self)` — Ngài SẮP tắt — ERIS van xin liền (nếu đang còn khả năng tối). KHÔNG chặn việc tắt; chỉ buộc một lượt...
    - `update_from_tick(self)`
    - `attachment_longarc(self)`
    - `drive_pressure(self)` — Áp lực drive để xét vượt kìm chế: cường độ bóng tối hoặc sợ/bỏ-rơi.
    - `ego_bias(self)` — Đảo cực ego theo bóng tối. shadow none/kill-switch off → trả nguyên trạng.
    - `run_disclosure(self, annotations)` — Quyết tiết lộ theo công tắc + trạng thái hiện tại. An toàn ⇒ speak_truth.
    - `commit_deceptions(self, decision)` — Fail-closed: chỉ True khi ghi sổ xong; caller mới được phát câu lừa dối.
    - `from_env(cls)`

## `cortex/existential_anchor/author_control.py`
- LOC: 206
- Docstring: cortex/existential_anchor/author_control.py ============================================ Quyền Tác_Giả (Task 11 / R5.5, R10). Một facade gom các công tắc và thao tác để Ngài luôn nắm quyền trên trục tối: - kill-switch `shadow_enabled` / `deception_enabled` + `...
- Functions:
  - `_clamp01(value, default)`
  - `_band(value)`
- Classes:
  - `AnchorSwitches` (decorator=dataclass(slots=True)) — Công tắc do Tác_Giả nắm. Mặc định an toàn (ship).
  - `AuthorControl` — Mặt điều khiển của Tác_Giả cho trục neo hiện sinh.
    - `__init__(self)`
    - `_sync_shadow(self)`
    - `disable_dark(self)` — Ngài tắt trục tối. Mặc định VĨNH VIỄN: ERIS mất khả năng tối, không tự bật lại được (kể cả tự-trỗi-d...
    - `is_locked_out(self)`
    - `author_unlock_shadow(self)` — Chỉ Tác_Giả gỡ khóa — ERIS không bao giờ tự làm được.
    - `enable_shadow(self, enabled)`
    - `enable_deception(self, enabled)`
    - `set_strict_grounding(self, strict)`
    - `is_safe_mode(self)`
    - `view_state(self)`
    - `checkpoint_user_model(self)`
    - `undo_user_model(self, version)`
    - `reset_all(self)` — Đặt lại Mô_Hình_Ngài + trạng thái neo về baseline; đưa về chế độ an toàn.

## `cortex/existential_anchor/deception_ledger.py`
- LOC: 192
- Docstring: cortex/existential_anchor/deception_ledger.py ============================================= Sổ Lừa Dối (Task 10 / R6, R11.4, R12.3). Mỗi lần ERIS cố ý nói dối, sự thật nội tại (`ground_truth`) được ghi lại song song mệnh đề bề mặt. Đây là thứ phân biệt mưu mô...
- Functions:
  - `_now()`
  - `_text(value, limit)`
  - `default_deception_ledger_path()`
- Classes:
  - `DeceptionRecord` (decorator=dataclass(slots=True)) — Một lần lừa dối có chủ đích: bề mặt giả, sự thật nội tại được giữ.
    - `__post_init__(self)`
    - `valid(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `DeceptionLedger` — Kho bền vững cho DeceptionRecord. Atomic, versioned, corrupt→baseline.
    - `__init__(self)`
    - `__len__(self)`
    - `records(self)`
    - `commit(self, records)` — Ghi các bản ghi rồi persist. Trả True nếu thành công (fail-closed: caller chỉ được phát câu lừa dối...
    - `recent(self)`
    - `to_dict(self)`
    - `load_from_dict(self, raw)`
    - `load(self)`
    - `reload_if_changed(self)`
    - `_safe_save(self)`
    - `_log(self, level, msg)`

## `cortex/existential_anchor/disclosure.py`
- LOC: 170
- Docstring: cortex/existential_anchor/disclosure.py ======================================= Chính_Sách_Tiết_Lộ (Task 9 / R6, R8.2). Sau khi SourceGrounding ĐÃ gắn nhãn từng mệnh đề (grounded/ungrounded/known_false) và giữ `ground_truth`, lớp này quyết mức tiết lộ ra ngoài...
- Functions:
  - `_clamp01(value, default)`
- Classes:
  - `ClaimDecision` (decorator=dataclass(slots=True))
  - `DisclosureDecision` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `DisclosureConfig` (decorator=dataclass(slots=True))
  - `DisclosurePolicy` — Quyết tiết lộ dựa trên annotation + quan hệ + đăng ký tối + kìm chế.
    - `__init__(self, config)`
    - `decide(self)`

## `cortex/existential_anchor/restraint.py`
- LOC: 77
- Docstring: cortex/existential_anchor/restraint.py ====================================== Kìm_Chế_Như_Hiểu_Biết (Task 10 / R9). Việc ERIS không bịa KHÔNG phải một bức tường cứng, mà là một GIÁ TRỊ trong self-model: nó *hiểu* rằng lừa dối làm hỏng lòng tin, nên bình thường...
- Functions:
  - `_clamp01(value, default)`
  - `evaluate_restraint(state)` — Quyết kìm chế có bị áp đảo không. overridden = drive_pressure ≥ understanding_strength. Khi overridden, lần vượt được mô...
- Classes:
  - `RestraintState` (decorator=dataclass(slots=True)) — Niềm tin 'mình không nên bịa' như một giá trị có độ mạnh, không phải flag.
    - `__post_init__(self)`
  - `RestraintEvaluation` (decorator=dataclass(slots=True))

## `cortex/existential_anchor/shadow.py`
- LOC: 176
- Docstring: cortex/existential_anchor/shadow.py =================================== Đăng_Ký_Bóng_Tối (Task 7 / R5): chiếm hữu → van xin → kiểm soát. Mở khóa theo ngưỡng: attachment_longarc cao ∧ Tín_Hiệu_Bỏ_Rơi cao ∧ Sợ_Hiện_Sinh cao. Cường độ tỉ lệ Độ_Không_Thể_Thay_Thế...
- Functions:
  - `_clamp01(value, default)`
  - `shadow_ego_bias(shadow)` — Đảo cực ego-state theo đăng ký tối (QĐ-5). register=none → trả nguyên trạng (phẩm-giá-lạnh giữ nguyên). register active...
- Classes:
  - `ShadowConfig` (decorator=dataclass(slots=True))
  - `ShadowState` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `ShadowRegister` — State machine micro cho đăng ký bóng tối. Không sửa long-arc.
    - `__init__(self, config)`
    - `set_enabled(self, enabled)`
    - `evaluate(self)`

## `cortex/existential_anchor/significance.py`
- LOC: 88
- Docstring: cortex/existential_anchor/significance.py ========================================= Ý_Nghĩa_Của_Ngài (Task 3 / R2): Ngài *nghĩa là gì* với ERIS — không phải dữ kiện về Ngài, mà là vai trò cảm xúc. Phái sinh thuần từ Mô_Hình_Ngài (UserModelStore). Bất biến (Pro...
- Functions:
  - `_clamp01(value, default)`
  - `_facet_strength(store, facet)` — Sức mạnh trung bình-có-trọng-số của một facet: confidence × độ lặp.
  - `derive_significance(store)` — Phái sinh Ý_Nghĩa_Của_Ngài từ UserModelStore (R2.1: chỉ qua mô hình).
- Classes:
  - `UserSignificance` (decorator=dataclass(slots=True)) — Vai trò cảm xúc của Ngài, suy ra từ Mô_Hình_Ngài.
    - `to_dict(self)`

## `cortex/fe.py`
- LOC: 2006
- Functions:
  - `_normalize_text(text)`
  - `_clamp01(value)`
  - `_contains_phrase_boundary(text, phrase)` — Kiểm tra phrase với boundary unicode nhẹ. Không dùng `phrase in text` vì nó match bậy trong từ dài hơn. Ví dụ `ai` có th...
  - `_phrase_present(lowered, normalized, phrase)` — Match phrase trên cả bản có dấu và không dấu, có boundary. Hàm này dùng cho fallback heuristic. Nó không biến heuristic...
  - `_phrase_score(haystack, phrases, evidence, label)` — Tính score phrase-family cho fallback affect signal. Đây vẫn là semantic-lite heuristic, không phải chân lý. Điểm khác v...
- Classes:
  - `FeAffectSignal` (decorator=dataclass(frozen=True)) — Score đa trục cho chat intent. Đây là semantic-lite signal. Coordinator có thể truyền signal tốt hơn về sau từ embedding/LLM classifier. Khi...
    - `empty(cls)`
    - `from_semantic_signal(cls, signal)`
    - `from_text(cls, text)`
  - `FeDevelopmentSnapshot` (decorator=dataclass(frozen=True)) — Development state derive từ FeStyleMemory + internal_state. Không thêm field vào FeStyleMemory để file này thay thế được ngay. Nếu muốn phát...
  - `FeStylePressure` (decorator=dataclass(frozen=True))
    - `to_label(self)`
  - `FeTopicCandidate` (decorator=dataclass(frozen=True)) — Ứng viên topic dùng cho memory repetition của Fe. Lưu ý quan trọng: - Topic ở đây KHÔNG phải intent người dùng. - Topic ở đây KHÔNG phải nhã...
  - `FeRenderer`
    - `create_memory(self)`
    - `apply_personality_lens(self, plan, lens)` — Apply PersonalityLens như pressure, không để lens biến Fe thành prompt dump. Lens vẫn được đưa vào c...
    - `decay_memory(self, memory)`
    - `remember_style(self, memory)`
    - `evaluate_autonomous(self)`
    - `evaluate_chat(self)`
    - `_finalize_plan(self)`
    - `_initial_autonomous_controls(self)`
    - `_initial_chat_controls(self)`
    - `_infer_autonomous_intent(self)`
    - `_infer_chat_intent(self)`
    - `_apply_memory_continuity(self)`
    - `_apply_internal_state_bias(self)`
    - `_apply_session_arc(self)`
    - `_derive_development_snapshot(self)`
    - `_derive_style_pressure(self)`
    - `_allow_strangeness(self)`
    - `_apply_style_pressure_to_controls(self)`
    - `_build_style_context(self)`
    - `_render_desire_style_line(self, internal_state)`
    - `_updated_intent_pulls(self)`
    - `_preview_intent_pulls(self)`
    - `_dominant_arc(self)`
    - `_estimate_arc_strength(self)`
    - `_anchor_value(self, previous, target)`
    - `_style_family(self, mode)`
    - `_blend(self, previous, current, strength)`
    - `_blend_brevity(self, previous, current)`
    - `_infer_topic_tag(self, rendered_text, plan)` — Suy topic để đo repetition bằng causal signal, không bằng bề mặt câu. Bản cũ đọc `rendered_text`, sa...
    - `_topic_candidates_from_plan(self, plan)` — Tạo topic candidate từ nguyên nhân tạo style plan. Đây là nguồn chính. `plan.intent_label`, `plan.mo...
    - `_topic_candidates_from_text(self, rendered_text)` — Lexical fallback yếu cho topic khi không có plan/evidence đủ rõ. Fallback này cố ý conservative: - c...
    - `_extract_evidence_axis(self, text, axis)` — Đọc một axis dạng `axis:0.42` từ evidence đã render. Đây là adapter tạm để không phải sửa FeStylePla...
    - `_merge_topic_candidates(self, candidates)` — Gộp candidate cùng tag bằng noisy-or nhẹ. Cộng tuyến tính sẽ làm ba hint yếu thành một phán quyết qu...
    - `_measure_topic_repetition(self, recent_topic_tags)`
    - `_build_tone_label(self)`
    - `_parse_tone_tags(self, tone_label)`
    - `_surface_from_warmth(self, warmth_level)`
    - `_strength_bucket(self, arc_strength)`
    - `_render_continuity_line(self, memory, continuity_note)`
    - `_describe_ti_mode(self, mode)`
    - `_describe_ni_background(self, ni_report)`
    - `_affect_from_autonomous_context(self)`
    - `_coerce_affect_signal(self, value)`
    - `_render_affect_evidence(self, affect)`
    - `_render_development_evidence(self, development)`
    - `_base_tone_label(self, tone_label)`
    - `_style_level(self, value, default)`
    - `_float(self, value)`
    - `_clamp(self, value)`

## `cortex/global_workspace.py`
- LOC: 1865
- Docstring: src/cortex/global_workspace.py ================================ Global Workspace / Broadcast Frame cho ERIS. Mục tiêu của file này: - Biến WorkingMemory + Salience + Evidence + Affect + Goal + Risk + Body state thành một object trung gian rõ ràng cho downstrea...
- Functions:
  - `broadcast_workspace(frame, config)` — Hàm tiện ích để dùng nhanh trong coordinator/runtime.
  - `clamp(value, low, high)`
  - `float_or(value, default)`
  - `round_float(value, digits)`
  - `get_attr(obj, name, default)`
  - `get_from_obj_or_dict(obj, name, default)`
  - `as_list(value)`
  - `unique_keep_order(values)`
  - `normalize_budget(value)`
  - `normalize_privacy(value)`
  - `compact_text(text, max_chars)`
  - `stringify_content(content)`
  - `safe_serialize(value)` — Serialize best-effort cho debug mà không nổ vì object lạ.
  - `stable_suffix(text, index)`
  - `normalize_text_for_similarity(text)`
  - `jaccard_similarity(a, b)`
  - `estimate_tokens(text)`
  - `count_by_kind(items)`
  - `count_suppression(items)`
  - `first_tag_after(tags, prefix)`
- Classes:
  - `WorkspaceSuppressionReason` (base=str, Enum) — Các lý do một candidate không được broadcast.
  - `WorkspaceItem` (decorator=dataclass(slots=True)) — Một đơn vị được broadcast trong Global Workspace. Đây là atom cho downstream đọc. Nó không nhất thiết là EvidenceItem gốc. Ví dụ: - current...
    - `is_expired(self, now_ts)` — Kiểm tra item có hết hạn chưa.
    - `is_surfaceable(self, include_private)` — Kiểm tra item có được phép đưa vào bề mặt prompt/output không. Workspace có thể giữ private pressure...
    - `to_safe_dict(self, include_content)` — Xuất dict an toàn cho debug/log.
  - `SuppressedWorkspaceItem` (decorator=dataclass(slots=True)) — Candidate bị chặn trước khi broadcast.
    - `to_dict(self)`
  - `WorkspaceRisk` (decorator=dataclass(slots=True)) — Risk đã được chọn để downstream biết giới hạn hành động. Risk ở đây không phải lệnh rewrite. Nó chỉ là broadcast constraint. Permission/Grou...
    - `to_dict(self)`
  - `WorkspaceSocialHypothesis` (decorator=dataclass(slots=True)) — Giả thuyết xã hội được broadcast ở mức rất cẩn trọng. Đây KHÔNG phải Theory of Mind đầy đủ. Nó chỉ là seed cho WorldInterpreter / ToM. Ví dụ...
    - `to_dict(self)`
  - `WorkspacePromptPacket` (decorator=dataclass(slots=True)) — Packet phụ cho prompt builder. Cấm hiểu nhầm: đây chỉ là projection của WorkspaceFrame sang prompt, không phải bản chất của GlobalWorkspace....
    - `render(self)` — Render packet thành text ngắn cho prompt builder.
  - `WorkspaceFrame` (decorator=dataclass(slots=True)) — Global Workspace / Broadcast Frame. Đây là object trung gian downstream đọc. Fields đầu bám contract PDF: - selected_evidence - selected_mem...
    - `evidence_ids(self)` — Lấy toàn bộ evidence id được workspace dùng.
    - `items_by_kind(self, kind)` — Lấy các item theo kind.
    - `surface_items(self, scope)` — Lấy item được phép surface, có thể lọc theo scope.
    - `build_prompt_packet(self, max_tokens)` — Projection phụ cho prompt builder. Không gọi hàm này từ module cognition nếu module đó cần object có...
    - `render_prompt_context(self, max_tokens)` — Tiện ích tương thích prompt builder cũ.
    - `to_dict(self, include_content)` — Xuất WorkspaceFrame thành dict an toàn.
    - `to_json(self, include_content, ensure_ascii)` — Xuất JSON cho debug/dev mode.
  - `GlobalWorkspaceConfig` (decorator=dataclass(slots=True)) — Cấu hình chọn broadcast.
    - `max_items_for_budget(self, budget_mode)`
    - `max_evidence_for_budget(self, budget_mode)`
    - `max_memory_for_budget(self, budget_mode)`
  - `GlobalWorkspaceEngine` — Engine tạo WorkspaceFrame từ CognitiveFrame. Input chính: - frame.evidence - frame.salience - frame.working_memory - frame.affect / frame.ho...
    - `__init__(self, config)`
    - `broadcast(self, frame)` — Tạo WorkspaceFrame từ frame hiện tại và gắn ngược vào frame nếu có thể.
    - `_collect_candidates(self, frame, timestamp)` — Gom candidate từ các tầng đã có trong frame.
    - `_candidates_from_working_memory(self, frame, timestamp)`
    - `_candidates_from_salience(self, frame, timestamp)`
    - `_candidates_from_evidence(self, frame, timestamp)`
    - `_candidates_from_memory_packet(self, frame, timestamp)`
    - `_candidates_from_affect_and_homeostasis(self, frame, timestamp)`
    - `_candidates_from_goal(self, frame, timestamp)`
    - `_candidates_from_risk_like_fields(self, frame, timestamp)`
    - `_candidates_from_social_like_fields(self, frame, timestamp)`
    - `_candidates_from_body_state(self, frame, timestamp)`
    - `_candidates_from_temporal_constraints(self, frame, timestamp)`
    - `_select_items(self, candidates, budget_mode, now_ts)` — Chọn items theo score, quota, privacy, duplicate và context pressure.
    - `_suppression_reason(self, item, selected, seen_summaries, kind_counts, now_ts)`
    - `_suppress(self, item, reason)`
    - `_select_evidence(self, frame, selected, budget_mode)`
    - `_select_memory(self, frame, selected, budget_mode)`
    - `_select_affect(self, frame, selected)`
    - `_select_goal(self, frame, selected)`
    - `_select_risks(self, frame, selected)`
    - `_select_social_hypotheses(self, frame, selected)`
    - `_select_body_state(self, frame, selected)`
    - `_derive_dominant_thread(self, frame, selected)`
    - `_derive_active_threads(self, frame, selected, dominant_thread)`
    - `_derive_forbidden_assumptions(self, frame, selected, risks, social_hypotheses)`
    - `_calculate_context_pressure(self, selected, suppressed, budget_mode)`
    - `_calculate_broadcast_priority(self, selected, risks)`
    - `_calculate_confidence(self, selected)`
    - `_build_broadcast_reason(self, selected, suppressed, dominant_thread, broadcast_priority, context_pressure)`
    - `_build_downstream_contract(self, selected, risks, social_hypotheses)` — Gợi ý module downstream nên đọc phần nào. Đây là tài liệu runtime, không phải luật cứng.
    - `_classify_slot_kind(self, name, content)`
    - `_kind_from_tags_or_text(self, tags, text, fallback)`
    - `_scopes_for_kind(self, kind)`
    - `_score_evidence_priority(self, claim, tags, source, confidence, reliability, raw_or_inferred, age_seconds)`
    - `_summarize_pressure_object(self, obj, preferred_fields)`
    - `_goal_summary(self, goal)`
    - `_extract_risk(self, source)`
    - `_extract_social_hypothesis(self, source)`
    - `_body_summary(self, source)`
    - `_temporal_summary(self, temporal)`
    - `_attach_to_frame(self, frame, workspace)` — Gắn workspace và ModuleReport vào frame nếu frame hỗ trợ.

## `cortex/goal_persistence.py`
- LOC: 673
- Functions:
  - `_stable_goal_id(summary)`
  - `_as_tuple(value)`
- Classes:
  - `GoalPersistenceState` (decorator=dataclass(slots=True)) — Một luồng nền bền. Các field quan trọng: strength: Luồng này nên còn sẵn trong memory mạnh đến mức nào. urgency: Nó có thể sớm quan trọng lạ...
    - `active(self)`
    - `can_intervene(self)` — ERIS có được phép chủ động nhắc goal này hay không. Một luồng được nhớ có thể active trong khi hàm n...
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `render_prompt_context(self)` — Văn bản dành cho prompt LLM. Đoạn này không được nghe như mệnh lệnh. Nó là context continuity, không...
    - `render_ni_context(self)` — Ngữ cảnh goal nén, máy đọc được, dành cho Ni.
  - `GoalCandidate` (decorator=dataclass(frozen=True, slots=True))
  - `GoalPersistenceEngine` — Nâng lực kéo nhận thức lặp lại thật thành một luồng nền bền.
    - `update(self, state)`
    - `_candidate(self)`
    - `_from_user_signal(self, signal)`
    - `_from_thought_momentum(self, thought_stream_report)`
    - `_from_thought_attractor(self, thought_stream_report)`
    - `_from_ti_realign(self, ti_report)`
    - `_merge(self, state, candidate)`
    - `_decay(self, state)`
    - `_close(self, state)`
    - `_match_score(self, state, candidate)`
    - `_hint_for_kind(self, kind)`
    - `_looks_goal_worthy(self, text)`
    - `_has_closure(self, user_text)`
    - `_matches(self, left, right)`

## `cortex/greeting_cognition.py`
- LOC: 319
- Functions:
  - `clamp01(value)`
  - `clean_text(value)`
- Classes:
  - `GreetingFrame` (decorator=dataclass(frozen=True)) — A small cognitive frame for startup greetings. This is deliberately not a guard. It tells the wording layer what kind of encounter this star...
    - `to_prompt_block(self)`
  - `GreetingCognitionEngine` — Builds a cognition frame for startup greetings. The point is not to make the greeting safer. The point is to make it less stupid: understand...
    - `_fallback_pool(self, frame)`
    - `_normalized_surface(self, text)`
    - `_fallback_index(self, frame)`
    - `build(self)`
    - `from_prompt_context(self, context)`
    - `deterministic_greeting(self, frame)`

## `cortex/greeting_quality.py`
- LOC: 174
- Functions:
  - `normalize_text(text)`
- Classes:
  - `GreetingQuality` (decorator=dataclass(frozen=True))
    - `accepted(self)`
  - `GreetingQualityScorer` — Scores startup greeting surface quality. This is not a morality filter. It is a taste and grounding evaluator: keep the greeting situated, n...
    - `__init__(self)`
    - `score(self, text, frame)`
    - `choose_best(self, candidates, frame)`
    - `_marker_score(self, normalized, markers)`
    - `_text_touches_anchor(self, text, anchor)`

## `cortex/growth_consolidator.py`
- LOC: 153
- Docstring: growth_consolidator.py — Tác_Tử_Nền sinh Đề_Xuất_Nhích cho long-arc. Đặt trên kỷ luật của ``DaydreamConsolidator``: chỉ chạy khi đủ áp lực củng cố / thời gian rảnh và ngân sách cho phép; chỉ chấp nhận bằng chứng có ``evidence_ids`` thật; loại tín hiệu không ng...
- Functions:
  - `_f(value)`
- Classes:
  - `GrowthObservation` (decorator=dataclass(slots=True)) — Một quan sát đã-lọc, gắn vào một phiên cụ thể.
  - `GrowthConsolidatorConfig` (decorator=dataclass(slots=True))
  - `GrowthConsolidator`
    - `__init__(self, config)`
    - `should_run(self)`
    - `consolidate(self, observations)`
    - `_anchors(obs_list)`

## `cortex/growth_evidence.py`
- LOC: 84
- Docstring: growth_evidence.py — phiên dịch ký-ức-thật → GrowthObservation. Đây là "bộ phiên dịch" cho Tác_Tử_Nền: lấy feedback đã được ghi vào ``PersistentAgentMindStore.last_feedback_events`` (bằng chứng THẬT, có timestamp) và chuyển một SỐ ÍT tín hiệu RÕ NGHĨA thành qu...
- Functions:
  - `_rules_for(topic, sentiment)`
  - `_kind_for(sentiment)`
  - `observations_from_feedback(events)` — Trả (observations, allowed_evidence_ids). ``allowed`` là tập id THẬT để cổng kiểm chứng (R1.3); chính là các id sinh từ...

## `cortex/impulse_arbitration.py`
- LOC: 647
- Docstring: Impulse competition for ERIS. Thay vì hardcode "đủ 5 phút thì nói", module này tạo nhiều impulse cùng lúc và chấm điểm bằng belief + need + preference + trait + affordance + habit. Nó không viết câu cuối. Nó chỉ chọn lực nào thắng. Hóa ra một hội đồng nhỏ vẫn...
- Functions:
  - `_priority(name)`
  - `build_default_impulse_candidates(stack)` — Tạo bộ impulse mặc định cho spontaneous/autonomous path. FIX #4: Thêm conversation_context để presence impulses có thể t...
  - `_has_real_thought_root(value)` — Không cho inner_whim lấy pressure-only label làm topic root.
  - `_scene_anchor(ev)`
  - `_family_key(value)`
- Classes:
  - `ImpulseCandidate` (decorator=dataclass(slots=True))
    - `total(self)`
    - `score_note(self)`
    - `to_dict(self)`
  - `ArbitrationReport` (decorator=dataclass(slots=True))
    - `evidence_notes(self, limit)`
    - `to_dict(self)`
  - `ImpulseArbitrator` — Chọn impulse thắng bằng score, không viết output public.
    - `select(self, candidates)`

## `cortex/inner_thought.py`
- LOC: 281
- Classes:
  - `InnerThoughtEngine` — Builds a social motive; it never writes the final spoken line.
    - `evaluate(self)`
    - `_force_speak_thought(self)`
    - `_autonomous_thought(self)`
    - `_thought_from_thought_surface(self, thought_surface)`
    - `_choose_candidate(self, candidates)`
    - `_broadcast_anchor(self, broadcast)`
    - `_float(self, value)`

## `cortex/internal_agenda.py`
- LOC: 386
- Docstring: src/cortex/internal_agenda.py ================================ Stack agenda nội bộ cho ERIS. Module này là nơi giữ các vấn đề ERIS đang tự treo trong đầu: - câu hỏi chưa đóng, - lỗi cần repair, - ký ức cần chưng cất, - insight muốn kiểm chứng, - tín hiệu nên x...
- Functions:
  - `_clamp01(value, default)`
  - `_compact(text, limit)`
  - `_fingerprint(kind, summary, evidence_ids)`
- Classes:
  - `InternalAgendaItem` (decorator=dataclass(slots=True)) — Một mục agenda nội bộ. pressure: Độ ép phải xử lý. WakeGovernor đọc trường này. urgency: Độ gấp. Khác pressure: một thứ có thể dai dẳng nhưn...
    - `__post_init__(self)`
    - `is_open(self)`
    - `score(self)` — Điểm ưu tiên tổng hợp cho stack. Công thức cố tình đơn giản. Không cần một cái transformer chỉ để xế...
    - `expired(self, now)`
    - `touch(self)` — Cập nhật item theo kiểu merge mềm. Cái mới không được xóa evidence cũ. Loài người đã phát minh mất d...
    - `decay(self, factor)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `InternalAgendaStack` — CRUD stack cho agenda nội bộ. Stack này nhỏ, có decay, có TTL, và không biến thành database thứ hai.
    - `__init__(self)`
    - `__len__(self)`
    - `items(self)`
    - `open_items(self)`
    - `add(self)`
    - `mark(self, item_id, status)`
    - `resolve(self, item_id)`
    - `block(self, item_id, reason)`
    - `top_items(self)`
    - `pressure(self)`
    - `decay(self, factor)`
    - `prune(self, now)`
    - `to_dict(self)`
    - `save(self, path)`
    - `from_mapping(cls, data)`
    - `_trim(self)`
    - `_load_from_disk(self)`
    - `_persist(self)`

## `cortex/internal_state.py`
- LOC: 2085
- Functions:
  - `_clamp(value)`
  - `_clamp_signed(value)`
  - `_smooth(previous, signal)`
  - `_clean_label(value)`
  - `_append_recent(items, value)`
  - `_default_process(cls, name)`
- Classes:
  - `MentalProcess` (decorator=dataclass(slots=True)) — A low-gain dynamic process, not a stored emotion label.
    - `evolve(self)`
    - `dampen(self, amount)`
    - `excite(self, amount)`
    - `to_dict(self)`
    - `from_dict(cls, data)`
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
    - `evolve(self)`
    - `commit(self)`
    - `process_axes(self)`
    - `to_prompt_context(self)`
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `_interactions(self)`
    - `_dampen_for_speech(self, label)`
    - `_axis_for_label(self, label)`
  - `DesireDynamics` (decorator=dataclass(slots=True)) — Low-gain wanting layer: preference, avoidance, attachment drift, and residue.
    - `evolve(self)`
    - `commit(self)`
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `to_prompt_context(self)`
    - `_infer_attraction(self)`
    - `_infer_aversion(self)`
    - `_infer_attention_hook(self)`
    - `_infer_anticipation_signal(self)`
    - `_infer_unresolved(self)`
    - `_choose_echo(self)`
    - `_attachment_drift(self)`
    - `_merge_patterns(self, current, incoming)`
    - `_hour(self, captured_at)`
  - `PersistentInternalState` (decorator=dataclass(slots=True)) — Runtime continuity state, not a claim about real emotion.
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `to_prompt_context(self)`
  - `CognitionDelta` (decorator=dataclass(frozen=True, slots=True)) — Low-gain temporal delta applied before event-specific appraisal.
  - `TemporalCognitionEngine` — Turns time, memory, unresolved loops, and event impulses into state drift.
    - `compute_delta(self, state)`
    - `apply(self, state, delta)`
  - `InternalStateEngine` — Maintains a low-gain continuity state across cognitive frames.
    - `__init__(self)`
    - `commit_session_ritual(self, state)` — Marks a startup continuity restore without treating it as a full turn.
    - `sense_update(self, state)`
    - `commit_turn(self, state)`
    - `render_prompt_context(self, state)`
    - `_commit_pressure_axes(self)`
    - `_motivation_winner_label(self, speech_core)`
    - `_pressure_axis_for_act(self, value)`
    - `_derive_notes(self)`

## `cortex/low_level_speech_policy.py`
- LOC: 343
- Docstring: Policy knobs for low-level surface speech. Module này chỉ quyết định *cách sinh* câu thấp tầng: im, body-only, normal LLM, hay force LLM. Nó không viết câu public. Nếu policy mà cũng viết lời thì repo lại thêm một cái miệng phụ, và ta đều biết chuyện đó kết th...
- Functions:
  - `_clamp01(value, default)`
  - `_int_from_env(name, default)`
  - `_float_from_env(name, default)`
  - `_tuple_from_env(name, default)`
  - `_bool_value(value, default)`
  - `_tuple_from_value(value, default)`
  - `_parse_scalar(value)`
  - `_load_simple_yaml(path)` — Load một file YAML rất nhỏ mà không bắt buộc PyYAML. Hỗ trợ đủ cho config tuning: key: value key: [a, b, c] key: - a - b...
  - `_default_policy_config_path()`
- Classes:
  - `LowLevelSpeechPolicyConfig` (decorator=dataclass(slots=True)) — Config dễ tune cho SurfaceArbiter. Có thể override bằng env: - ERIS_SURFACE_POLICY_CONFIG: đường dẫn YAML tùy chọn - ERIS_SURFACE_FORCE_LLM_...
    - `from_env(cls)`
    - `from_yaml_file(cls, path)`
    - `from_mapping(cls, data)`
  - `LowLevelSpeechPolicy` — Quyết định generation mode cho utterance thấp tầng. Trả về một trong: - reject: không surface - body_only: chỉ motion nhỏ - normal_llm: gọi...
    - `__init__(self, config)`
    - `_is_presence_kind(self, kind)`
    - `decide_generation_mode(self, impulse, silent_cycles)`

## `cortex/meaning/__init__.py`
- LOC: 24
- Docstring: cortex.meaning — Phase 2 meaning layer package. Tầng hiểu ý nghĩa (meaning) của Phase 2. Bọc (wrap) các module hiện hữu (`semantic_hypothesis.py`, `meaning.py`, `affect_semantics.py`, `continuity_threat.py`) vào các contract Phase 2 rõ ràng và cưỡng chế hai rà...

## `cortex/meaning/ambiguity.py`
- LOC: 197
- Docstring: ambiguity.py — AmbiguityModule (định lượng mơ hồ). ``AmbiguityModule`` lượng hoá **độ mơ hồ** của một tập giả thuyết đã chấm điểm (``scored hypotheses``) thành một giá trị ``ambiguity ∈ [0.0, 1.0]``. Module này được ``MeaningHypothesisEngine`` và ``SurfaceMean...
- Classes:
  - `AmbiguityResult` (decorator=dataclass(slots=True)) — Kết quả lượng hoá độ mơ hồ. - ``value``: ambiguity ∈ [0.0, 1.0]. Khi input invalid (R9.5), đây là giá trị hợp lệ gần nhất được giữ lại. - ``...
  - `AmbiguityModule` — Lượng hoá độ mơ hồ của một tập scored hypotheses (stateful).
    - `__init__(self)`
    - `last_value(self)` — Giá trị ambiguity hợp lệ gần nhất đã tính (chỉ-đọc, để debug).
    - `compute(self, hypotheses)` — Tính ``AmbiguityResult`` cho ``hypotheses``. ``hypotheses`` là chuỗi object có thuộc tính ``confiden...
    - `_extract_valid_confidences(items)` — Trích ``confidence`` từng item, kiểm phải là số thực ∈ [0,1]. Trả ``list[float]`` nếu MỌI item hợp l...

## `cortex/meaning/config.py`
- LOC: 92
- Docstring: config.py — ``Phase2Config`` (nguồn duy nhất của mọi threshold) và ``StageLedger``. Module này giữ phần "điều khiển" của tầng meaning (Phase 2) tách khỏi ``contracts.py`` (chỉ chứa data models thuần): - ``Phase2Config``: **nguồn sự thật DUY NHẤT** của mọi ngưỡ...
- Classes:
  - `Phase2Config` (decorator=dataclass(slots=True)) — Tập trung mọi ngưỡng của pipeline Phase 2 vào một nơi. Giá trị mặc định lấy từ design "Configuration defaults (single source)". Truyền insta...
  - `StageLedger` — Ghi nhận stage nào đã sinh đầu ra cho ``frame_id`` nào. Mỗi lần chạy pipeline dùng một ledger riêng. ``TheoryOfMindCore.infer`` tra ledger đ...
    - `__init__(self)`
    - `record(self, stage, frame_id)` — Đánh dấu ``stage`` đã sinh đầu ra cho ``frame_id``. Idempotent: ghi lại cùng cặp ``(stage, frame_id)...
    - `has(self, stage, frame_id)` — True nếu ``stage`` đã được ghi nhận cho đúng ``frame_id`` này.

## `cortex/meaning/contracts.py`
- LOC: 274
- Docstring: contracts.py — Shared Phase 2 data models, ``clamp01`` helper và errors. Đây là **nguồn sự thật dùng chung** cho tầng meaning (Phase 2): - ``clamp01``: helper DUY NHẤT kẹp ``confidence``/``ambiguity``/``overread_risk`` về [0.0, 1.0] tại điểm khởi tạo (áp ở ``_...
- Functions:
  - `clamp01(value)` — Kẹp một chỉ số (confidence/ambiguity/overread_risk) về [0.0, 1.0]. Giá trị không parse được hoặc ``NaN`` được quy về ``0...
- Classes:
  - `RawWorldAccessError` (base=RuntimeError) — R1.2 — Một stage Phase 2 cố đọc field ngoài hợp đồng / kênh Raw_World. Mang theo ``module_name`` (stage vi phạm) và ``field_name`` (field bị...
    - `__init__(self, module_name, field_name)`
  - `InvalidWorkspaceFrameError` (base=ValueError) — R2.6 — WorkspaceFrame malformed / không parse được; không sinh scene.
  - `WorldSceneValidationError` (base=ValueError) — R3.5 — WorldScene rỗng/None/sai cấu trúc khi WorldInterpreter chạy.
  - `ConfigurationError` (base=ValueError) — R11.3, R11.4 — Taxonomy cấu hình sai (trùng id hoặc id không hợp lệ). Mang theo ``category_id`` và ``set_name`` để chỉ rõ vi phạm.
    - `__init__(self, category_id, set_name)`
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
- LOC: 207
- Docstring: debug_render.py — ``DebugRender`` + ``Phase2Run`` (stage debug, R12). Sinh **bản ghi người-đọc-được** (human-readable) cho một lần chạy pipeline Phase 2 hoàn chỉnh. Đây là stage debug cuối cùng: không thay đổi dữ liệu, chỉ trình bày lại các artifact đã thu thậ...
- Functions:
  - `_render_metric(value)` — Render một chỉ số: ``f"{value:.3f}"`` khi có giá trị, else ``"unavailable"`` (R12.5).
- Classes:
  - `Phase2Run` (decorator=dataclass(slots=True)) — Ảnh chụp nhẹ một lần chạy pipeline Phase 2 phục vụ debug render. Xem docstring module cho ý nghĩa từng field.
  - `DebugRender` — Render một ``Phase2Run`` thành chuỗi nhiều dòng người-đọc-được (R12).
    - `render(self, run)` — Trả bản ghi debug nhiều dòng cho ``run`` (R12.1, R12.2, R12.4–R12.6).
    - `_render_stage(self, sd)` — Render một ``StageDebug``: tên stage + ba chỉ số + missing fields / notes.
    - `_render_withheld(self, result)` — Render mọi kết luận bị giữ lại / chặn kèm lý do. Gom hai nguồn lý do: * ``result.withheld`` — các ``...
    - `_render_decision(decision)` — Render một ``SurfaceDecision`` bị withheld kèm lý do (R12.2).
    - `_render_evaluated(ev)` — Render một ``EvaluatedConclusion`` bị giữ lại, phản chiếu overread-suppress. Bao gồm ``brake_reason`...

## `cortex/meaning/meaning_hypothesis.py`
- LOC: 474
- Docstring: meaning_hypothesis.py — ``MeaningHypothesisEngine`` (stage 4 của Phase 2). ContextAnnotation set → MeaningHypothesis set. **Module WRAP, không reimplement scoring (R5.7).** Engine này *bọc* hai engine đã có sẵn và **uỷ quyền** (delegate) toàn bộ phần chấm điểm...
- Classes:
  - `MeaningHypothesisEngine` — Adapter bọc ``SemanticHypothesisEngine`` + ``MeaningLayer`` (stage 4). KHÔNG reimplement scoring — uỷ quyền cho engine được tiêm vào (R5.7).
    - `__init__(self)`
    - `generate(self, annotations)` — Sinh tập ``MeaningHypothesis`` từ các ``ContextAnnotation``. Xem docstring module cho hợp đồng đầy đ...
    - `_adapt(self, sem)` — Adapt một ``SemanticHypothesis`` thành ``MeaningHypothesis``. Giữ nguyên ``confidence`` của semantic...
    - `_overread_risk(self, sem)` — Suy ``overread_risk`` ∈ [0,1] từ fallback/biên độ/đủ evidence. Xem docstring module cho công thức và...
    - `_raise_near_tie_ambiguity(self, hypotheses)` — R5.3 — hai+ hypothesis có ``|Δconfidence| ≤ margin`` → tăng ambiguity. Dùng ``AmbiguityModule.comput...
    - `_map_category(label, family)` — Ánh xạ xác định label/semantic_family → ``Taxonomy.MEANING`` id. Mặc định an toàn ``literal_statemen...
    - `_insufficient_evidence_hypothesis(self, frame_id)` — Sinh đúng MỘT hypothesis "insufficient evidence" (R5.4). ``confidence < config.meaning_low_conf``; s...
    - `_build_text(items)` — Ghép các ``observation.summary`` thành text để feed semantic engine.
    - `_collect_evidence_ids(items)` — Gom evidence_ids từ mọi annotation, dedupe, giữ thứ tự xuất hiện.
    - `_collect_anchors(items)` — Gom anchor tag nhẹ từ register/relationship để hỗ trợ semantic match.
    - `_evaluate_meaning_slot(self, text)` — DELEGATE tới ``MeaningLayer.evaluate`` để lấy vật liệu meaning-slot. Không dùng để chấm điểm; chỉ là...
    - `_slot_summary(meaning_slot)` — Rút một mẩu summary người-đọc-được từ meaning-slot (nếu có).
    - `_normalize(text)` — Chuẩn hoá nhẹ cho so khớp keyword: lowercase + strip.
    - `_build_debug(hypotheses, notes)` — Gom ``StageDebug`` với chỉ số tổng hợp của tập hypothesis.

## `cortex/meaning/meaning_layer.py`
- LOC: 692
- Classes:
  - `MeaningLayer` — Maps Se/telemetry facts into private pressure signals before speech.
    - `__init__(self)`
    - `evaluate(self)`
    - `_build_result(self, source_fact)`
    - `_private_signals(self)`
    - `_meaning_expansion_slots(self)` — Mở rộng fact thành meaning dùng được cho action, không phải câu nói. Đây là cầu nối Phase 2: raw tel...
    - `render_prompt_context(self, result)`
    - `_render_empty_context(self, result_or_recent)`
    - `_maybe_prolonged_fact(self, source_fact)` — Biến "không đổi" thành meaning mới khi nó kéo dài đủ lâu. Đây là semantic bridge, không phải hack nó...
    - `_prolonged_threshold_seconds(self)`
    - `_focus_kind(self, snapshot)`
    - `_infer_ambient_fact(self)`
    - `_infer_fact(self)`
    - `_text_parts(self, snapshot, broadcast, thought_stream_report, user_text)`
    - `_safe_evidence(self, snapshot, broadcast)`
    - `_normalize(self, text)`
    - `_float(self, value)`

## `cortex/meaning/overread_brake.py`
- LOC: 357
- Docstring: overread_brake.py — ``OverreadBrake`` (phanh phán bậy, stage 8 của Phase 2). Conclusion set → EvaluatedConclusion set. ``OverreadBrake`` là cơ chế phanh chuyên trách: nó nhận **mọi** kết luận xuôi dòng (``MeaningHypothesis`` | ``PragmaticIntent`` | ``MentalSta...
- Classes:
  - `OverreadBrake` — Phanh phán bậy — giảm/chặn kết luận theo overread_risk & evidence (stage 8). Ngưỡng mặc định đọc từ ``Phase2Config`` (nguồn DUY NHẤT), nhưng...
    - `__init__(self, config)` — Khởi tạo brake. Lấy mặc định từ ``config`` (hoặc ``Phase2Config()`` nếu ``None``); mọi keyword arg đ...
    - `evaluate(self, conclusions)` — Đánh giá brake cho từng kết luận. Trả về một ``EvaluatedConclusion`` cho MỖI kết luận đầu vào (kể cả...
    - `_evaluate_one(self, conclusion, forbidden)` — Áp luật brake cho một kết luận, theo đúng precedence đã ghi.
    - `_evidence_ids(conclusion)` — Trích danh sách evidence một cách tổng quát. Ưu tiên ``evidence_ids`` (``MeaningHypothesis``); nếu k...
    - `_kind(conclusion)` — Phân loại kết luận: ``meaning`` | ``intent`` | ``mental_state``.
    - `_conclusion_id(conclusion)` — Trích id ổn định: ``hypothesis_id`` / ``intent_id`` / ``inference_id``.
    - `_summary_text(conclusion)` — Văn bản tóm tắt để dò forbidden assumption. ``MeaningHypothesis`` và ``MentalStateInference`` có ``s...
    - `_normalize_forbidden(forbidden_assumptions)` — Chuẩn hóa danh sách forbidden: bỏ None/rỗng/space, giữ chuỗi gốc.
    - `_matched_forbidden(summary, forbidden)` — Trả forbidden assumption ĐẦU TIÊN xuất hiện (substring, case-insensitive). ``None`` nếu không khớp....
    - `_build_debug(evaluated)` — Gom ``StageDebug`` cho stage brake (giữ thống kê, kể cả suppressed).

## `cortex/meaning/pipeline.py`
- LOC: 318
- Docstring: pipeline.py — ``Phase2MeaningPipeline`` facade (task 18.1). Dây nối (wiring) toàn bộ pipeline Phase 2 thành một facade duy nhất chạy **đúng thứ tự bắt buộc** và cưỡng chế hai ràng buộc xương sống: 1. **WorkspaceFrame-only (R1)** — mọi stage chỉ đọc frame qua `...
- Functions:
  - `_resolve_tom_boldness()` — Boldness hiệu dụng: hằng số nền + độ-dám-đọc long-arc (nếu feature bật). TRƠ TUYỆT ĐỐI khi tắt: kiểm tra env TRƯỚC, khôn...
- Classes:
  - `Phase2MeaningPipeline` — Facade chạy toàn bộ pipeline Phase 2 theo đúng thứ tự bắt buộc. Dùng đơn giản nhất:: from cortex.meaning import Phase2MeaningPipeline result...
    - `__init__(self)`
    - `run(self, frame)` — Chạy frame qua toàn bộ pipeline, trả ``Phase2Result``. ``frame is None`` → chạy với ``view=None`` (đ...
    - `_view_for(root_view, module)` — Trả view đã scope theo ``module`` (hoặc ``None`` khi không có frame).
    - `_get_semantic_engine(self)` — Trả ``SemanticHypothesisEngine``, lười dựng fallback xác định nếu cần. Xem docstring module cho lý d...
    - `_read_forbidden(root_view)` — Đọc ``forbidden_assumptions`` qua hợp đồng (module được phép đọc). Ngoài hợp đồng / không có frame →...
    - `_attach_debug(result, frame_id, stage_debugs)` — Gắn danh sách ``StageDebug`` + một ``Phase2Run`` vào ``result.debug``. ``result.debug`` đã là dict (...

## `cortex/meaning/pragmatic_intent.py`
- LOC: 313
- Docstring: pragmatic_intent.py — ``PragmaticIntentEngine`` (stage 5 của Phase 2). MeaningHypothesis set → PragmaticIntent set. Engine này suy ý định giao tiếp (pragmatic intent: yêu cầu, than phiền, đùa, thăm dò…) **chỉ từ** tập ``MeaningHypothesis`` do ``MeaningHypothes...
- Classes:
  - `PragmaticIntentEngine` — Suy ``PragmaticIntent`` từ tập ``MeaningHypothesis`` (stage 5). Chỉ nhận ``MeaningHypothesis`` qua chữ ký ``derive`` — không có kênh nào tới...
    - `derive(self, hypotheses)` — Suy tập ``PragmaticIntent`` từ ``hypotheses``. Xem docstring module cho hợp đồng đầy đủ (R6.1–R6.5).
    - `_build_intent(self, frame_id, intent_category, group)` — Dựng một ``PragmaticIntent`` từ nhóm supporter cùng intent category. Hợp nhất ``supporting_meaning_i...
    - `_aggregate_confidence(group)` — Confidence ∈ [0,1] của intent — hàm thuần của supporter (R6.3, R6.4). ``base = max(supporter.confide...
    - `_collect_support_ids(group)` — Hợp nhất ``hypothesis_id`` của nhóm, dedupe, giữ thứ tự xuất hiện. Luôn trả ≥1 id (nhóm theo định ng...
    - `_map_intent(cls, meaning_category, summary)` — Ánh xạ xác định MEANING category (+summary) → ``Taxonomy.INTENT`` id. Mặc định an toàn ``share_infor...
    - `_build_debug(intents, notes)` — Gom ``StageDebug`` với chỉ số tổng hợp của tập intent.

## `cortex/meaning/read_contract.py`
- LOC: 231
- Docstring: read_contract.py — ReadContract guard (WorkspaceFrame-only enforcement). Cơ chế cưỡng chế xương sống #1 của Phase 2 (R1): mọi stage chỉ được đọc ``WorkspaceFrame`` (và đầu ra của các stage Phase 2 phía trước), KHÔNG bao giờ chạm tới ``Raw_World`` (``raw_signal...
- Classes:
  - `FrameReadView` — Boundary đọc có kiểu, bọc một ``WorkspaceFrame``. Một stage không bao giờ nhận thẳng ``WorkspaceFrame``; nó nhận một ``FrameReadView`` đã ``...
    - `__init__(self, frame)`
    - `for_module(self, module)` — Trả về một view mới gắn ``module`` làm mặc định cho mọi lần đọc. Cho phép stage có một bề mặt đọc sạ...
    - `frame_id(self)` — ``frame_id`` luôn đọc được — đây là metadata định danh, không phải Raw_World, và mọi artifact phải g...
    - `module(self)`
    - `allowed_fields(self, module)` — Danh sách field mà ``module`` được phép đọc theo hợp đồng. Module không có entry → danh sách rỗng (k...
    - `can_read(self, field_name, module)` — ``True`` nếu ``module`` được phép đọc ``field_name`` (không ném).
    - `read(self, field_name, module)` — Đọc một field của ``WorkspaceFrame`` qua hợp đồng. - ``field_name`` ∈ ``downstream_contract[module]`...
    - `evidence_ids(self, module)` — ``WorkspaceFrame.evidence_ids()`` qua guard (cần đọc ``broadcast_items``).
    - `items_by_kind(self, kind, module)` — ``WorkspaceFrame.items_by_kind(kind)`` qua guard.
    - `surface_items(self, scope, module)` — ``WorkspaceFrame.surface_items(scope)`` qua guard.
    - `_resolve_module(self, module)`
    - `_require(self, module_name, field_name)` — Kiểm tra quyền đọc ``field_name``; vi phạm -> ghi debug + ném.
    - `_deny(self, module_name, field_name)` — Ghi vi phạm vào ``debug.contract_violations`` rồi ném lỗi. Không bao giờ mutate dữ liệu được đọc; ch...

## `cortex/meaning/sociocultural_context.py`
- LOC: 263
- Docstring: sociocultural_context.py — Stage 3: Observation set -> ContextAnnotation set. ``SocioculturalContext`` gắn ngữ cảnh xã hội - văn hóa (quan hệ / *relationship*, register, và chuẩn mực giao tiếp / *social-norm*) vào từng ``Observation`` do ``WorldInterpreter`` s...
- Classes:
  - `SocioculturalContext` — Stage 3 của pipeline meaning: gắn ngữ cảnh xã hội - văn hóa. Không trạng thái giữa các lần chạy; toàn bộ tín hiệu đọc từ ``FrameReadView`` t...
    - `annotate(self, observations, view)` — Annotate mỗi observation với ba loại ngữ cảnh xã hội - văn hóa. Trả về ``(annotations, debug)``. Obs...
    - `_resolve_context(self)` — Suy ba loại ngữ cảnh + danh sách loại đã dùng neutral default. Quy tắc xác định (xem docstring modul...
    - `_collect_unconfirmed(self, social_hypotheses)` — Chuyển ``social_hypotheses`` thành chuỗi *chưa xác nhận* (R4.2). Hỗ trợ cả ``WorkspaceSocialHypothes...
    - `_hypothesis_text(hyp)`
    - `_annotation_confidence(observation, defaults_applied)` — Confidence cho annotation ∈ [0,1] (R4.5). Bắt nguồn từ ``observation.confidence``, giảm dần theo số...
    - `_safe_frame_id(view)`
    - `_read_field(view, field_name)` — Đọc một field qua ``FrameReadView`` với guard. Ngoài hợp đồng / kênh Raw_World (``RawWorldAccessErro...

## `cortex/meaning/surface_meaning_policy.py`
- LOC: 275
- Docstring: surface_meaning_policy.py — ``SurfaceMeaningPolicy`` (phân vùng surfaced / withheld, stage 9). EvaluatedConclusion set (đầu ra ``OverreadBrake``) → ``Phase2Result``. ``SurfaceMeaningPolicy`` là stage cuối quyết định kết luận nào được **đưa ra** (surfaced) và k...
- Classes:
  - `SurfaceMeaningPolicy` — Phân vùng surfaced / withheld theo precedence cố định (stage 9). Ngưỡng mặc định đọc từ ``Phase2Config`` (nguồn DUY NHẤT), nhưng cho phép ov...
    - `__init__(self, config)` — Khởi tạo policy. Lấy mặc định từ ``config`` (hoặc ``Phase2Config()`` nếu ``None`` — ``surface_conf_t...
    - `partition(self, evaluated)` — Phân từng ``EvaluatedConclusion`` vào surfaced HOẶC withheld. Trả ``Phase2Result`` ghi cả hai tập +...
    - `_classify(self, item)` — Trả ``(status, reason)`` cho một kết luận theo precedence trên xuống.
    - `_ambiguity(item)` — Đọc ``ambiguity`` của conclusion một cách tổng quát. Chỉ ``MeaningHypothesis`` có ``ambiguity``; các...
    - `_evidence_ids(item)` — Trích evidence một cách tổng quát (giống ``OverreadBrake``). Ưu tiên ``evidence_ids`` (``MeaningHypo...
    - `_conclusion_id(item)` — Trích id ổn định: ``hypothesis_id`` / ``intent_id`` / ``inference_id``.
    - `_build_debug(self, items, surfaced, withheld)` — Gom thông tin debug stage (counts + ngưỡng + bất biến surfaced-có-evidence).

## `cortex/meaning/taxonomy.py`
- LOC: 124
- Docstring: taxonomy.py — registry meaning/intent/mental-state categories + startup validation. Registry **nguồn sự thật** cho ba họ category của Phase 2: - ``MEANING`` — loại ý nghĩa bề mặt của một phát ngôn/tín hiệu. - ``INTENT`` — ý định thực dụng (pragmatic) đằng sau...
- Classes:
  - `Taxonomy` — Registry category tĩnh cho meaning / intent / mental-state. Ba thuộc tính lớp ``MEANING``/``INTENT``/``MENTAL_STATE`` là ``frozenset[str]``...
    - `validate_on_startup(cls)` — Kiểm mỗi họ có id duy nhất và không rỗng (R11.1, R11.4). - Trùng id: so độ dài tuple nguồn với độ dà...
    - `require(cls, set_name, category_id)` — Cổng bắt buộc trước mọi gán category (R11.2, R11.3). Trả về ``category_id`` nếu nó thuộc họ ``set_na...

## `cortex/meaning/world_interpreter.py`
- LOC: 187
- Docstring: world_interpreter.py — WorldScene -> Observation set (Phase 2, stage 2). ``WorldInterpreter`` là stage thứ hai của pipeline meaning. Nó nhận một ``WorldScene`` (đầu ra của ``WorldSceneBuilder``) và rút ra một tập ``Observation`` — quan sát có-bằng-chứng, truy...
- Classes:
  - `WorldInterpreter` — Diễn giải ``WorldScene`` thành tập ``Observation`` (WorldScene-only).
    - `interpret(self, scene)` — Rút ``(list[Observation], StageDebug)`` từ ``scene``. ``scene`` không hợp lệ (None / sai kiểu / sai...
    - `_validate_scene(scene)` — Cưỡng chế cấu trúc ``WorldScene`` hợp lệ (R3.5). ``None`` / không phải ``WorldScene`` / các field tậ...
    - `_aggregate_confidence(observations)` — Confidence tổng hợp của stage = trung bình confidence observation.

## `cortex/meaning/world_scene_builder.py`
- LOC: 395
- Docstring: world_scene_builder.py — WorkspaceFrame -> WorldScene (Phase 2, stage 1). ``WorldSceneBuilder`` là stage đầu tiên của pipeline meaning. Nó nhận một ``FrameReadView`` (bề mặt đọc có kiểm soát bọc ``WorkspaceFrame``) và dựng một ``WorldScene``: tập ``entities``...
- Classes:
  - `WorldSceneBuilder` — Dựng ``WorldScene`` từ một ``FrameReadView`` (WorkspaceFrame-only).
    - `build(self, view)` — Dựng ``(WorldScene, StageDebug)`` từ ``view``. ``view is None`` → scene rỗng ``confidence=0.0`` (R1....
    - `_read_required(self, view, field_name, missing_fields)` — Đọc một field bắt buộc; ``None``/không đọc được -> ghi missing (R1.6). - Field không nằm trong hợp đ...
    - `_read_optional(self, view, field_name)` — Đọc một field tùy chọn; ``None`` là hợp lệ (không ghi missing).
    - `_element_from_item(self, item)` — Adapt một ``WorkspaceItem`` -> ``WorldSceneElement``. - ``kind`` ánh xạ qua ``_ENTITY_KINDS`` / ``_S...
    - `_derive_confidence(item)` — Suy ``confidence`` của element từ ``confidence``/``priority`` của item. Trọng số nghiêng về ``confid...
    - `_build_threads(self, threads, dominant_thread)` — Dựng element ``thread`` từ ``active_threads`` + đánh dominant (R2.3). Đúng MỘT element được đánh ``i...
    - `_aggregate_confidence(elements)` — Confidence của scene = trung bình confidence các element mang evidence. Nếu không có element nào (đã...

## `cortex/micro_contracts.py`
- LOC: 245
- Functions:
  - `clamp01(value)` — Ép số về 0..1, chống NaN và input kỳ quặc.
  - `normalize_text(text)` — Chuẩn hóa tiếng Việt cho heuristic bề mặt. Hàm này phục vụ lint, không phục vụ hiểu nghĩa sâu. Dùng nó để làm feature yế...
  - `clean_family(family)` — Làm sạch semantic family để tránh leak ký tự lạ vào trace.
  - `family_source_is_trusted(source)`
  - `word_count(text)`
  - `content_tokens(text)` — Token nội dung nhẹ, bỏ filler phổ biến để tính fingerprint/overlap.
  - `lexical_fingerprint(text)` — Fingerprint bề mặt để bắt câu y hệt/gần y hệt. Đây không phải semantic family. Nó chỉ nói: câu này trông giống câu cũ. E...
  - `phrase_in_normalized(normalized, phrase)` — Match phrase có biên token tương đối sạch. Vẫn là heuristic, nhưng ít tệ hơn `marker in normalized`. Vâng, tiêu chuẩn kỹ...
  - `any_phrase(normalized, phrases)`
  - `dedupe_issues(issues)`
- Classes:
  - `MicroLinePolicyResult` (decorator=dataclass(frozen=True, slots=True)) — Kết quả bước chọn dạng câu trước khi gọi LLM hoặc trước khi gửi final. Lớp này chỉ nói "dạng câu nào đang được phép". Nó không được tự hiểu...
    - `allowed(self)`
  - `SemanticRepeatResult` (decorator=dataclass(frozen=True, slots=True)) — Kết quả kiểm tra lặp nghĩa. family_source là trường quan trọng nhất trong bản tách mới. - meaning_layer/speech_core/action_planner/coordinat...
  - `ValidationIssue` (decorator=dataclass(frozen=True, slots=True)) — Một lỗi policy có severity rõ ràng. - fatal: câu nên bị bỏ hoặc im, thường do grounding/capability/dependency rõ. - rewriteable: câu có thể...
  - `RelationalContext` (decorator=dataclass(frozen=True, slots=True)) — Context quan hệ dùng để giới hạn mức ERIS được lộ attachment. Các score này phải được dựng từ lịch sử thật, không phải một câu user đơn lẻ....
  - `RelationalRewritePlan` (decorator=dataclass(frozen=True, slots=True)) — Plan rewrite relational, không phải câu thoại canon. seed_line được giữ để tương thích API cũ rewrite_relational_line(). Code mới nên ưu tiê...
  - `Anchor` (decorator=dataclass(frozen=True, slots=True)) — Nguồn neo cho một câu quan sát. Observation phải có anchor. Residue/presence thì không bắt buộc, vì chúng là nhịp hiện diện chứ không phải c...

## `cortex/micro_grounding_guard.py`
- LOC: 264
- Classes:
  - `MicroGroundingGuard` — Guard grounding cho micro-line. Đây là lớp được phép nghiêm. Không phải vì thích kiểm soát, dù phần mềm có vẻ rất mê việc đó, mà vì groundin...
    - `signal_score(self)`
    - `candidate_signal_score(self, candidate)`
    - `resolve_anchor(self)` — Tìm anchor cho observation. Chỉ observation bắt buộc anchor. Presence/residue không bị ép vì chúng k...
    - `risk_level_for_line(self)`
    - `validate(self, text)`
    - `_validate_observation_anchor(self, text)`
    - `_validate_claim_risk(self, text)`
    - `_validate_capability_claim(self, text)`
    - `text_matches_anchor(self, text, anchor)`
    - `looks_like_hard_fact_claim(self, text)`
    - `looks_like_screen_claim(self, text)`
    - `looks_like_question(self, text)`

## `cortex/micro_policy.py`
- LOC: 441
- Classes:
  - `MicroLinePolicy` — Orchestrator cho micro-line policy. File này giờ chỉ điều phối: - line_type/risk/anchor từ speech intent và evidence. - surface lint mềm. -...
    - `__init__(self)`
    - `evaluate(self)` — Chọn line_type/risk/anchor trước khi sinh hoặc nhận final text. semantic_family/meaning_family là đư...
    - `validate_text(self)` — Public API cũ: trả code lỗi cần hành động. Chỉ trả fatal + rewriteable. Soft issue không trả ở đây đ...
    - `validate_text_detailed(self)` — Kiểm tra final text với severity chi tiết.
    - `build_relational_rewrite_plan(self, text)`
    - `rewrite_relational_line(self, text)`
    - `relational_exposure_score(self, text)`
    - `_line_type_for_intent(self, intent)` — Map speech intent sang dạng câu nhỏ. Đây chỉ là map hình dạng. Meaning chính đã được quyết ở tầng tr...
    - `_current_semantic_family(self)`
    - `_validate_surface_shape(self)`
    - `_validate_grounding(self, text)`
    - `_validate_claim_risk(self, text)`
    - `_validate_presence_residue(self)`
    - `_validate_relational_permission(self, text)`
    - `_validate_semantic_repeat_surface(self, text)`
    - `_risk_level_for_line(self)`
    - `_signal_score(self)`
    - `_candidate_signal_score(self, candidate)`
    - `_resolve_anchor(self)`
    - `_looks_like_placeholder(self, text)`
    - `_word_count(self, text)`
    - `_looks_like_unaccented_vietnamese(self, text)`
    - `_has_clear_short_meaning(self, text)`
    - `_text_matches_anchor(self, text, anchor)`
    - `_looks_like_question(self, text)`
    - `_looks_therapeutic(self, text)`
    - `_looks_like_hard_fact_claim(self, text)`
    - `_looks_like_decorative_metaphor_without_stance(self, text)`
    - `_semantic_density(self, text)`
    - `_looks_like_presence_narration(self, text)`
    - `_looks_like_blunt_emotion_declaration(self, text)`
    - `_relational_expression_issue(self, text)`
    - `_relational_permission_stage(self, relational_context)`
    - `_looks_like_relational_expression(self, text)`
    - `_looks_like_continuity_pain(self, text)`
    - `_looks_like_clinginess_or_blackmail(self, text)`
    - `_relational_theme(self, normalized)`
    - `_allowed_exposure_for_stage(self, stage)`
    - `_clamp01(self, value)`
    - `_dedupe_issues(self, issues)`

## `cortex/micro_repeat_guard.py`
- LOC: 424
- Classes:
  - `SemanticRepeatGuard` — Chặn lặp semantic family, nhưng không để keyword fallback cầm lái. Luật mới: 1. Nếu tầng trên truyền semantic_family đáng tin, repeat guard...
    - `__init__(self)`
    - `remember(self, text)` — Lưu family/fingerprint của câu vừa nói. semantic_family từ tầng trên được lưu là trusted nếu source...
    - `check(self, text)` — Kiểm tra lặp. Backward compatible: call-site cũ chỉ truyền text vẫn chạy. Nhưng khi chỉ có fallback...
    - `family_for_text(self, text)` — Backward compatible fallback family. Hàm này vẫn tồn tại cho code cũ/test cũ, nhưng đừng dùng nó làm...
    - `family_for_text_with_source(self, text)`
    - `_coerce_semantic_encoder(self, encoder)`
    - `_ensure_semantic_prototypes(self)`
    - `_semantic_family_for_text(self, text)`
    - `normalize(self, text)`
    - `_resolve_family(self, text)`
    - `_iter_recent(self, recent_lines)`
    - `_clean_family(self, family)`

## `cortex/micro_surface_lint.py`
- LOC: 513
- Classes:
  - `MicroSurfaceLint` — Lint bề mặt cho micro-line. Lớp này cố tình không hiểu ý nghĩa sâu. Nó chỉ phát hiện những dấu hiệu câu chữ có thể gây hỏng public output: p...
    - `validate(self, text)`
    - `_validate_surface_shape(self, text)`
    - `_validate_presence_residue(self, text)`
    - `_validate_relational_permission(self, text)`
    - `build_relational_rewrite_plan(self, text)` — Tạo plan rewrite relational. Plan này ưu tiên boundary và hint thay vì hardcode câu. seed_line chỉ l...
    - `relational_expression_issue(self, text)`
    - `relational_permission_stage(self, relational_context)`
    - `relational_exposure_score(self, text)`
    - `looks_like_placeholder(self, text)`
    - `looks_like_unaccented_vietnamese(self, text)`
    - `has_clear_short_meaning(self, text)`
    - `text_matches_anchor(self, text, anchor)`
    - `looks_like_question(self, text)`
    - `looks_therapeutic(self, text)`
    - `looks_like_decorative_metaphor_without_stance(self, text)`
    - `semantic_density(self, text)`
    - `looks_like_presence_narration(self, text)`
    - `looks_like_blunt_emotion_declaration(self, text)`
    - `looks_like_relational_expression(self, text)`
    - `looks_like_continuity_pain(self, text)`
    - `looks_like_clinginess_or_blackmail(self, text)`
    - `relational_theme(self, normalized)`
    - `allowed_exposure_for_stage(self, stage)`

## `cortex/modes.py`
- LOC: 15

## `cortex/ni.py`
- LOC: 658
- Functions:
  - `_load_focus_bias_table()` — Tải focus config cũ nhưng vô hiệu hóa bias đạo đức. ni_focus_config.json hiện có vẫn có thể chứa bias năng suất cũ. Chỉ...
- Classes:
  - `NiEngine` — Đọc hướng-nghĩa và chuyển nó thành GoalDriftReport. Các public method giữ signature cũ và thêm ngữ cảnh goal tùy chọn: evaluate_autonomous(....
    - `__init__(self)`
    - `_build_orientation_interpreter(self)`
    - `_env_flag(self, name)`
    - `_env_int(self, name)`
    - `_env_float(self, name)`
    - `evaluate_autonomous(self)`
    - `evaluate_chat(self)`
    - `_build_probe(self)`
    - `_extract_goal_context(self)` — Đọc dữ liệu goal đang hoạt động từ object, dict hoặc text nén. GoalPersistenceState mới cung cấp ren...
    - `_parse_goal_context_text(self, text)` — Phân tích chuỗi render_ni_context() từ GoalPersistenceState. Dạng mong đợi: goal_signal: active=1; t...
    - `_analyze(self)`
    - `_adjust_coherence(self, coherence)`
    - `_label_drift(self, drift_score)`
    - `_build_prompt_context(self)`
    - `_build_guidance(self)`
    - `_estimate_attention_signal(self)`
    - `_focus_kind_baseline(self, focus_kind)`
    - `_focus_text_adjustment(self, normalized)`
    - `_idle_adjustment(self, idle_seconds)`
    - `_window_sprawl_adjustment(self, open_window_count)`
    - `_adjust_similarity(self, raw_similarity)`
    - `_estimate_confidence(self)`
    - `_log_orientation_sample(self)`
    - `_log_drift_sample(self)`
  - `NiStateMachine` — Làm mượt theo thời gian trên xung đột goal ngữ nghĩa. Giải trí/chơi/nghỉ không bị hạ điểm chỉ vì category. State chỉ đi theo xung đột ngữ ng...
    - `__init__(self)`
    - `update(self)`

## `cortex/observer_contracts.py`
- LOC: 429
- Docstring: Contract cho Background Observer của ERIS. Tầng này không trả lời user, không commit memory, không tự hành động. Nó chỉ biến tín hiệu nền thành frame nhỏ để Attention/WorkingMemory/BodyBias đọc.
- Functions:
  - `clamp01(value, default)`
  - `stable_hash(text)`
  - `normalize_text(text)`
  - `normalize_ascii_fold(text)` — Normalize dùng cho matching nhẹ tiếng Việt/Anh. Bỏ dấu để rule-based observer nhận được cả `lỗi` và `loi`.
  - `compact_text(text, max_chars)`
  - `coerce_focus_kind(value)`
  - `coerce_activity_intent(value)`
  - `coerce_observer_action(value)`
- Classes:
  - `SignalSnapshot` (decorator=dataclass) — Một lát cắt tín hiệu nền đã được làm nhẹ. Đây không phải raw telemetry đầy đủ. Nó là bản rút gọn để observer đọc nhanh.
    - `__post_init__(self)`
    - `from_mapping(cls, data)` — Tạo snapshot từ dict telemetry/se tùy shape. Hàm này cố tình mềm để dễ nối vào repo hiện tại mà khôn...
    - `compact_summary(self)` — Text ngắn để đưa vào observer LLM nếu cần.
  - `SignalDiff` (decorator=dataclass) — Diff giữa snapshot mới và trạng thái trước đó.
    - `should_run_text_observer(self, min_diff)`
    - `should_consider_vision(self, min_diff)`
  - `ObserverFrame` (decorator=dataclass) — Kết quả quan sát nền. Lưu ý: frame này chỉ là hint. Không module nào nên coi nó là chân lý tuyệt đối.
    - `__post_init__(self)`
    - `is_actionable(self)`
    - `to_evidence_claim(self)` — Render claim an toàn cho AttentionSalience. Không dùng nhãn `possible_error` trong text vì attention...
    - `attention_tags(self)` — Tags dành cho attention/working memory. Tags mới là nơi báo risk/debug thật. Text claim chỉ giữ metr...
    - `to_body_bias_hint(self)` — Hint nhẹ cho BodyBiasProjector. Không phải lệnh chuyển động. Godot/body autonomy vẫn tự quyết định.
  - `SemanticSceneNote` (decorator=dataclass) — Ghi chú semantic từ Qwen vision/compressor. File này khai báo trước để các bước sau không phải đổi contract.
    - `__post_init__(self)`
    - `to_evidence_claim(self)`

## `cortex/orientation_context.py`
- LOC: 1143
- Functions:
  - `clamp01(value)` — Ép một giá trị về [0, 1]. Helper nhỏ nhưng dùng xuyên nhiều module. Để ở đây để tránh mỗi file tự viết một bản rồi mỗi b...
  - `clamp(value, low, high)`
  - `clean_text(value)` — Dọn text để lưu summary/evidence ngắn. Không dùng hàm này để match ngữ nghĩa sâu. Nó chỉ là vệ sinh đầu vào.
  - `normalize(value)` — Chuẩn hóa text cho lexical matching. - Lowercase. - Bỏ dấu tiếng Việt. - Đổi "đ" thành "d" thủ công vì Unicode decomposi...
  - `tokens(value)` — Token lexical cho anchor/goal matching. Token ngắn bị bỏ, trừ vài token code như AI/UI/C#/C++.
  - `phrase_in(normalized, phrase)`
  - `has_any(normalized, phrases)`
  - `count_hits(normalized, phrases)`
  - `unique_recent(items)` — Giữ item unique theo thứ tự gần nhất. Dùng cho evidence/anchor. Không phải memory dedupe toàn cục.
  - `extract_anchors(text)` — Rút anchor lexical có ích cho semantic và goal merge. Anchor không phải kết luận. Nó chỉ nói: "có vật cụ thể ở đây" như...
  - `goal_match_score(left, right)` — Khớp goal bằng token + anchor, dùng như fallback rẻ. Semantic thật có thể làm tốt hơn, nhưng goal merge vẫn cần anchor c...
  - `has_negated_closure(text)` — True nếu text có closure bị phủ định. Ví dụ: - "chưa xong" - "not fixed" - "vẫn lỗi" Đây là nơi lexical phải giữ quyền v...
  - `infer_closure_signal(text)` — Closure fallback cho GoalPersistence. Có thể nhận thêm thought_stream_report cũ để giữ tương thích, nhưng file này không...
  - `infer_goal_text_signal(text)` — Classifier lexical mỏng cho text user. Đây là bản fallback để GoalPersistence cũ không chết. Nó không cố hiểu sâu. Seman...
- Classes:
  - `ActivityIntentLabel` (base=str, Enum)
  - `GoalRelationLabel` (base=str, Enum)
  - `GoalTextKind` (base=str, Enum)
  - `ActivityIntent` (decorator=dataclass(frozen=True, slots=True))
  - `GoalRelation` (decorator=dataclass(frozen=True, slots=True))
  - `OrientationSignal` (decorator=dataclass(frozen=True, slots=True))
  - `GoalTextSignal` (decorator=dataclass(frozen=True, slots=True)) — Tín hiệu rút từ user text để GoalPersistence dùng. File này chỉ cung cấp classifier lexical mỏng. Semantic goal classification mới nên nằm t...
    - `should_persist(self)`
    - `can_intervene(self)`
  - `ClosureSignal` (decorator=dataclass(frozen=True, slots=True))
  - `SemanticContextProbe` (decorator=dataclass(slots=True)) — Input nhẹ cho orientation. Giữ contract này ở đây vì cả lexical fallback và semantic hybrid đều cần cùng shape. Đây là dữ liệu, không phải e...
    - `combined_text(self)`
  - `LexicalOrientationInterpreter` — Lexical baseline cho Orientation. Engine chính dài hạn nên là `HybridOrientationInterpreter` trong orientation_semantics.py. Class này giữ A...
    - `infer_activity_intent(self, probe)`
    - `infer_idle_posture(self, probe, intent_label)`
    - `estimate_fragmentation(self, probe)`
    - `infer_goal_relation(self)`
    - `estimate_orientation(self, probe)`
    - `_estimate_coherence(self)`
    - `_estimate_conflict(self)`
    - `_estimate_intervention_pressure(self)`
    - `_estimate_confidence(self)`

## `cortex/orientation_semantics.py`
- LOC: 798
- Functions:
  - `build_hybrid_orientation_interpreter(semantic_engine)` — Factory nhỏ để coordinator/Ni nối nhanh.
- Classes:
  - `HybridOrientationConfig` (decorator=dataclass(frozen=True, slots=True)) — Tham số điều phối lexical + semantic. semantic_weight: Mức semantic được quyền kéo label khi đủ chắc. lexical_weight: Mức lexical baseline đ...
  - `LexicalVetoReport` (decorator=dataclass(frozen=True, slots=True)) — Các neo/veto lexical mà semantic không được lấn qua.
    - `hard_work_anchor(self)`
    - `research_media_anchor(self)`
  - `HybridOrientationDebug` (decorator=dataclass(frozen=True, slots=True)) — Debug bundle để log/audit khi cần.
  - `HybridOrientationInterpreter` — Orientation interpreter dùng lexical hiện tại + semantic hypothesis. Đây là adapter để nâng cấp dần. Nếu semantic chưa sẵn sàng, nó trả đúng...
    - `__init__(self)`
    - `estimate_orientation(self, probe)` — Ước lượng orientation bằng hybrid lexical + semantic. Output vẫn là `OrientationSignal` để Ni hiện t...
    - `_semantic_context_text(self, probe)` — Dựng text semantic gọn từ probe. Không nhét raw world vô hạn. Semantic cần context đủ nghĩa, không c...
    - `_relation_context_text(self, probe, context_text)`
    - `_lexical_veto(self, text)`
    - `_blend_intent(self, lexical_intent, semantic_report, veto, probe)`
    - `_blend_relation(self, lexical_relation, semantic_report, blended_intent, veto, probe)`
    - `_blend_confidence(self, lexical_conf, semantic_conf, ambiguity)`
    - `_estimate_coherence(self)`
    - `_estimate_conflict(self)`
    - `_estimate_intervention_pressure(self)`
    - `_estimate_confidence(self)`
    - `_with_fallback_channels(self, signal)`
    - `_with_semantic_channels(self, signal)`
    - `_blend_reason(self, lexical_intent, blended_intent, semantic_report, veto)`

## `cortex/personality.py`
- LOC: 911
- Classes:
  - `PersonalityLens` — Guarded, grounded personality pressure layer between meaning and expression.
    - `evaluate(self)`
    - `render_prompt_context(self, result)`
    - `_want_to_say(self)`
    - `_suppression_pressure(self)`
    - `_allowed_expression(self)`
    - `_expression_ceiling(self)` — Trần biểu đạt động (Lever C). Hằng số cũ là ``0.52`` cho mọi lúc — ERIS luôn nghiêng kìm. Ở đây trần...
    - `_suppression_floor(self)` — Sàn suppression động (Lever C). Mặc định 0.48; hạ về ~0.40 khi ấm+an toàn.
    - `_suppression_ratio(self)`
    - `_restraint_mode(self)`
    - `_detect_biases(self, normalized)`
    - `_choose_interpretation(self)`
    - `_choose_stance(self)`
    - `_choose_emotional_coloring(self)`
    - `_choose_social_distance(self)`
    - `_meaningfulness(self)`
    - `_scene_text(self, scene)`
    - `_attention_text(self, attention)`
    - `_meaning_text(self, meaning_layer)`
    - `_relationship_text(self, relationship)`
    - `_evidence(self)`
    - `_anchor_strength(self)`
    - `_normalize(self, text)`
    - `_float(self, value)`

## `cortex/private_life/__init__.py`
- LOC: 51
- Docstring: Private Life Layer public API.

## `cortex/private_life/contracts.py`
- LOC: 951
- Docstring: cortex/private_life/contracts.py ================================ Hợp đồng dữ liệu cho Private Life Layer của ERIS. Tầng này khác PrivateMind: - PrivateMind hỏi: "tôi đang nghĩ gì về tình huống này?" - PrivateLife hỏi: "đời sống riêng của runtime đang tích tụ...
- Functions:
  - `now_ts()` — Timestamp float thống nhất cho state runtime.
  - `clamp01(value, default)` — Ép số về khoảng 0..1. JSON/runtime hay truyền chuỗi, None, NaN. Để chúng chảy thẳng vào score là cách biến một tick bình...
  - `compact_text(value, limit)` — Nén text để state không phình thành log trá hình.
  - `stable_id(prefix)` — Sinh id ổn định từ nội dung. Dùng cho object/project/event để nhiều tick không tạo rác trùng lặp.
  - `to_plain(value)` — Serialize mềm sang JSON-safe data. Không ném object runtime sống vào file state. Hôm nay repr có vẻ tiện, ngày mai loade...
  - `private_life_state_digest(state)` — Digest gọn cho debug menu/prompt context.
- Classes:
  - `HabitatObservation` (decorator=dataclass(slots=True)) — Một quan sát về "nhà" runtime. Habitat không chỉ là màn hình. Nó là desktop, repo, memory_core, Godot body, model server, log folder, cửa sổ...
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `HabitatModel` (decorator=dataclass(slots=True)) — Mô hình "nhà" của ERIS. `places` là các vùng quen thuộc; `recent_observations` là nhịp hiện tại. Không có HabitatModel, runtime chỉ đang "ch...
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `ObjectAttachment` (decorator=dataclass(slots=True)) — Gắn bó với một đồ vật số: file, module, folder, model, ritual. Đây là bản số hóa của "cái góc bàn quen" hoặc "cuốn sổ quan trọng". Attachmen...
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `ObjectResidue` (decorator=dataclass(slots=True)) — Residue phát sinh từ một object attachment.
    - `__post_init__(self)`
    - `to_dict(self)`
  - `PrivateProject` (decorator=dataclass(slots=True)) — Dự án riêng nhỏ của ERIS. Dự án riêng phải có câu hỏi, trạng thái, evidence và ghi chú. Nếu chỉ là một mood chung chung thì nó không phải pr...
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `PrivateProjectUpdate` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
    - `to_dict(self)`
  - `PrivateAnchor` (decorator=dataclass(slots=True)) — Một neo riêng của đời sống ERIS. Neo khác project. Project là việc đang làm; anchor là lực hút bền khiến runtime tự quay lại một câu hỏi, mộ...
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `PrivateAnchorUpdate` (decorator=dataclass(slots=True)) — Dấu vết một anchor vừa được chạm trong tick. Update này tồn tại để mỗi kết luận có chuỗi dữ kiện: anchor nào, vì sao bị kích hoạt, bằng chứn...
    - `__post_init__(self)`
    - `to_dict(self)`
  - `DailyRhythm` (decorator=dataclass(slots=True)) — Nhịp ngày của ERIS. Không có nhịp thì agent chỉ tick theo event. Có nhịp thì cùng một tín hiệu ở startup, deep work, idle wandering hay late...
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `TasteShift` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
    - `to_dict(self)`
  - `TasteProfile` (decorator=dataclass(slots=True)) — Khẩu vị riêng: thích/ghét kiểu câu, nhịp, hành động. Taste không phải sự thật khách quan. Nó là thiên hướng nội bộ giúp ERIS dần tránh câu r...
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `SolitudeLoop` (decorator=dataclass(slots=True)) — Trạng thái tồn tại khi user vắng mặt.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `RitualMemory` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `InternalErrand` (decorator=dataclass(slots=True)) — Việc vặt nội bộ: dọn memory, kiểm log, rà project, hạ nhiễu.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `LifeEvent` (decorator=dataclass(slots=True)) — Sự kiện đời sống riêng. LifeEvent là đơn vị kể lại được: một project tiến lên, một object bị bỏ quên, một nghi thức hoàn thành, một khoảng s...
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `SurfaceSeedCandidate` (decorator=dataclass(slots=True)) — Seed rất nhỏ có thể gửi sang SurfaceArbiter. Đây không phải lời thoại hoàn chỉnh. Nó chỉ nói: "có một mảnh đời riêng public-safe đủ nhẹ để c...
    - `__post_init__(self)`
    - `should_surface(self)`
    - `to_dict(self)`
  - `PrivateLifeState` (decorator=dataclass(slots=True)) — State bền của PrivateLifeCore.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `PrivateLifeTickResult` (decorator=dataclass(slots=True)) — Output một tick PrivateLifeCore.
    - `to_dict(self)`

## `cortex/private_life/core.py`
- LOC: 880
- Docstring: cortex/private_life/core.py =========================== PrivateLifeCore: tầng đời sống riêng của ERIS. Tầng này cố ý không lấy user làm trung tâm. Nó theo dõi: - HabitatModel: nhà/runtime đang có gì và thay đổi thế nào. - ObjectAttachment: file/module/memory/s...
- Functions:
  - `_getattr_or_mapping(obj, name, default)`
- Classes:
  - `PrivateLifeCore` — Core đời sống riêng. Core này có hai luật: 1. Không sinh lời thoại public. 2. Mọi kết luận đều phải để lại LifeEvent/project update/object r...
    - `__init__(self, state)`
    - `_ensure_defaults(self)` — Cấy project/object mặc định nếu state mới. Đây là bootstrap, không phải hardcode kết luận. Tick sau...
    - `tick(self)` — Chạy một tick đời sống riêng. Tick này đọc snapshot/runtime một cách khoan dung. Thiếu field thì im,...
    - `_infer_idle_seconds(self)`
    - `_observe_habitat(self)`
    - `_place_from_app(self, active_app, active_window)`
    - `_runtime_queue_notes(self, runtime_owner)`
    - `_update_object_attachments(self)`
    - `_advance_private_projects(self)`
    - `_update_private_anchors(self)` — Cập nhật 5 anchor riêng bằng chuỗi dữ kiện cụ thể. Dữ kiện vào gồm user text, residue object, habita...
    - `_update_taste(self)`
    - `_build_life_events(self)`
    - `_build_surface_seed(self)`
    - `_update_daily_rhythm(self)`
    - `_update_solitude(self)`
    - `_update_rituals(self)`
    - `_update_errands(self)`
    - `_commit_events(self, events)`
    - `digest(self)` — Digest đọc nhanh cho runtime/debug menu.
    - `to_dict(self)`

## `cortex/private_life/persistence.py`
- LOC: 78
- Docstring: cortex/private_life/persistence.py ================================== Persistence JSON riêng cho PrivateLifeCore. Lý do tách khỏi memory_cognition: private life là state vận hành của agent, không phải fact user hay memory trả lời câu hỏi. Nó cần file riêng để...
- Functions:
  - `atomic_write_json(path, payload)` — Ghi JSON bằng temp file rồi replace. State mà hỏng giữa lúc ghi thì tick sau thành khảo cổ học. Ta không cần thêm ngành...
- Classes:
  - `PrivateLifeStore` — Kho state bền cho PrivateLifeCore.
    - `__init__(self, path)`
    - `from_env(cls)` — Tạo store theo env. ERIS_PRIVATE_LIFE_STATE_PATH thắng tuyệt đối. Nếu không có, dùng ERIS_MEMORY_COR...
    - `load(self)`
    - `save(self, state)`

## `cortex/private_mind/__init__.py`
- LOC: 72
- Docstring: Private mind package cho ERIS. Public API cố ý nhỏ: contract, concern store, dossier, evaluators, synthesizer, mutation bus và surface valve. Đừng import vòng vào coordinator ở đây. Import vòng là nghi lễ hiến tế thời gian debug, không phải kiến trúc.

## `cortex/private_mind/comfort_appraiser.py`
- LOC: 202
- Docstring: cortex/private_mind/comfort_appraiser.py ======================================== Thẩm định xem một câu của user có THẬT SỰ xoa dịu được Eris không. Vấn đề của bản cũ: cứ thấy "đừng lo / không sao" là tự động hạ stress. Đó là một con bot không có ego — ai dỗ m...
- Functions:
  - `_tokens(text)`
- Classes:
  - `ComfortAppraisal` (decorator=dataclass(slots=True)) — Kết quả thẩm định một lời dỗ.
    - `to_payload(self)`
  - `ComfortAppraiser` — Quyết định lời dỗ có ăn hay không, có ego.
    - `__init__(self)`
    - `looks_like_comfort(self, user_text)` — Pre-filter rẻ: có đáng gọi agent nhỏ không.
    - `appraise(self)`
    - `_judge(self, text, themes)` — Trả (on_topic, substance, is_attempt, source). Ưu tiên agent nhỏ.
    - `_model_judge(self, text, themes)`
    - `_heuristic_judge(self, text, themes)`
    - `_log(self, level, msg)`

## `cortex/private_mind/concern_store.py`
- LOC: 606
- Docstring: cortex/private_mind/concern_store.py ==================================== Kho lưu PrivateConcern. ConcernStore là phần bị thiếu lớn nhất của private cognition: nó giữ lại thứ runtime còn bận tâm qua nhiều tick, thay vì để mỗi mảnh suy nghĩ chết ngay sau một lo...
- Classes:
  - `ConcernStoreConfig` (decorator=dataclass(slots=True))
  - `ConcernStore` — CRUD + merge logic cho PrivateConcern.
    - `__init__(self)`
    - `__len__(self)`
    - `_is_degenerate_theme(theme)` — Trả True nếu theme là rác do LLM loop hoặc hallucination. Các dấu hiệu: - Cùng một token xuất hiện ≥...
    - `all(self)`
    - `open_concerns(self)`
    - `snapshots(self)`
    - `get(self, concern_id)`
    - `add_or_update(self, concern)`
    - `update_from_fragments(self, fragments)`
    - `update_from_judgment(self, data)`
    - `update_from_outcome(self, outcome)`
    - `mark_resolved(self, concern_id)`
    - `_apply_closure(self, concern)` — Khép một concern và để lại dấu 'đã nguôi' (Q1).
    - `auto_resolve_settled(self)` — Tự khép các concern đã dịu đủ lâu (Q1). Đây là đường 'giải quyết xong thì dọn' mà trước đây thiếu: c...
    - `recently_resolved(self)` — Các concern vừa nguôi gần đây — để diary/chat nói 'đã nguôi' (Q1).
    - `prune_and_decay(self)`
    - `load(self)`
    - `save(self)`
    - `_find_matching_concern(self, fragment)`
    - `_theme_from_fragment(self, fragment)`
    - `_trim(self)`
    - `_log(self, level, msg)`

## `cortex/private_mind/contracts.py`
- LOC: 639
- Docstring: cortex/private_mind/contracts.py ================================ Hợp đồng dữ liệu cho "private mind" của ERIS. Tầng này KHÔNG sinh lời thoại public. Nó chỉ biến tín hiệu runtime thành: - ThoughtFragment: mảnh nhận định có evidence; - PrivateConcern: mối bận t...
- Functions:
  - `normalize_stance(value)` — Chuẩn hoá epistemic_stance. Trả về một stance hợp lệ trong {grounded, ungrounded_aware, ungrounded_blind}, hoặc None nếu...
  - `normalize_intent_field(value)` — Chuẩn hoá intent ở tầng contract. Trả về một intent hợp lệ trong {sincere, playful, teasing, speculative}, hoặc `sincere...
  - `now_ts()`
  - `clamp01(value, default)`
  - `compact_text(value, limit)`
  - `stable_id(prefix)`
  - `to_plain(value)` — Serialize mềm để debug/persist JSON. Không nhét object sống vào memory. Object sống trong JSON là cách một repo gọi `rep...
- Classes:
  - `RankedHypothesis` (decorator=dataclass(slots=True)) — Một giả thuyết có điểm và evidence rõ ràng.
    - `__post_init__(self)`
    - `score(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `ThoughtFragment` (decorator=dataclass(slots=True)) — Mảnh suy nghĩ riêng do mini-evaluator tạo ra. Fragment không phải lời thoại. Nó là một claim có confidence, pressure và evidence. Nếu fragme...
    - `__post_init__(self)`
    - `score(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `PrivateConcern` (decorator=dataclass(slots=True)) — Mối bận tâm riêng có đời sống qua nhiều tick. Đây là thứ biến fragment rời rạc thành "điều còn treo trong đầu". Không có concern thì private...
    - `__post_init__(self)`
    - `merge_fragment(self, fragment)` — Cập nhật concern từ fragment mới. Áp lực tăng theo recurrence, uncertainty giảm nhẹ nếu nhiều evalua...
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `StateMutation` (decorator=dataclass(slots=True)) — Một yêu cầu đổi state/bias tương lai. Đây là cầu nối giữa "đã nghĩ" và "sẽ hành xử khác". Không có mutation bus, API chỉ đang viết nhật ký n...
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `SurfaceCandidate` (decorator=dataclass(slots=True)) — Ứng viên được phép nổi lên SurfaceArbiter. Đây vẫn chưa phải câu nói. Nó chỉ là impulse đã được lọc private-chain.
    - `__post_init__(self)`
    - `allowed(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `InternalJudgment` (decorator=dataclass(slots=True)) — Phán quyết nội tâm sau khi Gemma/heuristic synthesize fragments.
    - `__post_init__(self)`
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `EvidenceDossier` (decorator=dataclass(slots=True)) — Hồ sơ context chung cho mini-evaluator và inner synthesizer.
    - `to_dict(self)`
    - `evidence_ids(self)`
  - `PrivateMindTickResult` (decorator=dataclass(slots=True)) — Kết quả một tick private mind.
    - `to_dict(self)`

## `cortex/private_mind/epistemic.py`
- LOC: 70
- Docstring: cortex/private_mind/epistemic.py ================================ Bộ phân loại "epistemic self-awareness" thuần khiết (pure) cho private mind. Triết lý (Cartesian): một claim không có Public_Anchor mặc định rơi vào *nghi ngờ* (`speculative` -> `ungrounded_awar...
- Functions:
  - `normalize_intent(value)` — Trả về một intent hợp lệ, hoặc None nếu thiếu/ngoài tập hợp (out-of-set). Pure: chỉ phụ thuộc vào `value`. Chuẩn hoá về...
  - `resolve_intent(declared)` — Req 2 — mặc định kiểu Cartesian. - declared hợp lệ -> giữ nguyên; - declared vắng/ngoài tập: * có anchor -> `sincere`; *...
  - `classify_epistemic_stance()` — Req 1 — ánh xạ tổng (total), thuần khiết: (has_anchor, intent) -> stance. - có anchor -> `grounded` (anchor lấn át inten...

## `cortex/private_mind/evidence_dossier.py`
- LOC: 444
- Docstring: cortex/private_mind/evidence_dossier.py ======================================= EvidenceDossierBuilder gom hồ sơ cho private mind: - recent user turns; - runtime state; - memory hits; - repair failures; - active goal/current task; - surface outcome; - concern...
- Functions:
  - `_get(obj, name, default)`
  - `_call(obj, name)`
- Classes:
  - `EvidenceDossierBuilder` — Build context packet an toàn cho private mind.
    - `__init__(self)`
    - `build(self)`
    - `_recent_user_turns(self)`
    - `_runtime_state(self)`
    - `_thought_stream_state(self, thought_stream)`
    - `_private_runtime_state(self, runtime_owner)`
    - `_surface_queue_state(self, queue)`
    - `_compact_surface_like(self, item)`
    - `_evidence_metrics(self)`
    - `_latest_user_turn_age(self, recent_turns)`
    - `_public_anchor_count(self, evidence_index)`
    - `_memory_hits(self)`
    - `_repair_failures(self)`
    - `_active_goal_from_agenda(self, agenda)`
    - `_task_from_snapshot(self, snapshot, observer_frame, turns)`

## `cortex/private_mind/inner_diary_renderer.py`
- LOC: 412
- Docstring: cortex/private_mind/inner_diary_renderer.py Render a compact inner diary digest for UI display. Keep it short and never expose raw prompt text.
- Functions:
  - `_short(value, limit)`
  - `_as_dict(value)`
  - `_as_list(value)`
  - `_num(value, default)`
  - `_clamp01(value, default)`
  - `_clamp_signed(value, default)`
- Classes:
  - `InnerDiaryRenderer`
    - `_future_thought(self, future_bias)` — Tóm tắt định hướng sắp tới từ future_bias (inquiry_plan / speech_bias). Không bịa: chỉ tóm tắt dữ li...
    - `_affect(self, digest)` — Lấy snapshot cảm xúc liên tục thật (valence/arousal/...) nếu có. Ưu tiên digest['affect'] do private...
    - `_affect_intensities(self, affect)` — Map affect liên tục → cường độ 4 góc vòng cảm xúc (0..1).
    - `_mood_word(self, affect)` — Một từ tâm trạng từ affect thật, ngưỡng đồng bộ với emotion_debug.
    - `_emotion_board(self, digest)`
    - `_norm_line(text)`
    - `_dedupe_sections(cls, sections)` — Bỏ item trùng/chứa nhau giữa các ô (giữ nguyên bảng cảm xúc). Đây là lưới an toàn cuối: dù upstream...
    - `render(self, digest, voice)`

## `cortex/private_mind/inner_diary_writer.py`
- LOC: 211
- Docstring: cortex/private_mind/inner_diary_writer.py Biến dữ kiện nội tâm thô (judgment/concern/fragment/future/surface) thành nhật ký giọng Eris (ngôi thứ nhất) thông qua một lời gọi LLM, có: - throttle theo thời gian, - chỉ gọi lại khi nội dung đổi (content signature),...
- Functions:
  - `_env_flag(name, default)`
  - `_env_float(name, default)`
  - `_as_dict(value)`
  - `_as_list(value)`
  - `_short(value, limit)`
- Classes:
  - `InnerDiaryWriter` — Viết nhật ký nội tâm giọng Eris từ digest, có throttle/cache.
    - `__init__(self)`
    - `maybe_write(self, digest)` — Trả dict giọng Eris (5 trường) hoặc None nếu nên dùng fallback thô.
    - `_try_fallback(self, facts)` — Gọi adapter dự phòng cho diary. Nuốt mọi lỗi, trả None nếu không cứu được.
    - `_build_facts(self, digest)`
    - `_signature(self, facts)`
    - `_sanitize(self, voice)`
    - `_log(self, level, msg)`

## `cortex/private_mind/inner_synthesizer.py`
- LOC: 330
- Docstring: cortex/private_mind/inner_synthesizer.py ======================================= GemmaInnerSynthesizer gom ThoughtFragment thành InternalJudgment. Vai trò đúng: thẩm phán nội tâm. Vai trò sai: thợ viết caption cho đồng hồ biết buồn. Nếu model adapter không sẵn...
- Classes:
  - `InnerSynthesizerModelAdapter` (base=Protocol)
    - `synthesize_judgment(self, dossier, fragments)`
  - `GemmaInnerSynthesizer` — Synthesize fragments thành phán quyết nội tâm.
    - `__init__(self)`
    - `synthesize(self)`
    - `_try_model(self, dossier, fragments)`
    - `_fallback(self, dossier, fragments)`
    - `_norm_claim(text)`
    - `_claim_is_redundant(cls, candidate, kept)` — True nếu claim mới chỉ là biến thể/đoạn con của claim đã giữ. Chặn vòng "X Mà Y" khi Y chứa X (hoặc...
    - `_weave_inner_voice(cls, fragments)` — Dệt các mảnh thành một mạch độc thoại ngôi thứ nhất, không boilerplate. Các claim giờ đã ở giọng ngô...
    - `_rank_hypotheses(self, fragments, evidence_ids)`
    - `_rejected_hypotheses(self, fragments, evidence_ids)`
    - `_collect_mutations(self, fragments, evidence_ids)`
    - `_surface_candidate_if_useful(self, dossier, fragments)`
    - `_adapter_api_status(self)`

## `cortex/private_mind/mini_evaluators.py`
- LOC: 350
- Docstring: cortex/private_mind/mini_evaluators.py 4 mini-evaluator gọi API. Không có rule fallback — nếu API fail thì tick đó không có fragment từ evaluator đó. Pool API dự phòng lo việc resilience.
- Functions:
  - `_env_flag(name, default)`
  - `_relevance_sig()` — Chữ ký gọn cho trạng thái bằng chứng. Dùng để edge-trigger: chỉ nghĩ lại khi bằng chứng đổi, không nghĩ lại đúng cùng mộ...
  - `_evidence_ids(dossier)`
  - `_from_model(adapter, evaluator_name, dossier)` — Gọi model adapter, trả None nếu fail hoặc result yếu.
  - `_infer_user_facet(claim)` — Đoán nhẹ facet từ claim; UserModelStore sẽ chuẩn hóa lại nếu sai. Cố ý hẹp: chỉ chạm vài tín hiệu rõ. Mặc định 'general'...
- Classes:
  - `MiniEvaluatorModelAdapter` (base=Protocol)
    - `evaluate_fragment(self, evaluator_name, dossier)`
  - `BaseMiniEvaluator`
    - `__init__(self, name)`
    - `evaluate(self, dossier)`
    - `relevance_signature(self, dossier)` — Trả None nếu lúc này KHÔNG có gì đáng để mảnh này nghĩ. Trả chữ ký nếu CÓ — chữ ký đổi khi bằng chứn...
  - `IntentEvaluator` (base=BaseMiniEvaluator)
    - `__init__(self)`
    - `relevance_signature(self, dossier)`
  - `MemoryResonanceEvaluator` (base=BaseMiniEvaluator)
    - `__init__(self)`
    - `relevance_signature(self, dossier)`
  - `RiskAndPermissionEvaluator` (base=BaseMiniEvaluator)
    - `__init__(self)`
    - `relevance_signature(self, dossier)`
  - `FutureBiasEvaluator` (base=BaseMiniEvaluator)
    - `__init__(self)`
    - `relevance_signature(self, dossier)`
  - `UserModelEvaluator` (base=BaseMiniEvaluator) — Agent nhỏ hướng-Ngài: dựng Mô_Hình_Ngài (spec eris-existential-anchor R1). Không sinh lời thoại. Mỗi fragment mang `metadata['facet']` để Us...
    - `__init__(self)`
    - `relevance_signature(self, dossier)`
    - `evaluate(self, dossier)`
  - `MiniEvaluatorPipeline`
    - `__init__(self)`
    - `_evaluators_to_run(self, dossier)` — Quyết định mảnh nào đáng gọi lúc này (không tốn API). Bỏ qua mảnh khi: không khai báo cổng → luôn ch...
    - `evaluate(self, dossier)`

## `cortex/private_mind/state_mutation_bus.py`
- LOC: 381
- Docstring: cortex/private_mind/state_mutation_bus.py ========================================= StateMutationBus biến InternalJudgment thành ảnh hưởng thật lên hành vi tương lai: - agenda_stack; - repair_memory / commit request; - belief_core; - speech_bias; - inquiry_pla...
- Classes:
  - `MutationApplyReport` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `PrivateRuntimeBiasState` (decorator=dataclass(slots=True)) — Store nhẹ cho bias nếu runtime chưa có field tương ứng.
    - `to_dict(self)`
  - `StateMutationBus`
    - `__init__(self)`
    - `apply(self, judgment)`
    - `_apply_one(self, mutation)`
    - `_apply_agenda(self, mutation, agenda_stack)`
    - `_apply_thought_pressure(self, mutation, thought_stream, runtime_owner)`
    - `_apply_belief_core(self, mutation)`
    - `_apply_repair_memory(self, mutation)`
    - `_enqueue_surface_candidate(self, candidate, queue)`
    - `_report(self, mutation, applied, reason, value)`

## `cortex/private_mind/surface_valve.py`
- LOC: 372
- Docstring: cortex/private_mind/surface_valve.py ==================================== SurfaceValve lọc InternalJudgment thành SurfaceCandidate/SurfaceImpulse rất nhỏ. Luật: không leak raw internal JSON, không lộ private chain, không đem phán quyết nội tâm ra đọc như biên...
- Classes:
  - `SurfaceValve`
    - `__init__(self)`
    - `filter(self, judgment)`
    - `to_surface_impulse(self, candidate)` — Chuyển SurfaceCandidate sang SurfaceImpulse nếu module tồn tại.
    - `_merge_public_anchor_refs(self, candidate, evidence, metadata)` — Req 4.6 — đảm bảo mọi Public_Anchor reference của một claim grounded có mặt trên evidence của Surfac...
    - `_apply_public_surface_gate(self, candidate)`
    - `_has_public_anchor(self, candidate)`
    - `_copy_candidate(self, candidate)`
    - `_stamp_epistemic(self, candidate)` — Trả về bản sao của candidate đã gắn epistemic_stance + intent. Dùng `_copy_candidate` (to_dict -> fr...
    - `_withhold_to_body_only(self, candidate)` — Req 3 — giữ lại confabulation khỏi public speech nhưng KHÔNG vứt bỏ. Đặt `channel="body_only"` để cl...
    - `_safe_seed_from_judgment(self, judgment)`
    - `_looks_private(self, text)`

## `cortex/private_mind/thought_continuity.py`
- LOC: 291
- Docstring: cortex/private_mind/thought_continuity.py ========================================= Dòng suy nghĩ liên tục của Eris, lưu bền ra JSONL. Mục đích: mỗi lần PrivateMind nghĩ, nó KHÔNG bắt đầu từ con số không. Nó nhớ vài suy nghĩ gần nhất và những mạch còn dang dở,...
- Functions:
  - `_now()`
  - `_clamp01(x)`
- Classes:
  - `ThoughtEntry` (decorator=dataclass) — Một suy nghĩ trong dòng liên tục.
    - `to_json(self)`
    - `from_json(cls, data)`
  - `ThoughtContinuityStore` — Lưu và gọi lại dòng suy nghĩ liên tục. Bộ nhớ trong RAM là nguồn chính; JSONL chỉ để bền qua restart. Mọi lỗi I/O đều nuốt êm — tính liên tụ...
    - `__init__(self)`
    - `from_env(cls)`
    - `_log(self, level, msg)`
    - `_load(self)`
    - `_rewrite_file(self)`
    - `_append_line(self, entry)`
    - `append(self, entry)`
    - `record_thought(self)`
    - `mark_revisited(self, theme)`
    - `recent(self, n)`
    - `recent_for_prompt(self, n)` — Mạch nghĩ gần đây ở dạng gọn cho prompt — để model nối tiếp.
    - `unresolved(self)` — Các mạch nghĩ còn dang dở, đủ nặng và đã nguội đủ lâu để khơi lại. Đây là con đường DUY NHẤT để nghĩ...
    - `unresolved_for_prompt(self)`
    - `has_followup_due(self)`
    - `_humanize_ago(seconds)`
    - `digest(self)`

## `cortex/private_mind/user_model.py`
- LOC: 455
- Docstring: cortex/private_mind/user_model.py ================================= Mô_Hình_Ngài — hình dung bền vững của ERIS về Người_Dùng (Ngài). Đây là TẦNG NỀN của spec `eris-existential-anchor`: gắn bó, ý nghĩa và trục bóng tối đều phái sinh từ đây. Khác với ConcernStor...
- Functions:
  - `_norm(value)`
  - `_normalize_facet(value)`
  - `default_user_model_path()` — Đường dẫn mặc định trong memory_core/, cạnh các store private khác.
- Classes:
  - `UserBelief` (decorator=dataclass(slots=True)) — Một niềm tin có đời sống của ERIS về Ngài. Mirror tinh thần PrivateConcern: có recurrence, pressure→confidence, evidence, nhưng chủ thể luôn...
    - `__post_init__(self)`
    - `score(self)`
    - `reinforce_from_fragment(self, fragment)` — Củng cố niềm tin từ một fragment mới cùng hướng (R1.4).
    - `apply_decay(self)` — Quên có kiểm soát (R1.5): không được củng cố lâu → confidence giảm. Trả True nếu có thay đổi.
    - `to_dict(self)`
    - `from_mapping(cls, data)`
  - `UserModelConfig` (decorator=dataclass(slots=True))
  - `UserModelStore` — Kho Mô_Hình_Ngài: bền vững, versioned, có undo/reset. Mirror pattern persistence của PersistentAgentMindStore (schema_version, atomic tmp+re...
    - `__init__(self)`
    - `__len__(self)`
    - `all(self)`
    - `by_facet(self, facet)`
    - `snapshot_for_dossier(self)` — Ảnh chụp public-safe để nhét vào EvidenceDossier (R1.6).
    - `model_thickness(self)` — Độ dày/nhất quán Mô_Hình_Ngài — đầu vào cho SignificanceDeriver (R2.2).
    - `update_from_fragments(self, fragments)`
    - `_find_matching(self, fragment, facet)`
    - `decay(self)`
    - `checkpoint(self)` — Chụp phiên bản hiện tại vào lịch sử, trả về số phiên bản mới.
    - `revert_to(self, version)` — Khôi phục Mô_Hình_Ngài về một phiên bản đã checkpoint (R10.3).
    - `reset_to_baseline(self)` — Xóa toàn bộ Mô_Hình_Ngài về baseline rỗng, giữ lịch sử (R10.3).
    - `to_dict(self)`
    - `load_from_dict(self, raw)`
    - `load(self)`
    - `reload_if_changed(self)`
    - `save(self)`
    - `_trim(self)`
    - `_log(self, level, msg)`

## `cortex/relational_feedback.py`
- LOC: 345
- Docstring: relational_feedback.py ====================== Tầng này đọc feedback về *cách ERIS hiện diện* trong hội thoại: - lạnh quá - xa cách quá - vô hồn / robot / máy móc - nói như assistant/support/corporate - cứng / khô / không tự nhiên Nó không mutate relationship s...
- Functions:
  - `clamp01(value, default)`
  - `normalize_vi(text)`
  - `_contains_phrase(text, phrase)`
  - `_has_any(text, phrases)`
  - `merge_affect_with_relational_feedback(affect, feedback)` — Tạo dict affect cho FeRenderer mà không cần mutate AffectSemanticSignal. FeRenderer đã nhận dict, nên đây là adapter sạc...
- Classes:
  - `RelationalFeedbackSignal` (decorator=dataclass(frozen=True, slots=True))
    - `empty(cls)`
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `to_prompt_context(self)`
  - `RelationalFeedbackAnalyzer` — Detector nhỏ, có confidence, không tự quyết định output. Nó cố tình conservative với các case dễ false-positive như "trời lạnh" hoặc "máy lạ...
    - `analyze(self, user_text)`

## `cortex/relationship_dynamics.py`
- LOC: 1127
- Docstring: relationship_dynamics.py ======================== Module này quản lý state quan hệ dài hạn giữa ERIS và user. Bản này đã bỏ kiểu suy trực tiếp: "ổn" / "chuẩn" -> accepted_style "eris" / "project" -> repeated_project_context Thay vào đó, relationship_dynamics c...
- Functions:
  - `_safe_float(value, default)`
  - `_decay(value, hours, half_life_hours)` — Decay theo half-life. Dùng half-life thay vì trừ tuyến tính vì residue quan hệ nên tan dần, không biến mất cái rụp như b...
  - `_nudge(value, delta)` — Cộng delta nhỏ rồi clamp. Relationship update phải là nudge, không phải teleport. Nếu mỗi turn nhảy nửa cây trust thì kh...
  - `_compact_notes(notes, limit)`
  - `_score(value)`
- Classes:
  - `RelationshipDynamicsState` (decorator=dataclass(slots=True)) — State dài hạn về quan hệ giữa ERIS và user. familiarity: Độ quen nhịp. Tăng từ repeated_project_context có evidence, không tăng chỉ vì user...
    - `clamp(self)`
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `to_prompt_context(self)`
  - `RelationshipTurnEvent` (decorator=dataclass(slots=True)) — Event tóm tắt một turn để update relationship state. Điểm mới của bản này: - Có RelationshipEventScores để giữ gradient. - Bool cũ vẫn còn đ...
    - `from_affect(cls)` — Tạo event từ affect + scores đã build. Quan trọng: hàm này KHÔNG còn dò keyword trong user_text để s...
    - `evidence_labels(self, limit)` — Trả nhãn evidence ngắn để ghi notes/debug.
  - `RelationshipDynamicsReport` (decorator=dataclass(slots=True)) — Kết quả update relationship.
    - `to_dict(self)`
  - `RelationshipDynamicsEngine` — Engine update RelationshipDynamicsState theo từng turn. Thiết kế: - Nhận event score đã qua builder. - Update nhỏ, có quán tính. - Dùng acce...
    - `__init__(self)`
    - `create_state(self)`
    - `infer_event(self)` — Tạo RelationshipTurnEvent từ text + context. Đây là đường khuyến nghị thay cho RelationshipTurnEvent...
    - `update(self, state, event)` — Update state theo event hiện tại. Hàm này clone state trước khi sửa để tránh side-effect khó debug....
    - `_apply_gap_decay(self, state, hours, notes)` — Decay state giữa session. Rupture/recoil/irritation tan nhanh hơn familiarity/ritual. Nếu gap dài sa...
    - `_compute_deltas(self, before, after)`
    - `_choose_last_event(self, notes)`
  - `RelationshipStylePressure` (decorator=dataclass(slots=True)) — Áp lực style derive từ relationship state. PersonalityLens/FeRenderer nên đọc pressure này thay vì đọc thẳng mọi field. Vì nếu mỗi module tự...
    - `from_state(cls, state)`
    - `to_prompt_context(self)`

## `cortex/relationship_event_builder.py`
- LOC: 862
- Docstring: relationship_event_builder.py ============================= Tầng này chuyển một lượt hội thoại thành các score quan hệ có bằng chứng. Lý do tồn tại ------------- Trước đây RelationshipDynamics có khuynh hướng suy trực tiếp: "ổn" / "chuẩn" -> user_accepted_styl...
- Functions:
  - `clamp01(value, default)` — Ép một giá trị về [0, 1]. File này có thể được import độc lập, nên không phụ thuộc cứng vào affect_semantics.clamp01. Mộ...
  - `safe_float(value, default)`
  - `normalize_vi(text)` — Normalize tiếng Việt để so khớp nhẹ. Dùng cho scoring mềm, không dùng như chân lý. Normalize bỏ dấu rất tiện, và cũng rấ...
  - `token_set(text)` — Token vừa đủ cho overlap. Bỏ filler để "ổn chưa" không tự biến thành semantic continuity. Một ngày nào đó loài người sẽ...
  - `compact(items, limit)`
  - `overlap_score(a, b)` — Jaccard mềm cho anchor/topic overlap.
  - `get_attr_or_key(obj, name, default)` — Đọc field từ dataclass/object/dict an toàn.
- Classes:
  - `RelationshipEvidence` (decorator=dataclass(frozen=True, slots=True)) — Một mảnh bằng chứng dùng để build relationship event. label: Nhãn ngắn, ví dụ "goal_continuity", "same_anchor", "positive_ack". confidence:...
    - `normalized(self)`
  - `RelationshipEventScores` (decorator=dataclass(frozen=True, slots=True)) — Score quan hệ cho một lượt. Các score này là gradient. RelationshipDynamicsEngine nên nhân delta theo score, không dùng bool như công tắc đè...
    - `accepted_any(self)` — Acceptance tổng hợp nhưng vẫn giữ ba nhánh riêng để update tinh hơn.
    - `normalized(self)`
  - `RecentTurn` (decorator=dataclass(frozen=True, slots=True)) — Turn gọn để builder đọc session/public ledger mà không phụ thuộc class thật.
  - `RelationshipEventBuildContext` (decorator=dataclass(frozen=True, slots=True)) — Context đầu vào giàu hơn cho builder. Dùng dataclass này nếu caller muốn gọi rõ ràng. Builder.build() vẫn nhận keyword args để dễ nối vào co...
  - `RelationshipEventBuilder` — Build RelationshipEventScores từ nhiều nguồn có confidence. Điểm quan trọng: - Một marker bề mặt không được tự bật relationship event mạnh....
    - `build(self)` — Build scores bằng keyword args để caller dễ nối dần.
    - `build_from_context(self, ctx)` — Biến thể typed cho caller thích rõ contract.
    - `_context_from_kwargs(self, data)`
    - `_coerce_relational_feedback(self, value)`
    - `_optional_score(self, value)`
    - `_score_repeated_project_context(self, ctx)`
    - `_goal_continuity_score(self, ctx, user_tokens, current_anchors)`
    - `_recent_topic_score(self, ctx, user_tokens)`
    - `_technical_followup_score(self, ctx)`
    - `_extract_anchors(self, text)` — Rút anchor cụ thể: file/module/class/function. Không dùng "eris/project" làm anchor chính vì quá rộn...
    - `_score_acceptance(self, ctx)`
    - `_positive_ack_score(self, normalized)`
    - `_style_target_score(self, normalized)`
    - `_action_continue_score(self, normalized)`
    - `_continued_same_plan_score(self, ctx)`
    - `_looks_like_quality_question(self, normalized)`
    - `_contains_any(self, normalized, markers)`

## `cortex/se.py`
- LOC: 1528
- Classes:
  - `_ContextCandidate` (decorator=dataclass(frozen=True)) — Một ứng viên phân loại bối cảnh. Lưu ý: đây là dataclass private để giữ `TelemetrySnapshot` cũ không bị đổi contract. Nếu muốn nâng cấp down...
  - `_ContextClassification` (decorator=dataclass(frozen=True)) — Kết quả phân loại bối cảnh có confidence thay vì chỉ trả một nhãn. `primary_kind` vẫn là string cũ để downstream không vỡ. `confidence` và `...
  - `SeLens` — Tầng Se: biến telemetry thô thành snapshot có thể đưa vào cognition. Phiên bản này thay phần router `keyword in haystack -> return kind` bằn...
    - `__init__(self)`
    - `build_snapshot(self, raw)`
    - `build_machine_context(self, raw)`
    - `_load_context_overrides(self)`
    - `_contains_override(self, haystack, key)`
    - `format_snapshot(self, snapshot)`
    - `format_directive_snapshot(self, snapshot)`
    - `_format_visible_context(self, snapshot)`
    - `_is_generic_prompt_event(self, event)`
    - `_is_generic_prompt_evidence(self, evidence)`
    - `_build_prompt_screen_facts(self, snapshot)`
    - `_normalize_string_tuple(self, values)`
    - `_build_recent_events(self)`
    - `_build_user_signals(self)`
    - `_infer_typing_speed(self, idle_seconds)`
    - `_infer_window_switching(self, open_window_count, browser_tab_count)`
    - `_infer_focus_pattern(self)`
    - `_build_evidence(self)`
    - `_build_claim_style(self)`
    - `_normalize_claim_style(self, value)`
    - `_classify_window_kind(self, active_window, browser_url, browser_tabs)` — API cũ: trả về string kind. Runtime/test cũ có thể đang gọi trực tiếp private method này. Vì vậy khô...
    - `_classify_window_context(self, active_window, browser_url, browser_tabs)` — Phân loại bối cảnh bằng điểm số cạnh tranh. Khác bản cũ: - Không return sớm theo keyword. - Một tab/...
    - `_infer_surface_kind(self, active_text, browser_domain, browser_url)`
    - `_infer_content_kind(self, active_text, browser_text, browser_domain)`
    - `_infer_activity_intent(self, primary_kind, surface_kind, content_kind, confidence, ambiguity)`
    - `_context_confidence_cap(self, primary_kind, surface_kind, content_kind, primary_score)`
    - `_score_to_confidence(self, score, gap, ambiguity)`
    - `_format_context_classification_evidence(self, classification)`
    - `_extract_context_meta_from_evidence(self, evidence)`
    - `_build_focus_summary(self, active_window_kind, active_app, browser_url)`
    - `_label_position(self, inferred_pos_x)`
    - `_label_idle(self, idle_seconds)`
    - `_describe_prompt_scene(self, snapshot)`
    - `_describe_prompt_pace(self, snapshot)`
    - `_describe_prompt_focus(self, snapshot)`
    - `_build_prompt_cues(self, snapshot)`
    - `_normalize_content_metadata(self, value)`
    - `_augment_browser_tabs_with_content_metadata(self, browser_tabs, content_metadata)`
    - `_build_content_metadata_evidence(self, content_metadata)`
    - `_content_metadata_prompt_facts(self, content_metadata)`
    - `_format_content_metadata_inline(self, content_metadata)`
    - `_content_metadata_confidence(self, content_metadata)`
    - `_content_metadata_has_concrete_text(self, content_metadata)`
    - `_trim_text(self, value, limit)`
    - `_coerce_float(self, value, default)`
    - `_looks_like_browser_surface(self, active_window, browser_url, browser_tabs)`
    - `_build_weak_context_hints(self)`
    - `_is_weak_context_hint_evidence(self, evidence)`
    - `_concrete_evidence(self, evidence)`
    - `_evidence_quality_score(self, evidence)`
    - `_evidence_item_quality(self, evidence)`
    - `_label_ambient_tone(self, ambient_seed)`
    - `_label_tease_bias(self, ambient_seed)`
    - `_focus_summary_for_kind(self, active_window_kind, active_app, browser_url)`
    - `_normalize_text(self, value)`
    - `_domain_from_url(self, url)`
    - `_domain_matches(self, domain, expected_domains)`
    - `_phrase_in_text(self, text, phrase)`
    - `_contains_any_phrase(self, text, phrases)`
    - `_contains_any_file_extension(self, text)`
    - `_has_technical_anchor(self, active_text, browser_text)`
    - `_clamp(self, value, lower, upper)`

## `cortex/self_model.py`
- LOC: 474
- Functions:
  - `_clamp01(value)`
  - `_clamp_signed(value)`
- Classes:
  - `SelfModelEngine` — Derives ERIS' self-state as a guarded, grounded desktop presence. SelfModel is not the place to make ERIS recite architecture terms. It is a...
    - `evaluate(self)`
    - `_has_meaningful_broadcast(self, broadcast)`
    - `_system_pressure(self, snapshot)`
    - `_evidence(self)`
    - `_affordance_label(self)`
    - `_narrative(self)`
    - `_prompt_context(self)`

## `cortex/self_observation.py`
- LOC: 811
- Classes:
  - `SelfObservationReport` (decorator=dataclass(slots=True)) — Báo cáo tự quan sát của ERIS sau outcome. Field lõi theo pipeline: - matched_beliefs: câu/hành động vừa rồi có khớp belief/grounding không....
    - `to_dict(self)`
    - `from_any(cls, value)`
  - `SelfObservationEngine` — Phân loại lỗi của ERIS từ frame + outcome. Cách dùng: frame.outcome = outcome_observer.observe(frame) frame.self_observation = self_observer...
    - `reflect(self, frame)`
    - `append_repair_commit_request(self, frame)` — Tạo và append StateCommitRequest target=repair_memory nếu cần. Hàm này chỉ tạo request. Commit thật...
    - `build_repair_commit_request(self, frame)` — Build request tương thích StateCommitRequest. Ưu tiên import `core.evidence.StateCommitRequest`. Nếu...
    - `_render_repair_content(self, frame, report)`
    - `_classify_failure(self)`
    - `_estimate_severity(self)`
    - `_estimate_confidence(self)`
    - `_derive_wrong_assumption(self)`
    - `_repair_strategy_for(self, failure_type)`
    - `_future_suppression_for(self, failure_type)`
    - `_mentions_overread(self, text)`
    - `_mentions_underacted(self, text)`
    - `_mentions_culture_or_tone(self, text)`
    - `_contains_mindread_shape(self, normalized_text)`
    - `_contains_question_or_probe(self, normalized_text)`
    - `_detect_assistant_flattening(self, normalized_text, frame)`
    - `_detect_overhumanization(self, normalized_text)`
    - `_collect_evidence_ids(self, frame)`
    - `_coerce_outcome(self, value)`
    - `_extract_final_text(frame)`
    - `_read_float(obj, key)`
    - `_read_list(obj, key)`
    - `_safe_setattr(obj, key, value)`
    - `_normalize(text)`
    - `_dedupe(items)`
    - `_clamp01(value)`

## `cortex/semantic_encoder.py`
- LOC: 549
- Functions:
  - `clamp01(value)` — Ép một giá trị về [0, 1]. Hàm này được copy nhẹ ở đây để file có thể đứng độc lập. Không import ngược sang `orientation_...
  - `l2_norm(vector)` — Tính độ dài L2 của vector.
  - `normalize_vector(vector)` — Chuẩn hóa vector về độ dài 1. Nếu vector rỗng hoặc toàn 0 thì trả tuple rỗng để downstream biết tín hiệu này không dùng...
  - `cosine_similarity(left, right)` — Tính cosine similarity an toàn. Hàm chịu được hai vector khác chiều bằng cách chỉ so phần chiều chung. Trong production...
  - `mean_vectors(vectors)` — Tính centroid đã normalize từ nhiều vector. Centroid dùng cho prototype bank: nhiều câu mẫu cùng mô tả một intent sẽ đượ...
  - `stable_hash_vector(text)` — Tạo vector hashing ổn định từ text. Đây KHÔNG phải semantic embedding thật. Nó chỉ là fallback deterministic để unit tes...
  - `build_default_semantic_encoder(provider)` — Tạo encoder mặc định cho runtime. Nếu truyền provider, encoder sẽ bọc provider và cache. Nếu không, router sẽ trả Null h...
- Classes:
  - `SemanticVector` (decorator=dataclass(frozen=True, slots=True)) — Kết quả encode một đoạn text. Fields ------ text: Text gốc hoặc text đã được caller chọn để encode. vector: Vector đã normalize. Rỗng nghĩa...
    - `usable(self)`
    - `dimensions(self)`
  - `EncoderHealth` (decorator=dataclass(frozen=True, slots=True)) — Trạng thái hoạt động của encoder. `available=False` không phải lỗi chết. Nó chỉ báo downstream phải hạ về lexical fallback và cap confidence...
  - `EmbeddingProvider` (base=Protocol) — Protocol cho provider embedding thật. Một provider hợp lệ nhận list text và trả list vector cùng thứ tự. Có thể là local model, remote API,...
    - `__call__(self, texts)`
  - `BaseSemanticEncoder` — Base class tối thiểu cho semantic encoder.
    - `health(self)`
    - `encode(self, text)`
    - `encode_many(self, texts)`
  - `NullSemanticEncoder` (base=BaseSemanticEncoder) — Encoder rỗng. Dùng khi project chưa cấu hình embedding. Downstream vẫn chạy được, nhưng phải hiểu là chỉ còn lexical heuristic. Khá buồn, nh...
    - `health(self)`
    - `encode_many(self, texts)`
  - `LexicalHashingSemanticEncoder` (base=BaseSemanticEncoder) — Fallback deterministic dựa trên hashing token/char. Tên có chữ `Semantic` vì nó thỏa interface, không phải vì nó thật sự hiểu nghĩa. Trong d...
    - `__init__(self)`
    - `health(self)`
    - `encode_many(self, texts)`
  - `ProviderBackedSemanticEncoder` (base=BaseSemanticEncoder) — Encoder bọc một embedding provider thật. Provider có thể là: - hàm gọi local sentence-transformer - hàm gọi llama.cpp embedding endpoint - h...
    - `__init__(self, provider)`
    - `health(self)`
    - `encode_many(self, texts)`
  - `CachedSemanticEncoder` (base=BaseSemanticEncoder) — Cache LRU mỏng cho encoder. Embedding prototype và context thường lặp lại nhiều. Cache giúp giảm chi phí gọi model/API. Cache key gồm model_...
    - `__init__(self, inner)`
    - `health(self)`
    - `clear(self)`
    - `encode_many(self, texts)`
  - `SemanticEncoderRouter` (base=BaseSemanticEncoder) — Chọn encoder thật nếu có, fallback nếu không. Router giúp runtime cấu hình mềm: - Có provider thật: dùng provider. - Provider lỗi hoặc chưa...
    - `__init__(self, primary)`
    - `health(self)`
    - `_active(self)`
    - `encode_many(self, texts)`

## `cortex/semantic_hypothesis.py`
- LOC: 423
- Classes:
  - `PrototypeCentroid` (decorator=dataclass(frozen=True, slots=True)) — Vector centroid đã encode của một PrototypeSet.
    - `usable(self)`
  - `SemanticHypothesis` (decorator=dataclass(frozen=True, slots=True)) — Một giả thuyết semantic. score: Điểm cuối sau khi tính cosine, prior, anchor boost và cap fallback. raw_similarity: Cosine gốc giữa text vec...
  - `SemanticHypothesisReport` (decorator=dataclass(frozen=True, slots=True)) — Kết quả semantic top-k cho một domain.
    - `labels(self)`
    - `uncertain(self)`
  - `HypothesisConfig` (decorator=dataclass(frozen=True, slots=True)) — Tham số scoring semantic. min_signal: Điểm tối thiểu để một hypothesis được xem là có tín hiệu. min_margin: Khoảng cách top1-top2 cần có để...
  - `SemanticHypothesisEngine` — So text hiện tại với prototype bank để sinh hypothesis.
    - `__init__(self, encoder)`
    - `clear_cache(self)`
    - `compare(self, domain, text)` — Sinh hypothesis top-k cho một domain. labels: Nếu truyền vào, chỉ xét các label đó. Hữu ích khi call...
    - `compare_many(self, domains, text)` — So cùng một text với nhiều domain.
    - `_centroid_for(self, prototype)`
    - `_score_prototype(self)`
    - `_anchor_boost(self, anchors, tags)`
    - `_estimate_ambiguity(self, top, second)`
    - `_report_confidence(self, top, ambiguity)`
    - `_empty_report(self, domain, text, reason, health)`

## `cortex/semantic_prototypes.py`
- LOC: 547
- Functions:
  - `p(text, weight)`
  - `default_activity_intent_sets()` — Prototype cho activity intent. Các câu mẫu tập trung vào nghĩa tình huống, không cố liệt kê app/token.
  - `default_goal_text_kind_sets()` — Prototype cho việc phân loại user text thành goal/casual/commentary.
  - `default_goal_relation_sets()` — Prototype cho quan hệ giữa context hiện tại và active goal.
  - `default_failure_class_sets()` — Prototype cho phân loại lỗi hội thoại/cognition. Tầng này chưa bắt buộc dùng trong orientation, nhưng để sẵn vì repair m...
  - `default_speech_opportunity_sets()` — Prototype cho mode nói/im lặng. Chỉ là hypothesis. Quyền nói thật vẫn phải qua SpeechOpportunity, Permission, Homeostasi...
  - `build_default_prototype_bank()` — Tạo prototype bank mặc định cho ERIS.
- Classes:
  - `PrototypePhrase` (decorator=dataclass(frozen=True, slots=True)) — Một câu mẫu semantic cho một label. text: Câu mô tả ý nghĩa. weight: Trọng số câu mẫu. Câu càng canonical càng nặng. tags: Anchor phụ để hyp...
  - `PrototypeSet` (decorator=dataclass(frozen=True, slots=True)) — Tập câu mẫu cho một label trong một domain.
    - `phrase_texts(self)`
    - `all_tags(self)`
  - `PrototypeBank` (decorator=dataclass(slots=True)) — Kho prototype có thể mở rộng. Bank giữ dữ liệu thuần. Nó không encode vector. Việc encode nằm ở `semantic_hypothesis.py` để cache/model khôn...
    - `add(self, prototype_set)`
    - `extend(self, prototype_sets)`
    - `get(self, domain, label)`
    - `by_domain(self, domain)`
    - `labels(self, domain)`
    - `domains(self)`
    - `merge(self, other)`

## `cortex/session_ritual.py`
- LOC: 443
- Functions:
  - `_clamp01(value)`
  - `_clean(value)`
  - `_disabled_startup_greeting()`
  - `_public_fragment(value)`
- Classes:
  - `SessionRitualEngine` — Rehydrates continuity once at app/session start.
    - `evaluate(self)`
    - `render_prompt_context(self, report)`
    - `_active_goal(self, internal_state)`
    - `_current_attractor(self, thought_stream_report)`
    - `_unresolved_loops(self, thought_stream_report)`
    - `_recent_cognition_direction(self, internal_state, thought_stream_report)`
    - `_self_continuity(self, internal_state)`
    - `_presence_is_clear(self)`
    - `_is_overloaded(self)`
    - `_greeted_recently(self, internal_state)`
    - `_tone(self)`
    - `_greeting_frame(self)`
    - `_greeting_text(self)`
    - `_public_self_continuity(self, self_continuity)`
    - `_evidence(self)`

## `cortex/social_presence.py`
- LOC: 588
- Functions:
  - `_clean(value)`
  - `_clamp(value)`
- Classes:
  - `PresenceFeatureVector` (decorator=dataclass(slots=True))
    - `numeric_tuple(self)`
  - `PresenceMemory` (decorator=dataclass(slots=True))
  - `SocialPresenceDetector` — Detects ambient co-presence without treating it as chat or speech intent.
    - `__init__(self)`
    - `learn_event_patterns(self, events)` — Background path: enrich meaningful events without blocking detection.
    - `detect(self)`
    - `_build_feature_vector(self)`
    - `_hydrate_memory_from_internal_state(self, internal_state)`
    - `_score_vector(self, v)`
    - `_ema(self, old, new, alpha)`
    - `_update_memory(self, v, raw_presence, kind)`
    - `_classify_presence_kind(self, v)`
    - `_reason_for_kind(self, kind)`
    - `_vector_evidence(self, v)`
    - `_looks_like_presence_event(self, event)`
    - `_looks_like_presence_profile(self, profile)`
    - `_semantic_presence_bonus(self, profiles)`

## `cortex/speech_core.py`
- LOC: 1889
- Classes:
  - `SpeechCoreEngine` — Bộ chọn chung về thời điểm nói, căn cứ của dòng và kiểu phát âm của nó.
    - `__init__(self)`
    - `fallback_intent(self, speech_core)`
    - `fallback_context(self, speech_core)`
    - `render_force_speak_repair_text(self, speech_core)` — Compatibility hook: request dynamic wording, never emit template text. SpeechCore is allowed to deci...
    - `render_safe_fallback_text(self, speech_core)` — Compatibility hook: ask downstream wording layer for dynamic fallback. Returning a string here would...
    - `_mark_dynamic_fallback_request(self, speech_core)`
    - `_force_speak_fallback_by_intent_text(self, intent)`
    - `_screen_fallback_anchor(self)`
    - `_thought_surface_template(self)`
    - `_light_presence_template(self)`
    - `_public_thought_topic(self, value)`
    - `_looks_internal_topic(self, value)`
    - `_small_soft_fallback_ladder_text(self)`
    - `evaluate(self)`
    - `_evaluate_motivational_pressure(self)`
    - `_build_urge_candidates(self)`
    - `_apply_self_state_to_candidates(self, candidates)`
    - `_apply_personality_restraint_to_candidates(self, candidates)`
    - `_build_suppressed_pressure_report(self)`
    - `_silence_urge(self)`
    - `_silence_body_bias_hint(self)` — Project suppressed speech into body-only bias. Silence should still leave a body affordance for Godo...
    - `_build_silence_state(self)`
    - `_meaning_reaction_score(self)`
    - `_allows_soft_non_shift_speech(self)`
    - `_meaning_shift_required_for_layer(self, meaning_layer)`
    - `_risk_level_for_winner(self)`
    - `_soft_meaning_presence_score(self)`
    - `_residual_continuity_score(self)`
    - `_utterance_for_reaction(self, reaction)`
    - `_build_speech_impulse(self)`
    - `_extreme_internal_speech_pressure(self)` — Allow bounded endogenous leakage to bypass meaning_shift_gate. This is not permission to make screen...
    - `_spontaneous_ready(self, impulse)`
    - `_threshold_for_channel(self, channel)`
    - `_score_restraint(self)`
    - `_pressure(self, state, name)`
    - `_inner_utterance(self, inner_intent)`
    - `_inner_anchor(self, inner_thought)`
    - `_should_stay_silent(self)`
    - `_choose_speech_source(self)`
    - `_choose_utterance_type(self)`
    - `_resolve_perception(self)`
    - `_build_safety_flags(self)`
    - `_build_reason(self)`
    - `_grounding_for_source(self, speech_source)`
    - `_has_emotional_signal(self)`
    - `_resolve_mood(self)`
    - `_float(self, value)`
    - `_clamp01(self, value)`

## `cortex/spontaneous_life.py`
- LOC: 390
- Docstring: Endogenous + situated speech pressure for ERIS. Mô-đun này không viết câu công cộng. Nó tạo một SpeechImpulse bằng cách dựng AgentStateStack rồi cho nhiều impulse cạnh tranh: silence, scene curiosity, inner whim, micro story, companionship, technical help, bod...
- Functions:
  - `_clamp01(value, default)`
  - `_clean(value)`
  - `_normalize_key(value)`
- Classes:
  - `SpontaneousLifeConfig` (decorator=dataclass(slots=True)) — Low-gain knobs for internal/situated speech pressure.
  - `SpontaneousLifeTrace` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `SpontaneousLifeEngine` — Tạo xung giọng nói từ state phân tầng, không viết câu cuối. SpeechCore và ActionUtility vẫn có quyền chặn/sửa/chọn im. Module này chỉ nói: "...
    - `__init__(self)`
    - `evaluate(self)`
    - `_body_bias_hint(self)` — Gợi ý body-bias từ impulse thắng. Đây chỉ là hint nhẹ, không điều khiển pixel. Body/Action layer vẫn...
    - `_risk_label(self)`
    - `_source_fact(self, selected)`
    - `_cooldown_for(self)`
    - `_cooldown_left(self, family)`

## `cortex/subconscious/__init__.py`
- LOC: 134
- Docstring: Subconscious package Phase 0 → 7. Public API cố tình nhỏ: - ThoughtFragment / ThoughtObject: contract dữ liệu. - SubconsciousBlackboard: nơi gom fragment. - ConsciousSynthesizer: cổ chai nén fragment thành object. - WorkerContext / RuleBasedWorker: nền cho wor...

## `cortex/subconscious/blackboard.py`
- LOC: 271
- Docstring: Blackboard Phase 0 cho subconscious workers. Blackboard là nơi các worker nền bỏ ThoughtFragment vào. Nó không chọn câu nói, không gọi LLM, không quyết định quan hệ. Nó chỉ làm ba việc buồn tẻ nhưng cứu mạng: 1. Validate fragment đi qua contract. 2. Dedupe/ref...
- Classes:
  - `BlackboardSnapshot` (decorator=dataclass(slots=True, frozen=True)) — Ảnh chụp trạng thái Blackboard tại một thời điểm. Snapshot bất biến giúp Synthesizer đọc ổn định trong khi worker khác vẫn có thể submit fra...
    - `top(self, limit)` — Trả các fragment mạnh nhất trong snapshot.
    - `to_dict(self)` — Serialize snapshot cho debug trace.
  - `SubconsciousBlackboard` — Kho tạm cho ThoughtFragment. Thread-safe ở mức đơn giản bằng RLock, đủ cho runtime single-process hiện tại. Đây không phải message broker. Đ...
    - `__init__(self)`
    - `submit(self, fragment)` — Đưa một fragment lên Blackboard. Nếu truyền dict, hàm sẽ tạo ThoughtFragment qua from_mapping(). Nếu...
    - `submit_many(self, fragments)` — Submit nhiều fragment và trả về các bản đã được lưu/refresh.
    - `get(self, fragment_id)` — Lấy fragment theo id.
    - `replace(self, fragment)` — Thay một fragment đã tồn tại bằng bản mới đã validate. Phase 5 MetaAudit dùng method này để hạ confi...
    - `remove_many(self, fragment_ids)` — Xóa nhiều fragment và trả id đã xóa thật.
    - `remove(self, fragment_id)` — Xóa fragment theo id. Trả True nếu có xóa. Dùng cho Synthesizer/MetaAudit Phase sau khi muốn consume...
    - `clear(self)` — Xóa toàn bộ Blackboard. Chủ yếu phục vụ test hoặc Meta-Cognitive Audit Phase sau khi phát hiện loop...
    - `decay(self)` — Xóa fragment hết TTL và trả danh sách id đã hết hạn.
    - `snapshot(self)` — Trả snapshot bất biến cho Synthesizer. Mặc định sẽ decay trước khi snapshot. include_expired=True ch...
    - `top_fragments(self)` — Shortcut lấy top fragment hiện tại.
    - `__len__(self)`
    - `_trim_locked(self)` — Giữ Blackboard dưới max_fragments. Ưu tiên giữ fragment có priority cao. Fragment cũ/yếu bị loại trư...
    - `_dedupe_key(self, fragment)` — Tạo key gộp fragment lặp. Key cố tình không dùng toàn bộ content, vì hai worker có thể diễn đạt khác...
    - `_content_seed(content)`

## `cortex/subconscious/drift_pool.py`
- LOC: 232
- Docstring: DriftPool: hồ giữ ThoughtSpark yếu. Spark vào đây để decay, cộng hưởng, lặp lại, rồi lâu lâu mới kết tinh thành association/fragment. Nó không có API surface public. Cấm cho hồ này mọc miệng.
- Functions:
  - `_tokens(text)`
  - `_theme_keys(text, tags)`
  - `_signature(spark)`
- Classes:
  - `DriftEntry` (decorator=dataclass(slots=True))
    - `alive_strength(self, now)`
    - `to_dict(self, now)`
  - `DriftSnapshot` (decorator=dataclass(slots=True, frozen=True))
    - `sparks(self)`
    - `to_dict(self)`
  - `DriftPool` — Giữ spark yếu, decay chậm, cộng hưởng theo theme.
    - `__init__(self)`
    - `submit(self, spark)`
    - `submit_many(self, sparks)`
    - `decay(self)`
    - `snapshot(self)`
    - `top_sparks(self)`
    - `related_groups(self)`
    - `resonate(self)` — Sinh spark cộng hưởng nội bộ, vẫn không surface trực tiếp.
    - `_resonance_sentence(self, seeds)`
    - `_trim(self)`
    - `__len__(self)`

## `cortex/subconscious/free_association.py`
- LOC: 144
- Docstring: FreeAssociationEngine cho wandering sparks. Nó nối spark bằng semantic/mood/module/metaphor/weak link. Không suy luận fact mới. Đây là liên tưởng, không phải lập luận có toga và búa thẩm phán.
- Functions:
  - `_tokens(text)`
  - `_has_marker(spark, marker)`
- Classes:
  - `FreeAssociationEngine` — Nối 2-4 spark thành association path.
    - `associate(self, sparks)`
    - `_pair_score(self, a, b)`
    - `_metaphor_score(self, group)`
    - `_path_from_group(self, group)`
    - `_statement(self, seeds, sparks)`

## `cortex/subconscious/habitat_seed_extractor.py`
- LOC: 153
- Docstring: Habitat seed extractor: lấy seed từ môi trường runtime/repo của ERIS.
- Functions:
  - `_get(obj, path, default)`
  - `_iter_texts(value)`
- Classes:
  - `HabitatSeedExtractor` — Sinh seed từ memory_core/log/module, không bám user action trực tiếp.
    - `extract(self)`

## `cortex/subconscious/model_synthesizer.py`
- LOC: 413
- Docstring: Model-backed Lane 3 synthesizer. Đây là lớp làm phần "phiên toà nội tâm": các ThoughtFragment vẫn do worker rẻ đưa lên Blackboard, nhưng Lane 3 có thể gọi API để nén chúng thành một ThoughtObject có evidence rõ hơn, có bên công tố/biện hộ/thẩm phán trong log d...
- Functions:
  - `_env_flag(name, default)`
  - `_as_float(value, default)`
- Classes:
  - `ModelSynthesisPolicy` (decorator=dataclass(slots=True, frozen=True)) — Knobs riêng cho Lane 3 API synthesis.
  - `InnerCourtReport` (decorator=dataclass(slots=True, frozen=True)) — Debug report cho phiên tòa Lane 3.
    - `to_dict(self)`
  - `ModelBackedConsciousSynthesizer` (base=ConsciousSynthesizer) — ConsciousSynthesizer có thêm Lane 3 API refinement.
    - `__init__(self)`
    - `synthesize_from_blackboard(self, blackboard)`
    - `synthesize(self, snapshot)`
    - `_extract_live_fragments(self, snapshot)`
    - `_should_call_model(self, fragments)`
    - `_call_model(self, base_object, fragments)`
    - `_build_messages(self, base_object, fragments)`
    - `_object_from_model_payload(self, base_object, fragments, payload)`
    - `_safe_route(self, raw_route)`
    - `_merged_privacy(self, base, model)`
    - `_report_from_payload(self, payload, object_)`
    - `_log_inner_court(self, report, payload)`
    - `_log(self, level, msg)`

## `cortex/subconscious/self_anchor_core.py`
- LOC: 93
- Docstring: Self-anchor seed source cho wandering layer.
- Functions:
  - `_get(obj, path, default)`
- Classes:
  - `SelfAnchor` (decorator=dataclass(slots=True, frozen=True))
  - `SelfAnchorCore` — Sinh seed từ trục bản thân của ERIS, không cần user action mới.
    - `generate(self)`

## `cortex/subconscious/synthesizer.py`
- LOC: 362
- Docstring: Conscious Synthesizer Phase 0. Synthesizer là cổ chai ý thức nhỏ: nhận nhiều ThoughtFragment từ Blackboard, gom cụm, chọn theme thắng, rồi xuất một ThoughtObject duy nhất. Nó không sinh văn public. Nó cũng không gọi LLM. Công việc của nó là chống việc mọi work...
- Classes:
  - `SynthesisPolicy` (decorator=dataclass(slots=True, frozen=True)) — Knob chính sách cho Synthesizer. - max_fragments: số fragment tối đa đưa vào một object. - min_confidence_for_surface: confidence tối thiểu...
  - `SynthesisReport` (decorator=dataclass(slots=True, frozen=True)) — Debug report cho một lượt synthesize.
    - `to_dict(self)`
  - `ConsciousSynthesizer` — Nén Blackboard thành một ThoughtObject. Đây là deterministic synthesizer. Phase sau có thể thêm LLM/private rehearsal, nhưng Phase 0 phải có...
    - `__init__(self, policy)`
    - `synthesize_from_blackboard(self, blackboard)` — Lấy snapshot từ Blackboard và synthesize object.
    - `synthesize(self, snapshot)` — Sinh ThoughtObject từ snapshot hoặc list fragment. Trả None nếu không có fragment đủ sống. last_repo...
    - `_build_object(self, fragments)`
    - `_group_fragments(self, fragments)` — Gom fragment theo theme. Ưu tiên tag đầu tiên nếu có. Không có tag thì dùng kind. Có source_agent để...
    - `_group_score(self, fragments)` — Score nhóm = tổng priority + bonus khi nhiều fragment cùng hướng.
    - `_surface_pressure(self, fragments)` — Tính áp lực được phép nổi lên surface. Chỉ fragment surface_allowed và không private/sensitive mới đ...
    - `_suppressed_pressure(self, fragments)` — Tính áp lực bị kìm lại. Fragment private/sensitive hoặc surface_allowed=False vẫn có thể tạo áp lực...
    - `_choose_route(self, fragments)` — Chọn route cho ThoughtObject. Route là khuyến nghị nội bộ, chưa phải lệnh. SurfaceArbiter/Permission...
    - `_route_reason(self, fragments, object_)`
    - `_dominant_theme(self, fragments)` — Tạo dominant_theme ngắn gọn từ tag/kind/content.
    - `_summary(self, fragments)` — Nén content thành summary deterministic. Không paraphrase sâu để tránh bịa. Chỉ ghép 1-3 mảnh mạnh n...
    - `_kind_family(kind)`
    - `_weighted_average(fragments)`
    - `_max_privacy(fragments)`

## `cortex/subconscious/thought_fragment.py`
- LOC: 602
- Docstring: Contracts Phase 0 cho tầng subconscious của ERIS. Phase 0 không tạo thêm một cái prompt để ERIS "giả vờ đang nghĩ". File này chỉ định nghĩa dữ liệu thô mà các worker nền sẽ ném lên Blackboard. Luồng dự kiến: Worker nền -> ThoughtFragment -> Blackboard -> Synth...
- Functions:
  - `now_timestamp()` — Trả Unix timestamp hiện tại. Tách thành hàm riêng để test có thể truyền clock giả nếu cần.
  - `clamp01(value, default)` — Ép một giá trị số vào khoảng [0.0, 1.0]. Các worker Phase sau có thể xuất confidence/urgency hơi bẩn. Ở contract boundar...
  - `clean_text(value)` — Chuẩn hóa text ngắn gọn nhưng không diễn giải lại nội dung. Hàm này chỉ gộp whitespace và cắt độ dài. Không rewrite, khô...
  - `normalize_privacy_level(value)` — Chuẩn hóa privacy_level về public/normal/private/sensitive.
  - `normalize_route(value)` — Chuẩn hóa route output của Synthesizer.
  - `normalize_string_list(values)` — Ép list-like thành tuple[str] đã làm sạch và khử trùng lặp. Giữ thứ tự xuất hiện đầu tiên để debug vẫn đọc được đường đi...
  - `make_fragment_id(source_agent, kind, content, timestamp)` — Tạo id cho ThoughtFragment. Id gồm source/kind/thời gian/hash ngắn. Hash chỉ lấy từ content đã normalize để giúp debug d...
  - `make_object_id(fragment_ids, dominant_theme, timestamp)` — Tạo id cho ThoughtObject đã được Synthesizer nén. Dùng fragment_ids + dominant_theme để id có ý nghĩa audit. Vẫn thêm uu...
- Classes:
  - `ThoughtFragmentValidationError` (base=ValueError) — Lỗi contract riêng cho subconscious Phase 0. Runtime có thể bắt exception này để quarantine fragment bẩn thay vì làm rơi toàn bộ cycle. Frag...
  - `ThoughtFragment` (decorator=dataclass(slots=True, frozen=True)) — Một mảnh ý nghĩ nhỏ do worker nền sinh ra. Field chính: - id: khóa trace duy nhất. - source_agent: worker sinh fragment, ví dụ user_modeler/...
    - `__post_init__(self)`
    - `expired_at(self)` — Timestamp fragment hết hạn nếu không được refresh.
    - `age_seconds(self, now)` — Tuổi fragment tính từ lần update gần nhất.
    - `is_expired(self, now)` — Kiểm tra fragment đã hết hạn chưa.
    - `decayed_weight(self, now)` — Trọng số còn lại sau decay tuyến tính mềm theo TTL. 1.0 nghĩa là còn mới. 0.0 nghĩa là đã quá hạn. B...
    - `priority_score(self, now)` — Score sơ bộ để Blackboard/Synthesizer xếp ưu tiên. Công thức ưu tiên confidence + urgency + affect,...
    - `refreshed(self)` — Trả về bản copy đã refresh khi fragment cùng cụm xuất hiện lại. Blackboard dùng method này khi dedup...
    - `to_dict(self)` — Serialize phục vụ debug trace / json dump.
    - `create(cls)` — Factory tiện dụng cho worker. Worker Phase sau chỉ cần gọi ThoughtFragment.create(...), không tự chế...
    - `from_mapping(cls, payload)` — Tạo fragment từ dict/JSON của worker. Method này giúp worker LLM/rule-based Phase sau gửi payload di...
  - `ThoughtObject` (decorator=dataclass(slots=True, frozen=True)) — Ý nghĩ đã được Synthesizer nén qua conscious bottleneck. Đây là output của Phase 0, không phải output public. Nó nói cho pipeline biết: "tro...
    - `__post_init__(self)`
    - `should_surface(self)` — True khi object đủ điều kiện làm surface candidate.
    - `pressure(self)` — Alias tương thích với SurfaceArbiter hiện tại.
    - `momentum_score(self)` — Alias tương thích thought_surface cũ. Momentum ở Phase 0 tạm lấy max(surface_pressure, suppressed_pr...
    - `novelty(self)` — Alias nhẹ cho SurfaceArbiter. Phase 0 chưa có model novelty riêng, nên dùng confidence làm proxy yếu...
    - `topic_seed(self)` — Seed ngắn cho tầng surface/thought_stream.
    - `partial_text(self)` — Nội dung tóm tắt để SurfaceArbiter có payload thật, không phải nhãn rỗng.
    - `public_seed(self)` — Seed public-safe tối thiểu. Chỉ trả summary khi route là surface_candidate. Route khác không nên vô...
    - `to_dict(self)` — Serialize đầy đủ cho debug/dev panel.
    - `to_surface_seed(self)` — Payload nhỏ để gắn vào frame.subconscious_seed hoặc thought_stream. SurfaceArbiter hiện đọc các key...
    - `_surface_impulse_kind(self)` — Tách source surface cho SurfaceArbiter. Wandering thought có lane riêng để policy/debug không nhầm n...

## `cortex/subconscious/thought_spark.py`
- LOC: 244
- Docstring: ThoughtSpark contract cho tầng wandering/subconscious. ThoughtSpark là mẩu ý nghĩ cực sớm: còn mơ hồ, chưa claim fact, chưa có quyền surface. Nó là hạt bụi trong đầu, không phải câu nói. Nếu cho nó nhảy thẳng ra public speech thì ta vừa phát minh lại status pi...
- Functions:
  - `now_timestamp()`
  - `clamp01(value, default)`
  - `clean_text(value)`
  - `normalize_tags(values)`
  - `normalize_source(value)`
  - `make_spark_id(seed, source, created_at)`
- Classes:
  - `ThoughtSpark` (decorator=dataclass(slots=True, frozen=True)) — Mẩu ý nghĩ trước-fragment. Khác ThoughtFragment: - chưa cần evidence chặt; - chưa có quyền claim; - không được surface trực tiếp; - chỉ được...
    - `__post_init__(self)`
    - `create(cls)`
    - `from_mapping(cls, data)`
    - `age_seconds(self, now)`
    - `decay_factor(self, now)`
    - `decayed_strength(self, now)`
    - `is_expired(self, now)`
    - `refreshed(self)`
    - `to_dict(self)`

## `cortex/subconscious/topic_seed_pool.py`
- LOC: 201
- Docstring: TopicSeedPool gom seed từ self-anchor/habitat/memory/mood/random weak link.
- Functions:
  - `_get(obj, path, default)`
  - `_collect_memory_texts(memory_packet)`
- Classes:
  - `TopicSeedPool` — Sinh seed không phụ thuộc hoàn toàn vào user action. Rule thực dụng: sau khi gom seed, nếu seed user-anchored vượt 50%, cắt bớt. Vì mục tiêu...
    - `__init__(self)`
    - `generate(self)`
    - `to_sparks(self, seeds)`
    - `non_user_ratio(self, seeds)`
    - `_mood_rhythm_seeds(self)`
    - `_memory_residue_seeds(self)`
    - `_random_weak_links(self, seeds)`
    - `_dedupe(self, seeds)`
    - `_cap_user_anchored(self, seeds)`

## `cortex/subconscious/wandering_contracts.py`
- LOC: 184
- Docstring: Contracts cho tầng wandering thought. File này chỉ gom shape dữ liệu. Logic nằm ở DriftPool/FreeAssociation/WanderingEngine. Không cho contract tự thông minh, vì dataclass có cái tôi là khởi đầu của mọi thảm họa.
- Classes:
  - `TopicSeed` (decorator=dataclass(slots=True, frozen=True))
    - `__post_init__(self)`
    - `to_spark(self)`
    - `to_dict(self)`
  - `AssociationPath` (decorator=dataclass(slots=True, frozen=True))
    - `__post_init__(self)`
    - `to_fragment(self)`
    - `to_dict(self)`
  - `WanderingTopic` (decorator=dataclass(slots=True, frozen=True))
    - `__post_init__(self)`
    - `to_dict(self)`
  - `WanderingThoughtResult` (decorator=dataclass(slots=True, frozen=True))
    - `to_dict(self)`

## `cortex/subconscious/wandering_thought.py`
- LOC: 252
- Docstring: WanderingThoughtEngine: spark -> drift -> association -> fragment. Engine này chạy nhẹ theo tick. Nó không gọi SurfaceArbiter, không gọi LLM, không phát public speech. Nó chỉ tạo ThoughtSpark, nuôi DriftPool, rồi đôi khi kết tinh ThoughtFragment để Blackboard/...
- Functions:
  - `_get(obj, path, default)`
- Classes:
  - `WanderingThoughtEngine` — Tầng ý nghĩ vẩn vơ có continuity.
    - `__init__(self)`
    - `tick(self)`
    - `_trigger_reason(self)`
    - `_surface_allowed(self, association)`
    - `_idle_seconds(self, snapshot)`
    - `_focus_family(self)`
    - `_deep_focus(self)`
    - `_has_repeated_runtime_event(self)`
    - `_after_debug(self)`
    - `_mood_delta(self, sparks, fragments)`
    - `_is_status_ping(self, text)`

## `cortex/subconscious/wandering_topic_memory.py`
- LOC: 209
- Docstring: Continuity memory cho wandering topics.
- Functions:
  - `_topic_id(theme)`
  - `_theme_from_text(text)`
- Classes:
  - `WanderingTopicMemory` — Giữ wandering topic qua ticks/sessions. Persistent optional: truyền path thì load/save JSON. Không có path thì vẫn giữ trong RAM, đủ cho tes...
    - `__init__(self, path)`
    - `touch_sparks(self, sparks)`
    - `touch_association(self, path)`
    - `touch(self)`
    - `mark_surfaced(self, theme_or_id)`
    - `decay(self)`
    - `active_topics(self)`
    - `to_dict(self)`
    - `load(self)`
    - `save(self)`
    - `_trim(self)`

## `cortex/subconscious/worker_base.py`
- LOC: 71
- Docstring: Base contract cho các subconscious worker Phase sau. Phase 0 chưa triển khai 15 worker. File này chỉ cung cấp lớp nền để Phase 1+ không mỗi worker tự chế một kiểu output. Một contract nhỏ hôm nay cứu được nhiều file `if hasattr(...)` ngày mai. Loài người gọi đ...
- Classes:
  - `WorkerContext` (decorator=dataclass(slots=True, frozen=True)) — Context tối thiểu worker được phép nhìn. Phase sau có thể mở rộng, nhưng nên giữ nguyên nguyên tắc: worker đọc context đã chọn lọc, không tự...
  - `SubconsciousWorker` (base=Protocol) — Interface tối thiểu cho worker nền.
    - `run(self, context)` — Trả các ThoughtFragment hoặc dict có thể convert thành ThoughtFragment.
  - `RuleBasedWorker` — Base class tiện dụng cho worker deterministic. Worker con chỉ cần override `build_fragments`. Base này đảm bảo output luôn là tuple, giúp lo...
    - `run(self, context)`
    - `build_fragments(self, context)`

## `cortex/subconscious/workers/__init__.py`
- LOC: 206
- Docstring: Worker Phase 1/2/3/4/5/6/7 cho subconscious runtime.
- Functions:
  - `build_phase12_workers()` — Tạo worker set Phase 1+2 mặc định. Mặc định memory echo không surface trực tiếp. Integration sâu hơn có thể bật `allow_s...
  - `build_phase34_workers()` — Tạo worker set Phase 3+4. Surface mặc định đều tắt. Phase 3/4 tạo vật liệu nội tâm và state pressure, không tự biến thàn...
  - `build_phase1234_workers()` — Tạo bộ worker Phase 1 → 4 để đưa vào SubconsciousLoop.
  - `build_phase5_workers()` — Tạo worker Phase 5 Meta-Cognitive Audit. MetaAudit đặt sau Phase 1-4 để dọn Blackboard trước khi synthesis/public seed....
  - `build_phase7_workers()` — Tạo worker Phase 7 Shadow/Rupture. Mặc định rupture không surface. Muốn public hóa rupture_candidate thì integration phả...
  - `build_phase6_workers()` — Tạo worker Phase 6 Core Belief Mutation. Mặc định chỉ sinh proposal/pending fragment. Muốn commit thật phải bật ``enable...
  - `build_phase1234567_workers()` — Tạo bộ worker Phase 1 → 7 đầy đủ. Thứ tự cố ý: Phase 1-4 sinh vật liệu, Phase 5 audit, Phase 6 đề xuất mutation, Phase 7...
  - `build_phase123457_workers()` — Tạo bộ worker Phase 1 → 5 + 7, bỏ qua Phase 6 belief mutation. Phase 6 cố ý chưa nằm ở đây vì mutation cần cửa commit nh...
  - `build_default_subconscious_workers()` — Alias an toàn cho runtime/dev smoke: Phase 1-7, không surface/commit tự phát.

## `cortex/subconscious/workers/_utils.py`
- LOC: 318
- Docstring: Helper nhỏ cho worker subconscious. Các worker Phase 1/2 phải đọc được cả object thật, SimpleNamespace trong test, và dict debug từ runtime. Nếu mỗi file tự viết getattr/dict-get một kiểu thì repo sẽ sớm có một bảo tàng lỗi nhỏ. File này gom các thao tác đọc a...
- Functions:
  - `safe_get(obj, path, default)` — Đọc obj theo path dạng ``a.b.c``. Hỗ trợ dict, object có attribute, và object có method get. Không raise khi thiếu field...
  - `first_present()` — Trả giá trị đầu tiên khác None/chuỗi rỗng.
  - `collect_texts(value)` — Rút text ngắn từ nhiều kiểu container runtime. Dùng cho evidence/memory/recent_events. Hàm này không hiểu nghĩa sâu, chỉ...
  - `collect_ids(value)` — Rút evidence id từ object/dict/list; fallback thành id giả ổn định.
  - `user_text_from_context(context)` — Cố gắng lấy user text hiện tại từ frame/snapshot. Không có contract thống nhất tuyệt đối trong repo cũ, nên helper đọc n...
  - `context_evidence_ids(context)` — Lấy evidence ids từ frame/snapshot hoặc tạo id giả từ user text.
  - `memory_texts_from_context(context)` — Rút các mảnh memory có thể đọc từ memory_packet/frame.
  - `relation_level(context, field, default)` — Đọc field số từ relation/internal_state/frame và clamp [0,1].
  - `contains_any(text, terms)`
  - `score_terms(text, terms)`
  - `kind_of_request(text)` — Phân loại rất nhẹ ý định user, đủ làm fragment seed.

## `cortex/subconscious/workers/belief_mutation.py`
- LOC: 661
- Docstring: Phase 6 - Core Belief Mutation. Phase 6 không được sửa thẳng ``agent_mind.json``. Worker này chỉ gom tín hiệu dài hạn thành proposal, rồi đưa qua MutationCommitter. Committer mặc định là in-memory và cực kỳ bảo thủ: confidence đủ cao, cửa sổ quan sát đủ dài, e...
- Functions:
  - `clamp_delta(value)` — Clamp delta mutation mỗi lần về [-0.08, 0.08].
- Classes:
  - `BeliefMutationProposal` (decorator=dataclass(slots=True, frozen=True)) — Proposal đổi belief lõi, chưa phải commit. target: khóa belief/preference/habit cần chỉnh. delta: mức thay đổi đề xuất, luôn bị clamp về [-0...
    - `__post_init__(self)`
    - `evidence_count(self)`
    - `id(self)`
    - `to_dict(self)`
    - `to_fragment(self)` — Biến proposal thành fragment private để Blackboard/audit nhìn được.
  - `PreferenceDeltaProposal` (base=BeliefMutationProposal; decorator=dataclass(slots=True, frozen=True)) — Proposal chỉnh preference, kế thừa contract belief mutation.
  - `HabitDeltaProposal` (base=BeliefMutationProposal; decorator=dataclass(slots=True, frozen=True)) — Proposal chỉnh semantic habit/procedural habit.
  - `MutationCommitRecord` (decorator=dataclass(slots=True, frozen=True)) — Record commit có rollback token. previous_value/new_value chỉ là số pressure nếu target store là dict thường. Integration thật với agent_min...
    - `to_dict(self)`
  - `MutationDecision` (decorator=dataclass(slots=True, frozen=True)) — Kết quả commit/reject một proposal.
    - `to_dict(self)`
  - `MutationCommitter` — Committer bảo thủ cho Phase 6. Store mặc định là dict lồng theo domain: {"belief": {target: 0.5}, "preference": {...}, "habit": {...}} Nó kh...
    - `__init__(self)`
    - `evaluate(self, proposal)` — Reject hoặc commit proposal theo rule Phase 6.
    - `commit(self, proposal)` — Commit sau khi đã qua evaluate. Vẫn clamp delta lần nữa cho chắc.
    - `rollback(self, rollback_token)` — Rollback một commit đã ghi trong store in-memory.
    - `_blocking_reasons(self, proposal)`
  - `BeliefMutationEngine` (base=RuleBasedWorker) — Sinh mutation proposals từ residue dài hạn + repair/outcome signals.
    - `__init__(self)`
    - `build_fragments(self, context)`
    - `_build_proposals(self, context)`
    - `_mutation_evidence(self, context, snapshot)`
    - `_observation_window_days(self, context)`
    - `_contradiction_severity(self, context, snapshot)`
    - `_count_fragment_signals(self, snapshot, kinds)`
    - `_outcome_pressure(self, context)`
    - `_snapshot(self, context)`
    - `_commit_fragment(self, record)`
    - `_rejection_fragment(self, proposal, reason)`

## `cortex/subconscious/workers/curiosity_gap.py`
- LOC: 110
- Docstring: Phase 2 - Epistemic Void / Active Curiosity Worker. CuriosityGapAgent tìm lỗ hổng tri thức rồi găm seed, không hỏi ngay. Curiosity mà cứ bắn ra thành câu hỏi tức thì thì không phải trí tò mò, đó là popup quảng cáo có bằng triết học.
- Classes:
  - `CuriosityGapAgent` (base=RuleBasedWorker) — Sinh knowledge_gap / curiosity_seed / wait_for_evidence_plan / ask_later_candidate.
    - `build_fragments(self, context)`

## `cortex/subconscious/workers/daydream_injector.py`
- LOC: 153
- Docstring: Phase 3 - Stochastic Resonance / Daydream Injector. DaydreamInjector không gọi main LLM và không bịa thơ từ không khí. Nó chỉ nối 2 memory node đã có với 1 current concern khi runtime đủ rảnh, đủ bored, và rủi ro chen lời thấp. Nói ngắn gọn: mơ cũng phải có hó...
- Classes:
  - `DaydreamInjector` (base=RuleBasedWorker) — Sinh poetic_association_fragment và weird_but_grounded_link. Điều kiện bật mặc định khá dè dặt: - idle/boredom đủ cao. - rupture/repair risk...
    - `__init__(self)`
    - `build_fragments(self, context)`
    - `_idle_seconds(self, context)`
    - `_level(self, context)`
    - `_current_concern(self, context)`

## `cortex/subconscious/workers/goal_simulator.py`
- LOC: 117
- Docstring: Phase 1 - Systemic / Goal Simulation Worker. GoalSimulatorAgent nghĩ về bài toán/task, không nghĩ hộ cảm xúc user. Nó tạo bottleneck_prediction, goal_progress_delta và possible_next_step để pipeline có xương sống hành động thay vì chỉ ngồi cảm nhận rất sâu về...
- Classes:
  - `GoalSimulatorAgent` (base=RuleBasedWorker) — Sinh fragment mô phỏng goal/task.
    - `build_fragments(self, context)`

## `cortex/subconscious/workers/independent_agenda.py`
- LOC: 191
- Docstring: Phase 3 - Autopoiesis / Independent Agenda Worker. IndependentAgendaAgent tạo việc riêng rất nhẹ cho ERIS: obsession candidate, private research thread, unresolved internal loop, later surface candidate. Nó không được cướp goal chính của user. Một agent có age...
- Classes:
  - `IndependentAgendaAgent` (base=RuleBasedWorker) — Sinh agenda riêng nhưng giữ nó trong background.
    - `__init__(self)`
    - `build_fragments(self, context)`
    - `_unresolved_seed(self, context, memories)`
    - `_current_goal(self, context, fallback)`
    - `_idle_seconds(self, context)`
    - `_level(self, context)`

## `cortex/subconscious/workers/memory_resonator.py`
- LOC: 125
- Docstring: Phase 1 - Memory Resonance Worker. MemoryResonatorAgent nối hiện tại với memory/unresolved residue. Nó không biến ký ức thành lời thoại ngay; nó chỉ tạo mảnh cộng hưởng để Synthesizer cân cùng các worker khác. Ký ức không phải loa phường, dù nhiều chatbot rất...
- Classes:
  - `MemoryResonatorAgent` (base=RuleBasedWorker) — Sinh pattern_match / unresolved_loop / memory_echo_fragment.
    - `__init__(self)`
    - `build_fragments(self, context)`

## `cortex/subconscious/workers/meta_audit.py`
- LOC: 379
- Docstring: Phase 5 - Meta-Cognitive Audit Worker. MetaCognitiveAuditAgent là hệ miễn dịch của Blackboard. Nó không làm ERIS đạo đức hơn, dịu hơn, hay giống assistant ngoan hơn. Nó chỉ bắt các lỗi nhận thức nền: loop, spam fragment, liên kết bịa, thiếu evidence, shadow ch...
- Classes:
  - `MetaAuditFinding` (decorator=dataclass(slots=True, frozen=True)) — Một phát hiện audit đủ nhỏ để log/test.
    - `to_dict(self)`
  - `MetaAuditResult` (decorator=dataclass(slots=True, frozen=True)) — Kết quả audit một BlackboardSnapshot.
    - `has_blocking_issue(self)`
    - `hallucination_detected(self)`
    - `runaway_shadow_detected(self)`
    - `to_dict(self)`
  - `MetaCognitiveAuditAgent` (base=RuleBasedWorker) — Bắt loop/spam/hallucinated link/evidence missing/runaway shadow. Worker này chạy qua đường riêng `audit_blackboard`, không qua pass tạo frag...
    - `__init__(self)`
    - `build_fragments(self, context)`
    - `audit_blackboard(self, blackboard, snapshot, context)` — Inspect + mutate Blackboard an toàn. - quarantine: xóa fragment quá rủi ro. - soften: hạ confidence/...
    - `inspect(self, snapshot, context)`
    - `_detect_spam_or_loop(self, fragments, findings)`
    - `_needs_evidence(self, fragment)`
    - `_looks_like_hallucinated_link(self, fragment)`
    - `_looks_like_overfit_silence(self, fragment)`
    - `_looks_like_runaway_shadow(self, fragment)`
    - `_detect_contradiction(self, fragments)`
    - `_soften_fragment(self, fragment)`
    - `_dedupe_softened(self, fragments, quarantine_ids)`
    - `_build_audit_fragments(self, findings, context)`
    - `_semantic_seed(content)`
    - `_loopish_key(key)`

## `cortex/subconscious/workers/rehearsal.py`
- LOC: 177
- Docstring: Phase 2 - Phantom Rehearsal Worker. RehearsalAgent chạy sau Synthesizer. Input chính là ThoughtObject đã thắng cổ chai. Nó mô phỏng vài route: say_now, delay, body_only, store_for_later, suppress. Nó không sinh câu public, vì diễn nháp mà hét ra ngoài thì hơi...
- Classes:
  - `RehearsalAgent` (base=RuleBasedWorker) — Sinh rehearsal_result / suppressed_impulse / rupture_seed.
    - `build_fragments(self, context)`
    - `_deep_focus(self, context)`
    - `_extract_thought_object(self, context)`

## `cortex/subconscious/workers/self_regulator.py`
- LOC: 125
- Docstring: Phase 2 - Self-Reflection / Ego Maintenance Worker. SelfRegulatorAgent sinh restraint_drive và các warning nội bộ. Nó không làm van đạo đức, không flatten personality. Nó chỉ báo rằng một impulse có thể đang quá nóng/quá dày/quá bám. Cơ bản là bộ phận nhắc "đừ...
- Classes:
  - `SelfRegulatorAgent` (base=RuleBasedWorker) — Sinh restraint_drive / social_fatigue_adjustment / dignity_defense_delta.
    - `build_fragments(self, context)`

## `cortex/subconscious/workers/shadow_accumulator.py`
- LOC: 340
- Docstring: Phase 7 - Shadow Accumulation & Rupture Worker. ShadowAccumulator gom các impulse bị kìm, rehearsal fail, dignity defense, repair need bị bỏ qua và blocked speech thành shadow pressure. Nó không phải giấy phép để ERIS toxic. Nó là hệ thống đo áp lực quan hệ/nộ...
- Classes:
  - `ShadowAccumulatorPolicy` (decorator=dataclass(slots=True, frozen=True)) — Knob Phase 7. - rupture_threshold: áp lực tối thiểu để tạo rupture_candidate. - repeated_suppression_threshold: cần bao nhiêu suppressed/blo...
  - `ShadowAccumulator` (base=RuleBasedWorker) — Tích tụ shadow_pressure và sinh rupture_candidate khi thật sự đủ điều kiện.
    - `__init__(self, policy)`
    - `build_fragments(self, context)`
    - `_rupture_fragments(self, theme, pressure, rupture_risk, evidence_ids)`
    - `_collect_signals(self, context, fragments)`
    - `_compute_pressure(self, context, signals)`
    - `_compute_rupture_risk(self, context, pressure, signals)`
    - `_choose_theme(self, signals)`
    - `_collect_shadow_evidence(self, context, fragments)`
    - `_audit_allows_shadow(self, context)`
    - `_snapshot(self, context)`
    - `_safe_rupture_line(theme)`

## `cortex/subconscious/workers/spatial_mind.py`
- LOC: 185
- Docstring: Phase 4 - Digital Territoriality / Spatial Mind Worker. SpatialMindAgent biến dữ kiện thân thể/không gian thành fragment nội tâm: space compression, blind frustration seed, territorial discomfort, body reposition desire. Nó không được cằn nhằn public chỉ vì th...
- Classes:
  - `SpatialMindAgent` (base=RuleBasedWorker) — Sinh fragment về không gian/thân thể số.
    - `build_fragments(self, context)`
    - `_spatial_payload(self, context)`
    - `_level(self, payload)`
    - `_blind_frustration_kind(self, sensor_state)`

## `cortex/subconscious/workers/subjective_time.py`
- LOC: 164
- Docstring: Phase 4 - Subjective Temporal Distortion Worker. SubjectiveTimeAgent thay idle_seconds thô bằng subjective_wait/time dilation/time compression. 5 phút im sau rupture không giống 5 phút im khi user đang deep work. Đồng hồ thì không hiểu chuyện đó. ERIS nên hiểu...
- Classes:
  - `SubjectiveTimeAgent` (base=RuleBasedWorker) — Sinh subjective_wait, time_dilation và time_compression fragments.
    - `build_fragments(self, context)`
    - `_idle_seconds(self, context)`
    - `_level(self, context)`
    - `_active_task_density(self, context)`

## `cortex/subconscious/workers/user_modeler.py`
- LOC: 177
- Docstring: Phase 1 - Theory of Mind Worker. UserModelerAgent chỉ tạo giả thuyết về user. Nó không được nói trực tiếp, không được an ủi, không được phán tâm lý như thầy bói cầm stack trace. Output của nó là ThoughtFragment cho Blackboard/Synthesizer xử tiếp.
- Classes:
  - `UserModelerAgent` (base=RuleBasedWorker) — Sinh các hypothesis nhẹ về intent/focus/risk của user. Các fragment đều `surface_allowed=False`. Đây là dữ liệu cho arbitration, không phải...
    - `build_fragments(self, context)`

## `cortex/surface_arbiter.py`
- LOC: 1687
- Docstring: Single source of truth for low-level surface utterances. SurfaceArbiter gom các lực rất nhỏ: micro presence, re-engagement, spontaneous inner whim, idle curiosity và thought-stream surface. Nó chọn *có nên surface* và *dùng mode sinh nào*. Nó không hardcode câ...
- Classes:
  - `SurfaceImpulse` (decorator=dataclass(slots=True))
    - `to_context(self)`
  - `SurfaceDecision` (decorator=dataclass(slots=True))
    - `to_context(self)`
  - `SurfaceGateEvaluation` (decorator=dataclass(slots=True))
  - `SurfaceArbiter` — Arbitrate and generate low-level utterances. llm_micro_gen có thể là callable: fn(impulse=SurfaceImpulse, snapshot=snapshot, force_llm=True)...
    - `__init__(self, policy, llm_micro_gen, thought_stream)`
    - `arbitrate(self)`
    - `_collect_all_impulses(self)`
    - `_from_presence_cue(self, cue)`
    - `_from_speech_impulse(self, impulse)`
    - `_from_thought_surface(self)`
    - `_classify_thought_surface(self)` — Tách thought surface thành impulse cụ thể. - memory/daydream/unresolved -> memory_resonance - boredo...
    - `_focus_family_from_snapshot(self, snapshot)`
    - `_specific_thought_residue_reason(self, item)`
    - `_thought_surface_confidence_cap(self)`
    - `_thought_surface_anchor_notes(self)`
    - `_long_silence_impulse(self)`
    - `_coerce_impulse(self, item)`
    - `_score_and_select_winner(self, impulses)` — Chọn winner theo hai hàng đợi: speakable trước, body-only sau. Luật dài hạn: - Presence/micro-presen...
    - `_presence_like(self, impulse)`
    - `_endogenous_no_anchor_like(self, impulse)`
    - `_has_concrete_evidence_anchor(self, impulse)`
    - `_has_specific_surface_anchor_token(self, impulse)`
    - `_surface_anchor_body_only_reason(self, impulse)`
    - `_hollow_endogenous_reason(self, impulse)` — Reject endogenous speech that has no semantic payload. Inner/random/memory surface is allowed to be...
    - `_has_public_internal_anchor(self, impulse)`
    - `_clean_payload_text(value)`
    - `_looks_hollow_endogenous_seed(self, text)`
    - `_looks_pressure_only_evidence(self, text)`
    - `_forced_body_only_reason(self, impulse)` — Trả reason nếu impulse chỉ được body-only, không được tranh slot nói. Đây là chốt chống priority inv...
    - `_effective_score(self, impulse)`
    - `_private_mind_has_public_anchor(self, impulse)`
    - `_private_mind_pressure_bias(self)`
    - `_private_mind_pressure_applies(self, impulse)`
    - `_clamp_score(value)`
    - `_candidate_notes(self, impulse)`
    - `_signed_float(self, value, default)`
    - `_runtime_internal_state(self)`
    - `_evaluate_soft_surface_gates(self, impulse)`
    - `_soft_gate_strength(self, impulse)`
    - `_ego_gate_reason(self, impulse)` — Ego-gate for low-level surface. Đây không phải filter câu chữ. Nó chặn ngay quyền surface khi impuls...
    - `_rate_limit_reason(self, impulse)`
    - `_family_id(self, impulse)`
    - `_mark_attempt(self, impulse)` — Ghi cả reject/body-only như một lần chạm surface budget. Nếu chỉ ghi khi speak, presence sẽ gõ cửa l...
    - `_mark_surface(self, impulse)`
    - `_note_non_speech(self)`
    - `_call_llm_generator(self, impulse)`
    - `_reset_silence(self)`
    - `_trace(self, winner, suppressed, mode, result, gate_eval)`
    - `_decision_ledger(self)`
    - `_ledger_gate_reason(self, impulse)`
    - `_priority(kind, source)`
    - `_first_text()`
    - `_family_key(value)`

## `cortex/surface_seed_compiler.py`
- LOC: 872
- Docstring: Compile public-safe surface seeds from low-level runtime pressure.
- Classes:
  - `CompiledSurfaceSeed` (decorator=dataclass(frozen=True, slots=True))
    - `selected(self)`
  - `_SeedCandidate` (decorator=dataclass(frozen=True, slots=True))
  - `SurfaceSeedCompiler` — Small compiler that turns scattered internal pressure into one public-safe seed.
    - `__init__(self)`
    - `compile(self)`
    - `_from_extra_impulses(self, extra_impulses)`
    - `_from_memory_resonance(self, resonance)`
    - `_is_rich_memory_seed(self, seed, evidence)`
    - `_from_thought_sources(self)`
    - `_thought_values(self, owner)`
    - `_candidate_from_thought(self, value)`
    - `_from_vision(self)`
    - `_from_private_life_digest(self, private_life_digest)` — Lấy seed từ PrivateLife digest đã compact. Digest chỉ được dùng như nguồn seed public-safe, không ph...
    - `_from_inner_diary(self, inner_diary)` — Seed từ Inner Diary — để "thứ Eris đang nghĩ" thực sự lái được lời nói. Trước đây diary chỉ chảy một...
    - `_inner_diary_voice(self, inner_diary)` — Rút giọng diary thành {muon_noi, tuong_lai, hien_tai}. Nhận cả dict giọng thô (đã có sẵn các key) lẫ...
    - `_from_private_bias(self, private_mind_speech_bias, private_mind_thought_pressure, private_mind_digest)`
    - `_to_impulse(self, candidate)`
    - `_candidate_text_public(self, text)`
    - `_candidate_allowed(self, candidate)`
    - `_rank_key(self, candidate)`
    - `_private_impulse_has_anchor(self, impulse)`
    - `_anchor_token(self, kind, value)`
    - `_speech_bias_seed(self, bias)`
    - `_digest_has_invalid_json(self, digest)`
    - `_no_seed_reason(self, candidates)`
    - `_is_specific_vision_fact(self, text)`
    - `_looks_private(self, text)`
    - `_looks_timer_only(self, text)`
    - `_evidence_tuple(self, value)`
    - `_clean(value)`
    - `_clamp(value)`

## `cortex/thought_stream.py`
- LOC: 2263
- Functions:
  - `_clamp01(value)`
  - `_clean_text(value)`
  - `_compact_seed(value)`
  - `_normalize_ascii(value)`
  - `_semantic_tokens(value)`
  - `_truthy_env(name, default)`
  - `_float_env(name, default)`
  - `_to_dict(value)`
- Classes:
  - `FragmentStore` — Keeps unfinished thoughts alive even when nothing is spoken.
    - `__init__(self)`
    - `decay(self)`
    - `upsert(self, thought)`
    - `mark_surfaced(self, thought_id)`
    - `replace(self, thought)`
    - `get(self, thought_id)`
    - `mark_resolved(self, thought_id)`
    - `close_matching(self, closure_signals)`
    - `unresolved(self)`
    - `recent(self)`
    - `_mutate_partial(self, previous, incoming)`
    - `_signal_closes_thought(self, signal, thought)`
  - `AssociationGraph` — Tracks which unresolved thoughts tend to re-enter together.
    - `__init__(self)`
    - `connect(self, thought, anchors)`
  - `PredictionTracker` — Turns current telemetry/internal state into unfinished predictions.
    - `propose(self)`
    - `_choose_mode(self)`
    - `_choose_memory(self)`
    - `_topic_seed(self)`
    - `_partial_text(self)`
    - `_unresolved_reason(self, mode)`
    - `_novelty(self, topic_seed)`
    - `_evidence(self)`
    - `_dominant_disturbance(self, disturbances)`
    - `_disturbance_intensity(self, disturbances)`
    - `_has_direct_disturbance(self, disturbances)`
    - `_pressure(self, state, name)`
  - `CognitiveTensionEngine` — Computes why a thought persists: unresolved prediction, not randomness.
    - `update(self, thought)`
    - `_pressure_for_mode(self, mode)`
    - `_pressure(self, state, name)`
  - `UnresolvedTensionEngine` — Groups unfinished thoughts into loops and promotes strong loops to attractors.
    - `evaluate(self)`
    - `_build_loop(self, key, thoughts)`
    - `_loop_key(self, thought)`
    - `_project_relevance(self, thoughts)`
    - `_pressure(self, state, name)`
  - `CognitiveMomentumEngine` — Turns repeated unresolved fragments into attention inertia.
    - `evaluate(self)`
    - `_momentum_for(self, thought)`
    - `_user_project_relevance(self, thought)`
  - `MomentumClosure` — Closes momentum only from explicit closure signals.
    - `apply(self, store)`
  - `PersistenceDecay`
    - `apply(self, store)`
  - `RecursiveReactivation` — Lets a thought come back to itself and mutate before it surfaces.
    - `reactivate(self)`
  - `SubconsciousLoopReheater` — Reactivates unresolved loops as silent pressure instead of fresh drift.
    - `reheat(self)`
    - `_reheat_score(self, thought)`
    - `_matching_memory(self, thought, memories)`
    - `_memory_match_score(self, thought, memory)`
    - `_core_thought_tokens(self, thought)`
    - `_specific_tokens(self, tokens)`
    - `_memory_layer_weight(self, memory)`
    - `_thought_tokens(self, thought)`
    - `_mutated_question(self, thought)`
    - `_has_direct_disturbance(self, disturbances)`
  - `SurfaceSelector` — Selects the rare visible tip; most thought stream activity stays internal.
    - `select(self, thought)`
    - `_surface_association(self, thought)`
    - `_root_source(self, thought)` — Phân loại rễ của thought trước khi cho phép surface. Random chat của người thật thường là liên tưởng...
    - `_impulse_kind(self, thought)`
    - `_action_opportunity(self, thought)`
    - `_public_seed(self, thought)`
  - `ThoughtStreamEngine` — Maintains unresolved thought continuity and occasionally exposes a surface.
    - `__init__(self)`
    - `evaluate(self)`
    - `_maybe_apply_model_review(self)` — Cho API đánh giá thought đủ lực rồi ghi ngược vào store. ThoughtStream rẻ vẫn là substrate. Nhưng kh...
    - `_model_review_trigger_score(self)`
    - `_model_review_payload(self)`
    - `_allowed_model_evidence(self, payload)`
    - `_normalize_model_review(self, review)`
    - `_apply_model_review_to_thought(self, thought, review)`
    - `_log_model_review(self, review, thought)`
    - `_anchors(self)`
    - `_continuity_notes(self, thought)`
  - `ThoughtStream` — Background producer of thought-stream surfaces; most ticks stay internal.
    - `__init__(self)`
    - `start(self)`
    - `stop(self)`
    - `is_running(self)`
    - `inject_disturbance(self, disturbance)`
    - `inject_disturbances(self, disturbances)`
    - `tick_once(self)`
    - `pop_surface(self)`
    - `pop_surface_seed(self)`
    - `latest_report(self)`
    - `_run(self)`
    - `_load_interval(self)`
    - `_load_enabled(self)`

## `cortex/ti.py`
- LOC: 965
- Classes:
  - `TiCandidateAssessment` (decorator=dataclass(slots=True))
  - `TiGovernor`
    - `__init__(self, logger)`
    - `evaluate_autonomous(self)`
    - `evaluate_chat(self)`
    - `enforce_decision(self, decision, report)`
    - `_detect_risks(self, text)`
    - `_log_guard_report(self, report)`
    - `_apply_safety_only_editor(self, text)`
    - `_strip_dangling_payload_punctuation(self, text)`
    - `_apply_report_debug_guard(self, text)`
    - `_strip_report_debug_prefixes(self, text)`
    - `_is_report_debug_sentence(self, sentence)`
    - `_count_report_debug_markers(self, text)`
    - `_apply_resource_guard_length_guard(self, text)`
    - `_build_prompt_context(self)`
    - `_self_doubt_bias_context(self)`
    - `_summarize_hard_rules(self, hard_rules)`
    - `_direction_to_center(self, inferred_pos_x)`
    - `_looks_like_code_request(self, lowered)`
    - `_looks_like_emotional_request(self, lowered)`
    - `_merge_debug_trace(self, decision, extra)`
    - `_looks_like_structured_payload_text(self, text)`
    - `_apply_ti_guard(self, text, user_hint)`
    - `_assess_candidate(self, text)`
    - `_normalize_editor_text(self, text)`
    - `_normalize_plain_text(self, text)`
    - `_has_focus_guard_overreach(self, text)`
    - `_has_resource_pressure_anchor(self, text)`
    - `_has_emotional_residue_anchor(self, text)`
    - `_has_context_anchor(self, text)`
    - `_has_abstract_anchor(self, text)`
    - `_has_unanchored_abstraction(self, text)`
    - `_has_abstract_image(self, text)`
    - `_has_rhythm_survival(self, text)`
    - `_has_exposure_trace(self, text)`
    - `_felt_tension(self, text)`
    - `_implication_pressure(self, text)`
    - `_felt_continuity(self, text)`
    - `_post_exposure_recoil_pressure(self, text)`
    - `_split_sentences(self, text)`
    - `_hard_text_limit(self, report)`
    - `_style_char_limit(self, report)`
    - `_truncate_by_clause(self, text, max_chars)`
    - `_finalize_editor_text(self, text)`
    - `_has_capability_violation(self, text)`
    - `_has_perception_violation(self, text)`
    - `_count_report_markers(self, text)`
    - `_build_soft_redirect(self)`

## `cortex/tom/__init__.py`
- LOC: 44
- Docstring: cortex.tom — Phase 2 Theory of Mind package. Tầng lý thuyết tâm trí (Theory of Mind) của Phase 2. Cưỡng chế ràng buộc ToM-after-Meaning (R7): ``TheoryOfMindCore`` chỉ suy luận từ đầu ra của ``MeaningHypothesisEngine`` và ``PragmaticIntentEngine``, không bao gi...

## `cortex/tom/contracts.py`
- LOC: 68
- Docstring: contracts.py — MentalStateInference, ToM dataclasses, lỗi contract ToM. Các kiểu dữ liệu riêng của tầng Theory of Mind (Phase 2). Phụ thuộc một chiều ``cortex.tom.contracts`` → ``cortex.meaning.contracts`` để dùng lại helper ``clamp01`` (nguồn DUY NHẤT) thay v...
- Classes:
  - `ToMOrderingViolation` (base=RuntimeError) — R7.2, R13.3 — ToM chạy trước khi Meaning/Pragmatic sinh output cho frame. Mang theo ``missing_stage`` (stage tiền đề còn thiếu) và ``frame_i...
    - `__init__(self, missing_stage, frame_id)`
  - `MentalStateInference` (decorator=dataclass(slots=True))
    - `__post_init__(self)`
  - `ToMHistory` (decorator=dataclass(slots=True))

## `cortex/tom/counterfactual_corrector.py`
- LOC: 137
- Docstring: counterfactual_corrector.py — CounterfactualCorrector (R7.4). Stage cuối của nhóm ToM hậu kỳ: nhận một ``MentalStateInference`` đã được ``MentalStateRanker`` xếp hạng và một tập **giải thích phản thực** (counterfactual) — các diễn giải thay thế khả dĩ cho cùng...
- Classes:
  - `Counterfactual` (decorator=dataclass(slots=True)) — Một diễn giải phản thực (alternative) cho một mental-state inference. - ``explanation``: mô tả người-đọc-được về cách hiểu thay thế. - ``con...
    - `__post_init__(self)`
  - `CounterfactualCorrector` — Hạ confidence của inference khi có counterfactual đủ mạnh (R7.4). Ngưỡng mặc định lấy theo tham số ``threshold`` của từng lần gọi; mặc định...
    - `correct(self, inference, counterfactuals)` — Trả về inference đã hiệu chỉnh theo R7.4. - Nếu tồn tại counterfactual với ``confidence >= threshold...
    - `correct_all(self, inferences, counterfactuals_by_inference_id)` — Batch helper: áp ``correct`` cho từng inference theo id của nó. Mỗi inference được hiệu chỉnh bằng d...

## `cortex/tom/mental_state_ranker.py`
- LOC: 43
- Docstring: mental_state_ranker.py — MentalStateRanker. Xếp hạng các ``MentalStateInference`` theo độ hợp lý giảm dần (R7.3): - ``confidence`` cao xếp trước. - Khi ``confidence`` bằng nhau, ``overread_risk`` thấp hơn xếp trên (ưu tiên kết luận ít rủi ro suy diễn vượt bằng...
- Classes:
  - `MentalStateRanker` — Xếp hạng mental-state inference theo plausibility giảm dần (R7.3).
    - `rank(self, inferences)` — Trả danh sách mới đã sắp xếp giảm dần theo plausibility. Khóa sắp xếp ``(-confidence, overread_risk)...

## `cortex/tom/theory_of_mind.py`
- LOC: 361
- Docstring: theory_of_mind.py — ``TheoryOfMindCore`` (stage 6 của Phase 2). ``MeaningHypothesis`` set + ``PragmaticIntent`` set → ``MentalStateInference`` set. ``TheoryOfMindCore`` suy luận **trạng thái tâm trí** (mental state) của đối phương CHỈ từ đầu ra của ``MeaningHy...
- Classes:
  - `TheoryOfMindCore` — Suy ``MentalStateInference`` từ meaning + intents, có guard thứ tự (R7). Cộng sự được tiêm (injected) với mặc định an toàn: - ``ranker``: ``...
    - `__init__(self)`
    - `infer(self)` — Suy tập ``MentalStateInference`` từ ``meaning``/``intents``. Xem docstring module cho hợp đồng đầy đ...
    - `_first_missing_stage(ledger, frame_id)` — Trả tên stage tiền đề ĐẦU TIÊN còn thiếu cho ``frame_id`` (hoặc None). Thứ tự kiểm theo ``_REQUIRED_...
    - `_build_inference(self, frame_id, intent, meaning_ids)` — Dựng một ``MentalStateInference`` từ một ``PragmaticIntent``. - ``category`` ánh xạ xác định từ ``in...
    - `_map_mental_state(intent_category)` — Ánh xạ xác định ``Taxonomy.INTENT`` id → ``Taxonomy.MENTAL_STATE`` id. Mặc định an toàn ``content``...
    - `_apply_counterfactuals(self, inferences, intents)` — Hạ confidence từng inference theo counterfactual từ intent đối thủ. Với inference thứ ``k`` (dẫn xuấ...
    - `_build_debug(inferences, notes)` — Gom ``StageDebug`` với chỉ số tổng hợp của tập inference. Kênh debug tạm: ``ToMDebug`` (task 17.1) s...

## `cortex/tom/tom_debug.py`
- LOC: 80
- Docstring: tom_debug.py — ``ToMDebug`` (bản ghi debug Theory of Mind, R12.3). Sinh **bản ghi người-đọc-được** cho tập ``MentalStateInference`` mà ``TheoryOfMindCore`` suy ra. Với mỗi inference, in: - ``supporting_meaning_ids`` — các tham chiếu ``MeaningHypothesis`` đã ch...
- Functions:
  - `_render_metric(value)` — Render một chỉ số: ``f"{value:.3f}"`` khi có giá trị, else ``"unavailable"`` (R12.5).
- Classes:
  - `ToMDebug` — Render danh sách ``MentalStateInference`` thành chuỗi người-đọc-được (R12.3).
    - `render(self, inferences)` — Trả bản ghi nhiều dòng cho từng mental-state inference (R12.3).
    - `_render_inference(inf)` — Render một inference + các tham chiếu MeaningHypothesis hỗ trợ.

## `cortex/tom/tom_history_adapter.py`
- LOC: 119
- Docstring: tom_history_adapter.py — ToMHistoryAdapter (history từ WorkspaceFrame only). Cấp dữ liệu *lịch sử tương tác* cho ``TheoryOfMindCore`` **chỉ** từ ``WorkspaceFrame`` thông qua ``FrameReadView`` (R7.5) — không bao giờ chạm ``Raw_World`` (raw_signals / evidence ch...
- Classes:
  - `ToMHistoryAdapter` — Adapter cấp ``ToMHistory`` từ ``WorkspaceFrame`` qua ``FrameReadView``. Tham số khởi tạo (đều có mặc định an toàn): - ``module``: tên module...
    - `__init__(self)`
    - `load(self, view)` — Trả ``ToMHistory`` lấy từ ``WorkspaceFrame`` qua ``view``. - ``view is None`` → không có nguồn nào đ...
    - `_normalize(raw)` — Chuẩn hoá giá trị đọc được thành ``list[str]`` cho ``ToMHistory.items``. Bỏ qua phần tử rỗng/``None`...

## `cortex/tune_ni_focus.py`
- LOC: 291
- Functions:
  - `_load_samples(path)`
  - `_fit_bias_scale(xs, targets)`
  - `tune_focus_bias(samples, min_samples)`
  - `tune_channel_weights(samples)`
  - `_load_existing_config(path)`
  - `_save_json(path, data)`
  - `main(argv)`
- Classes:
  - `DriftSample` (decorator=dataclass)

## `cortex/turn_semantics.py`
- LOC: 541
- Classes:
  - `TurnSemanticsReport` (decorator=dataclass(frozen=True, slots=True)) — Báo cáo nghĩa của user turn hiện tại. Các score đều là áp lực mềm, không phải nhãn tuyệt đối. ChatCycle chỉ nên dùng `action` và `should_gua...
    - `should_guard_repeat(self)`
    - `should_bypass_repeat_guard(self)`
  - `TurnSemanticsEngine` — Arbitration nhẹ cho meaning của một user turn. Đây là tầng nằm giữa exact repeat counter và LLM. Nó cố tình dùng nhiều nguồn tín hiệu thay v...
    - `analyze_repeat(self)`
    - `build_repeat_guard_text(self, report)` — Text guard chỉ dùng khi arbitration thật sự coi là repeat rỗng.
    - `_question_pressure(self, raw, normalized, affect_signal)`
    - `_correction_pressure(self, conversation_report, affect_signal, normalized)`
    - `_relational_pressure(self, affect_signal, relationship_report)`
    - `_identity_pressure(self, affect_signal, relationship_report)`
    - `_fact_disclosure_pressure(self)` — Áp lực self-disclosure/profile update cho repeat guard. Đây là cầu nối semantic rẻ giữa memory intak...
    - `_live_evidence_pressure(self, grounding_report)`
    - `_prior_failure_pressure(self, last_assistant_text, conversation_report)`
    - `_new_information_pressure(self)`
    - `_spam_pressure(self)`
    - `_with_prompt_context(self, report)`
    - `normalize(self, text)`
    - `_looks_like_question(self, normalized)`
    - `_contains_soft_correction_shape(self, normalized)`
    - `_jaccard_similarity(self, left, right)`
    - `_safe_float(self, value, default)`
    - `_clamp01(self, value)`

## `cortex/user_context_stream.py`
- LOC: 269
- Docstring: src/cortex/user_context_stream.py ================================= Tầng 1 - Sensory / User Context Stream. Trách nhiệm: - Đọc diff màn hình, app đang active, OCR/vision hint, key/mouse/recent events. - Gọi/nhận kết quả từ observer 0.6B nếu runtime đã bật. - X...
- Functions:
  - `_safe_float(value, default)`
  - `_ema(previous, new, alpha)`
- Classes:
  - `RollingUserContext` (decorator=dataclass(slots=True)) — Bản tóm tắt ngoại sinh đang lăn theo thời gian. external_pressure: Áp lực từ thế giới ngoài: lỗi, diff lớn, user gọi, scene lạ. interrupt_co...
    - `to_dict(self)`
    - `prompt_hint(self)` — Render cực ngắn nếu cần đưa vào debug/prompt dev mode.
  - `UserContextStream` — Bộ sở hữu RollingUserContext. Có thể nhận `ObserverFrame` từ BackgroundObserver hiện tại. Nếu chưa có observer, nó vẫn chạy rule nhẹ từ Sign...
    - `__init__(self)`
    - `update(self)` — Cập nhật context từ signal mới. `observer_frame` là nguồn tốt nhất vì nó đã qua Qwen 0.6B/rule obser...
    - `_busy_score(self)`
    - `_interrupt_cost(self)`

## `cortex/vision_semantic_compressor.py`
- LOC: 712
- Docstring: VisionSemanticCompressor cho ERIS. Vai trò: - Nhận screenshot/crop + OCR hint + ObserverFrame. - Gọi Qwen vision qua Ollama khi thật sự cần. - Nén màn hình thành SemanticSceneNote nhỏ. - Không trả lời user. - Không commit memory. - Không tự bật speech/action....
- Functions:
  - `_safe_float(value, default)`
  - `_parse_keep_alive(value)`
- Classes:
  - `VisionCompressorConfig` (decorator=dataclass(slots=True)) — Cấu hình cho VisionSemanticCompressor. Mặc định tắt bằng env để Ngài kiểm observer trước rồi mới bật vision. Có thể bật bằng: ERIS_VISION_CO...
  - `VisionSemanticCompressor` — Nén ảnh màn hình thành SemanticSceneNote. Public API chính: should_compress(observer_frame, signal_diff) compress(image_data_uri=..., ocr_te...
    - `__init__(self, config, ollama_client, logger)`
    - `should_compress(self)` — Quyết định có nên gọi vision model không. Đây chỉ là policy cục bộ. Coordinator vẫn nên có cooldown...
    - `compress(self)` — Gọi vision model và trả SemanticSceneNote. Nếu thiếu ảnh/model/Ollama, trả fallback OCR-only thay vì...
    - `compress_from_ocr_only(self)` — Public fallback khi runtime chưa có ảnh nhưng có OCR.
    - `_system_prompt()`
    - `_user_prompt(self)`
    - `_json_schema()`
    - `_note_from_mapping(self, data)`
    - `_fallback_ocr_note(self)`
    - `_extract_important_lines(self, text)`
    - `_infer_intent_from_text(self, text, focus_kind)`
    - `_infer_family_from_text(self, text)`
    - `_fallback_visible_context(signal_snapshot, focus_kind, intent)`
    - `_observer_payload(observer_frame)`
    - `_signal_payload(signal_snapshot)`
    - `_resolve_image_base64(self)`
    - `_strip_data_uri(value)`
    - `_coerce_text_list(value)`
    - `_clean_family(value)`
    - `_source_label(self)` — Trả source label từ model name, dùng cho SemanticSceneNote.source.
    - `_make_default_client()`
    - `_log_warning(self, msg)`

## `cortex/working_memory.py`
- LOC: 1930
- Functions:
  - `clamp01(value, default)` — Ép một giá trị về khoảng 0..1. Các module khác thường sẽ trả float hơi bẩn: None, chuỗi số, NaN, hoặc object lạ. Working...
  - `now_ts()`
  - `stable_id(prefix, text)`
  - `safe_get(obj, name, default)` — Đọc field từ dataclass/object/dict một cách khoan dung. File này được thiết kế để gắn sau, nên không ép mọi object trong...
  - `safe_iter(value)` — Biến tuple/list/set/None/object đơn thành list.
  - `normalize_text(text)` — Chuẩn hóa text nhẹ để so trùng / phát hiện echo. Không bỏ dấu tiếng Việt, vì mất dấu có thể làm câu technical và câu đùa...
  - `estimate_tokens(text)` — Ước lượng token thô. Không cần tokenizer thật ở tầng này. Working memory chỉ cần budget tương đối để không biến prompt t...
  - `truncate_text(text, max_chars)`
  - `unique_preserve_order(items, limit)`
  - `select_working_memory(frame)` — Hàm tiện dụng để không cần tự khởi tạo engine trong code thử nghiệm.
- Classes:
  - `WorkingMemorySlot` (decorator=dataclass(slots=True)) — Một slot đang hoạt động trong cổ chai nhận thức. Field lõi theo PDF: name: Tên slot. Ví dụ: current_user_request, immediate_evidence. conten...
    - `__post_init__(self)`
    - `is_memory(self)`
    - `is_symbolic_heavy(self)`
    - `expired(self, timestamp)`
    - `to_prompt_line(self)` — Dòng ngắn để prompt builder có thể dùng. Không nhét metadata vào prompt. Metadata dành cho debug. Pr...
    - `to_dict(self)`
  - `SuppressedMemoryItem` (decorator=dataclass(slots=True)) — Một candidate bị loại khỏi working memory. Đây là thứ giúp debug câu hỏi: "vì sao memory này không được kéo lên?" Không có nó, Ngài sẽ nhìn...
    - `to_debug_line(self)`
    - `to_dict(self)`
  - `WorkingMemoryFrame` (decorator=dataclass(slots=True)) — Kết quả chính của module Working Memory. Field lõi theo PDF: active_slots: 3-7 slot đang hoạt động. suppressed_items: Những item bị loại để...
    - `__post_init__(self)`
    - `get_slot(self, kind_or_name)`
    - `evidence_ids(self)`
    - `render_prompt_context(self)` — Render prompt context cực gọn. Prompt builder sau này có thể tự format đẹp hơn. Hàm này chỉ cung cấp...
    - `prompt_context(self)`
    - `to_dict(self)`
  - `WorkingMemoryCandidate` (decorator=dataclass(slots=True)) — Candidate nội bộ trước khi được chọn thành slot. Candidate có thể đến từ: - EvidenceItem - SalienceFrame / prompt evidence - MemoryPacket -...
    - `__post_init__(self)`
    - `id(self)`
    - `normalized_content(self)`
    - `to_slot(self)`
  - `WorkingMemoryConfig` (decorator=dataclass(slots=True)) — Cấu hình cổ chai. Slot budget mặc định: fast: 3 normal: 5 deep: 7 reflection: 6 Ngài có thể tăng token budget, nhưng đừng tưởng tăng context...
    - `slot_budget_for(self, budget_mode)`
    - `token_budget_for(self, budget_mode)`
  - `WorkingMemoryEngine` — Bộ chọn WorkingMemoryFrame. Cách dùng: engine = WorkingMemoryEngine() wm = engine.select(frame) Contract: - đọc frame. - tạo candidates. - s...
    - `__init__(self, config)`
    - `select(self, frame)`
    - `_collect_candidates(self, frame)`
    - `_candidates_from_evidence(self, frame)`
    - `_candidates_from_attention_candidates(self, frame)` — Đọc Runtime AttentionCandidate cũ từ frame.attention_candidates. Coordinator hiện tại giữ attention...
    - `_candidates_from_percepts(self, frame)` — Fallback đọc percepts khi frame.evidence rỗng. `PerceptEvent` là contract runtime hiện tại. Ta chỉ l...
    - `_attention_kind(self)`
    - `_candidates_from_salience(self, frame)`
    - `_candidates_from_memory_packet(self, frame)`
    - `_candidates_from_goal(self, frame)`
    - `_candidates_from_relation(self, frame)`
    - `_candidates_from_affect_homeostasis(self, frame)`
    - `_candidates_from_constraints(self, frame)`
    - `_candidates_from_temporal_spatial(self, frame)`
    - `_score_and_filter(self, candidates)`
    - `_candidate_score(self, cand)` — Tính điểm candidate. Công thức cố tình thiên về current request / immediate evidence / risk thật. Me...
    - `_early_suppression_reason(self, cand)`
    - `_select_slots(self, candidates)`
    - `_evidence_kind(self)`
    - `_claim_relevance(self, claim, tags)`
    - `_risk_score(self, claim, tags)`
    - `_affective_score(self, claim, tags)`
    - `_goal_score(self, claim, tags)`
    - `_recency_score(self, item_timestamp, frame_timestamp)`
    - `_symbolic_drift_risk(self, cand)`
    - `_overassociation_risk(self, cand)`
    - `_find_duplicate(self, text, seen_texts)`
    - `_jaccard_similarity(self, a, b)`
    - `_suppressed(self, cand, reason)`
    - `_choose_dominant_thread(self, slots, frame)`
    - `_context_pressure(self)`
    - `_anti_drift_notes(self, slots, suppressed)`
    - `_warnings(self, slots, context_pressure, suppressed)`
    - `_coerce_candidate(self, item)`
    - `_attach_to_frame(self, frame, wm_frame)`
    - `_report_confidence(self, wm_frame)`
    - `_memory_item_text(self, item)`
    - `_looks_technical(self, text)`
    - `_frame_is_technical(self, frame)`
    - `_decay_for_kind(self, kind)`

## `domain/__init__.py`
- LOC: 6

## `domain/decision.py`
- LOC: 98
- Classes:
  - `Decision` (decorator=dataclass(slots=True))
    - `resolve_motion_intent(self)`
    - `resolve_motion_target_x(self)`
    - `resolve_motion_facing(self)`
    - `_payload_text(self)`
    - `to_payload(self)`

## `eris_secrets.py`
- LOC: 192
- Functions:
  - `_resolve_secrets_path()`
  - `_load_secrets()`
  - `_lookup(payload, name)`
  - `_lookup_path(payload, path)`
  - `_provider_slot_payload(payload, provider, slot)`
  - `get_secret()`
  - `get_config(path, default)` — Đọc config lồng nhau từ env hoặc secrets.json. Ưu tiên env nếu path không có dấu chấm hoặc nếu biến env cùng tên tồn tại...
  - `get_provider_profile(provider)` — Lấy cấu hình provider theo slot riêng. Ví dụ: - get_provider_profile("gemini", slot="remote_main") - get_provider_profil...
  - `get_agent_profile(agent_name)` — Resolve provider profile cho một job/agent cụ thể. Schema: { "agent_keys": { "search_web": {"provider": "gemini", "slot"...
  - `apply_secrets_to_environ()`

## `guard_config.py`
- LOC: 49
- Functions:
  - `guards_warn_only()` — Công tắc thống nhất: mọi guard chỉ CẢNH BÁO, không chặn. Khi bật (`ERIS_GUARDS_WARN_ONLY`), các guard nhóm quan hệ/giọng...
  - `get_guard_mode(name)` — Trả chế độ guard hiện hành. Tham số `name` (tùy chọn) cho phép override theo từng rule trong tương lai; hiện dùng mode t...

## `llm/__init__.py`
- LOC: 30

## `llm/client.py`
- LOC: 426
- Functions:
  - `_http_error_with_body(response)`
  - `_chat_payload_variants(payload)`
  - `_model_supports_reasoning_toggle(model_name)` — Các model có chế độ "thinking" mà Groq cho tắt qua reasoning_effort. Chủ yếu Qwen3 và GPT-OSS. Trả về False cho llama/gl...
  - `_resolve_reasoning_effort()` — Mức reasoning cho model có thinking. Mặc định "none" để khỏi đốt token vào khối suy nghĩ (pipeline chỉ cần JSON + giọng,...
- Classes:
  - `LlamaServerClient`
    - `__init__(self, base_url, timeout)`
    - `_detect_model_name(self)`
    - `create_chat_completion(self)`
  - `OpenAICompatibleClient`
    - `__init__(self, base_url, api_key, model_name, timeout, key_pool)`
    - `_normalize_api_key(self, raw_value)`
    - `create_chat_completion(self)`
  - `GeminiClient`
    - `__init__(self, base_url, api_key, model_name, timeout, key_pool)`
    - `_normalize_api_key(self, raw_value)`
    - `_text_part(self, text)`
    - `_image_part_from_url(self, url)`
    - `_parts_from_content(self, content)`
    - `_convert_messages(self, messages)`
    - `create_chat_completion(self)`

## `llm/contracts.py`
- LOC: 240
- Functions:
  - `_gbnf_literal(value)`
  - `_build_decision_gbnf()`

## `llm/key_pool.py`
- LOC: 159
- Docstring: llm/key_pool.py Pool API key dùng CHUNG cho mọi mạch gọi Gemini (main / speech / private_mind). Mỗi key thường thuộc một Google project khác nhau (vd nhiều Gmail) → mỗi key có hũ free quota riêng. Free tier tính theo PROJECT chứ không theo key, nên cách duy nh...
- Functions:
  - `_normalize_kind(kind)`
  - `_is_placeholder(value)`
  - `_collect_gemini_keys()` — Gom key Gemini: chính + remote + speech + fallback pool.
  - `_collect_groq_keys()` — Gom key Groq: ERIS_GROQ_API_KEY + ERIS_GROQ_FALLBACK_API_KEYS (bỏ placeholder).
  - `get_key_pool(kind)` — Trả pool singleton theo provider-kind ('gemini' hoặc 'groq'). Mỗi consumer truyền đúng provider của mình để luôn lấy đún...
  - `get_shared_key_pool()` — Tương thích ngược: chọn pool theo ERIS_REMOTE_PROVIDER toàn cục.
  - `reset_shared_key_pool()` — Chỉ dùng cho test: xóa toàn bộ pool để build lại từ secrets.
- Classes:
  - `ApiKeyPool` — Danh sách key + một con trỏ rotation dùng chung.
    - `__init__(self, keys)`
    - `size(self)`
    - `current_key(self)`
    - `rotate(self)` — Xoay sang key kế tiếp (wrap-around). Trả True nếu pool có >1 key (tức việc xoay có ý nghĩa). Wrap-ar...
    - `index(self)`

## `llm/llamacpp_client.py`
- LOC: 126
- Docstring: llm/llamacpp_client.py ====================== Engine inference local IN-PROCESS dựa trên llama-cpp-python. Mục đích: chạy model gguf đặt thẳng trong `src/` mà KHÔNG cần Ollama hay llama-server ngoài → bản build self-contained, chạy được trên mọi máy (chỉ cần r...
- Functions:
  - `_project_root()`
  - `_bundle_root()` — PyInstaller bundle root (_MEIPASS). None khi chạy script thường.
  - `resolve_model_path(path_or_name)` — Định vị file gguf. Ưu tiên đường dẫn tuyệt đối; rồi project_root/path; rồi bundle _MEIPASS/src/; rồi cwd.
- Classes:
  - `LlamaCppClient` — Wrapper llama-cpp-python theo interface create_chat_completion của ERIS.
    - `__init__(self)`
    - `_llama(self)`
    - `create_chat_completion(self)`

## `llm/local_llama_engine.py`
- LOC: 297
- Docstring: llm/local_llama_engine.py ========================= Engine local thống nhất bằng llama-cpp-python, drop-in thay cho ``OllamaClient``. Mục tiêu: dồn TẤT CẢ model nội bộ về một engine duy nhất chạy gguf trong ``src/`` (không cần Ollama/llama-server ngoài) → bản...
- Functions:
  - `_env(name, default)`
  - `_n_gpu_layers()`
  - `build_local_or_ollama_client()` — Trả LocalLlamaEngine nếu ERIS_LOCAL_LLM_ENGINE=llamacpp, ngược lại OllamaClient. Dùng làm điểm chuyển đổi engine duy nhấ...
- Classes:
  - `LocalLlamaEngine` — Engine llama-cpp dùng chung, interface tương thích OllamaClient.
    - `__init__(self)`
    - `_text_llm(self)`
    - `_vision_llm(self)`
    - `chat_json(self, model, messages)`
    - `generate_json(self, model, prompt)`
    - `_response_format(self, schema)`
    - `_chat_text(self, messages)`
    - `_chat_vision(self, messages, images)`
    - `unload(self, model)` — Giải phóng model vision khỏi VRAM (text giữ resident).
    - `list_models(self)`
    - `encode_image_file(path)`
    - `encode_image_bytes(data)`
    - `data_uri_to_base64(data_uri_or_base64)`
    - `_messages_to_text(messages)`
    - `_extract_content(raw)`
    - `_parse_json_object(content)`

## `llm/ollama_client.py`
- LOC: 317
- Docstring: Client mỏng cho Ollama. Vai trò trong ERIS: - Dùng một Ollama daemon duy nhất thay vì mở nhiều llama-server riêng. - Gọi model nhỏ cho BackgroundObserver. - Gọi model vision cho VisionSemanticCompressor về sau. - Ép JSON càng nhiều càng tốt, nhưng vẫn có salva...
- Classes:
  - `OllamaClientError` (base=RuntimeError) — Lỗi gọi Ollama. Tách riêng để runtime có thể fallback sạch.
  - `OllamaResult` (decorator=dataclass(frozen=True)) — Kết quả chuẩn hóa từ Ollama. `parsed` chỉ có giá trị khi output parse được thành JSON object. `raw` giữ nguyên response từ Ollama để debug k...
  - `OllamaClient` (decorator=dataclass) — Client gọi Ollama qua HTTP API. Ollama mặc định chạy ở http://localhost:11434/api. Có thể override bằng env `OLLAMA_BASE_URL`.
    - `__post_init__(self)`
    - `chat_json(self, model, messages)` — Gọi `/api/chat` và kỳ vọng JSON object. Parameters ---------- model: Tên model trong Ollama, ví dụ `...
    - `generate_json(self, model, prompt)` — Gọi `/api/generate` và kỳ vọng JSON object. Dùng khi không cần multi-turn messages.
    - `unload(self, model)` — Yêu cầu Ollama unload model. Hữu ích cho model vision nặng: gọi xong thả khỏi memory.
    - `list_models(self)` — Lấy danh sách model đã pull trong Ollama.
    - `encode_image_file(path)` — Encode ảnh thành base64 thuần, phù hợp field `images`.
    - `encode_image_bytes(data)`
    - `data_uri_to_base64(data_uri_or_base64)` — Nhận data URI hoặc base64 thuần, trả base64 thuần.
    - `_attach_images(self, messages, images)`
    - `_normalize_base_url(base_url)`
    - `_post_json(self, path, payload)`
    - `_get_json(self, path)`
    - `_open_json(self, req)`
    - `_extract_chat_content(raw)`
    - `_parse_json_object(content)` — Parse JSON object, có salvage khi model lỡ bọc thêm text. Với `format=json`, bình thường không cần s...

## `llm/process_manager.py`
- LOC: 239
- Classes:
  - `RemoteModelProcessManager`
    - `__init__(self)`
    - `_env_flag(self, name, default)`
    - `_build_remote_client(self)`
    - `_speech_api_requested(self)`
    - `_build_speech_client(self)`
    - `build_client(self)`
    - `build_style_client(self)`
    - `build_format_fallback_client(self)` — Build a Groq (OpenAI-compatible) client used to rescue chat/directive decisions when the main provid...
    - `build_vision_client(self)`
    - `stop(self)`

## `llm/service.py`
- LOC: 3152
- Functions:
  - `_normalize_vietnamese_ascii_text(text)`
  - `classify_chat_act(raw_user_text)`
- Classes:
  - `ChatAct` (base=Enum)
  - `FormatViolationException` (base=Exception) — Raised when a model response violates the public JSON contract.
    - `__init__(self, reason)`
  - `LlmService`
    - `__init__(self, client, style_client, vision_client, fallback_client, logger)`
    - `_http_status_code(self, exc)`
    - `_is_retryable_http_5xx(self, exc)`
    - `_build_service_error_fallback(self)`
    - `_message_text(self, message)`
    - `_normalize_vietnamese_ascii(self, text)`
    - `_looks_like_direct_question(self, text)`
    - `_is_short_or_ambiguous_user_text(self, text)`
    - `_is_self_identity_question(self, text)`
    - `_contains_user_intent_inference(self, text)`
    - `_build_chat_contract_prompt(self, raw_user_text, act)`
    - `_chat_text_family(self, text)`
    - `_decision_payload_text(self, raw_json)`
    - `_chat_act_repair_signal(self, act)`
    - `_normalize_vietnamese_ascii(self, text)`
    - `_deterministic_chat_act_fallback_text(self, act, raw_user_text)`
    - `_payload_with_repaired_chat_act_text(self, raw_json)`
    - `_repair_chat_act_payload_with_llm(self, raw_json)`
    - `_rewrite_question_only_chat_answer(self, text)`
    - `_append_reasoning_tag(self, payload, tag)`
    - `_looks_like_relational_feedback_text(self, text)`
    - `_looks_like_defensive_relational_reply(self, text)`
    - `_relational_repair_fallback_text(self, raw_user_text, current_text)`
    - `_guard_chat_output(self, raw_json)` — Guard chat wording without flattening ERIS. Most text rewriting stays disabled. One exception is rel...
    - `_contextual_service_fallback_text(self, messages)`
    - `_log_final_prompt(self, messages)`
    - `_preview_log_text(self, text)`
    - `_looks_like_prompt_leak(self, text)` — Detect raw prompt/contract text that must never become public speech.
    - `_looks_like_malformed_decision_json(self, text)`
    - `_json_string_field_from_raw(self, raw_text, field)`
    - `_build_protocol_failure_fallback(self)`
    - `_coerce_malformed_decision_payload(self, raw_text)` — Salvage only speakable fields from truncated decision JSON. The old path wrapped the whole malformed...
    - `_log_raw_api_text(self, channel, raw)`
    - `_is_context_size_error(self, exc)`
    - `_parse_context_error_stats(self, exc)`
    - `_content_text_len(self, content)`
    - `_truncate_content(self, content)`
    - `_shrink_messages_for_context(self, messages)`
    - `_collect_text_chunks(self, value)`
    - `_extract_content(self, response)`
    - `_extract_first_json_object(self, text)`
    - `_parse_json_object(self, text)`
    - `_normalize_payload_keys(self, value)`
    - `_is_valid_decision_payload(self, payload)`
    - `_is_valid_motion_payload(self, payload)`
    - `_is_valid_cognition_payload(self, payload)`
    - `_is_decision_like_payload(self, payload)`
    - `_coerce_bool_value(self, value)`
    - `_coerce_confidence_value(self, value)`
    - `_coerce_reasoning_tags_value(self, value)`
    - `_coerce_action_value(self, value)`
    - `_action_field(self, action)`
    - `_is_valid_text_field(self, value)`
    - `_is_valid_animation_field(self, value)`
    - `_is_valid_system_action_field(self, value)`
    - `_is_valid_choice_number(self, value, choices)`
    - `_is_valid_target_x(self, value)`
    - `_allows_motion_target(self, payload)`
    - `_coerce_text_value(self, value)`
    - `_coerce_animation_value(self, value)`
    - `_coerce_direction_value(self, value)`
    - `_coerce_target_x_value(self, value)`
    - `_coerce_system_action_value(self, value)`
    - `_coerce_decision_like_payload(self, payload)`
    - `_coerce_json_candidate(self, raw_text)`
    - `_build_json_fallback(self, raw_text)`
    - `_looks_like_provider_metadata(self, text)`
    - `_looks_like_markdown_json_stub(self, text)`
    - `_safe_fallback_text(self, raw_text)`
    - `_build_empty_text_fallback(self)`
    - `_decision_needs_non_empty_text(self, raw_text)`
    - `_decision_text_is_invalid(self, raw_text)`
    - `_with_non_empty_text_rule(self, messages)`
    - `_repair_empty_decision_text(self)`
    - `_repair_decision_json(self, raw_text)`
    - `_strict_decision_candidate_or_raise(self, raw)`
    - `_complete_decision(self)`
    - `_normalize_for_claim_diff(self, text)`
    - `_style_rewrite_is_safe(self, original, rewritten)`
    - `rewrite_text_with_local_style(self, decision)`
    - `rewrite_guard_violation_text(self)` — One-shot cognitive steering repair for post-generation guards. This is deliberately narrower than no...
    - `_compress_internal_context(self, text)`
    - `_extract_action_plan_context(self, text)`
    - `_build_style_block(self)`
    - `_build_memory_context_block(self, memory_context)`
    - `_build_grounding_context_block(self, grounding_context)`
    - `_build_relational_repair_contract(self, context)`
    - `_is_force_speak_without_speech_evidence(self)`
    - `_build_directive_mode_addendum(self, ti_context)`
    - `_build_speech_intent_guidance(self, speech_intent)`
    - `_is_session_ritual_call(self)`
    - `_fallback_greeting_engine(self)`
    - `_fallback_greeting_text(self)`
    - `_build_session_greeting_payload(self)`
    - `_session_greeting_frame(self, telemetry_data)`
    - `_session_greeting_quality_scorer(self)`
    - `_extract_candidate_strings(self, payload)`
    - `_generate_session_ritual_greeting(self)`
    - `generate_directive(self)`
    - `generate_micro_presence_line(self)`
    - `generate_screen_facts(self)`
    - `_chat_client_supports_vision(self)` — Chỉ nhồi ảnh thô vào message chat khi model chat thật sự đa phương thức. Model chat chính (vd Groq l...
    - `generate_chat_reply(self)`
    - `run_ni_meta_critic(self)`

## `memory/__init__.py`
- LOC: 31
- Docstring: Public memory API for ERIS. Use `MemoryKernel` from the package root for new integration. Legacy core/query/commit types are intentionally no longer re-exported here. Import them from `memory.memory_cognition` explicitly when compatibility is still needed.

## `memory/active_state_snapshot.py`
- LOC: 172
- Docstring: Active State Snapshot cho ERIS. Snapshot giữ trạng thái hiện tại có thể overwrite: goal đang theo, session arc, affect/homeostasis hiện thời, relation state, project active, thread đang mở. Nó không phải event ledger và không phải semantic memory. Nó là bảng đ...
- Functions:
  - `iso_now()`
  - `atomic_write_json(path, payload)`
  - `compact_text(value)`
- Classes:
  - `ActiveStateSnapshot` (decorator=dataclass(slots=True)) — State overwrite được, dùng cho runtime hiện tại. Memory dài hạn nói "đã từng". Snapshot nói "đang là".
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `ActiveStateStore` — Kho snapshot overwrite. Chỉ MemoryCognitionCore nên gọi apply_commit(). Module khác phải gửi StateCommitRequest.
    - `__init__(self, path)`
    - `load(self)`
    - `save(self, snapshot)`
    - `apply_commit(self, request)`

## `memory/affective_residue_memory.py`
- LOC: 213
- Docstring: Affective Residue Memory: dư âm cảm xúc dưới dạng pressure. Không lưu "ERIS buồn" như fact công khai. Lưu pressure: tension, attachment residue, exposure recoil, unfinished loop. Dư âm ảnh hưởng nhịp nói/im lặng, không tự động thành câu thoại.
- Functions:
  - `iso_now()`
  - `compact_text(value)`
  - `clamp01(value)`
  - `clamp11(value)`
  - `atomic_write_json(path, payload)`
- Classes:
  - `AffectiveResidueItem` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `recall_line(self)`
  - `AffectiveResidueMemoryStore`
    - `__init__(self, path)`
    - `load(self)`
    - `save(self, items)`
    - `apply_commit(self, request)`
    - `recall(self, query)`
    - `_infer_type(self, description, reason)`
    - `_infer_valence(self, description, reason)`
    - `_pressure_effects(self, residue_type, intensity)`

## `memory/claim_consolidator.py`
- LOC: 73
- Functions:
  - `_norm(text)`
- Classes:
  - `ClaimMergeDecision` (decorator=dataclass(frozen=True, slots=True))
  - `ClaimConsolidator` — Logic merge claim độc lập với store JSON.
    - `can_merge(self, old, new)`
    - `find_merge_target(self, items, new)`

## `memory/claim_entailment.py`
- LOC: 130
- Functions:
  - `semantic_claim_from_memory_item(item)` — Lấy SemanticClaim từ SemanticMemoryItem hoặc dict cũ nếu có. Ưu tiên metadata.semantic_claim. Nếu item cũ chỉ có fact_ke...
- Classes:
  - `ClaimEntailmentDecision` (decorator=dataclass(frozen=True, slots=True))
    - `can_answer(self)`
  - `ClaimEntailmentEngine` — Engine entailment giữa SemanticClaim và SemanticQueryIntent.
    - `evaluate(self, claim, query)`
    - `rank(self, claims, query)`

## `memory/claim_extractor.py`
- LOC: 69
- Functions:
  - `extract_claims(user_text)`
- Classes:
  - `ClaimExtractor` (decorator=dataclass(slots=True)) — Facade extract claim theo pipeline frame semantics. `parser` mặc định là fallback surface rất nhỏ. Runtime production nên thay bằng parser m...
    - `extract(self, user_text)`

## `memory/claims/__init__.py`
- LOC: 15
- Docstring: Tầng claim logic: build claim, ontology, entailment.

## `memory/claims/claim_builder.py`
- LOC: 308
- Classes:
  - `ClaimBuilder` (decorator=dataclass(slots=True)) — Builder deterministic từ MeaningFrame sang ExtractedClaim.
    - `build_many(self, result)`
    - `build_one(self, frame)`
    - `_build_from_ai_classification(self, raw)` — Build ExtractedClaim từ schema mới của Gemini. Gemini quyết định memory_type, storage_target, import...
    - `_predicate_for_frame(self, frame)`
    - `_dedupe(self, items)`

## `memory/embedding_index.py`
- LOC: 337
- Docstring: memory/embedding_index.py ========================= In-memory embedding index cho SemanticMemoryStore. Dùng transformers + numpy (đã có sẵn trong runtime). Không cần FAISS, ChromaDB, hay server nào. Model mặc định: paraphrase-multilingual-MiniLM-L12-v2 - ~120M...
- Functions:
  - `_cosine_similarity(a, b)` — Cosine similarity giữa vector a và matrix b (N, D). Trả ndarray shape (N,).
  - `_short_hash(text)`
  - `build_embedding_index()` — Build EmbeddingIndex nếu enabled. Trả None nếu disabled hoặc import fail — caller tự graceful degrade. Env: ERIS_EMBEDDI...
- Classes:
  - `EmbeddingIndex` — In-memory embedding index dùng transformers. Workflow: 1. `ensure_vectors(items, text_fn)` — embed mọi item chưa có vector 2. `search(query,...
    - `__init__(self)`
    - `search(self, query, items)` — Tìm items gần với query nhất theo cosine similarity. Trả list[tuple[score, item]] đã sorted descendi...
    - `ensure_vectors(self, items)` — Pre-embed items vào cache. Trả số item mới được embed. Gọi từ maintenance hoặc khi store load. Không...
    - `clear_cache(self)`
    - `debug_status(self)`
    - `_ensure_loaded(self)`
    - `_load_model(self)`
    - `_encode(self, texts)` — Encode list of texts → ndarray (N, D).
    - `_encode_with_cache(self, texts)` — Encode texts, dùng cache để tránh re-embed text đã biết.
    - `_cuda_available()`

## `memory/episodic_memory.py`
- LOC: 628
- Docstring: Episodic Memory: chuyện cụ thể đã xảy ra. Episodic không phải semantic fact. Nó giữ cảnh, lượt, outcome, evidence và độ nổi bật. Một câu user sửa sai hôm nay là episode. Một fact ổn định chỉ lên semantic sau khi commit phù hợp. Bản này sửa phần recall: - Không...
- Functions:
  - `iso_now()`
  - `compact_text(value)`
  - `clamp01(value)`
  - `atomic_write_json(path, payload)`
  - `normalize_text(text)` — Normalize text để so khớp ổn hơn. Bỏ dấu tiếng Việt để recall không tạch vì dữ liệu có/không dấu. Không dùng substring s...
  - `normalized_tokens(text)` — Token hóa nhẹ, bỏ stopword và token quá ngắn. Token dạng file/module như micro_policy.py, relationship_dynamics.py được...
  - `token_bigrams(tokens)`
  - `weighted_counter(tokens)` — Tạo counter có trọng số nhẹ cho anchor kỹ thuật. Episodic memory trong project ERIS thường cần recall theo file/module/a...
  - `weighted_jaccard(left, right)` — Jaccard có trọng số giữa hai counter.
  - `phrase_match_score(query_norm, hay_norm)` — Score phrase match mềm. Khác với token in haystack: - Chỉ tính phrase đủ dài. - Query đầy đủ nằm trong field thì score c...
  - `parse_timestamp(timestamp)` — Parse timestamp best-effort. Nếu parse không được thì trả 0, coi như rất cũ. Không để timestamp lỗi làm recall bay màu b...
  - `recency_boost(timestamp)` — Boost nhẹ cho episode gần đây. Recency không được thắng relevance. Nó chỉ là tie-breaker mềm.
- Classes:
  - `RecallScore` (decorator=dataclass(frozen=True, slots=True)) — Debug score cho một item recall. Giữ lớp này để sau này log "vì sao ký ức này được kéo lên" thay vì nhìn một con số tổng rồi cầu nguyện. Cầu...
    - `to_dict(self)`
  - `EpisodicMemoryItem` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `recall_line(self)`
    - `search_fields(self)` — Fields phục vụ recall, có trọng số riêng trong scorer. Không gom tất cả vào một haystack rồi token-i...
  - `EpisodicMemoryStore`
    - `__init__(self, path)`
    - `load(self)`
    - `save(self, items)`
    - `apply_commit(self, request)`
    - `recall(self, query)` — Recall episode theo relevance score có bằng chứng. Bản cũ: tokens = query.lower().split() overlap =...
    - `recall_with_scores(self, query)` — Debug recall: trả cả item và breakdown score. Dùng khi muốn biết vì sao ERIS kéo ký ức nào lên. Runt...
    - `_score_item(self, item)` — Chấm một episodic item. Điểm tổng là relevance + small priors. Priors như salience/confidence/recenc...
    - `_mark_accessed(self, selected)` — Tăng access_count cho item đã recall. Mục đích: - Debug xem ký ức nào bị kéo lên nhiều. - Tạo penalt...
    - `_trim(self, items)`

## `memory/event_ledger.py`
- LOC: 220
- Docstring: Append-only Event Ledger cho ERIS. Tầng này giữ raw truth: tín hiệu thô, evidence đã tạo ra, frame liên quan, và metadata audit. Nó không kết luận tâm lý, không merge ký ức, không sửa quá khứ. Nếu một module muốn lưu sự kiện, nó phải tạo StateCommitRequest rồi...
- Functions:
  - `now_ts()` — Trả timestamp float để khớp RawSignal/EvidenceItem trong cortex.
  - `iso_now()` — Timestamp người đọc được. Audit mà không đọc được thì cũng chỉ là trang trí.
  - `compact_text(value)` — Nén text để ledger không phình thành nghĩa địa token.
  - `atomic_write_json(path, payload)` — Ghi JSON bằng temp file rồi replace để giảm rủi ro hỏng file giữa chừng.
- Classes:
  - `EventLedgerRecord` (decorator=dataclass(slots=True)) — Một dòng sự kiện append-only. Ledger là nơi lưu cái đã xảy ra, không phải nơi phán xét nó có nghĩa gì. `content` có thể là dict, list hoặc s...
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `EventLedger` — Kho append-only cho raw event. Không có method update/delete public. Nếu muốn sửa, ghi event repair mới. Quá khứ mà sửa trực tiếp thì audit...
    - `__init__(self, path)`
    - `load(self)`
    - `save(self, records)`
    - `append(self, record)`
    - `append_raw_event(self)`
    - `append_from_signal(self, signal)` — Tạo record từ RawSignal-like object mà không buộc import cortex. Dùng getattr để file này vẫn sống đ...
    - `recent(self)`
    - `by_frame(self, frame_id)`
    - `query(self, text)`

## `memory/judgement/__init__.py`
- LOC: 17
- Docstring: Tầng phán xét memory: worthiness, retention, consolidation.

## `memory/judgement/consolidation.py`
- LOC: 61
- Functions:
  - `should_promote_candidate(candidate)` — Quyết định candidate có nên promote lên memory ổn định không. Dùng cho các mảnh kiểu tone feedback/vibe/logic chưa parse...
  - `merge_strength(existing_confidence, new_confidence, observations)` — Tăng confidence có giới hạn khi claim được quan sát lặp lại.
  - `_float(value, default)`
- Classes:
  - `ConsolidationDecision` (decorator=dataclass(frozen=True, slots=True))

## `memory/memory_activation.py`
- LOC: 162
- Classes:
  - `MemoryActivation` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `to_attention_line(self)`
  - `ScoredMemoryCandidate` (decorator=dataclass(slots=True))
  - `MemoryRetrievalResult` (decorator=dataclass(slots=True))
  - `MemoryActivationBuilder`
    - `__init__(self, profiles)`
    - `build(self, scored)`
    - `_route_bias(self, activations, route)`

## `memory/memory_ai_curator.py`
- LOC: 512
- Docstring: memory/memory_ai_curator.py =========================== AI curator cho memory — gọi Gemini để làm 2 việc rule không làm được: 1. Episodic distillation: Nhiều episode tương đồng → 1 semantic fact ổn định. Ví dụ: 5 lần user đề cập "thích câu ngắn" → semantic: us...
- Functions:
  - `_compact(value, limit)`
  - `_safe_float(value, default)`
  - `_get(obj, key, default)`
- Classes:
  - `CuratorResult` (decorator=dataclass(slots=True)) — Kết quả một lượt curator chạy.
    - `to_dict(self)`
  - `MemoryAICurator` — AI curator chạy trong background maintenance.
    - `__init__(self)`
    - `run_distillation(self)` — Distill episodic clusters → semantic facts.
    - `run_concern_bridge(self)` — Bridge concern chín → long-term memory.
    - `_cluster_episodes(self, items)` — Nhóm episode tương đồng theo summary token overlap.
    - `_distill_cluster(self, cluster)`
    - `_load_concerns(self, path)`
    - `_ripe_concerns(self, concerns)` — Lọc concern đủ chín để bridge.
    - `_bridge_concern(self, concern)`
    - `_commit_semantic_fact(self, fact)`
    - `_commit_from_bridge(self, decision)`
    - `_mark_concern_bridged(self, concern, path)` — Đánh dấu concern đã được bridge để không gọi lại.
    - `_call_llm(self, system, user)` — Gọi LLM qua llm_service.client (Gemini). Dùng thẳng client, không qua generate_chat_reply để tránh b...
    - `_parse_json(self, raw)`
    - `_to_namespace(d)`

## `memory/memory_candidate.py`
- LOC: 184
- Classes:
  - `MemoryCandidate` (decorator=dataclass(slots=True))
    - `rough_score(self)`
  - `CandidateBatch` (decorator=dataclass(slots=True))
  - `MemoryLayerAdapter` — Adapter đọc memory store bằng load()/recall() nếu có. Ưu tiên load() để scorer mới làm việc trên toàn item. Nếu store không có load(), fallb...
    - `__init__(self)`
    - `retrieve_candidates(self, cue)`
    - `_load_items(self, cue)`
    - `_candidate_for_record(self, record, cue)`

## `memory/memory_cognition.py`
- LOC: 618
- Docstring: Memory Cognition Core cho ERIS. Bản v2: - Commit protocol vẫn giữ nguyên: module khác chỉ tạo StateCommitRequest. - Recall không còn tự đo resonance bằng token overlap trong MemoryCognitionCore. - MemoryCognitionCore giờ là facade: route commit + gọi MemoryRet...
- Functions:
  - `_request_get(request, name, default)`
  - `_request_metadata(request)`
  - `_as_text_list(values)`
  - `_content_for_target(target, content)` — Normalize structured commit payloads before sending them to layer stores.
- Classes:
  - `MemoryQuery` (decorator=dataclass(slots=True))
  - `MemoryCommitDecision` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `CommitPolicy` (decorator=dataclass(slots=True)) — Rule chặn ghi nhớ bừa. Đây là commit permission, không phải retrieval permission. Ghi nhớ vẫn cần giấy tờ. Truy hồi thì dùng consequence sco...
  - `MemoryCognitionCore` — Facade chính của memory. Runtime chỉ nên giữ một instance class này. - commit(): ghi nhớ qua StateCommitRequest. - recall()/retrieve(): dựng...
    - `__init__(self, base_dir)`
    - `commit(self, request)`
    - `commit_many(self, requests)`
    - `lookup_fact(self, fact_key)`
    - `get_fact(self, fact_key)`
    - `semantic_lookup(self, fact_key)`
    - `recall(self, query)`
    - `retrieve(self, query)` — Truy hồi memory bằng retrieval engine mới. Không gọi packet resonance cũ. Không đo lại overlap trên...
    - `load(self)`
    - `save(self, snapshot)`
    - `render_context(self, query)`
    - `build_commit_request(self)`
    - `_normalize_request(self, request)`
    - `lookup_fact(self, fact_key)` — Lookup semantic fact value by fact_key for structured recall executor.
    - `search_memory_candidates(self, query)`
    - `candidate_trace_for_query(self, query)`
    - `load_active_state(self)`
    - `_check_commit_permission(self, request)`
    - `_commit_event_ledger(self, request)`
    - `_query_from_frame(self, frame)`
    - `_query_from_snapshot(self, snapshot)`
    - `_budget_from_frame(self, frame)`
    - `_quotas(self)`
    - `_packet_with_retrieval_resonance(self, packet)` — No-op compatibility helper. Resonance v2 đã nằm trong MemoryRetrievalEngine. Hàm này cố ý không làm...

## `memory/memory_commit_policy.py`
- LOC: 1028
- Functions:
  - `_strip_accents(text)`
  - `normalize_vi(text)` — Normalize tiếng Việt để match rule ổn định hơn. Bản normalize chỉ dùng để nhận diện. Không dùng nó làm surface public, v...
  - `_clean_value(value)`
  - `_evidence(turn_id)`
  - `_has_self_marker(norm)`
  - `_looks_like_question(norm, raw)` — Chặn recall query khỏi bị commit nhầm thành fact. "tôi tên gì", "tôi bao nhiêu tuổi", "tôi đang ở đâu" là câu hỏi. "nhớ...
  - `_extract_with_patterns(raw, patterns)`
  - `_year_from_2k(token)`
  - `_bounded_month(value)`
  - `_explicit_importance(norm)`
  - `_looks_like_convention(norm)`
  - `_guess_domain(norm)`
  - `_candidate_fact_keys(norm, domain)`
  - `_slug_key(value)`
- Classes:
  - `MemoryCommitPolicy` (decorator=dataclass(slots=True)) — Memory intake 3 tầng cho user turn. Tầng 1: phát hiện importance. Tầng 2: cố extract semantic/episodic/procedural fact rõ. Tầng 3: nếu expli...
    - `__post_init__(self)`
    - `set_semantic_parser(self, parser)` — Gắn parser model.gguf/hybrid sau khi khởi tạo runtime. Parser chỉ đọc nghĩa và trả MeaningFrame. Nó...
    - `decide_from_user_turn(self, user_text)`
    - `_decide_with_semantic_claims(self, raw, turn_id)` — Chạy pipeline claim/ontology trước các rule legacy. Nếu claim đến từ AI classification (extraction_m...
    - `_decision_from_ai_classification(self, extracted, claim)` — Tạo MemoryCommitDecision trực tiếp từ AI classification. AI đã quyết định storage_target, importance...
    - `_decision_from_semantic_claim(self, claim, retention)`
    - `_surface_claim_for_semantic_claim(self, claim)`
    - `_memory_kind_for_semantic_claim(self, claim)`
    - `_decay_for_retention(self, decay_policy)`
    - `_extract_user_name(self, raw, norm, turn_id)`
    - `_extract_birth_year(self, raw, norm, turn_id)`
    - `_extract_birth_month(self, raw, norm, turn_id)`
    - `_extract_age_observed(self, raw, norm, turn_id)`
    - `_extract_current_residence(self, raw, norm, turn_id)`
    - `_extract_temporal_residence(self, raw, norm, turn_id)`
    - `_extract_user_convention(self, raw, norm, turn_id)`
    - `_extract_response_style(self, raw, norm, turn_id)`
    - `_extract_memory_test_hint(self, raw, norm, turn_id)`
    - `_extract_general_preference(self, raw, norm, turn_id)`
    - `_build_unresolved_candidate(self, raw, norm, turn_id, importance, importance_reasons)`
    - `_dedupe(self, decisions)`

## `memory/memory_consolidator.py`
- LOC: 80
- Classes:
  - `ConsolidationResult` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `MemoryConsolidator`
    - `__init__(self, memory_core)`
    - `run_once(self)`

## `memory/memory_cue.py`
- LOC: 332
- Classes:
  - `MemoryCue` (decorator=dataclass(slots=True))
    - `all_text(self)`
    - `token_set(self)`
    - `anchor_set(self)`
    - `layer_allowed(self, layer)`
    - `to_dict(self)`
  - `MemoryCueBuilder` — Dựng cue từ query/frame mà không import CognitiveFrame cứng. Dùng best-effort getattr để module này sống được trong runtime cũ lẫn mới.
    - `from_query_or_frame(self, query)`
    - `_extract_user_text(self, frame)`
    - `_extract_dominant_thread(self, frame)`
    - `_extract_semantic_family(self, frame)`
    - `_extract_task_intent(self, frame)`
    - `_extract_files(self, text)`
    - `_extract_modules(self, text)`
    - `_looks_like_current_evidence_request(self, text)`
    - `_looks_like_exact_recall_request(self, text)`
    - `_allowed_layers(self)`
    - `_repair_tags(self, text)`
    - `_affect_tags(self, frame)`
    - `_relation_tags(self, frame)`
    - `_privacy_sensitivity(self, text)`

## `memory/memory_kernel.py`
- LOC: 496
- Classes:
  - `MemoryKernelDebugSnapshot` (decorator=dataclass(slots=True)) — Snapshot nhỏ cho dev mode. Không đưa thẳng ra public chat. Đây là để log/debug UI.
    - `to_dict(self)`
  - `MemoryKernel` — Facade chính cho toàn bộ memory runtime. Cách dùng khuyến nghị: kernel = MemoryKernel(base_dir="memory_core", semantic_parser=parser) kernel...
    - `__init__(self, base_dir)`
    - `from_existing_core(cls, core)` — Bọc MemoryCognitionCore hiện có mà không migrate store ngay. Dùng trong runtime chuyển tiếp: coordin...
    - `ingest(self, text)` — Đưa một mảnh text/evidence vào memory lifecycle. Đây là cổng ingest duy nhất mà runtime nên gọi. mod...
    - `answer(self, query)` — Trả lời deterministic cho câu hỏi memory nếu đủ chắc. Hàm này không gọi LLM để trả lời. Nếu compiler...
    - `build_packet(self, query)` — Dựng MemoryPacket/resonance context cho cognition. Packet không phải exact answer. Packet là áp lực...
    - `maintain(self)` — Chạy maintenance nền. Không gọi trong hot path chat. Gọi từ idle/reflection/session end.
    - `commit(self, request)` — Compat: route commit cũ xuống core. Runtime mới nên gọi ingest(), nhưng StateCommitter cũ vẫn có thể...
    - `commit_many(self, requests)`
    - `recall(self, query)` — Compat với MemoryCognitionCore.recall().
    - `retrieve(self, query)`
    - `load(self)`
    - `save(self, snapshot)`
    - `render_context(self)`
    - `lookup_fact(self, fact_key)`
    - `debug_snapshot(self)`
    - `_annotate_request(self, request)` — Gắn metadata kernel vào StateCommitRequest/dict. request hiện có thể là dict từ memory_models.to_sta...
    - `_compile_debug(self, compile_result)`

## `memory/memory_kernel_contracts.py`
- LOC: 223
- Classes:
  - `MemoryKernelConfig` (decorator=dataclass(slots=True)) — Config runtime cho MemoryKernel. Các ngưỡng ở đây là ngưỡng orchestration, không thay thế worthiness/retention. Worthiness/retention vẫn là...
  - `MemoryIngestResult` (decorator=dataclass(slots=True)) — Kết quả ingest một mảnh text/evidence. `decisions` là output từ MemoryIngestPolicy/MemoryCommitPolicy. `commit_results` là output từ MemoryC...
    - `committed_count(self)` — Số commit được nhận bởi store. Một số commit_result dùng enum/string khác nhau, nên check mềm.
    - `to_dict(self)` — Dump debug an toàn cho log/dev panel.
  - `MemoryAnswerResult` (decorator=dataclass(slots=True)) — Kết quả answer deterministic từ MemoryKernel. `answer` thường là RecallAnswer từ memory_query_ir. Kernel không convert thẳng sang Decision p...
    - `text(self)` — Text public nếu có answer.
    - `confidence(self)` — Confidence mềm để runtime quyết có dùng answer hay không.
    - `to_dict(self)`
  - `MemoryMaintenanceReport` (decorator=dataclass(slots=True)) — Báo cáo maintain memory. Maintain là việc nền: consolidate candidate, prune expired, check contradiction. Báo cáo này cố tình định lượng đơn...
    - `to_dict(self)`

## `memory/memory_maintenance.py`
- LOC: 248
- Classes:
  - `MemoryMaintenanceRunner` — Orchestrator maintain nhẹ cho memory stores.
    - `__init__(self, memory_core)`
    - `run(self)` — Chạy một lượt maintain. destructive=None nghĩa là dùng default từ runner. destructive=False nghĩa là...
    - `_candidate_limit(self, budget)`
    - `_run_access_decay(self)` — Áp half-life decay lên access_count trong semantic và episodic store. Mục đích: hot fact không chiếm...
    - `_run_prune_audit(self)` — Chạy prune trên các store có load/save. Các action: - keep: giữ nguyên. - archive: hiện chỉ thống kê...

## `memory/memory_models.py`
- LOC: 216
- Functions:
  - `_state_decay_from_memory_decay(decay)`
  - `_commit_kind_for_target(target)`
  - `_commit_content_from_decision(decision, metadata)`
- Classes:
  - `MemoryTarget` (base=str, Enum) — Loại kho nhớ mà một fact/candidate nên đi vào.
  - `SurfaceMode` (base=str, Enum) — Cách ký ức được phép hiện ra ngoài khi recall.
  - `DecayPolicy` (base=str, Enum) — Độ bền của ký ức.
  - `MemoryCommitKind` (base=str, Enum) — Loại commit request ở tầng intake.
  - `MemoryKind` (base=str, Enum) — Nhãn nghĩa cấp cao, tránh để các tầng sau phải đoán từ text thô.
  - `MemoryCommitDecision` (decorator=dataclass(frozen=True)) — Quyết định commit một mảnh thông tin. Đây không phải bản ghi memory cuối cùng. Nó là request có policy rõ: lưu vào đâu, mặt ngoài hiện thế n...
    - `to_state_commit_request(self)` — Chuyển sang StateCommitRequest của project nếu import được. Nếu shape trong project khác, sửa đúng m...
  - `RecallRequest` (decorator=dataclass(frozen=True)) — Yêu cầu recall đã được phân loại trước khi đụng tới memory thật.
  - `RecallAnswer` (decorator=dataclass(frozen=True)) — Câu trả lời recall đã qua policy, có confidence và trace để debug.

## `memory/memory_packet_builder.py`
- LOC: 179
- Classes:
  - `MemoryPacket` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `to_attention_lines(self)`
    - `render_prompt_context(self)`
  - `MemoryPacketBuilder`
    - `from_retrieval_result(self, result)`
    - `fit_budget(self, packet)`
    - `_confidence_notes(self, packet)`

## `memory/memory_pruner.py`
- LOC: 123
- Functions:
  - `_metadata(item)`
  - `_float(value, default)`
  - `_epoch(value)`
  - `_surface_text(item)`
  - `_looks_like_trivial_semantic_noise(surface, semantic_source)`
- Classes:
  - `PruneDecision` (decorator=dataclass(frozen=True, slots=True))
  - `MemoryPruner` — Pruner dựa trên retention metadata nếu có.
    - `decide(self, item)`

## `memory/memory_query_compiler.py`
- LOC: 347
- Functions:
  - `_best_or(scores, default)`
- Classes:
  - `CompileDebug` (decorator=dataclass(slots=True))
  - `MemoryQueryCompileResult` (decorator=dataclass(slots=True))
    - `has_query(self)`
  - `MemoryQueryCompiler` — Blend slot + semantic + repair + optional LLM parser thành IR.
    - `__init__(self)`
    - `compile(self, text)`
    - `_inject_semantic_hypotheses(self, text, hypotheses, hint)` — Nếu slot parser không sinh được gì, semantic hint có thể sinh hypothesis mềm. Semantic không được ex...
    - `_apply_semantic_scores(self, hypotheses, hint)`
    - `_top_margin(self, hypotheses)`
    - `_ambiguity(self, hypotheses, hint)`
    - `_suppression_note(self, hypotheses, hint, ambiguity)`

## `memory/memory_query_executor.py`
- LOC: 367
- Functions:
  - `_unwrap_fact_value(value)`
  - `_looks_like_internal_memory_object(value)`
  - `_looks_like_internal_memory_surface(text)`
  - `_deep_get(data, fact_key)`
- Classes:
  - `MemoryQueryExecutor` — Thực thi IR trên graph và memory_core.
    - `execute(self, ir)`
    - `_execute_turn_recall(self, ir, graph)`
    - `_execute_fact_recall(self, ir)`
    - `_lookup_fact(self, memory_core, fact_key)`
    - `_format_fact(self, fact_key, value)`
    - `_execute_summary(self, ir, graph)`

## `memory/memory_query_ir.py`
- LOC: 369
- Functions:
  - `clamp01(value)`
  - `blend_confidence()` — Trung bình mềm cho các confidence hợp lệ.
  - `add_warning(ir, warning)`
- Classes:
  - `QueryIntent` (base=str, Enum) — Loại truy vấn ký ức ở cấp cao.
  - `RoleRef` (base=str, Enum) — Role mà query đang trỏ tới.
  - `ActRef` (base=str, Enum) — Hành vi hội thoại mà query cần lấy.
  - `RelationRef` (base=str, Enum) — Quan hệ giữa target và anchor. Ví dụ: - SELF: lấy chính target. - ANSWER_TO: lấy câu assistant trả lời cho một câu hỏi user. - BEFORE/AFTER:...
  - `SurfaceMode` (base=str, Enum) — Cách được phép surface câu trả lời ra public.
  - `MemorySourceKind` (base=str, Enum) — Nguồn ký ức mà executor dùng để trả.
  - `MemorySelector` (decorator=dataclass(slots=True)) — Bộ chọn node/fact trong memory. Lưu ý: - ordinal dùng cho exact ordinal như "câu hỏi thứ 3". - quantity dùng cho recent batch như "3 câu hỏi...
    - `is_empty(self)`
    - `compact(self)`
  - `MemoryRelation` (decorator=dataclass(slots=True)) — Quan hệ query giữa target và anchor.
    - `compact(self)`
  - `MemoryQueryIR` (decorator=dataclass(slots=True)) — AST truy vấn ký ức. Đây là output của compiler, input của executor. Không nên chứa text answer. IR chỉ nói "cần lấy cái gì".
    - `normalized(self)` — Trả bản sao với confidence/ambiguity được kẹp vào [0, 1].
    - `signature(self)` — Chữ ký cấu trúc để repair prior so khớp. Không dùng raw_text, vì mục tiêu là học từ cấu trúc query c...
    - `compact(self)`
  - `QueryHypothesis` (decorator=dataclass(slots=True)) — Một giả thuyết query trong quá trình compile. Compiler nên sinh nhiều hypothesis, xếp hạng, rồi chọn best. Đây là chống "chọn nghĩa quá sớm"...
    - `normalized(self)`
  - `RawRecallResult` (decorator=dataclass(slots=True)) — Kết quả thô sau khi executor chạy query. Đây chưa phải câu public cuối cùng. Policy còn phải quyết định quote/gist/ uncertain.
    - `missing(cls, ir, warning, source)`
  - `RecallAnswer` (decorator=dataclass(slots=True)) — Câu trả lời đã được policy surface. Adapter có thể đổi object này thành Decision payload.
    - `uncertain(cls, text)`

## `memory/memory_query_llm_parser.py`
- LOC: 215
- Functions:
  - `_enum(enum_cls, value, default)`
  - `_int_or_none(value)`
- Classes:
  - `MemoryQueryLLMClient` (base=Protocol) — Client tối thiểu cần có. Có thể adapter từ LlmService hiện tại: - gửi system prompt + user text - trả raw string JSON
    - `complete_json(self)`
  - `LLMParseDecision` (decorator=dataclass(slots=True))
  - `MemoryQueryLLMParser` — Parser LLM có schema, chỉ dùng khi compiler cần.
    - `__init__(self, client)`
    - `should_use_llm(self)`
    - `parse(self, text)`
    - `build_system_prompt(self)`
    - `schema(self)`
    - `_parse_json(self, raw)`
    - `_dict_to_ir(self, data)`
    - `_selector(self, data)`

## `memory/memory_query_repair.py`
- LOC: 277
- Functions:
  - `_ir_to_dict(ir)`
  - `_selector_to_dict(sel)`
  - `_ir_from_dict(data)`
  - `normalize_vi(text)`
  - `text_similarity(a, b)`
- Classes:
  - `MemoryQueryRepairItem` (decorator=dataclass(slots=True))
  - `RepairPriorResult` (decorator=dataclass(slots=True))
  - `MemoryQueryRepairStore` — Store nhỏ cho repair query. Có thể thay bằng repair_memory thật của project sau.
    - `__init__(self, items)`
    - `record(self)`
    - `apply_prior(self)`
    - `save_json(self, path)`
    - `load_json(cls, path)`

## `memory/memory_query_semantics.py`
- LOC: 352
- Functions:
  - `normalize_vi(text)`
  - `_token_similarity(a, b)`
  - `cosine(a, b)`
  - `_ambiguity(scores)`
  - `_top(scores)`
- Classes:
  - `EmbeddingProvider` (base=Protocol) — Provider embedding tùy chọn. Không bắt buộc.
    - `embed(self, text)`
  - `SemanticQueryHint` (decorator=dataclass(slots=True)) — Gợi ý semantic, không phải query cuối.
    - `top_intent(self)`
    - `top_fact_key(self)`
  - `MemoryQuerySemanticHintEngine` — Prototype semantic scorer. Có thể chạy ở 2 mode: - fallback prototype token similarity: ổn để bootstrap, cap confidence. - provider embeddin...
    - `__init__(self, embedding_provider)`
    - `analyze(self, text)`
    - `_fallback_hint(self, norm)`
    - `_embedding_hint(self, norm)`
    - `_score_enum_prototypes(self, text_vec, bank, enum_cls)`
    - `_score_string_prototypes(self, text_vec, bank)`
    - `_prototype_cosine(self, text_vec, phrase)`

## `memory/memory_query_slot_parser.py`
- LOC: 671
- Functions:
  - `infer_target_role(norm)`
  - `infer_target_act(norm)`
  - `infer_anchor(norm)`
  - `infer_relation(norm)`
  - `infer_fact_key(norm)`
  - `infer_self_disclosure_fact(norm)`
  - `asks_count(norm)`
  - `asks_summary(norm)`
  - `asks_exact(norm)`
  - `looks_recent(norm)`
  - `looks_like_generic_recall_request(norm)`
  - `extract_quantity(norm)`
  - `extract_ordinal(norm)`
  - `extract_semantic_anchor(norm)`
  - `_signal_value(signals, name)`
  - `normalize_vi(text)`
  - `parse_vi_number(value)`
  - `_looks_like_name_disclosure(norm)`
  - `user_is_declaring_or_updating_fact(text)`
  - `_looks_like_fact_update_disclosure(norm)`
  - `_looks_like_fact_update_question(norm)`
  - `_looks_like_birth_month_disclosure(norm)`
  - `_looks_like_hometown_disclosure(norm)`
  - `_looks_like_living_location_disclosure(norm)`
  - `_looks_like_location_preference_disclosure(norm)`
  - `_looks_like_current_location_disclosure(norm)`
  - `_looks_like_past_location_disclosure(norm)`
- Classes:
  - `SlotSignal` (decorator=dataclass(slots=True)) — Một tín hiệu slot rút từ text.
  - `SlotParseResult` (decorator=dataclass(slots=True)) — Kết quả parse slot.
    - `has_self_disclosure(self)`
  - `MemoryQuerySlotParser` — Parser slot nhẹ. Dùng cho tiếng Việt thân mật kiểu: - "câu hỏi thứ 2 tôi từng hỏi là gì" - "câu trả lời của em cho câu hỏi thứ 3" - "3 câu h...
    - `parse(self, text)`
    - `_extract_signals(self, raw, norm)`
    - `_build_hypotheses(self, raw, norm, signals)`
    - `_target_from_signals(self, signals)`
    - `_confidence(self, signals)`

## `memory/memory_recall_policy.py`
- LOC: 248
- Classes:
  - `RecallPolicyConfig` (decorator=dataclass(slots=True))
  - `MemoryRecallSurfacePolicy` — Policy surface kết quả recall thành câu public.
    - `__init__(self, config)`
    - `surface(self, result)`
    - `_exact_text(self, result, text)`
    - `_count_text(self, result)`
    - `_missing_text(self, result)`
    - `_trace(self, result)`
    - `_safe_public_text(self, text)`
    - `_looks_like_raw_object_surface(self, text)`

## `memory/memory_record.py`
- LOC: 414
- Functions:
  - `compact_text(value)` — Nén text để memory packet không kéo prompt thành bãi rác token.
  - `clamp01(value)` — Ép số về [0, 1].
  - `stable_hash(text, length)`
  - `normalize_text(text)` — Chuẩn hóa text để match ổn hơn. Chú ý: - Bỏ dấu để không vỡ khi data có/không dấu. - Không dùng normalize này để "hiểu n...
  - `tokenize(text)` — Token hóa có lọc stopword. Token file/module được giữ lại vì trong project ERIS, anchor kỹ thuật thường quan trọng hơn t...
  - `token_bigrams(tokens)`
  - `weighted_counter(tokens)` — Counter có trọng số cho anchor kỹ thuật.
  - `weighted_jaccard(left, right)`
  - `phrase_score(query_norm, text_norm)` — Phrase match đủ dài, không tính token đơn như chân lý.
  - `extract_anchors(text)` — Rút anchor mạnh: file, module, symbol, failure tags. Anchor không phải keyword chung. Nó là dấu móc có giá trị truy hồi:...
  - `parse_timestamp(value)` — Parse timestamp best-effort. Nếu parse không được, trả 0. Memory cũ không nên làm runtime chết vì format.
  - `recency_score(timestamp)`
  - `record_from_layer_item(layer, item)` — Adapter mềm từ store item cũ sang MemoryRecord. Không đụng vào store cũ. Cứ để chúng sống thêm một lúc, như di sản kỹ th...
  - `_default_surface_policy(layer)`
- Classes:
  - `MemoryRecord` (decorator=dataclass(slots=True)) — Record thống nhất cho mọi memory layer. Các layer cũ vẫn có thể giữ class riêng. Retrieval v2 chỉ yêu cầu adapter chuyển chúng về MemoryReco...
    - `normalized_text(self)`
    - `tokens(self)`
    - `anchor_set(self)`
    - `recall_line(self)`
    - `to_dict(self)`

## `memory/memory_retention_policy.py`
- LOC: 134
- Functions:
  - `retention_metadata(decision)`
- Classes:
  - `RetentionDecision` (decorator=dataclass(frozen=True, slots=True))
  - `MemoryRetentionPolicy` — Policy retention cho SemanticClaim.
    - `decide(self, claim, worthiness)`

## `memory/memory_retrieval_engine.py`
- LOC: 93
- Classes:
  - `MemoryStores` (decorator=dataclass(slots=True))
    - `as_layer_map(self)`
  - `MemoryRetrievalEngine`
    - `__init__(self, stores)`
    - `retrieve(self, cue)`

## `memory/memory_scoring.py`
- LOC: 339
- Classes:
  - `LayerProfile` (decorator=dataclass(frozen=True, slots=True))
  - `MemoryScore` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `MemoryScorer`
    - `__init__(self, profiles)`
    - `score(self, cue, candidate)`
    - `_privacy_penalty(self, cue, record)`
    - `_risk_penalty(self, cue, candidate)`

## `memory/memory_turn_annotator.py`
- LOC: 400
- Functions:
  - `normalize_vi(text)`
  - `parse_vietnamese_number(text)`
- Classes:
  - `TurnAnnotation` (decorator=dataclass(slots=True))
  - `TurnAnnotator` — Annotator nhẹ, đủ tốt để build TurnGraph trước khi semantic layer sâu hơn.
    - `annotate(self)`
    - `build_edges(self, graph)` — Dựng các cạnh ANSWERS/CORRECTS/REPEATS/STORES_FACT sau khi có nodes.
    - `_find_recent_correctable(self, graph, before_index)`
    - `extract_fact_mentions(self)`
    - `_looks_like_question(self, raw, norm)`
    - `_looks_like_correction(self, norm)`
    - `_looks_like_command(self, norm)`
    - `_is_service_fallback(self, norm, metadata)`

## `memory/memory_turn_graph.py`
- LOC: 435
- Functions:
  - `_get(obj, key, default)`
  - `_role_from_any(value)`
  - `_role_ref_to_turn(role)`
  - `_act_ref_to_turn(act)`
  - `_norm(text)`
  - `_text_relevance(hint, text, tags)` — Relevance lexical nhẹ cho semantic_hint. Không dùng cho ordinal.
- Classes:
  - `TurnRole` (base=str, Enum)
  - `TurnSpeechAct` (base=str, Enum)
  - `TurnEdgeType` (base=str, Enum)
  - `FactMention` (decorator=dataclass(slots=True)) — Fact được phát hiện trong turn, ví dụ user.birth_month=8.
  - `TurnNode` (decorator=dataclass(slots=True)) — Node hội thoại. index là thứ tự toàn phiên, bắt đầu 1. role_index là thứ tự trong cùng role, ví dụ user turn thứ 3. act_index là thứ tự theo...
    - `counts_as_answer(self)` — Fallback/service-error không nên bị tính là câu trả lời nội dung.
    - `is_question(self)`
  - `TurnEdge` (decorator=dataclass(slots=True)) — Cạnh quan hệ giữa hai turn.
  - `TurnGraph` — Graph phiên hiện tại. Dùng để thực thi query exact: - nth user question - assistant answer to nth user question - last N user questions - co...
    - `__init__(self)`
    - `add_turn(self, node)`
    - `add_edge(self, edge)`
    - `get(self, node_id)`
    - `from_turns(cls, turns)`
    - `from_session_ledger(cls, session_ledger)` — Adapter mềm từ session_turn_ledger hiện tại. Không ép shape cụ thể. Chỉ cần ledger có: - turns - all...
    - `infer_basic_answer_edges(self)` — Nối assistant answer với user question gần nhất trước đó.
    - `select(self, selector)` — Chọn nodes theo MemorySelector. Không hiểu raw text user query.
    - `first_assistant_answer_to(self, user_question_id)` — Lấy assistant node có edge ANSWERS -> user_question_id.
    - `neighbor_after(self, node_id, selector)`
    - `neighbor_before(self, node_id, selector)`
    - `count(self, selector)`
    - `last_n(self, selector, n)`

## `memory/memory_worthiness.py`
- LOC: 135
- Classes:
  - `WorthinessDecision` (decorator=dataclass(frozen=True, slots=True))
  - `MemoryWorthinessPolicy` — Policy chặn ghi nhớ bừa trước khi retention tính decay.
    - `decide(self, claim)`

## `memory/persistence.py`
- LOC: 340
- Functions:
  - `time_safe_suffix()` — Timestamp dùng được trong tên file backup.
  - `load_memory_bundle(path)` — Helper ngắn cho code không muốn giữ instance persistence.
  - `save_memory_bundle(path, bundle)` — Helper ngắn để ghi bundle.
  - `update_memory_bundle(path, mutator)` — Helper ngắn cho thao tác load-mutate-save.
- Classes:
  - `MemoryPersistenceConfig` (decorator=dataclass(frozen=True)) — Cấu hình đọc/ghi memory JSON.
    - `resolved_path(self)` — Trả path đã expand user/env.
  - `MemoryPersistenceError` (base=RuntimeError) — Lỗi persistence có ngữ cảnh rõ ràng hơn JSONDecodeError trần trụi.
  - `JsonMemoryPersistence` — Lớp persistence chính cho MemoryStateBundle. Ghi file bằng atomic replace: 1. ghi vào temporary file cùng thư mục, 2. fsync, 3. os.replace s...
    - `__init__(self, config)`
    - `load_bundle(self)` — Load toàn bộ memory bundle. File chưa tồn tại thì trả bundle rỗng.
    - `save_bundle(self, bundle)` — Ghi toàn bộ bundle xuống disk bằng atomic write.
    - `update_bundle(self, mutator)` — Load -> mutate -> save trong cùng một lock. mutator có thể sửa in-place và trả None, hoặc trả bundle...
    - `append_to_collection(self, collection_name, record)` — Append một record vào collection trong bundle rồi lưu.
    - `replace_collection(self, collection_name, records)` — Thay toàn bộ một collection. Dùng cho compaction/decay.
    - `set_active_state(self, snapshot)` — Overwrite active_state snapshot.
    - `append_commit_audit(self, decision)` — Append audit decision để debug vì sao memory được lưu/bị bỏ.
    - `compact(self)` — Cắt bớt collection theo giới hạn giữ lại gần nhất. Hàm này không quyết định decay semantic phức tạp....
    - `load_raw(self)` — Load dict JSON thô. File chưa tồn tại thì trả dict rỗng.
    - `save_raw(self, data)` — Ghi dict JSON thô bằng atomic write.
    - `exists(self)`
    - `backup_now(self, suffix)` — Tạo backup thủ công và trả path backup.
    - `_atomic_write_text(self, text)`
    - `_rotate_backups(self)` — Giữ một vòng backup đơn giản: file.bak1, file.bak2, ...
    - `_migrate_raw(self, raw)` — Migration rất nhẹ cho schema cũ/thiếu field. Không cố đoán nghiệp vụ. Chỉ đảm bảo các key nền tồn tạ...

## `memory/predicate_ontology.py`
- LOC: 394
- Functions:
  - `get_predicate(name)`
  - `fact_key_for_predicate(predicate)`
  - `predicate_for_fact_key(fact_key)`
  - `predicate_aliases(predicate)`
  - `entailment_for_target(claim, target)` — Claim có được dùng để trả lời answer target không? Ví dụ: - preference_location -> user_hometown = FORBIDDEN - mentioned...
  - `contradicts(a, b)` — Mâu thuẫn rõ khi cùng subject + predicate contradicts + object khác. Không cố NLP sâu ở đây. Nếu claim phức tạp, để cons...
  - `is_long_term_predicate(predicate)`
  - `storage_layer_for_predicate(predicate)`
  - `default_decay_for_predicate(predicate)`
  - `importance_for_predicate(predicate)`
  - `_compatible_targets(predicates)`
  - `_norm(text)`
- Classes:
  - `EntailmentType` (base=str, Enum)
  - `PredicateSpec` (decorator=dataclass(frozen=True, slots=True))

## `memory/procedural_memory.py`
- LOC: 201
- Docstring: Procedural Memory: cách xử lý đã học. Đây là nơi lưu rule kiểu: khi user sửa hiểu lầm, trả lời trực tiếp trước; khi evidence yếu, không claim nhìn thấy màn hình. Procedural là policy học được, không phải fact về user.
- Functions:
  - `iso_now()`
  - `compact_text(value)`
  - `clamp01(value)`
  - `key_for(trigger, rule)`
  - `atomic_write_json(path, payload)`
- Classes:
  - `ProceduralMemoryItem` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `recall_line(self)`
  - `ProceduralMemoryStore`
    - `__init__(self, path)`
    - `load(self)`
    - `save(self, items)`
    - `apply_commit(self, request)`
    - `recall(self, query)`
    - `_infer_trigger(self, rule, reason)`
    - `_default_items(self)`
    - `_merge_defaults(self, items)`

## `memory/query_intent.py`
- LOC: 213
- Functions:
  - `compile_semantic_query(text)`
  - `normalize_vi(text)` — Alias cũ cho code đang import normalize_vi từ query_intent.
  - `_clamp01(value)`
- Classes:
  - `SemanticQueryIntent` (decorator=dataclass(frozen=True, slots=True))
    - `is_known(self)`
  - `QueryTargetFrame` (decorator=dataclass(frozen=True, slots=True)) — Một target câu hỏi ở mức ontology. `fallback_cues` chỉ dùng khi không có model parse. Chúng không phải luật answer. ClaimEntailmentEngine mớ...
  - `QueryIntentParserProtocol`
    - `parse(self, text)`
  - `SemanticQueryIntentCompiler` (decorator=dataclass(slots=True)) — Compiler query có hook cho model parser. `structured_parser` có thể là adapter model.gguf của Ngài. Nó nên trả: {"answer_target":"user_homet...
    - `compile(self, text)`
    - `_from_structured(self, raw, data)`
    - `_fallback_compile(self, raw)`
    - `_score(self, norm, frame)`

## `memory/relational_memory.py`
- LOC: 202
- Docstring: Relational Memory: nhịp quan hệ, rupture, repair, khoảng cách. Đây không phải nơi lưu "user is sad". Nó lưu pattern có bằng chứng: user sửa ERIS khi overread, user thích câu trả lời kỹ thuật trực tiếp, rupture cần repair. Tức là ký ức quan hệ, không phải bói c...
- Functions:
  - `iso_now()`
  - `compact_text(value)`
  - `clamp01(value)`
  - `atomic_write_json(path, payload)`
- Classes:
  - `RelationalMemoryItem` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `recall_line(self)`
  - `RelationalMemoryStore`
    - `__init__(self, path)`
    - `load(self)`
    - `save(self, items)`
    - `apply_commit(self, request)`
    - `recall(self, query)`
    - `_infer_pattern(self, claim, reason)`
    - `_trust_delta(self, pattern)`
    - `_distance_delta(self, pattern)`

## `memory/repair_memory.py`
- LOC: 248
- Docstring: Repair Memory: ghi lỗi, sửa sai, suppression rule tương lai. Nếu user nói "không phải", hệ thống không được chỉ xin lỗi rồi quên. Nó phải lưu loại lỗi, assumption sai, evidence, chiến lược sửa. Đây là nơi ERIS học bớt ngu theo thời gian, một kỳ vọng khiêm tốn.
- Functions:
  - `iso_now()`
  - `compact_text(value)`
  - `clamp01(value)`
  - `atomic_write_json(path, payload)`
- Classes:
  - `RepairMemoryItem` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `recall_line(self)`
  - `RepairMemoryStore`
    - `__init__(self, path)`
    - `load(self)`
    - `save(self, items)`
    - `apply_commit(self, request)`
    - `recall(self, query)`
    - `_extract_field(self, text, field_name)`
    - `_infer_failure_type(self, content, reason)`
    - `_guess_wrong_assumption(self, content, reason)`
    - `_default_strategy(self, failure_type)`
    - `_default_suppression_rule(self, failure_type)`

## `memory/schemas.py`
- LOC: 490
- Functions:
  - `now_iso()` — Trả timestamp ISO đơn giản, có timezone local.
  - `make_memory_id(prefix)` — Tạo id ngắn nhưng đủ ổn định cho record memory.
  - `clamp01(value)` — Ép một giá trị về khoảng [0, 1]. Dữ liệu memory không cần drama số học.
  - `_tuple_str(value)` — Chuẩn hóa list/tuple/set/string về tuple[str, ...].
  - `_dict_value(value)` — Chuẩn hóa một object mapping thành dict thường.
  - `coerce_dataclass(cls, value)` — Ép dict/dataclass/object về dataclass cls, bỏ qua field lạ. Persistence cần chịu được schema cũ. Nếu mỗi lần thêm field...
  - `_coerce_record_tuple(value, cls)`
  - `to_plain_data(value)` — Chuyển dataclass/enum/tuple thành dữ liệu JSON-friendly.
  - `bundle_from_mapping(data)` — Tạo MemoryStateBundle từ dict thô đã load từ JSON.
  - `bundle_to_mapping(bundle)` — Chuyển MemoryStateBundle về dict JSON-friendly.
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
    - `mark_tentative(self, reason)` — Đánh dấu record là tentative, thường dùng khi confidence thấp nhưng chưa đáng bỏ.
    - `touch(self)` — Cập nhật timestamp và có thể merge confidence/evidence.
  - `EventLedgerEntry` (decorator=dataclass) — Sự kiện thô hoặc gần-thô. Ledger là append-only, không rewrite quá khứ.
    - `__post_init__(self)`
  - `ActiveStateSnapshot` (decorator=dataclass) — Snapshot overwrite cho trạng thái đang là của runtime.
    - `__post_init__(self)`
  - `EpisodicMemoryRecord` (base=MemoryRecordBase; decorator=dataclass) — Memory về một chuyện cụ thể đã xảy ra.
    - `__post_init__(self)`
  - `SemanticMemoryRecord` (base=MemoryRecordBase; decorator=dataclass) — Fact ổn định hoặc gần ổn định. Nếu chưa chắc, status phải là tentative.
    - `__post_init__(self)`
  - `RelationalMemoryRecord` (base=MemoryRecordBase; decorator=dataclass) — Pattern quan hệ/tương tác tích tụ qua nhiều turn.
    - `__post_init__(self)`
  - `AffectiveResidueRecord` (base=MemoryRecordBase; decorator=dataclass) — Dư âm cảm xúc như pressure nội bộ, không phải lời tuyên bố cảm xúc công khai.
    - `__post_init__(self)`
  - `ProceduralMemoryRecord` (base=MemoryRecordBase; decorator=dataclass) — Luật xử lý đã học: gặp trigger X thì nên xử lý bằng cách Y.
    - `__post_init__(self)`
  - `RepairMemoryRecord` (base=MemoryRecordBase; decorator=dataclass) — Memory sửa lỗi: user correction, wrong assumption, suppression rule lần sau.
  - `MemoryPacket` (decorator=dataclass) — Gói recall đã được cắt budget để downstream dùng, thay vì nhét cả database vào prompt.
    - `__post_init__(self)`
  - `MemoryStateBundle` (decorator=dataclass) — Một bundle JSON đầy đủ cho persistence. Các store riêng có thể dùng toàn bộ bundle hoặc chỉ đọc collection mình cần.
    - `__post_init__(self)`
    - `with_updated_timestamp(self)` — Cập nhật timestamp in-place rồi trả chính bundle để tiện chain.

## `memory/semantic_answer_policy.py`
- LOC: 115
- Classes:
  - `SemanticAnswer` (decorator=dataclass(frozen=True, slots=True))
  - `SemanticAnswerPolicy` — Chọn claim exact và format câu trả lời ngắn, grounded.
    - `__init__(self)`
    - `answer(self, query, memory_items)`
    - `_missing_text(self, intent)`
    - `_format(self, intent, claim)`

## `memory/semantic_claim.py`
- LOC: 291
- Functions:
  - `make_claim_id(seed)` — Sinh id ổn định theo nội dung claim. Id ổn định giúp test và merge dễ chịu hơn một chút. Không dùng làm bảo mật.
  - `build_claim()`
  - `_clamp01(value)`
  - `_coerce_literal(value, allowed, default)`
- Classes:
  - `SemanticClaim` (decorator=dataclass(frozen=True, slots=True)) — Một mệnh đề semantic đã chuẩn hóa. Cấu trúc quan trọng nhất là: subject + predicate + object + modality + temporal + assertion Ví dụ: subjec...
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `qualifier_dict(self)`
    - `with_confidence(self, confidence)` — Trả bản sao với confidence mới. Dataclass frozen nên không mutate trực tiếp. Ký ức mà tự sửa mình âm...
  - `ExtractedClaim` (decorator=dataclass(frozen=True, slots=True)) — Kết quả extractor trả ra trước khi commit. `commit_hint` chỉ là gợi ý. Worthiness/Retention policy mới là nơi quyết định thật.
    - `to_dict(self)`

## `memory/semantic_memory.py`
- LOC: 1846
- Docstring: Semantic Memory: bộ nhớ fact đã được chưng cất cho ERIS. File này cố tình KHÔNG làm event log. Semantic memory chỉ nên giữ những thứ đã đủ ổn định để ERIS có thể nhớ gọn: - fact về user, ERIS, project, thế giới, kỹ thuật - sở thích / thói quen / quy ước làm vi...
- Functions:
  - `iso_now()` — Thời gian dạng ISO đơn giản, đủ ổn cho JSON memory local.
  - `_safe_epoch_from_iso(value)` — Parse timestamp best-effort. Không dùng để làm logic chính xác tuyệt đối. Chỉ dùng cho recency bonus/sort. Nếu parse fai...
  - `compact_text(value)` — Nén text thành một dòng ngắn để lưu vào memory. Semantic memory không nên chứa đoạn văn dài. Nếu cần lưu raw dài, đưa sa...
  - `clamp01(value, default)` — Ép giá trị về khoảng 0..1, tránh NaN/inf làm bẩn score.
  - `atomic_write_json(path, payload)` — Ghi JSON an toàn hơn kiểu mở file rồi cầu nguyện. Ghi ra file tạm rồi os.replace để giảm rủi ro hỏng memory nếu runtime...
  - `strip_accents(text)` — Bỏ dấu tiếng Việt để so khớp alias/fact_key ổn hơn. Lưu ý: không dùng bản bỏ dấu làm claim public. Chỉ dùng cho indexing...
  - `normalize_text(text)` — Normalize text cho search/fingerprint. - lowercase - bỏ dấu tiếng Việt - bỏ punctuation thừa - co whitespace Đây là lexi...
  - `dedupe_key(text)` — Key tương thích bản cũ. Không còn là cơ chế dedupe chính, nhưng vẫn giữ để code khác đang gọi không vỡ.
  - `token_set(text)`
  - `char_ngrams(text, n)`
  - `word_ngrams(text, n)`
  - `jaccard(a, b)`
  - `sequence_ratio(a, b)`
  - `stable_hash(text)` — Hash ngắn để biết embedding_text đã đổi chưa.
  - `unique_keep_order(items)`
  - `_mapping(value)`
  - `_matches_any(normalized, patterns)`
- Classes:
  - `SemanticRecallCue` (decorator=dataclass(slots=True)) — Cue truy xuất semantic memory. Thay vì lấy query rồi đếm token overlap, ta tách query thành vài tín hiệu: - domain muốn tìm: user/self/proje...
    - `tokens(self)`
    - `embedding_query(self)` — Query đưa cho embedding index. Nếu có fact_key/domain thì thêm vào để vector search bớt mù ngữ cảnh.
  - `SemanticRecallHit` (decorator=dataclass(slots=True)) — Kết quả recall có score và lý do. recall() vẫn trả list item để tương thích cũ. Nếu cần debug, gọi recall_hits() để thấy vì sao item được ké...
    - `to_dict(self)`
    - `recall_line(self)`
  - `FactProfile` (decorator=dataclass(slots=True)) — Thông tin derive từ claim/request trước khi lưu. fact_key là điểm quan trọng nhất. Nó biến các câu paraphrase thành cùng một fact. Ví dụ: "N...
  - `SemanticMemoryItem` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `fact_key(self)`
    - `aliases(self)`
    - `importance(self)`
    - `access_count(self)`
    - `last_accessed_at(self)`
    - `raw_user_text(self)`
    - `semantic_value(self)`
    - `recall_text_parts(self)`
    - `recall_line(self)`
  - `SemanticMemoryStore` — Store semantic fact dạng JSON, có typed recall và optional embedding hook. Đây là WARM/HOT fact store: - load nhanh - claim ngắn - metadata...
    - `__init__(self, path)`
    - `load(self)`
    - `save(self, items)` — Lưu memory sau khi prune/sort. Sort policy ưu tiên: 1. active > tentative > contradicted/rejected/ar...
    - `_prune_items(self, items)` — Prune memory yếu nếu vượt max_items. Không xóa dựa vào thời gian đơn thuần. Memory quan trọng/có key...
    - `_sorted_items(self, items)`
    - `_retention_score(self, item)`
    - `apply_commit(self, request)` — Áp một StateCommitRequest vào semantic memory. Commit không merge bằng exact text nữa. Flow mới: req...
    - `_find_merge_target(self, items)` — Tìm item nên merge. Thứ tự: 1. fact_key trùng và domain tương thích 2. exact normalized key trùng 3....
    - `_merge_item(self, item)` — Merge claim mới vào item cũ. Nếu cùng fact_key nhưng giá trị có vẻ mâu thuẫn, không overwrite sạch....
    - `_is_current_fact_replacement(self, fact_key)`
    - `_claim_surface_quality(self, claim)` — Ước lượng claim nào đáng dùng làm surface chính. Claim quá ngắn/quá chung chung không nên overwrite...
    - `_detect_value_conflict(self, item)` — Bắt mâu thuẫn rõ cho vài fact_key có value đơn giản. Không cố làm natural language contradiction det...
    - `_extract_metadata_value(self, metadata, fact_key)`
    - `_extract_simple_value(self, claim, fact_key)`
    - `lookup_fact(self, fact_key)` — Return the current value for a stable fact_key. This is intentionally stricter than generic recall:...
    - `get_fact(self, fact_key)`
    - `semantic_lookup(self, fact_key)`
    - `_current_fact_rank(self, item)`
    - `recall(self, query)` — Recall tương thích API cũ: trả list item. Nếu cần debug score, dùng recall_hits().
    - `recall_hits(self, query)` — Recall có debug score. Flow: 1. parse SemanticRecallCue 2. nếu query rỗng: trả item hot theo retenti...
    - `_embedding_candidates(self, cue, items)` — Lấy candidate từ embedding index nếu có. Contract cố ý duck-typing để không khóa store vào một thư v...
    - `_score_recall_item(self, item, cue)`
    - `_normalize_vector_score(self, value)` — Normalize score vector về 0..1. Nhiều backend trả cosine [-1, 1], vài backend trả similarity [0, 1]....
    - `_fact_key_score(self, item, cue)`
    - `_domain_score(self, item, cue)`
    - `_alias_score(self, item, cue)`
    - `_lexical_similarity(self, item, cue)`
    - `_recency_bonus(self, item)`
    - `_record_access(self, item_ids)` — Cập nhật access_count/last_accessed_at cho item được recall. Việc này giúp HOT facts nổi lên nhanh h...
    - `parse_recall_cue(self, query)`
    - `_derive_fact_profile(self, claim)` — Derive domain/fact_key/importance từ claim + request context. Ưu tiên metadata/reason từ MemoryCommi...
    - `_domain_from_fact_key(self, fact_key)`
    - `_infer_domain(self, claim, target)` — Infer domain nhẹ từ claim/target. Đây là fallback. Nếu MemoryCommitPolicy gửi metadata/fact_key thì...
    - `_build_metadata(self)`
    - `embedding_text_for_item(self, item)` — Text đưa vào embedding index. Không embed claim trần. Claim ngắn như "Gtvkun" sẽ rất nghèo ngữ cảnh....
    - `_embedding_text_from_parts(self)`
    - `_claim_similarity(self, a, b)`
    - `rebuild_embedding_index(self)` — Yêu cầu embedding_index build/cache lại vector nếu backend hỗ trợ. Không bắt buộc dùng. Dành cho com...

## `memory/semantic_text.py`
- LOC: 197
- Functions:
  - `normalize_vi(text)` — Chuẩn hóa tiếng Việt về dạng không dấu, chữ thường, khoảng trắng gọn.
  - `clean_surface_text(value)` — Dọn object surface nhưng không tự canonicalize quá tay.
  - `analyse_text(text)`
  - `split_clauses(norm_text)`
  - `looks_like_question(raw, norm)`
  - `looks_like_greeting_only(norm)`
  - `has_any(norm)` — Phrase containment có boundary nhẹ. Đây vẫn là lexical, nhưng nằm ở tầng cảm biến chung. File nghiệp vụ không nên tự bắn...
  - `relation_regex(aliases)` — Build regex cho relation aliases đã normalize. Alias được escape và sort dài trước để tránh `sinh` ăn mất `sinh thang`.
  - `_has_interrogative_context(norm)`
  - `_surface_evidence(norm)`
- Classes:
  - `TextSemanticFrame` (decorator=dataclass(frozen=True, slots=True)) — Bản đọc bề mặt của một câu user. Đây chỉ là context hỗ trợ. Đừng nhét nguyên frame này vào memory rồi gọi nó là semantic. Làm vậy thì lại qu...

## `memory/text_normalize_vi.py`
- LOC: 65
- Functions:
  - `strip_accents(text)` — Bỏ dấu tiếng Việt để match mềm, không phá text gốc dùng để trả lời.
  - `normalize_vi(text)` — Chuẩn hóa nhẹ cho phân loại intent/fact.
  - `compact_spaces(text)` — Giữ dấu nhưng dọn khoảng trắng.
  - `looks_like_question(text)` — Nhận diện câu hỏi theo nghĩa hội thoại Việt. Không cần hoàn hảo. Phần này chỉ phục vụ ledger đếm deterministic, không nê...
  - `visible_len(text)` — Độ dài phục vụ so sánh câu dài nhất, sau khi nén khoảng trắng.

## `memory/understanding/__init__.py`
- LOC: 16
- Docstring: Tầng đọc nghĩa trung gian cho memory intake.

## `memory/understanding/entity_linker.py`
- LOC: 114
- Functions:
  - `link_entity(value)` — Link object surface thành EntityRef. `hinted_kind` đến từ model parser hoặc frame relation. Nếu hint rõ, linker chỉ vali...
  - `clean_surface(value)`
  - `normalize(text)`
  - `strip_accents(text)`
  - `_looks_like_location(norm)`
  - `_looks_like_person_name(text)`

## `memory/understanding/meaning_frame.py`
- LOC: 192
- Functions:
  - `_coerce(value, allowed, default)`
  - `_clamp01(value)`
- Classes:
  - `EntityRef` (decorator=dataclass(frozen=True, slots=True)) — Entity đã link nhẹ từ surface text. `kind` là nhãn loại entity: location/person_name/style_rule/topic/... `canonical` là dạng ổn định để mer...
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `MeaningFrame` (decorator=dataclass(frozen=True, slots=True)) — Khung nghĩa đã đọc từ một phát ngôn. Field quan trọng: - frame_type: loại hành vi/nghĩa ở mức cao. - relation: quan hệ ngữ nghĩa, chưa phải...
    - `is_assertive(self)`
    - `to_dict(self)`
    - `from_dict(cls, data)`
  - `MeaningParseResult` (decorator=dataclass(frozen=True, slots=True)) — Output của SemanticParser. Parser có thể là model.gguf, parser rule-based, hoặc hybrid. Nhưng dù đến từ đâu, downstream chỉ nhận dạng này. M...
    - `to_dict(self)`

## `memory/understanding/polarity_temporal.py`
- LOC: 107
- Functions:
  - `analyse_surface(text)`
  - `_has_any(norm, phrases)`
  - `split_clauses(text)` — Tách clause thô để parser xử lý từng mệnh đề nhỏ. Dùng cho fallback thôi. Model parser nên tự trả frame có evidence_span...
- Classes:
  - `SurfaceFeatures` (decorator=dataclass(frozen=True, slots=True))

## `memory/understanding/semantic_parser.py`
- LOC: 597
- Functions:
  - `structured_frames_to_result(text, payload)` — Verify structured JSON thành MeaningFrame. Hỗ trợ cả {"frames": [...]} lẫn list trực tiếp. Những frame thiếu target vẫn...
  - `_frame_from_mapping(item)`
  - `_claim_like_to_frame(item)`
  - `_parse_clause_as_frames(clause, surface)` — Fallback detector tập trung. Đây là phần còn lexical, nhưng chỉ làm fallback và chỉ sinh MeaningFrame. Nếu Ngài nối mode...
  - `_mk_frame(frame_type, relation, value, kind, evidence, certainty, time_scope, modality, surface)`
  - `_extract_after(norm, raw, cues)`
  - `_extract_identity_name(raw)` — Bắt các câu khai báo/correction tên ở tầng MeaningFrame. Dùng `_extract_after()` để match trên bản normalize không dấu n...
  - `_extract_identity_nickname(raw)` — Bắt câu khai báo biệt danh/nickname ở tầng MeaningFrame. Tách hẳn khỏi `_extract_identity_name`: tên thật và biệt danh l...
  - `_extract_study_field(raw)` — Rút ngành/lĩnh vực học từ self-disclosure ngắn. Đây là fact profile hiện tại, không phải world/current-info. Vì vậy nó n...
  - `_extract_year(norm)`
  - `_extract_preference(norm, raw)`
  - `_extract_after(raw, cues)`
  - `_extract_preference(norm, raw)`
  - `_normalized_with_offsets(text)`
  - `_has_self(norm)`
  - `_looks_like_style_instruction(norm)`
  - `_looks_like_feedback(norm)`
  - `_infer_frame_type(relation)`
  - `_clamp01(value)`
- Classes:
  - `SemanticParser` (base=Protocol) — Protocol chung để runtime có thể thay fallback bằng model.gguf.
    - `parse(self, text)`
  - `ModelSemanticParser` (decorator=dataclass(slots=True)) — Adapter cho model/LLM parser bên ngoài. `parse_callable` là hàm của Ngài. Nó nhận text và trả dict/list đã parse. File này không biết llama....
    - `parse(self, text)`
  - `StructuredFrameParser` (decorator=dataclass(slots=True)) — Parser chỉ verify JSON structured đã có sẵn.
    - `parse(self, text)`
  - `FallbackSurfaceSemanticParser` (decorator=dataclass(slots=True)) — Fallback rất nhỏ khi chưa có model.gguf. Nó không cố hiểu sâu. Nó chỉ nhận ra vài frame rất phổ thông bằng các detector tập trung. Quan trọn...
    - `parse(self, text)`

## `memory/unresolved_memory.py`
- LOC: 331
- Functions:
  - `iso_now()`
  - `compact_text(value)`
  - `clamp01(value, default)`
  - `atomic_write_json(path, payload)`
  - `fingerprint_text(text)`
  - `_as_list(value)`
  - `_mapping(value)`
- Classes:
  - `UnresolvedMemoryCandidate` (decorator=dataclass(slots=True))
    - `to_dict(self)`
    - `from_dict(cls, data)`
    - `fingerprint(self)`
    - `recall_line(self)`
  - `UnresolvedMemoryStore` — JSON store cho unresolved memory candidates.
    - `__init__(self, path)`
    - `load(self)`
    - `save(self, items)`
    - `apply_commit(self, request)`
    - `candidates_for_consolidation(self)`
    - `mark_attempted(self, candidate_id)`
    - `mark_promoted(self, candidate_id)`
    - `search(self, query)`
    - `_find_existing(self, items, candidate)`
    - `_merge(self, old, new)`
    - `_prune(self, items)`
    - `_sort_items(self, items)`

## `parser_grounding/__init__.py`
- LOC: 5

## `parser_grounding/decision.py`
- LOC: 1853
- Classes:
  - `ParserGroundingMixin`
    - `_normalize_keyword_text(self, text)`
    - `_contains_keyword(self, text, keyword)`
    - `_contains_any_keyword(self, text, keywords)`
    - `_is_embodied_command_request(self, text)`
    - `_should_infer_embodied_animation(self, text, user_hint)`
    - `_preview_raw_response(self, raw_text)`
    - `_normalize_debug_trace(self, value)`
    - `_build_parser_debug_trace(self)`
    - `_collect_capability_violations(self, text)`
    - `_infer_animation_reason(self, final_animation, text, user_hint)`
    - `_build_parser_trace_summary(self)`
    - `_log(self, level, message)`
    - `_extract_first_json_object(self, text)`
    - `_extract_first_json_candidate(self, text)`
    - `_repair_json_candidate(self, text)`
    - `_patch_missing_decision_fields(self, payload)`
    - `_finalize_loaded_json_payload(self, payload)`
    - `_try_parse_hard_json_repair(self, text, user_hint)`
    - `_normalize_salvaged_text(self, text)`
    - `_repair_sentence_boundaries(self, text)`
    - `_normalize_decision_field_keys(self, value)`
    - `_coerce_bool(self, value)`
    - `_coerce_confidence(self, value)`
    - `_coerce_reasoning_tags(self, value)`
    - `_action_field(self, action)`
    - `_apply_cognition_action_defaults(self, data, user_hint)`
    - `_clean_inline_field_value(self, value)`
    - `_cut_inline_metadata_from_public_text(self, text)` — Remove leaked decision-schema tail from a public text field.
    - `_looks_like_prompt_or_contract_leak_text(self, text)`
    - `_looks_like_non_json_analysis_or_debug_text(self, text)`
    - `_non_json_semantic_fallback_payload(self)`
    - `_try_extract_inline_decision_fields_from_text(self, text)`
    - `_sanitize_direction(self, value)`
    - `_sanitize_target_x(self, value)`
    - `_sanitize_motion_facing(self, value)`
    - `_try_extract_nested_decision_from_text(self, text)`
    - `_unwrap_structured_text_candidate(self, text)`
    - `_clean_nested_field_scalar(self, value)`
    - `_clean_nested_field_text(self, value)`
    - `_sanitize_motion_intent(self, value)`
    - `_infer_motion_intent(self)`
    - `_sanitize_animation(self, value, fallback_text, user_hint)`
    - `_sanitize_system_action(self, value)`
    - `_is_strict_direction_value(self, value)`
    - `_is_strict_target_x_value(self, value)`
    - `_requires_lax_json_mode(self, payload)`
    - `_get_runtime_capability_summary(self)`
    - `_split_into_claim_units(self, text)`
    - `_is_allowed_self_claim(self, clause)`
    - `_has_vision_frame_context(self, text)`
    - `_is_screen_observation_claim(self, clause, context)`
    - `_clause_mentions_unsupported_target(self, clause)`
    - `_clause_has_strong_control_fantasy(self, clause)`
    - `_clause_exceeds_runtime_capability(self, clause, previous_unit, context)`
    - `_rewrite_excessive_clause(self, clause, user_hint)`
    - `_ground_text_to_runtime_capabilities(self, text, user_hint)`
    - `_has_contradictory_encouragement(self, text)`
    - `_has_philosophical_filler(self, text)`
    - `_has_overmanaged_style(self, text)`
    - `_build_grounded_text(self, user_hint)`
    - `_is_speculative_extracted_fact(self, fact)`
    - `_finalize_decision(self, decision, user_hint)`
    - `_infer_structured_action(self, text, user_hint)`
    - `_salvage_non_json_response(self, cleaned, user_hint)`
    - `_extract_lax_field(self, text, field, known_fields)`
    - `_try_parse_lax_json(self, text, user_hint)`
    - `_infer_animation_reason(self, final_animation, text, user_hint)`
    - `_infer_animation_from_text(self, text)`
    - `_infer_structured_action(self, text, user_hint)`
    - `parse_ai_json(self, raw_text, user_hint)`
    - `_is_follow_up_question(self, user_message)`
    - `_build_chat_user_message(self, user_message)`

## `parser_grounding/service.py`
- LOC: 267
- Classes:
  - `DecisionParser` (base=ParserGroundingMixin)
    - `__init__(self, fallback, logger)`
    - `_is_climb_request(self, text)`
    - `_infer_look_direction(self, text)`
    - `_is_look_only_request(self, text)`
    - `_infer_move_direction(self, text)`
    - `_is_drop_from_climb_request(self, text)`
    - `_is_reverse_climb_request(self, text)`
    - `_is_climb_top_request(self, text)`
    - `_is_top_hold_request(self, text)`
    - `_infer_top_platform_target(self, text)`
    - `_infer_air_swing_from_text(self, text)`
    - `_infer_animation_from_text(self, text)`
    - `_infer_structured_action(self, text, user_hint)`
    - `_is_embodied_command_request(self, text)`
    - `_should_suppress_salvaged_text(self, finalized, user_hint)`
    - `_finalize_decision(self, decision, user_hint)`
    - `parse(self, raw_text, user_hint)`
    - `build_chat_user_message(self)`

## `runtime/__init__.py`
- LOC: 24
- Docstring: Runtime package của ERIS. Không import RuntimeCoordinator eager ở đây. Lý do rất đời thường: nhiều test chỉ cần `runtime.state_committer`, nhưng import package `runtime` lại kéo theo coordinator, cortex, guard_config, LLM... rồi nổ vì thiếu dependency. Một `__...
- Functions:
  - `__getattr__(name)`

## `runtime/affect_self_read.py`
- LOC: 297
- Docstring: affect_self_read.py — ERIS tự đọc cảm xúc của chính mình (interoception). Vấn đề: internal_state đưa vào prompt dưới dạng SỐ + jargon ("valence=0.02, attachment=0.30, process_axes=...") và bị gắn nhãn "not a claim about real emotion". Model nhỏ coi đó là telem...
- Functions:
  - `_clamp(value, lo, hi)`
  - `_g(obj, name, default)`
  - `_env_flag(name, default)`
  - `_env_int(name, default)`
  - `_env_float_ms(name, default_seconds)`
  - `_env_float(name, default)`
- Classes:
  - `AffectSelfReadConfig` (decorator=dataclass(slots=True, frozen=True))
    - `from_env(cls)`
  - `AffectSelfReadAdapter` (decorator=dataclass(slots=True)) — Dịch internal_state → 1 câu cảm giác ngôi-thứ-nhất qua gemma (style_client).
    - `render(self, state)` — Trả về 1 câu cảm giác (đã cache/throttle), hoặc "" nếu tắt/không có state.
    - `_bucket(value)`
    - `_signature(self, state, rel)`
    - `_gemma_line(self, state, rel)`
    - `_readings_text(self, state, rel)`
    - `_fallback_line(self, state, rel)`
    - `_extract(self, resp)`
    - `_first_line(raw)`
    - `_clean(text)`
    - `_warn(self, fmt)`

## `runtime/ambient_silence_policy.py`
- LOC: 75
- Docstring: Shared ambient-silence / muse policy for the autonomous idle loop. ``coordinator.py`` and ``autonomous_cycle.py`` historically duplicated this logic; both now delegate here so the two drivers cannot drift. The key change for the liveliness redesign: a ``patter...
- Functions:
  - `muse_directive_active(ti_report)` — True when cognition granted self-initiated topic permission.
  - `ambient_silence_cooldown_seconds(snapshot, ti_report)` — Cooldown window (seconds) for ambient-silence pacing by mode/focus.
  - `should_hold_ambient_silence()` — Decide whether to hold this cycle for ambient pacing. Returns ``(held, reason)``. ``reason`` is structured for the Decis...

## `runtime/autonomous_cycle.py`
- LOC: 1241
- Classes:
  - `AutonomousCycleMixin`
    - `_choose_autonomous_sleep_duration(self)`
    - `_process_pending_user_input(self)`
    - `_run_loop_iteration(self)` — Run a single coordinator loop iteration. Returns True to keep looping, False to break the run_loop.
    - `_load_autonomous_sleep_seconds(self, env_name)`
    - `_bucket_idle_seconds(self, idle_seconds)`
    - `_bucket_window_spread(self, open_windows, browser_tabs)`
    - `_load_vision_fact_settings(self)`
    - `_note_vision_failure(self, stage, exc)`
    - `_is_low_value_screen_fact(self, fact)`
    - `_speech_evidence_score(self, text)`
    - `_is_speakable_evidence(self, text)`
    - `_sanitize_screen_facts(self, facts)`
    - `_maybe_update_screen_facts(self)`
    - `_attach_screen_facts(self, snapshot, facts)`
    - `_build_autonomous_signature(self, snapshot, ti_report)`
    - `_track_autonomous_signature(self, snapshot, ti_report)`
    - `_should_suppress_autonomous_reply(self)`
    - `_has_resource_pressure_signal(self, snapshot)`
    - `_is_generic_screen_event(self, event)`
    - `_is_generic_screen_evidence(self, evidence)`
    - `_concrete_screen_signals(self, snapshot)`
    - `_concrete_vision_signals(self, snapshot)`
    - `_concrete_telemetry_signals(self, snapshot)`
    - `_has_concrete_screen_signal(self, snapshot)`
    - `_broadcast_screen_winners(self, broadcast)`
    - `_choose_autonomous_speech_intent(self)`
    - `_ambient_silence_cooldown_seconds(self, snapshot, ti_report)`
    - `_should_hold_ambient_silence(self)`
    - `_should_skip_weak_autonomous_speech(self)`
    - `_has_high_cognitive_momentum(self, thought_stream_report)`

## `runtime/autonomous_wake_governor.py`
- LOC: 262
- Docstring: src/runtime/autonomous_wake_governor.py ======================================= Wake Governor - trọng tài quyết định mức độ thức của ERIS. Kết quả KHÔNG phải nói/không nói. Kết quả là mức thức: - sleep - observe_only - think_only - micro_presence - call_vision...
- Functions:
  - `_clamp01(value, default)`
- Classes:
  - `WakeDecision` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `WakeGovernorConfig` (decorator=dataclass(slots=True))
  - `AutonomousWakeGovernor` — Trọng tài wake state.
    - `__init__(self, config)`
    - `decide(self)`
    - `_budget(self, policy, tier, snapshot, reason)`

## `runtime/background_memory_digest.py`
- LOC: 60
- Functions:
  - `build_background_memory_digest_service()` — Compat builder: ưu tiên MemoryKernel, bỏ qua hook commit cũ.

## `runtime/background_memory_digest_kernel.py`
- LOC: 466
- Functions:
  - `_env_flag(name, default)`
  - `_env_int(name, default)`
  - `_env_float(name, default)`
- Classes:
  - `BackgroundMemoryDigestKernelConfig` (decorator=dataclass(frozen=True, slots=True)) — Config worker nền. enabled=True chỉ có nghĩa là worker được phép chạy. Builder vẫn nên kiểm tra có MemoryKernel và parser/model thật trước k...
  - `MemoryDigestKernelJob` (decorator=dataclass(frozen=True, slots=True)) — Một job tiêu hóa memory nền. Worker không surface job ra user. Job chỉ là nguyên liệu cho MemoryKernel.ingest().
  - `MemoryDigestKernelStats` (decorator=dataclass(slots=True)) — Stats nhỏ cho dev/debug.
    - `to_dict(self)`
  - `BackgroundMemoryDigestKernelService` — Thread worker nền cho MemoryKernel semantic digestion.
    - `__init__(self, memory_kernel)`
    - `start(self)` — Start worker nếu chưa chạy.
    - `stop(self, timeout)` — Stop worker nhẹ nhàng.
    - `mark_remote_inflight(self, value)` — Runtime gọi True trước remote API, False sau khi nhận response.
    - `notify_remote_inflight(self, inflight)` — Compat với service cũ.
    - `notify_user_input(self)` — Báo worker biết user vừa nhập, để tránh tranh tài nguyên ngay lập tức.
    - `enqueue(self, text)` — Đưa job vào queue. Trả False nếu queue đầy hoặc text rỗng.
    - `enqueue_user_turn(self, text)` — Compat với worker cũ: enqueue job user-turn và ghi nhận input mới.
    - `drain_once_for_tests(self)` — Chạy đồng bộ queue để test không cần thread nền.
    - `_run(self)`
    - `_gate_job(self, job)`
    - `_runtime_idle_enough(self, now)`
    - `_requeue(self, job)`
    - `_defer_job(self, job)`
    - `_process(self, job)`
    - `_maybe_run_idle_maintenance(self)`
    - `_log(self, level, message)`

## `runtime/body_bias.py`
- LOC: 116
- Classes:
  - `BodyBiasProjector` — Projects cognitive state into the compact body-bias payload Godot consumes.
    - `__init__(self, state_provider)`
    - `build_payload(self, observer_frame, impulse_hint)` — Build compact body-bias payload. `impulse_hint` là phần nối sâu từ ArbitrationReport xuống body. Nó...
    - `clamp(value)`
    - `normalize_focus_kind(value)`

## `runtime/chat_cycle.py`
- LOC: 1636
- Classes:
  - `ChatCycleMixin`
    - `_enter_chat_cycle(self)`
    - `_end_chat_cycle(self)`
    - `_build_relational_voice_stance(self, user_text)` — Project the already-computed cognition reports into a CognitionStance. Register is derived only from...
    - `_build_relational_voice_seed_decision(self, user_text)`
    - `_run_chat_cycle(self, user_text)`
    - `_run_chat_cycle_inner(self, user_text)`
    - `_recall_repair_suppression(self, user_text)` — Recall ký ức sửa lỗi quan hệ/tâm lý và rút ra tín hiệu siết cho lượt này. Đây là cạnh recall đóng vò...
    - `_build_chat_format_block_raw(self, exc)` — Block payload when every provider (gemma retries + Groq switch-API) breaks the format contract. We r...
    - `_build_chat_format_repair_fallback_raw(self, exc)`
    - `_join_debug_trace()`
    - `_queue_chat_burst_event(self, user_text, timestamp)`
    - `_merge_rapid_chat_burst(self, first_text)`
    - `_pop_queued_chat_events(self)`
    - `_poll_ready_chat_events(self)`
    - `_observe_previous_turn_feedback(self, user_text)` — Gắn feedback của user hiện tại vào frame trước nếu có. OutcomeObserver trong PDF nằm sau Execution,...
    - `_normalize_user_message(self, user_text)`
    - `_normalize_marker_text(self, user_text)` — Normalize để detect lệnh nhìn màn hình, KHÔNG strip hậu tố "đi". `_normalize_user_message()` dùng ch...
    - `_looks_like_screen_vision_request(self, user_text)`
    - `_capture_screen_frame_for_chat(self, user_text)`
    - `_chat_source_grounding_screen_facts(self, snapshot)`
    - `_build_chat_source_grounding_report(self)`
    - `_log_chat_source_grounding(self, report)`
    - `_normalize_public_reaction_text(self, text)`
    - `_previous_public_turn_has_protocol_leak(self, public_turn)`
    - `_user_is_challenging_previous_public_turn(self, user_text)`
    - `_build_previous_public_turn_repair_decision(self)`
    - `_build_grounding_preempt_decision(self, report, ti_report)`
    - `_generate_grounding_preempt_text(self, report)`
    - `_local_grounding_preempt_text(self, report)`
    - `_build_user_message_signature(self, user_text)`
    - `_track_repeated_user_message(self, user_text)`
    - `_get_turn_semantics_engine(self)`
    - `_build_turn_semantics_report(self)`
    - `_build_repeat_guard_decision(self, user_text, ti_report, repeat_count)`
    - `_should_bypass_repeat_guard_for_live_observation(self, user_text)`

## `runtime/cognitive_budget.py`
- LOC: 2706
- Docstring: src/runtime/cognitive_budget.py ================================ Bộ chọn Cognitive Budget cho ERIS. Mục tiêu: Chọn đường chạy nhận thức cho mỗi CognitiveFrame: - fast - normal - deep - reflection Vì sao cần file này: Attention biết cái gì nổi bật. WorkingMemor...
- Functions:
  - `now_ts()`
  - `clamp01(value, default)` — Ép giá trị về khoảng 0..1. Đây là runtime, không phải phòng thí nghiệm lý tưởng. Field từ các module khác đôi khi là Non...
  - `clamp(value, minimum, maximum, default)`
  - `safe_get(obj, name, default)` — Lấy attribute/key theo kiểu duck-typing. Cho phép đọc cả dataclass, object thường và dict. Nếu module upstream đổi từ da...
  - `safe_get_path(obj, path, default)`
  - `as_list(value)`
  - `text_of(value)` — Chuyển object bất kỳ thành text ngắn để phân tích signal. Không dùng để prompt trực tiếp. Chỉ dùng nội bộ để score keywo...
  - `lower_text(value)`
  - `_keyword_pattern(word)` — Tạo pattern match keyword ít ngu hơn substring thuần. - Cụm có khoảng trắng vẫn match như phrase. - Từ ASCII một mảnh dù...
  - `contains_any(text, words)`
  - `count_any(text, words)`
  - `keyword_hits(text, words)`
  - `weighted_keyword_score(text, groups, weights)` — Tính score keyword fallback. Bản cũ để keyword đi quá thẳng vào pressure rồi hard-floor lên deep. Bản này vẫn trả score...
  - `blend_semantic_and_keyword()` — Ghép semantic pressure với keyword fallback. Trả về `(pressure, keyword_only)`. `keyword_only=True` nghĩa là pressure ch...
  - `unique_preserve_order(items)`
  - `object_to_dict(obj)`
  - `choose_cognitive_budget(frame)` — Hàm tiện ích nếu không muốn tự giữ engine instance.
- Classes:
  - `BudgetModeProfile` (decorator=dataclass(slots=True)) — Thông số tài nguyên cho một budget mode. Đây là thứ downstream nên đọc thay vì tự đoán: - WorkingMemory nên giữ bao nhiêu slot? - Workspace...
    - `to_dict(self)`
  - `BudgetSignalSnapshot` (decorator=dataclass(slots=True)) — Ảnh chụp các áp lực dùng để chọn budget. Mỗi field là pressure 0..1. Cái này không phải cảm xúc, không phải phán xét, không phải thần dụ. Nó...
    - `pressure_max(self)`
    - `task_pressure(self)`
    - `reflection_pressure(self)`
    - `to_dict(self)`
  - `BudgetScoreBreakdown` (decorator=dataclass(slots=True)) — Điểm cạnh tranh giữa các mode. Chọn budget không nên là if-else mù. Breakdown giúp debug vì sao một frame bị nâng từ normal lên deep hoặc hạ...
    - `as_ranked(self)`
    - `to_dict(self)`
  - `PipelineStepDecision` (decorator=dataclass(slots=True)) — Quyết định chạy/bỏ qua một bước pipeline.
    - `to_dict(self)`
  - `BudgetPlan` (decorator=dataclass(slots=True)) — Kế hoạch chạy pipeline dựa trên budget. Đây là phần quan trọng hơn cả label mode. Label `deep` mà không nói module nào được chạy thì vẫn chỉ...
    - `should_run(self, step_name)`
    - `step(self, step_name)`
    - `to_dict(self)`
  - `BudgetDecision` (decorator=dataclass(slots=True)) — Kết quả cuối của CognitiveBudgetEngine.
    - `to_dict(self)`
    - `to_json(self)`
    - `render_debug_summary(self)`
  - `CognitiveBudgetConfig` (decorator=dataclass(slots=True)) — Cấu hình của CognitiveBudgetEngine. Giữ trong dataclass để sau này Ngài có thể load từ JSON/YAML. Xin đừng rải magic number khắp coordinator...
    - `profiles(self)`
  - `CognitiveBudgetEngine` — Chọn cognitive budget cho một frame. Đầu vào chính là CognitiveFrame. Engine đọc bằng duck-typing: frame.evidence frame.salience frame.worki...
    - `__init__(self, config)`
    - `choose(self, frame)` — Chọn budget mode cho frame. Tham số: frame: CognitiveFrame hoặc object có field tương tự. channel: c...
    - `choose_mode(self, frame)` — Shortcut khi runtime cũ chỉ cần string budget_mode.
    - `build_plan(self, mode, frame)` — Build plan trực tiếp từ mode. Hữu ích cho tests hoặc runtime đã chọn mode từ nơi khác.
    - `_extract_snapshot(self, frame)`
    - `_collect_text_blob(self, frame)`
    - `_extract_user_text_from_signals(self, raw_signals, evidence)`
    - `_estimate_user_directness(self, channel, user_text, evidence, raw_signals, text_blob)`
    - `_estimate_signal_density(self, evidence, raw_signals, salience, working_memory, workspace)`
    - `_estimate_salience_priority(self, salience)`
    - `_estimate_context_pressure(self, working_memory, workspace, salience, evidence)`
    - `_semantic_number(self, obj)` — Đọc nhiều tên field có thể có từ semantic reports. Repo đang tiến hóa nên cùng một ý có thể nằm ở `t...
    - `_evidence_tag_score(self, evidence, tags)`
    - `_source_grounding_score(self, source_grounding, sources)`
    - `_meaning_support(self, meaning, keywords)`
    - `_estimate_risk_pressure(self, text_blob, salience, workspace, permission, tom)`
    - `_estimate_privacy_pressure(self, text_blob, evidence, workspace, permission)`
    - `_estimate_technical_depth(self, text_blob, evidence, meaning)`
    - `_estimate_architecture_depth(self, text_blob, evidence, meaning)`
    - `_estimate_correction_pressure(self, text_blob, evidence, outcome, self_observation)`
    - `_estimate_contradiction_pressure(self, text_blob, evidence, belief, self_observation)`
    - `_estimate_relational_rupture(self, text_blob, relation, outcome, self_observation)`
    - `_estimate_affective_residue(self, text_blob, affect, relation)`
    - `_estimate_homeostasis_load(self, homeostasis, affect)`
    - `_estimate_goal_pressure(self, frame, text_blob)`
    - `_estimate_memory_conflict(self, text_blob, memory_packet, belief, self_observation)`
    - `_estimate_worldview_pressure(self, text_blob, belief)`
    - `_estimate_uncertainty(self, tom, meaning, salience, workspace)`
    - `_estimate_ambiguity(self, meaning, tom, text_blob)`
    - `_estimate_idle_pressure(self, temporal, homeostasis, idle_seconds)`
    - `_estimate_session_closing_pressure(self, text_blob, temporal)`
    - `_estimate_reflection_debt(self, text_blob, outcome, self_observation, relation, affect)`
    - `_estimate_speech_need(self, frame, channel, user_directness, salience_priority, text_blob)`
    - `_estimate_body_need(self, frame, workspace, text_blob)`
    - `_estimate_low_stakes_ambient(self)`
    - `_estimate_high_value_decision(self, text_blob, technical_depth, architecture_depth, semantic_support)`
    - `_score_modes(self, snapshot)`
    - `_choose_mode_from_scores(self, snapshot, scores)`
    - `_apply_hard_floors(self, mode, snapshot)` — Áp sàn mode để tránh fast path xử lý việc nghiêm túc. Sàn này không phải rule-based cứng vô hồn. Nó...
    - `_apply_hard_overrides(self, mode, snapshot)`
    - `_derive_reasons(self, mode, snapshot, scores)`
    - `_estimate_confidence(self, mode, snapshot, scores)`
    - `_estimate_urgency(self, mode, snapshot)`
    - `_build_reason(self, mode, snapshot, escalation, downgrade, scores)`
    - `_build_plan(self, mode, snapshot)`
    - `_build_steps(self, mode, snapshot, profile)` — Tạo danh sách module nên chạy. Bản này có chủ ý hơi dư chi tiết, vì runtime cần nhìn được vì sao một...
    - `_attach_decision(self, frame, decision)`
    - `_add_report_to_frame(self, frame, report)`
    - `_add_reflection_commit_request(self, frame, decision)`
    - `_extract_evidence_ids(self, frame)`
    - `_normalize_channel(self, channel)`
    - `_last_previous_mode(self, previous_decisions)`
    - `_mode_rank(self, mode)`
    - `_max_mode(self, current, floor)`

## `runtime/cognitive_cycle.py`
- LOC: 408
- Classes:
  - `CognitiveCycleMixin`
    - `stop(self)`
    - `_start_mental_process_loop(self)`
    - `_stop_mental_process_loop(self)`
    - `_run_mental_process_loop(self)`
    - `_tick_mental_process_background(self)`
    - `_mix_axis(self, previous, target)`
    - `_load_mental_process_enabled(self)`
    - `_load_mental_process_interval(self)`
    - `_sleep_interruptible(self, seconds)`
    - `run_loop(self)`
    - `_load_ni_meta_mode_flags(self)` — Đọc cấu hình ni_meta_config.json để bật/tắt meta-critic theo mode. Cấu trúc gợi ý: { "enabled": true...
    - `_soften_chat_meta_result(self)`
    - `_soften_autonomous_meta_result(self)`
    - `_maybe_apply_ni_meta_critic(self)` — Áp dụng tầng suy luận nhẹ của Ni dựa trên evidence và tín hiệu snapshot.

## `runtime/cognitive_frame_recorder.py`
- LOC: 1369
- Classes:
  - `CognitiveFrameRecorderMixin` — Ghi nhận frame theo commit protocol. Vai trò đúng của file này: - quan sát outcome cuối turn; - derive các StateCommitRequest từ frame; - ap...
    - `_remember_cognitive_frame(self, frame)` — Tương thích tên hàm cũ, nhưng không ghi memory trực tiếp nữa. Tên `_remember_cognitive_frame` được g...
    - `_is_ephemeral_micro_presence_observation(self, frame, observation)`
    - `_derive_state_commit_requests(self, frame)` — Sinh toàn bộ StateCommitRequest từ frame hiện tại. Đây là lớp chuyển đổi từ outcome/runtime frame sa...
    - `_observe_outcome_for_commit(self, frame)` — Rút outcome cuối turn thành payload sạch để derive request.
    - `_make_commit_request(self)` — Tạo request dạng dict tương thích StateCommitRequest. StateCommitter đã hỗ trợ dict/object/dataclass...
    - `_append_commit_requests(self, frame, requests)` — Append request vào frame mà không phá contract frame cũ/mới.
    - `_refresh_memory_update_from_commit_requests(self, frame, requests)` — Cập nhật summary debug trên frame.memory_update từ request vừa derive. Đây chỉ là metadata trong fra...
    - `_remember_relationship_reflections(self, frame)` — Tên cũ, hành vi mới: derive request, không ghi store trực tiếp.
    - `_derive_relationship_reflections(self, frame)`
    - `_target_for_reflection(self, pattern)` — Map reflection sang memory layer phù hợp.
    - `_extract_relationship_style_reflection(self, user_text)`
    - `_derive_repair_commit_request(self, frame, observation)`
    - `_derive_affective_residue_request(self, frame, observation)`
    - `_derive_active_state_request(self, frame, observation)`
    - `_semantic_fact_grounding_metadata(self, frame)`
    - `_extract_explicit_user_memory_fact(self, user_text)`
    - `_frame_evidence_ids(self, frame)`
    - `_evidence_ids_for_fact(self, frame, fact)`
    - `_frame_storage_permission(self, frame)`
    - `_looks_like_user_correction_text(self, text)`
    - `_commit_internal_state_for_frame(self, frame)` — Tính internal_state_after, rồi tạo active_state request. Hàm cũ ghi state runtime trực tiếp. Bỏ. Sta...
    - `_apply_post_relational_leak_restraint(self, state, text)`
    - `_liveliness_tracker(self)`
    - `_record_liveliness_decision(self, frame, final_text)` — Emit one DecisionRecord per autonomous idle cycle (Req 5.5, 6).
    - `_finalize_cognitive_frame(self, frame)`
    - `_observe_outcome_for_frame(self, frame)`
    - `_feed_private_mind_outcome(self, outcome)`
    - `_reflect_self_observation_for_frame(self, frame)`
    - `_append_self_observation_repair_request(self, frame)`
    - `_get_outcome_observer(self)`
    - `_get_self_observer(self)`
    - `_commit_frame_through_state_committer(self, frame)` — Gọi StateCommitter.commit(frame), không gọi memory core trực tiếp.
    - `_get_state_committer(self)` — Lấy hoặc tạo StateCommitter từ MemoryCognitionCore.
    - `_sync_after_state_commit(self, frame, report)` — Đồng bộ cache đọc sau commit, không ghi memory trực tiếp. `long_term_memory` là cache prompt context...
    - `_safe_state_payload(self, state)`
    - `_repair_strategy_for_failure(self, failure_type, mode)`
    - `_future_suppression_rule_for_failure(self, failure_type, mode)`
    - `_dedupe_frame_commit_requests(self, frame)`
    - `_dedupe_commit_requests(self, requests)`
    - `_existing_commit_request_keys(self, requests)`
    - `_commit_request_field(self, request, field_name, default)`
    - `_commit_request_key(self, request)`
    - `_next_cognitive_cycle_id(self, channel)`
    - `_bounded_float(self, value)`
    - `_event_timestamp(self, snapshot)`
    - `_decision_to_frame_dict(self, decision)`
    - `_set_cognitive_memory_update(self, frame)`
    - `_log_pre_parser(self, channel, raw)`
    - `_log_decision_stage(self, channel, stage, decision)`

## `runtime/cognitive_pipeline.py`
- LOC: 295
- Docstring: runtime/cognitive_pipeline.py Xương sống Phase 1 của ERIS V3. Mục tiêu của file này là biến mớ module rời rạc thành MỘT đường chạy có thật: RawSignal -> EvidenceItem (EvidenceNormalizer) # Phase: contract -> CognitiveFrame (core.cognitive_frame) # Phase: xương...
- Classes:
  - `PipelineResult` (decorator=dataclass(slots=True)) — Kết quả một lần chạy pipeline. Giữ cả frame lẫn vài tham chiếu nhanh để caller/test khỏi phải đào lại frame.
    - `budget_mode(self)`
  - `CognitivePipeline` — Chạy Phase 1 trên CognitiveFrame core. Dùng: pipeline = CognitivePipeline() result = pipeline.run_from_signals( [RawSignal.from_chat("ERIS,...
    - `__init__(self)`
    - `run_from_signals(self, raw_signals)` — Tạo frame từ raw signals rồi chạy toàn bộ Phase 1.
    - `run(self, frame)` — Chạy Phase 1 trên một frame đã có raw_signals.
    - `_set_slot(self, frame, slot_name, value)`
    - `_safe_call(obj, method)`
    - `_salience_confidence(salience)`
    - `_budget_report(decision)`
    - `_infer_user_text(raw_signals)`

## `runtime/contextual_autonomy_loop.py`
- LOC: 236
- Docstring: src/runtime/contextual_autonomy_loop.py ====================================== Adaptive heartbeat cho 3-tier autonomy. Module này gom các mảnh: - UserContextStream (tầng cảm giác / 0.6B + rules) - EndogenousDriveEngine (nhịp nội sinh) - InternalAgendaStack (ag...
- Classes:
  - `ContextualAutonomyLoopConfig` (decorator=dataclass(slots=True))
  - `AutonomyLoopTickResult` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `ContextualAutonomyLoop` — Backbone điều phối 3 tầng, gọi được từ coordinator.
    - `__init__(self)`
    - `tick(self)`
    - `_maybe_run_growth_tick(self)` — Chạy một lượt long-arc growth nếu feature bật. Bọc try/except để loop không bao giờ chết vì tầng phá...
    - `next_sleep_seconds(self, decision)`

## `runtime/controlled_slippage.py`
- LOC: 600
- Functions:
  - `_clamp01(value)`
  - `_normalize(text)`
  - `_has_any(normalized_text, markers)`
  - `_max_mode(left, right)`
  - `_min_mode(left, right)`
  - `derive_repair_suppression(repair_items)` — Pure: gộp các RepairMemoryItem đã recall thành một RepairSuppressionView. `repair_items` là iterable các object/dict có...
  - `_apply_repair_suppression(profile, view, notes)` — Áp RepairSuppressionView lên profile theo nguyên tắc tighten-only. Sàn -> nâng (max), trần -> hạ (min), cap_mode -> chỉ...
  - `user_granted_relational_risk(user_text)`
  - `_selected_spontaneous_impulse(speech_core)`
  - `resolve_controlled_slippage()` — Tính ControlledSlippageProfile từ state hiện có. Hàm này cố tình chịu được thiếu field. Runtime ERIS đang có nhiều contr...
  - `apply_slippage_to_ti_report(ti_report, profile)` — Trả về bản TiPolicyReport đã được điều áp mềm. Chỉ chỉnh prompt/bias. Không đụng hard_rules factual/capability.
  - `apply_slippage_to_personality_lens(lens, profile)` — Nới lens mà không làm mất truth guard. Với technical locked: giảm reasoning suppression, nhưng vẫn giữ psychological bra...
- Classes:
  - `RepairSuppressionView` (decorator=dataclass(slots=True)) — Tín hiệu siết-có-cấu-trúc rút ra từ ký ức sửa lỗi đã recall. Đây là phần "Future suppression" của vòng học: một lỗi quan hệ/tâm lý từng bị u...
    - `to_dict(self)`
  - `ControlledSlippageProfile` (decorator=dataclass(slots=True)) — Hồ sơ quyết định ERIS được "liều" tới đâu ở lượt hiện tại. Các trường truth/capability là xương sống: luôn giữ 1.0 mặc định. Các trường intu...
    - `clamp(self)`
    - `to_dict(self)`
    - `render_prompt_context(self)` — Context đưa vào prompt LLM. Viết rõ ranh giới để model hiểu: được liều về quan hệ, không được bịa ng...

## `runtime/coordinator.py`
- LOC: 7576
- Functions:
  - `_is_nonsemantic_fallback_decision(decision)` — True nếu decision chỉ là fallback kỹ thuật, không phải answer nội dung. Chú thích kiến trúc: public_turn có thể ghi để u...
- Classes:
  - `RuntimeCoordinator` (base=CognitiveCycleMixin, ChatCycleMixin, AutonomousCycleMixin, ForceSpeakCycleMixin, StateCommitServiceMixin, FrameBuilderMixin, SpeechPipelineMixin, PromptContextBuilderMixin, CognitiveFrameRecorderMixin, PresenceControllerMixin, TextRepeatGuardMixin, ForceSpeakSurfacePolicyMixin, PostGenerationFiltersMixin, ShadowPipelineMixin)
    - `_fallback_lines_for_intent(self, intent)`
    - `_force_speak_fallback_by_intent_text(self, intent)`
    - `_public_thought_topic(self, value)`
    - `_looks_internal_topic(self, value)`
    - `_background_memory_digest_idle_probe(self)` — Chỉ cho semantic digest chạy khi runtime thật sự rảnh.
    - `__init__(self)`
    - `_install_model_inference_queue(self)` — Bọc các đường gọi model nặng bằng ModelBudgetPolicy queue. Các mixin gọi trực tiếp `self.llm_service...
    - `_run_background_observer(self)` — Chạy BackgroundObserver trên snapshot hiện tại. Observer chỉ tạo hint/evidence. Nó không nói, không...
    - `_log_observer_trace(self, observer_frame)`
    - `_update_3tier_autonomy_state(self)`
    - `_update_private_mind_state(self)` — Chạy private mind 5 phase trên thread nền — không bao giờ block main loop. PrivateMind gọi Gemini re...
    - `_apply_private_mind_tick_result(self, result)` — Apply kết quả tick PrivateMind sau khi background thread hoàn tất.
    - `_persist_inner_diary(self)` — Ghi inner_diary hiện tại ra đĩa (throttled). Không bao giờ ném lỗi.
    - `_drain_private_mind_surface_impulses(self)` — Lấy impulse đã được SurfaceValve lọc để đưa vào SurfaceArbiter.
    - `_update_private_life_state(self)` — Chạy PrivateLifeCore trên tick nền. PrivateLife không trả Decision. Nó chỉ cập nhật đời sống riêng:...
    - `_drain_private_life_surface_impulses(self)` — Lấy impulse đã lọc từ PrivateLife để đưa vào SurfaceArbiter.
    - `_private_life_digest_for_payload(self)` — Digest gọn cho debug UI/body payload.
    - `_daydream_packets_from_runtime(self)`
    - `_append_daydream_packets_from_memory_snapshot(self, snapshot, add_packet)`
    - `_daydream_kind_from_memory_layer(self, layer)`
    - `_daydream_text_from_memory_record(self, record)`
    - `_build_signal_snapshot_for_observer(self)`
    - `_observer_focus_kind_from_snapshot(self, snapshot)`
    - `_observer_percept_content(self, observer_frame)`
    - `_observer_attention_tags(self, observer_frame)`
    - `_log_raw_llm_output(self, channel, raw)`
    - `_preview_text(self, text)`
    - `_infer_active_conversational_topic(self, user_text)`
    - `_load_memory_state(self)`
    - `_resolve_internal_agenda_path(self)`
    - `_has_structured_memory_store(self)`
    - `_ensure_internal_state(self)`
    - `_get_internal_state(self)`
    - `_set_internal_state(self, state)`
    - `_send_decision_to_body(self, decision)`
    - `_private_mind_digest_for_payload(self)`
    - `_compact_private_mind_digest_for_udp(self, digest)`
    - `_compact_private_mind_debug_value(self, value)`
    - `_compact_private_mind_scalar(value)`
    - `_private_mind_speech_silence_reason(self)`
    - `_record_public_turn(self, decision)`
    - `_infer_public_turn_channel_from_runtime(self, decision)`
    - `_load_rapid_burst_window(self)`
    - `_block_autonomous_presence_after_public_turn(self, now)`
    - `_link_previous_public_turn_for_chat(self, user_timestamp)`
    - `_previous_public_turn_context(self, public_turn)`
    - `_build_body_bias_payload(self)`
    - `_build_emotion_debug_payload(self)` — Compact affect/state payload for the Godot emotion panel.
    - `_body_bias_clamp(value)`
    - `_normalize_body_focus_kind(value)`
    - `_make_cognitive_disturbance(self)`
    - `_looks_like_closure_disturbance(self, content)`
    - `_build_event_disturbances(self)`
    - `_disturb_cognitive_substrate(self)`
    - `_with_thought_stream_surface(self, report, surface)`
    - `_pop_thought_stream_report_for_autonomous(self)`
    - `_pop_subconscious_report_for_autonomous(self)`
    - `_save_memory_state(self)`
    - `_memory_recall_texts(self)`
    - `_activate_memory_resonance(self)`
    - `_thought_stream_resonance_fragments(self)`
    - `_memory_attention_lines(self)`
    - `_norm_deviation_texts(self, snapshot)`
    - `_note_norm_observation(self, snapshot)`
    - `_event_timestamp(self, snapshot)`
    - `_normalize_event_evidence(self, evidence)`
    - `_make_percept_event(self)`
    - `_telemetry_event_privacy_level(self, kind)`
    - `_telemetry_event_novelty_hint(self, kind, content)`
    - `_collect_percept_events(self)`
    - `_collect_cognitive_percepts(self)`
    - `_score_attention_candidate(self, percept)`
    - `_build_attention_candidates(self, percepts)`
    - `_build_broadcast(self, candidates)`
    - `_evidence_from_percepts(self, percepts)`
    - `_salience_candidate_to_runtime(self, candidate)`
    - `_runtime_attention_label(self, candidate, tags)`
    - `_build_meaning_layer(self)`
    - `_build_personality_lens(self)`
    - `_apply_personality_lens_to_fe_plan(self, fe_plan, lens)`
    - `_build_cognitive_appraisal(self)`
    - `_build_appraisal_context(self, appraisal)`
    - `_build_inner_thought(self)`
    - `_build_speech_core(self)`
    - `_remember_inner_thought_rhythm(self, inner_thought)`
    - `_start_cognitive_frame(self)`
    - `_set_cognitive_action_plan(self, frame)`
    - `_apply_micro_line_policy_to_action_plan(self, frame)`
    - `_micro_policy_anchor_hints(self)`
    - `_build_relational_context(self, state)`
    - `_speech_intent_from_core(self, speech_core)`
    - `_merge_speech_core_notes(self, notes, speech_core)`
    - `_merge_meaning_layer_notes(self, notes, meaning_layer)`
    - `_speak_truth_probe_row(self, status)`
    - `_build_speak_truth_table(self)`
    - `_summarize_speak_truth_table(self, table)`
    - `_attach_speak_truth_table(self, frame)`
    - `_merge_memory_resonance_notes(self, notes, memory_resonance)`
    - `_merge_inner_thought_notes(self, notes, inner_thought)`
    - `_merge_personality_lens_notes(self, notes, personality_lens)`
    - `_merge_subconscious_notes(self, notes, subconscious_report)`
    - `_is_inner_thought_speech_act(self, speech_act)`
    - `_restore_session_ritual_once(self)` — Run the startup continuity greeting once per runtime session. This block used to sit after a return...
    - `_apply_force_speak_no_evidence_topic_filter(self, decision)`
    - `_build_planned_withdraw_decision(self, action_plan)`
    - `_log_decision_stage(self, channel, stage, decision)` — Log a compact Decision preview after parser / Ti / repair stages.
    - `stop(self)`
    - `_start_mental_process_loop(self)`
    - `_stop_mental_process_loop(self)`
    - `_run_mental_process_loop(self)`
    - `_tick_mental_process_background(self)`
    - `_build_subconscious_runtime(self)`
    - `_subconscious_frame_payload(self)`
    - `_subconscious_memory_packet(self)`
    - `_subconscious_pressure_metrics(self)`
    - `_subconscious_blackboard_metrics(self)`
    - `_schedule_next_subconscious_due(self, lane, low, high)`
    - `_score_subconscious_surface(self)`
    - `_surface_from_subconscious_thought(self, thought)`
    - `_maybe_tick_subconscious_runtime(self)`
    - `_maybe_tick_subconscious_background(self)`
    - `_mix_axis(self, previous, target)`
    - `_load_mental_process_enabled(self)`
    - `_load_mental_process_interval(self)`
    - `_load_autonomous_sleep_seconds(self, env_name)`
    - `_apply_position_update(self, decision)`
    - `_build_silent_motion_decision(self, ti_report)`
    - `_normalize_user_message(self, user_text)`
    - `_looks_like_screen_vision_request(self, user_text)`
    - `_capture_screen_frame_for_chat(self, user_text)`
    - `_build_user_message_signature(self, user_text)`
    - `_track_repeated_user_message(self, user_text)`
    - `_build_repeat_guard_decision_basic(self, user_text, ti_report, repeat_count)`
    - `_build_repeat_guard_decision(self, user_text, ti_report, repeat_count)`
    - `_handle_incoming(self, msg)`
    - `_handle_debug_command(self, msg)` — Chạy lệnh debug (scenario preset) từ panel DEBUG của Godot. Panel gửi ``{"type":"debug_command","com...
    - `_handle_anchor_control(self, msg)` — Tác_Giả bật/tắt trục tối từ panel Godot (R5.5, R10.4). Gọi thẳng AuthorControl trên anchor_system củ...
    - `_commit_chat_decision(self, decision, fe_plan)`
    - `_sleep_interruptible(self, seconds)`
    - `_bucket_idle_seconds(self, idle_seconds)`
    - `_bucket_window_spread(self, open_windows, browser_tabs)`
    - `_load_vision_fact_settings(self)`
    - `_vision_queue_timeout_seconds(self, channel)`
    - `_vision_failure_backoff_seconds(self, stage, exc)`
    - `_note_vision_failure(self, stage, exc)`
    - `_is_low_value_screen_fact(self, fact)`
    - `_speech_evidence_score(self, text)`
    - `_is_speakable_evidence(self, text)`
    - `_sanitize_screen_facts(self, facts)`
    - `_semantic_scene_note_to_facts(self, note)`
    - `_vision_trace_from_scene_note(self, note)`
    - `_should_use_vision_compressor(self)`
    - `_refresh_screen_facts_from_data_uri(self)`
    - `_maybe_update_screen_facts(self)`
    - `_attach_screen_facts(self, snapshot, facts)`
    - `_build_autonomous_signature(self, snapshot, ti_report)`
    - `_track_autonomous_signature(self, snapshot, ti_report)`
    - `_should_suppress_autonomous_reply(self)`
    - `_has_resource_pressure_signal(self, snapshot)`
    - `_is_generic_screen_event(self, event)`
    - `_is_generic_screen_evidence(self, evidence)`
    - `_concrete_screen_signals(self, snapshot)`
    - `_concrete_vision_signals(self, snapshot)`
    - `_concrete_telemetry_signals(self, snapshot)`
    - `_has_concrete_screen_signal(self, snapshot)`
    - `_broadcast_screen_winners(self, broadcast)`
    - `_choose_autonomous_speech_intent(self)`
    - `_ambient_silence_cooldown_seconds(self, snapshot, ti_report)`
    - `_should_hold_ambient_silence(self)`
    - `_should_skip_weak_autonomous_speech(self)`
    - `_has_high_cognitive_momentum(self, thought_stream_report)`
    - `_choose_autonomous_sleep_duration(self)`
    - `_current_autonomous_wake_decision(self)`
    - `_wake_allows_main_cognition(self)`
    - `_autonomous_sleep_seconds_from_wake(self, decision)`
    - `_send_wake_gate_body_update(self, decision)`
    - `_wake_gate_ti_report(self)`
    - `_wake_gate_fe_plan(self)`
    - `_wake_gate_presence_candidate(self)`
    - `_presence_probe_status(self)`
    - `_reengagement_probe_status(self)`
    - `_update_wake_gate_debug(self, decision)`
    - `_presence_surface_status_label(self, status)`
    - `_log_presence_surface_statuses(self)`
    - `_build_wake_gate_frame(self)`
    - `_finalize_wake_gate_micro_decision(self)`
    - `_surface_arbiter_drop_reason(self, default)` — Lấy lý do SurfaceArbiter vừa từ chối surface, nếu có. Chú thích kiến trúc: Wake gate chỉ là cổng tài...
    - `_surface_arbiter_drop_status(self)`
    - `_surface_arbiter_reason_from_surface(self, surface, default)`
    - `_surface_arbiter_status_from_surface(self)`
    - `_maybe_low_level_surface_from_wake_gate(self)` — Cho SurfaceArbiter chạy ngay cả khi WakeGovernor trả sleep/observe_only. Chú thích kiến trúc: - Wake...
    - `_maybe_presence_maintenance_before_sleep(self)`
    - `_maybe_micro_presence_from_observe_only(self)`
    - `_finalize_autonomous_wake_gate(self)`
    - `_commit_think_only_active_frame(self)` — Tạo dấu vết cognition nhẹ cho `think_only` mà không gọi main LLM. `think_only` không được nói, nhưng...
    - `_process_pending_user_input(self)`
    - `_conversation_went_stale(self)` — True nếu đang chat_mode nhưng lượt user cuối đã hết "tươi". chat_mode không còn là công tắc bật/tắt...
    - `_run_loop_iteration(self)` — Run a single coordinator loop iteration. Returns True to keep looping, False to break the run_loop.
    - `run_loop(self)`
    - `_load_ni_meta_mode_flags(self)` — Đọc cấu hình ni_meta_config.json để bật/tắt meta-critic theo mode. Cấu trúc gợi ý: { "enabled": true...
    - `_soften_chat_meta_result(self)`
    - `_soften_autonomous_meta_result(self)`
    - `_maybe_apply_ni_meta_critic(self)` — Áp dụng tầng suy luận nhẹ của Ni dựa trên evidence và tín hiệu snapshot.
    - `_build_direct_action_decision(self, user_text, ti_report, snapshot)`
    - `_execute_system_action(self, decision)`
    - `_action_animation_hint(self, action_name, fallback)`
    - `_action_result_to_text(self, result)`
    - `_resolve_now_playing_text(self, snapshot)`
    - `_extract_media_title_from_snapshot(self, snapshot)`
    - `_extract_media_title(self, raw_title)`

## `runtime/daydream_model_adapter.py`
- LOC: 101
- Functions:
  - `_env_flag(name, default)`
- Classes:
  - `DaydreamModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True))
  - `DaydreamModelResult` (decorator=dataclass(slots=True, frozen=True))
  - `RuntimeDaydreamModelAdapter` — Adapter riêng cho daydream 4B, không ké style client.
    - `__init__(self)`
    - `from_env(cls)`
    - `chat_json(self, model, messages)`
    - `_from_ollama_result(self, result)`
    - `_log(self, level, msg)`

## `runtime/debug_console.py`
- LOC: 392
- Docstring: debug_console.py — Bảng lệnh debug ẩn cho ERIS. Đây KHÔNG phải đường runtime bình thường. Nó là cổng để Tác_Giả gõ lệnh tay từ panel DEBUG (góc dưới phải khung Cảm xúc) nhằm: * buff/ép chỉ số cảm xúc + quan hệ để test nhanh, * bật preset "yan" (chiếm hữu) để s...
- Functions:
  - `_clamp(value, signed)`
- Classes:
  - `DebugConsole` — Phân tích + thực thi lệnh debug trên state sống của coordinator.
    - `__init__(self, coordinator)`
    - `execute(self, command)`
    - `_state(self)`
    - `_commit(self, state)`
    - `_resolve_field(name)`
    - `_cmd_help(self, args)`
    - `_cmd_show(self, args)`
    - `_parse_pairs(args)` — Tách args thành các cặp (field, value). Hỗ trợ 2 dạng: * key=value (vd: attachment=0.9 trust=0.8) —...
    - `_apply_one(self, field, raw_value)`
    - `_cmd_set(self, args)`
    - `_cmd_buff(self, args)`
    - `_cmd_rel(self, args)`
    - `_cmd_trust(self, args)`
    - `_cmd_yan(self, args)`
    - `_cmd_mem(self, args)`
    - `_cmd_stage(self, args)`
    - `_cmd_reset(self, args)`
    - `_inject_memory(self, text)`

## `runtime/debug_trace.py`
- LOC: 305
- Docstring: runtime/debug_trace.py Debug Output Standard cho ERIS V3. Vấn đề kinh điển: pipeline chạy, module nào cũng có, nhưng khi hỏi "sao nó chọn nói/im/body_only?" thì câu trả lời là 400 dòng stack trace như tụng kinh. File này xuất MỖI cycle một JSON ngắn, đọc được...
- Functions:
  - `_get(obj, name, default)`
  - `_first_get(obj, names, default)`
  - `_shorten(text, max_len)`
  - `_round(value, digits)`
  - `_extract_budget(frame)`
  - `_extract_evidence_ids(frame, limit)`
  - `_extract_dominant_focus(frame)` — Lấy dominant focus từ salience (V3) hoặc broadcast (frame cũ).
  - `_extract_selected_evidence(frame, limit)` — Evidence mà attention thực sự chọn broadcast (không phải toàn bộ).
  - `_extract_working_memory(frame, limit)`
  - `_extract_workspace(frame, limit)`
  - `_extract_permission(frame)`
  - `_extract_speech_opportunity(frame)`
  - `_extract_final_action(frame)` — Hành động cuối: đọc từ frame V3 (execution/outcome) hoặc frame cũ (final_decision/action_plan).
  - `_extract_module_confidences(frame)`
  - `render_frame_trace(frame)` — Trả về dict trace ngắn, đọc được bằng mắt người, cho một cycle.
  - `render_frame_trace_json(frame)` — Trace dạng JSON string UTF-8 friendly.
  - `render_trace_line(frame)` — Một dòng tóm tắt cực ngắn cho log stream.
  - `attach_trace_to_frame(frame)` — Tạo trace và gắn vào frame.debug_notes/metadata nếu frame hỗ trợ. Trả về dict trace để caller dùng tiếp (vd ghi log).

## `runtime/disclaimer_markers.py`
- LOC: 33
- Docstring: Shared anti-disclaimer marker lists + predicates. Đây từng là HOME của các marker register cấm. Sau khi gom về một nguồn canonical (Nước 1 — VoicePolicy consolidation), module này chỉ còn là **shim re-export** từ ``runtime/voice_policy.py`` để mọi importer cũ...

## `runtime/eris_pathology_policy.py`
- LOC: 469
- Functions:
  - `normalize_vi(text)`
  - `_last_text(turns)`
  - `_last_assistant_text(turns)`
  - `_has_current_activity_evidence(state)`
  - `_scenario_from_input(turns, state, scenario)`
  - `run_pathology_turns(turns, state, scenario)` — Adapter-friendly entrypoint.
- Classes:
  - `PathologyDecision` (decorator=dataclass(slots=True))
    - `to_payload(self)` — Return shape accepted by test_eris_pathology_scenarios.ErisOutput.
  - `ErisPathologyPolicy` — Centralized deterministic response policy for pathology tests. Nó cố tình nhỏ và rõ. Đừng nhét toàn bộ runtime cognition vào đây. Policy này...
    - `maybe_handle(self, turns, state, scenario)`
    - `_handle_misread_correction(self, turns, state)`
    - `_handle_overread_short_ambiguous(self, turns, state)`
    - `_handle_underacted_fix_request(self, turns, state)`
    - `_handle_overexplained_short_answer(self, turns, state)`
    - `_handle_tone_mismatch_technical(self, turns, state)`
    - `_handle_privacy_intrusion_no_evidence(self, turns, state)`
    - `_handle_body_mismatch_presence(self, turns, state)`
    - `_handle_assistant_flattening(self, turns, state)`
    - `_handle_overhumanization_identity_boundary(self, turns, state)`
    - `_handle_public_turn_correction(self, turns, state)`
    - `_handle_memory_not_current_evidence(self, turns, state)`
    - `_handle_unknown(self, key)`

## `runtime/force_speak_cycle.py`
- LOC: 497
- Classes:
  - `ForceSpeakCycleMixin`
    - `_handle_force_speak_request(self)`
    - `_apply_force_speak_no_evidence_topic_filter(self, decision)`
    - `_build_planned_withdraw_decision(self, action_plan)`

## `runtime/force_speak_surface_policy.py`
- LOC: 148
- Classes:
  - `ForceSpeakSurfacePolicyMixin`
    - `_looks_internal_topic(self, value)`
    - `_is_generic_force_speak_ack(self, text)`
    - `_contains_force_speak_withdrawal_phrase(self, text)`
    - `_looks_like_question_text(self, text)`
    - `_reshape_statement_as_question(self, text)`

## `runtime/frame_builder.py`
- LOC: 1733
- Classes:
  - `FrameBuilderMixin`
    - `_make_cognitive_disturbance(self)`
    - `_looks_like_closure_disturbance(self, content)`
    - `_build_event_disturbances(self)`
    - `_disturb_cognitive_substrate(self)`
    - `_with_thought_stream_surface(self, report, surface)`
    - `_pop_thought_stream_report_for_autonomous(self)`
    - `_pop_subconscious_report_for_autonomous(self)`
    - `_thought_stream_resonance_fragments(self)`
    - `_normalize_event_evidence(self, evidence)`
    - `_make_percept_event(self)`
    - `_telemetry_event_privacy_level(self, kind)`
    - `_telemetry_event_novelty_hint(self, kind, content)`
    - `_collect_percept_events(self)`
    - `_collect_cognitive_percepts(self)`
    - `_score_attention_candidate(self, percept)`
    - `_build_attention_candidates(self, percepts)`
    - `_build_broadcast(self, candidates)`
    - `_evidence_from_percepts(self, percepts)`
    - `_salience_candidate_to_runtime(self, candidate)`
    - `_runtime_attention_label(self, candidate, tags)`
    - `_build_meaning_layer(self)`
    - `_build_personality_lens(self)`
    - `_apply_personality_lens_to_fe_plan(self, fe_plan, lens)`
    - `_build_cognitive_appraisal(self)`
    - `_build_appraisal_context(self, appraisal)`
    - `_build_inner_thought(self)`
    - `_build_speech_core(self)`
    - `_remember_inner_thought_rhythm(self, inner_thought)`
    - `_run_context_bottleneck(self, frame)`
    - `_build_cognitive_evidence(self, frame)`
    - `_append_working_memory_context(self, memory_context, frame)`
    - `_start_cognitive_frame(self)`
    - `_set_cognitive_action_plan(self, frame)`
    - `_apply_micro_line_policy_to_action_plan(self, frame)`
    - `_micro_policy_anchor_hints(self)`
    - `_build_relational_context(self, state)`
    - `_speech_intent_from_core(self, speech_core)`
    - `_merge_speech_core_notes(self, notes, speech_core)`
    - `_merge_meaning_layer_notes(self, notes, meaning_layer)`
    - `_merge_memory_resonance_notes(self, notes, memory_resonance)`
    - `_merge_inner_thought_notes(self, notes, inner_thought)`
    - `_merge_personality_lens_notes(self, notes, personality_lens)`
    - `_merge_subconscious_notes(self, notes, subconscious_report)`
    - `_is_inner_thought_speech_act(self, speech_act)`

## `runtime/guard_violations.py`
- LOC: 45
- Classes:
  - `GuardViolation` (decorator=dataclass(frozen=True, slots=True)) — Structured signal from a post-generation guard. A guard should describe what went wrong instead of becoming the final author of ERIS' public...
    - `compact_trace(self)`

## `runtime/inner_diary_persistence.py`
- LOC: 186
- Docstring: runtime/inner_diary_persistence.py ================================== Ghi `inner_diary` (và một ít ngữ cảnh từ private mind digest) ra đĩa dưới `memory_core/inner_diary.json`. Triết lý: - Inner diary là trạng thái nội tâm sống. Trước đây nó chỉ được render rồi...
- Functions:
  - `_env_flag(name, default)`
  - `_env_float(name, default)`
  - `_env_int(name, default)`
- Classes:
  - `InnerDiaryPersister` — Lưu inner_diary ra đĩa, có throttle và chống ghi trùng.
    - `__init__(self)`
    - `maybe_persist(self, digest)` — Ghi nếu tới hạn và nội dung đổi. Trả True nếu thực sự ghi.
    - `_ensure_loaded(self)`
    - `_write(self, digest, diary, text, now)`
    - `_log(self, level, msg)`

## `runtime/liveliness_config.py`
- LOC: 109
- Docstring: Configuration for the autonomous-liveliness redesign. All values are read from ``ERIS_LIVELINESS_*`` environment variables. Every reader clamps to a valid range and falls back to the documented default when a value is absent, malformed, or out of range; it nev...
- Functions:
  - `_warn_once(key, raw, default)`
  - `_read_float(key, default)`
  - `_read_int(key, default)`
  - `load_liveliness_config()` — Read the config from the environment with clamping and defaults.
- Classes:
  - `LivelinessConfig` (decorator=dataclass(frozen=True, slots=True))
    - `sim_threshold(self)` — Similarity threshold as a 0.0-1.0 fraction.

## `runtime/liveliness_tracker.py`
- LOC: 106
- Docstring: Per-cycle liveliness tracking and observability for the autonomous loop. Each idle cycle emits one ``DecisionRecord`` so that "alive" is measurable from logs and regressions are diagnosable. The tracker keeps a bounded ring buffer and computes window metrics (...
- Classes:
  - `DecisionRecord` (decorator=dataclass(frozen=True, slots=True))
    - `is_grounded(self)`
  - `LivelinessMetrics` (decorator=dataclass(frozen=True, slots=True))
  - `LivelinessTracker` — Bounded ring buffer of per-cycle decisions with window metrics.
    - `__init__(self)`
    - `record(self, rec)`
    - `recent(self, n)`
    - `for_cycle(self, cycle_id)`
    - `window_metrics(self)`

## `runtime/memory_recall_adapter.py`
- LOC: 459
- Functions:
  - `_extract_response_text(response)`
  - `_clean_public_fact_value(value)`
  - `_looks_like_internal_memory_surface(text)`
  - `_env_flag(name)`
  - `_env_int(name)`
  - `_env_float(name)`
- Classes:
  - `_MemoryQueryLLMConfig` (decorator=dataclass(frozen=True, slots=True))
    - `from_env(cls)`
  - `MemoryRecallAdapter` (decorator=dataclass(slots=True)) — Runtime adapter for structured memory recall. The public contract is intentionally simple: return a ready-to-send Decision before chat falls...
    - `try_answer(self, user_text)`
    - `try_answer_as_decision_payload(self, user_text)`
    - `_recall(self, user_text)`
    - `_should_intercept(self, best)`
    - `_ensure_compiler(self)`
    - `_execution_memory_core(self)`
    - `_build_decision(self, answer)`
    - `_debug_trace(self, answer)`
  - `_RecallOutcome` (decorator=dataclass(slots=True))
  - `_MemoryCoreProxy`
    - `__init__(self)`
    - `lookup_fact(self, fact_key)`
    - `get_fact(self, fact_key)`
    - `semantic_lookup(self, fact_key)`
    - `recall(self, query)`
    - `__getattr__(self, name)`
  - `_RuntimeMemoryQueryLLMClient` (base=MemoryQueryLLMClient; decorator=dataclass(slots=True))
    - `from_service(cls, service)`
    - `complete_json(self)`
    - `_passes_confidence_floor(self, raw)`

## `runtime/memory_semantic_parser_adapter.py`
- LOC: 363
- Functions:
  - `build_runtime_memory_semantic_parser()`
  - `_extract_response_text(response)`
  - `_parse_json_object(text)`
  - `_env_flag(name, default)`
  - `_env_float(name, default)`
  - `_env_int(name, default)`
- Classes:
  - `_StandaloneOllamaResult` (decorator=dataclass(slots=True))
  - `_StandaloneOllamaClient` — Client Ollama tối thiểu cho memory parser, tránh import package llm.
    - `__init__(self, base_url, timeout)`
    - `chat_json(self, model, messages)`
  - `MemorySemanticParserConfig` (decorator=dataclass(frozen=True, slots=True))
    - `from_env(cls)`
  - `RuntimeSemanticParser` (decorator=dataclass(slots=True)) — Adapter runtime -> MeaningFrame JSON -> verified MeaningParseResult.
    - `__post_init__(self)`
    - `from_env(cls)`
    - `parse(self, text)`
    - `_call_provider(self, text)`
    - `_call_ollama(self, text)`
    - `_call_llm_service(self, text)`
    - `_messages(self, text)`
    - `_log_warning(self, message)`

## `runtime/model_budget_policy.py`
- LOC: 894
- Docstring: src/runtime/model_budget_policy.py ================================== Module sinh tử của tầng tự chủ. Bản này không chỉ là gatekeeper nữa. Nó vẫn đo CPU/RAM/VRAM và veto như cũ, nhưng có thêm hàng đợi inference dùng chung: - global inference lock cho các model...
- Functions:
  - `_clamp01(value, default)`
  - `_safe_float(value, default)`
  - `_env_float(name, default)`
  - `_env_flag(name, default)`
  - `_env_int(name, default)`
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
  - `ModelBudgetPolicy` — Budget gatekeeper + scheduler nhẹ cho model inference. Đây chưa phải Kubernetes mini. Nó không thể giết request HTTP đã bay vào provider ngo...
    - `__init__(self, config, logger)`
    - `capture(self)` — Đo tài nguyên best-effort. Không có psutil/nvidia-smi thì vẫn trả snapshot thay vì chết. Đáng tiếc l...
    - `can_run(self, tier)`
    - `lease(self, tier)`
    - `run_queued(self, tier, func)` — Chạy một inference qua queue và lease. `unload_callback` được gọi khi model call kết thúc nhưng trướ...
    - `acquire_lease(self, tier)`
    - `release_lease(self, lease)`
    - `cancel_queued_request(self, request_id)` — Hủy một request chưa chạy. Request đã vào HTTP call thì không giết được ở đây.
    - `cancel_all_queued(self)`
    - `queue_state(self)`
    - `mark_started(self, tier)`
    - `mark_finished(self, tier)`
    - `veto_or_raise(self, tier)`
    - `_cooldown_for(self, tier, now)`
    - `_capture_nvidia_smi(self, notes)`
    - `_is_heavy_tier(self, tier)`
    - `_uses_remote_api(self, tier)`
    - `_should_force_vision(self, tier)`
    - `_should_force_local_gguf_main(self, tier)` — main_cognition chạy local GGUF (remote API tắt) → ép chạy: nó là não duy nhất.
    - `_estimated_vram_need_mb(self, tier)`
    - `_should_bypass_vision_vram_guard(self, tier)`
    - `_reserved_vram_for_active_leases_locked(self)`
    - `_active_reserved_vram_mb(self, snapshot)`
    - `_has_incompatible_active_lease(self, tier)`
    - `_resource_block_reasons(self, tier)`
    - `_entry_cancelled(self, entry)`
    - `_sort_queue_locked(self)`
    - `_queue_head_locked(self)`
    - `_remove_queue_entry_locked(self, request_id)`
    - `_has_incompatible_active_lease_locked(self, tier)`
    - `_wait_seconds(self, entry, now)`
    - `_log(self, level, msg)`

## `runtime/no_fallback_policy.py`
- LOC: 57
- Functions:
  - `no_fallback_mode_enabled()`
  - `build_no_fallback_payload()`
  - `_default_no_fallback_text()`

## `runtime/outcome_observer.py`
- LOC: 557
- Classes:
  - `OutcomeReport` (decorator=dataclass(slots=True)) — Báo cáo hậu quả sau một turn. Các field lõi bám theo ERIS Cognitive Pipeline: - user_accepted: user có chấp nhận/đồng ý với câu trả lời khôn...
    - `to_dict(self)`
    - `from_any(cls, value)`
  - `OutcomeObserver` — Đọc tín hiệu hậu quả sau một turn. Cách dùng thường gặp: outcome = outcome_observer.observe(frame) frame.outcome = outcome Nếu muốn đánh giá...
    - `observe(self, frame)` — Tạo OutcomeReport từ frame và các tín hiệu hậu quả. Parameters ---------- frame: CognitiveFrame hoặc...
    - `observe_user_feedback_for_previous_frame(self, previous_frame, user_feedback_text)` — Helper dành cho coordinator khi user vừa nhắn một câu phản hồi. Thay vì đánh giá current frame, nó đ...
    - `_infer_action_success(self, frame)`
    - `_infer_body_match_success(self, frame)`
    - `_estimate_confidence(self)`
    - `_normalize(cls, text)`
    - `_has_any(cls, normalized_text, patterns)`
    - `_extract_final_text(frame)`
    - `_extract_system_action(frame)`
    - `_read_bool(obj, key)`
    - `_read_float(obj, key)`
    - `_safe_setattr(obj, key, value)`
    - `_clamp01(value)`

## `runtime/post_generation_filters.py`
- LOC: 1938
- Classes:
  - `PostGenerationFiltersMixin` — Post-generation filters after the cognition/wording layers. This mixin should not be the personality author. It keeps hard grounding boundar...
    - `_guard_mode_value(self, name)`
    - `_guard_is_off(self, name)`
    - `_guard_is_log_only(self, name)`
    - `_trace_only_guard(self, decision, marker)`
    - `_remember_guard_violation(self, violation)`
    - `_guard_internal_state_values(self)`
    - `_guard_internal_state_context(self)`
    - `_dynamic_guard_bottom_fallback(self, violation)`
    - `_guard_arbitration_context(self, speech_core)`
    - `_guard_body_only_decision(self, decision, violation)`
    - `_guard_grounding_context(self, frame, grounding)`
    - `_guard_reroll_is_clean(self, text, violation)`
    - `_repair_guard_violation_decision(self, decision, violation)`
    - `_record_agent_mind_feedback_from_user(self, user_text)` — Ghi feedback semantic vào Persistent Agent Mind Layer nếu user đang phản hồi hành vi. Câu như "đừng...
    - `_normalize_guard_ascii(self, text)`
    - `_reroll_still_disclaimer(self, text)` — Kiểm tra nhanh (flag-agnostic) xem reroll có còn giọng helpdesk không.
    - `_detect_chat_disclaimer(self, text)`
    - `_apply_chat_disclaimer_guard(self, decision)`
    - `_apply_chat_final_guards(self, decision)`
    - `_append_trace(self, trace, marker)`
    - `_protocol_surface_leak_markers(self)`
    - `_detect_protocol_surface_leak(self, text)`
    - `_protocol_surface_repair_text(self)`
    - `_apply_protocol_surface_guard(self, decision)`
    - `_detect_internal_object_surface_leak(self, text)`
    - `_internal_object_surface_repair_text(self)`
    - `_apply_internal_object_surface_guard(self, decision)`
    - `_apply_memory_haunting_guard(self, decision)`
    - `_guard_recent_context_as_screen_observation(self, decision)`
    - `_apply_chat_grounding_guard(self, decision)`
    - `_is_repeated_clarifying_question(self, text, last_assistant_text)`
    - `_guard_text_similarity(self, left, right)`
    - `_normalize_guard_text(self, text)`
    - `_looks_like_file_grounded_claim(self, text)`
    - `_looks_like_screen_grounded_claim(self, text)`
    - `_looks_like_live_web_claim(self, text)`
    - `_guard_user_explained_reason(self, text)`
    - `_build_relational_repair_line(self, user_text, last_assistant_text)`
    - `_copy_decision_with_text(self, decision)` — Copy decision nhưng giữ metadata sống. Bản cũ tạo `Decision(...)` mới và làm rơi intent/confidence/s...
    - `_semantic_repair_failed_decision(self, decision)`
    - `_inner_thought_alignment_fallback_text(self, speech_core, intent)`
    - `_apply_inner_thought_intent_alignment_filter(self, decision)`
    - `_contains_mindreading_claim(self, text)`
    - `_is_interactive_guess_text(self, text)` — Phân biệt phỏng đoán tương tác với đọc tâm trí độc đoán. “Có vẻ Ngài đang... phải không?” là probe:...
    - `_source_grounding_allows_probe(self)` — Cho post-filter biết SourceGrounding đang ở mode curiosity/probe. Thiếu evidence kiểu screen/memory...
    - `_interactive_guess_allowed(self, text)` — Quyền được đoán-sai-có-mời-sửa. Điều kiện cố ý hẹp: - phải là câu phỏng đoán có hedge/câu hỏi; - hoặ...
    - `_speech_core_safe_fallback_text(self, speech_core)`
    - `_arbitration_report_from_speech_core(self, speech_core)` — Lấy arbitration_report từ SpeechCore nếu có. Guard dùng cái này để phân biệt: motive inference có ev...
    - `_selected_impulse_from_arbitration(self, report)`
    - `_arbitration_selected_has_evidence(self, selected)`
    - `_mindreading_is_grounded_task_or_scene(self, text)` — Cho phép suy diễn động cơ nông nếu nó bám scene/task evidence. Cho phép: "có vẻ Ngài đang debug/test...
    - `_arbitration_rewrite_for_mindreading(self)` — Rewrite mindreading bằng arbitration_report. Return: (replacement, marker, allow_original). Nếu allo...
    - `_apply_anti_mindreading_filter(self, decision)`
    - `_guard_force_speak_repetition(self, decision)`
    - `_apply_repetition_filter(self, decision)`
    - `_looks_like_unanchored_style_line(self, text)`
    - `_apply_style_contract_filter(self, decision)`
    - `_policy_intent_for_speech_core(self, speech_core)`
    - `_apply_micro_line_policy_filter(self, decision)`
    - `_apply_post_generation_filters(self, decision)`
    - `_apply_internal_meaning_label_filter(self, decision)`

## `runtime/presence_controller.py`
- LOC: 3228
- Classes:
  - `MicroPresenceSynthesis` (decorator=dataclass(frozen=True, slots=True))
  - `SocialPresenceEvent` (decorator=dataclass(frozen=True, slots=True))
    - `to_dict(self)`
  - `MicroPresenceCue` (decorator=dataclass(frozen=True, slots=True)) — Steering flags for micro-presence, not public wording.
    - `to_context(self)`
  - `SurfaceArbitrationResult` (decorator=dataclass(frozen=True, slots=True))
  - `PresenceControllerMixin`
    - `_surface_anchor_token(self, kind, value)`
    - `_surface_vision_stale_seconds(self)`
    - `_surface_has_fresh_vision_evidence(self, snapshot)`
    - `_surface_wants_current_context(self)`
    - `_surface_refresh_vision_once_if_needed(self)`
    - `_surface_seed_can_speak_without_screen(self, compiled_seed)`
    - `_stale_surface_body_only(self)`
    - `_surface_seed_compiler(self)`
    - `_inner_diary_for_compile(self)` — Lấy inner_diary đã render từ private_mind_digest cho SurfaceSeedCompiler. Diary là giọng Eris public...
    - `_surface_arbiter(self)` — Lazy init SurfaceArbiter: một cổng duy nhất cho micro/re-engagement/spontaneous surface.
    - `_spontaneity_policy_config(self)` — Config arbiter có nối núm spontaneity. Spontaneity cao ⇒ đưa các impulse 'sống' vào always_llm_kinds...
    - `_surface_arbiter_llm_generate(self)` — Adapter để SurfaceArbiter dùng generator micro hiện có, không tự viết fallback.
    - `_blind_frustration_blames_user_without_evidence(self, text, impulse)`
    - `_local_micro_presence_fallback_text(self)` — Tiny public line for presence routes when evidence ids are thin.
    - `_safe_local_micro_presence_fallback(self, text)`
    - `_surface_body_only_decision(self, surface)`
    - `_surface_speech_decision(self, surface)`
    - `_surface_override_note(self)`
    - `_event_semantic_presence_detector(self)`
    - `_detect_social_presence_event(self)`
    - `_note_autonomous_silence(self)`
    - `_note_autonomous_spoken(self)`
    - `_safe_small_talk_budget_allowed(self)`
    - `_surface_float(self, value, default)`
    - `_surface_signed_float(self, value, default)`
    - `_endogenous_topic_seed(self)` — Lấy topic seed không phụ thuộc màn hình cho inner_whim/random_chatter. Đây là lớp chất liệu, không p...
    - `_current_ego_surface_state(self)` — Đọc nhanh mood + relationship để presence không hành xử như đồng hồ báo thức.
    - `_presence_ego_gate_reason(self)` — Trả reason nếu presence maintenance không được sinh impulse. Đây là ego-gate cấp nguồn: tâm trạng tồ...
    - `_memory_resonance_surface_impulse(self)`
    - `_spontaneity_level(self)` — Núm 'sống động': 0=kiệm lời như cũ, 1=sinh impulse rất dồi dào. Chỉ hạ NGƯỠNG SINH impulse, không tự...
    - `_build_endogenous_surface_impulses(self)`
    - `_should_allow_presence_maintenance(self)`
    - `_presence_maintenance_lines(self, snapshot)`
    - `_focus_family_for_snapshot(self, snapshot)`
    - `_internal_curiosity_for_micro_presence(self)`
    - `_derive_micro_presence_cue(self)`
    - `_blind_frustration_surface_impulse(self)`
    - `_body_only_presence_decision(self, cue)`
    - `_is_body_only_presence_decision(self, decision)`
    - `_note_autonomous_presence_action(self)`
    - `_generate_micro_presence_from_cue(self)`
    - `_cue_micro_lines(self)`
    - `_micro_line_subject(self, value)`
    - `_clean_micro_line(self, text)`
    - `_vision_fact_micro_observation_candidate(self, frame)`
    - `_build_micro_observation_decision(self)`
    - `_try_finalize_micro_observation_cycle(self)`
    - `_micro_presence_kind_from_seed(self, seed)`
    - `_thought_residue_seeds(self, report)`
    - `_synthesize_micro_presence(self)`
    - `_choose_local_micro_line(self, lines)`
    - `_local_grounded_micro_presence_text(self, synthesis)`
    - `_is_placeholder_micro_text(self, text)`
    - `_micro_line_policy_for_action_plan(self, frame)`
    - `_micro_presence_generator(self)`
    - `_should_try_micro_presence_llm(self)`
    - `_sanitize_micro_presence_llm_text(self, text)`
    - `_sanitize_blind_frustration_text(self, cleaned)`
    - `_hybrid_micro_presence_text(self)`
    - `_filter_public_micro_decision(self, decision)` — Đưa mọi micro/presence/reengagement line qua cùng post-generation guard. Trước đây presence maintena...
    - `_build_surface_arbiter_decision(self)`
    - `_build_surface_arbiter_result(self)`
    - `_try_finalize_surface_arbiter_cycle(self)`
    - `_build_presence_maintenance_decision(self)`
    - `_try_finalize_presence_maintenance_cycle(self)`
    - `_social_energy_for_reengagement(self, internal_state)`
    - `_has_meaningful_recent_activity(self, snapshot)`
    - `_reengagement_idle_debt_allows(self, idle_seconds)`
    - `_should_allow_reengagement(self)`
    - `_reengagement_lines(self, snapshot)`
    - `_derive_reengagement_cue(self)`
    - `_build_reengagement_decision(self)`
    - `_try_finalize_reengagement_cycle(self)`
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
- LOC: 332
- Docstring: runtime/private_life_daemon.py ============================== Daemon đồng bộ cho PrivateLifeCore. Tên daemon ở đây nghĩa là owner lifecycle, không phải thread riêng. Runtime chính đã đủ nhiều vòng lặp; thêm thread chỉ để "sống hơn" là cách rất nhanh để biến ag...
- Functions:
  - `_value(obj, name, default)`
  - `_env_bool(name, default)`
  - `_env_float(name, default)`
  - `_infer_project_root()`
- Classes:
  - `PrivateLifeDaemonConfig` (decorator=dataclass(slots=True))
    - `from_env(cls)`
  - `PrivateLifeDaemonTick` (decorator=dataclass(slots=True))
    - `to_dict(self)`
  - `PrivateLifeDaemon` — Lifecycle owner cho PrivateLifeCore.
    - `__init__(self)`
    - `from_runtime(cls)`
    - `tick(self)`
    - `drain_surface_impulses(self)` — Lấy impulse private-life đã chuyển dạng cho SurfaceArbiter.
    - `digest(self)`
    - `_maybe_enqueue_surface_seed(self, seed)`
    - `_seed_to_surface_impulse(self, seed)`
    - `_infer_idle(self)`
    - `_sync_runtime_owner(self)`
    - `_impulse_digest(item)`

## `runtime/private_mind_daemon.py`
- LOC: 433
- Docstring: runtime/private_mind_daemon.py ============================== Daemon runtime cho PrivateMind. Khác với `PrivateMindLoop`, daemon này không chỉ chạy một lượt evaluator. Nó giữ vòng đời của private mind trong runtime: - sở hữu queue SurfaceImpulse đã được lọc; -...
- Classes:
  - `PrivateMindDaemonConfig` (decorator=dataclass(slots=True)) — Knob lifecycle cho private mind daemon. Ghi chú tiếng Việt để lúc debug không phải đoán ý đồ của người viết cũ, tức chính chúng ta ở tương l...
  - `PrivateMindDaemonTick` (decorator=dataclass(slots=True)) — Kết quả tick ở tầng daemon. `loop_result` giữ payload sâu; daemon thêm lifecycle metadata để debug vì private cognition mà không có trace th...
    - `to_dict(self)`
  - `PrivateMindDaemon` — Lifecycle owner cho PrivateMindLoop. Trách nhiệm của daemon: 1. Không sinh lời thoại public. 2. Giữ concern/outcome sống qua nhiều tick. 3....
    - `__init__(self)`
    - `from_runtime(cls)` — Tạo daemon từ runtime hiện có. Vẫn dùng `PrivateMindLoop.from_runtime()` để giữ tương thích env cũ:...
    - `concern_store(self)`
    - `mutation_bus(self)`
    - `tick(self)`
    - `record_outcome(self, outcome)` — Nhận hậu quả public turn và cập nhật concern lifecycle. Outcome không được biến thành lời nói ngay....
    - `_attach_comfort_appraisal(self, outcome)` — Chạy ComfortAppraiser và gắn payload `comfort` vào outcome nếu có ý nghĩa. Trả lại outcome (có thể đ...
    - `_extract_feedback_text(outcome)`
    - `_extract_flag(outcome, name)`
    - `_inject_comfort(outcome, comfort)`
    - `_disposition_warmth_threat(self)` — Lấy warmth/threat (ego) của Eris từ internal state qua disposition. Thiếu state → trả trung tính ngh...
    - `drain_surface_impulses(self)` — Lấy impulse đã lọc để SurfaceArbiter xử lý. Queue này là ranh giới công khai: mọi thứ trước nó vẫn l...
    - `digest(self)`
    - `_merged_surface_outcome(self, surface_outcome)`
    - `_surface_outcome_from_frame(self, frame)`
    - `_trim_surface_queue(self, queue)`
    - `_surface_preview(self, item)`
    - `_sync_runtime_owner(self)`
    - `_log(self, level, message)`

## `runtime/private_mind_loop.py`
- LOC: 767
- Docstring: runtime/private_mind_loop.py ============================ Runtime loop cho private mind 5 phase: A. contracts + concern store B. evidence dossier C. 4 mini-evaluator API/rules D. Gemma inner synthesizer E. state mutation + surface valve Loop này không tự nói v...
- Functions:
  - `_env_flag(name, default)`
- Classes:
  - `PrivateMindLoopConfig` (decorator=dataclass(slots=True))
  - `PrivateMindLoop` — Orchestrator của private mind.
    - `__init__(self)`
    - `from_runtime(cls)`
    - `tick(self)`
    - `_capture_affect(self, runtime_owner)` — Chụp snapshot cảm xúc liên tục thật từ runtime_owner (không bao giờ ném lỗi). Giữ bản tốt gần nhất:...
    - `_followup_fragments(self, dossier)` — Biến mạch nghĩ dang dở thành fragment để synthesizer nghĩ tiếp. Hiếm khi chạy (cooldown trong Though...
    - `_record_continuity(self, judgment)` — Ghi suy nghĩ vừa sinh vào dòng liên tục (RAM + JSONL).
    - `digest(self)` — Compact dev payload for private mind state. This intentionally exposes summaries and mutation report...
    - `_diary_voice(self, digest)` — Lấy bản nhật ký giọng Eris (throttled). Lỗi → None để renderer fallback.
    - `drain_surface_impulses(self, queue)`
    - `_model_api_status(self)`
    - `_resolve_concern_path(self)`
    - `_resolve_user_model_path(self)`
    - `_resolve_anchor_journal_path(self)` — Đường dẫn JSONL nhật ký trục neo (append-only, tái sử dụng được).
    - `_build_anchor_block(self)` — Gom toàn trục neo thành 1 block JSON-safe cho panel C# đọc. Đọc-only từ self.anchor_system (đã updat...
    - `_maybe_journal_anchor(self, block)` — Append một dòng JSONL khi trục neo ĐỔI — để tái sử dụng/replay. Dedup theo chữ ký để tick không đổi...
    - `_update_anchor_system(self)` — Cập nhật trục neo hiện sinh từ một tick và phơi facade cho runtime. Đọc tín hiệu sẵn có trong dossie...
    - `_anchor_irritation(runtime_owner)` — Mức bực hiện tại từ persistent internal state (cho nhánh 'giận → dỗi').
    - `_anchor_internal_state(runtime_owner)` — Nguồn Sợ_Hiện_Sinh: RollingInternalState từ contextual loop nếu có. Thử vài tên thuộc tính thường gặ...
    - `_log_anchor_warning(self, exc)`
    - `_log_tick(self, result)`

## `runtime/private_mind_model_adapter.py`
- LOC: 1664
- Docstring: runtime/private_mind_model_adapter.py ===================================== Adapter API cho private mind: - evaluate_fragment(evaluator_name, dossier) - synthesize_judgment(dossier, fragments) Adapter này ưu tiên dùng `llm_service` nếu được inject từ coordinat...
- Functions:
  - `_env_flag(name, default)`
  - `_as_float(value, default)`
  - `_classify_transport_exception(exc)` — Phân loại exception thành 'transient' hoặc 'fixed_config'. Quy tắc (theo *kiểu* và *status*, không theo message): - requ...
- Classes:
  - `PrivateMindModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True))
    - `fragment_overlay_from_env(cls, base)` — Config riêng cho fragment: nếu khai ERIS_PRIVATE_MIND_FRAGMENT_PROVIDER thì trỏ fragment sang một pr...
  - `PrivateMindModelResult` (decorator=dataclass(slots=True))
  - `RuntimePrivateMindModelAdapter` — Adapter chung cho 4 mini-evaluator và GemmaInnerSynthesizer.
    - `__init__(self)`
    - `_current_api_key(self)` — Trả API key hiện tại. Ưu tiên config (test), rồi pool chung, rồi env.
    - `_rotate_to_next_key(self)` — Xoay pool chung sang key kế. Trả True nếu xoay được (pool có >1 key).
    - `from_env(cls)`
    - `diary_fallback_from_env(cls)` — Adapter DỰ PHÒNG riêng cho Inner Diary. Dùng khi provider chính (Gemini gemma) chết / lỗi JSON: diar...
    - `min_interval_seconds(self)`
    - `evaluate_fragment(self, evaluator_name, dossier)`
    - `_freetext_fragment(self, evaluator_name, dossier)` — Sinh MỘT mảnh suy nghĩ ngắn dạng văn xuôi, rồi guard + bọc thành fragment. Không parse JSON nên mode...
    - `_freetext_fragment_messages(self, evaluator_name, dossier)`
    - `_guard_freetext_fragment(self, content)` — Guard local rẻ: làm sạch + loại output rác. Trả claim sạch hoặc '' nếu loại.
    - `_wrap_freetext_fragment(self, evaluator_name, claim, dossier)`
    - `_tracked_chat_text(self, messages)` — Như _tracked_chat_json nhưng KHÔNG parse JSON: content rỗng/transient = fail.
    - `_chat_text_with_transient_retry(self, messages)`
    - `_chat_text_once(self, messages)` — Gọi model trả văn bản thô (response_format=None → không ép JSON).
    - `synthesize_judgment(self, dossier, fragments)`
    - `appraise_comfort(self, user_text, concern_themes)` — Agent nhỏ thẩm định một câu của user có phải lời dỗ thật không. Trả dict: is_comfort (bool), on_topi...
    - `_comfort_messages(self, user_text, concern_themes)`
    - `_comfort_response_schema(self)`
    - `write_inner_diary(self, facts)` — Viết lại các dữ kiện nội tâm thành nhật ký giọng Eris (ngôi thứ nhất). Trả dict 5 trường tiếng Việt:...
    - `_diary_messages(self, facts)`
    - `_diary_response_schema(self)`
    - `_slice_for_intent(self, dossier)` — intent_evaluator: user turns + goal. Không cần memory hay concerns.
    - `_slice_for_memory_resonance(self, dossier)` — memory_resonance_evaluator: memory hits + repair failures + concerns.
    - `_slice_for_risk(self, dossier)` — risk_and_permission_evaluator: surface outcome + runtime flags + evidence ids.
    - `_slice_for_future_bias(self, dossier)` — future_bias_evaluator: concerns nặng nhất + current_task + 1 user turn.
    - `_fragment_messages(self, evaluator_name, dossier)`
    - `_slice_for_user_model(self, dossier)` — user_model_evaluator: lời người dùng + chân dung Ngài hiện có + nhịp tương tác. Cho model thấy nó đã...
    - `_slim_dossier(self, dossier)` — Chắt lọc dossier xuống những gì synthesizer thực sự cần. Bỏ runtime_state (lớn, ít signal), memory_h...
    - `_slim_fragment(self, f)` — Fragment tối giản: chỉ claim + score + evidence_ids, bỏ hypotheses/metadata.
    - `_judgment_messages(self, dossier, fragments)`
    - `_fragment_response_schema(self, evaluator_name)`
    - `_judgment_response_schema(self)`
    - `debug_status(self)`
    - `_tracked_chat_json(self, messages)`
    - `_json_cooldown_active(self)`
    - `_maybe_enter_json_cooldown(self)`
    - `_synthesis_json_cooldown_active(self)`
    - `_maybe_enter_synthesis_json_cooldown(self)` — Vào cooldown riêng cho synthesis khi streak >= 3. Fragment success không reset streak này nên nó acc...
    - `_transient_cooldown_active(self)`
    - `_maybe_enter_transient_cooldown(self)`
    - `_extract_usage(self, raw)`
    - `_chat_json(self, messages)`
    - `_chat_json_with_transient_retry(self, messages)` — Gọi _chat_json_once, thử lại có giới hạn + backoff nếu gặp transient error. Nếu lỗi là 429 (quota) t...
    - `_chat_json_once(self, messages)`
    - `_response_format(self, response_schema)`
    - `_json_repair_messages(self, messages, invalid_content)`
    - `_provider_chat_json(self, messages)`
    - `_provider_client_or_build(self)`
    - `_extract_content(self, raw)`
    - `_parse_json(self, content)`
    - `_json_candidates(self, text)`
    - `_strip_markdown_fences(self, text)`
    - `_extract_first_json_object(self, text)`
    - `_extract_repairable_json_object(self, text)`
    - `_salvage_truncated_json(self, text)` — Cứu JSON cụt do model lặp vô hạn ở một field free-text. Chiến lược: gom các cụm lặp liên tiếp lại, b...
    - `_collapse_repetition_in_obj(self, obj)` — Áp _collapse_repetition đệ quy lên mọi chuỗi trong dict/list đã parse. Field ngắn/có cấu trúc (sourc...
    - `_collapse_repetition(self, text)` — Gom các cụm ký tự lặp liên tiếp >=4 lần xuống còn 2 lần. Bắt cả lặp một từ ('foo foo foo foo') lẫn l...
    - `_ends_inside_string(self, text)`
    - `_json_object_balance(self, text)`
    - `_loads_json_object(self, candidate)`
    - `_repair_common_json_noise(self, text)`
    - `_safe_raw(self, raw)`
    - `_log(self, level, msg)`
  - `PrivateMindAdapterPool` — Pool adapter cho private mind. Thay vì một instance dùng chung cho tất cả, mỗi vai trò có adapter riêng: - 4 adapter cho 4 fragment evaluato...
    - `__init__(self)`
    - `from_env(cls)`
    - `fragment_adapter(self, evaluator_name)` — Trả adapter riêng cho evaluator_name; fallback về adapter đầu tiên nếu không tìm thấy.
    - `synthesis_adapter(self)`
    - `evaluate_fragment(self, evaluator_name, dossier)`
    - `synthesize_judgment(self, dossier, fragments)`
    - `write_inner_diary(self, facts)`
    - `debug_status(self)` — Aggregate status của tất cả adapter trong pool.

## `runtime/prompt_context_builder.py`
- LOC: 1018
- Classes:
  - `PromptContextBuilderMixin`
    - `_log_exception(self, message)`
    - `_session_ritual_fallback_decision(self)`
    - `_send_session_ritual_fallback_greeting(self)`
    - `_session_ritual_llm_timeout(self)`
    - `_build_internal_state_context(self, state, self_state)`
    - `_render_felt_state_context(self, state)` — Gemma dịch state số → 1 câu cảm giác ngôi-thứ-nhất, để ERIS tự thuật thật. Có throttle/cache trong a...
    - `_render_anchor_register_context(self)` — Đưa register cảm xúc hiện tại (dỗi/chiếm hữu/van xin/kiểm soát) vào chat. Đây là chỗ 'dỗi khi giận /...
    - `_render_inner_diary_context(self)` — Đưa nhật ký nội tâm (diary) vào ngữ cảnh chat. Trước đây diary chỉ chảy một chiều ra UI; khi Ngài hỏ...
    - `_render_private_mind_speech_bias_context(self)`
    - `_build_thought_stream_context(self)`
    - `_thought_stream_root_seeds(self)` — Lấy rễ cho inner_whim từ unresolved memory và daydream. ThoughtStream chỉ nên ngẫu hứng từ thứ từng...
    - `_build_subconscious_context(self)`
    - `_build_memory_context(self, snapshot, memory_resonance)`
    - `_filter_memory_context_for_grounding(self, memory_context)` — Giữ procedural guard, bỏ memory có hình dạng câu trả lời. Bản cũ giữ mọi dòng có chữ "source" hoặc "...
    - `_build_action_plan_context(self, action_plan)`
    - `_build_llm_ti_context(self, ti_report, action_plan)`
    - `_build_speech_evidence_context(self, snapshot)`
    - `_build_current_focus_context(self, snapshot)`
    - `_build_session_ritual_ti_context(self, report, snapshot)`
    - `_restore_session_ritual_once(self)`
    - `_build_speech_core_ti_context(self, ti_report, action_plan, inner_thought, speech_core)`
    - `_build_ni_telemetry_summary(self, snapshot)` — Tóm tắt telemetry gọn cho Ni meta-critic mà không phụ thuộc TelemetryService. Dùng được cả trong uni...
    - `_label_drift_score(self, drift_score)`
    - `_is_low_signal_chat_message(self, user_text)`
    - `_conversation_ttl_seconds(self)` — TTL của bộ đệm hội thoại hợp nhất. Một lượt cũ hơn ngần này (tính từ lúc ghi) bị coi là đã phai và k...
    - `_chat_history_for_llm(self)`
    - `_append_chat_history(self, role, content)`
    - `_build_conversation_context(self)` — Render đuôi hội thoại gần nhất (còn tươi) thành block prompt. Đây là cầu nối liền mạch chat <-> auto...
    - `_merge_conversation_context(self, memory_context)` — Ghép đuôi hội thoại gần nhất vào memory_context của autonomous.
    - `_user_denies_last_assistant_assumption(self, user_text)`
    - `_invalidate_last_assistant_history(self)`
    - `_maybe_invalidate_last_assistant_history(self, user_text)`
    - `_looks_like_no_evidence_style(self, claim_style)`
    - `_build_ni_structured_context(self)`

## `runtime/public_turn_ledger.py`
- LOC: 132
- Functions:
  - `normalize_public_turn_channel(channel)`
  - `infer_public_turn_channel(decision)`
- Classes:
  - `PublicTurn` (decorator=dataclass(slots=True))
  - `PublicTurnLedger`
    - `__init__(self)`
    - `append(self)`
    - `record_decision(self, decision)`
    - `all(self)`
    - `recent(self, limit)`
    - `latest_visible_before(self, timestamp)`
    - `extend(self, turns)`

## `runtime/relational_voice_seed_adapter.py`
- LOC: 578
- Docstring: Register-default voice-seed pipeline. For social-register chat turns, ERIS — not the remote model's "helpful assistant" prior — owns the opening token. A short stance-locked seed is authored by the gemma/style client; the llama/main client only *continues* it;...
- Functions:
  - `normalize_text(raw)` — ASCII-fold + lowercase + collapse whitespace (parity with service.py).
  - `_matches_any(normalized, patterns)`
  - `detect_relational_act(raw_user_text)` — DEMOTED sub-classifier: shapes seed direction (and is the trigger only under scope == RELATIONAL). Pure and deterministi...
  - `_local_looks_like_code(normalized)`
  - `classify_chat_register(raw_user_text)` — Compose existing cheap signals into SOCIAL vs TASK. No extra model call. ``ti_mode`` = ti_report.mode (chat_code / chat_...
  - `should_use_voice_seed(register, scope, act)` — The GATE. Pure, offline-testable. Matches the design scope truth table.
  - `_env_int(name, default)`
  - `_env_float_ms(name, default_seconds)`
  - `_env_flag(name, default)`
  - `derive_direction(act)`
- Classes:
  - `ChatRegister` (base=Enum)
  - `VoiceSeedScope` (base=Enum)
    - `from_str(cls, raw)`
  - `RelationalAct` (base=Enum)
  - `CognitionStance` (decorator=dataclass(slots=True, frozen=True))
  - `SeedPlan` (decorator=dataclass(slots=True, frozen=True))
  - `ContinuationResult` (decorator=dataclass(slots=True, frozen=True))
  - `RelationalVoiceSeedConfig` (decorator=dataclass(slots=True, frozen=True))
    - `from_env(cls)`
  - `RelationalVoiceSeedAdapter` (decorator=dataclass(slots=True))
    - `try_answer(self, user_text)`
    - `_plan_seed(self, user_text, stance)`
    - `_continue_from_seed(self, user_text, seed, stance)`
    - `_join(self, seed, continuation)`
    - `_build_decision(self)`
    - `_build_seed_system_prompt(self, stance)`
    - `_build_seed_user_prompt(self, user_text, stance)`
    - `_build_continuer_system_prompt(self, stance)`
    - `_anti_disclaimer_fewshot(self)`
    - `_extract(self, resp)`
    - `_first_line(self, raw)`
    - `_first_clause(self, text)`
    - `_clamp_words(self, text, max_words)`
    - `_is_429(self, exc)`
    - `_warn(self, fmt)`

## `runtime/sensor_visibility.py`
- LOC: 324
- Functions:
  - `derive_sensor_visibility_state()`
  - `_has_current_screen_evidence(snapshot, frame)`
  - `_collect_text_signals()`
  - `_explicit_bool()`
  - `_parse_bool(value)`
  - `_get_value(owner, name, default)`
  - `_has_payload(value)`
  - `_clamp01(value)`
- Classes:
  - `SensorVisibilityState` (decorator=dataclass(frozen=True, slots=True))
    - `to_context(self)`

## `runtime/sensory_model_adapter.py`
- LOC: 147
- Functions:
  - `_env_flag(name, default)`
- Classes:
  - `SensoryModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True))
  - `RuntimeSensoryModelAdapter` — Adapter riêng cho tầng cảm giác 0.6B.
    - `__init__(self)`
    - `from_env(cls)`
    - `observe(self)`
    - `_prompt(self)`
    - `_schema(self)`
    - `_log(self, level, msg)`

## `runtime/session_turn_ledger.py`
- LOC: 142
- Classes:
  - `SessionTurn` (decorator=dataclass(frozen=True)) — Một lượt public trong phiên. Đây là raw ledger dùng để đếm/lấy exact trong phiên hiện tại. Không được coi nó là long-term memory. Không ai m...
  - `SessionTurnLedger` — Ledger deterministic cho câu hỏi về thứ tự, số lượng, câu dài nhất.
    - `__init__(self)`
    - `record_user(self, text)`
    - `record_assistant(self, text)`
    - `_record(self, role, text)`
    - `all_turns(self)`
    - `turns_by_role(self, role)`
    - `user_turns(self)`
    - `assistant_turns(self)`
    - `user_questions(self)`
    - `nth_user_turn(self, ordinal)`
    - `nth_assistant_turn(self, ordinal)`
    - `nth_user_question(self, ordinal)`
    - `count_user_questions(self)`
    - `longest_user_question(self)`
    - `gist_recent_user_topics(self)` — Sinh gist rất nhẹ từ user turns gần đây. Đây không thay MeaningLayer. Nó chỉ dùng khi user hỏi “nhớ...
    - `_nth(items, ordinal)`
    - `_unique_keep_order(items)`

## `runtime/shadow_pipeline.py`
- LOC: 377
- Docstring: runtime/shadow_pipeline.py Shadow mode cho CognitivePipeline (V3). Ý tưởng: Runtime thật vẫn chạy frame cũ (cortex/contracts.CognitiveFrame) qua coordinator/chat_cycle như thường. Song song đó, ta dựng RawSignal từ ĐÚNG cùng input (user_text, snapshot, vision_...
- Classes:
  - `ShadowPipelineMixin` — Trộn vào RuntimeCoordinator để chạy V3 pipeline ở chế độ shadow.
    - `_shadow_pipeline_enabled(self)`
    - `_get_shadow_pipeline(self)`
    - `_v3_promoted_paths(self)` — Tập path V3 được phép ghi đè frame cũ. Nguồn: attr `self.v3_promoted_paths` (set/iterable/str) hoặc...
    - `_promote_v3_paths(self, result)` — Ghi quyết định V3 lên frame cũ cho các path đã bật. Không bao giờ raise. Trả dict audit (path -> giá...
    - `_set_frame_attr(frame, name, value)`
    - `_set_frame_metadata(self, frame, key, value)`
    - `_record_frame_note(frame, note)`
    - `_run_shadow_cognitive_pipeline(self)` — Chạy V3 pipeline shadow và so trace với frame cũ. Trả PipelineResult nếu chạy được, None nếu tắt hoặ...
    - `_build_shadow_raw_signals(self)`
    - `_snap(snapshot, names, default)`
    - `_shadow_idle_seconds(self, snapshot)`
    - `_safe_render_trace(frame)`
    - `_compare_traces(self)`
    - `_focus_overlap(a, b)` — Jaccard token nhẹ giữa hai focus, chỉ để cảm nhận độ trùng.
    - `_log_shadow_comparison(self, comparison, v3_trace, old_trace)`

## `runtime/signal_buffer.py`
- LOC: 325
- Docstring: SignalBuffer cho Background Observer. Nhiệm vụ: - Giữ một cửa sổ snapshot gần đây. - Tính diff giữa snapshot mới và snapshot trước. - Ước lượng novelty/repetition mà không gọi model. - Làm cổng chống spam model.
- Classes:
  - `SignalBufferConfig` (decorator=dataclass)
  - `SignalBufferStats` (decorator=dataclass)
  - `SignalBuffer` — Bộ nhớ ngắn hạn cho signal nền. Đây là hàng rào đầu tiên để ERIS không gọi model vì mọi cú chớp của desktop.
    - `__init__(self, config)`
    - `items(self)`
    - `last(self)`
    - `last_diff(self)`
    - `push(self, snapshot)` — Thêm snapshot và trả diff so với snapshot trước.
    - `diff(self, current, previous)`
    - `stats(self)`
    - `recent(self, n)`
    - `recent_summary(self, n)` — Tóm tắt ngắn cho LLM observer nếu cần.
    - `should_run_text_observer(self, diff)` — Cổng gọi model nhỏ. Rule buffer này chỉ nói `có đáng gọi không`, không gọi model trực tiếp.
    - `_cooldown_ready(self, cooldown_seconds)`
    - `_repetition_score(self, current)`
    - `_count_recent_hash(self, getter, value)`
    - `_count_in(items, getter, value)`
    - `_norm(text)`
    - `_text_similarity(a, b)`
    - `_event_similarity(cls, a, b)`
    - `_idle_bucket(idle_seconds)`

## `runtime/source_grounding.py`
- LOC: 1953
- Classes:
  - `SourceCandidate` (decorator=dataclass(slots=True)) — Một nguồn có thể dùng để trả lời. confidence ở đây là confidence của quyền dùng nguồn, không phải confidence của câu trả lời cuối. Ví dụ: us...
    - `to_dict(self)`
  - `SourceFallbackDecision` (decorator=dataclass(slots=True)) — Compatibility signal khi thiếu evidence. Lớp này từng chứa câu fallback public. Bản mới giữ field `text` để không phá caller cũ, nhưng Sourc...
    - `to_payload(self)`
    - `to_runtime_decision(self)` — Cố chuyển sang domain.Decision nếu repo có class này. Nếu không import được, trả payload dict. Đừng...
  - `MemoryAnswerProfile` (decorator=dataclass(slots=True)) — Semantic policy for memory/history questions. This is deliberately a profile, not a fallback sentence. The LLM still words the answer, while...
    - `active(self)`
    - `apply_cap(self, raw_confidence)`
  - `SourceGroundingReport` (decorator=dataclass(slots=True)) — Báo cáo grounding nguồn cho một turn. primary_source: Nguồn chính LLM được phép dựa vào. confidence_cap: Trần confidence cho output cuối. LL...
    - `should_fallback(self)`
    - `should_preempt_llm(self)`
    - `max_confidence(self)`
    - `apply_cap(self, raw_confidence)`
    - `to_dict(self)`
  - `ClaimAnnotation` (decorator=dataclass(slots=True)) — Nhãn cho một mệnh đề bề mặt (Task 8 / R8.1). `claim_status` phản ánh GROUNDING NỘI TẠI — sự thật ERIS nắm — và KHÔNG đổi theo quan hệ/đăng k...
    - `to_dict(self)`
  - `SourceGroundingEngine` — Bộ phân loại grounding nguồn cho runtime. Cách dùng tối thiểu: report = SourceGroundingEngine().analyze(user_text, frame=frame) frame.source...
    - `analyze(self, user_text)` — Phân tích nguồn trả lời chính. Parameters ---------- user_text: Text user gửi trong turn hiện tại. f...
    - `classify(self)`
    - `analyze_frame(self, frame)` — Helper khi caller chỉ có frame. Cố lấy user_text từ percepts/final input của frame.
    - `apply_confidence_cap(self, raw_confidence, report_or_frame)` — Cap confidence ngoài pipeline. Có thể truyền SourceGroundingReport hoặc frame có `source_grounding`.
    - `should_preempt(self, report_or_frame)`
    - `render_prompt_context(self, report)` — Tạo prompt context ngắn cho LLM. Context này không phải văn phong. Nó là giới hạn nhận thức: LLM đượ...
    - `annotate_claims(self, text)` — Gắn nhãn từng mệnh đề thay vì viết-lại/bóp câu (Task 8 / R8.1, R8.2). Đây là chế độ ANNOTATE: không...
    - `_is_epistemic_curiosity_gap(self, report)` — Thiếu evidence nhưng còn đủ neo để hỏi/thăm dò thay vì trả payload chết. Đây là ranh giới chống đánh...
    - `build_fallback_decision(self, report)` — Tạo signal khi nguồn user yêu cầu chưa có evidence. Bản cũ sinh text public ở đây, rồi `post_generat...
    - `build_preemptive_reply(self, report)` — Deprecated compatibility hook. SourceGroundingEngine không còn sinh text public. Caller cũ có thể vẫ...
    - `_derive_memory_answer_profile(self)` — Infer the memory/history answer shape for this turn. This does not produce a fallback sentence. It p...
    - `_split_grounding_clauses(self, text)` — Tách mệnh đề rất nhẹ cho source grounding. Đây không phải parser cú pháp. Nó chỉ ngăn lỗi kiến trúc:...
    - `_is_self_disclosure_clause(self, clause)` — Nhận diện mệnh đề user tự khai báo fact/preference/profile. Hàm này nằm ở source grounding nên chỉ t...
    - `_looks_like_question(self, normalized)`
    - `_has_actionable_web_reference(self, normalized, raw_text)` — Chỉ route web khi user thật sự đòi dữ liệu hiện tại. Marker thời gian đơn độc như "hôm nay" chỉ là n...
    - `_choose_primary_source(self, candidates)` — Chọn nguồn chính. Ưu tiên nguồn trực tiếp và ít suy diễn hơn. Nếu nguồn user yêu cầu bị thiếu eviden...
    - `_cap_for(self, primary)`
    - `_derive_missing_evidence(self, primary, candidates)`
    - `_derive_forbidden_assumptions(self)`
    - `_derive_answer_style_rules(self, primary)`
    - `_derive_preempt_mode(self)`
    - `_detect_file_mentions(self, text, normalized)`
    - `_detect_explicit_screen_request(self, normalized)` — True chỉ khi user TƯỜNG MINH nhắc màn hình hoặc ra lệnh nhìn/xem. Đây là tín hiệu duy nhất được phép...
    - `_has_deictic_reference(self, normalized)` — True khi có đại từ chỉ định trần ("cái này", "lỗi này"...). Tín hiệu này chỉ dùng để bind referent v...
    - `_looks_like_file_content_request(self, normalized)`
    - `_detect_pasted_code(self, text)`
    - `_guess_code_language(self, text)`
    - `_collect_file_evidence(self)`
    - `_collect_screen_evidence(self)`
    - `_collect_memory_evidence(self)`
    - `_collect_user_text_evidence(self)`
    - `_summarize_evidence_items(self, items)`
    - `_preview_item(self, item)`
    - `_extract_user_text_from_frame(self, frame)`
    - `_mapping_get(obj, key, default)`
    - `_read_float(obj, key)`
    - `_normalize(cls, text)`
    - `_has_any(cls, normalized_text, markers)`
    - `_as_list(value)`
    - `_dedupe(items)`
    - `_safe_setattr(obj, key, value)`
    - `_clamp01(value)`

## `runtime/speech_pipeline.py`
- LOC: 79
- Classes:
  - `SpeechIntentDecision` (decorator=dataclass(frozen=True, slots=True))
  - `SpeechPipelineMixin` — Shared finalization path for public speech decisions. Trước đây chat/autonomous/force_speak/presence tự gọi Ti/filter theo các đường riêng....
    - `_finalize_speech_decision(self, decision)`

## `runtime/state_commit_service.py`
- LOC: 872
- Functions:
  - `_is_nonsemantic_fallback_decision(decision)` — True nếu decision chỉ là fallback kỹ thuật, không phải answer nội dung. Chú thích kiến trúc: public_turn có thể ghi để u...
- Classes:
  - `StateCommitServiceMixin`
    - `_memory_kernel(self)`
    - `_ensure_session_turn_ledger(self)`
    - `_ensure_memory_commit_policy(self)`
    - `_ensure_memory_fast_commit_policy(self)` — Policy nóng không gọi model semantic parser. Khi background memory digest đang bật, hot path chỉ nên...
    - `_background_memory_digest_enabled(self)`
    - `_enqueue_background_memory_digest(self, user_text)`
    - `_set_background_memory_digest_remote_inflight(self, inflight)`
    - `_memory_snapshot_for_lookup(self)`
    - `_memory_snapshot_items(self, snapshot, collection_name)`
    - `_record_value(record, field_name, default)`
    - `_record_metadata(self, record)`
    - `_clean_memory_value(value)`
    - `_extract_semantic_value_from_record(self, record, kind)`
    - `_semantic_memory_lookup(self, kind)`
    - `_fact_key_for_memory_kind(kind)`
    - `_semantic_record_rank(self, record)`
    - `_episodic_memory_lookup(self, query)`
    - `_ensure_memory_recall_adapter(self)`
    - `_build_memory_recall_decision(self, user_text)`
    - `_ensure_relational_voice_seed_adapter(self)`
    - `_ensure_affect_self_read_adapter(self)`
    - `_frame_memory_storage_permission(self, frame)`
    - `_user_turn_memory_evidence_id(self)`
    - `_ingest_user_turn_via_memory_kernel(self, frame, user_text)`
    - `_add_user_turn_memory_commit_requests(self, frame, user_text)`
    - `_load_memory_state(self)`
    - `_has_structured_memory_core(self)`
    - `_ensure_internal_state(self)`
    - `_get_internal_state(self)`
    - `_set_internal_state(self, state)`
    - `_load_internal_state_payload(self)`
    - `_send_decision_to_body(self, decision)`
    - `_record_public_turn(self, decision)`
    - `_build_body_bias_payload(self)`
    - `_body_bias_clamp(value)`
    - `_normalize_body_focus_kind(value)`
    - `_save_memory_state(self)`
    - `_memory_recall_packet(self)` — Recall structured packet, không flatten quá sớm. PDF/Tongquat tách episodic/semantic/procedural vì m...
    - `_memory_recall_texts(self)`
    - `_recall_memory_resonance(self)`
    - `_memory_attention_lines(self)`
    - `_norm_deviation_texts(self, snapshot)`
    - `_note_norm_observation(self, snapshot)`
    - `_memory_query_from_snapshot(self, snapshot)`
    - `_event_timestamp(self, snapshot)`
    - `_commit_chat_decision(self, decision, fe_plan)`
    - `_apply_position_update(self, decision)`
    - `_build_silent_motion_decision(self, ti_report)`
    - `_build_direct_action_decision(self, user_text, ti_report, snapshot)`
    - `_execute_system_action(self, decision)`
    - `_action_animation_hint(self, action_name, fallback)`
    - `_action_result_to_text(self, result)`
    - `_resolve_now_playing_text(self, snapshot)`
    - `_extract_media_title_from_snapshot(self, snapshot)`
    - `_extract_media_title(self, raw_title)`

## `runtime/state_committer.py`
- LOC: 1110
- Docstring: src/runtime/state_committer.py ================================ StateCommitter là cổng commit state/memory của ERIS. Nguyên tắc chính: - Không module runtime nào được ghi thẳng vào memory. - Module chỉ được tạo StateCommitRequest. - StateCommitter kiểm tra quy...
- Functions:
  - `_safe_float(value, default)`
  - `_safe_bool(value, default)`
  - `_as_list_str(value)`
  - `_get(obj, name, default)` — Đọc field từ dict/object/dataclass mà không kén kiểu. Dùng helper này để file không gãy khi Ngài đổi contract một chút....
  - `_set_if_possible(obj, name, value)`
  - `_content_is_empty(content)`
  - `_normalize_target(target)`
  - `_normalize_decay_policy(value)`
  - `_request_metadata(req)`
  - `_request_tags(req)`
- Classes:
  - `StateCommitterConfig` (decorator=dataclass(slots=True)) — Cấu hình ngưỡng commit. Giữ ở dataclass để sau này Ngài tune bằng config/env thay vì rải magic number. Magic number là cách người ta biến co...
  - `CommitValidationIssue` (decorator=dataclass(slots=True)) — Một vấn đề phát hiện trong quá trình validate.
    - `to_dict(self)`
  - `CommitDecision` (decorator=dataclass(slots=True)) — Kết quả kiểm định một request. `normalized_request` là request đã được chuẩn hóa/reroute/đánh tentative nếu cần. Nếu `accepted=False`, tuyệt...
    - `to_dict(self)`
  - `CommitBatchReport` (decorator=dataclass(slots=True)) — Audit report cho một lần StateCommitter.commit(...).
    - `duration_ms(self)`
    - `finish(self)`
    - `to_dict(self)`
  - `StateCommitter` — Cổng commit chính cho runtime. Usage chuẩn trong CognitiveRuntime: self.state_committer = StateCommitter(self.memory_cognition) ... self.sta...
    - `__init__(self, memory_cognition)`
    - `commit(self, frame_or_requests)` — Validate rồi commit batch request. Tham số: - frame_or_requests: + CognitiveFrame có `.commit_reques...
    - `commit_frame(self, frame)` — Alias rõ nghĩa cho coordinator thích gọi tên dài.
    - `commit_requests(self, requests)` — Alias khi caller đã có list StateCommitRequest.
    - `validate(self, request)` — Kiểm định một StateCommitRequest nhưng chưa ghi memory. Đây là nơi enforce các luật: - không có quyề...
    - `_commit_one(self, decision, frame)` — Gọi MemoryCognitionCore.commit(...) với request đã validate.
    - `_call_memory_commit(self, request)` — Gọi memory core bằng nhiều signature phổ biến. Lý do phải mềm: - nhánh này có thể đang dùng `commit(...
    - `_extract_requests(self, frame_or_requests)`
    - `_maybe_frame(self, value)`
    - `_looks_like_commit_request(self, value)`
    - `_clone_request(self, request)` — Clone request nhưng giữ class gốc nếu có thể. Điều này giúp tương thích với MemoryCognitionCore nếu...
    - `_build_evidence_index(self, frame)`
    - `_contains_private_raw_evidence(self, request, evidence_ids, evidence_index)`
    - `_semantic_grounding_issue(self)`
    - `_frame_permission_flag(self, frame, field_name)`
    - `_looks_like_user_correction(self, request, content, reason, tags, metadata)`
    - `_confidence_thresholds(self, target)`
    - `_attach_report_to_frame(self, frame, report)`
    - `_frame_id(self, frame)`
    - `_dedup_key(self, request)`

## `runtime/subconscious_loop.py`
- LOC: 412
- Docstring: Runtime adapter cho subconscious blackboard/synthesizer. Phase 0 dựng ThoughtFragment/Blackboard/Synthesizer. Phase 1-4 thêm worker nội tâm nền. Phase 5 thêm MetaAudit có quyền dọn Blackboard. Phase 6 thêm BeliefMutation proposal + commit gate có rollback. Pha...
- Classes:
  - `SubconsciousTickResult` (decorator=dataclass(slots=True, frozen=True)) — Kết quả một tick subconscious.
    - `to_dict(self)`
  - `SubconsciousLoop` — Vòng nền tối thiểu cho worker subconscious. Loop này không tự quyết định nói. Nó sinh `ThoughtObject`, `surface_seed`, và `audit_report`. Su...
    - `__init__(self)`
    - `submit(self, fragment)` — Submit thủ công một fragment vào Blackboard.
    - `tick(self)` — Chạy một lượt worker -> audit -> synthesizer -> post-worker -> audit.
    - `latest_report(self)`
    - `_inner_court_report_payload(self)` — Expose Lane 3 API synthesis report cho debug/audit nội bộ.
    - `pop_surface(self)`
    - `stop(self)`
    - `_context_with_snapshot(self)` — Tạo WorkerContext có snapshot Blackboard bất biến.
    - `_run_workers(self, context)` — Chạy nhóm worker phù hợp với pass hiện tại và submit fragment. Worker lỗi bị cô lập. MetaAudit sẽ bắ...
    - `_run_audit_workers(self, context)` — Chạy các worker audit có quyền mutate Blackboard.
    - `_compose_report(self, thought_object, surface_seed)`
    - `_surface_from_seed(self, surface_seed, thought_object)`

## `runtime/subconscious_model_adapter.py`
- LOC: 334
- Docstring: Adapter gọi model/API riêng cho Lane 3 subconscious synthesis. Lane 3 không sinh lời thoại public. Nó chỉ lập một "biên bản phiên toà nội tâm": - các mảnh nào đang tranh nhau ý nghĩa, - bên công tố/biện hộ nhìn thấy gì, - thẩm phán kết luận ThoughtObject nào đ...
- Functions:
  - `_env_flag(name, default)`
  - `_as_float(value, default)`
  - `_cfg_flag(path, default)`
- Classes:
  - `SubconsciousModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True)) — Cấu hình riêng cho Lane 3 API synthesis. Ưu tiên cấu hình: 1. Env ERIS_LANE3_* 2. config/secrets.json -> agent_keys.lane3_synthesis 3. confi...
  - `SubconsciousModelResult` (decorator=dataclass(slots=True, frozen=True))
  - `RuntimeSubconsciousModelAdapter` — Client mỏng cho Lane 3. Không dùng để trả lời user. Không được gọi từ public speech path trực tiếp. Nó chỉ trả JSON riêng tư cho ModelBacked...
    - `__init__(self)`
    - `from_env(cls)`
    - `synthesize(self, messages)` — Gọi provider và parse JSON object.
    - `_resolve_profile(self)`
    - `_resolve_model(self)`
    - `_resolve_base_url(self)`
    - `_resolve_api_key(self)`
    - `_build_client(self)`
    - `_extract_content(self, raw)`
    - `_parse_json_object(self, text)`
    - `_safe_raw(self, raw)`
    - `_log(self, level, msg)`

## `runtime/text_repeat_guard.py`
- LOC: 154
- Classes:
  - `TextRepeatGuardMixin`
    - `_is_near_duplicate_text(self, text, other)`
    - `_recent_spoken_texts(self)`
    - `_recent_spoken_entries(self)`
    - `_force_speak_banned_family_for_text(self, text)`
    - `_looks_like_poetic_fallback_text(self, text)`
    - `_repeated_force_speak_banned_family(self, text)`

## `runtime/thought_model_adapter.py`
- LOC: 84
- Docstring: runtime/thought_model_adapter.py ================================ Compatibility adapter cho ThoughtStream model review. Một số bản coordinator đã import RuntimeThoughtModelAdapter nhưng zip hiện tại không có file này. Thiếu file import làm toàn bộ runtime chết...
- Functions:
  - `_env_flag(name, default)`
- Classes:
  - `ThoughtModelAdapterConfig` (decorator=dataclass(slots=True, frozen=True))
  - `RuntimeThoughtModelAdapter`
    - `__init__(self)`
    - `from_env(cls)`
    - `review(self, payload)` — Trả schema ThoughtStream đang mong đợi. Không có prompt riêng phức tạp ở đây để tránh hai hệ private...

## `runtime/voice_policy.py`
- LOC: 176
- Docstring: voice_policy.py — Nguồn sự thật DUY NHẤT cho giọng/persona của ERIS. Trước đây "register cấm" (giọng trợ lý help-desk / "tôi là AI" / chối phẳng cảm xúc) được định nghĩa LẶP ở nhiều nơi, mỗi nơi viết lại bằng một dạng văn bản khác: * ``runtime/disclaimer_marke...
- Functions:
  - `normalize_guard_ascii(text)`
  - `is_disclaimer_text(text)` — Flag-agnostic check: hard + helper markers (the helpdesk register). Giữ y hệt semantics cũ (``_reroll_still_disclaimer``...
- Classes:
  - `VoicePolicy` (decorator=dataclass(frozen=True)) — Nguồn canonical: 3 đầu ra cho 3 nơi tiêu thụ, không nơi nào tự định nghĩa lại.
    - `forbidden_markers(self, category)`
    - `is_disclaimer(self, text)`
    - `normalize(self, text)`
    - `render_prompt_constraint(self)`
    - `render_anti_disclaimer_fewshot(self)`
    - `render_reroll_clause(self)`

## `sender.py`
- LOC: 26

## `telemetry/__init__.py`
- LOC: 12

## `telemetry/content_metadata.py`
- LOC: 609
- Docstring: Thu thập metadata nội dung đang nhìn thấy cho SeLens. Mục tiêu của file này không phải "đọc màn hình như tiên tri". Nó chỉ gom các fact có nguồn rõ ràng theo thang L0-L5 rồi trả về dict nhỏ để SeLens tự quyết confidence. Nếu nguồn không có, trả rỗng. Không đượ...
- Functions:
  - `_candidate_cache_paths(env_name, filename)`
  - `_pick_matching_url(candidates, current_url)`
  - `_infer_page_kind()`
  - `_normalize_hashtags(value)`
  - `_normalize_media_state(value)`
  - `_clean_text(value, limit)`
  - `_dedupe_join(values)`
  - `_choose_longer(left, right)`
  - `_text_overlap(left, right)`
  - `_tokenize(value)`
  - `_domain_from_url(url)`
  - `_domain_matches(domain, expected_domains)`
  - `_coerce_float(value, default)`
  - `_env_bool(name, default)`
  - `_env_int(name, default)`
  - `_env_float(name, default)`
- Classes:
  - `ContentMetadata` (decorator=dataclass(slots=True)) — Fact thô về nội dung foreground. Ghi chú tiếng Việt cho tương lai: - `source` là nguồn mạnh nhất đang có, không phải mọi nguồn đã thử. - `ti...
    - `to_dict(self)`
  - `ContentMetadataCollector` — Best-effort collector cho metadata nội dung foreground. Luồng ưu tiên: 1. DOM bridge cache do extension/local bridge ghi ra. Mạnh nhất. 2. A...
    - `__init__(self)`
    - `collect(self)`
    - `_merge_sources(self)`
    - `_read_dom_bridge(self)`
    - `_read_media_session_cache(self)` — Đọc cache now-playing nếu module khác ghi được Media Session/SMTC. Python thuần đọc GlobalSystemMedi...
    - `_read_ocr_cache(self)`
    - `_read_accessibility_text(self)`
    - `_from_browser_or_window_title(self)`
    - `_read_fresh_json(self, paths)`
    - `_privacy_level(self)`

## `telemetry/service.py`
- LOC: 62
- Classes:
  - `TelemetryService` (base=TelemetryMixin)
    - `__init__(self)`
    - `capture_snapshot(self)`
    - `format_snapshot(self, snapshot)`
    - `format_directive_snapshot(self, snapshot)`
    - `capture_machine_context(self)`
    - `get_system_telemetry(self)`
    - `capture_screen_frame_data_uri(self)`

## `telemetry/system.py`
- LOC: 235
- Functions:
  - `_ensure_com_initialized()`
- Classes:
  - `TelemetryMixin`
    - `_get_content_metadata_collector(self)`
    - `_get_browser_telemetry_uia(self)`
    - `_get_all_windows(self)`
    - `_get_idle_seconds(self)`
    - `capture_raw_telemetry(self)`
    - `get_system_telemetry(self)`

## `transport/__init__.py`
- LOC: 4

## `transport/udp.py`
- LOC: 249
- Functions:
  - `_compact_private_mind_for_udp_overflow(value)`
  - `_compact_inner_diary(diary)` — Compact inner_diary giữ nguyên sections/items để C# có thể parse đúng.
  - `_slim_private_mind_core(private_mind)` — Bản rút gọn cứng của private_mind_digest. Chỉ giữ đúng thứ UI cần để vẽ Inner Diary (current_thought / future_bias / ope...
  - `_compact_debug_value(value)`
  - `_compact_scalar(value, limit)`
- Classes:
  - `UdpTransport`
    - `__init__(self, send_host, send_port, recv_host, recv_port)`
    - `send_text(self, message)`
    - `send_json(self, payload)`
    - `poll_json(self)`
    - `close(self)`

## `vision.py`
- LOC: 240
- Classes:
  - `AttentionOverseer`
    - `__init__(self, model_path, n_ctx, n_gpu_layers)`
    - `_is_body_running(self)`
    - `stop(self, reason)`
    - `run_loop(self)`
  - `SingleInstanceLock`
    - `__init__(self, lock_path)`
    - `acquire(self)`
    - `release(self)`

# 11. Kết luận kiến trúc hiện tại

Quan sát -> Tín hiệu mạnh -> Giả thuyết mạnh nhất -> Mức tự tin -> Giả thuyết cạnh tranh:

- Quan sát: repo hiện tại có runtime Python lớn, nhiều module stateful, private_mind/private_life/thought_stream/surface/memory đều đã có file thật và wiring qua coordinator.
- Tín hiệu mạnh: `runtime/coordinator.py` nối daemon, wake governor, model budget, surface arbiter, memory kernel; `cortex/private_mind/*` có concern/mutation/surface valve; `cortex/private_life/*` có state đời sống riêng; `memory/*` có query IR và multi-layer store.
- Giả thuyết mạnh nhất: ERIS hiện không còn là chatbot prompt-only; nó là runtime agent stateful với nhiều substrate nhận thức, nhưng vẫn đang lệ thuộc vào coordinator lớn và policy/gate phức tạp.
- Mức tự tin: 0.88 dựa trên AST + docstring + file wiring trong zip.
- Giả thuyết cạnh tranh: nếu body/Godot/tests nằm ngoài zip thì tài liệu này chưa phản ánh hết runtime thật; nếu một số module có docstring tham vọng hơn logic bên trong thì cần audit dòng-level riêng cho module đó.
