"""
Standalone logic test for the Context Engine (v1.3.0).

Verifies: layered memory storage, priority-order prompt building, the context
budget, hard compaction (/compact), automatic pruning, and restart-free
persistence (data lives in primus.db).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.db import init_db
from backend.context import ContextEngine, ContextLayer, DEFAULT_USER
from backend.api import (
    initialize_memory,
    get_context_info,
    compact_context,
    handle_context_command,
)


async def main():
    await init_db()
    initialize_memory()  # no config -> defaults (max_tokens=128000)

    eng = ContextEngine()
    cid = "test-conv"

    # ── Req 1 + 2: one shared memory, eight layers ──
    await eng.set_fact(ContextLayer.USER_FACTS, "name", "Ashut")
    await eng.set_fact(ContextLayer.PROJECT_MEMORY, "repo", "Primus")
    await eng.set_fact(ContextLayer.LONG_TERM, "pref", "Prefers concise answers")
    await eng.set_fact(ContextLayer.SKILLS, "deploy", "Use render.yaml")
    await eng.set_fact(ContextLayer.COMPACT_MEMORY, "old", "previous summary")

    counts = await eng.count_by_layer()
    assert counts["user_facts"] == 1, counts
    assert counts["project_memory"] == 1, counts
    assert counts["long_term"] == 1, counts
    print("OK  layered memory stored (shared user '%s')" % DEFAULT_USER)

    # ── Req 7: prompt builder consumes layers in priority order ──
    await eng.add_interaction(DEFAULT_USER, cid, "Hello there", "Hi! How can I help?")
    prompt = await eng.build_prompt(DEFAULT_USER, cid, "What is my name?")
    assert "USER FACTS" in prompt, "user_facts missing from prompt"
    assert "PROJECT MEMORY" in prompt, "project_memory missing from prompt"
    assert "LONG TERM MEMORY" in prompt, "long_term missing from prompt"
    assert "ACTIVE SESSION" in prompt, "active session missing from prompt"
    assert "CURRENT MESSAGE" in prompt, "current message missing"
    # priority order: persona is first, user_facts before project before long_term
    i_uf = prompt.index("USER FACTS")
    i_pm = prompt.index("PROJECT MEMORY")
    i_lt = prompt.index("LONG TERM MEMORY")
    assert i_uf < i_pm < i_lt, "layer priority order wrong"
    print("OK  prompt built in priority order")

    # ── Req 3: context budget exposed ──
    info = await get_context_info(cid)
    assert info["max_tokens"] == 128000, info
    assert info["current_tokens"] > 0, info
    assert 0 <= info["percentage"] <= 100, info
    assert info["remaining"] == info["max_tokens"] - info["current_tokens"], info
    assert info["active_session_messages"] >= 2, info
    print("OK  context budget: %s%% (%s/%s) remaining=%s" % (
        info["percentage"], info["current_tokens"], info["max_tokens"], info["remaining"]))

    # ── Req 5: /compact hard-compacts into Compact Memory, clears session ──
    matched, cmd = handle_context_command("/compact")
    assert matched and cmd["command"] == "compact", (matched, cmd)
    res = await compact_context(cid)
    assert res["compacted"] is True, res
    assert res["summary"], res
    cm = await eng.get_layer(ContextLayer.COMPACT_MEMORY)
    assert any("compact_" in e["key"] for e in cm), cm
    cs = await eng.get_layer(ContextLayer.CONVERSATION_SUMMARY)
    assert cs and cs[0]["key"] == "current", cs
    after = await eng.active_session_count(cid)
    assert after == 0, "active session should be cleared after compact"
    print("OK  /compact archived summary + cleared active session")

    # ── Req 6: automatic pruning when budget exceeds threshold ──
    # max_tokens=800, threshold=0.5 -> soft_limit=400 (above the small amount of
    # shared persistent memory, leaving room for the active session to be pruned).
    small = ContextEngine(max_tokens=800, prune_threshold=0.5)
    for i in range(40):
        await small.add_interaction(DEFAULT_USER, "prune-conv",
                                    "message number %d content here" % i,
                                    "acknowledged message number %d" % i)
    budget = await small.get_budget("prune-conv")
    # Pruning targets the active session, so the total must stay within budget.
    assert budget.current_tokens <= budget.max_tokens, budget.current_tokens
    n = await small.active_session_count("prune-conv")
    assert n < 80, "pruning did not reduce active session (%d)" % n
    print("OK  auto-prune kept budget bounded (kept %d msgs, %s tokens)" % (n, budget.current_tokens))

    # ── Req 8: persistence (fresh engine reads same DB) ──
    eng2 = ContextEngine()
    c2 = await eng2.get_layer(ContextLayer.USER_FACTS)
    assert c2 and c2[0]["value"] == "Ashut", c2
    print("OK  memory persists across engine instances (sqlite)")

    print("\nALL CONTEXT ENGINE LOGIC CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
