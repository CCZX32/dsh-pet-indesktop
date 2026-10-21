from __future__ import annotations

from petcore.chat.session_store import SessionStore


def test_session_store_isolated_by_slot_and_character(tmp_path) -> None:
    main = SessionStore(tmp_path, slot=0, character_id="main")
    child = SessionStore(tmp_path, slot=1, character_id="main")
    main_session = main.new_session()
    main_session.append("user", "主宠问题")
    main.save(main_session)

    assert main.load(main_session.session_id).messages[-1]["content"] == "主宠问题"
    assert child.list_sessions() == []
    assert "sessions" in str(main.directory)
    assert "sessions-slot-1" in str(child.directory)


def test_session_store_limits_messages_and_writes_atomically(tmp_path) -> None:
    store = SessionStore(tmp_path, slot=2, character_id="safe")
    session = store.new_session()
    for index in range(250):
        session.append("user", f"message-{index}")
    store.save(session)

    loaded = store.load(session.session_id)
    assert loaded is not None
    assert len(loaded.messages) == 200
    assert loaded.messages[0]["content"] == "message-50"
    assert not list(store.directory.glob("*.tmp"))


def test_session_store_rejects_path_escape(tmp_path) -> None:
    store = SessionStore(tmp_path)
    try:
        store.load("../outside")
    except ValueError as exc:
        assert "session id" in str(exc)
    else:
        raise AssertionError("path escape must be rejected")
