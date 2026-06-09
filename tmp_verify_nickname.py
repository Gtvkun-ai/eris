"""Ad-hoc verification for the user.nickname memory fix. Deleted after running."""
import os, sys, tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from memory.claim_extractor import extract_claims
from memory.predicate_ontology import fact_key_for_predicate, get_predicate
from memory.memory_worthiness import MemoryWorthinessPolicy
from memory.semantic_memory import SemanticMemoryStore
from memory.query_intent import QUERY_TARGETS

failures = []

def check(label, cond, detail=""):
    print(("PASS" if cond else "FAIL"), label, ("" if cond else f"-> {detail}"))
    if not cond:
        failures.append(label)

# 1. Parser + builder + ontology: nickname disclosure becomes nickname_is/Gtvkun.
claims = [c.claim for c in extract_claims("tôi có biệt danh là Gtvkun")]
nick = [c for c in claims if c.predicate == "nickname_is"]
check("nickname claim extracted", bool(nick), f"claims={[(c.predicate, c.object_text) for c in claims]}")
if nick:
    check("nickname object == Gtvkun", nick[0].object_text.strip().lower() == "gtvkun", nick[0].object_text)
    check("nickname fact_key == user.nickname", fact_key_for_predicate("nickname_is") == "user.nickname")

# alt phrasing
claims2 = [c.claim for c in extract_claims("biệt danh của tôi là Gtvkun")]
check("alt-phrasing nickname extracted", any(c.predicate == "nickname_is" for c in claims2),
      f"claims={[(c.predicate, c.object_text) for c in claims2]}")

# 2. Real name still works and is NOT a nickname.
name_claims = [c.claim for c in extract_claims("tôi tên là Hoà")]
check("name still extracted as name_is", any(c.predicate == "name_is" for c in name_claims),
      f"claims={[(c.predicate, c.object_text) for c in name_claims]}")
check("name disclosure does not produce nickname", not any(c.predicate == "nickname_is" for c in name_claims))

# 3. Worthiness routes nickname claim to semantic memory as active.
if nick:
    wd = MemoryWorthinessPolicy().decide(nick[0])
    check("nickname routes to semantic_memory", wd.target_layer == "semantic_memory", f"{wd.target_layer}/{wd.status}/{wd.reason}")

# 4 & 5. Storage: name + nickname coexist; recall cue maps queries correctly.
with tempfile.TemporaryDirectory() as tmp:
    store = SemanticMemoryStore(os.path.join(tmp, "semantic_memory.json"))
    store.apply_commit(SimpleNamespace(
        content="User's name is Hoà", confidence=0.86, evidence_ids=["t1"],
        target="semantic_memory", reason="user_name", decay_policy="slow",
        metadata={"fact_key": "user.name", "value": "Hoà"}, tags=["typed_fact"]))
    store.apply_commit(SimpleNamespace(
        content="User's nickname is Gtvkun", confidence=0.90, evidence_ids=["t2"],
        target="semantic_memory", reason="user_nickname", decay_policy="slow",
        metadata={"fact_key": "user.nickname", "value": "Gtvkun"}, tags=["typed_fact"]))

    check("lookup user.name == Hoà", store.lookup_fact("user.name") == "Hoà", repr(store.lookup_fact("user.name")))
    check("lookup user.nickname == Gtvkun", store.lookup_fact("user.nickname") == "Gtvkun", repr(store.lookup_fact("user.nickname")))

    cue_nick = store.parse_recall_cue("biệt danh của tôi là gì")
    check("recall cue nickname -> user.nickname", cue_nick.fact_key == "user.nickname", cue_nick.fact_key)
    cue_name = store.parse_recall_cue("tên tôi là gì")
    check("recall cue name -> user.name", cue_name.fact_key == "user.name", cue_name.fact_key)

# 6. Query target registered.
check("user_nickname query target exists", "user_nickname" in QUERY_TARGETS)
check("user_nickname target predicate nickname_is", QUERY_TARGETS.get("user_nickname") and QUERY_TARGETS["user_nickname"].target_predicates == ("nickname_is",))

print("\nRESULT:", "ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
