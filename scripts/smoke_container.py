"""Exercise the packaged application with synthetic data in an isolated container."""
from pathlib import Path
import base64
import json
import zipfile

import archive_io
import server
import storage
import webapp

root = Path('/data')
config = root / 'config.json'
config.write_text(json.dumps({'root': str(root), 'url': 'http://127.0.0.1:9/dir?dir=A:',
                              'run_on_startup': False, 'attempts': 1, 'timeout': 10}))
cfg = server.load_config(config)


def download(work, cfg):
    (work / 'Identification.tgt').write_bytes(b'synthetic-device')
    (work / 'STR.EDF').write_bytes(b'synthetic-data')
    return True


assert server.run_once(cfg, download=download) == 0
assert server.read_live_state(root)['availability'] == 'ready'
with archive_io.transfer_lock(root):
    output = archive_io.build_snapshot_zip(root)
    with zipfile.ZipFile(output) as archive:
        assert sorted(archive.namelist()) == ['Identification.tgt', 'STR.EDF']
    output.unlink()
password = 'synthetic-smoke-password'
app = webapp.create_app(config, password, start_scheduler=False)
client = app.test_client()
assert client.get('/').status_code == 401
headers = {'Authorization': 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()}
assert client.get('/', headers=headers).status_code == 200
assert client.get('/api/status', headers=headers).json['availability'] == 'ready'
assert storage.reserved_bytes(root) == 0
print('Packaged application smoke checks passed')
