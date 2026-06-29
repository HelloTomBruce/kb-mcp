"""Versioning mixin for SqliteStore — history, restore, diff, audit."""

from __future__ import annotations

import json
import sqlite3

from kb_mcp_lite.schema import Document, NotFoundError, ValidationError

_DEFAULT_ACTOR = "mcp-server"


class VersioningMixin:
    """Mixin providing document versioning methods.

    Requires the host class to expose ``self._conn``, ``self._txn()``,
    ``self._now_iso()``, ``self.get()``, ``self.update()``,
    ``self._record_doc_version()``, ``self._record_audit()``,
    and ``self._index_embedding()``.
    """

    def _record_doc_version(
        self,
        cur: sqlite3.Cursor,
        doc: Document,
        *,
        action: str,
        actor: str = _DEFAULT_ACTOR,
        note: str = "",
    ) -> None:
        cur.execute(
            """
            INSERT INTO document_versions (doc_id, action, snapshot, created_at, actor, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                doc.id,
                action,
                json.dumps(doc.model_dump(mode="json"), ensure_ascii=False),
                self._now_iso(),
                actor,
                note,
            ),
        )

    def _record_audit(
        self,
        cur: sqlite3.Cursor,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        detail: dict[str, object],
        actor: str = _DEFAULT_ACTOR,
        note: str = "",
    ) -> None:
        cur.execute(
            """
            INSERT INTO audit_log (entity_type, entity_id, action, detail, created_at, actor, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_type,
                entity_id,
                action,
                json.dumps(detail, ensure_ascii=False, default=str),
                self._now_iso(),
                actor,
                note,
            ),
        )

    def document_history(self, doc_id: str, limit: int = 50) -> list[dict[str, object]]:
        rows = self._conn.execute(
            """
            SELECT version_id, doc_id, action, snapshot, created_at, actor, note
            FROM document_versions
            WHERE doc_id = ?
            ORDER BY version_id DESC
            LIMIT ?
            """,
            (doc_id, limit),
        ).fetchall()
        out: list[dict[str, object]] = []
        for row in rows:
            out.append(
                {
                    "version_id": row["version_id"],
                    "doc_id": row["doc_id"],
                    "action": row["action"],
                    "snapshot": json.loads(row["snapshot"]),
                    "created_at": row["created_at"],
                    "actor": row["actor"],
                    "note": row["note"],
                }
            )
        return out

    def audit_log(self, limit: int = 100) -> list[dict[str, object]]:
        rows = self._conn.execute(
            """
            SELECT audit_id, entity_type, entity_id, action, detail, created_at, actor, note
            FROM audit_log
            ORDER BY audit_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        out: list[dict[str, object]] = []
        for row in rows:
            out.append(
                {
                    "audit_id": row["audit_id"],
                    "entity_type": row["entity_type"],
                    "entity_id": row["entity_id"],
                    "action": row["action"],
                    "detail": json.loads(row["detail"] or "{}"),
                    "created_at": row["created_at"],
                    "actor": row["actor"],
                    "note": row["note"],
                }
            )
        return out

    def _fetch_version(self, doc_id: str, version_id: int) -> dict[str, object] | None:
        row = self._conn.execute(
            """
            SELECT version_id, doc_id, action, snapshot, created_at, actor, note
            FROM document_versions
            WHERE doc_id = ? AND version_id = ?
            """,
            (doc_id, version_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "version_id": row["version_id"],
            "doc_id": row["doc_id"],
            "action": row["action"],
            "snapshot": json.loads(row["snapshot"]),
            "created_at": row["created_at"],
            "actor": row["actor"],
            "note": row["note"],
        }

    def restore(self, doc_id: str, version_id: int | None = None) -> Document:
        """Restore a document to a previous version."""
        self.get(doc_id, include_deleted=True)
        if version_id is not None:
            entry = self._fetch_version(doc_id, version_id)
            if entry is None:
                raise NotFoundError(f"version {version_id} for {doc_id!r}")
        else:
            history = self.document_history(doc_id, limit=1)
            if not history:
                raise NotFoundError(f"no versions found for {doc_id!r}")
            entry = history[0]
        snapshot = dict(entry["snapshot"])
        snapshot["id"] = doc_id
        restored_doc = Document.model_validate(snapshot)
        fields: dict[str, object] = {}
        for f in ("title", "body", "tags", "source"):
            fields[f] = getattr(restored_doc, f, None)
        return self.update(doc_id, **fields)

    def diff(
        self,
        doc_id: str,
        version_a: int,
        version_b: int,
    ) -> dict[str, object]:
        """Compare two document versions."""
        entry_a = self._fetch_version(doc_id, version_a)
        if entry_a is None:
            raise NotFoundError(f"version {version_a} for {doc_id!r}")
        entry_b = self._fetch_version(doc_id, version_b)
        if entry_b is None:
            raise NotFoundError(f"version {version_b} for {doc_id!r}")
        snap_a: dict[str, object] = entry_a["snapshot"]
        snap_b: dict[str, object] = entry_b["snapshot"]
        keys_a = set(snap_a.keys())
        keys_b = set(snap_b.keys())
        added: dict[str, object] = {}
        removed: dict[str, object] = {}
        changed: dict[str, dict[str, object]] = {}
        for k in keys_b - keys_a:
            added[k] = snap_b[k]
        for k in keys_a - keys_b:
            removed[k] = snap_a[k]
        for k in keys_a & keys_b:
            if snap_a[k] != snap_b[k]:
                changed[k] = {"from": snap_a[k], "to": snap_b[k]}
        return {
            "doc_id": doc_id,
            "version_a": version_a,
            "version_b": version_b,
            "added": added,
            "removed": removed,
            "changed": changed,
        }

    def restore_deleted(self, doc_id: str) -> Document:
        """Restore a soft-deleted document."""
        doc = self.get(doc_id, include_deleted=True)
        if doc.deleted_at is None:
            raise ValidationError(f"document {doc_id!r} is not deleted")
        now = self._now_iso()
        with self._txn() as cur:
            cur.execute(
                "UPDATE documents SET deleted_at = NULL, updated_at = ? WHERE id = ?",
                (now, doc_id),
            )
            restored_doc = doc.model_copy(update={"deleted_at": None})
            self._record_doc_version(cur, restored_doc, action="restore")
            self._record_audit(
                cur,
                entity_type="document",
                entity_id=doc_id,
                action="restore",
                detail={"title": doc.title, "type": doc.type},
            )
        self._index_embedding(restored_doc)
        return self.get(doc_id)


__all__ = ["VersioningMixin"]
