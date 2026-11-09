"""Typed application configuration (T008)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Google Gemini API & Model Roles
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    llm_fast_model: str = Field(default="gemini/gemini-3.5-flash-lite", alias="LLM_FAST_MODEL")
    llm_answer_model: str = Field(default="gemini/gemini-3.5-flash-lite", alias="LLM_ANSWER_MODEL")
    embedding_model: str = Field(default="gemini/gemini-embedding-001", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=768, alias="EMBEDDING_DIM")

    # Reranker ("gemini_flash" | "local_bge" | "heuristic")
    reranker_provider: Literal["gemini_flash", "local_bge", "heuristic"] = Field(
        default="gemini_flash", alias="RERANKER_PROVIDER"
    )
    local_reranker_model: str = Field(
        default="BAAI/bge-reranker-v2-m3", alias="LOCAL_RERANKER_MODEL"
    )
    rerank_min_score: float = Field(default=0.25, alias="RERANK_MIN_SCORE")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./.data/local_demo.db",
        alias="DATABASE_URL",
    )

    # Auth & Security
    session_secret: str = Field(
        default="dev-session-secret-change-me-in-production-32b", alias="SESSION_SECRET"
    )
    session_cookie_name: str = "rag_session"
    session_cookie_secure: bool = Field(default=False, alias="SESSION_COOKIE_SECURE")
    session_sliding_hours: int = 8
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    field_encryption_key: str = Field(
        default="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        alias="FIELD_ENCRYPTION_KEY",
    )

    # Agent & Turn Hard Limits (FR-012, FR-014, Constitution V)
    max_clarifications_per_question: int = Field(
        default=2, alias="MAX_CLARIFICATIONS_PER_QUESTION"
    )
    max_turn_llm_calls: int = Field(default=8, alias="MAX_TURN_LLM_CALLS")
    max_retrieval_rounds: int = Field(default=2, alias="MAX_RETRIEVAL_ROUNDS")
    max_turn_input_tokens: int = Field(default=60000, alias="MAX_TURN_INPUT_TOKENS")
    max_turn_cost_usd: float = Field(default=0.05, alias="MAX_TURN_COST_USD")
    rate_limit_questions_per_minute: int = 30

    # Document Upload & Storage
    blob_store_backend: Literal["local", "s3"] = Field(default="local", alias="BLOB_STORE_BACKEND")
    blob_store_local_dir: str = Field(default=".data/blobs", alias="BLOB_STORE_LOCAL_DIR")
    s3_endpoint_url: str | None = None
    s3_bucket: str = "rag-documents"
    max_upload_file_bytes: int = Field(default=50 * 1024 * 1024, alias="MAX_UPLOAD_FILE_BYTES")
    max_upload_files_count: int = Field(default=20, alias="MAX_UPLOAD_FILES_COUNT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
