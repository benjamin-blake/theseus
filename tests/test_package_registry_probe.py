from __future__ import annotations

import io
import urllib.error
from unittest.mock import MagicMock, patch

from scripts import package_registry_probe as probe


def _response(status: int, body: bytes) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def _http_error(code: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="https://example.invalid/x", code=code, msg="err", hdrs=None, fp=io.BytesIO(body))


# --- _classify: the three-state outcome vocabulary ---------------------------------------------


def test_classify_200_with_valid_json_is_claimed() -> None:
    assert probe._classify(200, b'{"name": "ontheloop"}', "") == (probe.RegistryStatus.CLAIMED, "http 200")


def test_classify_404_is_unclaimed() -> None:
    assert probe._classify(404, b'{"error": "Not found"}', "") == (probe.RegistryStatus.UNCLAIMED, "http 404")


def test_classify_403_is_unreachable() -> None:
    status, detail = probe._classify(403, b"", "")
    assert status is probe.RegistryStatus.UNREACHABLE
    assert "403" in detail


def test_classify_other_status_is_unreachable() -> None:
    status, detail = probe._classify(500, b"", "")
    assert status is probe.RegistryStatus.UNREACHABLE
    assert "500" in detail


def test_classify_network_error_is_unreachable() -> None:
    assert probe._classify(None, None, "TimeoutError") == (probe.RegistryStatus.UNREACHABLE, "TimeoutError")


def test_classify_network_error_with_no_detail_still_unreachable() -> None:
    status, detail = probe._classify(None, None, "")
    assert status is probe.RegistryStatus.UNREACHABLE
    assert detail


def test_classify_malformed_body_on_200_is_unreachable_not_unclaimed() -> None:
    status, detail = probe._classify(200, b"<html>not json</html>", "")
    assert status is probe.RegistryStatus.UNREACHABLE
    assert "malformed" in detail


def test_classify_empty_body_on_200_is_unreachable() -> None:
    status, detail = probe._classify(200, b"", "")
    assert status is probe.RegistryStatus.UNREACHABLE
    assert "empty" in detail


def test_classify_non_object_json_on_200_is_unreachable() -> None:
    status, detail = probe._classify(200, b"[1, 2, 3]", "")
    assert status is probe.RegistryStatus.UNREACHABLE
    assert "non-object" in detail


# --- _fetch: urllib plumbing ---------------------------------------------------------------------


def test_fetch_success_returns_status_and_body() -> None:
    with patch("scripts.package_registry_probe.urllib.request.urlopen", return_value=_response(200, b'{"a": 1}')):
        status, body, detail = probe._fetch("https://example.invalid/x", "ua/1", 5.0)
    assert (status, body, detail) == (200, b'{"a": 1}', "")


def test_fetch_http_error_returns_code_and_body() -> None:
    with patch("scripts.package_registry_probe.urllib.request.urlopen", side_effect=_http_error(404, b'{"error": "x"}')):
        status, body, detail = probe._fetch("https://example.invalid/x", "ua/1", 5.0)
    assert (status, body, detail) == (404, b'{"error": "x"}', "")


def test_fetch_connection_error_returns_none_status() -> None:
    with patch(
        "scripts.package_registry_probe.urllib.request.urlopen",
        side_effect=urllib.error.URLError("no route to host"),
    ):
        status, body, detail = probe._fetch("https://example.invalid/x", "ua/1", 5.0)
    assert status is None
    assert body is None
    assert detail == "URLError"


def test_fetch_timeout_returns_none_status() -> None:
    with patch("scripts.package_registry_probe.urllib.request.urlopen", side_effect=TimeoutError("timed out")):
        status, body, detail = probe._fetch("https://example.invalid/x", "ua/1", 5.0)
    assert status is None
    assert detail == "TimeoutError"


# --- probe_registry / probe_all -------------------------------------------------------------------


def test_probe_registry_sends_url_and_user_agent() -> None:
    with patch(
        "scripts.package_registry_probe.urllib.request.urlopen", return_value=_response(200, b'{"name":"x"}')
    ) as mocked:
        result = probe.probe_registry("pypi", "ontheloop", "my-ua/1", timeout=5.0)
    assert result == probe.RegistryResult("pypi", probe.RegistryStatus.CLAIMED, "http 200")
    sent_request = mocked.call_args[0][0]
    assert sent_request.full_url == "https://pypi.org/pypi/ontheloop/json"
    assert sent_request.get_header("User-agent") == "my-ua/1"


def test_probe_all_covers_every_registry_in_order() -> None:
    with patch(
        "scripts.package_registry_probe.urllib.request.urlopen",
        side_effect=[_response(200, b'{"name":"x"}'), _http_error(404), _http_error(403)],
    ):
        results = probe.probe_all("ontheloop", "ua/1", timeout=5.0)
    assert [r.registry for r in results] == ["pypi", "npm", "crates.io"]
    assert [r.status for r in results] == [
        probe.RegistryStatus.CLAIMED,
        probe.RegistryStatus.UNCLAIMED,
        probe.RegistryStatus.UNREACHABLE,
    ]


def test_unreachable_is_not_reported_as_unclaimed() -> None:
    """VP step 5 / AC4 -- the plan's primary graduated invariant (probe-unreachable-not-unclaimed).

    A proxy 403, a timeout and a malformed body must never be reported as unclaimed: that is the
    dangerous direction to be wrong in, since it would read a network failure as evidence that a
    name is free.
    """
    with patch(
        "scripts.package_registry_probe.urllib.request.urlopen",
        side_effect=[_http_error(403), TimeoutError("timed out"), _response(200, b"not json")],
    ):
        results = probe.probe_all("ontheloop", "ua/1", timeout=5.0)
    assert all(r.status is probe.RegistryStatus.UNREACHABLE for r in results)
    assert not any(r.status is probe.RegistryStatus.UNCLAIMED for r in results)


# --- config-sourced contact / User-Agent ----------------------------------------------------------


def test_resolve_contact_uses_mapping_when_provided() -> None:
    assert probe.resolve_contact({"PACKAGE_REGISTRY_PROBE_CONTACT": "ops@example.com"}) == "ops@example.com"
    assert probe.resolve_contact({}) == probe._DEFAULT_CONTACT


def test_resolve_contact_defaults_to_process_environment(monkeypatch) -> None:
    monkeypatch.delenv("PACKAGE_REGISTRY_PROBE_CONTACT", raising=False)
    assert probe.resolve_contact() == probe._DEFAULT_CONTACT
    monkeypatch.setenv("PACKAGE_REGISTRY_PROBE_CONTACT", "env-value@example.com")
    assert probe.resolve_contact() == "env-value@example.com"


def test_default_contact_is_a_neutral_placeholder_not_a_real_address() -> None:
    assert "package-registry-reservation.yaml" in probe._DEFAULT_CONTACT
    assert "@" not in probe._DEFAULT_CONTACT


def test_user_agent_contact_comes_from_config() -> None:
    """AC5 / VP step 6 named test. The crates.io User-Agent contact is sourced from configuration
    (an env var), never hardcoded -- overriding the config value changes the built User-Agent."""
    ua_default = probe.build_user_agent(probe.resolve_contact({}))
    ua_configured = probe.build_user_agent(probe.resolve_contact({"PACKAGE_REGISTRY_PROBE_CONTACT": "ops@otl-labs.example"}))
    assert "ops@otl-labs.example" in ua_configured
    assert "ops@otl-labs.example" not in ua_default
    assert ua_default != ua_configured


# --- report formatting and the CLI entry point ------------------------------------------------------


def test_format_report_lists_every_registry_and_status() -> None:
    results = [
        probe.RegistryResult("pypi", probe.RegistryStatus.CLAIMED, "http 200"),
        probe.RegistryResult("npm", probe.RegistryStatus.UNCLAIMED, "http 404"),
        probe.RegistryResult("crates.io", probe.RegistryStatus.UNREACHABLE, "http 403"),
    ]
    report = probe._format_report("ontheloop", results)
    assert "ontheloop" in report
    assert "pypi: claimed (http 200)" in report
    assert "npm: unclaimed (http 404)" in report
    assert "crates.io: unreachable (http 403)" in report


def test_main_exits_zero_without_require_claimed_even_if_unclaimed(capsys) -> None:
    with patch(
        "scripts.package_registry_probe.probe_all",
        return_value=[probe.RegistryResult("pypi", probe.RegistryStatus.UNCLAIMED, "http 404")],
    ):
        exit_code = probe.main(["ontheloop"])
    assert exit_code == 0
    assert "pypi: unclaimed" in capsys.readouterr().out


def test_main_require_claimed_exits_nonzero_unless_all_claimed() -> None:
    with patch(
        "scripts.package_registry_probe.probe_all",
        return_value=[
            probe.RegistryResult("pypi", probe.RegistryStatus.CLAIMED, "http 200"),
            probe.RegistryResult("npm", probe.RegistryStatus.UNCLAIMED, "http 404"),
        ],
    ):
        assert probe.main(["ontheloop", "--require-claimed"]) == 1


def test_main_require_claimed_exits_zero_when_all_claimed() -> None:
    with patch(
        "scripts.package_registry_probe.probe_all",
        return_value=[
            probe.RegistryResult("pypi", probe.RegistryStatus.CLAIMED, "http 200"),
            probe.RegistryResult("npm", probe.RegistryStatus.CLAIMED, "http 200"),
        ],
    ):
        assert probe.main(["ontheloop", "--require-claimed"]) == 0
