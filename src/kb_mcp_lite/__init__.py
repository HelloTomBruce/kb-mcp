"""kb-mcp-lite: lightweight agent-native knowledge base.

A local-first, schema-first, MCP-native knowledge base for LLM agents.
See https://github.com/HelloTomBruce/kb-mcp-lite for the full spec.
"""

from kb_mcp_lite.reranker import (
    HttpReranker,
    NullReranker,
    RerankConfig,
    Reranker,
    RerankError,
    RerankItem,
    load_rerank_config,
    make_reranker,
)
from kb_mcp_lite.schema import (
    Decision,
    DoctorCheck,
    DoctorReport,
    Document,
    DocumentType,
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

__version__ = "0.8.7"

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
    # reranker
    "Reranker",
    "RerankConfig",
    "RerankError",
    "RerankItem",
    "HttpReranker",
    "NullReranker",
    "load_rerank_config",
    "make_reranker",
    # exceptions
    "KbMcpError",
    "NotFoundError",
    "DuplicateError",
    "ValidationError",
    "IntegrityError",
]
