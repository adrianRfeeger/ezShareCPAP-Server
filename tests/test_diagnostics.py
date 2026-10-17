from datetime import datetime, timezone, timedelta
import json
import diagnostics


def test_optional_stale_and_malformed_wifi(tmp_path):
    path = tmp_path / "wifi.json"
    now = datetime.now(timezone.utc)
    assert diagnostics.read_wifi_status(path, now)["available"] is False
    path.write_text(
        json.dumps(
            {
                "sampled_at": (now - timedelta(seconds=61)).isoformat(),
                "signal_dbm": -48,
                "connected": True,
            }
        )
    )
    assert diagnostics.read_wifi_status(path, now)["stale"] is True
    path.write_text("bad")
    assert diagnostics.read_wifi_status(path, now)["available"] is False


def test_wifi_parser_no_secrets():
    from scripts.collect_wifi_status import parse_link

    value = parse_link(
        "Connected to 00:00:00:00:00:00\n\tSSID: secret-name\n\tsignal: -49 dBm\n\trx bitrate: 52.0 MBit/s\n\ttx bitrate: 72.2 MBit/s\n",
        "Power save: off",
    )
    assert (
        value["connected"] and value["signal_dbm"] == -49 and value["tx_mbps"] == 72.2
    )
    assert "secret-name" not in json.dumps(value)
    assert parse_link("Not connected.", "")["connected"] is False


def test_transfer_resets_between_runs():
    tracker = diagnostics.TransferRate()
    tracker.observe("one", "file", 100, 10)
    result = tracker.observe("one", "file", 200, 20)
    assert result["bytes_per_second"] == 10
    assert tracker.observe("two", "file", 10, 21)["bytes_per_second"] is None
