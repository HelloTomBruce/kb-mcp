"""kb-mcp: agent-native knowledge base.

A local-first, schema-first, MCP-native knowledge base for LLM agents.
See https://github.com/your-org/kb-mcp for the full spec.
"""

from kb_mcp.schema import (
    Decision,
    Document,
    DocumentType,
    DoctorCheck,
    DoctorReport,
    DuplicateError,
    Faq,
    Glossary,
    ImportReport,
    IntegrityError,
    KbMcpError,
    Lesson,
    Link,
    NotFoundError,
    Person,
    Project,
    SearchHit,
    TypeRegistry,
    ValidationError,
    default_registry,
    make_id,
    slugify,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # schema
    "Document",
    "DocumentType",
    "Project",
    "Decision",
    "Lesson",
    "Glossary",
    "Person",
    "Faq",
    "Link",
    "SearchHit",
    "ImportReport",
    "DoctorCheck",
    "DoctorReport",
    "TypeRegistry",
    "default_registry",
    "make_id",
    "slugify",
    # exceptions
    "KbMcpError",
    "NotFoundError",
    "DuplicateError",
    "ValidationError",
    "IntegrityError",
]
