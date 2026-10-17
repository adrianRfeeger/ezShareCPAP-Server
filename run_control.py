"""Persistent user pause and run-scoped stop requests shared across processes."""

import json
from pathlib import Path
import storage


def read_control(root):
    try:
        return json.loads((Path(root) / "state/control.json").read_text())
    except (OSError, ValueError):
        return {}


def control_lock(root):
    return storage.file_lock(Path(root) / "state/control.lock")


def request_stop(root, run_id):
    import server

    with control_lock(root):
        status = server.read_state(Path(root))
        if (
            status.get("last_attempt") != run_id
            or not status.get("running")
            or not server.run_is_active(Path(root))
        ):
            raise ValueError("This run has finished or changed. Refresh its status.")
        value = {"paused": True, "stop_run_id": run_id}
        storage.atomic(Path(root) / "state/control.json", value)
        return value


def stop_requested(root, run_id):
    return read_control(root).get("stop_run_id") == run_id


def clear_pause(root):
    storage.atomic(Path(root) / "state/control.json", {"paused": False})


def recovery_decision(root, status, cfg):
    if read_control(root).get("paused"):
        return "paused"
    if cfg.get("resume_interrupted", True) and (
        status.get("running") or status.get("run_state") == "interrupted"
    ):
        return "resume"
    return "none"
