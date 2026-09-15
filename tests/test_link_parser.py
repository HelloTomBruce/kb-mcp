"""Tests for body reference parser (v0.8 特性 #4)."""

from kb_mcp_lite.link_parser import extract_body_references, sync_body_references
from kb_mcp_lite.schema import Document
from kb_mcp_lite.store.sqlite import SqliteStore

# ---------------------------------------------------------------------------
# extract_body_references
# ---------------------------------------------------------------------------


class TestExtractBodyReferences:
    def test_markdown_link(self):
        body = "See [the lesson](lesson/dont-mix-sqlite-libs) for details."
        known = {"lesson/dont-mix-sqlite-libs"}
        refs = extract_body_references(body, known)
        assert refs == [("lesson/dont-mix-sqlite-libs", "markdown")]

    def test_code_ref(self):
        body = "The `dec/use-sqlite-fts5` decision was made."
        known = {"dec/use-sqlite-fts5"}
        refs = extract_body_references(body, known)
        assert refs == [("dec/use-sqlite-fts5", "code")]

    def test_skips_unknown_ids(self):
        body = "[link](dec/nonexistent)"
        refs = extract_body_references(body, known_ids=set())
        assert refs == []

    def test_skips_fenced_code_blocks(self):
        body = "```\n`dec/fake`\n```\nBut [real](dec/real)"
        known = {"dec/real", "dec/fake"}
        refs = extract_body_references(body, known)
        assert refs == [("dec/real", "markdown")]

    def test_inline_code_and_markdown(self):
        body = "Use `dec/fake` and [real](dec/real)."
        known = {"dec/real", "dec/fake"}
        refs = extract_body_references(body, known)
        # Both inline code and markdown link are valid reference syntaxes
        ids = {r[0] for r in refs}
        assert ids == {"dec/real", "dec/fake"}

    def test_deduplicates(self):
        body = "[a](proj/x) and `proj/x` again."
        known = {"proj/x"}
        refs = extract_body_references(body, known)
        # Only one reference to proj/x
        assert len(refs) == 1
        assert refs[0] == ("proj/x", "markdown")

    def test_multiple_refs(self):
        body = "See [A](proj/a) and `lesson/b`."
        known = {"proj/a", "lesson/b"}
        refs = extract_body_references(body, known)
        assert len(refs) == 2
        ids = {r[0] for r in refs}
        assert ids == {"proj/a", "lesson/b"}

    def test_empty_body(self):
        assert extract_body_references("", {"x"}) == []

    def test_empty_known_ids(self):
        assert extract_body_references("See [a](proj/a)", set()) == []

    def test_invalid_id_format(self):
        # IDs with uppercase or special chars should not match
        body = "[link](Proj/Invalid)"
        known = {"Proj/Invalid"}
        refs = extract_body_references(body, known)
        assert refs == []  # uppercase not in pattern

    def test_disable_markdown_links(self):
        body = "See [a](proj/a)"
        known = {"proj/a"}
        refs = extract_body_references(body, known, markdown_links=False)
        assert refs == []

    def test_disable_code_refs(self):
        body = "Use `proj/a`"
        known = {"proj/a"}
        refs = extract_body_references(body, known, code_refs=False)
        assert refs == []


# ---------------------------------------------------------------------------
# sync_body_references (integration)
# ---------------------------------------------------------------------------


class TestSyncBodyReferences:
    def test_creates_references_links(self, tmp_path):
        store = SqliteStore(tmp_path / "test.db")
        store.add(
            Document(id="source", type="decision", title="Source", body="See [target](target/doc).")
        )
        store.add(Document(id="target/doc", type="lesson", title="Target"))

        count = sync_body_references(store, "source", "See [target](target/doc).")
        assert count == 1
        links = store.outgoing_links("source")
        assert any(link.to_id == "target/doc" and link.rel == "references" for link in links)
        store.close()

    def test_no_refs_no_links(self, tmp_path):
        store = SqliteStore(tmp_path / "test.db")
        store.add(Document(id="a", type="decision", title="A", body="No refs here."))
        store.add(Document(id="b", type="lesson", title="B"))

        count = sync_body_references(store, "a", "No refs here.")
        assert count == 0
        assert store.outgoing_links("a") == []
        store.close()

    def test_removes_stale_references(self, tmp_path):
        store = SqliteStore(tmp_path / "test.db")
        store.add(Document(id="src", type="decision", title="Src", body="See [old](old/doc)."))
        store.add(Document(id="old/doc", type="lesson", title="Old"))
        store.add(Document(id="new/doc", type="lesson", title="New"))

        # First sync creates link
        sync_body_references(store, "src", "See [old](old/doc).")
        assert len(store.outgoing_links("src")) == 1

        # Second sync with different body removes old, adds new
        sync_body_references(store, "src", "See [new](new/doc).")
        links = store.outgoing_links("src")
        link_ids = {link.to_id for link in links}
        assert "new/doc" in link_ids
        assert "old/doc" not in link_ids
        store.close()


# ---------------------------------------------------------------------------
# Auto-link integration (add/update)
# ---------------------------------------------------------------------------


class TestAutoLinkIntegration:
    def test_add_creates_auto_links(self, tmp_path):
        store = SqliteStore(tmp_path / "test.db")
        store.add(Document(id="ref-target", type="lesson", title="Target"))
        store.add(
            Document(
                id="ref-source", type="decision", title="Source", body="See [target](ref-target)."
            )
        )

        links = store.outgoing_links("ref-source")
        assert any(link.to_id == "ref-target" and link.rel == "references" for link in links)
        store.close()

    def test_update_body_syncs_links(self, tmp_path):
        store = SqliteStore(tmp_path / "test.db")
        store.add(Document(id="t1", type="lesson", title="T1"))
        store.add(Document(id="t2", type="lesson", title="T2"))
        store.add(Document(id="src", type="decision", title="Src", body="Ref [t1](t1)."))

        # Verify initial link
        assert any(link.to_id == "t1" for link in store.outgoing_links("src"))

        # Update body to reference t2
        store.update("src", body="Ref [t2](t2).")
        links = store.outgoing_links("src")
        link_ids = {link.to_id for link in links}
        assert "t2" in link_ids
        assert "t1" not in link_ids
        store.close()
