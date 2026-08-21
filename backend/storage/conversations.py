from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .database import Database


def now() -> str:
    return datetime.now(UTC).isoformat()


class ConversationStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list(self, query: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT id, title, created_at, updated_at FROM conversations"
        params: tuple[Any, ...] = ()
        if query:
            sql += " WHERE title LIKE ?"
            params = (f"%{query}%",)
        sql += " ORDER BY updated_at DESC"
        with self.database.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def create(self, title: str = "New conversation") -> dict[str, Any]:
        conversation = {"id": str(uuid4()), "title": title.strip() or "New conversation", "created_at": now(), "updated_at": now()}
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                tuple(conversation.values()),
            )
        return conversation

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            if not row:
                return None
            conversation = dict(row)
            messages = []
            for message in connection.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at", (conversation_id,)
            ).fetchall():
                item = dict(message)
                item["trace"] = json.loads(item.pop("trace_json") or "[]")
                item["trajectory"] = json.loads(item.pop("trajectory_json") or "[]")
                messages.append(item)
            conversation["messages"] = messages
            return conversation

    def rename(self, conversation_id: str, title: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title.strip()[:120], now(), conversation_id),
            )
            return cursor.rowcount > 0

    def delete(self, conversation_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            return cursor.rowcount > 0

    def add_message(self, conversation_id: str, role: str, content: str, **metadata: Any) -> dict[str, Any]:
        message = {
            "id": str(uuid4()),
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "created_at": now(),
            "route": metadata.get("route"),
            "provider": metadata.get("provider"),
            "model": metadata.get("model"),
            "node": metadata.get("node"),
            "latency_ms": metadata.get("latency_ms"),
            "prompt_tokens": metadata.get("prompt_tokens"),
            "completion_tokens": metadata.get("completion_tokens"),
            "action_status": metadata.get("action_status"),
            "trajectory_json": json.dumps(metadata.get("trajectory", [])),
        }
        # Existing callers can still write a legacy trace explicitly, while
        # new chat runs keep one durable source of truth in trajectory_json.
        if "trace" in metadata:
            message["trace_json"] = json.dumps(metadata["trace"])
        columns = ", ".join(message)
        placeholders = ", ".join("?" for _ in message)
        with self.database.connect() as connection:
            connection.execute(f"INSERT INTO messages ({columns}) VALUES ({placeholders})", tuple(message.values()))
            connection.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (message["created_at"], conversation_id))
            count = connection.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,)).fetchone()[0]
            if role == "user" and count == 1:
                title = " ".join(content.strip().split())[:52] or "New conversation"
                connection.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))
        message["trace"] = json.loads(message.pop("trace_json", "[]") or "[]")
        message["trajectory"] = json.loads(message.pop("trajectory_json"))
        return message

    def history(self, conversation_id: str, limit: int = 24) -> list[dict[str, str]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def affinity(self, conversation_id: str) -> tuple[str | None, str | None]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT affinity_provider, affinity_model FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return (row[0], row[1]) if row else (None, None)

    def set_affinity(self, conversation_id: str, provider: str, model: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE conversations SET affinity_provider = ?, affinity_model = ? WHERE id = ?",
                (provider, model, conversation_id),
            )
