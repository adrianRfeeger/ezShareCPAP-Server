import json
import pytest
import server, run_control


def test_pause_is_scoped_and_survives_restart(tmp_path):
    server.atomic_json(
        tmp_path / "state/status.json", {"running": True, "last_attempt": "one"}
    )
    with server.run_lock(tmp_path / "state"):
        run_control.request_stop(tmp_path, "one")
        assert run_control.stop_requested(tmp_path, "one")
        assert not run_control.stop_requested(tmp_path, "two")
        with pytest.raises(ValueError):
            run_control.request_stop(tmp_path, "two")
    assert (
        run_control.recovery_decision(
            tmp_path, server.read_state(tmp_path), {"resume_interrupted": True}
        )
        == "paused"
    )


def test_recovery_and_stopped_run_preserve_cache(tmp_path):
    from tests.test_server import config

    cfg = config(tmp_path)
    server.atomic_json(
        tmp_path / "state/status.json", {"running": True, "last_attempt": "dead"}
    )
    assert (
        run_control.recovery_decision(tmp_path, server.read_state(tmp_path), cfg)
        == "resume"
    )

    def download(work, cfg):
        (work / "file").write_bytes(b"complete")
        run_control.request_stop(tmp_path, cfg["_run_id"])
        return True

    assert server.run_once(cfg, download=download) == 0
    state = server.read_live_state(tmp_path)
    assert state["run_state"] == "paused"
    assert state["history"][-1]["result"] == "Stopped"
    assert not (tmp_path / "published/current").exists()
    assert (tmp_path / "work/archive/file").read_bytes() == b"complete"


def test_stop_during_transfer_finishes_one_file_only(tmp_path):
    from types import SimpleNamespace
    import file_ops

    stopped = [False]

    class Response:
        headers = {"content-length": "4"}

        def raise_for_status(self):
            pass

        def iter_content(self, size):
            yield b"ab"
            stopped[0] = True
            yield b"cd"

    class Session:
        def get(self, *a, **kw):
            return Response()

    app = SimpleNamespace(
        retries=1,
        connection_delay=0,
        _is_running=True,
        should_stop=lambda: stopped[0],
        session=Session(),
    )
    assert file_ops.download_file(app, "http://card/file", tmp_path / "one")
    assert (tmp_path / "one").read_bytes() == b"abcd"
    assert not file_ops.download_file(app, "http://card/file", tmp_path / "two")
    assert not (tmp_path / "two").exists()


def test_stop_during_snapshot_preserves_previous(tmp_path, monkeypatch):
    from tests.test_server import config

    cfg = config(tmp_path)

    def download(work, cfg):
        (work / "file").write_bytes(b"data")
        return True

    assert server.run_once(cfg, download=download) == 0
    old = (tmp_path / "published/current").resolve()
    original = server.copy_archive

    def copy(src, dst, deadline):
        run_control.request_stop(tmp_path, server.read_state(tmp_path)["last_attempt"])
        return original(src, dst, deadline)

    monkeypatch.setattr(server, "copy_archive", copy)
    assert server.run_once(cfg, download=download) == 0
    assert (tmp_path / "published/current").resolve() == old
    assert server.read_live_state(tmp_path)["run_state"] == "paused"


def test_recovery_rechecks_intent_after_taking_lock(tmp_path):
    from tests.test_server import config

    cfg = config(tmp_path)
    server.atomic_json(
        tmp_path / "state/status.json", {"running": False, "run_state": "completed"}
    )
    assert (
        server.run_once(
            cfg,
            trigger="recovery",
            download=lambda *args: pytest.fail("stale recovery started"),
        )
        == 0
    )


def test_parent_bounds_a_stalled_file_process(tmp_path, monkeypatch):
    import subprocess, sys, time
    from tests.test_server import config

    cfg = config(tmp_path)
    cfg["_config_path"] = "unused"
    cfg["_run_id"] = "run"
    writer = server.ProgressWriter(tmp_path, "run")
    writer(
        {"phase": "downloading", "current_file": "test.edf", "file_attempt_id": "one"},
        force=True,
    )
    real = subprocess.Popen
    child = [None]

    def start(*args, **kwargs):
        child[0] = real(
            [sys.executable, "-c", "import time;time.sleep(30)"], start_new_session=True
        )
        return child[0]

    monkeypatch.setattr(server.subprocess, "Popen", start)
    monkeypatch.setattr(server, "FILE_TIMEOUT", 0.2)
    started = time.monotonic()
    assert server.download_archive(tmp_path, cfg) is False
    assert time.monotonic() - started < 3
    assert child[0].poll() is not None


def test_completed_resume_is_not_admitted_again(tmp_path):
    from tests.test_server import config

    cfg = config(tmp_path)
    server.atomic_json(
        tmp_path / "state/status.json", {"running": False, "run_state": "completed"}
    )
    assert (
        server.run_once(
            cfg, resume=True, download=lambda *args: pytest.fail("duplicate resume")
        )
        == 75
    )


def test_manual_resume_consumes_already_due_schedule(tmp_path):
    from tests.test_server import config
    from datetime import datetime, timezone

    cfg = config(tmp_path)
    cfg["time"] = "00:00"
    server.atomic_json(tmp_path / "state/status.json", {"run_state": "interrupted"})

    def download(work, cfg):
        (work / "file").write_bytes(b"data")
        return True

    assert server.run_once(cfg, resume=True, download=download) == 0
    assert (
        server.scheduled_date(
            datetime.now(timezone.utc),
            cfg,
            server.read_state(tmp_path).get("last_scheduled_date"),
        )
        is None
    )
