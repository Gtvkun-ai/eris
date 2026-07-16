# ERIS â€” SÆ¡ Ä‘á»“ kiáº¿n trÃºc (graph)

TÃ i liá»‡u nÃ y tÃ³m táº¯t repo báº±ng sÆ¡ Ä‘á»“ Mermaid cho dá»… nhÃ¬n. Äá»c kÃ¨m `tongquat.txt`
(báº£n Ä‘á»“ file-to-file chi tiáº¿t) vÃ  `README.md` (cÃ i Ä‘áº·t/cáº¥u hÃ¬nh).

> Máº¹o: má»Ÿ file nÃ y trong Kiro hoáº·c GitHub Ä‘á»ƒ xem Mermaid render thÃ nh hÃ¬nh.

---

## 1. Hai ná»­a há»‡ thá»‘ng (Body â†” Cortex qua UDP)

```mermaid
flowchart LR
    subgraph BODY["ðŸ§ BODY â€” Godot 4.6 .NET (body/*.cs)"]
        UL["UdpListener<br/>node chÃ­nh, váº½ text+animation"]
        UDP_PARSE["UdpDecisionParser<br/>parse JSON Decision"]
        MOTION["MotionController<br/>váº­t lÃ½ di chuyá»ƒn"]
        AUTO_BODY["LocalBodyAutonomy<br/>tá»± Ä‘i láº¡i khi idle"]
        AUDIO["BodyAudioController"]
        SPAWN["ErisProcessManager<br/>spawn vision.py + inject env"]
    end

    subgraph CORTEX["ðŸ§  CORTEX / RUNTIME â€” Python (src/*)"]
        VISION["vision.py<br/>ENTRY POINT"]
        COORD["RuntimeCoordinator<br/>(coordinator.py) â€” TRUNG TÃ‚M"]
    end

    SPAWN -->|"spawn process"| VISION
    VISION --> COORD
    COORD -->|"UDP 4242 â€” Decision<br/>(text, animation, motion)"| UL
    UL -->|"UDP 4243 â€” event/chat<br/>(chat, force_speak, touch)"| COORD
    UL --> UDP_PARSE --> MOTION
    UL --> AUDIO
    UL -. idle .-> AUTO_BODY
```

---

## 2. Báº£n Ä‘á»“ thÆ° má»¥c `src/` (vai trÃ² tá»«ng nhÃ³m)

```mermaid
flowchart TB
    ENTRY["vision.py<br/>entry point"]

    subgraph CORE["core/ â€” ná»n táº£ng"]
        CF["cognitive_frame.py"]
        EV["evidence.py / evidence_normalizer.py"]
    end

    subgraph CX["cortex/ â€” cÃ¡c táº§ng nháº­n thá»©c"]
        NTF["ni.py Â· ti.py Â· fe.py"]
        MEAN["meaning/ Â· personality.py"]
        AFF["appraisal.py Â· affect_semantics.py"]
        ATT["attention_salience.py"]
        WM["working_memory.py Â· global_workspace.py"]
        THO["thought_stream.py Â· subconscious/"]
        PRIV["private_mind/ Â· private_life/"]
        SPCH["speech_core.py Â· surface_arbiter.py Â· micro_policy.py"]
    end

    subgraph RT["runtime/ â€” Ä‘iá»u phá»‘i"]
        COORD["coordinator.py + mixins<br/>(chat / autonomous / cognitive cycle)"]
        PIPE["speech_pipeline Â· cognitive_pipeline"]
        DAEMON["private_mind_daemon Â· private_life_daemon Â· subconscious_loop"]
        POLICY["model_budget Â· no_fallback Â· ambient_silence"]
    end

    subgraph MEM["memory/ â€” trÃ­ nhá»› phÃ¢n táº§ng"]
        KERNEL["memory_kernel.py Â· memory_cognition.py"]
        LAYERS["episodic Â· semantic Â· relational<br/>procedural Â· affective_residue"]
        RETR["retrieval_engine Â· commit_policy Â· consolidator"]
        EMB["embedding_index<br/>(MiniLM-L12-v2)"]
    end

    subgraph LLM["llm/ â€” gá»i model"]
        SVC["service.py (LlmService)"]
        CLIENTS["client - remote providers"]
        POOL["key_pool.py (xoay key 429)"]
    end

    PARSE["parser_grounding/ + domain/decision.py"]
    ACT["actions/ â€” router Â· executor"]
    TRANS["transport/udp.py"]
    TELE["telemetry/ â€” mÃ n hÃ¬nh/ngá»¯ cáº£nh"]

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

## 3. Luá»“ng dá»¯ liá»‡u â€” lÆ°á»£t chat cá»§a user

```mermaid
sequenceDiagram
    participant U as User (panel)
    participant B as Body (UdpListener)
    participant C as Coordinator
    participant P as SpeechPipeline
    participant L as LlmService â†’ LLM remote
    participant M as Memory

    U->>B: gÃµ chat
    B->>C: UDP 4243 (chat text)
    C->>C: meaning + personality + appraisal/affect
    C->>M: recall kÃ½ á»©c liÃªn quan
    C->>P: dá»±ng prompt
    P->>L: gá»i model (Gemini/Groq, pool key)
    L-->>P: text thÃ´
    P->>P: parse â†’ Decision, filters, repeat guard, surface arbiter
    P-->>C: Decision
    C->>B: UDP 4242 (Decision: text + animation)
    B->>U: hiá»‡n bong bÃ³ng thoáº¡i + animation
```

---

## 4. VÃ²ng tá»± chá»§ (autonomous â€” khi khÃ´ng chat)

```mermaid
flowchart TB
    LOOP["coordinator.run_loop()"] --> TELE["telemetry + vision facts"]
    TELE --> OBS["signal_buffer / background_observer<br/>â†’ ObserverFrame"]
    OBS --> CP["CognitivePipeline"]
    CP --> S1["RawSignal â†’ EvidenceItem"]
    S1 --> S2["CognitiveFrame"]
    S2 --> S3["AttentionSalience"]
    S3 --> S4["CognitiveBudget<br/>fast/normal/deep/reflection"]
    S4 --> S5["WorkingMemory â†’ GlobalWorkspace"]
    S5 --> WAKE{"AutonomousWakeGovernor<br/>cÃ³ 'thá»©c dáº­y nÃ³i'?"}
    WAKE -->|"cÃ³"| DEC["dá»±ng Decision â†’ UDP 4242 â†’ Body"]
    WAKE -->|"khÃ´ng"| SILENT["im láº·ng (silence_debt)"]

    LOOP -. song song .-> BG["thought_stream Â· private_mind_daemon<br/>private_life_daemon Â· subconscious lanes"]
    BG --> STATE["ghi state ra memory_core/*.json"]
```

---

## 5. State trÃªn Ä‘Ä©a (Ä‘á»c khi debug "nhá»›/quÃªn gÃ¬")

```mermaid
flowchart LR
    subgraph MC["memory_core/ â€” state runtime (khÃ´ng commit git)"]
        EP["episodic / semantic / relational<br/>procedural / affective_residue"]
        MIND["agent_mind Â· inner_diary Â· thought_stream"]
        LIFE["private_concerns Â· private_life_state Â· anchor_state"]
        USER["user_model Â· active_state_snapshot"]
    end
    subgraph ROOT["root"]
        LTM["long_term_memory.json"]
        GOAL["goal_memory.json Â· goal_profiles.json"]
        LOGS["logs/eris_run_*.txt"]
    end
    subgraph CFG["config / env"]
        SEC["config/secrets.json (API keys, gitignore)"]
        ENVF[".env / .env.example"]
    end
```

---

### KÃªnh UDP (nháº¯c nhanh)
- `127.0.0.1:4242` â€” CORTEX â†’ BODY (Decision: text, animation, motion, debug)
- `127.0.0.1:4243` â€” BODY â†’ CORTEX (event: chat_start/end, chat text, force_speak, touch)
