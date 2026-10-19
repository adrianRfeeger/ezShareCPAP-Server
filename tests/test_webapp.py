import base64
import json
import pytest
import webapp


@pytest.fixture
def app(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"root": str(tmp_path / "data"), "url": "http://card/dir?dir=A:"})
    )
    return webapp.create_app(path, "test-password-at-least-16", start_scheduler=False)


def auth():
    return {
        "Authorization": "Basic "
        + base64.b64encode(b"admin:test-password-at-least-16").decode()
    }


def test_status_requires_login(app):
    client = app.test_client()
    assert client.get("/").status_code == 401
    assert client.get("/", headers=auth()).status_code == 200


def test_settings_need_csrf_and_validate_timezone(app):
    client = app.test_client()
    assert (
        client.post("/settings", headers=auth(), data={"time": "11:00"}).status_code
        == 403
    )
    client.get("/", headers=auth())
    with client.session_transaction() as session:
        token = session["csrf"]
    assert (
        client.post(
            "/settings",
            headers=auth(),
            data={"csrf": token, "time": "99:00", "timezone": "bad"},
        ).status_code
        == 400
    )
    response = client.post(
        "/settings",
        headers=auth(),
        data={
            "csrf": token,
            "time": "11:00",
            "timezone": "Australia/Melbourne",
            "run_on_startup": "on",
        },
    )
    assert response.status_code == 303
    assert json.loads(app.config["CONFIG_PATH"].read_text())["time"] == "11:00"


def test_cross_origin_post_is_rejected(app):
    client = app.test_client()
    client.get("/", headers=auth())
    with client.session_transaction() as session:
        token = session["csrf"]
    assert (
        client.post(
            "/sync",
            headers=dict(auth(), Origin="https://attacker.test"),
            data={"csrf": token},
        ).status_code
        == 403
    )


def test_first_post_cannot_use_predictable_missing_token(app):
    client = app.test_client()
    assert (
        client.post(
            "/settings",
            headers=auth(),
            data={
                "csrf": "missing",
                "time": "11:00",
                "timezone": "Australia/Melbourne",
            },
        ).status_code
        == 403
    )


def test_live_status_api_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/status").status_code == 401
    response = client.get("/api/status", headers=auth())
    assert response.status_code == 200
    assert response.json["progress"]["percent"] is None
    assert response.headers["Cache-Control"] == "no-store"


def test_page_serves_illustration_and_eta_module(app):
    client = app.test_client()
    page = client.get("/", headers=auth()).text
    assert "/static/cpap-artwork.png" in page
    assert 'id="download-eta"' in page
    assert 'type="module" src="/static/progress.js"' in page
    module = client.get("/static/eta.mjs", headers=auth())
    assert module.status_code == 200
    assert "javascript" in module.content_type
    image = client.get("/static/cpap-artwork.png", headers=auth())
    assert image.status_code == 200 and image.data.startswith(b"\x89PNG\r\n\x1a\n")


def test_upload_imports_full_card_zip(app):
    import io, zipfile

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("Identification.tgt", b"device-one")
        archive.writestr("DATALOG/night.edf", b"sample")
    stream.seek(0)
    client = app.test_client()
    client.get("/", headers=auth())
    with client.session_transaction() as session:
        token = session["csrf"]
    response = client.post(
        "/import",
        headers=auth(),
        data={"csrf": token, "archive": (stream, "SD_card.zip")},
    )
    assert response.status_code == 200
    assert response.json["imported"] == 2
    root = app.config["CONFIG_PATH"].parent / "data"
    assert (root / "work/archive/DATALOG/night.edf").read_bytes() == b"sample"


def test_download_has_zip_attachment_and_no_working_files(app):
    import io, zipfile

    root = app.config["CONFIG_PATH"].parent / "data"
    snap = root / "published/complete"
    snap.mkdir(parents=True)
    (snap / "Identification.tgt").write_bytes(b"device-one")
    (snap.parent / "current").symlink_to("complete")
    response = app.test_client().get("/download", headers=auth())
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert archive.namelist() == ["Identification.tgt"]
    assert not list((root / "exports").glob("*.zip"))


def test_upload_larger_than_regular_form_limit_is_accepted(app):
    import io, zipfile

    payload = bytes(range(256)) * 64
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("Identification.tgt", b"device-one")
        archive.writestr("DATALOG/night.edf", payload)
    assert stream.tell() > app.config["MAX_CONTENT_LENGTH"]
    stream.seek(0)
    client = app.test_client()
    client.get("/", headers=auth())
    with client.session_transaction() as session:
        token = session["csrf"]
    response = client.post(
        "/import",
        headers=auth(),
        data={"csrf": token, "archive": (stream, "SD_card.zip")},
    )
    assert response.status_code == 200
    root = app.config["CONFIG_PATH"].parent / "data"
    assert (root / "work/archive/DATALOG/night.edf").read_bytes() == payload
    assert not app.config["TRANSFERS"]


def test_mac_connection_script_is_authenticated_and_executable(app):
    import io, zipfile, subprocess

    client = app.test_client()
    assert client.get("/connect-mac.zip").status_code == 401
    response = client.get(
        "/connect-mac.zip", headers=auth(), base_url="http://192.168.8.104:8080"
    )
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        info = archive.getinfo("Connect-CPAP.command")
        assert (info.external_attr >> 16) & 0o111 == 0o111
        script = archive.read(info).decode()
    assert "smb://cpap@192.168.8.104/CPAP" in script
    assert "8080" not in script
    assert "test-password" not in script
    assert (
        subprocess.run(
            ["/bin/bash", "-n"], input=script, text=True, capture_output=True
        ).returncode
        == 0
    )
    assert b"/connect-mac.zip" in client.get("/", headers=auth()).data


def test_mac_connection_script_quotes_host_and_supports_ipv6(app):
    import io, zipfile

    client = app.test_client()
    response = client.get(
        "/connect-mac.zip", headers=auth(), base_url="http://[::1]:8080"
    )
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert b"smb://cpap@[::1]/CPAP" in archive.read("Connect-CPAP.command")
    response = client.get(
        "/connect-mac.zip", headers=dict(auth(), Host="bad;host:8080")
    )
    assert response.status_code == 400


def test_explicit_smb_host_overrides_dashboard(app):
    import io, zipfile

    cfg = json.loads(app.config["CONFIG_PATH"].read_text())
    cfg["smb_host"] = "192.168.8.104"
    app.config["CONFIG_PATH"].write_text(json.dumps(cfg))
    client = app.test_client()
    response = client.get(
        "/connect-mac.zip", headers=auth(), base_url="https://proxy.example"
    )
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert b"smb://cpap@192.168.8.104/CPAP" in archive.read("Connect-CPAP.command")
    assert (
        b'href="smb://cpap@192.168.8.104/CPAP"' in client.get("/", headers=auth()).data
    )


@pytest.mark.parametrize(
    "host",
    ["https://host", "host:445", "user@host", "host/path", "bad host", "bad;host"],
)
def test_invalid_smb_host_is_rejected(app, host):
    import server

    cfg = json.loads(app.config["CONFIG_PATH"].read_text())
    cfg["smb_host"] = host
    app.config["CONFIG_PATH"].write_text(json.dumps(cfg))
    with pytest.raises(ValueError):
        server.load_config(app.config["CONFIG_PATH"])


@pytest.mark.parametrize(
    "host", ["fe80::1%foo bar", "fe80::1%foo?bar", "fe80::1%foo@bar", "fe80::1%eth0"]
)
def test_smb_scoped_ipv6_rejected(host):
    import server

    with pytest.raises(ValueError):
        server.validate_smb_host(host)


def test_enable_retention_requires_preview(app):
    import server

    root = app.config["CONFIG_PATH"].parent / "data"
    published = root / "published"
    snapshot = published / "20261016T000000Z-1234abcd"
    snapshot.mkdir(parents=True)
    (published / "current").symlink_to(snapshot.name)
    client = app.test_client()
    client.get("/", headers=auth())
    with client.session_transaction() as session:
        token = session["csrf"]
    settings = {
        "csrf": token,
        "time": "10:00",
        "timezone": "Australia/Melbourne",
        "retention_keep": "2",
        "retention_enabled": "on",
    }
    assert client.post("/settings", headers=auth(), data=settings).status_code == 400
    assert client.get("/api/storage/preview?keep=2", headers=auth()).status_code == 200
    assert client.post("/settings", headers=auth(), data=settings).status_code == 303


def test_check_connection_is_idle_only_and_rate_limited(app, monkeypatch):
    import server

    root = app.config["CONFIG_PATH"].parent / "data"
    client = app.test_client()
    client.get("/", headers=auth())
    with client.session_transaction() as session:
        token = session["csrf"]
    monkeypatch.setattr(webapp.diagnostics, "check_card", lambda _: {"reachable": True})
    with server.run_lock(root / "state"):
        assert (
            client.post(
                "/diagnostics/check", headers=auth(), data={"csrf": token}
            ).status_code
            == 409
        )
    assert (
        client.post(
            "/diagnostics/check", headers=auth(), data={"csrf": token}
        ).status_code
        == 303
    )
    assert (
        client.post(
            "/diagnostics/check", headers=auth(), data={"csrf": token}
        ).status_code
        == 429
    )


@pytest.mark.parametrize('password_free', [False, True])
def test_real_waitress_upload_releases_all_reservations(app, monkeypatch, password_free):
    if password_free:
        monkeypatch.setenv('WEB_AUTH_MODE', 'none')
        app = webapp.create_app(app.config['CONFIG_PATH'], start_scheduler=False)
    headers = {} if password_free else auth()
    import io, zipfile, threading, urllib.request, http.cookiejar, time, storage
    from waitress import create_server
    from upload_server import upload_channel

    root = app.config["CONFIG_PATH"].parent / "data"
    listener = create_server(
        app, host="127.0.0.1", port=0, max_request_body_size=1000000
    )
    listener.channel_class = upload_channel(
        root, app.config['UPLOAD_AUTH'], 1000000, 1024**3
    )

    def run():
        try:
            listener.run()
        except OSError:
            pass

    threading.Thread(target=run, daemon=True).start()
    base = "http://127.0.0.1:" + str(listener.effective_port)
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    try:
        with opener.open(urllib.request.Request(base, headers=headers)) as response:
            response.read()
        page = opener.open(urllib.request.Request(base, headers=headers)).read().decode()
        import re

        token = re.search('name="csrf" value="([^"]+)"', page).group(1)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("Identification.tgt", b"test-device")
            archive.writestr("DATALOG/night.edf", b"abcd" * 8192)
        body = (
            b'--boundary\r\nContent-Disposition: form-data; name="csrf"\r\n\r\n'
            + token.encode()
            + b'\r\n--boundary\r\nContent-Disposition: form-data; name="archive"; filename="card.zip"\r\nContent-Type: application/zip\r\n\r\n'
            + stream.getvalue()
            + b"\r\n--boundary--\r\n"
        )
        request = urllib.request.Request(
            base + "/import",
            data=body,
            headers=dict(
                auth(), **{"Content-Type": "multipart/form-data; boundary=boundary"}
            ),
        )
        with opener.open(request, timeout=5) as response:
            assert json.load(response)["imported"] == 2
        for _ in range(40):
            if storage.reserved_bytes(root) == 0:
                break
            time.sleep(0.025)
        assert storage.reserved_bytes(root) == 0
        assert (root / "work/archive/DATALOG/night.edf").stat().st_size == 32768
    finally:
        listener.close()


def test_password_free_dashboard_keeps_csrf_and_persistent_session(tmp_path, monkeypatch):
    path = tmp_path / 'server.json'
    path.write_text(json.dumps({'root': str(tmp_path / 'data'), 'url': 'http://card/dir?dir=A:'}))
    monkeypatch.setenv('WEB_AUTH_MODE', 'none')
    monkeypatch.setenv('WEB_PASSWORD_FILE', str(tmp_path / 'missing-password'))
    app = webapp.create_app(path, start_scheduler=False)
    client = app.test_client()
    assert client.get('/').status_code == 200
    assert app.config['UPLOAD_AUTH'] is None
    with client.session_transaction() as session:
        token = session['csrf']
    assert client.post('/settings', data={'time': '11:00'}).status_code == 403
    data = {'csrf': token, 'time': '11:00', 'timezone': 'Australia/Melbourne'}
    assert client.post('/settings', data=data, headers={'Origin': 'https://other.test'}).status_code == 403
    assert client.post('/settings', data=data).status_code == 303
    restarted = webapp.create_app(path, start_scheduler=False)
    assert restarted.secret_key == app.secret_key
    secret = path.parent / '.web-session-secret'
    assert secret.stat().st_mode & 0o777 == 0o600


def test_invalid_auth_mode_fails_closed(app, monkeypatch):
    monkeypatch.setenv('WEB_AUTH_MODE', 'offf')
    with pytest.raises(ValueError, match='WEB_AUTH_MODE'):
        webapp.create_app(app.config['CONFIG_PATH'], 'test-password-at-least-16', start_scheduler=False)
