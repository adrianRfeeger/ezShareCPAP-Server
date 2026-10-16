import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import server


def test_real_http_download_child_publishes_and_skips_unchanged_files(tmp_path):
    downloads = []
    class Card(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith('/download'):
                downloads.append(self.path)
                body = b'representative-edf-bytes'
            else:
                body = b'<pre>2026-10-15 10:00:00 <a href="/download?file=STR.EDF">STR.EDF</a>\n</pre>'
            self.send_response(200)
            # Intentionally omit Content-Length to exercise real streaming.
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    card = ThreadingHTTPServer(('127.0.0.1', 0), Card)
    thread = Thread(target=card.serve_forever, daemon=True)
    thread.start()
    try:
        path = tmp_path / 'config.json'
        path.write_text(json.dumps({'url': f'http://127.0.0.1:{card.server_port}/dir?dir=A:',
                                    'root': str(tmp_path / 'data'), 'attempts': 1, 'timeout': 10}))
        cfg = server.load_config(path)
        cfg['_config_path'] = str(path)
        assert server.run_once(cfg) == 0
        snapshot = tmp_path / 'data/published/current/STR.EDF'
        assert snapshot.read_bytes() == b'representative-edf-bytes'
        assert server.run_once(cfg) == 0
        assert len(downloads) == 1
    finally:
        card.shutdown()
        card.server_close()
        thread.join()
