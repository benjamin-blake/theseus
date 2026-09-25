"""Mirror test for src/telemetry/identity.py: golden vectors, negative vectors, DOMAIN_TAGS
closure, KEY_PLANS FK-equality, and the envelope-contract pointer test.
"""

from __future__ import annotations

import hashlib
import struct
import unicodedata
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from src.telemetry.identity import (
    DOMAIN_TAGS,
    KEY_PLANS,
    IdentityError,
    _assemble_ulid,
    canonical_ref,
    canonical_ulid,
    decode_time_prefix,
    derive_entity_key,
    derive_event_id,
    identity_hash,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "identity_vectors.yaml"
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # pragma: allowlist secret


def _load_vectors() -> dict:
    return yaml.safe_load(_FIXTURES.read_text(encoding="ascii"))


def _independent_length_prefixed(value: str) -> bytes:
    """Recompute the length-prefixed NFC UTF-8 encoding from scratch (struct, not identity.py)."""
    nfc = unicodedata.normalize("NFC", value)
    encoded = nfc.encode("utf-8")
    return struct.pack(">I", len(encoded)) + encoded


def _independent_identity_hash(tag: str, tenant_id: str, project_id: str, ref: str) -> bytes:
    buf = b"".join(
        _independent_length_prefixed(p)
        for p in (tag, tenant_id.upper(), project_id.upper(), unicodedata.normalize("NFC", ref))
    )
    return hashlib.sha256(buf).digest()


def _independent_crockford_encode(raw: bytes) -> str:
    assert len(raw) == 16
    value = int.from_bytes(raw, "big")
    chars = [""] * 26
    for i in range(25, -1, -1):
        chars[i] = _ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(chars)


class TestGoldenVectors:
    def test_positive_vectors_match_module_and_independent_recomputation(self) -> None:
        vectors = _load_vectors()["positive_vectors"]
        assert len(vectors) >= 15
        for vector in vectors:
            time_basis = datetime.fromisoformat(vector["time_basis"])

            module_h = identity_hash(vector["domain_tag"], vector["tenant_id"], vector["project_id"], vector["ref"])
            module_id = derive_entity_key(
                vector["domain_tag"], vector["tenant_id"], vector["project_id"], vector["ref"], time_basis
            )
            assert module_h.hex() == vector["h_hex"], vector["name"]
            assert module_id == vector["id"], vector["name"]

            independent_h = _independent_identity_hash(
                vector["domain_tag"], vector["tenant_id"], vector["project_id"], vector["ref"]
            )
            assert independent_h.hex() == vector["h_hex"], f"{vector['name']} (independent recompute)"
            independent_raw = bytes.fromhex(vector["raw_bytes_hex"])
            assert independent_raw == vector["time_ms"].to_bytes(6, "big") + independent_h[:10], vector["name"]
            independent_id = _independent_crockford_encode(independent_raw)
            assert independent_id == vector["id"], f"{vector['name']} (independent Crockford encode)"

    def test_fk_equality_pair(self) -> None:
        vectors = {v["name"]: v for v in _load_vectors()["positive_vectors"]}
        assert vectors["fk_parent_session_key"]["id"] == vectors["fk_child_over_parent_tag"]["id"]

    def test_nfc_equivalence_pair(self) -> None:
        vectors = {v["name"]: v for v in _load_vectors()["positive_vectors"]}
        assert vectors["nfc_composed_ref"]["id"] == vectors["nfc_decomposed_ref"]["id"]

    def test_lowercase_tenant_canonicalisation(self) -> None:
        vectors = {v["name"]: v for v in _load_vectors()["positive_vectors"]}
        assert vectors["uppercase_tenant"]["id"] == vectors["lowercase_tenant"]["id"]

    def test_submillisecond_truncation_never_rounds(self) -> None:
        vectors = {v["name"]: v for v in _load_vectors()["positive_vectors"]}
        v = vectors["submillisecond_truncation"]
        decoded = decode_time_prefix(v["id"])
        assert decoded.microsecond == 999000

    def test_nonutc_offset_normalised_to_same_ms(self) -> None:
        vectors = {v["name"]: v for v in _load_vectors()["positive_vectors"]}
        assert vectors["utc_time_basis"]["id"] == vectors["nonutc_offset_normalised"]["id"]

    def test_whitespace_never_trimmed(self) -> None:
        vectors = {v["name"]: v for v in _load_vectors()["positive_vectors"]}
        assert vectors["whitespace_ref"]["id"] != vectors["unpadded_ref_for_contrast"]["id"]

    def test_decode_time_prefix_round_trip(self) -> None:
        vectors = {v["name"]: v for v in _load_vectors()["positive_vectors"]}
        v = vectors["decode_round_trip"]
        expected = datetime.fromisoformat(v["time_basis"]).replace(microsecond=999000)
        assert decode_time_prefix(v["id"]) == expected

    def test_full_preimage_hex_documented(self) -> None:
        vectors = {v["name"]: v for v in _load_vectors()["positive_vectors"]}
        v = vectors["full_preimage_documented"]
        preimage = bytes.fromhex(v["preimage_hex"])
        assert hashlib.sha256(preimage).digest().hex() == v["h_hex"]

    def test_event_id_vector(self) -> None:
        vectors = {v["name"]: v for v in _load_vectors()["positive_vectors"]}
        v = vectors["session_event_id"]
        table = v["domain_tag"].rsplit(":", 1)[0]
        time_basis = datetime.fromisoformat(v["time_basis"])
        assert derive_event_id(table, v["tenant_id"], v["project_id"], v["ref"], time_basis) == v["id"]


class TestNegativeVectors:
    def test_negative_vectors_raise_identity_error(self) -> None:
        vectors = _load_vectors()["negative_vectors"]
        assert len(vectors) >= 8
        for v in vectors:
            with pytest.raises(IdentityError):
                if v["kind"] == "tag":
                    identity_hash(v["domain_tag"], v["tenant_id"], v["project_id"], v["ref"])
                elif v["kind"] == "time" and "time_basis_naive" in v:
                    naive = datetime.fromisoformat(v["time_basis_naive"])
                    derive_entity_key(v["domain_tag"], v["tenant_id"], v["project_id"], v["ref"], naive)
                elif v["kind"] == "time":
                    aware = datetime.fromisoformat(v["time_basis"])
                    derive_entity_key(v["domain_tag"], v["tenant_id"], v["project_id"], v["ref"], aware)
                elif v["kind"] == "tenant":
                    canonical_ulid(v["tenant_id"])
                elif v["kind"] == "ref_length":
                    canonical_ref(v["ref_fill_char"] * v["ref_length_bytes"])
                else:  # ref
                    canonical_ref(v["ref"])


class TestCanonicalUlidRejections:
    def test_rejects_non_str(self) -> None:
        with pytest.raises(IdentityError):
            canonical_ulid(12345)  # type: ignore[arg-type]

    def test_rejects_non_crockford_character(self) -> None:
        with pytest.raises(IdentityError):
            canonical_ulid("!" + "A" * 25)


class TestTimeBasisRejections:
    def test_rejects_non_datetime_time_basis(self) -> None:
        with pytest.raises(IdentityError):
            derive_entity_key(
                "telemetry_sessions:session_id",
                "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "x",
                "not-a-datetime",  # type: ignore[arg-type]
            )


class TestAssembleUlidBounds:
    def test_rejects_out_of_range_time_ms(self) -> None:
        with pytest.raises(IdentityError):
            _assemble_ulid(2**48, b"0123456789")

    def test_rejects_negative_time_ms(self) -> None:
        with pytest.raises(IdentityError):
            _assemble_ulid(-1, b"0123456789")

    def test_rejects_wrong_entropy_length(self) -> None:
        with pytest.raises(IdentityError):
            _assemble_ulid(0, b"short")


class TestDomainTagsClosure:
    def test_domain_tags_is_the_closed_eight_tag_registry(self) -> None:
        assert DOMAIN_TAGS == frozenset(
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

    def test_unknown_tag_raises(self) -> None:
        with pytest.raises(IdentityError):
            identity_hash("nope:nope", "01ARZ3NDEKTSV4RRFFQ69G5FAV", "01ARZ3NDEKTSV4RRFFQ69G5FAV", "x")


class TestKeyPlansFkEquality:
    def test_every_table_has_a_key_plan(self) -> None:
        assert set(KEY_PLANS) == {
            "telemetry_sessions",
            "telemetry_observations",
            "telemetry_transcripts",
            "telemetry_agents",
        }

    def test_fk_domain_tag_equals_the_referenced_table_own_entity_tag(self) -> None:
        # Every table's OWN entity-key domain tag (the plan whose ref_field is "entity_ref").
        entity_tag_by_table = {
            table: next(p.domain_tag for p in plans.values() if p.ref_field == "entity_ref")
            for table, plans in KEY_PLANS.items()
        }
        # An FK column's domain_tag must equal the PARENT table's own entity tag (Decision 199's
        # no-propagation rule): computing it with the same tag+ref as the parent used yields the
        # identical key with no coordination step.
        fk_expectations = {
            ("telemetry_sessions", "parent_session_id"): "telemetry_sessions",
            ("telemetry_observations", "session_id"): "telemetry_sessions",
            ("telemetry_observations", "parent_observation_id"): "telemetry_observations",
            ("telemetry_transcripts", "session_id"): "telemetry_sessions",
            ("telemetry_transcripts", "observation_id"): "telemetry_observations",
            ("telemetry_agents", "session_id"): "telemetry_sessions",
            ("telemetry_agents", "observation_id"): "telemetry_observations",
        }
        for (table, column), parent_table in fk_expectations.items():
            assert KEY_PLANS[table][column].domain_tag == entity_tag_by_table[parent_table], f"{table}.{column}"

        tenant = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
        project = "01BRZ3NDEKTSV4RRFFQ69G5FBW"
        time_basis = datetime.fromisoformat("2026-09-25T10:00:00+00:00")
        for (table, column), parent_table in fk_expectations.items():
            plan = KEY_PLANS[table][column]
            fk_value = derive_entity_key(plan.domain_tag, tenant, project, "shared-fk-ref", time_basis)
            parent_plan = next(p for p in KEY_PLANS[parent_table].values() if p.ref_field == "entity_ref")
            parent_value = derive_entity_key(parent_plan.domain_tag, tenant, project, "shared-fk-ref", time_basis)
            assert fk_value == parent_value, f"{table}.{column} vs {parent_table}"

    def test_required_ref_absent_raises_optional_yields_none(self) -> None:
        # This test documents the KEY_PLANS.required contract; append.py enforces it at the row
        # level (tests/telemetry/test_append.py). Here we assert the registry itself is consistent:
        # every table has exactly one required=True entry with ref_field="entity_ref" (its own key).
        for table, plans in KEY_PLANS.items():
            entity_plans = [p for p in plans.values() if p.ref_field == "entity_ref"]
            assert len(entity_plans) == 1, table
            assert entity_plans[0].required is True, table


class TestUlidCrossCheck:
    def test_derive_entity_key_matches_python_ulid_encoding(self) -> None:
        ulid_mod = pytest.importorskip("ulid")
        tenant = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
        project = "01BRZ3NDEKTSV4RRFFQ69G5FBW"
        time_basis = datetime.fromisoformat("2026-09-25T10:00:00+00:00")
        h = identity_hash("telemetry_sessions:session_id", tenant, project, "cross-check-ref")
        ours = derive_entity_key("telemetry_sessions:session_id", tenant, project, "cross-check-ref", time_basis)
        raw = int(1790330400000).to_bytes(6, "big") + h[:10]
        theirs = str(ulid_mod.ULID.from_bytes(raw))
        assert ours == theirs


class TestEnvelopeContractPointer:
    def test_envelope_contract_references_golden_vectors(self) -> None:
        envelope_path = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "telemetry-event-envelope.yaml"
        contract = yaml.safe_load(envelope_path.read_text(encoding="utf-8"))
        governance_notes = contract["governance_notes"]
        assert "tests/telemetry/fixtures/identity_vectors.yaml" in governance_notes
        assert _FIXTURES.exists()
        assert _load_vectors()  # parses
