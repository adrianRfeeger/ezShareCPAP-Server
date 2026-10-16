"""Password-protected LAN controls for the downloader."""
import base64
import storage
import run_control
import scheduling
import diagnostics
from datetime import datetime,timezone
import upload_server
import hashlib
import hmac
import io
import re
import shlex
from urllib.parse import urlsplit
import os
from pathlib import Path
import secrets
import signal
import threading
import time
import tempfile
import zipfile

from flask import Flask, abort, redirect, render_template, request, session, jsonify, send_file, g
from waitress import create_server
import server
import archive_io


def smb_url(configured_host,request_host):
    host=server.validate_smb_host(configured_host or urlsplit('http://'+request_host).hostname or '')
    if not host:raise ValueError('SMB hostname is missing')
    address='['+host+']' if ':' in host else host
    return 'smb://cpap@'+address+'/CPAP'


def create_app(config_path='/config/server.json', password=None, start_scheduler=True):
    config_path = Path(config_path)
    server.load_config(config_path)
    if password is None:
        password = Path(os.environ.get('WEB_PASSWORD_FILE', '/run/secrets/web_password')).read_text().strip()
    if len(password) < 16:
        raise ValueError('Web password must contain at least 16 characters')
    app = Flask(__name__)
    app.request_class=upload_server.UploadRequest
    app.config['UPLOAD_AUTH']='Basic '+base64.b64encode(('admin:'+password).encode()).decode()
    app.secret_key = hashlib.sha256(('ezshare-session:' + password).encode()).digest()
    app.config.update(CONFIG_PATH=config_path, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict', MAX_CONTENT_LENGTH=4096)
    action_lock = threading.Lock()
    workers = []
    app.config['WORKERS'] = workers
    transfers=set()
    transfers_lock=threading.Lock()
    app.config.update(TRANSFERS=transfers, TRANSFERS_LOCK=transfers_lock)
    root=Path(server.load_config(config_path)['root'])
    try:
        with archive_io.transfer_lock(root): pass
    except BlockingIOError: pass

    def config():
        cfg = server.load_config(config_path)
        cfg['_config_path'] = str(config_path.resolve())
        return cfg

    def live_state():
        cfg=config();state=server.read_live_state(root)
        state['diagnostics']={'wifi':diagnostics.read_wifi_status('/diagnostics/wifi.json',datetime.now(timezone.utc))}
        try:state['diagnostics']['card']=__import__('json').loads((root/'state/card-check.json').read_text())
        except (OSError,ValueError):state['diagnostics']['card']={}
        state['schedule']=scheduling.schedule_status(datetime.now(timezone.utc),cfg,state)
        return state

    @app.before_request
    def protect():
        if request.endpoint == 'import_zip':
            request.max_content_length = archive_io.MAX_ZIP_BYTES + 1024 * 1024
        credentials = request.authorization
        if not credentials or not hmac.compare_digest(credentials.username or '', 'admin') or not hmac.compare_digest(credentials.password or '', password):
            return 'Sign in as admin.', 401, {'WWW-Authenticate': 'Basic realm="ezShareCPAP"'}
        if request.endpoint in ('import_zip','download_zip'):
            g.transfer_done=threading.Event()
            with transfers_lock: transfers.add(g.transfer_done)
        if request.method == 'POST':
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                abort(403)
            if not session.get('csrf') or not hmac.compare_digest(request.form.get('csrf', ''), session['csrf']):
                abort(403)
        session.setdefault('csrf', secrets.token_hex(32))

    @app.teardown_request
    def finish_transfer(error):
        event=getattr(g,'transfer_done',None)
        if event:
            event.set()
            with transfers_lock: transfers.discard(event)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get('/')
    def index():
        cfg = config()
        status = live_state()
        return render_template('index.html', cfg=cfg, status=status, csrf=session['csrf'],
                               notice=request.args.get('notice', ''),smb_address=smb_url(cfg.get('smb_host',''),request.host))

    @app.get('/connect-mac.zip')
    def connect_mac():
        try:url=smb_url(config().get('smb_host',''),request.host)
        except ValueError:abort(400)
        script="""#!/bin/bash
# Open the read-only CPAP share. macOS asks for the SMB password.
printf '%s\\n' 'Connecting to the CPAP share. Sign in as cpap when Finder asks.'
/usr/bin/open """+shlex.quote(url)+"""
result=$?
if [ "$result" -ne 0 ]; then
    printf '%s\\n' 'Could not open Finder. Check that your server is reachable.'
    read -r -p 'Press Return to close.'
fi
exit "$result"
"""
        payload=io.BytesIO()
        with zipfile.ZipFile(payload,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            info=zipfile.ZipInfo('Connect-CPAP.command')
            info.create_system=3
            info.external_attr=0o100755<<16
            archive.writestr(info,script)
        payload.seek(0)
        return send_file(payload,as_attachment=True,download_name='Connect-CPAP-Mac.zip',
                         mimetype='application/zip')

    @app.get('/api/status')
    def live_status():
        return jsonify(live_state())

    @app.post('/diagnostics/check')
    def card_check():
        try:
            with server.run_lock(root/'state'):
                path=root/'state/card-check.json'
                if path.exists() and time.time()-path.stat().st_mtime<30:return 'Wait 30 seconds between checks',429
                server.atomic_json(path,diagnostics.check_card(config()))
            return redirect('/?notice=Connection+check+finished',303)
        except BlockingIOError:return 'Connection checks are available while sync and import are idle.',409

    @app.get('/api/schedule/preview')
    def preview_schedule():
        cfg=config()
        cfg.update(time=request.args.get('time',cfg['time']),timezone=request.args.get('timezone',cfg['timezone']))
        try:
            if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',cfg['time']):raise ValueError('Invalid time')
            return jsonify(scheduling.schedule_status(datetime.now(timezone.utc),cfg,live_state()))
        except (ValueError,KeyError):return jsonify(error='Enter a valid time and timezone'),400

    @app.post('/import')
    def import_zip():
        cfg=config()
        root=Path(cfg['root'])
        if server.run_is_active(root):
            return jsonify(error='A sync or import is running. Wait until it finishes, then import.'),409
        # Request form/CSRF parsing has already happened; keep the card archive locked during import.
        upload=request.files.get('archive')
        if not upload:
            return jsonify(error='Choose a ZIP of the complete SD folder'),400
        directory=root/'imports';directory.mkdir(parents=True,exist_ok=True)
        path=directory/('upload-'+secrets.token_hex(12)+'.zip')
        try:
            with archive_io.transfer_lock(root):
                lease=upload_server.request_lease(request)
                with path.open('wb') as target:
                    while block:=upload.stream.read(1024*1024):
                        if server.STOP.is_set(): raise RuntimeError('Import was interrupted')
                        target.write(block);target.flush()
                        if lease:lease.consume(len(block))
                result=archive_io.import_seed_zip(path,root)
            return jsonify(result)
        except BlockingIOError:
            return jsonify(error='A sync or import is running. Wait until it finishes, then import.'),409
        except (ValueError,zipfile.BadZipFile,RuntimeError) as exc:
            return jsonify(error=str(exc)),400
        except OSError:
            return jsonify(error='The import could not be saved. Check free space and server logs.'),507
        finally:
            path.unlink(missing_ok=True)

    @app.get('/download')
    def download_zip():
        path=None
        try:
            with archive_io.transfer_lock(Path(config()['root'])):
                path=archive_io.build_snapshot_zip(Path(config()['root']))
                response=send_file(path,as_attachment=True,download_name='CPAP-SD-card.zip',
                                   mimetype='application/zip',conditional=False)
                path.unlink()
                return response
        except BlockingIOError:
            return jsonify(error='Another archive transfer is running. Try again when it finishes.'),409
        except RuntimeError as exc:
            return jsonify(error=str(exc)),503
        except FileNotFoundError:
            return jsonify(error='No completed snapshot is available yet'),404
        except (ValueError,OSError) as exc:
            return jsonify(error=str(exc)),507
        finally:
            if path: path.unlink(missing_ok=True)

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error='Request is too large. ZIP uploads are limited to 4 GB.'),413

    @app.get('/api/storage/preview')
    def storage_preview():
        try:
            with storage.snapshot_access(root,False):
                return jsonify(storage.retention_preview(root,int(request.args.get('keep','2'))))
        except (ValueError,OSError) as exc: return jsonify(error=str(exc)),400

    @app.post('/storage/prune')
    def storage_prune():
        try:
            with server.run_lock(root/'state'):
                storage.prune_snapshots(root,config()['retention_keep'])
            return redirect('/?notice=Snapshot+cleanup+finished',303)
        except BlockingIOError: return 'A sync or import is running.',409
        except (ValueError,OSError) as exc: return str(exc),400

    @app.post('/settings')
    def settings():
        candidate = dict(config())
        candidate.pop('_config_path', None)
        candidate.update(time=request.form.get('time'), timezone=request.form.get('timezone'),
                         run_on_startup=request.form.get('run_on_startup') == 'on')
        candidate['smb_host']=request.form.get('smb_host',candidate.get('smb_host',''))
        if 'retention_keep' in request.form:
            try:candidate['retention_keep']=int(request.form['retention_keep'])
            except ValueError:return 'Snapshot count must be a number',400
            candidate['retention_enabled']=request.form.get('retention_enabled')=='on'
            if candidate['retention_enabled']:
                try:
                    with storage.snapshot_access(root,False):storage.retention_preview(root,candidate['retention_keep'])
                except (ValueError,OSError) as exc:return str(exc),400
        # Validate before replacing the actual settings; preserve card URL and paths.
        temporary = config_path.with_name('.validate-' + secrets.token_hex(8) + '.json')
        try:
            server.atomic_json(temporary, candidate)
            server.load_config(temporary)
            server.atomic_json(config_path, candidate)
        except ValueError as exc:
            return str(exc), 400
        finally:
            temporary.unlink(missing_ok=True)
        return redirect('/?notice=Schedule+saved', code=303)

    @app.post('/sync/stop')
    def stop_sync():
        try:run_control.request_stop(root,request.form.get('run_id',''))
        except ValueError as exc:return str(exc),409
        return redirect('/?notice=Stopping+after+the+current+file',303)

    @app.post('/sync/resume')
    @app.post('/sync')
    def sync():
        if not action_lock.acquire(blocking=False):
            return redirect('/?notice=A+manual+sync+is+already+running', code=303)
        cfg = config()
        resume=request.path=='/sync/resume'
        if server.run_is_active(root):
            action_lock.release();return 'A sync or import is already running',409
        def work():
            try:
                server.run_once(cfg,resume=resume)
            finally:
                action_lock.release()
        worker = threading.Thread(target=work, daemon=True)
        workers[:] = [thread for thread in workers if thread.is_alive()]
        workers.append(worker)
        worker.start()
        return redirect('/?notice=Sync+requested.+Progress+will+appear+below.', code=303)

    if start_scheduler:
        inventory=threading.Thread(target=storage.inventory_loop,args=(root,server.STOP),daemon=True)
        workers.append(inventory);inventory.start()
        scheduler = threading.Thread(target=lambda: server.serve(config()), daemon=True)
        workers.append(scheduler)
        scheduler.start()
    return app


def main():
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    application = create_app()
    root = Path(server.load_config(application.config['CONFIG_PATH'])['root'])
    uploads_tmp = root / 'imports/tmp'
    uploads_tmp.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(uploads_tmp)
    listener = create_server(application, host='0.0.0.0', port=8080, threads=4,
                             max_request_body_size=archive_io.MAX_ZIP_BYTES + 1024*1024)
    listener.channel_class=upload_server.upload_channel(root,application.config['UPLOAD_AUTH'],archive_io.MAX_ZIP_BYTES+1024*1024,server.load_config(application.config['CONFIG_PATH'])['storage_reserve_bytes'])
    signal.signal(signal.SIGTERM, server.stop)
    signal.signal(signal.SIGINT, server.stop)
    thread = threading.Thread(target=listener.run, daemon=True)
    thread.start()
    while thread.is_alive() and not server.STOP.wait(1):
        pass
    listener.close()
    # Allow an interrupted download to clean up and record its outcome.
    deadline = time.monotonic() + 15
    with application.config['TRANSFERS_LOCK']:
        active=list(application.config['TRANSFERS'])
    for event in active:
        event.wait(timeout=max(0, deadline-time.monotonic()))
    for worker in list(application.config['WORKERS']):
        worker.join(timeout=max(0, deadline - time.monotonic()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
