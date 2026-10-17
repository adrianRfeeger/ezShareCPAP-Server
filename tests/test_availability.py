import server, storage


def test_seeded_and_failed_published_states(tmp_path):
    server.atomic_json(
        tmp_path / "state/import.json",
        {
            "imported": 7,
            "kept": 2,
            "phase": "completed",
            "completed_at": "2026-10-16T00:00:00+00:00",
        },
    )
    state = server.read_live_state(tmp_path)
    assert state["availability"] == "seeded_pending"
    assert state["archive"]["last_import_added"] == 7
    p = tmp_path / "published/snapshot"
    p.mkdir(parents=True)
    (tmp_path / "published/current").symlink_to("snapshot")
    server.atomic_json(
        tmp_path / "state/status.json",
        {"snapshot": "snapshot", "error": "previous failed", "files": 9},
    )
    assert server.read_live_state(tmp_path)["availability"] == "ready"


def test_inventory_unknown_and_clamped(tmp_path):
    server.atomic_json(tmp_path / "state/status.json", {"last_attempt": "run"})
    writer = server.ProgressWriter(tmp_path, "run")
    writer({"phase": "scanning"}, force=True)
    assert (
        server.read_live_state(tmp_path)["progress"]["inventory"]["remaining"] is None
    )
    writer(
        {"phase": "downloading", "files_total": 4, "files_done": 5, "card_files": 10},
        force=True,
    )
    inventory = server.read_live_state(tmp_path)["progress"]["inventory"]
    assert inventory["remaining"] == 0 and inventory["reused_files"] == 6
