# Requirements Document

## Introduction

Mục tiêu (nguyên văn của người dùng):

> "Định nghĩa lại cách nhân vật AI 'sống'. Repo hiện đã thêm rất nhiều tầng nhận thức nhưng khi chạy tự hành (idle/autonomous) nó vẫn nhìn như đã chết: cứ lải nhải đúng 2 câu generic 'Khoảng yên này vẫn giữ chỗ' / 'Nhịp này vẫn yên thêm chút' suốt cả tiếng."

This feature redesigns the autonomous (idle) presence loop of the Eris/Monika AI VTuber character so that, while running without user interaction, the character appears *alive* rather than dead. User-facing chat already works and the LLM API fallback already works; this spec scopes only the autonomous presence path.

The core problem is that "alive" has never been defined in observable terms, so the loop degrades to two generic filler lines for an hour. This document defines "sống / alive" as a set of measurable, verifiable behaviors and captures them as EARS-format acceptance criteria.

The redesign is grounded in four confirmed root causes in the current code:

1. **Screen facts are discarded or out-ranked.** In `surface_seed_compiler.py`, `_from_vision` filters real OCR facts through `_is_specific_vision_fact`, and even when a fact passes, its confidence is capped (`confidence=max(0.40, cue_conf, 0.50)`), so it always loses `_rank_key` to a generic `private_life` seed at confidence 0.74. The character sees the screen ("Kiro editing eris") for an hour but never grounds a line in it.
2. **Short memory seeds are dropped.** `_from_memory_resonance` requires `_is_rich_memory_seed`, discarding short but valid memory seeds.
3. **The fallback emits exactly the banned lines.** When generation fails, `presence_controller._local_micro_presence_fallback_text` returns "Khoảng yên này vẫn giữ chỗ." / "Nhịp này vẫn yên thêm chút." — the same strings `service.py` (~line 2709) explicitly instructs the LLM to avoid as "stale micro templates".
4. **Repetition slips the guard and proactivity is gated off.** `micro_repeat_guard` only blocks `exact_micro_line_repeat` inside a 90s window, but idle cycles are 60–120s apart, so repeats pass. Separately, when `[ti auto] mode=pattern_muse` grants permission to "pull its own topic", `_should_hold_ambient_silence` immediately skips it with `[directive skipped] ambient_silence mode=pattern_muse cooldown=150s`.

## Glossary

- **Autonomous_Presence_Loop**: The runtime cycle (driven by `autonomous_cycle.py` / `coordinator.py`) that runs while there is no active user interaction, deciding each cycle whether the character speaks, performs a body-only action, or stays silent. Synonym for the "idle" / "tự hành" loop.
- **Idle_Cycle**: One iteration of the Autonomous_Presence_Loop. In the current system these occur approximately every 60–120 seconds.
- **Autonomous_Line**: A short spoken line emitted by the Autonomous_Presence_Loop (not a chat reply).
- **Surface_Seed_Compiler**: The component (`surface_seed_compiler.py`) that turns scattered internal pressure (vision, memory, thought stream, private life) into one public-safe seed for wording.
- **Vision_Fact**: A public-safe observation derived from screen capture/OCR (e.g. an active window title), exposed via `snapshot.vision_facts`.
- **Memory_Seed**: A candidate seed sourced from memory resonance activations.
- **Micro_Repeat_Guard**: The component (`micro_repeat_guard.py`) that detects and blocks repeated or near-duplicate Autonomous_Lines.
- **Banned_Filler**: The set of "stale micro template" lines that `service.py` instructs generation to avoid, including "Khoảng yên này vẫn giữ chỗ." and "Nhịp này vẫn yên thêm chút.".
- **Muse_Directive**: A directive raised when the cognition layer (`ti_report.mode == "pattern_muse"`) grants the character permission to pull its own topic or curiosity instead of staying silent.
- **Ambient_Silence_Gate**: The logic (`_should_hold_ambient_silence` / `_ambient_silence_cooldown_seconds`) that may suppress an Autonomous_Line for a cooldown period.
- **Body_Only_Presence**: A non-verbal presence action (e.g. `idle_shift`, `quiet_observe_scene`) emitted instead of speech.
- **Observation_Window**: A continuous span of autonomous operation used to evaluate liveliness; the reference span for this feature is 60 minutes.
- **Grounded_Line**: An Autonomous_Line whose content is anchored in a concrete current evidence source (Vision_Fact, Memory_Seed, thought stream, or private-life residue) rather than generic presence filler.

## Requirements

### Requirement 1: Ground autonomous lines in current observed context

**User Story:** As a viewer watching the character idle, I want its spontaneous lines to reflect what is actually on screen or in its memory right now, so that it feels aware of its environment instead of reciting generic filler.

#### Acceptance Criteria

1. WHEN the Autonomous_Presence_Loop selects a seed for an Idle_Cycle AND at least one specific Vision_Fact was last observed within the preceding 30 seconds, THE Surface_Seed_Compiler SHALL include that Vision_Fact as a seed candidate.
2. WHEN a Vision_Fact candidate and a generic private-life candidate are both available for the same Idle_Cycle, THE Surface_Seed_Compiler SHALL assign the Vision_Fact candidate a rank value greater than or equal to the generic private-life candidate rank value.
3. THE Surface_Seed_Compiler SHALL derive a Vision_Fact candidate confidence as a value between 0.0 and 1.0 inclusive from the underlying evidence.
4. WHEN a Memory_Seed is public-safe AND contains at least one non-whitespace character with a length from 1 character up to a configured maximum length, THE Surface_Seed_Compiler SHALL retain it as a seed candidate.
5. WHEN the Autonomous_Presence_Loop selects a seed for an Idle_Cycle, THE Autonomous_Presence_Loop SHALL emit a Grounded_Line derived from the selected seed.
6. IF no specific Vision_Fact, Memory_Seed, thought-stream seed, or private-life residue is available for an Idle_Cycle, THEN THE Autonomous_Presence_Loop SHALL emit Body_Only_Presence or silence instead of a generic spoken filler line.
7. IF a Memory_Seed is not public-safe, THEN THE Surface_Seed_Compiler SHALL exclude it from seed candidates.

### Requirement 2: Vary autonomous lines across an extended observation window

**User Story:** As a viewer watching for a long time, I want the character's idle lines to vary, so that it does not sound like a stuck loop.

#### Acceptance Criteria

1. WHEN an Autonomous_Line is a verbatim repeat of any Autonomous_Line emitted within the Micro_Repeat_Guard repeat window, THE Micro_Repeat_Guard SHALL reject the line.
2. THE Micro_Repeat_Guard repeat-detection window SHALL be configurable with a minimum duration at least as long as the maximum Idle_Cycle interval, so that two consecutive Idle_Cycles cannot emit identical Autonomous_Line text.
3. WHEN an Autonomous_Line of a given family matches an Autonomous_Line of the same family emitted within the Micro_Repeat_Guard repeat window at or above a configured similarity threshold (expressed as a percentage from 0 to 100), THE Micro_Repeat_Guard SHALL reject the line.
4. WHILE the Autonomous_Presence_Loop runs over a 60-minute Observation_Window, THE Autonomous_Presence_Loop SHALL emit no single Autonomous_Line text more than a configured maximum repeat count, where the count is an integer in the range 1 to 10 with a default of 3.
5. WHEN the Micro_Repeat_Guard rejects a candidate line AND an alternative seed is available, THE Autonomous_Presence_Loop SHALL attempt up to a configured maximum number of alternative seeds (an integer in the range 1 to 10 with a default of 3) rather than emitting the rejected line.
6. IF the Micro_Repeat_Guard rejects a candidate line AND no alternative seed is available, THEN THE Autonomous_Presence_Loop SHALL emit Body_Only_Presence or remain silent, and SHALL retain the existing repeat-window history unchanged.
7. IF the configured similarity threshold, repeat window, maximum repeat count, or maximum alternative-seed attempts is absent or outside its valid range, THEN THE Micro_Repeat_Guard SHALL apply its default value and continue operating without interrupting the Autonomous_Presence_Loop.

### Requirement 3: Never emit banned filler lines

**User Story:** As the character's author, I want the system to never speak the stale template lines it already tells the LLM to avoid, so that the documented "do not say" rule is actually enforced at output.

#### Acceptance Criteria

1. IF a candidate Autonomous_Line matches a Banned_Filler line after normalizing letter case and trimming leading and trailing whitespace, THEN THE Autonomous_Presence_Loop SHALL suppress that candidate so that it is never emitted as an Autonomous_Line.
2. WHEN generation fails or returns empty or whitespace-only text for an Idle_Cycle, THE Autonomous_Presence_Loop SHALL emit Body_Only_Presence or silence instead of a Banned_Filler line.
3. IF every candidate Autonomous_Line for an Idle_Cycle is suppressed because each matches a Banned_Filler line, THEN THE Autonomous_Presence_Loop SHALL emit Body_Only_Presence or silence rather than any Banned_Filler line.
4. THE Autonomous_Presence_Loop SHALL treat the Banned_Filler set as a single source of truth shared between the generation instructions and the output filter, such that any line added to or removed from the Banned_Filler set is simultaneously reflected in both the generation instructions and the output filter without a separate update.

### Requirement 4: Let proactive muse and curiosity actually fire

**User Story:** As a viewer, I want the character to occasionally pull its own topic or curiosity when its cognition grants permission, so that it shows initiative instead of only reacting.

#### Acceptance Criteria

1. WHEN the cognition layer raises a Muse_Directive granting the character permission to pull its own topic, THE Autonomous_Presence_Loop SHALL attempt to surface a self-initiated line within the same Idle_Cycle in which the directive was raised, rather than skipping the directive.
2. WHILE a Muse_Directive is active, THE Ambient_Silence_Gate SHALL NOT suppress the directive solely because the standard ambient-silence cooldown has not yet elapsed.
3. WHEN a Muse_Directive produces a usable seed, THE Autonomous_Presence_Loop SHALL emit exactly one Grounded_Line derived from that seed within the same Idle_Cycle in which the seed was produced.
4. IF a Muse_Directive produces no usable seed within the same Idle_Cycle in which it was raised, THEN THE Autonomous_Presence_Loop SHALL discard the directive without emitting a Grounded_Line and SHALL record the no-seed outcome as a suppression reason for observability.
5. IF a Muse_Directive is suppressed, THEN THE Autonomous_Presence_Loop SHALL record a suppression reason identifying the suppressing component and the suppression cause, retaining the record for observability, and SHALL leave any existing conversation output unchanged.

### Requirement 5: Maintain a felt sense of life over a long session

**User Story:** As a viewer leaving the character running for an hour, I want it to feel present and varied across that time, so that it reads as alive rather than dead.

#### Acceptance Criteria

1. WHILE the Autonomous_Presence_Loop runs over a 60-minute Observation_Window, THE Autonomous_Presence_Loop SHALL emit at least a configured minimum number of distinct Grounded_Lines with a default of 20, where a distinct Grounded_Line is one that is neither a verbatim nor a semantic repeat as determined by the Micro_Repeat_Guard.
2. WHILE the Autonomous_Presence_Loop runs over a 60-minute Observation_Window, THE Autonomous_Presence_Loop SHALL distribute Grounded_Lines so that no configured sub-interval of the window, with a default of 5 minutes, passes without a Grounded_Line when grounded content is available.
3. WHILE the Autonomous_Presence_Loop runs over a 60-minute Observation_Window, THE proportion of emitted Autonomous_Lines that are Grounded_Lines SHALL meet a configured minimum threshold with a default of 60 percent.
4. WHEN an Idle_Cycle ends with neither a spoken Autonomous_Line nor a Body_Only_Presence action after autonomous line generation was attempted, THE Autonomous_Presence_Loop SHALL emit a Body_Only_Presence action.
5. WHEN the Autonomous_Presence_Loop emits an Autonomous_Line, THE Autonomous_Presence_Loop SHALL record the seed source identifier and the grounding evidence reference for that line so that liveliness can be verified from logs.

### Requirement 6: Observability of seed selection and suppression

**User Story:** As a developer debugging the idle loop, I want each cycle's seed selection and suppression decisions to be inspectable, so that I can verify the redesign is working and diagnose regressions.

#### Acceptance Criteria

1. WHEN the Surface_Seed_Compiler selects a seed, THE Surface_Seed_Compiler SHALL record the selected seed source, its confidence as a numeric value between 0.0 and 1.0 inclusive, and the count of candidates considered as a non-negative integer.
2. WHEN the Surface_Seed_Compiler produces no seed, THE Surface_Seed_Compiler SHALL record a reason drawn from a predefined enumerated set of no-seed reasons, where a generic or unspecified failure value is not a permitted reason.
3. WHEN the Micro_Repeat_Guard rejects a line, THE Micro_Repeat_Guard SHALL record the rejection reason and either the matched family identifier or the matched fingerprint value that triggered the rejection.
4. WHEN the Ambient_Silence_Gate suppresses an Autonomous_Line, THE Ambient_Silence_Gate SHALL record the active mode and the remaining cooldown duration in seconds that caused the suppression.
5. WHEN any of the Surface_Seed_Compiler, Micro_Repeat_Guard, or Ambient_Silence_Gate records a decision, THE recording component SHALL associate that record with the identifier of the idle cycle in which the decision occurred, so that all decisions for a single cycle are retrievable together.
6. THE system SHALL retain decision records for at least the 100 most recent idle cycles and SHALL make those retained records available for inspection.
