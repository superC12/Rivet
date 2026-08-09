from backend.storage.conversations import ConversationStore
from backend.storage.database import Database


def test_conversation_round_trip(tmp_path):
    database = Database(tmp_path / "rivet.db")
    database.initialize()
    store = ConversationStore(database)
    conversation = store.create()
    store.add_message(conversation["id"], "user", "Hello from the homelab")
    store.add_message(conversation["id"], "assistant", "Hello.", route="LOCAL", trace=[{"time": "10:00:00", "message": "Local selected"}])
    loaded = store.get(conversation["id"])
    assert loaded is not None
    assert loaded["title"] == "Hello from the homelab"
    assert [message["role"] for message in loaded["messages"]] == ["user", "assistant"]
    assert loaded["messages"][1]["trace"][0]["message"] == "Local selected"


def test_delete_cascades_messages(tmp_path):
    database = Database(tmp_path / "rivet.db")
    database.initialize()
    store = ConversationStore(database)
    conversation = store.create()
    store.add_message(conversation["id"], "user", "Temporary")
    assert store.delete(conversation["id"])
    assert store.get(conversation["id"]) is None
