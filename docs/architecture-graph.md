# ERIS — Sơ đồ kiến trúc (graph)

Tài liệu này tóm tắt repo bằng sơ đồ Mermaid cho dễ nhìn. Đọc kèm `tongquat.txt`
(bản đồ file-to-file chi tiết) và `README.md` (cài đặt/cấu hình).

> Mẹo: mở file này trong Kiro hoặc GitHub để xem Mermaid render thành hình.

---

## 1. Hai nửa hệ thống (Body ↔ Cortex qua UDP)

```mermaid
flowchart LR
    subgraph BODY["🧍 BODY — Godot 4.6 .NET (body/*.cs)"]
        UL["UdpListener<br/>node chính, vẽ text+animation"]
        UDP_PARSE["UdpDecisionParser<br/>parse JSON Decision"]
        MOTION["MotionController<br/>vật lý di chuyển"]
        AUTO_BODY["LocalBodyAutonomy<br/>tự đi lại khi idle"]
        AUDIO["BodyAudioController"]
        SPAWN["ErisProcessManager<br/>spawn vision.py + inject env"]
    end

    subgraph CORTEX["🧠 CORTEX / RUNTIME — Python (src/*)"]
        VISION["vision.py<br/>ENTRY POINT"]
        COORD["RuntimeCoordinator<br/>(coordinator.py) — TRUNG TÂM"]
    end

    SPAWN -->|"spawn process"| VISION
    VISION --> COORD
    COORD -->|"UDP 4242 — Decision<br/>(text, animation, motion)"| UL
    UL -->|"UDP 4243 — event/chat<br/>(chat, force_speak, touch)"| COORD
    UL --> UDP_PARSE --> MOTION
    UL --> AUDIO
    UL -. idle .-> AUTO_BODY
```

---

## 2. Bản đồ thư mục `src/` (vai trò từng nhóm)

```mermaid
flowchart TB
    ENTRY["vision.py<br/>entry point"]

    subgraph CORE["core/ — nền tảng"]
        CF["cognitive_frame.py"]
        EV["evidence.py / evidence_normalizer.py"]
    end

    subgraph CX["cortex/ — các tầng nhận thức"]
        NTF["ni.py · ti.py · fe.py"]
        MEAN["meaning/ · personality.py"]
        AFF["appraisal.py · affect_semantics.py"]
        ATT["attention_salience.py"]
        WM["working_memory.py · global_workspace.py"]
        THO["thought_stream.py · subconscious/"]
        PRIV["private_mind/ · private_life/"]
        SPCH["speech_core.py · surface_arbiter.py · micro_policy.py"]
    end

    subgraph RT["runtime/ — điều phối"]
        COORD["coordinator.py + mixins<br/>(chat / autonomous / cognitive cycle)"]
        PIPE["speech_pipeline · cognitive_pipeline"]
        DAEMON["private_mind_daemon · private_life_daemon · subconscious_loop"]
        POLICY["model_budget · no_fallback · ambient_silence"]
    end

    subgraph MEM["memory/ — trí nhớ phân tầng"]
        KERNEL["memory_kernel.py · memory_cognition.py"]
        LAYERS["episodic · semantic · relational<br/>procedural · affective_residue"]
        RETR["retrieval_engine · commit_policy · consolidator"]
        EMB["embedding_index<br/>(MiniLM-L12-v2)"]
    end

    subgraph LLM["llm/ — gọi model"]
        SVC["service.py (LlmService)"]
        CLIENTS["client · ollama · llamacpp"]
        POOL["key_pool.py (xoay key 429)"]
    end

    PARSE["parser_grounding/ + domain/decision.py"]
    ACT["actions/ — router · executor"]
    TRANS["transport/udp.py"]
    TELE["telemetry/ — màn hình/ngữ cảnh"]

    ENTRY --> COORD
    ENTRY --> SVC
    ENTRY --> KERNEL
    ENTRY --> TRANS
    COORD --> CX
    COORD --> CORE
    COORD --> RT
    COORD --> MEM
    COORD --> PIPE
    PIPE --> LLM
    PIPE --> PARSE --> ACT
    COORD --> TRANS
    COORD --> TELE
    SVC --> POOL
    MEM --> EMB
```

---

## 3. Luồng dữ liệu — lượt chat của user

```mermaid
sequenceDiagram
    participant U as User (panel)
    participant B as Body (UdpListener)
    participant C as Coordinator
    participant P as SpeechPipeline
    participant L as LlmService → LLM remote
    participant M as Memory

    U->>B: gõ chat
    B->>C: UDP 4243 (chat text)
    C->>C: meaning + personality + appraisal/affect
    C->>M: recall ký ức liên quan
    C->>P: dựng prompt
    P->>L: gọi model (Gemini/Groq, pool key)
    L-->>P: text thô
    P->>P: parse → Decision, filters, repeat guard, surface arbiter
    P-->>C: Decision
    C->>B: UDP 4242 (Decision: text + animation)
    B->>U: hiện bong bóng thoại + animation
```

---

## 4. Vòng tự chủ (autonomous — khi không chat)

```mermaid
flowchart TB
    LOOP["coordinator.run_loop()"] --> TELE["telemetry + vision facts"]
    TELE --> OBS["signal_buffer / background_observer<br/>→ ObserverFrame"]
    OBS --> CP["CognitivePipeline"]
    CP --> S1["RawSignal → EvidenceItem"]
    S1 --> S2["CognitiveFrame"]
    S2 --> S3["AttentionSalience"]
    S3 --> S4["CognitiveBudget<br/>fast/normal/deep/reflection"]
    S4 --> S5["WorkingMemory → GlobalWorkspace"]
    S5 --> WAKE{"AutonomousWakeGovernor<br/>có 'thức dậy nói'?"}
    WAKE -->|"có"| DEC["dựng Decision → UDP 4242 → Body"]
    WAKE -->|"không"| SILENT["im lặng (silence_debt)"]

    LOOP -. song song .-> BG["thought_stream · private_mind_daemon<br/>private_life_daemon · subconscious lanes"]
    BG --> STATE["ghi state ra memory_core/*.json"]
```

---

## 5. State trên đĩa (đọc khi debug "nhớ/quên gì")

```mermaid
flowchart LR
    subgraph MC["memory_core/ — state runtime (không commit git)"]
        EP["episodic / semantic / relational<br/>procedural / affective_residue"]
        MIND["agent_mind · inner_diary · thought_stream"]
        LIFE["private_concerns · private_life_state · anchor_state"]
        USER["user_model · active_state_snapshot"]
    end
    subgraph ROOT["root"]
        LTM["long_term_memory.json"]
        GOAL["goal_memory.json · goal_profiles.json"]
        LOGS["logs/eris_run_*.txt"]
    end
    subgraph CFG["config / env"]
        SEC["config/secrets.json (API keys, gitignore)"]
        ENVF[".env / .env.example"]
    end
```

---

### Kênh UDP (nhắc nhanh)
- `127.0.0.1:4242` — CORTEX → BODY (Decision: text, animation, motion, debug)
- `127.0.0.1:4243` — BODY → CORTEX (event: chat_start/end, chat text, force_speak, touch)
