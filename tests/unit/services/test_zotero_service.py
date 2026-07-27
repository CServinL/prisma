"""Unit tests for ZoteroService.status() -- particularly the new
web_api-mode "reachable" live check, added alongside prisma-desktop's
zotero_desktop_ping (2026-07-27): "available" keeps meaning "credentials
configured" (existing UI consumers gate on it), "reachable" is the new,
separate live network+auth check, mirroring the same short-timeout
reachable-or-not pattern already used for Ollama.
"""
from unittest.mock import MagicMock, patch

from prisma.services.zotero import ZoteroMode, ZoteroService, check_web_api_reachable


def test_check_web_api_reachable_false_when_credentials_missing():
    assert check_web_api_reachable(None, "12345") is False
    assert check_web_api_reachable("key", None) is False


def test_check_web_api_reachable_does_not_call_network_when_credentials_missing():
    with patch("urllib.request.urlopen") as mock_urlopen:
        check_web_api_reachable(None, None)
    mock_urlopen.assert_not_called()


def test_check_web_api_reachable_true_on_200():
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert check_web_api_reachable("key", "12345") is True


def test_check_web_api_reachable_false_on_exception():
    with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
        assert check_web_api_reachable("key", "12345") is False


def test_web_api_status_unreachable_when_not_configured():
    service = ZoteroService(mode=ZoteroMode.web_api, api_key=None, user_id=None)
    status = service.status()
    assert status == {"mode": ZoteroMode.web_api, "available": False, "reachable": False}


def test_web_api_status_does_not_attempt_network_call_when_not_configured():
    service = ZoteroService(mode=ZoteroMode.web_api, api_key=None, user_id=None)
    with patch("urllib.request.urlopen") as mock_urlopen:
        service.status()
    mock_urlopen.assert_not_called()


def test_web_api_status_reachable_when_key_check_succeeds():
    service = ZoteroService(mode=ZoteroMode.web_api, api_key="testkey", user_id="12345")
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_resp):
        status = service.status()
    assert status == {"mode": ZoteroMode.web_api, "available": True, "reachable": True}


def test_web_api_status_unreachable_when_key_check_fails():
    service = ZoteroService(mode=ZoteroMode.web_api, api_key="testkey", user_id="12345")
    with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
        status = service.status()
    assert status == {"mode": ZoteroMode.web_api, "available": True, "reachable": False}


def test_web_api_status_unreachable_on_non_200_response():
    service = ZoteroService(mode=ZoteroMode.web_api, api_key="testkey", user_id="12345")
    mock_resp = MagicMock()
    mock_resp.status = 403
    mock_resp.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_resp):
        status = service.status()
    assert status["reachable"] is False


def test_offline_status_unaffected_by_reachable_field():
    # Confirms the offline branch's shape is untouched by this change.
    service = ZoteroService(mode=ZoteroMode.offline, db_path=None)
    status = service.status()
    assert "reachable" not in status
