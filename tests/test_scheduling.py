from datetime import datetime, timezone
from scheduling import schedule_decision, schedule_status

CFG = {"time": "02:30", "timezone": "Australia/Melbourne"}


def test_dst_gap_repeat_and_catchup():
    gap = schedule_decision(
        datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc), CFG, None
    )
    assert gap["next_run_at"] == datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc)
    assert (
        schedule_decision(datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc), CFG, None)[
            "due_date"
        ]
        == "2026-10-04"
    )
    assert (
        schedule_decision(
            datetime(2026, 4, 4, 16, 30, tzinfo=timezone.utc), CFG, "2026-04-05"
        )["due_date"]
        is None
    )
    assert (
        schedule_decision(
            datetime(2026, 10, 16, 3, tzinfo=timezone.utc), CFG, "2026-10-01"
        )["due_date"]
        == "2026-10-16"
    )


def test_schedule_warnings_and_pause():
    now = datetime(2026, 10, 16, 3, tzinfo=timezone.utc)
    state = {
        "paused": True,
        "last_success": "2026-10-14T00:00:00Z",
        "history": [{"trigger": "scheduled", "result": "Failed"}] * 2
        + [{"trigger": "manual", "result": "Failed"}],
    }
    status = schedule_status(now, CFG, state)
    assert (
        status["next_run_at"] is None and status["consecutive_scheduled_failures"] == 2
    )
    assert len(status["warnings"]) == 2
    state["history"].append({"trigger": "scheduled", "result": "Success"})
    assert schedule_status(now, CFG, state)["consecutive_scheduled_failures"] == 0
