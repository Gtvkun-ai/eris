# Golden conversational suite của Eris

Chạy:

```powershell
$env:PYTHONPATH="."
python evals/run_social_evals.py
```

Kết quả được ghi vào `evals/results/social_policy_report.json`. Exit code là `2`
nếu pass rate thấp hơn gate. File JSONL là dữ liệu regression, không phải prompt.
Mỗi case thuộc một bucket như permission grant, playful initiation, revoke,
literal trap hoặc ordinary chat.

Khi nối provider thật, hãy ghi output model vào `sample_output` hoặc tạo adapter
đọc file kết quả riêng. Grader hiện chấm act, state transition, literalism,
performative success, brevity và boundary compliance.
