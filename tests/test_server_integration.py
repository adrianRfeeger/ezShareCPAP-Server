import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import server


def test_real_http_download_child_publishes_and_skips_unchanged_files(tmp_path):
    downloads = []

    class Card(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/download"):
                downloads.append(self.path)
                body = b"representative-edf-bytes"
            else:
                body = b'<pre>2026-10-15 10:00:00 <a href="/download?file=STR.EDF">STR.EDF</a>\n</pre>'
            self.send_response(200)
            # Intentionally omit Content-Length to exercise real streaming.
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    card = ThreadingHTTPServer(("127.0.0.1", 0), Card)
    thread = Thread(target=card.serve_forever, daemon=True)
    thread.start()
    try:
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{card.server_port}/dir?dir=A:",
                    "root": str(tmp_path / "data"),
                    "attempts": 1,
                    "timeout": 10,
                }
            )
        )
        cfg = server.load_config(path)
        cfg["_config_path"] = str(path)
        assert server.run_once(cfg) == 0
        snapshot = tmp_path / "data/published/current/STR.EDF"
        assert snapshot.read_bytes() == b"representative-edf-bytes"
        assert server.run_once(cfg) == 0
        assert len(downloads) == 1
    finally:
        card.shutdown()
        card.server_close()
        thread.join()


def test_service_restart_recovers_once_and_reuses_seed(tmp_path):
    import os, subprocess, sys, time
    from datetime import datetime, timezone

    downloads = []

    class Card(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/download"):
                downloads.append(self.path)
                body = b"new-card-data"
            else:
                body = b'<pre>2026-10-15 10:00:00 <a href="/download?file=STR.EDF">STR.EDF</a>\n2026-10-15 10:00:00 <a href="/download?file=NEW.EDF">NEW.EDF</a>\n</pre>'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    card = ThreadingHTTPServer(("127.0.0.1", 0), Card)
    thread = Thread(target=card.serve_forever, daemon=True)
    thread.start()
    root = tmp_path / "data"
    seed = root / "work/archive/STR.EDF"
    seed.parent.mkdir(parents=True)
    seed.write_bytes(b"seed-data")
    stamp = datetime(2026, 10, 15, 10, tzinfo=timezone.utc).timestamp()
    os.utime(seed, (stamp, stamp))
    server.atomic_json(
        root / "state/status.json", {"running": True, "last_attempt": "abandoned"}
    )
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "root": str(root),
                "url": f"http://127.0.0.1:{card.server_port}/dir?dir=A:",
                "run_on_startup": False,
                "attempts": 1,
                "timeout": 10,
            }
        )
    )
    process = None
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                str(__import__("pathlib").Path(server.__file__)),
                "--config",
                str(config),
                "serve",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            if (root / "published/current/NEW.EDF").exists():
                break
            time.sleep(0.05)
        assert (root / "published/current/STR.EDF").read_bytes() == b"seed-data"
        assert len(downloads) == 1 and "NEW.EDF" in downloads[0]
        for _ in range(40):
            if not server.read_state(root).get("running"):
                break
            time.sleep(0.025)
        assert server.read_state(root)["history"][-1]["trigger"] == "recovery"
        process.terminate()
        process.wait(timeout=5)
        process = subprocess.Popen(
            [sys.executable, server.__file__, "--config", str(config), "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.35)
        process.terminate()
        process.wait(timeout=5)
        assert len(downloads) == 1
    finally:
        if process and process.poll() is None:
            process.kill()
            process.wait()
        card.shutdown()
        card.server_close()
        thread.join()
