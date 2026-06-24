"""Tests for slugify() CJK fallback (kb-mcp-lite v0.2.2)."""
from kb_mcp_lite.schema import slugify, make_id


def test_slugify_ascii_unchanged():
    """Pure ASCII titles produce the same slug as v0.2.1 and earlier."""
    assert slugify("Use SQLite FTS5!") == "use-sqlite-fts5"
    assert slugify("kb-mcp") == "kb-mcp"
    assert slugify("Hello World") == "hello-world"


def test_slugify_mixed_keeps_ascii_part():
    """Mixed CJK+ASCII keeps the ASCII part (since v0.1.0)."""
    assert slugify("kb-mcp 项目") == "kb-mcp"
    assert slugify("Props 属性") == "props"
    assert slugify("CMMap 组件使用指南") == "cmmap"


def test_slugify_cjk_fallback_is_stable_hash():
    """Pure-CJK titles now produce a stable cjk-<hash> slug instead of empty."""
    s1 = slugify("项目概述")
    s2 = slugify("项目概述")
    assert s1 == s2, "must be idempotent"
    assert s1.startswith("cjk-")
    assert len(s1) == 12, f"expected 12 chars (cjk- + 8 hex), got {len(s1)}: {s1!r}"


def test_slugify_digit_only_fallback():
    """Pure-digit slugs (likely truncated CJK) also trigger fallback."""
    s = slugify("1. 概述")
    assert s.startswith("cjk-") and len(s) == 12
    # And the bare number is rejected (would collide on every chapter).
    assert "1" != s


def test_slugify_different_cjk_different_hash():
    """Different CJK titles must produce different slugs."""
    a = slugify("项目概述")
    b = slugify("技术栈")
    assert a != b


def test_slugify_empty_falls_back():
    """Empty string also falls back (an empty slug would collide on every
    empty-title doc of the same type). The fallback is stable."""
    s = slugify("")
    assert s.startswith("cjk-") and len(s) == 12


def test_make_id_with_cjk_fallback():
    """make_id composes prefix with the (possibly fallback) slug."""
    assert make_id("reference", "项目概述") == "reference/cjk-cb580c2c"
    assert make_id("reference", "1. 概述") == "reference/cjk-8247761e"


def test_make_id_ascii_unchanged():
    """ASCII titles still get the prefix-based id."""
    assert make_id("project", "kb-mcp") == "proj/kb-mcp"
    assert make_id("reference", "use-sqlite-fts5") == "reference/use-sqlite-fts5"
