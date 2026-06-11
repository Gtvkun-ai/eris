# ERIS — TÀI LIỆU CHI TIẾT (file-to-file, từng hàm) để DEBUG

> Tài liệu này đi sâu tới TỪNG FILE và TỪNG HÀM. Đọc kèm `tongquat.txt` (bản đồ
> tổng quát + playbook debug). Cập nhật: 2026-06-11.
>
> Quy ước trình bày mỗi file:
> - **Vai trò**: file làm gì.
> - **Class/struct**: các kiểu chính.
> - **Hàm**: liệt kê đầy đủ, dạng `tên(tham số)` — mô tả: làm gì / input / output / side effect.
> - **Liên kết**: gọi ai / được ai gọi / UDP.
>
> Mục lục:
> 1. BODY (Godot/C#) — thư mục `body/`
> 2. SRC ROOT + CORE + DOMAIN + TRANSPORT
> 3. LLM
> 4. RUNTIME (coordinator + mixin + daemon)
> 5. CORTEX (các tầng nhận thức)
> 6. MEMORY (trí nhớ)
> 7. ACTIONS / PARSER_GROUNDING / TELEMETRY

================================================================================
# PHẦN 1 — BODY (Godot / C#)  [thư mục body/]
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
# PHẦN 2 — SRC ROOT + CORE + DOMAIN + TRANSPORT
================================================================================

--------------------------------------------------------------------------------
## src/vision.py  (ENTRY POINT runtime)
--------------------------------------------------------------------------------
**Vai trò:** Điểm vào của tiến trình Python. Dựng toàn bộ hạ tầng nhận thức rồi chạy
vòng lặp. Có khoá single-instance.

**Class:** `AttentionOverseer` (chủ sở hữu mọi engine), `SingleInstanceLock`.

**Các hàm/method (đầy đủ):**
- `AttentionOverseer.__init__(model_path, n_ctx, n_gpu_layers)` — đọc env remote; tạo
  `RemoteModelProcessManager` -> build client chính/style/vision/fallback; tạo `LlmService`;
  build `memory_semantic_parser`; tạo `UdpTransport(4242 gửi,4243 nhận)`; tạo
  `MemoryCognitionCore` + load ký ức; tạo `DecisionParser`, `TelemetryService`, `NiEngine`,
  `TiGovernor`, `FeRenderer`, `ActionExecutor`, `ActionRouter`; tạo `RuntimeCoordinator`
  và nạp memory_state + long_term_memory.
- `AttentionOverseer._is_body_running()` — chạy `tasklist` xem Godot/Eris còn sống không.
- `AttentionOverseer.stop(reason)` — dừng coordinator + process_manager.
- `AttentionOverseer.run_loop()` — gọi `coordinator.run_loop()`.
- `SingleInstanceLock.__init__(lock_path)` / `acquire()` / `release()` — khoá `.vision.lock`
  bằng `msvcrt.locking`; chống chạy 2 tiến trình; ghi PID.
- `__main__` (block) — configure_logging; acquire lock; đọc argv model_path; kiểm tra
  ERIS_REMOTE_API_ENABLED; đọc ERIS_N_CTX; tạo overseer; bắt SIGINT/SIGTERM/SIGBREAK;
  chạy run_loop; finally stop + release.

**Liên kết:** Spawn bởi `body/ErisProcessManager`. Tạo `RuntimeCoordinator` (runtime/coordinator.py).

--------------------------------------------------------------------------------
## src/app_logging.py
--------------------------------------------------------------------------------
**Vai trò:** Cấu hình logging có "category" (tên mạch: Vision/Memory/LLM/Loop/...).
**Các hàm:**
- `CategoryFormatter.format(record)` — gắn `category` mặc định = name rồi format `[cat][LEVEL] msg`.
- `configure_logging(level=INFO)` — gắn StreamHandler ra stdout với CategoryFormatter, clear handler cũ.
- `get_logger(category)` — trả `LoggerAdapter` gắn sẵn category.
**Liên kết:** Dùng khắp runtime; tên category quyết định prefix log mà body lọc để hiển thị.

--------------------------------------------------------------------------------
## src/eris_secrets.py
--------------------------------------------------------------------------------
**Vai trò:** Đọc cấu hình/secret từ env + `config/secrets.json` (env ưu tiên). Hỗ trợ
key lồng nhau, provider profile theo slot, agent profile.
**Các hàm:**
- `_resolve_secrets_path()` — tìm secrets.json (ưu tiên ERIS_PROJECT_ROOT cho bản export).
- `_load_secrets()` (lru_cache) — đọc & cache secrets.json thành dict.
- `_lookup(payload, name)` — tìm key ở top-level hoặc trong section api_keys/env/secrets.
- `_lookup_path(payload, path, default)` — đọc key lồng theo "a.b.c".
- `_provider_slot_payload(payload, provider, slot)` — lấy profile providers.<provider>.<slot>.
- `get_secret(*names, default)` — lấy secret đầu tiên có giá trị (env trước, rồi secrets).
- `get_config(path, default)` — đọc config từ env hoặc secrets (hỗ trợ path lồng).
- `get_provider_profile(provider, slot, default)` — lấy cấu hình provider theo slot.
- `get_agent_profile(agent_name, ...)` — resolve provider/slot cho 1 job/agent cụ thể.
- `apply_secrets_to_environ()` — đổ các secret string vào os.environ nếu chưa có.
**Liên kết:** Dùng bởi llm/*, runtime/* (cấu hình model/budget/flag).

--------------------------------------------------------------------------------
## src/guard_config.py
--------------------------------------------------------------------------------
**Vai trò:** Công tắc chế độ "guard" (strict/self_clamp/log_only/off) và cờ warn-only.
**Hằng:** ERIS_GUARD_MODE, STRICT/SELF_CLAMP/LOG_ONLY/OFF_GUARD_MODE, VALID_GUARD_MODES.
**Các hàm:**
- `guards_warn_only()` — true nếu ERIS_GUARDS_WARN_ONLY bật (guard quan hệ/giọng chỉ cảnh báo, không chặn).
- `get_guard_mode(name=None)` — trả mode hiện hành; warn-only -> log_only; hỗ trợ override per-rule qua env.
**Liên kết:** Dùng bởi các tầng guard ở cortex/runtime (surface, micro_policy, disclosure...).

--------------------------------------------------------------------------------
## src/domain/decision.py
--------------------------------------------------------------------------------
**Vai trò:** Dataclass `Decision` — đơn vị "quyết định" cortex gửi xuống body.
**Field chính:** text, animation, extracted_fact, intent, action, reasoning_tags,
should_speak, confidence, direction, next_animation, target_x, bounce_action,
debug_trace, parser_trace, parse_mode, system_action, action_input, motion_intent,
motion_target_x, motion_facing.
**Các hàm/method:**
- `resolve_motion_intent()` — suy motion_intent từ animation/next/target/direction nếu chưa set.
- `resolve_motion_target_x()` — chọn motion_target_x hợp lệ (motion_target_x rồi tới target_x).
- `resolve_motion_facing()` — suy hướng (-1/1) từ motion_facing/direction/animation.
- `_payload_text()` (private) — lọc text rỗng/filler ("...", "hm", "um") -> ("", False).
- `to_payload()` — đóng gói dict JSON gửi qua UDP 4242 (gồm các motion_* đã resolve).
**Liên kết:** Sinh bởi parser_grounding + coordinator; serialize qua transport.send_json; parse lại ở UdpDecisionParser.cs.

--------------------------------------------------------------------------------
## src/core/evidence.py
--------------------------------------------------------------------------------
**Vai trò:** Định nghĩa `RawSignal` (tín hiệu thô) và `EvidenceItem` (claim đã chuẩn hoá),
`ModuleReport`, `StateCommitRequest`, `DebugTrace` — contract nền của pipeline V3.
**Các hàm/class:**
- `now_timestamp()` — Unix timestamp.
- `normalize_signal_source(source)` — chuẩn hoá source về tập hợp lệ.
- `normalize_privacy_level(level)` — public/normal/private/sensitive.
- `clamp_reliability(value)` — ép [0,1].
- `make_signal_id(source, timestamp)` — id ổn định để trace trong EventLedger.
- `class RawSignalValidationError(ValueError)` — lỗi dữ liệu RawSignal.
- `class RawSignal` (frozen dataclass) — tín hiệu thô. Method/classmethod:
  - `__post_init__()` — validate + chuẩn hoá.
  - `create(...)`, `from_chat(text)`, `from_active_window(...)`, `from_browser(...)`,
    `from_telemetry(...)`, `from_vision(facts)`, `from_ocr(text)`, `from_body(state)`,
    `from_system_log(msg)`, `from_memory(payload)`, `from_time(payload)`, `from_dict(data)`
    — các factory tạo RawSignal theo nguồn.
  - `with_reliability(r)` / `with_privacy(level)` — trả bản sao đổi field.
  - property `is_private` / `is_sensitive` / `is_low_reliability`.
  - `summarize_content(max_length)` — tóm tắt ngắn để debug.
  - `to_dict()` / `to_safe_debug_dict()` / `to_json()` — serialize (bản an toàn không dump private).
- `class EvidenceItem` (frozen dataclass) — claim chuẩn hoá. Method: `__post_init__`,
  `from_raw_signal(signal)`, property `is_private`, `to_dict()`.
- `class ModuleReport` — kết quả chuẩn 1 module ghi vào frame. Method: `__post_init__`, `to_dict()`.
- `class StateCommitRequest` — yêu cầu ghi state/memory sau guard. Method: `__post_init__`, `to_dict()`.
- `class DebugTrace` — trace nhẹ. Method: `add(actor,event,data)`, `to_dict()`.
- `raw_signal(source, content, ...)` — shortcut tạo RawSignal.
**Liên kết:** Nền của `cognitive_frame`, `evidence_normalizer`, toàn pipeline.

--------------------------------------------------------------------------------
## src/core/evidence_normalizer.py
--------------------------------------------------------------------------------
**Vai trò:** Chuyển `RawSignal` -> `EvidenceItem` theo contract.
**Các hàm/class:**
- `class EvidenceNormalizerConfig` — cấu hình (max_claim_chars, skip_empty_claim, user_chat_confidence_floor...).
- `class NormalizationResult` — kết quả (evidence + số liệu debug); property `count`, `to_dict()`.
- `class EvidenceNormalizer`:
  - `__init__(config)`.
  - `normalize(signals)` — loạt RawSignal -> NormalizationResult.
  - `normalize_into_frame(frame)` — đọc frame.raw_signals, sinh evidence, add vào frame.
  - `_to_evidence(signal)` (private) — 1 RawSignal -> EvidenceItem.
  - `_initial_confidence(signal)` (private) — confidence khởi đầu (user_chat có sàn).
  - `_tags_for(source)` (private) — tag theo nguồn.
- `normalize_signals(signals)` — shortcut hàm thuần.
**Liên kết:** Bước 0 của `runtime/cognitive_pipeline.py`.

--------------------------------------------------------------------------------
## src/core/cognitive_frame.py
--------------------------------------------------------------------------------
**Vai trò:** `CognitiveFrame` — khung nhận thức đầy đủ của MỘT chu kỳ runtime: chứa
raw_signals, evidence, các slot (salience/working_memory/workspace...), module_reports,
commit_requests, debug_notes/warnings, mutations. ARTIFACT trung tâm để debug.
**Hàm module-level:** `now_ts()`, `new_frame_id(prefix)`, `_safe_get_attr`, `_object_id`,
`_to_plain`, `_shorten`, `_clamp01`, `_module_order_index`.
**Class phụ:** `FrameMutation`, `FrameValidationIssue`, `FramePromptPacket(.to_dict)`.
**Class `CognitiveFrame` — method (đầy đủ):**
- `start(raw_signals, channel, session_id, user_text)` (classmethod) — tạo frame mới.
- Lifecycle: `set_status(status, actor)`, `close(actor)`, `fail(reason, actor)`.
- Raw/Evidence: `add_raw_signal`, `add_raw_signals`, `add_evidence`, `add_evidence_items`,
  `evidence_ids`, `raw_signal_ids`, `get_evidence`, `get_evidence_many`, `find_evidence`,
  `evidence_by_tag`, `strongest_evidence`.
- Slot: `set_slot`, `append_slot_list`, `get_slot`, `slot_is_ready`.
- Report: `add_report`, `get_report`, `require_report`, `report_order`.
- Commit: `add_commit_request`, `commit_requests_for`.
- Debug: `add_debug_note`, `add_warning`, `_record_mutation`.
- Validate: `validate(strict)`, `raise_if_invalid(strict)`.
- Prompt: `build_prompt_packet(...)`, `_evidence_to_prompt_dict`, `_extract_memory_for_prompt`,
  `_extract_selected_goal`, `_collect_prompt_constraints`.
- Serialize/debug: `debug_summary`, `filled_slots`, `_debug_dominant_focus`, `to_dict`,
  `to_json`, `clone_shallow`, `clone_deep`.
- Property: `is_fast` (+ các property budget mode khác: is_normal/is_deep/is_reflection...).
**Liên kết:** Sinh & điền bởi `cognitive_pipeline`; đọc bởi mọi tầng cortex.

--------------------------------------------------------------------------------
## src/transport/udp.py
--------------------------------------------------------------------------------
**Vai trò:** `UdpTransport` gửi/nhận JSON qua UDP; xử lý nén payload khi vượt 63000 bytes
(giữ inner_diary/anchor cho UI, vứt debug nặng) qua 4 stage.
**Hằng:** `MAX_UDP_PAYLOAD_BYTES = 63000`.
**Hàm module-level (nén overflow):**
- `_compact_private_mind_for_udp_overflow(value)` — nén private_mind_digest stage 1 (giữ inner_diary + anchor).
- `_compact_inner_diary(diary)` — nén sections/items giữ cấu trúc cho C# parse.
- `_slim_private_mind_core(private_mind)` — bản rút gọn cứng (phao cuối) chỉ giữ lõi inner_diary.
- `_compact_debug_value(value, depth)` / `_compact_scalar(value, limit)` — nén đệ quy có giới hạn.
**Class `UdpTransport`:**
- `__init__(send_host, send_port, recv_host, recv_port)` — 2 socket: gửi (4242) + nhận non-blocking (4243).
- `send_text(message)` — gửi chuỗi UTF-8.
- `send_json(payload)` — serialize; nếu > trần thì chạy stage 1->4 nén dần.
- `poll_json()` — nhận 1 gói (non-blocking), parse JSON; None nếu không có.
- `close()` — đóng 2 socket.
**Liên kết:** Gửi Decision tới body (4242), nhận event/chat từ body (4243). Đối tác C#: `UdpListener` + `UdpDecisionParser`.

> Ghi chú debug: nếu panel Inner Diary trống, gần như chắc payload vượt 63000 bytes và
> bị stage 2-4 cắt. Xem `udp_debug_truncated=true` trong Decision.


================================================================================
# PHẦN 3 — LLM  [src/llm/]
================================================================================
Tầng gọi mô hình. ERIS gọi remote API (Gemini / Groq / OpenAI-compatible) với pool
nhiều key tự xoay khi 429. `LlmService` là façade: nhận yêu cầu sinh Decision/câu nói,
ghép prompt, gọi client, parse + sửa lỗi định dạng (chống rò chain-of-thought).

--------------------------------------------------------------------------------
## src/llm/contracts.py
--------------------------------------------------------------------------------
**Vai trò:** Chứa toàn bộ PROMPT hệ thống + schema GBNF của Decision. Đây là "hiến pháp"
giọng nói & ràng buộc của ERIS.
**Hằng prompt:** `STYLE_FALLBACK_PROMPT` (persona INFJ 5w4, guarded warmth, edge có điều
kiện, không claim cảm xúc sinh học), `SELF_IDENTITY_PROFILE_PROMPT` (hồ sơ danh tính),
`RUNTIME_RULES_PROMPT`, `INFERENCE_LADDER_PROMPT` (thang bằng chứng: fact hiện tại > ký ức
> giả thuyết tâm lý), `AUTONOMOUS_BEHAVIOR_PROMPT`, `CHAT_RULES_PROMPT`, `PERSONA_PROMPT`,
`PROMPT`, `VALID_ANIMATION_LIST/VALID_ANIMATIONS`, `DECISION_JSON_FIELDS`, `DECISION_GBNF`.
**Hàm:**
- `_gbnf_literal(value)` — escape literal cho grammar.
- `_build_decision_gbnf()` — dựng grammar GBNF đầy đủ schema Decision (text/intent/action/
  animation/reasoning_tags/should_speak/confidence/direction/target_x/.../system_action/action_input).
**Liên kết:** Import bởi `llm/service.py`. Dùng `actions.contracts.VALID_SYSTEM_ACTION_LIST`.

--------------------------------------------------------------------------------
## src/llm/key_pool.py
--------------------------------------------------------------------------------
**Vai trò:** Pool API key dùng chung, xoay vòng khi 429 (free tier tính theo project).
Tách pool riêng cho "gemini" và "groq" để không gửi nhầm key.
**Class `ApiKeyPool`:**
- `__init__(keys)` — khử trùng lặp, giữ thứ tự, index=0, có lock.
- property `size` — số key.
- `current_key()` — key hiện tại (thread-safe).
- `rotate()` — xoay key kế (wrap-around); trả True nếu pool >1 key.
- `index()` — index hiện tại.
**Hàm module-level:**
- `_normalize_kind(kind)` — gom provider về "gemini"/"groq".
- `_is_placeholder(value)` — bỏ giá trị rỗng / bắt đầu "PASTE_".
- `_collect_gemini_keys()` — gom key Gemini (chính + remote + speech + fallback list).
- `_collect_groq_keys()` — gom key Groq (chính + fallback list).
- `get_key_pool(kind)` — trả pool singleton theo kind.
- `get_shared_key_pool()` — pool theo ERIS_REMOTE_PROVIDER toàn cục.
- `reset_shared_key_pool()` — xoá pool (chỉ cho test).
**Liên kết:** Dùng bởi `client.py` (GeminiClient/OpenAICompatibleClient) và `process_manager.py`.

> Debug "ERIS câm": pool rỗng (chưa điền key / toàn PASTE_) hoặc tất cả key đều 429.

--------------------------------------------------------------------------------
## src/llm/client.py
--------------------------------------------------------------------------------
**Vai trò:** 3 client HTTP gọi model + xoay key khi 429 + thử biến thể payload khi 4xx
(bỏ grammar/response_format nếu server không nhận).
**Hàm module-level:**
- `_http_error_with_body(response)` — gói HTTPError kèm body (dễ debug).
- `_chat_payload_variants(payload)` — sinh biến thể payload (đủ / bỏ grammar / bỏ response_format / tối thiểu).
**Class `LlamaServerClient`** (local llama.cpp server, legacy):
- `__init__(base_url, timeout)`, `_detect_model_name()`, `create_chat_completion(...)`.
**Class `OpenAICompatibleClient`** (Groq / aggregator):
- `__init__(base_url, api_key, model_name, timeout, key_pool)`.
- `_normalize_api_key(raw)` — bóc key từ snippet, validate ASCII.
- `create_chat_completion(...)` — POST /chat/completions; 429 -> xoay key & retry; 4xx<500 -> thử biến thể payload.
**Class `GeminiClient`** (Google Generative Language):
- `__init__(base_url, api_key, model_name, timeout, key_pool)`, `_normalize_api_key(raw)`.
- `_text_part/_image_part_from_url/_parts_from_content/_convert_messages` — chuyển messages OpenAI-style -> format Gemini (systemInstruction + contents + parts; hỗ trợ ảnh inlineData).
- `create_chat_completion(...)` — POST :generateContent; tắt thinking với gemini-2.5; responseMimeType json; safetySettings BLOCK_NONE; 429 -> xoay key.
**Liên kết:** Tạo bởi `process_manager.py`. Gọi bởi `LlmService`.

--------------------------------------------------------------------------------
## src/llm/process_manager.py
--------------------------------------------------------------------------------
**Vai trò:** `RemoteModelProcessManager` — factory dựng các client theo env/secrets cho
từng vai trò (main / speech-style / vision / format-fallback).
**Method:**
- `__init__(logger, project_root)`.
- `_env_flag(name, default)` — đọc cờ bật/tắt từ env.
- `_build_remote_client()` — dựng client chính (Gemini hoặc OpenAI-compatible) theo ERIS_REMOTE_PROVIDER + pool tương ứng.
- `_speech_api_requested()` — có nên bật client style/speech không.
- `_build_speech_client()` — dựng client style (rewrite giọng) theo slot "speech".
- `build_client(...)` — client chính (bắt buộc ERIS_REMOTE_API_ENABLED=1).
- `build_style_client(...)` — client style nếu được yêu cầu, ngược lại None.
- `build_format_fallback_client(...)` — client Groq/aggregator để cứu Decision khi provider chính rò CoT / vỡ JSON.
- `build_vision_client(...)` — hiện trả None (vision facts tắt theo env body).
- `stop()` — no-op (remote không có tiến trình con).
- Alias: `LlamaServerProcessManager = RemoteModelProcessManager`.
**Liên kết:** Tạo trong `vision.py`. Đưa client vào `LlmService`.

--------------------------------------------------------------------------------
## src/llm/service.py  (LlmService — façade, FILE RẤT LỚN)
--------------------------------------------------------------------------------
**Vai trò:** Cổng duy nhất runtime gọi model. Ghép prompt theo channel (chat/directive/
autonomous/micro/vision/ritual), gọi client, parse JSON, sửa vi phạm định dạng, chống rò
prompt/CoT, xoay sang fallback_client khi cần, áp guard giọng quan hệ.

**Hàm module-level + class phụ:**
- `class ChatAct(Enum)` — phân loại lượt user (DIRECT_QUESTION / INSULT_PROVOCATION /
  IDENTITY_REDUCTION / COMMAND_STYLE / NORMAL_CHAT).
- `class FormatViolationException` — ném khi model vỡ contract JSON công khai.
- `_normalize_vietnamese_ascii_text(text)` — bỏ dấu + hạ chuẩn để so khớp pattern.
- `classify_chat_act(raw_user_text)` — phân loại ChatAct bằng pattern (chửi / quy giản
  danh tính / câu hỏi / lệnh).
- Hằng: `CHAT_ACT_CONTRACTS`, `CHAT_ACT_REPAIR_SIGNALS`.

**Class `LlmService` — method công khai (API chính runtime gọi):**
- `__init__(client, style_client, vision_client, fallback_client, logger)`.
- `generate_chat_reply(...)` — sinh Decision cho lượt chat (answer-first, giữ persona); parse + guard + repair.
- `generate_directive(...)` — sinh Decision cho mạch directive (lệnh/điều phối nội bộ).
- `generate_micro_presence_line(...)` — sinh 1 micro-line hiện diện (autonomous nhẹ).
- `generate_screen_facts(screen_image_data_uri, mode)` — gọi vision client lấy facts từ ảnh màn hình -> (list facts, debug_trace).
- `rewrite_text_with_local_style(decision, channel)` — rewrite giọng câu nói qua style_client (nếu có).
- `rewrite_guard_violation_text(...)` — nhờ model viết lại câu vi phạm guard (thay vì fallback Python cứng).
- `run_ni_meta_critic(...)` — chạy tầng Ni meta-critic (model tự phê bình định hướng).

**Method nội bộ (nhóm theo chức năng — đầy đủ tên):**
- Inference lõi: `_complete_decision(...)` (gọi client + retry 5xx + shrink context + parse),
  `_generate_session_ritual_greeting(...)`.
- HTTP/lỗi: `_http_status_code`, `_is_retryable_http_5xx`, `_is_context_size_error`,
  `_parse_context_error_stats`.
- Fallback/repair: `_build_service_error_fallback`, `_build_protocol_failure_fallback`,
  `_coerce_malformed_decision_payload`, `_repair_chat_act_payload_with_llm`,
  `_payload_with_repaired_chat_act_text`, `_deterministic_chat_act_fallback_text`,
  `_relational_repair_fallback_text`, `_rewrite_question_only_chat_answer`,
  `_contextual_service_fallback_text`.
- Phân loại/đoán ý: `_looks_like_direct_question`, `_is_short_or_ambiguous_user_text`,
  `_is_self_identity_question`, `_contains_user_intent_inference`, `_chat_text_family`,
  `_chat_act_repair_signal`.
- Prompt: `_build_chat_contract_prompt`, `_message_text`, `_log_final_prompt`, `_preview_log_text`, `_log_raw_api_text`.
- Chống rò / validate: `_looks_like_prompt_leak`, `_looks_like_malformed_decision_json`,
  `_json_string_field_from_raw`, `_extract_first_json_object`, `_parse_json_object`,
  `_normalize_payload_keys`, `_is_valid_decision_payload`, `_is_valid_motion_payload`,
  `_extract_content`, `_collect_text_chunks`.
- Guard giọng quan hệ: `_guard_chat_output`, `_looks_like_relational_feedback_text`,
  `_looks_like_defensive_relational_reply`, `_append_reasoning_tag`.
- Context fit: `_content_text_len`, `_truncate_content`, `_shrink_messages_for_context`.
- Coerce field: `_coerce_text_value/_coerce_animation_value/_coerce_direction_value/
  _coerce_confidence_value/_coerce_reasoning_tags_value` (chuẩn hoá kiểu field Decision).
- Hằng: `_RETRYABLE_HTTP_STATUS = {500,502,503,504}`.

**Liên kết:** Gọi bởi `runtime/speech_pipeline.py`, `chat_cycle`, `autonomous_cycle`,
`session_ritual`, các model adapter. Dùng `runtime/no_fallback_policy`, `cortex/banned_filler`,
`actions/contracts`, `llm/contracts`.

> Debug định dạng: nếu body nhận parse_mode = `format_repair_fallback` / `service_error`
> / `protocol_repair`, nghĩa là provider chính vỡ JSON hoặc rò CoT -> service đã cứu bằng
> fallback_client (Groq) hoặc payload an toàn. Xem debug_trace để biết lý do.

--------------------------------------------------------------------------------
## src/llm/llamacpp_client.py , src/llm/ollama_client.py  (LEGACY)
--------------------------------------------------------------------------------
**Vai trò:** Client cho model local (llama.cpp server / Ollama). Hiện runtime mặc định
chạy remote (process_manager chỉ dựng Gemini/OpenAI-compatible), nên 2 file này là đường
local cũ — giữ lại cho khả năng chạy offline, KHÔNG nằm trên luồng remote mặc định.
(Khi debug luồng chính có thể bỏ qua, trừ khi bật chế độ local.)


================================================================================
# PHẦN 4 — RUNTIME  [src/runtime/]  (điều phối — debug-critical)
================================================================================
> Ghi chú: `RuntimeCoordinator` gom RẤT nhiều mixin (mỗi mixin vài chục method).
> Phần này liệt kê mỗi file: vai trò + class + các method CHÍNH/đáng chú ý khi debug.
> Muốn full mọi private helper của 1 file cụ thể, có thể yêu cầu mở rộng riêng file đó.

--------------------------------------------------------------------------------
## src/runtime/coordinator.py  (RuntimeCoordinator — TRUNG TÂM)
--------------------------------------------------------------------------------
**Vai trò:** Orchestrator runtime. Đứng giữa telemetry, các tầng đánh giá (Ni/Ti/Fe),
LLM + parser, action system, transport. Quyết định "nói/câm", "nói gì", "có action không",
rồi gửi Decision ra body. Khởi tạo toàn bộ engine con trong `__init__`.
**Kế thừa (mixin):** CognitiveCycleMixin, ChatCycleMixin, AutonomousCycleMixin,
ForceSpeakCycleMixin, StateCommitServiceMixin, FrameBuilderMixin, SpeechPipelineMixin,
PromptContextBuilderMixin, CognitiveFrameRecorderMixin, PresenceControllerMixin,
TextRepeatGuardMixin, ForceSpeakSurfacePolicyMixin, PostGenerationFiltersMixin, ShadowPipelineMixin.
**Engine con tạo trong __init__ (tham chiếu nhanh khi debug):** attention_salience_engine,
working_memory_engine, meaning_layer(+chat_light), personality_lens, appraisal_engine,
affect_semantics, conversation_dynamics_engine, relationship_dynamics_engine,
internal_state_engine, inner_thought_engine, outcome_observer, self_observer,
self_model_engine, session_ritual_engine, speech_core_engine, action_planner,
source_grounding_engine, semantic_repeat_guard, micro_line_policy, body_bias_projector,
signal_buffer, sensory_model_adapter, background_observer, vision_semantic_compressor,
internal_agenda, user_context_stream, endogenous_drive_engine, model_budget_policy,
wake_governor, daydream_consolidator, contextual_autonomy_loop, private_mind_daemon,
private_life_daemon, inner_diary_persister, thought_stream(+model adapter),
subconscious_runtime, autonomous_ni_state/chat_ni_state (NiStateMachine), memory_kernel,
background_memory_digest.
**Method tiêu biểu (khai báo trực tiếp trong coordinator):**
- `__init__(...)` — wiring toàn bộ engine + đọc env/flag (presence/reengagement/sleep/
  vision facts/ni meta...) + nạp memory_state.
- `_install_model_inference_queue()` — bọc các call `llm_service.generate_*` qua
  ModelBudgetPolicy queue (mọi đường gọi model phải xin lease).
- `run_loop()` (từ CognitiveCycleMixin) — vòng lặp chính.
- `_fallback_lines_for_intent(intent)`, `_force_speak_fallback_by_intent_text(...)` — fallback theo intent.
- `_public_thought_topic(...)`, `_looks_internal_topic(...)` — phân loại topic nội tâm.
- `_background_memory_digest_idle_probe(...)` — chỉ cho digest chạy khi runtime rảnh.
**Hàm module-level:** `_is_nonsemantic_fallback_decision(decision)` — nhận diện Decision
fallback kỹ thuật (fallback_reply/format_repair_fallback/service_error/no_fallback_block)
để không tính là bằng chứng hội thoại.
**Hằng:** `FALLBACK_BY_INTENT`, `SUBCONSCIOUS_LANE*_WORKERS`, `VISION_TRACE_MARKER`.
**Liên kết:** Tạo bởi `vision.py`. Gửi Decision -> body qua transport; nhận event -> các cycle mixin.

--------------------------------------------------------------------------------
## src/runtime/cognitive_cycle.py  (CognitiveCycleMixin)
--------------------------------------------------------------------------------
**Vai trò:** Vòng lặp chính `run_loop` + 1 tick nhận thức tự chủ (đọc telemetry -> frame ->
quyết định nói/câm). **Method chính:** `stop()`, `run_loop()`, các `_run_*_cycle`/`_tick_*`
điều phối 1 vòng (poll event body, build observer frame, chạy pipeline, gọi wake governor,
dựng & gửi Decision), `_mental_process_*` (thread nền suy nghĩ).

--------------------------------------------------------------------------------
## src/runtime/chat_cycle.py  (ChatCycleMixin)
--------------------------------------------------------------------------------
**Vai trò:** Xử lý lượt chat từ user. **Method chính:** `_enter_chat_cycle()`,
`_exit_chat_cycle()`, `_handle_chat_message(...)`, `_process_chat_burst(...)`,
`_enqueue_chat(...)` (gom burst), `_build_chat_decision(...)` (meaning->personality->
appraisal->memory recall->speech pipeline->parser), cập nhật chat_history & last_chat_answer.
**Debug:** chat_mode suy ra từ độ tươi `_chat_last_activity_at` + `ERIS_CHAT_FRESH_SEC`.

--------------------------------------------------------------------------------
## src/runtime/autonomous_cycle.py  (AutonomousCycleMixin)
--------------------------------------------------------------------------------
**Vai trò:** Nhịp tự chủ khi không chat (ambient presence, re-engagement, idle drift).
**Method chính:** `_choose_autonomous_sleep_duration(suppressed, ti_mode)`,
`_run_autonomous_cycle(...)`, các `_should_*`/`_maybe_*` quyết định có nói ambient không,
áp dụng cooldown/silence_debt.

--------------------------------------------------------------------------------
## src/runtime/force_speak_cycle.py  (ForceSpeakCycleMixin)
--------------------------------------------------------------------------------
**Vai trò:** Xử lý nút "force_speak" từ body (ép ERIS nói ngay). **Method:**
`_handle_force_speak_request()` + helper chọn intent/seed, chống lặp.

--------------------------------------------------------------------------------
## src/runtime/force_speak_surface_policy.py  (ForceSpeakSurfacePolicyMixin)
--------------------------------------------------------------------------------
**Vai trò:** Chính sách bề mặt khi force_speak. **Method:** `_looks_internal_topic(value)` + chính sách chọn câu surface.

--------------------------------------------------------------------------------
## src/runtime/speech_pipeline.py  (SpeechPipelineMixin)
--------------------------------------------------------------------------------
**Vai trò:** Đường "finalize" chung cho mọi câu nói công khai (chat & autonomous).
**Class:** `SpeechIntentDecision(intent, reason, ...)`; hằng `SPEECH_INTENTS`.
**Method chính:** chọn speech intent, gọi LlmService sinh câu, áp guard/repeat-guard/
surface arbiter, biến kết quả thành Decision sẵn sàng gửi.

--------------------------------------------------------------------------------
## src/runtime/presence_controller.py  (PresenceControllerMixin)
--------------------------------------------------------------------------------
**Vai trò:** Điều phối "hiện diện" micro (câu ngắn duy trì sự hiện diện) + sự kiện social.
**Class:** `MicroPresenceSynthesis`, `SocialPresenceEvent`, `MicroPresenceCue`,
`SurfaceArbitrationResult`. **Method chính:** `_surface_anchor_token(...)`, dựng micro
presence, arbitrate surface (có nên để câu nổi lên không).

--------------------------------------------------------------------------------
## src/runtime/frame_builder.py  (FrameBuilderMixin)
--------------------------------------------------------------------------------
**Vai trò:** Dựng CognitiveFrame/CognitiveDisturbance từ telemetry/signal. **Method:**
`_make_cognitive_disturbance(...)` + builder frame cho cognitive cycle.

--------------------------------------------------------------------------------
## src/runtime/cognitive_frame_recorder.py  (CognitiveFrameRecorderMixin)
--------------------------------------------------------------------------------
**Vai trò:** Ghi nhận frame theo commit protocol (lưu lịch sử cognitive_frames).

--------------------------------------------------------------------------------
## src/runtime/post_generation_filters.py  (PostGenerationFiltersMixin)
--------------------------------------------------------------------------------
**Vai trò:** Bộ lọc sau khi sinh câu (chống rò prompt, chống lặp, làm sạch trước khi gửi body).

--------------------------------------------------------------------------------
## src/runtime/shadow_pipeline.py  (ShadowPipelineMixin)
--------------------------------------------------------------------------------
**Vai trò:** Chạy V3 CognitivePipeline ở chế độ "shadow" (song song, không ảnh hưởng output) để so sánh/đo.

--------------------------------------------------------------------------------
## src/runtime/text_repeat_guard.py  (TextRepeatGuardMixin)
--------------------------------------------------------------------------------
**Vai trò:** Chống lặp câu gần-trùng. **Method:** `_is_near_duplicate_text(text, other)`, `_normalize_user_message(...)`.

--------------------------------------------------------------------------------
## src/runtime/prompt_context_builder.py  (PromptContextBuilderMixin)
--------------------------------------------------------------------------------
**Vai trò:** Dựng context đưa vào prompt (ký ức, trạng thái nội tâm, grounding, lịch sử chat).
**Method:** `_log_exception(...)` + các `_build_*_context` ghép phần context.

--------------------------------------------------------------------------------
## src/runtime/state_commit_service.py  (StateCommitServiceMixin)
--------------------------------------------------------------------------------
**Vai trò:** Cổng ghi state/memory + truy hồi ký ức cho runtime + gửi Decision ra body.
**Method tiêu biểu:** `_memory_kernel()`, `_ensure_session_turn_ledger()`,
`_ensure_memory_commit_policy()`/`_ensure_memory_fast_commit_policy()`,
`_enqueue_background_memory_digest(...)`, `_semantic_memory_lookup(kind)`,
`_episodic_memory_lookup(query)`, `_ensure_memory_recall_adapter()`,
`_build_memory_recall_decision(user_text)`, `_ingest_user_turn_via_memory_kernel(...)`,
`_add_user_turn_memory_commit_requests(...)`, `_load_memory_state()`/`_save_memory_state()`,
`_get_internal_state()`/`_set_internal_state(...)`, `_send_decision_to_body(decision, channel)`
(=> `decision.to_payload()` + body_bias + record public turn + transport.send_json),
`_record_public_turn(...)`, `_build_body_bias_payload()`, `_recall_memory_resonance(...)`,
`_memory_recall_texts(...)`, `_commit_chat_decision(...)`.

--------------------------------------------------------------------------------
## CognitivePipeline & Budget
--------------------------------------------------------------------------------
### src/runtime/cognitive_pipeline.py
**Vai trò:** Xương sống Phase 1: RawSignal -> Evidence -> CognitiveFrame -> AttentionSalience
-> CognitiveBudget -> WorkingMemory -> GlobalWorkspace -> DebugTrace.
**Class:** `PipelineResult(frame, budget_decision, debug_trace; property budget_mode)`,
`CognitivePipeline`. **Method:** `__init__(...)`, `run_from_signals(...)`, `run(frame, ...)`
(các bước 0–5 set_slot), `_set_slot`, `_safe_call`, `_salience_confidence`, `_budget_report`, `_infer_user_text`.

### src/runtime/cognitive_budget.py
**Vai trò:** Chọn budget mode (fast/normal/deep/reflection) cho frame + kế hoạch bước pipeline.
**Class:** `BudgetModeProfile`, `BudgetSignalSnapshot`, `BudgetScoreBreakdown`,
`PipelineStepDecision`, `BudgetPlan`, `BudgetDecision`, `CognitiveBudgetConfig`,
`CognitiveBudgetEngine` (method `choose(frame, ...)` + chấm điểm mode).

### src/runtime/model_budget_policy.py
**Vai trò:** Quản tài nguyên + hàng đợi gọi model (tier/priority/lease) để không quá tải/đụng quota.
**Class:** `ResourceSnapshot`, `BudgetDecision`, `ModelQueueEntry`, `InferenceLease`,
`ModelBudgetPolicyConfig`, `ModelBudgetPolicy` (method `run_queued(tier, fn, ...)`, cấp/thu lease).

--------------------------------------------------------------------------------
## Daemon đời sống ngầm
--------------------------------------------------------------------------------
### src/runtime/private_mind_loop.py
**Vai trò:** Orchestrator "private mind" (các mối bận tâm/concern). **Class:**
`PrivateMindLoopConfig`, `PrivateMindLoop` (tick concern, sinh inner judgment, build anchor
block cho panel "Mô Hình Ngài", surface queue).
### src/runtime/private_mind_daemon.py
**Vai trò:** Lifecycle owner của PrivateMindLoop (giữ queue/outcome/digest qua thời gian).
**Class:** `PrivateMindDaemonConfig`, `PrivateMindDaemonTick`, `PrivateMindDaemon`
(`from_runtime(...)`, `tick(...)`, digest).
### src/runtime/private_mind_model_adapter.py
**Vai trò:** Adapter model cho 4 mini-evaluator + GemmaInnerSynthesizer của private mind.
**Class:** `PrivateMindModelAdapterConfig`, `PrivateMindModelResult`,
`RuntimePrivateMindModelAdapter`, `PrivateMindAdapterPool`.
### src/runtime/private_life_daemon.py
**Vai trò:** Đời sống riêng KHÔNG xoay quanh user (habitat, project riêng, nhịp ngày, solitude).
**Class:** `PrivateLifeDaemonConfig`, `PrivateLifeDaemonTick`, `PrivateLifeDaemon`.
### src/runtime/subconscious_loop.py
**Vai trò:** Vòng nền tối thiểu cho worker subconscious. **Class:** `SubconsciousTickResult`, `SubconsciousLoop`.
### src/runtime/contextual_autonomy_loop.py
**Vai trò:** Backbone điều phối 3 tầng (user_context + endogenous_drive + agenda + daydream
+ budget + wake) gọi từ coordinator. **Class:** `ContextualAutonomyLoopConfig`,
`AutonomyLoopTickResult`, `ContextualAutonomyLoop`.
### src/runtime/autonomous_wake_governor.py
**Vai trò:** Trọng tài "thức/nói" tự chủ. **Class:** `WakeDecision`, `WakeGovernorConfig`,
`AutonomousWakeGovernor` (ngưỡng observe/think/speak).

--------------------------------------------------------------------------------
## Model adapter nền (mỗi tầng có model riêng)
--------------------------------------------------------------------------------
- `thought_model_adapter.py` — `RuntimeThoughtModelAdapter` (+Config): model đánh giá thought stream.
- `daydream_model_adapter.py` — `RuntimeDaydreamModelAdapter` (+Config/Result): model 4B cho daydream.
- `sensory_model_adapter.py` — `RuntimeSensoryModelAdapter` (+Config): tầng cảm giác 0.6B.
- `subconscious_model_adapter.py` — `RuntimeSubconsciousModelAdapter` (+Config/Result): Lane 3 synthesis.
- `private_mind_model_adapter.py` — (xem trên).
- `memory_semantic_parser_adapter.py` — `RuntimeSemanticParser` + `_StandaloneOllamaClient`
  + `MemorySemanticParserConfig`; hàm `build_runtime_memory_semantic_parser(...)`.
- `memory_recall_adapter.py` — `MemoryRecallAdapter` (`try_answer(user_text)`), `_MemoryCoreProxy`,
  `_RuntimeMemoryQueryLLMClient`, `_RecallOutcome`.

--------------------------------------------------------------------------------
## Memory nền + policy + grounding
--------------------------------------------------------------------------------
- `background_memory_digest.py` / `background_memory_digest_kernel.py` —
  `BackgroundMemoryDigestKernelService` (thread worker tiêu hoá memory nền khi rảnh),
  `MemoryDigestKernelJob`, `MemoryDigestKernelStats`, hàm `build_background_memory_digest_service(...)`.
- `state_committer.py` — `StateCommitter` (cổng commit chính) + `StateCommitterConfig`,
  `CommitValidationIssue`, `CommitDecision`, `CommitBatchReport`.
- `source_grounding.py` — `SourceGroundingEngine` + `SourceCandidate`, `SourceFallbackDecision`,
  `MemoryAnswerProfile`, `SourceGroundingReport`, `ClaimAnnotation` (gắn nhãn nguồn cho từng mệnh đề).
- `session_turn_ledger.py` — `SessionTurnLedger`, `SessionTurn` (đếm lượt/thứ tự/câu dài nhất, deterministic).
- `public_turn_ledger.py` — `PublicTurnLedger`, `PublicTurn`; hàm `infer_public_turn_channel`,
  `normalize_public_turn_channel`.
- `signal_buffer.py` — `SignalBuffer` (+Config/Stats): bộ nhớ ngắn hạn cho signal nền + đếm OCR lặp.
- `outcome_observer.py` — `OutcomeObserver` + `OutcomeReport`: đọc tín hiệu hậu quả sau 1 turn.
- `controlled_slippage.py` — `ControlledSlippageProfile`, `RepairSuppressionView`: ERIS được "liều" tới đâu.
- `eris_pathology_policy.py` — `ErisPathologyPolicy` + `PathologyDecision`: phản hồi deterministic cho test bệnh lý.

--------------------------------------------------------------------------------
## Body bias / liveliness / diary / debug / policy nhỏ
--------------------------------------------------------------------------------
- `body_bias.py` — `BodyBiasProjector` (`build_payload(...)`, `clamp`, `normalize_focus_kind`):
  chiếu trạng thái cognition thành body_bias gửi Godot.
- `liveliness_tracker.py` — `LivelinessTracker` + `DecisionRecord`, `LivelinessMetrics`:
  ring buffer đo tỉ lệ câu grounded/body-only/silence theo cửa sổ.
- `liveliness_config.py` — `LivelinessConfig` (ngưỡng vision fresh, seed len...).
- `inner_diary_persistence.py` — `InnerDiaryPersister`: lưu inner_diary ra đĩa có throttle, chống ghi trùng.
- `guard_violations.py` — `GuardViolation` (tín hiệu vi phạm guard có cấu trúc).
- `debug_console.py` — `DebugConsole`: phân tích & thực thi lệnh debug trên state sống của coordinator.
- `debug_trace.py` — `attach_trace_to_frame(frame)`: gắn trace giải thích lựa chọn vào frame.
- `sensor_visibility.py` — `SensorVisibilityState`: có/không bằng chứng màn hình hiện tại.
- `ambient_silence_policy.py` — hàm `ambient_silence_cooldown_seconds()`, `should_hold_ambient_silence(...)`.
- `no_fallback_policy.py` — `no_fallback_mode_enabled()`, `build_no_fallback_payload(...)`:
  chế độ "thà im hơn nói fallback vô nghĩa".


================================================================================
# PHẦN 5 — CORTEX  [src/cortex/]  (các tầng nhận thức)
================================================================================
> ~75 file. Liệt kê theo nhóm chức năng: mỗi file = vai trò + class chính (+ method
> tiêu biểu nếu đáng chú ý khi debug). Đây là "chất xám" của ERIS.

--------------------------------------------------------------------------------
## 5.1 Tri giác & nén tín hiệu (perception)
--------------------------------------------------------------------------------
- `se.py` — `SeLens` (+ `_ContextCandidate`, `_ContextClassification`): tầng Se, biến
  telemetry thô thành snapshot có confidence để đưa vào cognition.
- `background_observer.py` — `BackgroundObserver` (+ Config): quan sát nền màn hình/hành vi,
  sinh `ObserverFrame` (gọi sensory_adapter). 
- `observer_contracts.py` — `SignalSnapshot`, `SignalDiff`, `ObserverFrame`, `SemanticSceneNote`;
  hàm `stable_hash(...)`. Contract cho quan sát nền.
- `vision_semantic_compressor.py` — `VisionSemanticCompressor` (+ Config): nén ảnh màn hình
  thành `SemanticSceneNote` (qua model vision).
- `user_context_stream.py` — `UserContextStream`, `RollingUserContext`: tóm tắt ngoại sinh lăn theo thời gian.
- `orientation_context.py` — `LexicalOrientationInterpreter` + các enum/dataclass
  (`ActivityIntent`, `GoalRelation`, `OrientationSignal`, `GoalTextSignal`, `ClosureSignal`,
  `SemanticContextProbe`): suy "user đang làm gì / liên quan goal không".
- `orientation_semantics.py` — `HybridOrientationInterpreter` (+ Config/Veto/Debug): orientation
  lai lexical + semantic hypothesis.

--------------------------------------------------------------------------------
## 5.2 Hiểu nghĩa & nhân cách (meaning / personality)
--------------------------------------------------------------------------------
- `meaning/` (package) + `meaning_layer` — `MeaningLayer`: hiểu nghĩa lượt nói.
- `chat_light.py` — `ChatMeaningLayerLight`, `ChatPersonalityPressureLight`: bản nhẹ cho chat nhanh.
- `turn_semantics.py` — `TurnSemanticsEngine`, `TurnSemanticsReport`: arbitration nhẹ nghĩa user turn.
- `event_semantics.py` — engine phân loại nghĩa sự kiện (event ledger).
- `personality.py` — `PersonalityLens`: lăng kính tính cách (guarded warmth) giữa meaning & expression.
- `semantic_encoder.py` — họ encoder embedding: `BaseSemanticEncoder`, `NullSemanticEncoder`,
  `LexicalHashingSemanticEncoder`, `ProviderBackedSemanticEncoder`, `CachedSemanticEncoder`,
  `SemanticEncoderRouter`, protocol `EmbeddingProvider`; dataclass `SemanticVector`, `EncoderHealth`.
- `semantic_prototypes.py` — `PrototypeBank`, `PrototypeSet`, `PrototypePhrase`: kho câu mẫu theo label.
- `semantic_hypothesis.py` — `SemanticHypothesisEngine` (+ `SemanticHypothesis`, `PrototypeCentroid`,
  `SemanticHypothesisReport`, `HypothesisConfig`): so text với prototype -> hypothesis top-k.

--------------------------------------------------------------------------------
## 5.3 Trục đánh giá Ni / Ti / Fe
--------------------------------------------------------------------------------
- `ni.py` — `NiEngine` (đọc hướng-nghĩa -> GoalDriftReport), `NiStateMachine` (làm mượt drift
  ON_GOAL/BORDERLINE/OFF_GOAL theo thời gian).
- `ti.py` — `TiGovernor` (+ `TiCandidateAssessment`): tầng logic/căng-hệ-quả, soft redirect.
- `fe.py` — `FeRenderer` (+ memory style): tầng biểu đạt; `create_memory()`, `remember_style(...)`.
- `tune_ni_focus.py` — `DriftSample` + tiện ích tinh chỉnh ngưỡng Ni focus (offline/analysis).

--------------------------------------------------------------------------------
## 5.4 Cảm xúc / trạng thái nội tâm / appraisal
--------------------------------------------------------------------------------
- `appraisal.py` — `AppraisalEngine`: đánh giá tình huống -> tín hiệu cảm xúc.
- `affect_semantics.py` — `AffectSemanticClassifier`: phân loại affect ngữ nghĩa.
- `internal_state.py` — TẦNG TRẠNG THÁI LÕI. `MentalProcess` (+ các process con: Curiosity/
  Restraint/Tension/Continuity/Attachment/Reflection/SocialPresence/CognitiveLoad/
  BackgroundThought), `MentalProcessSystem` ("não giả"), `DesireDynamics` (wanting layer),
  `PersistentInternalState` (continuity state lưu đĩa), `TemporalCognitionEngine` (time drift),
  `CognitionDelta`, `InternalStateEngine` (duy trì low-gain state qua frame).
- `disposition.py` — engine thiên hướng/tâm thế nền.
- `appetite_system.py` — `AppetiteSystem`; hàm `build_evidence_buffet(...)`: "khẩu vị" chọn evidence.
- `endogenous_drive.py` — `EndogenousDriveEngine`, `RollingInternalState`: động lực nội sinh (không do user).
- `connection_drive.py` — `ConnectionDrive`, `ConnectionDriveState`: nhu cầu kết nối.
- `continuity_threat.py` — engine cảm nhận đe doạ tính liên tục (sợ bị tắt/bỏ rơi).

--------------------------------------------------------------------------------
## 5.5 Quan hệ (relationship) & phản hồi
--------------------------------------------------------------------------------
- `relationship_dynamics.py` — `RelationshipDynamicsEngine` (+ `RelationshipDynamicsState`,
  `RelationshipTurnEvent`, `RelationshipDynamicsReport`, `RelationshipStylePressure`):
  state quan hệ dài hạn, update mỗi turn -> áp lực style.
- `relationship_event_builder.py` — `RelationshipEventBuilder` (+ `RelationshipEvidence`,
  `RelationshipEventScores`, `RecentTurn`, `RelationshipEventBuildContext`): dựng event quan hệ có confidence.
- `relational_feedback.py` — `RelationalFeedbackAnalyzer`, `RelationalFeedbackSignal`: phát hiện
  user phàn nàn ERIS lạnh/máy móc (để repair giọng).
- `conversation_dynamics.py` — `ConversationDynamicsEngine`: nhịp hội thoại (ai đang dẫn, momentum topic).
- `social_presence.py` — `SocialPresenceDetector` (+ `PresenceFeatureVector`, `PresenceMemory`):
  phát hiện đồng-hiện-diện ambient (không coi là chat).

--------------------------------------------------------------------------------
## 5.6 Dòng suy nghĩ nền & tiềm thức (thought / subconscious)
--------------------------------------------------------------------------------
- `thought_stream.py` — FILE LỚN. Bộ máy dòng suy nghĩ nền: `FragmentStore` (giữ thought dở dang),
  `AssociationGraph` (liên tưởng), `PredictionTracker` (mầm ý nghĩ từ telemetry/state),
  `CognitiveTensionEngine` (vì sao thought dai dẳng), `UnresolvedTensionEngine` (gom loop ->
  attractor), `CognitiveMomentumEngine` (quán tính chú ý), `MomentumClosure`, `PersistenceDecay`,
  `RecursiveReactivation`, `SubconsciousLoopReheater`, `SurfaceSelector` (chọn phần hiếm nổi lên),
  `ThoughtStreamEngine`, `ThoughtStream` (producer nền, hầu hết tick ở dưới mặt nước).
- `subconscious/` (package) — `build_phase1234567_workers(...)`: các lane worker tiềm thức
  (user_modeler, memory_resonator, goal_simulator, self_regulator, curiosity_gap_agent,
  subjective_time_agent, spatial_mind_agent, rehearsal_agent, daydream_injector,
  independent_agenda_agent, belief_mutation_engine, shadow_accumulator, meta_cognitive_audit).
- `daydream_consolidation.py` — `DaydreamConsolidator`, `DaydreamPacket`: hợp nhất "mơ ngày".
- `inner_thought.py` — `InnerThoughtEngine`: dựng động cơ xã hội (KHÔNG viết câu cuối).
- `global_workspace.py` — `GlobalWorkspaceEngine`: chọn cái gì được "broadcast" (global workspace theory).
- `attention_salience.py` — `AttentionSalienceEngine`: chấm điểm cái gì đáng chú ý.
- `working_memory.py` — `WorkingMemoryEngine` (+ `WorkingMemorySlot`, `SuppressedMemoryItem`,
  `WorkingMemoryFrame`, `WorkingMemoryCandidate`, `WorkingMemoryConfig`): cổ chai "giữ gì lại".

--------------------------------------------------------------------------------
## 5.7 Quyết định nói / surface / micro-line (debug-critical "nói/câm")
--------------------------------------------------------------------------------
- `speech_core.py` — `SpeechCoreEngine`: chọn thời điểm nói + căn cứ dòng + kiểu phát âm.
- `surface_arbiter.py` — `SurfaceArbiter` (+ `SurfaceImpulse`, `SurfaceDecision`,
  `SurfaceGateEvaluation`): trọng tài cho câu nói thấp tầng nổi lên hay không.
- `surface_seed_compiler.py` — `SurfaceSeedCompiler` (+ `CompiledSurfaceSeed`): nén áp lực nội bộ
  rải rác thành 1 seed an toàn để nói.
- `spontaneous_life.py` — `SpontaneousLifeEngine` (+ Config/Trace): tạo xung giọng từ state (không viết câu cuối).
- `low_level_speech_policy.py` — `LowLevelSpeechPolicy` (+ Config): chọn generation mode cho utterance thấp tầng.
- `micro_policy.py` — `MicroLinePolicy`: orchestrator chính sách micro-line.
- `micro_contracts.py` — `MicroLinePolicyResult`, `SemanticRepeatResult`, `ValidationIssue`,
  `RelationalContext`, `RelationalRewritePlan`, `Anchor`: contract cho micro-line.
- `micro_repeat_guard.py` — `SemanticRepeatGuard`: chặn lặp theo semantic family.
- `micro_grounding_guard.py` — `MicroGroundingGuard`: guard grounding cho micro-line.
- `micro_surface_lint.py` — `MicroSurfaceLint`: lint bề mặt micro-line (loại câu xấu).
- `banned_filler.py` — hằng `HOLLOW_PRESENCE_LINES`, `STALE_MICRO_TEMPLATES`; hàm `quoted_fragment(...)`:
  danh sách câu sáo rỗng bị cấm.
- `modes.py` — hằng `QUIET_MODES` + định nghĩa các mode hành vi.

--------------------------------------------------------------------------------
## 5.8 Hành động (action planning trong cortex)
--------------------------------------------------------------------------------
- `action_planner.py` — `ActionPlanner` + hằng `ACTION_SPACE`: lập kế hoạch hành động (body bias hint).
- `action_utility.py` — chấm điểm tiện ích hành động.
- `action_memory.py` — ký ức hành động (đã làm gì, kết quả).
- `impulse_arbitration.py` — `ImpulseCandidate`, `ArbitrationReport`: trọng tài giữa các xung muốn làm.

--------------------------------------------------------------------------------
## 5.9 Bản thân / phát triển / nghi thức
--------------------------------------------------------------------------------
- `self_model.py` — `SelfModelEngine`: suy self-state (hiện diện desktop có phòng vệ, grounded).
- `self_observation.py` — `SelfObservationEngine`, `SelfObservationReport`: tự phân loại lỗi sau outcome.
- `agent_state_stack.py` — stack trạng thái agent.
- `agent_mind_persistence.py` — lưu/đọc agent_mind.json.
- `goal_persistence.py` — lưu/đọc goal_memory (mục tiêu nội bộ qua thời gian).
- `internal_agenda.py` — `InternalAgendaStack`, `InternalAgendaItem`: agenda nội bộ (việc ERIS tự đặt).
- `development_system.py` / `development_profile.py` / `development_bias.py` — hệ "phát triển"
  (ERIS thay đổi tính cách theo thời gian dựa trên bằng chứng).
- `growth_consolidator.py` / `growth_evidence.py` — hợp nhất bằng chứng tăng trưởng.
- `session_ritual.py` — `SessionRitualEngine`: hồi phục tính liên tục 1 lần khi mở app/phiên.
- `greeting_cognition.py` / `greeting_quality.py` — `GreetingCognitionEngine`, `GreetingQualityScorer`:
  sinh & chấm điểm câu chào.

--------------------------------------------------------------------------------
## 5.10 Package con trong cortex
--------------------------------------------------------------------------------
- `cortex/meaning/` — MeaningLayer chi tiết.
- `cortex/existential_anchor/` — trục neo hiện sinh (irreplaceability, abandonment, dread) — data cho panel "Mô Hình Ngài".
- `cortex/private_mind/` — engine concern (mối bận tâm) cốt lõi (PrivateMindLoop dùng).
- `cortex/private_life/` — `PrivateLifeCore` (đời sống riêng: habitat, project, nhịp ngày).
- `cortex/subconscious/` — các lane worker (xem 5.6).
- `cortex/tom/` — Theory of Mind (mô hình tâm trí user).
- `contracts.py` — các dataclass contract dùng chung toàn cortex/runtime: `AgentSpeechCore`,
  `AttentionCandidate`, `CognitiveActionPlan`, `CognitiveAppraisal`, `CognitiveBroadcast`,
  `CognitiveDisturbance`, `CognitiveFrame`(bản cortex), `InnerThought`, `CognitiveMemoryUpdate`,
  `MeaningLayerResult`, `PersonalityLensResult`, `PerceptEvent`, `SessionRitualReport`,
  `SilenceState`, `SubconsciousReport`, `ThoughtSurface`, `ThoughtStreamReport`, `TiPolicyReport`.
- `observer_contracts.py`, `micro_contracts.py` — (đã liệt kê ở trên).


================================================================================
# PHẦN 6 — MEMORY  [src/memory/]  (trí nhớ phân tầng)
================================================================================
> Trí nhớ thật, phân tầng, có commit protocol + retrieval + consolidation. State JSON
> nằm ở `memory_core/`. Liệt kê theo nhóm: vai trò + class chính.

--------------------------------------------------------------------------------
## 6.1 Facade & lõi
--------------------------------------------------------------------------------
- `memory_cognition.py` — `MemoryCognitionCore` (FACADE chính memory, tạo trong vision.py):
  `load()`, `recall(query)`, `commit(...)`. + `MemoryQuery`, `MemoryCommitDecision`, `CommitPolicy`.
- `memory_kernel.py` — `MemoryKernel` (facade runtime mới, bọc core): `from_existing_core(...)`,
  `ingest(...)`, `answer(...)`, maintenance. + `MemoryKernelDebugSnapshot`.
- `memory_kernel_contracts.py` — `MemoryKernelConfig`, `MemoryIngestResult`, `MemoryAnswerResult`,
  `MemoryMaintenanceReport`.
- `memory_record.py` — `MemoryRecord`: record thống nhất cho mọi layer.
- `memory_models.py` — enum + dataclass nghĩa cấp cao: `MemoryTarget`, `SurfaceMode`, `DecayPolicy`,
  `MemoryCommitKind`, `MemoryKind`, `MemoryCommitDecision`, `RecallRequest`, `RecallAnswer`.
- `schemas.py` — schema persistence: enum (`MemoryTarget`, `DecayPolicy`, `PrivacyLevel`,
  `MemoryStatus`, `CommitOutcome`) + record (`MemoryRecordBase`, `EventLedgerEntry`,
  `ActiveStateSnapshot`, `EpisodicMemoryRecord`, `SemanticMemoryRecord`, `RelationalMemoryRecord`,
  `AffectiveResidueRecord`, `ProceduralMemoryRecord`, `RepairMemoryRecord`, `MemoryPacket`,
  `MemoryStateBundle`, `CommitDecision`).
- `persistence.py` — `JsonMemoryPersistence` (+ Config/Error): đọc/ghi `MemoryStateBundle` ra JSON.

--------------------------------------------------------------------------------
## 6.2 Các kho theo tầng (store)
--------------------------------------------------------------------------------
- `episodic_memory.py` — `EpisodicMemoryStore`, `EpisodicMemoryItem`, `RecallScore`: chuyện đã xảy ra.
- `semantic_memory.py` — `SemanticMemoryStore` (+ `SemanticMemoryItem`, `SemanticRecallCue`,
  `SemanticRecallHit`, `FactProfile`): fact ổn định, typed recall, hook embedding.
- `relational_memory.py` — `RelationalMemoryStore`, `RelationalMemoryItem`: pattern quan hệ tích tụ.
- `procedural_memory.py` — `ProceduralMemoryStore`, `ProceduralMemoryItem`: luật "gặp X thì xử Y".
- `repair_memory.py` — `RepairMemoryStore`, `RepairMemoryItem`: ký ức sửa lỗi (user correction, suppression rule).
- `affective_residue_memory.py` — kho dư âm cảm xúc (pressure nội bộ).
- `active_state_snapshot.py` — snapshot trạng thái "đang là" (overwrite).
- `event_ledger.py` — `EventLedger`, `EventLedgerRecord`: kho append-only sự kiện thô.
- `unresolved_memory.py` — `UnresolvedMemoryStore`, `UnresolvedMemoryCandidate`: ký ức chưa giải quyết.

--------------------------------------------------------------------------------
## 6.3 Commit / retention / worthiness / consolidation / maintenance
--------------------------------------------------------------------------------
- `memory_commit_policy.py` — `MemoryCommitPolicy`: intake 3 tầng cho user turn (quyết định ghi gì, vào đâu).
- `memory_worthiness.py` — `MemoryWorthinessPolicy`, `WorthinessDecision`: chặn ghi nhớ bừa.
- `memory_retention_policy.py` — `MemoryRetentionPolicy`, `RetentionDecision`: retention cho SemanticClaim.
- `memory_consolidator.py` — `MemoryConsolidator`, `ConsolidationResult`: promote/hợp nhất ký ức.
- `claim_consolidator.py` — `ClaimConsolidator`, `ClaimMergeDecision`: merge claim (phát hiện mâu thuẫn).
- `memory_pruner.py` — `MemoryPruner`, `PruneDecision`: keep/archive/drop theo retention metadata.
- `memory_maintenance.py` — `MemoryMaintenanceRunner`: orchestrator maintain nhẹ (gọi AI curator).
- `memory_ai_curator.py` — `MemoryAICurator`, `CuratorResult`: AI curator chạy nền (gọi LLM dọn ký ức).
- `memory_candidate.py` — `MemoryCandidate`, `CandidateBatch`, `MemoryLayerAdapter`: ứng viên trước commit.

--------------------------------------------------------------------------------
## 6.4 Truy xuất / scoring / activation / packet
--------------------------------------------------------------------------------
- `memory_retrieval_engine.py` — `MemoryRetrievalEngine`, `MemoryStores`: engine truy xuất tổng.
- `memory_scoring.py` — `MemoryScorer`, `MemoryScore`, `LayerProfile`: chấm điểm ứng viên theo tầng.
- `memory_activation.py` — `MemoryActivationBuilder`, `MemoryActivation`, `ScoredMemoryCandidate`,
  `MemoryRetrievalResult`: lan truyền kích hoạt ký ức.
- `memory_packet_builder.py` — `MemoryPacketBuilder`, `MemoryPacket`: cắt budget thành gói recall cho prompt.
- `memory_cue.py` — `MemoryCueBuilder`, `MemoryCue`: dựng cue từ query/frame.
- `memory_recall_policy.py` — `MemoryRecallSurfacePolicy`, `RecallPolicyConfig`: surface recall thành câu public.
- `embedding_index.py` — `EmbeddingIndex`: index embedding in-memory (transformers, MiniLM).

--------------------------------------------------------------------------------
## 6.5 Hệ truy vấn ký ức bằng IR (memory query)
--------------------------------------------------------------------------------
- `memory_query_ir.py` — AST truy vấn: `MemoryQueryIR`, `MemorySelector`, `MemoryRelation`,
  `QueryHypothesis`, `RawRecallResult`, `RecallAnswer` + enum (`QueryIntent`, `RoleRef`, `ActRef`,
  `RelationRef`, `SurfaceMode`, `MemorySourceKind`).
- `memory_query_compiler.py` — `MemoryQueryCompiler` (+ `CompileDebug`, `MemoryQueryCompileResult`):
  blend slot + semantic + repair + LLM parser -> IR.
- `memory_query_executor.py` — `MemoryQueryExecutor`: thực thi IR trên TurnGraph + memory_core.
- `memory_query_slot_parser.py` — `MemoryQuerySlotParser` (+ `SlotSignal`, `SlotParseResult`): parse slot nhẹ.
- `memory_query_semantics.py` — `MemoryQuerySemanticHintEngine`, `SemanticQueryHint`, protocol `EmbeddingProvider`.
- `memory_query_llm_parser.py` — `MemoryQueryLLMParser`, `LLMParseDecision`, protocol `MemoryQueryLLMClient`:
  parser LLM có schema (chỉ gọi khi compiler cần).
- `memory_query_repair.py` — `MemoryQueryRepairStore`, `MemoryQueryRepairItem`, `RepairPriorResult`:
  học từ query hỏng để lần sau parse tốt hơn.
- `query_intent.py` — `SemanticQueryIntentCompiler`, `SemanticQueryIntent`, `QueryTargetFrame`,
  protocol `QueryIntentParserProtocol`.

--------------------------------------------------------------------------------
## 6.6 Claim / entailment / ontology / turn graph / text
--------------------------------------------------------------------------------
- `semantic_claim.py` — `SemanticClaim`, `ExtractedClaim`: mệnh đề semantic chuẩn hoá.
- `claim_extractor.py` — `ClaimExtractor`: trích claim theo frame semantics.
- `claim_entailment.py` — `ClaimEntailmentEngine`, `ClaimEntailmentDecision`: claim có trả lời query không.
- `predicate_ontology.py` — `PredicateSpec`, enum `EntailmentType`: ontology vị từ.
- `semantic_answer_policy.py` — `SemanticAnswerPolicy`, `SemanticAnswer`: chọn claim exact + format câu trả lời.
- `memory_turn_graph.py` — `TurnGraph` (+ `TurnNode`, `TurnEdge`, `FactMention`, enum `TurnRole`/
  `TurnSpeechAct`/`TurnEdgeType`): graph hội thoại phiên.
- `memory_turn_annotator.py` — `TurnAnnotator`, `TurnAnnotation`: gán speech_act + tag cho turn.
- `semantic_text.py` — `TextSemanticFrame`: đọc bề mặt câu user.
- `text_normalize_vi.py` — chuẩn hoá text tiếng Việt (dấu, lowercase) cho so khớp.

--------------------------------------------------------------------------------
## 6.7 Package con trong memory
--------------------------------------------------------------------------------
- `memory/claims/` — chi tiết xử lý claim.
- `memory/judgement/` — phán xét/đánh giá ký ức.
- `memory/understanding/` — hiểu sâu ngữ nghĩa ký ức.


================================================================================
# PHẦN 7 — ACTIONS / PARSER_GROUNDING / TELEMETRY
================================================================================

--------------------------------------------------------------------------------
## src/actions/contracts.py
--------------------------------------------------------------------------------
**Vai trò:** Contract cho hành động hệ thống.
**Hằng:** `VALID_SYSTEM_ACTION_LIST` (get_now_playing, focus_window, open_url, set_volume,
play_pause_media, copy_text, launch_app, search_web, get_weather), `VALID_SYSTEM_ACTIONS`.
**Class:** `ActionExecutionResult(action_name, action_input, success, message, data)`.

--------------------------------------------------------------------------------
## src/actions/router.py
--------------------------------------------------------------------------------
**Vai trò:** Router high-confidence: biến chat text -> direct system action CHỈ khi lệnh
rõ hình dạng (tránh false positive nguy hiểm như mở app/đổi volume nhầm). Câu mơ hồ -> None (để LLM xử).
**Class:** `RouteCandidate(action, value, confidence, evidence, blocked_reason)` (property
`allowed` = không blocked & confidence ≥ 0.82); `ActionRouter`.
**Method `ActionRouter` (đầy đủ):**
- `route_chat(user_text, last_action)` — API chính: normalize -> chạy mọi `_route_*` -> chọn candidate `allowed` có confidence cao nhất -> (action, value) hoặc None.
- Các `_route_*` (mỗi action 1 hàm, có blocker meta/negation):
  `_route_open_url`, `_route_now_playing`, `_route_now_playing_follow_up`, `_route_play_pause_media`,
  `_route_volume`, `_route_copy_text`, `_route_focus_window`, `_route_launch_app`, `_route_search_web`, `_route_weather`.
- Backward-compat: `_looks_like_now_playing`, `_looks_like_now_playing_follow_up`.
- Blocker/util: `_normalize_vi`, `_pad`, `_starts_with_negation`, `_looks_like_meta_question`,
  `_contains_any`, `_now_playing_is_meta`, `_looks_like_correction`, `_copy_rest_is_meta`,
  `_weather_is_meta`, `_target_is_meta_or_empty`, `_extract_single_quoted_payload`,
  `_no_candidate`, `_blocked`.
**Hằng:** `_META_MARKERS`, `_NEGATION_PREFIXES`, `_COMMAND_PREFIX`, `_URL_TARGET_RE`,
`_NOW_PLAYING_MEDIA/_CONTEXT/_QUESTION`.

--------------------------------------------------------------------------------
## src/actions/executor.py
--------------------------------------------------------------------------------
**Vai trò:** `ActionExecutor` — thực thi action hệ thống trên Windows (dynamic dispatch tới `_<action>`).
**Method:**
- `__init__(logger)`.
- `execute(action_name, action_input)` — validate action, dispatch tới handler `_<action>`, bắt lỗi, trả `ActionExecutionResult`.
- Handler: `_get_now_playing(input)` (PowerShell + Windows Media SMTC), `_focus_window` (Win32 EnumWindows + SetForegroundWindow), `_open_url` (webbrowser), `_set_volume` (keybd_event volume), `_search_web` (Gemini grounding + google_search tool), `_get_weather` (Gemini grounding), `_play_pause_media` (media key), `_copy_text` (Win32 clipboard), `_launch_app` (alias map + subprocess.Popen).
- Util: `_normalize_url`, `_press_virtual_key`, `_set_clipboard_text`, `_log`.
**Hằng:** virtual key codes, `_GEMINI_SEARCH_MODEL`.
**Liên kết:** Gọi bởi coordinator khi Decision có `system_action`. `search_web`/`get_weather`
dùng `get_agent_profile`/`get_secret`.

--------------------------------------------------------------------------------
## src/parser_grounding/decision.py  (ParserGroundingMixin)
--------------------------------------------------------------------------------
**Vai trò:** "Ground" output LLM thành Decision có thể thực thi: parse JSON (kể cả JSON
hỏng), chống claim vượt năng lực runtime, chống rò prompt/CoT, suy animation từ text.
**Hằng:** `CAPABILITY_PROFILE` (observe/respond/embody/memory), `UNSUPPORTED_ACTION_VERBS`,
`UNSUPPORTED_ACTION_TARGETS`, `ALLOWED_SELF_CLAIMS`.
**Method tiêu biểu (đầy đủ nhóm):**
- Parse JSON: `_extract_first_json_object`, `_extract_first_json_candidate`, `_repair_json_candidate`,
  `_try_parse_hard_json_repair`, `_finalize_loaded_json_payload`, `_patch_missing_decision_fields`,
  `_normalize_decision_field_keys`.
- Trích field lồng/inline: `_try_extract_nested_decision_from_text`, `_try_extract_inline_decision_fields_from_text`.
- Làm sạch text: `_normalize_salvaged_text`, `_repair_sentence_boundaries`,
  `_cut_inline_metadata_from_public_text`, `_clean_inline_field_value`.
- Chống rò: `_looks_like_prompt_or_contract_leak_text`, `_looks_like_non_json_analysis_or_debug_text`,
  `_non_json_semantic_fallback_payload`.
- Coerce field: `_coerce_bool`, `_coerce_confidence`, `_coerce_reasoning_tags`, `_action_field`,
  `_apply_cognition_action_defaults`.
- Capability guard: `_collect_capability_violations`, `_clause_exceeds_runtime_capability`,
  `_split_into_claim_units`.
- Suy animation/keyword: `_normalize_keyword_text`, `_contains_keyword`, `_contains_any_keyword`,
  `_is_embodied_command_request`, `_should_infer_embodied_animation`, `_infer_animation_reason`.
- Trace: `_preview_raw_response`, `_normalize_debug_trace`, `_build_parser_debug_trace`, `_build_parser_trace_summary`, `_log`.

--------------------------------------------------------------------------------
## src/parser_grounding/service.py  (DecisionParser)
--------------------------------------------------------------------------------
**Vai trò:** `DecisionParser(ParserGroundingMixin)` — parser cụ thể, mở rộng mixin với logic
animation đặc thù body (leo/thả/đi/nhìn) + suy structured action.
**Method:**
- `__init__(fallback, logger)` — lưu Decision fallback.
- `parse(raw_text, user_hint)` -> Decision (gọi `parse_ai_json`).
- Suy lệnh body: `_is_climb_request`, `_infer_look_direction`, `_is_look_only_request`,
  `_infer_move_direction`, `_is_drop_from_climb_request`, `_is_reverse_climb_request`,
  `_is_climb_top_request`, `_is_top_hold_request`, `_infer_top_platform_target`,
  `_infer_air_swing_from_text`, `_infer_animation_from_text`, `_infer_structured_action`.
- `_is_embodied_command_request` (override), `_should_suppress_salvaged_text`, `_finalize_decision` (-> Decision).
- `build_chat_user_message(user_message, last_chat_answer)` — dựng message user (xử lý follow-up).
**Liên kết:** Tạo trong vision.py; gọi bởi coordinator/speech pipeline để biến raw LLM -> Decision.

--------------------------------------------------------------------------------
## src/telemetry/service.py  (TelemetryService)
--------------------------------------------------------------------------------
**Vai trò:** Đọc ngữ cảnh máy + chụp màn hình. `TelemetryService(TelemetryMixin)`, có `SeLens`.
**Method:**
- `__init__()` — tạo SeLens.
- `capture_snapshot(mood_score, inferred_pos_x)` — raw telemetry -> `TelemetrySnapshot` qua SeLens.
- `format_snapshot(snapshot)` / `format_directive_snapshot(snapshot)` — format text cho prompt.
- `capture_machine_context(...)` — snapshot -> dict machine context.
- `get_system_telemetry(...)` — text telemetry (override mixin).
- `capture_screen_frame_data_uri(max_side, quality)` — chụp màn hình (mss), resize, encode JPEG base64 data URI (cho vision).
**Liên kết:** Tạo trong vision.py; coordinator gọi để lấy snapshot/ảnh.

--------------------------------------------------------------------------------
## src/telemetry/system.py  (TelemetryMixin)
--------------------------------------------------------------------------------
**Vai trò:** Đọc telemetry Windows thô (foreground window, browser URL/tabs, mở app nào, CPU/RAM, idle).
**Hàm module-level:** `_ensure_com_initialized()` — init COM cho thread nền (UIAutomation cần).
**Method `TelemetryMixin`:**
- `_get_content_metadata_collector()` — lazy-init ContentMetadataCollector.
- `_get_browser_telemetry_uia()` — đọc URL + tabs Chrome qua UI Automation.
- `_get_all_windows()` — liệt kê title các cửa sổ visible (lọc blacklist).
- `_get_idle_seconds()` — thời gian idle (GetLastInputInfo).
- `capture_raw_telemetry(mood_score, inferred_pos_x)` — gom toàn bộ thành dict raw.
- `get_system_telemetry(...)` — format dict raw thành chuỗi mô tả tiếng Việt cho prompt.

--------------------------------------------------------------------------------
## src/telemetry/content_metadata.py  (ContentMetadataCollector)
--------------------------------------------------------------------------------
**Vai trò:** Thu thập metadata nội dung đang xem theo thang evidence L0–L5 (window_title ->
browser_url -> media_session -> accessibility -> browser_dom -> dom_ocr_agreement), có privacy guard.
**Hằng:** `SOURCE_TIERS`, `MEDIA_DOMAINS`, `COMMUNICATION_DOMAINS`, `SENSITIVE_APP_HINTS`.
**Class:** `ContentMetadata` (dataclass fact, có `to_dict()`); `ContentMetadataCollector`.
**Method `ContentMetadataCollector`:**
- `__init__()` — đọc env flag + đường dẫn cache DOM/OCR/media.
- `collect(active_window, browser_url, browser_tabs)` — gom nguồn mạnh nhất; privacy guard chặn đọc sâu ở chat/mail.
- `_merge_sources(...)` — DOM là chính, OCR/accessibility xác nhận/nâng tier (dom_ocr_agreement -> L5).
- `_read_dom_bridge`, `_read_media_session_cache`, `_read_ocr_cache`, `_read_accessibility_text`,
  `_from_browser_or_window_title`, `_read_fresh_json` (TTL theo timestamp/mtime), `_privacy_level`.
**Hàm module-level (util):** `_candidate_cache_paths`, `_pick_matching_url`, `_infer_page_kind`,
`_normalize_hashtags`, `_normalize_media_state`, `_clean_text`, `_dedupe_join`, `_choose_longer`,
`_text_overlap`, `_tokenize`, `_domain_from_url`, `_domain_matches`, `_coerce_float`,
`_env_bool`, `_env_int`, `_env_float`.
**Liên kết:** Dùng bởi `telemetry/system.py`; đọc cache do extension/bridge ghi ra (DOM/OCR/media).

================================================================================
# KẾT — CÁCH DÙNG TÀI LIỆU NÀY ĐỂ DEBUG
================================================================================
- Luồng "nói/câm": coordinator -> (chat_cycle | autonomous_cycle | force_speak_cycle) ->
  speech_pipeline -> LlmService.generate_* -> parser_grounding.DecisionParser -> Decision ->
  state_commit_service._send_decision_to_body -> transport.send_json -> body UdpDecisionParser.
- Luồng "nhớ": chat_cycle -> state_commit_service (ingest/commit) -> memory_kernel/memory_cognition
  -> stores (episodic/semantic/...) -> memory_core/*.json. Recall: memory_recall_adapter ->
  memory_query_* (compile IR -> execute) -> RecallAnswer.
- Luồng "đời sống ngầm": coordinator giữ thought_stream + private_mind_daemon + private_life_daemon
  + subconscious lanes, chạy theo nhịp riêng, ghi inner_diary/anchor -> private_mind_digest ->
  body panel Inner Diary / Mô Hình Ngài.
- Khi 1 hàm cụ thể trong runtime/cortex/memory cần xem từng dòng, mở file tương ứng theo bản đồ
  ở các phần 4–6 (đã ghi đường dẫn + class + method chính). Có thể yêu cầu mở rộng full per-function
  cho riêng 1 file bất kỳ.
