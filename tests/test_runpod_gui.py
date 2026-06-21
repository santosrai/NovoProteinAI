"""Tests for the RunPod interactive-GUI client (src/runpod_gui.py).

Mocks the RunPod REST API so we can assert launch_gui parses {url, job_id} from
a streamed chunk and close_gui posts to /cancel — no network required.
"""

from unittest.mock import Mock, patch

import pytest

from src import runpod_gui


@pytest.fixture
def runpod_env(monkeypatch):
    monkeypatch.setenv("RUNPOD_API_KEY", "test-key")
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "ep123")
    monkeypatch.setenv("RUNPOD_GUI_POLL_TIMEOUT", "5")


def _resp(json_data, status=200):
    r = Mock()
    r.json.return_value = json_data
    r.raise_for_status.return_value = None
    r.status_code = status
    return r


def test_is_enabled(monkeypatch):
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    monkeypatch.delenv("RUNPOD_ENDPOINT_ID", raising=False)
    assert runpod_gui.is_enabled() is False
    monkeypatch.setenv("RUNPOD_API_KEY", "k")
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "e")
    assert runpod_gui.is_enabled() is True


def test_launch_gui_not_configured(monkeypatch):
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    monkeypatch.delenv("RUNPOD_ENDPOINT_ID", raising=False)
    res = runpod_gui.launch_gui("1crn")
    assert res["ok"] is False
    assert res["job_id"] is None


def test_launch_gui_streams_url(runpod_env):
    url = "https://abc-8080.proxy.runpod.net/vnc.html?password=xyz"
    run_resp = _resp({"id": "job-1"})
    stream_resp = _resp({
        "status": "IN_PROGRESS",
        "stream": [{"output": {"interactive_link": url}}],
    })

    with patch.object(runpod_gui.requests, "post", return_value=run_resp) as mock_post, \
         patch.object(runpod_gui.requests, "get", return_value=stream_resp):
        res = runpod_gui.launch_gui("1crn", chain="A", epitope="12+15")

    assert res["ok"] is True
    assert res["url"] == url
    assert res["job_id"] == "job-1"
    # the /run POST should carry the input payload
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["input"]["pdb_id"] == "1crn"
    assert kwargs["json"]["input"]["chain"] == "A"
    assert kwargs["json"]["input"]["epitope"] == "12+15"


def test_launch_gui_job_failed(runpod_env):
    run_resp = _resp({"id": "job-2"})
    stream_resp = _resp({"status": "FAILED", "stream": []})
    with patch.object(runpod_gui.requests, "post", return_value=run_resp), \
         patch.object(runpod_gui.requests, "get", return_value=stream_resp):
        res = runpod_gui.launch_gui("1crn")
    assert res["ok"] is False
    assert res["job_id"] == "job-2"


def test_close_gui_posts_cancel(runpod_env):
    cancel_resp = _resp({"status": "CANCELLED"})
    with patch.object(runpod_gui.requests, "post", return_value=cancel_resp) as mock_post:
        res = runpod_gui.close_gui("job-9")
    assert res["ok"] is True
    url = mock_post.call_args[0][0]
    assert url.endswith("/cancel/job-9")


def test_close_gui_no_job():
    res = runpod_gui.close_gui("")
    assert res["ok"] is False
