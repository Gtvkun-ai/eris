# Product

Eris la mot AI coding assistant tich hop vao VS Code, su dung Gemini (qua WebAI proxy) lam LLM chinh.

## Muc tieu
- Co-pilot + agent: vua hoi dap, vua tu dong hoa task lap trinh
- Khong can API key — xac thuc qua Google cookie (WebAI-to-API proxy tai localhost:8081)
- Long-term memory: ghi nho user, project, preferences giua cac phien

## Nguoi dung
- Developer don le lam viec tren Windows, dung VS Code
- Uu tien: toc do, chinh xac, giu nguyen code hien co (khong refactor lung tung)

## Nguyen tac uu tien
1. Khong pha code dang hoat dong
2. Fallback graceful neu component khong available (bridge down, etc.)
3. Eris la "shell UI" — logic nam o Python Brain, extension chi render
