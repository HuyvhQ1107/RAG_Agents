"""RAG package."""

from app.rag.access_filter import (
    apply_document_access_filter,
    build_accessible_documents_predicate,
    verify_user_can_access_document,
)
from app.rag.citation_verifier import (
    CitationVerificationResult,
    VerifiedCitation,
    verify_citations,
)
from app.rag.prompt_loader import PromptTemplate, load_prompt
from app.rag.retriever import HybridRetriever, RetrievedPassage, reciprocal_rank_fusion
from app.rag.summarizer import (
    format_sources_xml,
    load_document_passages_for_summary,
    summarize_single_document,
)

__all__ = [
    "CitationVerificationResult",
    "HybridRetriever",
    "PromptTemplate",
    "RetrievedPassage",
    "VerifiedCitation",
    "apply_document_access_filter",
    "build_accessible_documents_predicate",
    "format_sources_xml",
    "load_document_passages_for_summary",
    "load_prompt",
    "reciprocal_rank_fusion",
    "summarize_single_document",
    "verify_citations",
    "verify_user_can_access_document",
]
