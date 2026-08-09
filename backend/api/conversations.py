from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .dependencies import store

router = APIRouter(prefix="/api/conversations")


class ConversationPayload(BaseModel):
    title: str = Field(default="New conversation", max_length=120)


@router.get("")
async def list_conversations(q: str | None = Query(default=None, max_length=120)) -> list[dict]:
    return store.list(q)


@router.post("")
async def create_conversation(payload: ConversationPayload | None = None) -> dict:
    return store.create(payload.title if payload else "New conversation")


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict:
    conversation = store.get(conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    return conversation


@router.patch("/{conversation_id}")
async def rename_conversation(conversation_id: str, payload: ConversationPayload) -> dict:
    if not store.rename(conversation_id, payload.title):
        raise HTTPException(404, "Conversation not found")
    return {"id": conversation_id, "title": payload.title}


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str) -> Response:
    if not store.delete(conversation_id):
        raise HTTPException(404, "Conversation not found")
    return Response(status_code=204)
