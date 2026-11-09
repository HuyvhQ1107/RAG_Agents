"""Conversation & SSE streaming endpoints (/api/v1/conversations/*) per contracts/api.md & chat-stream.md (T034)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.conversations.service import ConversationService, cancel_active_turn
from app.db.base import get_db_session
from app.db.models.auth import User

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


def get_conversation_service(request: Request) -> ConversationService:
    return request.app.state.conversation_service  # type: ignore[no-any-return]


class CreateConversationRequest(BaseModel):
    scope_document_id: uuid.UUID | None = None
    title: str | None = None


class UpdateConversationRequest(BaseModel):
    title: str | None = None
    scope_document_id: uuid.UUID | None = None


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    clarification_choice: dict[str, Any] | None = None
    as_of_date: date | None = None


@router.get("")
async def list_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    svc: ConversationService = Depends(get_conversation_service),
) -> dict[str, Any]:
    _ = cursor
    convs = await svc.list_conversations(session, user_id=user.id, limit=limit)
    return {
        "items": [
            {
                "id": str(c.id),
                "title": c.title,
                "scope_document_id": str(c.scope_document_id) if c.scope_document_id else None,
                "pending_clarification_count": c.pending_clarification_count,
                "last_activity_at": c.last_activity_at.isoformat(),
            }
            for c in convs
        ],
        "next_cursor": None,
    }


@router.post("", status_code=201)
async def create_conversation(
    payload: CreateConversationRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    svc: ConversationService = Depends(get_conversation_service),
) -> dict[str, Any]:
    conv = await svc.create_conversation(
        session,
        user_id=user.id,
        scope_document_id=payload.scope_document_id,
        title=payload.title,
    )
    return {
        "id": str(conv.id),
        "title": conv.title,
        "scope_document_id": str(conv.scope_document_id) if conv.scope_document_id else None,
        "pending_clarification_count": conv.pending_clarification_count,
        "turns": [],
    }


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    svc: ConversationService = Depends(get_conversation_service),
) -> dict[str, Any]:
    return await svc.get_conversation_detail(
        session, user_id=user.id, conversation_id=conversation_id
    )


@router.patch("/{conversation_id}")
async def patch_conversation(
    conversation_id: uuid.UUID,
    payload: UpdateConversationRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    svc: ConversationService = Depends(get_conversation_service),
) -> dict[str, Any]:
    fields_set = payload.model_fields_set
    conv = await svc.update_conversation(
        session,
        user_id=user.id,
        conversation_id=conversation_id,
        title=payload.title,
        scope_document_id=payload.scope_document_id,
        update_scope="scope_document_id" in fields_set,
    )
    return {
        "id": str(conv.id),
        "title": conv.title,
        "scope_document_id": str(conv.scope_document_id) if conv.scope_document_id else None,
    }


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    svc: ConversationService = Depends(get_conversation_service),
) -> Response:
    await svc.delete_conversation(session, user_id=user.id, conversation_id=conversation_id)
    response.status_code = 204
    return response


@router.post("/{conversation_id}/messages")
async def post_message_stream(
    conversation_id: uuid.UUID,
    payload: SendMessageRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    svc: ConversationService = Depends(get_conversation_service),
) -> StreamingResponse:
    stream = await svc.stream_message(
        session,
        user_id=user.id,
        conversation_id=conversation_id,
        content=payload.content,
        clarification_choice=payload.clarification_choice,
        as_of_date=payload.as_of_date,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{conversation_id}/messages/{turn_id}/cancel", status_code=204)
async def cancel_message(
    conversation_id: uuid.UUID,
    turn_id: uuid.UUID,
    response: Response,
    _user: User = Depends(get_current_user),
) -> Response:
    _ = conversation_id
    cancel_active_turn(turn_id)
    response.status_code = 204
    return response
