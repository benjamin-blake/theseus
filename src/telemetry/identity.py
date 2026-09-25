"""Telemetry envelope identity spec (Decision 199), normative: docs/contracts/telemetry-event-envelope.yaml.

Stdlib only (AGENTS.md plane-neutral rule; Decision 184 cl.2): ULID assembly and canonical ULID
parsing are implemented here as a 26-char Crockford base32 encoder/decoder over 16 raw bytes,
because pr-validate's fast tier installs neither python-ulid nor duckdb (requirements-fast.txt)
and the graduated VP rows (steps 1-3) must pass there.

H = sha256 over 4-byte big-endian length-prefixed NFC UTF-8 encodings of [domain tag, tenant_id,
project_id, ref]. An entity/FK key = ULID(48-bit ROOT session_started_at ms + the first 80 bits
(bytes 0-9) of H). event_id = ULID(48-bit event_timestamp ms + the first 80 bits of H computed
over external_ref with domain tag '<table>:event'). A foreign key is computed using the PARENT's
own domain tag over the same ref the parent used -- KEY_PLANS below is the single source of which
ref feeds which key column, per table.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.telemetry.timestamps import TimestampError, epoch_ms, truncate_to_ms

_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # pragma: allowlist secret
_CROCKFORD_INDEX = {ch: i for i, ch in enumerate(_CROCKFORD_ALPHABET)}
_REJECTED_ULID_CHARS = frozenset("ILOUilou")
_MAX_REF_BYTES = 4096
_ULID_LENGTH = 26

# Closed domain-tag registry (telemetry-event-envelope.yaml governance_notes): the four entity
# tags (one per table's own primary/entity key) plus the four '<table>:event' row-identity tags.
DOMAIN_TAGS: frozenset[str] = frozenset(
    {
        "telemetry_sessions:session_id",
        "telemetry_observations:observation_id",
        "telemetry_transcripts:transcript_id",
        "telemetry_agents:agent_run_id",
        "telemetry_sessions:event",
        "telemetry_observations:event",
        "telemetry_transcripts:event",
        "telemetry_agents:event",
    }
)


class IdentityError(ValueError):
    """Raised on any rejected identity input across this module."""


def canonical_ulid(value: str) -> str:
    """Upper-case *value* and validate it as a strict 26-char Crockford ULID.

    Rejects: non-str, wrong length, any of I/L/O/U (case-insensitive), and a first character
    that would overflow the 128-bit ULID value space (must decode to <= 7).
    """
    if not isinstance(value, str):
        raise IdentityError(f"expected str ULID, got {type(value).__name__}")
    upper = value.upper()
    if len(upper) != _ULID_LENGTH:
        raise IdentityError(f"ULID must be {_ULID_LENGTH} chars, got {len(upper)}: {value!r}")
    for ch in upper:
        if ch in _REJECTED_ULID_CHARS:
            raise IdentityError(f"ULID contains a rejected Crockford character {ch!r}: {value!r}")
        if ch not in _CROCKFORD_INDEX:
            raise IdentityError(f"ULID contains a non-Crockford-base32 character {ch!r}: {value!r}")
    if _CROCKFORD_INDEX[upper[0]] > 7:
        raise IdentityError(f"ULID first character overflows the 128-bit value space: {value!r}")
    return upper


def canonical_ref(ref: str) -> str:
    """NFC-normalise *ref* and validate it. Never trims or case-folds.

    Rejects: non-str, empty (post-normalisation), any Unicode Cc/Cs (control/surrogate) code
    point, and a normalised UTF-8 encoding longer than 4096 bytes.
    """
    if not isinstance(ref, str):
        raise IdentityError(f"expected str ref, got {type(ref).__name__}")
    normalized = unicodedata.normalize("NFC", ref)
    if normalized == "":
        raise IdentityError("ref must not be empty")
    for ch in normalized:
        category = unicodedata.category(ch)
        if category in ("Cc", "Cs"):
            raise IdentityError(f"ref contains a rejected Unicode category {category} code point: {ch!r}")
    encoded_len = len(normalized.encode("utf-8"))
    if encoded_len > _MAX_REF_BYTES:
        raise IdentityError(f"ref exceeds {_MAX_REF_BYTES} UTF-8 bytes (got {encoded_len})")
    return normalized


def _length_prefixed(value: str) -> bytes:
    encoded = unicodedata.normalize("NFC", value).encode("utf-8")
    return len(encoded).to_bytes(4, "big") + encoded


def identity_hash(domain_tag: str, tenant_id: str, project_id: str, ref: str) -> bytes:
    """H = sha256 over 4-byte big-endian length-prefixed NFC UTF-8 [tag, tenant_id, project_id, ref]."""
    if domain_tag not in DOMAIN_TAGS:
        raise IdentityError(f"unknown domain tag (not in the closed DOMAIN_TAGS registry): {domain_tag!r}")
    canon_tenant = canonical_ulid(tenant_id)
    canon_project = canonical_ulid(project_id)
    canon_ref = canonical_ref(ref)
    buf = b"".join(_length_prefixed(part) for part in (domain_tag, canon_tenant, canon_project, canon_ref))
    return hashlib.sha256(buf).digest()


def _time_ms_from_basis(time_basis: datetime) -> int:
    """Normalise a tz-aware *time_basis* to UTC, truncate to ms, and return exact epoch ms.

    Rejects (IdentityError): a non-datetime, a naive datetime, a pre-epoch instant, or one
    beyond the 48-bit ULID time-prefix range. A non-UTC offset is NORMALISED, not rejected.
    """
    if not isinstance(time_basis, datetime):
        raise IdentityError(f"expected datetime time basis, got {type(time_basis).__name__}")
    if time_basis.tzinfo is None or time_basis.utcoffset() is None:
        raise IdentityError("time basis must be tz-aware -- a naive datetime is not accepted")
    utc_basis = truncate_to_ms(time_basis.astimezone(timezone.utc))
    try:
        return epoch_ms(utc_basis)
    except TimestampError as exc:
        raise IdentityError(str(exc)) from exc


def _assemble_ulid(time_ms: int, entropy: bytes) -> str:
    """Build a 26-char Crockford ULID from a 48-bit ms prefix and 10 bytes of entropy."""
    if not (0 <= time_ms <= 2**48 - 1):
        raise IdentityError(f"time_ms out of the 48-bit ULID time-prefix range: {time_ms}")
    if len(entropy) != 10:
        raise IdentityError(f"ULID entropy must be exactly 10 bytes, got {len(entropy)}")
    raw = time_ms.to_bytes(6, "big") + entropy
    value = int.from_bytes(raw, "big")
    chars = [""] * _ULID_LENGTH
    for i in range(_ULID_LENGTH - 1, -1, -1):
        chars[i] = _CROCKFORD_ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(chars)


def _decode_ulid_bytes(ulid: str) -> bytes:
    """Decode a canonical (already-validated) 26-char ULID string to its 16 raw bytes."""
    value = 0
    for ch in ulid:
        value = (value << 5) | _CROCKFORD_INDEX[ch]
    return value.to_bytes(16, "big")


@dataclass(frozen=True)
class KeyPlan:
    """One derived-column rule: which domain tag and which caller-supplied ref field feed it."""

    domain_tag: str
    ref_field: str
    required: bool


# Closed per-table registry (column -> KeyPlan). The single source of which caller-supplied ref
# field feeds which derived entity/FK column, and under which domain tag. A table's own PK/entity
# column always reads ref_field="entity_ref" (telemetry-event-envelope.yaml: the row's own natural
# reference); an FK column reads the specifically-named ref field the envelope declares
# (session_ref, parent_session_ref, observation_ref, parent_observation_ref) and is computed under
# the PARENT's own domain tag, so it equals the parent's key with no propagation step.
KEY_PLANS: dict[str, dict[str, KeyPlan]] = {
    "telemetry_sessions": {
        "session_id": KeyPlan("telemetry_sessions:session_id", "entity_ref", True),
        "parent_session_id": KeyPlan("telemetry_sessions:session_id", "parent_session_ref", False),
    },
    "telemetry_observations": {
        "session_id": KeyPlan("telemetry_sessions:session_id", "session_ref", True),
        "parent_observation_id": KeyPlan("telemetry_observations:observation_id", "parent_observation_ref", False),
        "observation_id": KeyPlan("telemetry_observations:observation_id", "entity_ref", True),
    },
    "telemetry_transcripts": {
        "session_id": KeyPlan("telemetry_sessions:session_id", "session_ref", True),
        "observation_id": KeyPlan("telemetry_observations:observation_id", "observation_ref", True),
        "transcript_id": KeyPlan("telemetry_transcripts:transcript_id", "entity_ref", True),
    },
    "telemetry_agents": {
        "session_id": KeyPlan("telemetry_sessions:session_id", "session_ref", True),
        "observation_id": KeyPlan("telemetry_observations:observation_id", "observation_ref", False),
        "agent_run_id": KeyPlan("telemetry_agents:agent_run_id", "entity_ref", True),
    },
}


def derive_entity_key(
    domain_tag: str,
    tenant_id: str,
    project_id: str,
    ref: str,
    session_started_at: datetime,
) -> str:
    """An ENTITY or FK key: ULID(48-bit ROOT session_started_at ms + first 80 bits of H)."""
    time_ms = _time_ms_from_basis(session_started_at)
    h = identity_hash(domain_tag, tenant_id, project_id, ref)
    return _assemble_ulid(time_ms, h[:10])


def derive_event_id(
    table: str,
    tenant_id: str,
    project_id: str,
    external_ref: str,
    event_timestamp: datetime,
) -> str:
    """event_id = ULID(48-bit event_timestamp ms + first 80 bits of H over external_ref, tag '<table>:event')."""
    time_ms = _time_ms_from_basis(event_timestamp)
    domain_tag = f"{table}:event"
    h = identity_hash(domain_tag, tenant_id, project_id, external_ref)
    return _assemble_ulid(time_ms, h[:10])


def decode_time_prefix(entity_key: str) -> datetime:
    """Decode a held entity/FK key's 48-bit ms time prefix back to a UTC tz-aware datetime.

    The envelope's sanctioned route for a transcript-less producer (contract risk R7) that holds
    a session_id but not the root transcript: it recovers session_started_at from the id itself.
    """
    canon = canonical_ulid(entity_key)
    raw = _decode_ulid_bytes(canon)
    time_ms = int.from_bytes(raw[:6], "big")
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=time_ms)


__all__ = [
    "DOMAIN_TAGS",
    "KEY_PLANS",
    "IdentityError",
    "KeyPlan",
    "canonical_ref",
    "canonical_ulid",
    "decode_time_prefix",
    "derive_entity_key",
    "derive_event_id",
    "identity_hash",
]
