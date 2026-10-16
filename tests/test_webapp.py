import base64
import json
import pytest
import webapp


@pytest.fixture
def app(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'root': str(tmp_path / 'data'), 'url': 'http://card/dir?dir=A:'}))
    return webapp.create_app(path, 'test-password-at-least-16', start_scheduler=False)


def auth():
    return {'Authorization': 'Basic ' + base64.b64encode(b'admin:test-password-at-least-16').decode()}


def test_status_requires_login(app):
    client = app.test_client()
    assert client.get('/').status_code == 401
    assert client.get('/', headers=auth()).status_code == 200


def test_settings_need_csrf_and_validate_timezone(app):
    client = app.test_client()
    assert client.post('/settings', headers=auth(), data={'time': '11:00'}).status_code == 403
    client.get('/', headers=auth())
    with client.session_transaction() as session:
        token = session['csrf']
    assert client.post('/settings', headers=auth(), data={'csrf': token, 'time': '99:00', 'timezone': 'bad'}).status_code == 400
    response = client.post('/settings', headers=auth(), data={'csrf': token, 'time': '11:00', 'timezone': 'Australia/Melbourne', 'run_on_startup': 'on'})
    assert response.status_code == 303
    assert json.loads(app.config['CONFIG_PATH'].read_text())['time'] == '11:00'


def test_cross_origin_post_is_rejected(app):
    client = app.test_client()
    client.get('/', headers=auth())
    with client.session_transaction() as session:
        token = session['csrf']
    assert client.post('/sync', headers=dict(auth(), Origin='https://attacker.test'), data={'csrf': token}).status_code == 403


def test_first_post_cannot_use_predictable_missing_token(app):
    client = app.test_client()
    assert client.post('/settings', headers=auth(), data={
        'csrf': 'missing', 'time': '11:00', 'timezone': 'Australia/Melbourne'}).status_code == 403


def test_live_status_api_requires_authentication(app):
    client = app.test_client()
    assert client.get('/api/status').status_code == 401
    response = client.get('/api/status', headers=auth())
    assert response.status_code == 200
    assert response.json['progress']['percent'] is None
    assert response.headers['Cache-Control'] == 'no-store'


def test_page_serves_illustration_and_eta_module(app):
    client = app.test_client()
    page = client.get('/', headers=auth()).text
    assert '/static/cpap-artwork.png' in page
    assert 'id="download-eta"' in page
    assert 'type="module" src="/static/progress.js"' in page
    module = client.get('/static/eta.mjs', headers=auth())
    assert module.status_code == 200
    assert 'javascript' in module.content_type
    image = client.get('/static/cpap-artwork.png', headers=auth())
    assert image.status_code == 200 and image.data.startswith(b'\x89PNG\r\n\x1a\n')
