"""CD.40 scrubber rules."""

from __future__ import annotations

import hashlib
import json

import pytest

from src.turn_capture.scrub import CLASS_ORDER, scrub_text
from tests.fixtures.turn_capture_corpus import build_secret

PLAIN = {
    "AWS_ACCESS_KEY_ID": "aws_access",
    "ANTHROPIC_API_KEY": "anthropic",  # pragma: allowlist secret
    "GITHUB_TOKEN": "github",
}


def test_every_credential_class_is_redacted() -> None:
    for cls, kind in PLAIN.items():
        secret = build_secret(kind)
        result = scrub_text(f"before {secret} after")
        assert result.text == f"before [REDACTED:{cls}] after"
        assert result.counts == {cls: 1}
    pat = build_secret("github_pat")
    assert scrub_text(f"x {pat} y").text == "x [REDACTED:GITHUB_TOKEN] y"
    for prefix in ("ASIA", "AIDA", "AROA", "AGPA", "ANPA", "ANVA", "ASCA", "APKA"):
        assert scrub_text(prefix + "ABCDEFGHIJKLMNOP").counts == {"AWS_ACCESS_KEY_ID": 1}
    bearer = scrub_text(f"Authorization: {build_secret('bearer')}")
    assert bearer.text == "Authorization: Bearer [REDACTED:BEARER_TOKEN]"
    secret = scrub_text(f"aws_secret_access_key = {build_secret('aws_secret')}")
    assert secret.text == "aws_secret_access_key = [REDACTED:AWS_SECRET_ACCESS_KEY]"
    session = scrub_text(f"aws_session_token: {build_secret('aws_session')}")
    assert session.text == "aws_session_token: [REDACTED:AWS_SESSION_TOKEN]"


def test_scrub_is_idempotent() -> None:
    text = " ".join(build_secret(k) for k in ("aws_access", "anthropic", "github", "bearer"))
    text += f" SecretAccessKey={build_secret('aws_secret')}"
    once = scrub_text(text)
    twice = scrub_text(once.text)
    assert twice.text == once.text
    assert twice.counts == {}
    assert scrub_text(text) == once


def test_negative_corpus_untouched() -> None:
    corpus = [
        "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
        hashlib.sha256(b"digest").hexdigest(),
        "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "AKIA" + "SHORT",
        "akia" + "abcdefghijklmnop",
        "sk-ant-short",
        "ghp_short",
        "Bearer shorttoken",
        "Bearer " + "a" * 25,
        "toolu_01RWuAU836aYWLLFJRiRh8UF",
        "the aws_secret_access_key setting",
        "arn:aws:iam::role/example",
    ]
    for text in corpus:
        result = scrub_text(text)
        assert result.text == text
        assert result.counts == {}


def test_aws_json_and_export_shapes_redacted() -> None:
    secret, session = build_secret("aws_secret"), build_secret("aws_session")
    as_json = json.dumps({"SecretAccessKey": secret, "SessionToken": session})
    result = scrub_text(as_json)
    assert secret not in result.text and session not in result.text
    assert result.counts == {"AWS_SECRET_ACCESS_KEY": 1, "AWS_SESSION_TOKEN": 1}
    escaped = json.dumps(as_json)
    assert secret not in scrub_text(escaped).text
    exported = f"export AWS_SECRET_ACCESS_KEY={secret}\nexport AWS_SESSION_TOKEN={session}\n"
    multi = scrub_text(exported)
    assert (
        multi.text == "export AWS_SECRET_ACCESS_KEY=[REDACTED:AWS_SECRET_ACCESS_KEY]\n"
        "export AWS_SESSION_TOKEN=[REDACTED:AWS_SESSION_TOKEN]\n"
    )


def test_bearer_boundaries_and_counts_never_content() -> None:
    assert scrub_text("Bearer " + "a" * 40).counts == {"BEARER_TOKEN": 1}
    assert scrub_text("Bearer abcdefghij0123456789").counts == {"BEARER_TOKEN": 1}
    assert set(scrub_text("Bearer " + "a" * 25).counts) == set()
    result = scrub_text(build_secret("anthropic"))
    assert all(isinstance(k, str) and isinstance(v, int) for k, v in result.counts.items())
    assert set(CLASS_ORDER) >= set(result.counts)


def test_never_raises_on_any_str() -> None:
    assert scrub_text("").text == ""
    assert scrub_text("\ud800 lone surrogate").counts == {}
    assert scrub_text("x" * 100_000).counts == {}


@pytest.mark.parametrize("cls", CLASS_ORDER)
def test_class_order_is_closed(cls: str) -> None:
    assert cls.isupper()
