"""Credential-free, read-only probe of package-registry public metadata endpoints (rec-3941).

Reports claimed / unclaimed / unreachable per registry for a distribution name on PyPI, npm and
crates.io. Deliberately NOT wired into scripts/validate.py's check registry (VP step 7 of
PLAN-ontheloop-package-registries asserts this negatively) -- it makes live network calls, which
would make the presubmit tiers non-hermetic and flaky. Operator-invoked only, per the procedure in
docs/contracts/package-registry-reservation.yaml.

The three outcomes are distinct states, never a bool: an unreachable registry (proxy block,
timeout, malformed body) must never be reported as unclaimed -- that is the dangerous direction to
be wrong in, since it would read a network failure as evidence a name is free.

Usage:
    bin/venv-python -m scripts.package_registry_probe ontheloop
    bin/venv-python -m scripts.package_registry_probe --require-claimed ontheloop
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

_CONTACT_ENV_VAR = "PACKAGE_REGISTRY_PROBE_CONTACT"
_DEFAULT_CONTACT = "contact pending -- see docs/contracts/package-registry-reservation.yaml"
_TIMEOUT_SECONDS = 10.0

_REGISTRY_URL_TEMPLATES: dict[str, str] = {
    "pypi": "https://pypi.org/pypi/{name}/json",
    "npm": "https://registry.npmjs.org/{name}",
    "crates.io": "https://crates.io/api/v1/crates/{name}",
}


class RegistryStatus(str, Enum):
    """Three mutually-exclusive outcomes. UNREACHABLE must never collapse into UNCLAIMED."""

    CLAIMED = "claimed"
    UNCLAIMED = "unclaimed"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class RegistryResult:
    registry: str
    status: RegistryStatus
    detail: str


def resolve_contact(env: Mapping[str, str] | None = None) -> str:
    """Config-sourced contact string for the descriptive User-Agent. `env` defaults to the real
    process environment; a test passes a fake mapping instead. Never a hardcoded real address --
    the fallback is a neutral placeholder naming where the settled contact will be recorded."""
    active_env = env if env is not None else os.environ
    return active_env.get(_CONTACT_ENV_VAR) or _DEFAULT_CONTACT


def build_user_agent(contact: str) -> str:
    """crates.io's crawler policy requires a descriptive User-Agent naming a contact; PyPI and
    npm accept the same header harmlessly."""
    return f"theseus-package-registry-probe/1.0 ({contact})"


def _fetch(url: str, user_agent: str, timeout: float) -> tuple[int | None, bytes | None, str]:
    """Returns (http_status, body, error_detail). A successful fetch (2xx or an HTTPError status
    like 404/403) carries a non-None status and empty error_detail. A connection-level failure
    (timeout, DNS, refused, ...) carries status=None, body=None and a non-empty error_detail."""
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed https registry hosts)
            return response.status, response.read(), ""
    except urllib.error.HTTPError as exc:
        # HTTPError carries a real response (status + body) for non-2xx statuses -- route it
        # through the same status-based classification as a success, not the network-failure arm.
        return exc.code, exc.read(), ""
    except (urllib.error.URLError, OSError) as exc:
        return None, None, type(exc).__name__


def _classify(status: int | None, body: bytes | None, error_detail: str) -> tuple[RegistryStatus, str]:
    if status is None:
        return RegistryStatus.UNREACHABLE, error_detail or "network error"
    if status == 404:
        return RegistryStatus.UNCLAIMED, "http 404"
    if status == 200:
        if not body:
            return RegistryStatus.UNREACHABLE, "http 200 with an empty body"
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return RegistryStatus.UNREACHABLE, "http 200 with a malformed (non-JSON) body"
        if not isinstance(parsed, dict):
            return RegistryStatus.UNREACHABLE, "http 200 with a non-object JSON body"
        return RegistryStatus.CLAIMED, "http 200"
    return RegistryStatus.UNREACHABLE, f"http {status}"


def probe_registry(registry: str, name: str, user_agent: str, timeout: float = _TIMEOUT_SECONDS) -> RegistryResult:
    url = _REGISTRY_URL_TEMPLATES[registry].format(name=name)
    status, body, error_detail = _fetch(url, user_agent, timeout)
    outcome, detail = _classify(status, body, error_detail)
    return RegistryResult(registry=registry, status=outcome, detail=detail)


def probe_all(name: str, user_agent: str, timeout: float = _TIMEOUT_SECONDS) -> list[RegistryResult]:
    return [probe_registry(registry, name, user_agent, timeout=timeout) for registry in _REGISTRY_URL_TEMPLATES]


def _format_report(name: str, results: list[RegistryResult]) -> str:
    lines = [f"Package-registry probe for '{name}':"]
    lines.extend(f"  {r.registry}: {r.status.value} ({r.detail})" for r in results)
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Credential-free, read-only package-registry namespace probe.")
    parser.add_argument("name", help="Distribution/package/crate name to probe (e.g. ontheloop).")
    parser.add_argument(
        "--require-claimed",
        action="store_true",
        help="Exit non-zero unless every registry reports claimed.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    user_agent = build_user_agent(resolve_contact())
    results = probe_all(args.name, user_agent)
    print(_format_report(args.name, results))
    if args.require_claimed and any(r.status is not RegistryStatus.CLAIMED for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
