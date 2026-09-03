import pytest
from kb_mcp_lite.merge import merge_frontmatter_dicts, resolve_git_conflict_text

def test_merge_frontmatter_dicts():
    ours = {
        "title": "New Title",
        "tags": ["python", "api"],
        "aliases": ["corp-api"],
        "metadata": {"status": "accepted", "owner": "alice"}
    }
    theirs = {
        "title": "Old Title",
        "tags": ["api", "cloud"],
        "aliases": ["v1-api"],
        "metadata": {"status": "proposed", "team": "platform"}
    }
    
    merged = merge_frontmatter_dicts(ours, theirs)
    assert set(merged["tags"]) == {"python", "api", "cloud"}
    assert set(merged["aliases"]) == {"corp-api", "v1-api"}
    assert merged["metadata"]["status"] == "accepted" # ours wins status
    assert merged["metadata"]["team"] == "platform"  # merged theirs key
    assert merged["metadata"]["owner"] == "alice"

def test_resolve_git_conflict_text():
    conflict_doc = """<<<<<<< HEAD
title: Feature A
tags:
  - fast
  - reliable
=======
title: Feature A
tags:
  - secure
  - reliable
>>>>>>> branch-b

# Body Content
Working smoothly.
"""
    resolved, text = resolve_git_conflict_text(conflict_doc)
    assert resolved is True
    assert "reliable" in text
    assert "fast" in text
    assert "secure" in text
    assert "<<<<<<<" not in text
