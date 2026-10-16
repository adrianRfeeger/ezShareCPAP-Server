"""Password-protected LAN controls for the downloader."""
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import signal
import threading
import time

from flask import Flask, abort, redirect, render_template, request, session
from waitress import create_server
import server


def create_app(config_path='/config/server.json', password=None, start_scheduler=True):
    config_path = Path(config_path)
    server.load_config(config_path)
    if password is None:
        password = Path(os.environ.get('WEB_PASSWORD_FILE', '/run/secrets/web_password')).read_text().strip()
    if len(password) < 16:
        raise ValueError('Web password must contain at least 16 characters')
    app = Flask(__name__)
    app.secret_key = hashlib.sha256(('ezshare-session:' + password).encode()).digest()
    app.config.update(CONFIG_PATH=config_path, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict', MAX_CONTENT_LENGTH=4096)
    action_lock = threading.Lock()
    workers = []
    app.config['WORKERS'] = workers

    def config():
        cfg = server.load_config(config_path)
        cfg['_config_path'] = str(config_path.resolve())
        return cfg

    @app.before_request
    def protect():
        credentials = request.authorization
        if not credentials or not hmac.compare_digest(credentials.username or '', 'admin') or not hmac.compare_digest(credentials.password or '', password):
            return 'Sign in as admin.', 401, {'WWW-Authenticate': 'Basic realm="ezShareCPAP"'}
        if request.method == 'POST':
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                abort(403)
            if not session.get('csrf') or not hmac.compare_digest(request.form.get('csrf', ''), session['csrf']):
                abort(403)
        session.setdefault('csrf', secrets.token_hex(32))

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
        status = server.read_state(Path(cfg['root']))
        return render_template('index.html', cfg=cfg, status=status, csrf=session['csrf'],
                               notice=request.args.get('notice', ''))

    @app.post('/settings')
    def settings():
        candidate = dict(config())
        candidate.pop('_config_path', None)
        candidate.update(time=request.form.get('time'), timezone=request.form.get('timezone'),
                         run_on_startup=request.form.get('run_on_startup') == 'on')
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

    @app.post('/sync')
    def sync():
        if not action_lock.acquire(blocking=False):
            return redirect('/?notice=A+manual+sync+is+already+running', code=303)
        cfg = config()
        def work():
            try:
                server.run_once(cfg)
            finally:
                action_lock.release()
        worker = threading.Thread(target=work, daemon=True)
        workers[:] = [thread for thread in workers if thread.is_alive()]
        workers.append(worker)
        worker.start()
        return redirect('/?notice=Sync+requested.+Refresh+to+see+progress.', code=303)

    if start_scheduler:
        scheduler = threading.Thread(target=lambda: server.serve(config()), daemon=True)
        workers.append(scheduler)
        scheduler.start()
    return app


def main():
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    application = create_app()
    listener = create_server(application, host='0.0.0.0', port=8080, threads=4)
    signal.signal(signal.SIGTERM, server.stop)
    signal.signal(signal.SIGINT, server.stop)
    thread = threading.Thread(target=listener.run, daemon=True)
    thread.start()
    while thread.is_alive() and not server.STOP.wait(1):
        pass
    listener.close()
    # Allow an interrupted download to clean up and record its outcome.
    deadline = time.monotonic() + 15
    for worker in list(application.config['WORKERS']):
        worker.join(timeout=max(0, deadline - time.monotonic()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
