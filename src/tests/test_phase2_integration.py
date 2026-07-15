# -*- coding: utf-8 -*-
"""test_phase2_integration.py — Phase 2 integration & cross-cutting tests.

Covers spec tasks 1.3, 2.2, 4.3, 7.2, 7.3, 10.2, 10.3, 16.2, 16.3, 17.2, 17.3,
18.2, 18.3, 18.4 of ``phase2-meaning-tom``.

Conventions:
- pytest + hypothesis.
- ``tests/conftest.py`` puts ``src/`` and ``tests/`` on ``sys.path`` so the
  ``cortex.*`` and ``phase2_strategies`` imports below resolve without install.
- Every property-based test uses ``@settings(max_examples=100)`` (minimum; the
  flagship Property 1 uses >=100) and a leading
  ``# Feature: phase2-meaning-tom, Property N: ...`` comment, plus a docstring
  noting the requirements it validates.
"""

from __future__ import annotations

import ast
import copy
import math
import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from phase2_strategies import (
    frames,
    ids,
    near_tie_hypotheses,
    unit_floats,
)

from cortex.global_workspace import WorkspaceFrame, WorkspaceItem
from cortex.meaning import Phase2MeaningPipeline, MeaningLayer  # noqa: F401
from cortex.meaning.ambiguity import AmbiguityModule
from cortex.meaning.config import Phase2Config
from cortex.meaning.contracts import (
    ConfigurationError,
    EvaluatedConclusion,
    MeaningHypothesis,
    Observation,
    Phase2Result,
    PragmaticIntent,  # noqa: F401
    StageDebug,
    SurfaceDecision,
    clamp01,
)
from cortex.meaning.debug_render import DebugRender, Phase2Run
from cortex.meaning.read_contract import FrameReadView
from cortex.meaning.surface_meaning_policy import SurfaceMeaningPolicy
from cortex.meaning.taxonomy import Taxonomy
from cortex.meaning.world_interpreter import WorldInterpreter
from cortex.meaning.world_scene_builder import WorldSceneBuilder
from cortex.tom.contracts import MentalStateInference
from cortex.tom.tom_debug import ToMDebug


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
# Default downstream contract mirroring the one ``phase2_strategies.frames``
# attaches to generated frames (design R1.3) — used by the manually-built
# integration frame so each stage can read the fields it needs.
_DOWNSTREAM_CONTRACT: dict[str, list[str]] = {
    "WorldSceneBuilder": [
        "frame_id",
        "broadcast_items",
        "active_threads",
        "dominant_thread",
        "broadcast_reason",
    ],
    "WorldInterpreter": ["frame_id"],
    "SocioculturalContext": [
        "frame_id",
        "social_hypotheses",
        "forbidden_assumptions",
    ],
    "MeaningHypothesisEngine": [
        "frame_id",
        "broadcast_items",
        "forbidden_assumptions",
    ],
    "PragmaticIntentEngine": ["frame_id"],
    "TheoryOfMindCore": ["frame_id", "forbidden_assumptions"],
}


class _Scored:
    """Minimal object exposing ``.confidence`` for AmbiguityModule (ScoredHypothesis)."""

    __slots__ = ("confidence",)

    def __init__(self, confidence) -> None:
        self.confidence = confidence


def _evidence_for(ec: EvaluatedConclusion) -> list[str]:
    """Generic evidence extraction: prefer ``evidence_ids`` else ``supporting_meaning_ids``."""

    conclusion = getattr(ec, "conclusion", None)
    candidate = getattr(conclusion, "evidence_ids", None)
    if candidate is None:
        candidate = getattr(conclusion, "supporting_meaning_ids", None)
    return list(candidate) if candidate else []


def _meaning(
    *,
    hid: str = "h",
    confidence: float = 0.5,
    ambiguity: float = 0.0,
    overread_risk: float = 0.0,
    evidence_ids=None,
) -> MeaningHypothesis:
    """Build a MeaningHypothesis with a valid taxonomy category and given metrics."""

    return MeaningHypothesis(
        hypothesis_id=hid,
        category="joke",  # ∈ Taxonomy.MEANING
        summary="s",
        evidence_ids=["e1"] if evidence_ids is None else list(evidence_ids),
        confidence=confidence,
        ambiguity=ambiguity,
        overread_risk=overread_risk,
    )


def _evaluated(
    conclusion: MeaningHypothesis,
    *,
    confidence: float | None = None,
    suppressed: bool = False,
    brake_reason: str = "",
) -> EvaluatedConclusion:
    """Wrap a conclusion in an EvaluatedConclusion mirroring OverreadBrake output."""

    conf = conclusion.confidence if confidence is None else confidence
    return EvaluatedConclusion(
        conclusion=conclusion,
        kind="meaning",
        confidence=conf,
        original_confidence=conf,
        overread_suppressed=suppressed,
        brake_reason=brake_reason,
    )


def _build_simple_frame() -> WorkspaceFrame:
    """A single valid WorkspaceFrame for the end-to-end integration test."""

    item = WorkspaceItem(
        id="item-1",
        kind="user_request",
        content="can you help me with this?",
        summary="can you help me with this?",
        priority=0.8,
        confidence=0.8,
        evidence_ids=["ev-1"],
    )
    return WorkspaceFrame(
        frame_id="frame-int-1",
        timestamp=0.0,
        budget_mode="normal",
        broadcast_items=[item],
        active_threads=["thread-1"],
        dominant_thread="thread-1",
        broadcast_reason="integration-test",
        forbidden_assumptions=[],
        downstream_contract={k: list(v) for k, v in _DOWNSTREAM_CONTRACT.items()},
    )


# ===========================================================================
# Task 1.3 — clamp01 helper & dataclass clamping (R1.5 clamp invariant)
# ===========================================================================
def test_clamp01_clamps_to_unit_interval():
    """clamp01 maps out-of-range / NaN values into [0,1].

    Validates: Requirements 1.5
    """

    assert clamp01(1.7) == 1.0
    assert clamp01(-0.3) == 0.0
    assert clamp01(0.5) == 0.5
    assert clamp01(float("nan")) == 0.0


def test_meaning_hypothesis_clamps_metrics_at_construction():
    """A MeaningHypothesis built with out-of-range metrics clamps them to [0,1].

    Validates: Requirements 1.5
    """

    h = MeaningHypothesis(
        hypothesis_id="h1",
        category="joke",
        summary="s",
        evidence_ids=["e1"],
        confidence=1.7,
        ambiguity=-0.3,
        overread_risk=2.0,
    )
    assert h.confidence == 1.0
    assert h.ambiguity == 0.0
    assert h.overread_risk == 1.0
    assert 0.0 <= h.confidence <= 1.0
    assert 0.0 <= h.ambiguity <= 1.0
    assert 0.0 <= h.overread_risk <= 1.0


# ===========================================================================
# Task 2.2 — Taxonomy smoke (R11.1, R11.4)
# ===========================================================================
def test_taxonomy_validate_on_startup_and_require():
    """validate_on_startup does not raise; each family is non-empty; require()
    returns valid ids and raises ConfigurationError for unknown ids.

    Validates: Requirements 11.1, 11.4
    """

    # Does not raise.
    Taxonomy.validate_on_startup()

    assert len(Taxonomy.MEANING) >= 1
    assert len(Taxonomy.INTENT) >= 1
    assert len(Taxonomy.MENTAL_STATE) >= 1

    valid_meaning = next(iter(Taxonomy.MEANING))
    assert Taxonomy.require("MEANING", valid_meaning) == valid_meaning

    valid_intent = next(iter(Taxonomy.INTENT))
    assert Taxonomy.require("INTENT", valid_intent) == valid_intent

    valid_mental = next(iter(Taxonomy.MENTAL_STATE))
    assert Taxonomy.require("MENTAL_STATE", valid_mental) == valid_mental

    with pytest.raises(ConfigurationError):
        Taxonomy.require("MEANING", "__not_a_real_category__")


# ===========================================================================
# Task 4.3 — AST no-direct-read scan (R13.5)
# ===========================================================================
# Raw_World channel symbols that no Phase 2 stage module may import or access as
# an attribute. Plain "evidence"/"memory" are intentionally excluded so we never
# flag legitimate names like selected_evidence/selected_memory.
_RAW_WORLD_SYMBOLS: frozenset[str] = frozenset(
    {
        "raw_signals",
        "raw_world",
        "raw_evidence",
        "unfiltered_evidence",
        "raw_memory",
        "unselected_memory",
    }
)


def _scan_module_for_raw_world(path: str) -> list[tuple[str, str]]:
    """Parse ``path`` and return (file, symbol) for any Raw_World import/attribute.

    Detects imports of the symbols and attribute access (e.g. ``frame.raw_signals``)
    only — NOT bare local variable names — so legitimate locals are not flagged.
    """

    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source, filename=path)

    violations: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                leaf = alias.name.split(".")[-1]
                if leaf in _RAW_WORLD_SYMBOLS:
                    violations.append((path, alias.name))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in _RAW_WORLD_SYMBOLS:
                    violations.append((path, alias.name))
        elif isinstance(node, ast.Attribute):
            if node.attr in _RAW_WORLD_SYMBOLS:
                violations.append((path, node.attr))
    return violations


def _scan_dir_for_raw_world(dir_path: str) -> list[tuple[str, str]]:
    """Scan every .py file under ``dir_path`` except read_contract.py (the guard)."""

    found: list[tuple[str, str]] = []
    for root, _dirs, files in os.walk(dir_path):
        for filename in files:
            if not filename.endswith(".py"):
                continue
            # read_contract.py DEFINES RAW_WORLD_FIELDS as a guard — exclude it.
            if filename == "read_contract.py":
                continue
            found.extend(_scan_module_for_raw_world(os.path.join(root, filename)))
    return found


def test_no_raw_world_access_in_phase2_modules():
    """No Phase 2 stage module imports or references Raw_World channel symbols.

    Validates: Requirements 13.5
    """

    cortex_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "src", "cortex")
    )
    meaning_dir = os.path.join(cortex_dir, "meaning")
    tom_dir = os.path.join(cortex_dir, "tom")

    assert os.path.isdir(meaning_dir), meaning_dir
    assert os.path.isdir(tom_dir), tom_dir

    violations = _scan_dir_for_raw_world(meaning_dir) + _scan_dir_for_raw_world(tom_dir)
    assert violations == [], f"Raw_World references found: {violations}"


# ===========================================================================
# Task 7.2 — Property 11: observations well-formed & traceable
# ===========================================================================
# Feature: phase2-meaning-tom, Property 11: Observations are well-formed and traceable
@settings(max_examples=100)
@given(frame=frames(min_items=1, max_items=4))
def test_observations_well_formed_and_traceable(frame):
    """For any frame, FrameReadView -> WorldSceneBuilder -> WorldInterpreter
    yields observations each with confidence in [0,1], >=1 evidence_id, and a
    source_element_id referencing an existing scene element id.

    Validates: Requirements 3.1, 3.4, 3.6
    """

    view = FrameReadView(frame).for_module("WorldSceneBuilder")
    scene, _sd = WorldSceneBuilder().build(view)
    observations, _odbg = WorldInterpreter().interpret(scene)

    element_ids = {
        e.element_id
        for e in list(scene.entities)
        + list(scene.salient_signals)
        + list(scene.active_threads)
    }

    for obs in observations:
        assert 0.0 <= obs.confidence <= 1.0
        assert len(obs.evidence_ids) >= 1
        assert obs.source_element_id in element_ids


# ===========================================================================
# Task 7.3 — Property 12: WorldInterpreter stays in scope
# ===========================================================================
# Feature: phase2-meaning-tom, Property 12: WorldInterpreter stays in scope
@settings(max_examples=100)
@given(frame=frames(min_items=0, max_items=4))
def test_world_interpreter_only_produces_observations(frame):
    """For any frame, the WorldInterpreter output contains only Observation
    instances (no intent / mental-state types).

    Validates: Requirements 3.2
    """

    view = FrameReadView(frame).for_module("WorldSceneBuilder")
    scene, _sd = WorldSceneBuilder().build(view)
    observations, _odbg = WorldInterpreter().interpret(scene)

    assert all(isinstance(o, Observation) for o in observations)


# ===========================================================================
# Task 10.2 — Property 31: ambiguity computation bounds
# ===========================================================================
# Feature: phase2-meaning-tom, Property 31: ambiguity computation bounds
@settings(max_examples=100)
@given(confidences=st.lists(unit_floats(), min_size=2, max_size=6))
def test_ambiguity_two_or_more_in_unit_interval(confidences):
    """For any >=2 scored hypotheses, ambiguity is a valid value in [0,1].

    Validates: Requirements 9.1
    """

    result = AmbiguityModule().compute([_Scored(c) for c in confidences])
    assert result.valid
    assert 0.0 <= result.value <= 1.0


# Feature: phase2-meaning-tom, Property 31: ambiguity computation bounds
@settings(max_examples=100)
@given(confidence=unit_floats())
def test_ambiguity_single_hypothesis_low(confidence):
    """For exactly one hypothesis with no competitor, ambiguity is in [0.0, 0.1].

    Validates: Requirements 9.2
    """

    result = AmbiguityModule().compute([_Scored(confidence)])
    assert result.valid
    assert 0.0 <= result.value <= 0.1


# Feature: phase2-meaning-tom, Property 31: ambiguity computation bounds
@settings(max_examples=100)
@given(hyps=near_tie_hypotheses(margin=0.05))
def test_ambiguity_near_tie_is_high(hyps):
    """For top-2 confidences within 0.05, ambiguity is in [0.9, 1.0].

    Validates: Requirements 9.3
    """

    result = AmbiguityModule().compute(hyps)
    assert result.valid
    assert len(hyps) >= 2
    assert 0.9 <= result.value <= 1.0


# ===========================================================================
# Task 10.3 — ambiguity invalid-input retention & 0-hypothesis (R9.4, R9.5)
# ===========================================================================
def test_ambiguity_zero_hypotheses_returns_zero():
    """compute([]) returns value 0.0 with a 'no hypotheses' indication.

    Validates: Requirements 9.4
    """

    result = AmbiguityModule().compute([])
    assert result.value == 0.0
    assert result.valid is True
    assert "no hypotheses" in result.reason.lower()


def test_ambiguity_invalid_input_retains_previous_value():
    """An out-of-range confidence is rejected (valid=False) and the previously
    computed ambiguity value is retained.

    Validates: Requirements 9.5
    """

    module = AmbiguityModule()
    # Establish a previous valid value (near-tie -> high ambiguity).
    previous = module.compute([_Scored(0.5), _Scored(0.5)])
    assert previous.valid
    retained = previous.value

    # Feed a tiny object whose confidence is outside [0,1].
    bad = module.compute([_Scored(1.5)])
    assert bad.valid is False
    assert bad.value == retained


# ===========================================================================
# Task 16.2 — Property 2: surface partition total & disjoint
# ===========================================================================
@st.composite
def _evaluated_conclusions(draw, *, min_size: int = 0, max_size: int = 6):
    """Build a list of EvaluatedConclusion with varied confidence / suppression /
    underlying ambiguity / evidence."""

    count = draw(st.integers(min_value=min_size, max_value=max_size))
    out: list[EvaluatedConclusion] = []
    for _ in range(count):
        conf = draw(unit_floats())
        amb = draw(unit_floats())
        suppressed = draw(st.booleans())
        evidence = draw(st.lists(ids(), max_size=3, unique=True))  # may be empty
        hyp = MeaningHypothesis(
            hypothesis_id=draw(ids()),
            category="joke",
            summary="s",
            evidence_ids=evidence,
            confidence=conf,
            ambiguity=amb,
            overread_risk=draw(unit_floats()),
        )
        out.append(
            EvaluatedConclusion(
                conclusion=hyp,
                kind="meaning",
                confidence=conf,
                original_confidence=conf,
                overread_suppressed=suppressed,
                brake_reason="suppressed" if suppressed else "",
            )
        )
    return out


# Feature: phase2-meaning-tom, Property 2: Surface partition is total and disjoint
@settings(max_examples=100)
@given(evaluated=_evaluated_conclusions())
def test_surface_partition_total_and_disjoint(evaluated):
    """For any list of EvaluatedConclusion, partition() assigns each to exactly
    one of surfaced/withheld (union == input, intersection empty) and records
    exactly one SurfaceDecision per input.

    Validates: Requirements 10.1, 10.5
    """

    result = SurfaceMeaningPolicy(Phase2Config()).partition(evaluated, frame_id="f")

    surfaced_ids = [id(e) for e in result.surfaced]
    withheld_ids = [id(e) for e in result.withheld]

    # Total: union equals the input set.
    assert len(surfaced_ids) + len(withheld_ids) == len(evaluated)
    assert set(surfaced_ids) | set(withheld_ids) == {id(e) for e in evaluated}

    # Disjoint: no conclusion appears in both sets.
    assert set(surfaced_ids).isdisjoint(set(withheld_ids))

    # Exactly one SurfaceDecision per input conclusion.
    assert len(result.decisions) == len(evaluated)


# ===========================================================================
# Task 16.3 — Property 3: surface classification rules
# ===========================================================================
# Feature: phase2-meaning-tom, Property 3: Surface classification rules hold
@settings(max_examples=100)
@given(
    confidence=unit_floats(),
    ambiguity=unit_floats(),
    suppressed=st.booleans(),
    has_evidence=st.booleans(),
)
def test_surface_classification_rules(confidence, ambiguity, suppressed, has_evidence):
    """For any EvaluatedConclusion, surfaced/withheld status follows the
    precedence: suppressed -> withheld; no evidence -> withheld; ambiguity==1.0
    -> withheld; confidence < threshold -> withheld; >=threshold &
    ambiguity in [ambiguity_threshold, 1.0) -> surfaced tentative; >=threshold &
    ambiguity < ambiguity_threshold -> surfaced asserted.

    Validates: Requirements 10.2, 10.3, 10.4, 10.6, 10.7
    """

    cfg = Phase2Config()
    evidence = ["e1"] if has_evidence else []
    hyp = _meaning(
        hid="h1",
        confidence=confidence,
        ambiguity=ambiguity,
        overread_risk=0.0,
        evidence_ids=evidence,
    )
    ec = _evaluated(
        hyp,
        confidence=confidence,
        suppressed=suppressed,
        brake_reason="brake" if suppressed else "",
    )

    result = SurfaceMeaningPolicy(cfg).partition([ec], frame_id="f")
    status = result.decisions[0].status

    if suppressed:
        expected = "withheld"
    elif not evidence:
        expected = "withheld"
    elif ambiguity >= 1.0:
        expected = "withheld"
    elif confidence < cfg.surface_conf_threshold:
        expected = "withheld"
    elif cfg.ambiguity_threshold <= ambiguity < 1.0:
        expected = "surfaced_tentative"
    else:
        expected = "surfaced_asserted"

    assert status == expected

    if expected == "withheld":
        assert ec in result.withheld
        assert ec not in result.surfaced
    else:
        assert ec in result.surfaced
        assert ec not in result.withheld


# ===========================================================================
# Task 17.2 — Property 32: debug record completeness
# ===========================================================================
# Feature: phase2-meaning-tom, Property 32: debug record completeness
def test_debug_render_completeness():
    """DebugRender.render(run) includes the frame_id, 'unavailable' for None
    metrics, and the withheld reasons; ToMDebug.render references supporting ids.

    Validates: Requirements 12.1, 12.2, 12.3, 12.4
    """

    withheld_hyp = _meaning(hid="h1", confidence=0.1, ambiguity=0.0, evidence_ids=["e1"])
    withheld_ec = _evaluated(withheld_hyp, confidence=0.1)

    surfaced_hyp = _meaning(hid="h2", confidence=0.9, ambiguity=0.0, evidence_ids=["e2"])
    surfaced_ec = _evaluated(surfaced_hyp, confidence=0.9)

    decisions = [
        SurfaceDecision(
            conclusion_id="h1",
            status="withheld",
            reason="confidence_below_threshold:0.1000<0.5000",
        ),
        SurfaceDecision(conclusion_id="h2", status="surfaced_asserted", reason="asserted"),
    ]
    result = Phase2Result(
        frame_id="frame-xyz",
        surfaced=[surfaced_ec],
        withheld=[withheld_ec],
        decisions=decisions,
        debug={},
    )

    stage_debugs = [
        StageDebug(stage="WorldSceneBuilder", confidence=0.4, ambiguity=0.2, overread_risk=0.1),
        StageDebug(stage="WorldInterpreter"),  # all-None metrics
    ]
    run = Phase2Run(frame_id="frame-xyz", stage_debugs=stage_debugs, result=result)

    rendered = DebugRender().render(run)
    assert "frame-xyz" in rendered          # R12.4
    assert "unavailable" in rendered         # R12.1 / None metrics
    assert "confidence_below_threshold" in rendered  # R12.2 withheld reason

    inference = MentalStateInference(
        inference_id="i1",
        category="curious",  # ∈ Taxonomy.MENTAL_STATE
        summary="seems curious",
        confidence=0.5,
        overread_risk=0.1,
        supporting_meaning_ids=["h1", "h2"],
    )
    tom_rendered = ToMDebug().render([inference])  # R12.3
    assert "h1" in tom_rendered
    assert "h2" in tom_rendered


# ===========================================================================
# Task 17.3 — debug "unavailable" handling (R12.5, R12.6)
# ===========================================================================
def test_debug_stage_all_none_metrics_render_unavailable():
    """A StageDebug with all-None metrics renders 'unavailable'.

    Validates: Requirements 12.5
    """

    run = Phase2Run(
        frame_id="f",
        stage_debugs=[StageDebug(stage="SomeStage")],
        result=None,
    )
    rendered = DebugRender().render(run)
    assert "unavailable" in rendered


def test_debug_missing_frame_id_renders_unavailable():
    """A Phase2Run with frame_id=None renders 'frame_id unavailable'.

    Validates: Requirements 12.6
    """

    run = Phase2Run(frame_id=None, stage_debugs=[], result=None)
    rendered = DebugRender().render(run)
    assert "frame_id unavailable" in rendered


# ===========================================================================
# Task 18.2 — Property 1 (FLAGSHIP): no-overread invariant over >=100 frames
# ===========================================================================
# Feature: phase2-meaning-tom, Property 1: Surfaced conclusions always carry evidence (no-overread flagship)
@settings(max_examples=100)
@given(frame=frames(min_items=0, max_items=4))
def test_no_overread_surfaced_always_has_evidence(frame):
    """For any frame run through the full Phase 2 pipeline, every conclusion in
    the surfaced set carries at least one supporting evidence id.

    Validates: Requirements 10.8, 13.8
    """

    result = Phase2MeaningPipeline().run(frame)
    for ec in result.surfaced:
        assert len(_evidence_for(ec)) >= 1


# ===========================================================================
# Task 18.3 — Property 4: WorkspaceFrame-only boundary
# ===========================================================================
# Feature: phase2-meaning-tom, Property 4: WorkspaceFrame-only boundary
@settings(max_examples=100)
@given(frame=frames(min_items=0, max_items=4))
def test_workspaceframe_only_boundary(frame):
    """Mutating a field NOT in any stage's downstream_contract (selected_affect)
    leaves the pipeline's surfaced/withheld decisions unchanged — the stages do
    not read it.

    Validates: Requirements 1.1, 1.3, 6.2, 7.1, 7.5
    """

    frame_mutated = copy.deepcopy(frame)
    frame_mutated.selected_affect = "MUTATED_NON_CONTRACT_FIELD"

    result_a = Phase2MeaningPipeline().run(frame)
    result_b = Phase2MeaningPipeline().run(frame_mutated)

    decisions_a = [(d.conclusion_id, d.status) for d in result_a.decisions]
    decisions_b = [(d.conclusion_id, d.status) for d in result_b.decisions]
    assert decisions_a == decisions_b


# ===========================================================================
# Task 18.4 — Integration: end-to-end pipeline
# ===========================================================================
def test_end_to_end_pipeline_produces_result():
    """One WorkspaceFrame -> Phase2MeaningPipeline().run -> a Phase2Result with
    frame_id set and decisions count == surfaced + withheld count.

    Validates: Requirements 13.2
    """

    frame = _build_simple_frame()
    result = Phase2MeaningPipeline().run(frame)

    assert isinstance(result, Phase2Result)
    assert result.frame_id == frame.frame_id
    assert len(result.decisions) == len(result.surfaced) + len(result.withheld)
