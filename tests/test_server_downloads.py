import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import pytest
from ezshare import ezShare
from file_ops import download_file, list_dir
from test_connect_sync import FakeSession
from test_file_ops import FakeResponse, ezshare_for


def test_existing_network_download_never_controls_wifi():
    app = ezShare()
    app.network_mode = 'existing'
    app.connection_manager = Mock()
    with tempfile.TemporaryDirectory() as directory:
        app.set_params(directory, 'http://card/dir?dir=A:', None, False, False,
                       False, False, None, None, [], 1, 0, False)
        with patch('ezshare.requests.Session', return_value=FakeSession()):
            assert app.run()
        assert (Path(directory) / 'STR.EDF').read_bytes() == b'edf-data'
    app.connection_manager.connect.assert_not_called()
    app.connection_manager.disconnect.assert_not_called()


def test_missing_length_streams_body(tmp_path):
    response = FakeResponse([b'data'])
    response.headers = {}
    target = tmp_path / 'file'
    assert download_file(ezshare_for(response), 'http://card/download', target)
    assert target.read_bytes() == b'data'


def test_truncated_download_preserves_old_file(tmp_path):
    response = FakeResponse([b'bad'])
    response.headers = {'content-length': '20'}
    target = tmp_path / 'file'
    target.write_bytes(b'old')
    assert not download_file(ezshare_for(response), 'http://card/download', target)
    assert target.read_bytes() == b'old'
    assert list(tmp_path.iterdir()) == [target]


def test_invalid_listing_is_failure():
    response = Mock(text='<html>Not a card listing</html>')
    app = ezShare()
    app.session = Mock()
    app.session.get.return_value = response
    assert list_dir(app, 'http://card/dir') == (None, None)


def test_unsafe_remote_name_is_failure():
    response = Mock(text='<pre>2026-01-01 10:00:00 <a href="/download?x">../escape</a></pre>')
    app = ezShare()
    app.session = Mock()
    app.session.get.return_value = response
    assert list_dir(app, 'http://card/dir') == (None, None)


def test_remote_directory_cycle_fails_without_recursion(tmp_path):
    app = ezShare()
    app.network_mode = 'existing'
    app.set_params(str(tmp_path), 'http://card/dir?dir=A:', None, False, False,
                   False, False, None, None, [], 1, 0, False)
    session = Mock()
    session.get.return_value = Mock(text='<pre>2026-01-01 10:00:00 <a href="/dir?dir=A:">loop</a></pre>')
    with patch('ezshare.requests.Session', return_value=session):
        assert app.run() is False
    assert session.get.call_count < 5


def test_foreign_download_url_rejected():
    app = ezShare()
    app.session = Mock()
    app.session.get.return_value = Mock(text='<pre>2026-01-01 10:00:00 <a href="http://other/download?x">file</a></pre>')
    assert list_dir(app, 'http://card/dir') == (None, None)


def test_changed_card_is_not_reported_as_success(tmp_path):
    class ChangingSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.listings = 0
        def get(self, url, **kwargs):
            response = super().get(url, **kwargs)
            if 'download?' not in url:
                self.listings += 1
                if self.listings > 3:
                    response.text = response.text.replace('10:00:00', '11:00:00')
            return response
    app = ezShare()
    app.network_mode = 'existing'
    app.set_params(str(tmp_path), 'http://card/dir?dir=A:', None, False, False,
                   False, False, None, None, [], 1, 0, False)
    with patch('ezshare.requests.Session', return_value=ChangingSession()):
        assert app.run() is False


def test_pre_error_page_is_not_empty_card():
    app = ezShare()
    app.session = Mock()
    app.session.get.return_value = Mock(text='<pre>Service temporarily unavailable</pre>')
    assert list_dir(app, 'http://card/dir') == (None, None)


def test_listing_size_change_requires_download(tmp_path):
    from file_ops import should_download
    target = tmp_path / 'file'
    target.write_bytes(b'old')
    app = ezShare()
    app.overwrite = False
    app.keep_old = False
    assert should_download(app, target, 0, remote_size=6)


def test_over_one_hundred_sibling_directories_are_supported(tmp_path):
    app = ezShare()
    app.path = tmp_path
    app.overwrite = False
    app.keep_old = False
    dirs = [(str(index), f'/dir?dir=A:/{index}') for index in range(150)]
    with patch('ezshare.list_dir', return_value=([], [])):
        assert app.calculate_total_files_from_listing([], dirs, 'http://card/dir', tmp_path, False) == 0
