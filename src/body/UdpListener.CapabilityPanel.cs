using Godot;
using System;
using System.Collections.Generic;
using System.Text;
using System.Text.Json;

public partial class UdpListener : Node2D
{
	// V87: panel thống kê + user control. UI không tự ghi score; mọi correction/reset
	// chỉ gửi action có cấu trúc về runtime trusted channel để Mentor tự cập nhật belief.
	private static readonly Vector2 CapabilityPanelPreferredSize = new(980f, 720f);
	private static readonly Vector2 CapabilityPanelMinSize = new(860f, 620f);
	private Panel _capabilityPanel;
	private Button _contextCapabilityButton;
	private VBoxContainer _capabilityContent;
	private Label _capabilityStatus;
	private string _capabilityRequestId = "";
	private bool _capabilityPending;
	private ulong _capabilityRequestAtMs;

	private void InitializeCapabilityPanel()
	{
		_capabilityPanel = new Panel
		{
			Name = "CapabilityPanel",
			Visible = false,
			CustomMinimumSize = CapabilityPanelMinSize,
			Size = CapabilityPanelPreferredSize,
			ZIndex = 99,
		};
		GetNode<Control>("CanvasLayer/Control").AddChild(_capabilityPanel);
		BuildCapabilityPanelUi();
		if (_contextCapabilityButton != null)
			_contextCapabilityButton.Pressed += OnContextCapabilityPressed;
	}

	private void OnContextCapabilityPressed()
	{
		if (_capabilityPanel == null) return;
		if (_capabilityPanel.Visible) CloseCapabilityPanel(); else ShowCapabilityPanel();
	}

	private void ShowCapabilityPanel()
	{
		if (_capabilityPanel == null) return;
		CloseCharacterContextMenu();
		Vector2 viewport = GetViewportRect().Size;
		Vector2 target = new(
			Mathf.Clamp(viewport.X - 120f, CapabilityPanelMinSize.X, CapabilityPanelPreferredSize.X),
			Mathf.Clamp(viewport.Y - 90f, CapabilityPanelMinSize.Y, CapabilityPanelPreferredSize.Y));
		_capabilityPanel.Size = target;
		_capabilityPanel.Position = new Vector2(
			Mathf.Max(16f, (viewport.X - target.X) * 0.5f),
			Mathf.Max(16f, (viewport.Y - target.Y) * 0.5f));
		_capabilityPanel.Visible = true;
		SendCapabilityPanelRequest();
	}

	private void CloseCapabilityPanel()
	{
		if (_capabilityPanel != null) _capabilityPanel.Visible = false;
	}

	private void BuildCapabilityPanelUi()
	{
		if (_capabilityPanel == null) return;
		_capabilityPanel.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(1f, 0.985f, 0.993f, 0.995f),
			BorderColor = MemoryBorder,
			BorderWidthLeft = 2, BorderWidthTop = 2, BorderWidthRight = 2, BorderWidthBottom = 2,
			CornerRadiusTopLeft = 20, CornerRadiusTopRight = 20,
			CornerRadiusBottomLeft = 20, CornerRadiusBottomRight = 20,
			ShadowColor = new Color(0.55f, 0.10f, 0.30f, 0.20f), ShadowSize = 10,
		});
		_capabilityPanel.ClipContents = true;

		var margin = new MarginContainer();
		margin.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		margin.AddThemeConstantOverride("margin_left", 24);
		margin.AddThemeConstantOverride("margin_right", 24);
		margin.AddThemeConstantOverride("margin_top", 18);
		margin.AddThemeConstantOverride("margin_bottom", 18);
		_capabilityPanel.AddChild(margin);

		var root = new VBoxContainer();
		root.AddThemeConstantOverride("separation", 10);
		margin.AddChild(root);

		var header = new HBoxContainer();
		header.AddThemeConstantOverride("separation", 10);
		root.AddChild(header);
		var title = CreateUiLabel("NĂNG LỰC KỸ THUẬT", 25, MemoryInk);
		title.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		header.AddChild(title);
		var refresh = CreateMemoryButton("Cập nhật", SendCapabilityPanelRequest, primary: false);
		refresh.CustomMinimumSize = new Vector2(96f, 34f);
		header.AddChild(refresh);
		var resetAll = CreateMemoryButton("Đặt lại mô hình", ConfirmResetCapabilityProfile, primary: false, danger: true);
		resetAll.CustomMinimumSize = new Vector2(126f, 34f);
		header.AddChild(resetAll);
		header.AddChild(CreateWindowControlCapsule(() => _capabilityPanel.Visible = false, CloseCapabilityPanel));

		var note = CreateUiLabel("Đây là ước lượng của ERIS từ bằng chứng đã quan sát; không phải điểm thi hay đánh giá con người.", 11, MemoryInkSoft);
		note.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		root.AddChild(note);

		_capabilityStatus = CreateUiLabel("Chưa đọc dữ liệu.", 10, MemoryInkSoft);
		root.AddChild(_capabilityStatus);

		var scroll = new ScrollContainer { SizeFlagsVertical = Control.SizeFlags.ExpandFill, SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		root.AddChild(scroll);
		_capabilityContent = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		_capabilityContent.AddThemeConstantOverride("separation", 12);
		scroll.AddChild(_capabilityContent);
		RenderCapabilityEmpty();
	}

	private void RenderCapabilityEmpty()
	{
		if (_capabilityContent == null) return;
		foreach (Node child in _capabilityContent.GetChildren()) child.QueueFree();
		var card = CreateMemoryCard(new Color(1f, 0.97f, 0.985f, 0.96f), 16);
		var margin = CapabilityCardMargin();
		card.AddChild(margin);
		var text = CreateUiLabel("Chưa có snapshot. Bấm “Cập nhật” để đọc mô hình năng lực hiện tại.", 13, MemoryInkSoft);
		text.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		margin.AddChild(text);
		_capabilityContent.AddChild(card);
	}

	private void SendCapabilityPanelRequest() => SendCapabilityAction("snapshot");

	private void SendCapabilityAction(string action, Dictionary<string, object> extra = null)
	{
		if (_chatSend == null) return;
		_capabilityRequestId = $"capability-{Time.GetTicksMsec()}-{GD.Randi()}";
		var payload = new Dictionary<string, object>
		{
			["type"] = "capability_panel_request",
			["action"] = action,
			["request_id"] = _capabilityRequestId,
		};
		if (extra != null)
			foreach (KeyValuePair<string, object> pair in extra) payload[pair.Key] = pair.Value;
		Error error = _chatSend.PutPacket(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload)));
		if (error != Error.Ok)
		{
			SetCapabilityStatus($"Không gửi được request: {error}", true);
			return;
		}
		_capabilityPending = true;
		_capabilityRequestAtMs = Time.GetTicksMsec();
		SetCapabilityStatus(action == "snapshot" ? "Đang đọc thống kê năng lực..." : "Đang cập nhật mô hình...");
	}

	private bool TryHandleCapabilityPanelPacket(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw)) return false;
		try
		{
			using JsonDocument doc = JsonDocument.Parse(raw);
			JsonElement root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object
				|| !root.TryGetProperty("type", out JsonElement typeNode)
				|| !string.Equals(typeNode.GetString(), "capability_panel_ack", StringComparison.Ordinal))
				return false;
			string requestId = ReadJsonString(root, "request_id");
			if (!string.IsNullOrWhiteSpace(_capabilityRequestId) && !string.IsNullOrWhiteSpace(requestId)
				&& !string.Equals(requestId, _capabilityRequestId, StringComparison.Ordinal)) return true;
			_capabilityPending = false;
			string status = ReadJsonString(root, "status");
			string message = ReadJsonString(root, "message");
			if (root.TryGetProperty("capability_panel", out JsonElement panel) && panel.ValueKind == JsonValueKind.Object)
				ApplyCapabilitySnapshot(panel);
			SetCapabilityStatus(string.IsNullOrWhiteSpace(message) ? "Đã cập nhật." : message, status == "error");
			return true;
		}
		catch (JsonException) { return false; }
		catch (Exception ex)
		{
			SetCapabilityStatus($"Không đọc được thống kê: {ex.Message}", true);
			return true;
		}
	}

	private void ApplyCapabilitySnapshot(JsonElement panel)
	{
		if (_capabilityContent == null) return;
		foreach (Node child in _capabilityContent.GetChildren()) child.QueueFree();
		int total = ReadJsonInt(panel, "tong_bang_chung");
		_capabilityContent.AddChild(CreateCapabilitySectionHeader($"Tổng quan · {total} bằng chứng"));

		if (panel.TryGetProperty("nhom_nang_luc", out JsonElement groups) && groups.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement group in groups.EnumerateArray())
				if (group.ValueKind == JsonValueKind.Object) _capabilityContent.AddChild(CreateCapabilityGroupCard(group));
		}

		_capabilityContent.AddChild(CreateCapabilitySectionHeader("Mục tiêu đang theo dõi"));
		if (panel.TryGetProperty("muc_tieu_hien_tai", out JsonElement goals) && goals.ValueKind == JsonValueKind.Array && goals.GetArrayLength() > 0)
		{
			foreach (JsonElement goal in goals.EnumerateArray())
				if (goal.ValueKind == JsonValueKind.Object) _capabilityContent.AddChild(CreateDevelopmentGoalCard(goal));
		}
		else
			_capabilityContent.AddChild(CreateUiLabel("Chưa theo dõi mục tiêu nào. Bạn có thể chọn một đề xuất dài hạn ở bên dưới.", 11, MemoryInkSoft));

		if (panel.TryGetProperty("thong_ke_phat_trien_30_ngay", out JsonElement developmentStats) && developmentStats.ValueKind == JsonValueKind.Object)
			_capabilityContent.AddChild(CreateDevelopmentStatsCard(developmentStats));

		_capabilityContent.AddChild(CreateCapabilitySectionHeader("SỨC KHỎE DỰ ÁN · 30 NGÀY"));
		if (panel.TryGetProperty("du_an_30_ngay", out JsonElement project) && project.ValueKind == JsonValueKind.Object)
			_capabilityContent.AddChild(CreateProjectTrajectoryCard(project));
		else
			_capabilityContent.AddChild(CreateUiLabel("Chưa đủ CodingObservation để thống kê project.", 11, MemoryInkSoft));

		if (panel.TryGetProperty("ghep_user_du_an", out JsonElement userProjectFit) && userProjectFit.ValueKind == JsonValueKind.Object)
			_capabilityContent.AddChild(CreateUserProjectFitCard(userProjectFit));

		_capabilityContent.AddChild(CreateCapabilitySectionHeader("Xu hướng 30 ngày"));
		if (panel.TryGetProperty("xu_huong_30_ngay", out JsonElement trend) && trend.ValueKind == JsonValueKind.Array)
			_capabilityContent.AddChild(CreateTrendCard(trend));

		_capabilityContent.AddChild(CreateCapabilitySectionHeader("Khả năng sử dụng công cụ"));
		if (panel.TryGetProperty("cong_cu", out JsonElement tools) && tools.ValueKind == JsonValueKind.Array)
			_capabilityContent.AddChild(CreateToolStatsCard(tools));

		_capabilityContent.AddChild(CreateCapabilitySectionHeader("Thói quen làm việc với AI · 30 ngày"));
		if (panel.TryGetProperty("thoi_quen_ai_30_ngay", out JsonElement ai) && ai.ValueKind == JsonValueKind.Object)
			_capabilityContent.AddChild(CreateAiStatsCard(ai));

		_capabilityContent.AddChild(CreateCapabilitySectionHeader("Đề xuất dài hạn"));
		if (panel.TryGetProperty("de_xuat_dai_han", out JsonElement recs) && recs.ValueKind == JsonValueKind.Array && recs.GetArrayLength() > 0)
		{
			foreach (JsonElement rec in recs.EnumerateArray())
				if (rec.ValueKind == JsonValueKind.Object) _capabilityContent.AddChild(CreateRecommendationCard(rec));
		}
		else
		{
			var label = CreateUiLabel("Chưa đủ dữ liệu để đưa đề xuất dài hạn đáng tin.", 12, MemoryInkSoft);
			_capabilityContent.AddChild(label);
		}
	}

	private Control CreateCapabilitySectionHeader(string text)
	{
		var label = CreateUiLabel(text, 16, MemoryInk);
		label.CustomMinimumSize = new Vector2(0f, 30f);
		return label;
	}

	private Control CreateCapabilityGroupCard(JsonElement group)
	{
		var card = CreateMemoryCard(new Color(1f, 0.985f, 0.993f, 0.97f), 14);
		var margin = CapabilityCardMargin(); card.AddChild(margin);
		var box = new VBoxContainer(); box.AddThemeConstantOverride("separation", 6); margin.AddChild(box);
		string title = ReadJsonString(group, "ten");
		bool observed = ReadJsonBool(group, "da_du_bang_chung");
		int score = ReadJsonInt(group, "phan_tram");
		string confidence = ReadJsonString(group, "do_tin_cay");
		int evidence = ReadJsonInt(group, "so_bang_chung");
		var row = new HBoxContainer(); box.AddChild(row);
		var left = CreateUiLabel(title, 15, MemoryInk); left.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill; row.AddChild(left);
		row.AddChild(CreateUiLabel(observed ? $"{score}%" : "Chưa đủ dữ liệu", 14, observed ? MemoryPink : MemoryInkSoft));
		box.AddChild(CreateUiLabel(observed ? $"Độ tin cậy: {confidence} · {evidence} bằng chứng" : $"{evidence} bằng chứng · cần thêm dữ liệu trước khi chấm %", 10, MemoryInkSoft));
		if (observed)
		{
			var bar = new ProgressBar { MinValue = 0, MaxValue = 100, Value = score, ShowPercentage = false, CustomMinimumSize = new Vector2(0f, 8f) };
			box.AddChild(bar);
		}
		if (group.TryGetProperty("ky_nang", out JsonElement skills) && skills.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement skill in skills.EnumerateArray())
			{
				string skillId = ReadJsonString(skill, "id");
				string name = ReadJsonString(skill, "ten"); bool known = ReadJsonBool(skill, "da_du_bang_chung"); int pct = ReadJsonInt(skill, "phan_tram"); int ev = ReadJsonInt(skill, "so_bang_chung");
				var skillBox = new VBoxContainer(); skillBox.AddThemeConstantOverride("separation", 3); box.AddChild(skillBox);
				skillBox.AddChild(CreateUiLabel($"• {name}: {(known ? pct + "%" : "Chưa đủ dữ liệu")} · {ev} bằng chứng", 10, known ? MemoryInk : MemoryInkSoft));

				if (skill.TryGetProperty("bang_chung_gan_day", out JsonElement evidenceRows) && evidenceRows.ValueKind == JsonValueKind.Array)
				{
					int shown = 0;
					foreach (JsonElement evidence in evidenceRows.EnumerateArray())
					{
						if (shown++ >= 3 || evidence.ValueKind != JsonValueKind.Object) break;
						string desc = ReadJsonString(evidence, "mo_ta");
						if (!string.IsNullOrWhiteSpace(desc)) skillBox.AddChild(CreateUiLabel("   ↳ " + desc, 9, MemoryInkSoft));
					}
				}

				var actions = new HBoxContainer(); actions.AddThemeConstantOverride("separation", 5); skillBox.AddChild(actions);
				actions.AddChild(CreateCapabilityMiniButton("Đúng", () => SendSkillFeedback(skillId, "confirmed")));
				actions.AddChild(CreateCapabilityMiniButton("Tôi đã biết", () => SendSkillFeedback(skillId, "already_knew")));
				actions.AddChild(CreateCapabilityMiniButton("Đánh giá sai", () => SendSkillFeedback(skillId, "wrong")));
				actions.AddChild(CreateCapabilityMiniButton("Đặt lại", () => SendSkillFeedback(skillId, "reset"), danger: true));
			}
		}
		return card;
	}

\tprivate Control CreateProjectTrajectoryCard(JsonElement project)
\t{
\t\tvar card = CreateMemoryCard(new Color(0.975f, 0.99f, 0.985f, 0.97f), 14, new Color(0.28f, 0.56f, 0.46f));
\t\tvar margin = CapabilityCardMargin(); card.AddChild(margin);
\t\tvar box = new VBoxContainer(); box.AddThemeConstantOverride("separation", 6); margin.AddChild(box);
\t\tif (!project.TryGetProperty("tong_quan", out JsonElement summary) || summary.ValueKind != JsonValueKind.Object)
\t\t{
\t\t\tbox.AddChild(CreateUiLabel("Chưa đủ dữ liệu project.", 10, MemoryInkSoft));
\t\t\treturn card;
\t\t}
\t\tint tasks = ReadJsonInt(summary, "task_da_quan_sat");
\t\tbox.AddChild(CreateUiLabel($"Task đã quan sát: {tasks} · hoàn thành {ReadJsonInt(summary, "task_hoan_thanh")} · fail {ReadJsonInt(summary, "task_that_bai")}", 11, MemoryInk));
\t\tbox.AddChild(CreateUiLabel($"Có thay đổi file: {ReadJsonInt(summary, "task_co_thay_doi_file")} · có test: {ReadJsonInt(summary, "task_co_test")} · test fail: {ReadJsonInt(summary, "task_co_test_fail")}", 10, MemoryInkSoft));
\t\tint noVerify = ReadJsonInt(summary, "task_thieu_verification_co_cau_truc");
\t\tif (noVerify > 0) box.AddChild(CreateUiLabel($"Thiếu verification có cấu trúc: {noVerify} task", 10, MemoryInkSoft));

\t\tif (project.TryGetProperty("subsystem", out JsonElement subsystems) && subsystems.ValueKind == JsonValueKind.Array && subsystems.GetArrayLength() > 0)
\t\t{
\t\t\tbox.AddChild(CreateUiLabel("Subsystem nổi bật", 11, MemoryInk));
\t\t\tint shown = 0;
\t\t\tforeach (JsonElement item in subsystems.EnumerateArray())
\t\t\t{
\t\t\t\tif (shown++ >= 5 || item.ValueKind != JsonValueKind.Object) break;
\t\t\t\tbox.AddChild(CreateUiLabel($"• {ReadJsonString(item, "ten")}: {ReadJsonInt(item, "so_task")} task · tín hiệu ổn định {ReadJsonString(item, "tin_hieu_on_dinh")}", 10, MemoryInkSoft));
\t\t\t}
\t\t}

\t\tif (project.TryGetProperty("diem_nong", out JsonElement hotspots) && hotspots.ValueKind == JsonValueKind.Array && hotspots.GetArrayLength() > 0)
\t\t{
\t\t\tbox.AddChild(CreateUiLabel("Điểm nóng", 11, MemoryInk));
\t\t\tint shown = 0;
\t\t\tforeach (JsonElement item in hotspots.EnumerateArray())
\t\t\t{
\t\t\t\tif (shown++ >= 4 || item.ValueKind != JsonValueKind.Object) break;
\t\t\t\tbox.AddChild(CreateUiLabel($"• {ReadJsonString(item, "file")}: {ReadJsonInt(item, "so_task_cham")} task chạm", 10, MemoryInkSoft));
\t\t\t}
\t\t\tbox.AddChild(CreateUiLabel("Tần suất sửa chỉ là tín hiệu quan sát; không đồng nghĩa code xấu.", 9, MemoryInkSoft));
\t\t}

\t\tif (project.TryGetProperty("no_ky_thuat_ung_vien", out JsonElement debts) && debts.ValueKind == JsonValueKind.Array && debts.GetArrayLength() > 0)
\t\t{
\t\t\tbox.AddChild(CreateUiLabel("Nợ kỹ thuật ứng viên", 11, MemoryInk));
\t\t\tint shown = 0;
\t\t\tforeach (JsonElement item in debts.EnumerateArray())
\t\t\t{
\t\t\t\tif (shown++ >= 4 || item.ValueKind != JsonValueKind.Object) break;
\t\t\t\tvar label = CreateUiLabel($"[{ReadJsonString(item, "muc")}] {ReadJsonString(item, "tieu_de")}\n{ReadJsonString(item, "evidence")}", 10, MemoryInkSoft);
\t\t\t\tlabel.AutowrapMode = TextServer.AutowrapMode.WordSmart; box.AddChild(label);
\t\t\t}
\t\t}

\t\tif (project.TryGetProperty("uu_tien_de_xuat", out JsonElement priorities) && priorities.ValueKind == JsonValueKind.Array && priorities.GetArrayLength() > 0)
\t\t{
\t\t\tbox.AddChild(CreateUiLabel("Ưu tiên 2–4 tuần", 11, MemoryInk));
\t\t\tint shown = 0;
\t\t\tforeach (JsonElement item in priorities.EnumerateArray())
\t\t\t{
\t\t\t\tif (shown++ >= 3 || item.ValueKind != JsonValueKind.Object) break;
\t\t\t\tvar label = CreateUiLabel($"{shown}. {ReadJsonString(item, "tieu_de")} · {ReadJsonString(item, "uu_tien")}\n{ReadJsonString(item, "ly_do")}", 10, MemoryInkSoft);
\t\t\t\tlabel.AutowrapMode = TextServer.AutowrapMode.WordSmart; box.AddChild(label);
\t\t\t}
\t\t}
\t\treturn card;
\t}

\tprivate Control CreateUserProjectFitCard(JsonElement fit)
\t{
\t\tvar card = CreateMemoryCard(new Color(0.985f, 0.985f, 1f, 0.96f), 12, new Color(0.38f, 0.48f, 0.78f));
\t\tvar margin = CapabilityCardMargin(); card.AddChild(margin);
\t\tvar box = new VBoxContainer(); box.AddThemeConstantOverride("separation", 4); margin.AddChild(box);
\t\tbox.AddChild(CreateUiLabel("BẠN × DỰ ÁN", 11, MemoryInk));
\t\tbool enough = ReadJsonBool(fit, "co_du_lieu");
\t\tstring note = enough ? ReadJsonString(fit, "goi_y") : ReadJsonString(fit, "ghi_chu");
\t\tvar label = CreateUiLabel(string.IsNullOrWhiteSpace(note) ? "Chưa đủ dữ liệu để ghép năng lực với nhu cầu project." : note, 10, MemoryInkSoft);
\t\tlabel.AutowrapMode = TextServer.AutowrapMode.WordSmart; box.AddChild(label);
\t\treturn card;
\t}

	private Control CreateTrendCard(JsonElement trend)
	{
		var card = CreateMemoryCard(new Color(1f, 0.99f, 0.995f, 0.96f), 14);
		var margin = CapabilityCardMargin(); card.AddChild(margin);
		var box = new VBoxContainer(); box.AddThemeConstantOverride("separation", 5); margin.AddChild(box);
		foreach (JsonElement row in trend.EnumerateArray())
		{
			string id = ReadJsonString(row, "id");
			string name = id switch { "debugging" => "Gỡ lỗi", "architecture" => "Kiến trúc", "verification" => "Kiểm chứng", "ai_operation" => "Vận hành AI", _ => id };
			string label = ReadJsonString(row, "nhan");
			string text = label == "Chưa đủ lịch sử" ? $"{name}: Chưa đủ lịch sử" : $"{name}: {ReadJsonInt(row, "delta"):+#;-#;0}% · {label}";
			box.AddChild(CreateUiLabel(text, 10, label == "Chưa đủ lịch sử" ? MemoryInkSoft : MemoryInk));
		}
		return card;
	}

	private Control CreateToolStatsCard(JsonElement tools)
	{
		var card = CreateMemoryCard(new Color(0.985f, 0.975f, 1f, 0.96f), 14);
		var margin = CapabilityCardMargin(); card.AddChild(margin);
		var box = new VBoxContainer(); box.AddThemeConstantOverride("separation", 5); margin.AddChild(box);
		foreach (JsonElement tool in tools.EnumerateArray())
		{
			string name = ReadJsonString(tool, "ten"); string stage = ReadJsonString(tool, "muc_do"); int count = ReadJsonInt(tool, "so_lan_chung_minh");
			box.AddChild(CreateUiLabel($"{name}  —  {stage}{(count > 0 ? $" · {count} lần có evidence" : "")}", 10, stage == "Chưa đủ dữ liệu" ? MemoryInkSoft : MemoryInk));
		}
		return card;
	}

	private Control CreateAiStatsCard(JsonElement ai)
	{
		var card = CreateMemoryCard(new Color(1f, 0.97f, 0.985f, 0.96f), 14);
		var margin = CapabilityCardMargin(); card.AddChild(margin);
		var box = new VBoxContainer(); box.AddThemeConstantOverride("separation", 5); margin.AddChild(box);
		box.AddChild(CreateUiLabel($"Lượt kỹ thuật đã quan sát: {ReadJsonInt(ai, "luot_ky_thuat_da_quan_sat")}", 11, MemoryInk));
		box.AddChild(CreateUiLabel($"Tự nêu giả thuyết có evidence: {ReadJsonInt(ai, "tu_neu_gia_thuyet_co_evidence")}", 10, MemoryInkSoft));
		box.AddChild(CreateUiLabel($"Chủ động kiểm chứng: {ReadJsonInt(ai, "chu_dong_kiem_chung")}", 10, MemoryInkSoft));
		box.AddChild(CreateUiLabel($"Chủ động học hỏi: {ReadJsonInt(ai, "chu_dong_hoc_hoi")}", 10, MemoryInkSoft));
		box.AddChild(CreateUiLabel($"Yêu cầu thực thi mù: {ReadJsonInt(ai, "yeu_cau_thuc_thi_mu")}", 10, MemoryInkSoft));
		box.AddChild(CreateUiLabel($"Chỉ số rủi ro phụ thuộc AI: {ReadJsonInt(ai, "rui_ro_phu_thuoc_ai")}% (không phải điểm năng lực)", 10, MemoryInkSoft));
		return card;
	}

	private Control CreateRecommendationCard(JsonElement rec)
	{
		var card = CreateMemoryCard(new Color(0.985f, 0.965f, 1f, 0.94f), 14, new Color(0.64f, 0.38f, 0.88f));
		var margin = CapabilityCardMargin(); card.AddChild(margin);
		var box = new VBoxContainer(); box.AddThemeConstantOverride("separation", 4); margin.AddChild(box);
		box.AddChild(CreateUiLabel(ReadJsonString(rec, "tieu_de"), 13, MemoryInk));
		box.AddChild(CreateUiLabel($"Ưu tiên: {ReadJsonString(rec, "uu_tien")} · Thời hạn: {ReadJsonString(rec, "thoi_han")}", 10, MemoryPink));
		var reason = CreateUiLabel("Lý do: " + ReadJsonString(rec, "ly_do"), 10, MemoryInkSoft); reason.AutowrapMode = TextServer.AutowrapMode.WordSmart; box.AddChild(reason);
		var practice = CreateUiLabel("Thực hành: " + ReadJsonString(rec, "thuc_hanh"), 10, MemoryInkSoft); practice.AutowrapMode = TextServer.AutowrapMode.WordSmart; box.AddChild(practice);
		var success = CreateUiLabel("Dấu hiệu tiến bộ: " + ReadJsonString(rec, "dau_hieu_tien_bo"), 10, MemoryInkSoft); success.AutowrapMode = TextServer.AutowrapMode.WordSmart; box.AddChild(success);
		string recId = ReadJsonString(rec, "id");
		if (!string.IsNullOrWhiteSpace(recId))
		{
			var follow = CreateCapabilityMiniButton("Theo dõi mục này", () => SendCapabilityAction("follow_recommendation", new Dictionary<string, object> { ["recommendation_id"] = recId }));
			follow.CustomMinimumSize = new Vector2(138f, 28f);
			box.AddChild(follow);
		}
		return card;
	}

	private void ConfirmResetCapabilityProfile()
	{
		if (_capabilityPanel == null) return;
		var dialog = new ConfirmationDialog
		{
			Title = "Đặt lại mô hình năng lực",
			DialogText = "Thao tác này đặt lại toàn bộ estimate kỹ năng kỹ thuật của ERIS. Lịch sử calibration và các mục tiêu đang theo dõi vẫn được giữ. Bạn có chắc không?",
			OkButtonText = "Đặt lại",
			CancelButtonText = "Hủy",
			Size = new Vector2I(560, 220),
		};
		_capabilityPanel.AddChild(dialog);
		dialog.Confirmed += () =>
		{
			SendCapabilityAction("reset_profile");
			dialog.QueueFree();
		};
		dialog.Canceled += () => dialog.QueueFree();
		dialog.PopupCentered();
	}

	private void SendSkillFeedback(string skillId, string feedback)
	{
		if (string.IsNullOrWhiteSpace(skillId)) return;
		SendCapabilityAction("skill_feedback", new Dictionary<string, object>
		{
			["skill_id"] = skillId,
			["feedback"] = feedback,
		});
	}

	private Button CreateCapabilityMiniButton(string text, Action pressed, bool danger = false)
	{
		var button = CreateMemoryButton(text, pressed, primary: false, danger: danger);
		button.CustomMinimumSize = new Vector2(92f, 26f);
		button.AddThemeFontSizeOverride("font_size", 9);
		return button;
	}

	private Control CreateDevelopmentGoalCard(JsonElement goal)
	{
		var card = CreateMemoryCard(new Color(0.975f, 0.985f, 1f, 0.96f), 14, new Color(0.34f, 0.52f, 0.86f));
		var margin = CapabilityCardMargin(); card.AddChild(margin);
		var box = new VBoxContainer(); box.AddThemeConstantOverride("separation", 5); margin.AddChild(box);
		string goalId = ReadJsonString(goal, "id");
		box.AddChild(CreateUiLabel(ReadJsonString(goal, "tieu_de"), 13, MemoryInk));
		int progress = ReadJsonInt(goal, "tien_do");
		int gained = ReadJsonInt(goal, "da_them_bang_chung");
		int target = ReadJsonInt(goal, "muc_tieu_bang_chung");
		box.AddChild(CreateUiLabel($"Tiến độ evidence: {gained}/{target} · {progress}%", 10, MemoryInkSoft));
		var bar = new ProgressBar { MinValue = 0, MaxValue = 100, Value = progress, ShowPercentage = false, CustomMinimumSize = new Vector2(0f, 7f) }; box.AddChild(bar);
		var practice = CreateUiLabel("Thực hành: " + ReadJsonString(goal, "thuc_hanh"), 10, MemoryInkSoft); practice.AutowrapMode = TextServer.AutowrapMode.WordSmart; box.AddChild(practice);
		if (!string.IsNullOrWhiteSpace(goalId))
			box.AddChild(CreateCapabilityMiniButton("Dừng theo dõi", () => SendCapabilityAction("stop_goal", new Dictionary<string, object> { ["goal_id"] = goalId }), danger: true));
		return card;
	}

	private Control CreateDevelopmentStatsCard(JsonElement stats)
	{
		var card = CreateMemoryCard(new Color(1f, 0.99f, 0.995f, 0.96f), 12);
		var margin = CapabilityCardMargin(); card.AddChild(margin);
		var box = new VBoxContainer(); box.AddThemeConstantOverride("separation", 4); margin.AddChild(box);
		box.AddChild(CreateUiLabel("Thống kê phát triển · 30 ngày", 11, MemoryInk));
		box.AddChild(CreateUiLabel($"Mục tiêu hoàn thành: {ReadJsonInt(stats, "muc_tieu_hoan_thanh")} · Đang theo dõi: {ReadJsonInt(stats, "muc_tieu_dang_theo_doi")}", 10, MemoryInkSoft));
		box.AddChild(CreateUiLabel($"Đã dừng: {ReadJsonInt(stats, "muc_tieu_da_dung")} · Lần bạn sửa đánh giá ERIS: {ReadJsonInt(stats, "lan_user_sua_danh_gia")}", 10, MemoryInkSoft));
		return card;
	}

	private static MarginContainer CapabilityCardMargin()
	{
		var margin = new MarginContainer();
		margin.AddThemeConstantOverride("margin_left", 14); margin.AddThemeConstantOverride("margin_right", 14);
		margin.AddThemeConstantOverride("margin_top", 10); margin.AddThemeConstantOverride("margin_bottom", 10);
		return margin;
	}

	private void TickCapabilityPanelStatus()
	{
		if (!_capabilityPending) return;
		if (Time.GetTicksMsec() - _capabilityRequestAtMs > 6500UL)
		{
			_capabilityPending = false;
			SetCapabilityStatus("Brain chưa trả lời; thử bấm Cập nhật lại.", true);
		}
	}

	private void SetCapabilityStatus(string text, bool error = false)
	{
		if (_capabilityStatus == null) return;
		_capabilityStatus.Text = text;
		_capabilityStatus.AddThemeColorOverride("font_color", error ? new Color(0.76f, 0.18f, 0.28f) : MemoryInkSoft);
	}
}
