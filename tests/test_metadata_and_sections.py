"""Regression tests for document metadata and section extraction.

Covers the metadata column end-to-end: store round-trip, update (replace
semantics), version restore, Markdown round-trip, and search-hit decoding
(tags/metadata must come back as Python objects, not raw JSON strings).
"""

from pathlib import Path

from kb_mcp_lite.md_io import doc_from_frontmatter, parse_frontmatter, render_document
from kb_mcp_lite.schema import Document
from kb_mcp_lite.store.sqlite import SqliteStore


def test_document_extract_sections():
    body = """Intro paragraph before any headings.

# Overview
This is overview content.

## Sub Section
Detailed technical notes.

# Conclusion
Final thoughts.
"""
    doc = Document(id="proj/test", type="project", title="Test", body=body)
    sections = doc.extract_sections()
    assert "" in sections
    assert "Intro paragraph" in sections[""]
    assert "Overview" in sections
    assert "Sub Section" in sections
    assert "Conclusion" in sections
    assert "Final thoughts." in sections["Conclusion"]

    # Test get_section with fuzzy matching
    assert "overview content" in doc.get_section("Overview")
    assert "overview content" in doc.get_section("overview")
    assert "Detailed technical notes" in doc.get_section("sub section")
    assert doc.get_section("Nonexistent") is None


def test_metadata_roundtrip_store(tmp_path: Path):
    db_path = tmp_path / "kb.db"
    store = SqliteStore(db_path)

    meta = {
        "status": "accepted",
        "deciders": ["alice", "bob"],
        "severity": "high",
        "nested": {"key": 123},
    }
    doc = Document(
        id="dec/arch-decision",
        type="decision",
        title="Arch Decision",
        body="## Context\nWe need a database.",
        tags=["arch", "database"],
        metadata=meta,
    )
    store.add(doc)

    fetched = store.get("dec/arch-decision")
    assert fetched.metadata == meta
    assert fetched.metadata["status"] == "accepted"
    assert fetched.metadata["deciders"] == ["alice", "bob"]

    # metadata update replaces the whole dict (pass {} to clear) — no merge.
    store.update(
        "dec/arch-decision",
        metadata={"status": "deprecated", "superseded_by": "dec/new-db"},
    )
    updated = store.get("dec/arch-decision")
    assert updated.metadata == {
        "status": "deprecated",
        "superseded_by": "dec/new-db",
    }

    # Non-dict metadata is rejected with a clear error.
    from kb_mcp_lite.schema import ValidationError

    try:
        store.update("dec/arch-decision", metadata="not-a-dict")
    except ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError for non-dict metadata")

    store.close()


def test_restore_rolls_back_metadata(tmp_path: Path):
    """kb restore must roll the metadata dict back to the target snapshot."""
    db_path = tmp_path / "kb.db"
    store = SqliteStore(db_path)

    v1_meta = {"status": "accepted", "deciders": ["alice"], "impact": "high"}
    store.add(
        Document(
            id="dec/restore-meta",
            type="decision",
            title="Restore Metadata",
            body="Decision body.",
            metadata=v1_meta,
        )
    )
    store.update(
        "dec/restore-meta",
        metadata={"status": "superseded", "superseded_by": "dec/other"},
    )
    assert store.get("dec/restore-meta").metadata == {
        "status": "superseded",
        "superseded_by": "dec/other",
    }

    history = store.document_history("dec/restore-meta")
    create_entry = next(e for e in history if e["action"] == "create")
    store.restore("dec/restore-meta", version_id=create_entry["version_id"])

    restored = store.get("dec/restore-meta")
    assert restored.metadata == v1_meta
    store.close()


def test_search_hit_metadata_is_decoded(tmp_path: Path):
    """Search hits must decode tags/metadata like store.get() does.

    Regression: rows materialised by _search_fts used to keep metadata as
    the raw JSON string '{}' instead of a dict.
    """
    db_path = tmp_path / "kb.db"
    store = SqliteStore(db_path)
    store.add(
        Document(
            id="lesson/lexicon-quirk",
            type="lesson",
            title="Lexicon Quirk",
            body="The uniquelexicon token appears here.",
            tags=["search"],
            metadata={"kind": "special", "priority": 2},
        )
    )

    hits = store.search("uniquelexicon", mode="lexical")
    assert hits, "expected at least one lexical hit"
    doc = hits[0].doc
    assert doc.tags == ["search"]
    assert isinstance(doc.metadata, dict)
    assert doc.metadata == {"kind": "special", "priority": 2}
    store.close()


def test_metadata_markdown_roundtrip():
    meta = {
        "status": "proposed",
        "affected_components": ["auth", "gateway"],
    }
    doc = Document(
        id="auth-token-leak",
        type="lesson",
        title="Auth Token Leak",
        body="# Root Cause\nMisconfigured header.",
        tags=["security"],
        metadata=meta,
    )

    rendered = render_document(doc)
    assert "metadata:" in rendered or "status: proposed" in rendered

    fm, body = parse_frontmatter(rendered)
    reconstructed = doc_from_frontmatter(fm, body)

    assert reconstructed.id == doc.id
    assert reconstructed.type == doc.type
    assert reconstructed.title == doc.title
    assert reconstructed.metadata.get("status") == "proposed"
    assert reconstructed.metadata.get("affected_components") == ["auth", "gateway"]
