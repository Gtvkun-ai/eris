# Profile parameter INFJ theo góc nhìn người dùng

## Phạm vi điều khiển

- `ParamAngleX`: `-30` là đầu sang trái màn hình, `0` chính diện, `+10` sang phải màn hình.
- `ParamAngleZ`: nghiêng đầu quanh trục Z; runtime chỉ dùng biên nhỏ để tránh tạo dáng quá tay.
- `ParamEyeLOpen`, `ParamEyeROpen`: `0` đóng, `1` mở tối đa. Runtime giữ auto-blink rồi nhân thêm hệ số mí theo mood, nên chớp mắt vẫn đóng hoàn toàn.
- `eyeballxl`, `eyeballxr`: với từng mắt, `-1` hướng vào sống mũi, `+1` hướng ra ngoài. Khi nhìn cùng một phía, hai mắt phải nhận giá trị trái dấu.
- `eyebally`, `eyeballyr`: `-1` nhìn xuống, `+1` nhìn lên.
- `ParamBrowLAngle`, `ParamBrowRAngle`: `-1` thấp/điềm tĩnh/buồn, `0` trung tính, `+1` nhướng. Mood vui không tự động nhướng cả hai lông mày vì sẽ dễ thành ngạc nhiên giả tạo.
- `ParamMouthForm`: `-1` mood xấu/bực, `0` trung tính, `+1` vui.
- `ParamMouthOpenY`: rig riêng của model dùng `-1` đóng, `0` nửa mở, `+1` mở hết.

## Những phần đã tinh chỉnh

1. Gaze bất đối xứng: mắt nhìn vào mũi có biên nhỏ hơn mắt nhìn ra ngoài, giảm cảm giác lé khi nhìn xa.
2. Head follow bất đối xứng đúng với miền `-30..+10`: sang trái có biên lớn hơn sang phải, nhưng cursor tracking chỉ dùng một phần nhỏ của toàn miền.
3. Mí mắt được phối với auto-blink bằng phép nhân, không ghi đè giá trị blink.
4. Lip-sync đổi đúng từ độ mở chuẩn hóa `0..1` sang miền miệng `-1..1`, có hai nhịp lệch pha và easing nhanh hơn phần đầu/mày.
5. Biểu cảm vui giữ lông mày gần trung tính; tease/curious mới dùng nhướng lệch một bên.
6. Physics tóc chuyển sang 60 FPS, normalization Angle X `-30..+10`, giảm input/output và làm các tầng tóc mềm dần để bớt giật.

## Giới hạn của gói hiện tại

`infj.moc3` là embedded binary đã compile. Không nên sửa trực tiếp binary vì không có thông tin keyform/mesh an toàn để tái tạo. Những thay đổi trong gói này nằm ở runtime, metadata và `physics3.json`.

Muốn chỉnh thật sự hình dáng mắt, lông mày, miệng hoặc mesh ở từng keyform cần file nguồn `.cmo3` rồi export lại `.moc3` bằng Live2D Cubism Editor.

## Affect nền và idle có nhịp

Runtime nhận thêm event `affect_state` chỉ chứa vector số đã chuẩn hóa. Affect nền dùng biên nhỏ và có quán tính; emotion của câu nói là lớp tạm thời ưu tiên cao hơn rồi decay về affect nền sau khi audio kết thúc.

Idle không còn chỉ là hai sóng sin cố định. `IdleDirector` lên lịch các gesture ngắn như liếc mắt, nghiêng đầu, soften, ponder và slow blink, có easing vào/ra và dừng khi đang nói. Private mind/DeepSeek chỉ được phép thúc nhẹ pose `ponder` thông qua `thought_pressure`, không điều khiển parameter trực tiếp.

Chi tiết kỹ thuật: `LIVE2D_AFFECT_IDLE_VI.md`.
