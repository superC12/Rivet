from backend.storage.conversations import ConversationStore
from backend.storage.database import Database


def test_conversation_round_trip(tmp_path):
    database = Database(tmp_path / "rivet.db")
    database.initialize()
    store = ConversationStore(database)
    conversation = store.create()
    store.add_message(conversation["id"], "user", "Hello from the homelab")
    store.add_message(
        conversation["id"], "assistant", "Hello.", route="LOCAL",
        trajectory=[
            {"id": "routing", "state": "complete", "timestamp_ms": 1_000},
            {"id": "routing-detail-1", "parent": "routing", "detail": "Local selected", "timestamp_ms": 1_001},
        ],
    )
    loaded = store.get(conversation["id"])
    assert loaded is not None
    assert loaded["title"] == "Hello from the homelab"
    assert [message["role"] for message in loaded["messages"]] == ["user", "assistant"]
    assert loaded["messages"][1]["trace"] == []
    assert loaded["messages"][1]["trajectory"][0]["id"] == "routing"
    assert loaded["messages"][1]["trajectory"][1]["detail"] == "Local selected"


def test_existing_database_is_migrated_for_trajectory(tmp_path):
    database = Database(tmp_path / "rivet.db")
    with database.connect() as connection:
        connection.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT, affinity_provider TEXT, affinity_model TEXT)")
        connection.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT, created_at TEXT, route TEXT, provider TEXT, model TEXT, node TEXT, latency_ms INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, action_status TEXT, trace_json TEXT)")
    database.initialize()
    with database.connect() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(messages)")}
    assert "trajectory_json" in columns


def test_delete_cascades_messages(tmp_path):
    database = Database(tmp_path / "rivet.db")
    database.initialize()
    store = ConversationStore(database)
    conversation = store.create()
    store.add_message(conversation["id"], "user", "Temporary")
    assert store.delete(conversation["id"])
    assert store.get(conversation["id"]) is None
