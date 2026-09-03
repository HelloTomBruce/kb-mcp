import pytest
from pathlib import Path
from kb_mcp_lite.schema import Document
from kb_mcp_lite.store.sqlite import SqliteStore
from kb_mcp_lite.context_guard import ContextGuard

def test_context_guard_evaluation(tmp_path: Path):
    db_path = tmp_path / "guard_kb.db"
    store = SqliteStore(db_path)

    # 1. Add team decisions and lessons
    dec = Document(
        id="dec/use-fastapi",
        type="decision",
        title="Use FastAPI for HTTP APIs",
        body="All backend services must use FastAPI framework and Pydantic models for validation.",
        tags=["framework", "fastapi"]
    )
    lesson = Document(
        id="lesson/dont-block-async-event-loop",
        type="lesson",
        title="Avoid Blocking Sync IO in Async Handlers",
        body="Never call time.sleep() or blocking sqlite queries inside async def endpoints.",
        tags=["async", "fastapi", "performance"]
    )
    store.add(dec)
    store.add(lesson)

    guard = ContextGuard(store=store)

    # Test mock evaluation
    res = guard.evaluate_diff()
    # No git repo in clean test dir returns clean result without crash
    assert "has_recommendations" in res
    assert "prompt_context" in res
