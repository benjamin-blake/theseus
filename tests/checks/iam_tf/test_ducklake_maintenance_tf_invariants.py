"""Standing guard: no CloudWatch alarm description on the DuckLake maintenance alarms pins a
THRESHOLD SHAPE (T2.18, Decision 188 amending Decision 81 clause 6 / CD.33 H1).

Block-scoped, not whole-file: a terraform file can hold MULTIPLE aws_cloudwatch_metric_alarm
resources (ducklake_maintenance.tf holds three as of production-gc-and-storage-stability: the
breaker alarm, and two gc_ops alarms placed after it), and a SIBLING non-alarm field (e.g. an
EventBridge rule's own description) can carry a legitimate numeric that a whole-file assertion
would false-positive on. The assertion is a SHAPE check (a percentage bound or a byte-unit bound),
never any-digit: the rewritten descriptions retain their "T2.18[ c9] / CD.33 H1" provenance tag,
which an any-digit assertion would reject. Uses the resource-header brace-balanced slice pattern
from tests/checks/iam_tf/test_oidc_trust_slug_invariants.py.

Also hosts TestProductionGcRuleInvariants (production-gc-and-storage-stability, T2.18 c2): the
gc_ops EventBridge rule's state matches its declared intent (_INTENDED_GC_OPS_STATE, currently
"ENABLED" per gc-ops-baseline-gate-and-schedule-enable), the maintenance role's IAM stays
unwidened, the liveness alarm treats missing data as breaching, the gc_ops cron does not collide
with this singleton's other two 6-hourly cadences, and the catalog-DR dump precedes the gc_ops
window on the same day. TestGcOpsEnablementBaseline adjudicates the committed
tests/fixtures/gc_ops_dryrun_baseline.json dry_run reading against the shipped G4 caps, licensing
the enablement.

TestDataLakeLifecycleGoverned (PLAN-ducklake-noncurrent-version-reclaim, T2.18) replaces this
module's former no-lifecycle-at-all invariant (which asserted "no lifecycle configuration on the
data-lake bucket at all" when the property meant was "no CURRENT-version expiration") with a
net-tightened guard: it RETAINS the predecessor's directory-wide sweep of every
terraform/personal/*.tf for every aws_s3_bucket_lifecycle_configuration block referencing
aws_s3_bucket.data_lake, whatever its resource name, and ADDS cardinality, prefix-scope,
trailing-slash, declared-coverage, SNAPSHOT_RETAIN_DAYS-binding and status assertions
(Decision 181). TestDataLakeLifecycleRedCases proves the guard can actually fail.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ADMIN_TF = _REPO_ROOT / "terraform" / "personal" / "ducklake_maintenance.tf"
_SMOKE_TF = _REPO_ROOT / "terraform" / "personal" / "ducklake_maintenance_smoke.tf"

_ALARM_RESOURCE_RE = re.compile(r'resource\s+"aws_cloudwatch_metric_alarm"\s+"(\w+)"\s*\{')
_ALARM_DESCRIPTION_RE = re.compile(r'alarm_description\s*=\s*"([^"]*)"')

# A threshold SHAPE: a percentage bound (">20%") or a byte-unit bound ("10 GiB", "500MB",
# "1024 bytes"). Never any-digit -- a bare \d check would reject the rewritten descriptions' own
# retained "T2.18[ c9] / CD.33 H1" provenance tag.
_THRESHOLD_SHAPE_RE = re.compile(r">\s*\d+\s*%|\d+\s*(?:GiB|GB|MB|bytes)", re.IGNORECASE)


def _alarm_blocks_from_text(text: str) -> list[str]:
    """Return the full text of each aws_cloudwatch_metric_alarm resource block, brace-balanced."""
    blocks = []
    for match in _ALARM_RESOURCE_RE.finditer(text):
        depth = 0
        end = match.end() - 1
        for i in range(match.end() - 1, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        blocks.append(text[match.start() : end + 1])
    return blocks


def _alarm_descriptions_from_text(text: str) -> list[str]:
    descriptions = []
    for block in _alarm_blocks_from_text(text):
        m = _ALARM_DESCRIPTION_RE.search(block)
        assert m is not None, f"alarm block has no alarm_description: {block[:200]}"
        descriptions.append(m.group(1))
    return descriptions


def _alarm_descriptions(path: Path) -> list[str]:
    return _alarm_descriptions_from_text(path.read_text(encoding="utf-8"))


def _find_resource_block(text: str, resource_type: str, resource_name: str) -> str:
    """Brace-balanced slice for one named resource block (generalizes _alarm_blocks_from_text's
    pattern to any resource type/name -- production-gc-and-storage-stability)."""
    pattern = re.compile(rf'resource\s+"{re.escape(resource_type)}"\s+"{re.escape(resource_name)}"\s*\{{')
    match = pattern.search(text)
    assert match is not None, f"resource {resource_type!r} {resource_name!r} not found"
    depth = 0
    end = match.end() - 1
    for i in range(match.end() - 1, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    return text[match.start() : end + 1]


class TestAlarmDescriptionsPinNoThreshold:
    def test_admin_tf_has_exactly_three_alarm_blocks(self) -> None:
        """Breaker alarm (unchanged, index 0) + the two gc_ops alarms (production-gc-and-storage-stability)."""
        assert len(_alarm_blocks_from_text(_ADMIN_TF.read_text(encoding="utf-8"))) == 3

    def test_smoke_tf_has_exactly_one_alarm_block(self) -> None:
        assert len(_alarm_blocks_from_text(_SMOKE_TF.read_text(encoding="utf-8"))) == 1

    def test_alarm_descriptions_pin_no_threshold(self) -> None:
        for path in (_ADMIN_TF, _SMOKE_TF):
            for description in _alarm_descriptions(path):
                assert not _THRESHOLD_SHAPE_RE.search(description), (
                    f"{path}: alarm_description {description!r} pins a threshold SHAPE -- "
                    "retire it (Decision 55 / Decision 188)."
                )

    def test_alarm_descriptions_retain_provenance_tag(self) -> None:
        """Proves the assertion is shape-scoped, not any-digit: the retained tag carries digits
        ("T2.18", "T2.18 c9") and must survive untouched."""
        admin_desc = _alarm_descriptions(_ADMIN_TF)[0]
        smoke_desc = _alarm_descriptions(_SMOKE_TF)[0]
        assert "T2.18 / CD.33 H1" in admin_desc
        assert "T2.18 c9 / CD.33 H1" in smoke_desc


# ---------------------------------------------------------------------------
# Red-case fixtures: prove the assertion is block-scoped (not whole-file) and shape-scoped (not
# any-digit). All three are required, per the plan's own discrimination requirement.
# ---------------------------------------------------------------------------

_SYNTHETIC_MIXED_TF = """
resource "aws_cloudwatch_event_rule" "example_schedule" {
  name        = "example-schedule"
  description = "Runs on a schedule, transferring up to 500MB per batch, every 6h."
}

resource "aws_cloudwatch_metric_alarm" "example_alarm" {
  alarm_name        = "example-circuit-breaker"
  alarm_description = "Example fail-closed guard-set trip alert. T2.18 / CD.33 H1."
  metric_name       = "ExampleTrip"
}
"""


_TERRAFORM_PERSONAL_DIR = _REPO_ROOT / "terraform" / "personal"
_DR_TF = _TERRAFORM_PERSONAL_DIR / "ducklake_catalog_dr.tf"
_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "gc_ops_dryrun_baseline.json"
_LIFECYCLE_CONFIG_RE = re.compile(r'resource\s+"aws_s3_bucket_lifecycle_configuration"\s+"(\w+)"\s*\{')
_CRON_MINUTE_RE = re.compile(r'schedule_expression\s*=\s*"cron\((\d+)\s')
_CRON_FIELDS_RE = re.compile(r"cron\((\d+)\s+(\d+)\s+\S+\s+\S+\s+(\S+)\s+\S+\)")

# gc-ops-baseline-gate-and-schedule-enable: the declared intent for the gc_ops rule's state.
# Parameterised so a rollback flip is one constant edit, no test surgery, no re-keyed check_id.
_INTENDED_GC_OPS_STATE = "ENABLED"

# Catalog-identity floor for the committed dry_run reading (plan amended 2026-09-17, #1205).
# FROZEN LITERALS, never derived from field_semantics.yaml: the fixture is an immutable historical
# reading, so a literal floor can never redden on a future roster rename, and deriving would
# re-import the very roster whose misreading produced the original (falsified) premise that
# ducklake_smoke_* names are smoke-resident. They are production-resident -- ducklake_writer's
# smoke_actions falls through to the production META_SCHEMA -- so no negative clause on them can
# ever hold. Nothing shipped creates an ops_* table under META_SCHEMA='ducklake_smoke', so a
# smoke-targeted reading fails every one of these names.
_PRODUCTION_CATALOG_TABLE_FLOOR = frozenset(
    {
        "ops_recommendations_current",
        "ops_recommendations_history",
        "ops_decisions_current",
        "ops_decisions_history",
        "ops_entity_counters",
    }
)

# Provenance anchor: deploy-ducklake-lambdas.yml run 17 shipped #1203's drain walk and completed at
# this timestamp. captured_at must post-date the COMPLETION rather than the merge commit -- a reading
# taken inside the merge-to-deploy window would have exercised pre-drain code. The id and the
# timestamp are pinned TOGETHER so the two provenance fields cannot silently disagree; a fixture
# re-taken after a later deploy must move both.
_DRAIN_DEPLOY_RUN_ID = 17
_DRAIN_DEPLOY_COMPLETED_AT = "2026-09-16T13:21:24+00:00"


class TestProductionGcRuleInvariants:
    """production-gc-and-storage-stability (T2.18 c2): the gc_ops rule + its two alarms, and the
    no-lifecycle-on-the-lakehouse invariant."""

    def test_gc_ops_rule_state_matches_declared_intent(self) -> None:
        """Parameterised on _INTENDED_GC_OPS_STATE (gc-ops-baseline-gate-and-schedule-enable) so a
        rollback flip is one constant edit, no test surgery. Block-scoped: the opposing literal must
        appear nowhere in the resource block, which also covers the `description` attribute -- an
        APPLIED resource attribute that ships to AWS, not a comment."""
        text = _ADMIN_TF.read_text(encoding="utf-8")
        block = _find_resource_block(text, "aws_cloudwatch_event_rule", "ducklake_maintenance_gc_ops")
        m = re.search(r'state\s*=\s*"([^"]*)"', block)
        assert m is not None, "gc_ops rule has no state attribute"
        assert m.group(1) == _INTENDED_GC_OPS_STATE, (
            f"gc_ops rule state {m.group(1)!r} does not match the declared intent {_INTENDED_GC_OPS_STATE!r}"
        )
        opposing = "DISABLED" if _INTENDED_GC_OPS_STATE == "ENABLED" else "ENABLED"
        assert opposing not in block, (
            f"the opposing literal {opposing!r} still appears in the gc_ops resource block -- check "
            "the `description` attribute, not just the `state` literal"
        )

    def test_maintenance_role_iam_is_not_widened(self) -> None:
        """gc_ops needs NO new IAM: the role already carries s3:ListBucket scoped to the prod prefix
        and cloudwatch:PutMetricData conditioned on the DuckLakeMaintenance namespace -- that
        namespace condition is WHY an unemitted gc_ops metric reads absent rather than breached, so
        it must be asserted here, not merely assumed."""
        text = _ADMIN_TF.read_text(encoding="utf-8")
        policy_block = _find_resource_block(text, "aws_iam_role_policy", "ducklake_maintenance")
        assert '"cloudwatch:namespace" = "DuckLakeMaintenance"' in policy_block
        assert '"s3:prefix" = ["${local.ducklake_prod_data_prefix}/*"]' in policy_block
        sids = re.findall(r'Sid\s*=\s*"(\w+)"', policy_block)
        assert sids == ["Logs", "NeonDsnRead", "S3DataReadWriteDelete", "S3ListDataPrefix", "CloudWatchMetrics"], (
            f"maintenance role IAM Sid set changed -- gc_ops must not widen it: {sids}"
        )

    def test_liveness_alarm_treats_missing_data_as_breaching(self) -> None:
        """The liveness alarm is the OTHER half of the absence-detection problem the breach alarm's
        notBreaching posture deliberately leaves open: a pass that never runs must be visible."""
        text = _ADMIN_TF.read_text(encoding="utf-8")
        block = _find_resource_block(text, "aws_cloudwatch_metric_alarm", "ducklake_maintenance_gc_ops_liveness")
        metric = re.search(r'metric_name\s*=\s*"([^"]*)"', block)
        treat_missing = re.search(r'treat_missing_data\s*=\s*"([^"]*)"', block)
        assert metric is not None and metric.group(1) == "GcDeletedSnapshots"
        assert treat_missing is not None and treat_missing.group(1) == "breaching"

    def test_liveness_alarm_period_product_stays_inside_the_putmetricalarm_cap(self) -> None:
        """rec-3881 regression: PutMetricAlarm rejects EvaluationPeriods*Period > 86400s when
        period<3600, and > 604800s when period>=3600 -- a runtime CloudWatch API validation that
        terraform plan/validate cannot see. The prior period=1800/evaluation_periods=480 design
        (864000s) satisfied neither cap; it was sized against the wrong (>=3600-only) ceiling."""
        text = _ADMIN_TF.read_text(encoding="utf-8")
        block = _find_resource_block(text, "aws_cloudwatch_metric_alarm", "ducklake_maintenance_gc_ops_liveness")
        period = re.search(r"period\s*=\s*(\d+)", block)
        evaluation_periods = re.search(r"evaluation_periods\s*=\s*(\d+)", block)
        assert period is not None and evaluation_periods is not None
        period_s = int(period.group(1))
        product = period_s * int(evaluation_periods.group(1))
        cap = 86400 if period_s < 3600 else 604800
        assert product <= cap, (
            f"aws_cloudwatch_metric_alarm.ducklake_maintenance_gc_ops_liveness: "
            f"evaluation_periods*period={product}s exceeds the PutMetricAlarm cap ({cap}s for "
            f"period={period_s}s) -- this apply will be rejected by CloudWatch (rec-3881)."
        )

    def test_referenced_missing_alarm_treats_missing_data_as_not_breaching(self) -> None:
        """The BREACH alarm is deliberately the opposite posture: a weekly metric is legitimately
        absent six days in seven, and this alarm is the breach detector, not the liveness detector."""
        text = _ADMIN_TF.read_text(encoding="utf-8")
        block = _find_resource_block(text, "aws_cloudwatch_metric_alarm", "ducklake_maintenance_gc_ops_referenced_missing")
        metric = re.search(r'metric_name\s*=\s*"([^"]*)"', block)
        treat_missing = re.search(r'treat_missing_data\s*=\s*"([^"]*)"', block)
        assert metric is not None and metric.group(1) == "GcReferencedMissing"
        assert treat_missing is not None and treat_missing.group(1) == "notBreaching"

    def test_gc_ops_rule_cron_does_not_collide_with_the_singleton_cadences(self) -> None:
        """reserved_concurrent_executions=1 on this singleton function means any cadence collision
        throttles with a 429 that -- per the absence-detection problem -- would be SILENT."""
        text = _ADMIN_TF.read_text(encoding="utf-8")
        gc_ops_block = _find_resource_block(text, "aws_cloudwatch_event_rule", "ducklake_maintenance_gc_ops")
        merge_ops_block = _find_resource_block(text, "aws_cloudwatch_event_rule", "ducklake_maintenance_merge_ops")
        control_health_block = _find_resource_block(text, "aws_cloudwatch_event_rule", "ducklake_maintenance_control_health")

        gc_ops_minute = _CRON_MINUTE_RE.search(gc_ops_block)
        merge_ops_minute = _CRON_MINUTE_RE.search(merge_ops_block)
        control_health_minute = _CRON_MINUTE_RE.search(control_health_block)
        assert gc_ops_minute and merge_ops_minute and control_health_minute

        minutes = {gc_ops_minute.group(1), merge_ops_minute.group(1), control_health_minute.group(1)}
        assert len(minutes) == 3, f"cadence minute collision on this reserved_concurrent_executions=1 singleton: {minutes}"

    def test_dr_dump_precedes_the_gc_ops_window(self) -> None:
        """Backup precedes destruction: two independently-authored cron literals in two different
        files, unchecked until this plan enabled the destructive cadence. Does NOT prove the backup
        COMPLETED (rec-3909's deferred half) -- only that its scheduled window starts first, on the
        same day."""
        gc_ops_block = _find_resource_block(
            _ADMIN_TF.read_text(encoding="utf-8"), "aws_cloudwatch_event_rule", "ducklake_maintenance_gc_ops"
        )
        dr_block = _find_resource_block(_DR_TF.read_text(encoding="utf-8"), "aws_cloudwatch_event_rule", "ducklake_catalog_dr")
        gc_ops_cron = _CRON_FIELDS_RE.search(gc_ops_block)
        dr_cron = _CRON_FIELDS_RE.search(dr_block)
        assert gc_ops_cron is not None, "gc_ops rule has no parseable cron schedule_expression"
        assert dr_cron is not None, "catalog-DR rule has no parseable cron schedule_expression"

        gc_ops_minute, gc_ops_hour, gc_ops_dow = gc_ops_cron.groups()
        dr_minute, dr_hour, dr_dow = dr_cron.groups()
        assert dr_dow == gc_ops_dow, (
            f"catalog-DR ({dr_dow}) and gc_ops ({gc_ops_dow}) do not share a day-of-week -- the "
            "ordering guarantee only holds within the same weekly window"
        )
        dr_offset = int(dr_hour) * 60 + int(dr_minute)
        gc_ops_offset = int(gc_ops_hour) * 60 + int(gc_ops_minute)
        assert dr_offset < gc_ops_offset, (
            f"catalog-DR dump ({dr_hour}:{dr_minute} UTC) does not precede the gc_ops destructive "
            f"window ({gc_ops_hour}:{gc_ops_minute} UTC) -- backup must run first"
        )


# TestDataLakeLifecycleGoverned (PLAN-ducklake-noncurrent-version-reclaim, T2.18): text-parameterized
# helpers (mirroring _alarm_blocks_from_text above) so red cases can feed a synthetic corpus.


def _tf_dir_file_texts(tf_dir: Path) -> dict[str, str]:
    """{filename: text}, factored out so red-case fixtures can substitute a synthetic mapping."""
    return {tf_file.name: tf_file.read_text(encoding="utf-8") for tf_file in sorted(tf_dir.glob("*.tf"))}


def _data_lake_lifecycle_blocks_from_texts(file_texts: dict[str, str]) -> list[tuple[str, str]]:
    """(filename, block_text) for every lifecycle-config block, in any file, referencing
    aws_s3_bucket.data_lake -- whatever its resource name (Decision 181 breadth)."""
    found: list[tuple[str, str]] = []
    for filename, text in file_texts.items():
        for match in _LIFECYCLE_CONFIG_RE.finditer(text):
            block = _find_resource_block(text, "aws_s3_bucket_lifecycle_configuration", match.group(1))
            if "aws_s3_bucket.data_lake" in block:
                found.append((filename, block))
    return found


def _single_data_lake_lifecycle_block(file_texts: dict[str, str]) -> str:
    """The one governed block -- asserts cardinality itself, not only via the dedicated test."""
    matches = _data_lake_lifecycle_blocks_from_texts(file_texts)
    assert len(matches) == 1, (
        f"expected exactly one aws_s3_bucket_lifecycle_configuration targeting "
        f"aws_s3_bucket.data_lake, found {len(matches)}: {[name for name, _ in matches]}"
    )
    return matches[0][1]


_DATA_PREFIX_LOCAL_RE = re.compile(r'\b(\w+_data_prefix)\s*=\s*"([^"]+)"')


def _declared_data_prefix_locals(file_texts: dict[str, str]) -> dict[str, str]:
    """{local_name: prefix_value}, DERIVED from every *_data_prefix local -- never hand-authored
    (a hand-written roster lets a future third prefix pass the coverage sweep vacuously)."""
    roster: dict[str, str] = {}
    for text in file_texts.values():
        for match in _DATA_PREFIX_LOCAL_RE.finditer(text):
            roster[match.group(1)] = match.group(2)
    return roster


# A future *_data_prefix local with no entry here fails the coverage test, never passes vacuously.
_DECLARED_LIFECYCLE_EXCLUSIONS: dict[str, str] = {
    "ducklake_smoke_data_prefix": (
        "rec-3892's unexplained object-disappearance RCA is open in the smoke prefix; a managed "
        "lifecycle rule there would contaminate that investigation. rec-3945 owns the RCA."
    ),
}

# `\b` cannot match inside "noncurrent_version_expiration" (no boundary between two word chars),
# so the negative lookbehind is a belt-and-suspenders duplicate of that same exclusion.
_CURRENT_VERSION_EXPIRATION_RE = re.compile(r"(?<!noncurrent_version_)\bexpiration\s*\{([^}]*)\}", re.DOTALL)
_CURRENT_VERSION_EXPIRATION_AGE_RE = re.compile(r"\b(?:days|date)\s*=")
_GOVERNED_PREFIX_RE = re.compile(r'prefix\s*=\s*"\$\{local\.ducklake_prod_data_prefix\}/"')


class TestDataLakeLifecycleGoverned:
    """PLAN-ducklake-noncurrent-version-reclaim: net-tightened replacement (Decision 181)."""

    def test_exactly_one_lifecycle_configuration_targets_the_data_lake_bucket(self) -> None:
        """Directory-wide: a second config added to ANY OTHER FILE must still be caught."""
        matches = _data_lake_lifecycle_blocks_from_texts(_tf_dir_file_texts(_TERRAFORM_PERSONAL_DIR))
        assert len(matches) == 1, (
            f"expected exactly one aws_s3_bucket_lifecycle_configuration targeting "
            f"aws_s3_bucket.data_lake across every terraform/personal/*.tf, found {len(matches)}: "
            f"{[name for name, _ in matches]}"
        )

    def test_sweep_uses_the_directory_wide_glob_idiom(self) -> None:
        """Mechanically impossible to narrow to main.tf-only -- reads this module's OWN source."""
        source = Path(__file__).read_text(encoding="utf-8")
        assert '_TERRAFORM_PERSONAL_DIR.glob("*.tf")' in source, (
            'the directory-wide sweep no longer uses the _TERRAFORM_PERSONAL_DIR.glob("*.tf") '
            "idiom -- a main.tf-only guard would be a weakening (Decision 181)"
        )

    def test_rule_status_is_enabled(self) -> None:
        """A Disabled rule satisfies every other assertion here while reclaiming nothing."""
        block = _single_data_lake_lifecycle_block(_tf_dir_file_texts(_TERRAFORM_PERSONAL_DIR))
        assert re.search(r'status\s*=\s*"Enabled"', block), "governed rule's status is not the literal Enabled"

    def test_prefix_is_derived_from_the_declared_local_with_a_trailing_slash(self) -> None:
        block = _single_data_lake_lifecycle_block(_tf_dir_file_texts(_TERRAFORM_PERSONAL_DIR))
        assert _GOVERNED_PREFIX_RE.search(block), (
            'prefix is not exactly "${local.ducklake_prod_data_prefix}/" -- a retyped literal or a '
            "missing trailing slash would also match the sibling smoke prefix (Decision 191)"
        )

    def test_no_current_version_expiration_rule(self) -> None:
        """An age rule here would delete live Parquet the catalog still references."""
        block = _single_data_lake_lifecycle_block(_tf_dir_file_texts(_TERRAFORM_PERSONAL_DIR))
        for body in _CURRENT_VERSION_EXPIRATION_RE.findall(block):
            assert not _CURRENT_VERSION_EXPIRATION_AGE_RE.search(body), (
                f"expiration block carries a days/date argument ({body.strip()!r}) -- this deletes "
                "live Parquet the catalog still references (Decision 55/188)"
            )

    def test_expired_object_delete_marker_is_present(self) -> None:
        block = _single_data_lake_lifecycle_block(_tf_dir_file_texts(_TERRAFORM_PERSONAL_DIR))
        assert re.search(r"expired_object_delete_marker\s*=\s*true", block), (
            "rec-3907's acceptance criterion 1 second half is unmet"
        )

    def test_noncurrent_days_bound_to_snapshot_retain_days(self) -> None:
        # Deliberately function-local: the rest of this module reads terraform text and needs no
        # first-party runtime import, so hoisting this would couple collection of every test here
        # to src.common's own import chain.
        from src.common.ducklake_maintenance import SNAPSHOT_RETAIN_DAYS

        block = _single_data_lake_lifecycle_block(_tf_dir_file_texts(_TERRAFORM_PERSONAL_DIR))
        nve = re.search(r"noncurrent_version_expiration\s*\{([^}]*)\}", block, re.DOTALL)
        assert nve is not None, "rule carries no noncurrent_version_expiration block"
        days_match = re.search(r"noncurrent_days\s*=\s*(\d+)", nve.group(1))
        assert days_match is not None, "noncurrent_version_expiration block has no noncurrent_days"
        assert int(days_match.group(1)) == SNAPSHOT_RETAIN_DAYS, (
            f"noncurrent_days={days_match.group(1)} != SNAPSHOT_RETAIN_DAYS={SNAPSHOT_RETAIN_DAYS}"
        )

    def test_every_declared_data_prefix_local_is_covered_or_declared_excluded(self) -> None:
        file_texts = _tf_dir_file_texts(_TERRAFORM_PERSONAL_DIR)
        block = _single_data_lake_lifecycle_block(file_texts)
        roster = _declared_data_prefix_locals(file_texts)
        assert roster, "no *_data_prefix local found -- roster derivation is broken"
        uncovered = [
            local_name
            for local_name in roster
            if f"local.{local_name}" not in block and not _DECLARED_LIFECYCLE_EXCLUSIONS.get(local_name)
        ]
        assert not uncovered, (
            f"data-prefix local(s) {uncovered} are neither covered nor declared excluded -- a future "
            "prefix must not pass this coverage sweep vacuously (Decision 191)"
        )


# Red-case fixtures proving the guard above actually discriminates ("a guard that cannot fail is
# not a guard" -- the plan's VP step 5 fix_if).

_GOOD_DATA_LAKE_LIFECYCLE_TF = """
resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  rule {
    id     = "ducklake-prod-noncurrent-reclaim"
    status = "Enabled"

    filter {
      prefix = "${local.ducklake_prod_data_prefix}/"
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    expiration {
      expired_object_delete_marker = true
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}
"""


class TestDataLakeLifecycleRedCases:
    def test_current_version_expiration_rule_trips(self) -> None:
        """(a) An age-based `days` argument added to the rule's `expiration` block must trip."""
        tf = _GOOD_DATA_LAKE_LIFECYCLE_TF.replace(
            "expiration {\n      expired_object_delete_marker = true\n    }",
            "expiration {\n      expired_object_delete_marker = true\n      days                        = 45\n    }",
        )
        block = _single_data_lake_lifecycle_block({"main.tf": tf})
        bodies = _CURRENT_VERSION_EXPIRATION_RE.findall(block)
        assert any(_CURRENT_VERSION_EXPIRATION_AGE_RE.search(body) for body in bodies), "fixture is broken"

    def test_slashless_prefix_trips(self) -> None:
        """(b) A bare slashless prefix must trip -- it would also match the sibling smoke prefix."""
        tf = _GOOD_DATA_LAKE_LIFECYCLE_TF.replace(
            'prefix = "${local.ducklake_prod_data_prefix}/"', 'prefix = "${local.ducklake_prod_data_prefix}"'
        )
        block = _single_data_lake_lifecycle_block({"main.tf": tf})
        assert not _GOVERNED_PREFIX_RE.search(block), "fixture did not actually drop the trailing slash"

    def test_disabled_status_trips(self) -> None:
        """(c) A Disabled rule satisfies every other assertion while reclaiming nothing."""
        tf = _GOOD_DATA_LAKE_LIFECYCLE_TF.replace('status = "Enabled"', 'status = "Disabled"')
        block = _single_data_lake_lifecycle_block({"main.tf": tf})
        assert not re.search(r'status\s*=\s*"Enabled"', block), "fixture did not actually flip the status"

    def test_second_lifecycle_config_in_another_file_trips_the_cardinality_sweep(self) -> None:
        """(d) A second config in a DIFFERENT file under a DIFFERENT resource name must still trip."""
        file_texts = {
            "main.tf": _GOOD_DATA_LAKE_LIFECYCLE_TF,
            "rogue.tf": _GOOD_DATA_LAKE_LIFECYCLE_TF.replace(
                'resource "aws_s3_bucket_lifecycle_configuration" "data_lake"',
                'resource "aws_s3_bucket_lifecycle_configuration" "data_lake_rogue"',
            ),
        }
        matches = _data_lake_lifecycle_blocks_from_texts(file_texts)
        assert len(matches) == 2, "fixture does not actually add a second block"


class TestThresholdShapeRedCases:
    def test_non_alarm_description_with_a_legitimate_number_does_not_trip_the_block_scoped_check(self) -> None:
        """(a) A non-alarm description (the EventBridge rule's own) carries a real numeric
        ("500MB", "6h") but must NOT trip once the assertion is scoped to the alarm block alone."""
        descriptions = _alarm_descriptions_from_text(_SYNTHETIC_MIXED_TF)
        assert len(descriptions) == 1
        assert not any(_THRESHOLD_SHAPE_RE.search(d) for d in descriptions)

    def test_whole_file_naive_check_would_false_positive_on_the_sibling_field(self) -> None:
        """Demonstrates WHY block-scoping is required: a naive whole-text check trips on the
        EventBridge rule's unrelated "500MB" batch-size mention, which a block-scoped check
        (above) correctly ignores."""
        assert _THRESHOLD_SHAPE_RE.search(_SYNTHETIC_MIXED_TF)

    def test_alarm_description_with_threshold_shape_trips(self) -> None:
        """(b) An alarm description carrying ">20% files or >10 GiB" MUST trip."""
        text = _SYNTHETIC_MIXED_TF.replace(
            "Example fail-closed guard-set trip alert. T2.18 / CD.33 H1.",
            "Circuit breaker tripped (>20% files or >10 GiB). T2.18 / CD.33 H1.",
        )
        descriptions = _alarm_descriptions_from_text(text)
        assert any(_THRESHOLD_SHAPE_RE.search(d) for d in descriptions)

    def test_alarm_description_with_only_provenance_tag_does_not_trip(self) -> None:
        """(c) An alarm description carrying only the "T2.18 / CD.33 H1" provenance tag must NOT
        trip -- this is what distinguishes a shape assertion from an any-digit one."""
        descriptions = _alarm_descriptions_from_text(_SYNTHETIC_MIXED_TF)
        assert "T2.18 / CD.33 H1" in descriptions[0]
        assert not any(_THRESHOLD_SHAPE_RE.search(d) for d in descriptions)


class TestGcOpsEnablementBaseline:
    """gc-ops-baseline-gate-and-schedule-enable: adjudicates the committed operator dry_run reading
    against the shipped G4 caps, licensing the production enable. NECESSARY, not SUFFICIENT -- the
    real pass is post-expiry and strict-sized, a strictly larger and less forgiving check (see
    tests/fixtures/gc_ops_dryrun_baseline.json's own provenance).

    Catalog identity rests on _PRODUCTION_CATALOG_TABLE_FLOOR plus the envelope's own
    ok/action/dry_run self-identification -- all MEASURED handler output, none operator-attested."""

    def test_committed_dry_run_baseline_licenses_the_enablement(self) -> None:
        # Deliberately function-local: the rest of this module reads terraform text and needs no
        # first-party runtime import, so hoisting this would couple collection of every test here
        # to src.common's own import chain.
        from src.common.ducklake_maintenance_ops import G4_MAX_DELETE_BYTES, G4_MAX_DELETE_FILES

        assert _FIXTURE_PATH.is_file(), (
            "tests/fixtures/gc_ops_dryrun_baseline.json is missing -- the operator precondition "
            "(pre_implementation_checklist) was not satisfied before this plan started"
        )
        reading = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))

        assert reading.get("referenced_missing") == 0, (
            f"referenced_missing={reading.get('referenced_missing')!r} -- a catalog-live path is "
            "missing from storage; RCA before enabling (STOP, do not merge)"
        )
        assert reading.get("unsized_candidates") == 0, (
            f"unsized_candidates={reading.get('unsized_candidates')!r} -- the real pass raises on "
            "the first unsized path; the first firing would 500 and trip the breaker"
        )

        ladder = reading.get("drain_probe_counts")
        assert ladder, "drain_probe_counts is absent or empty -- reading predates #1203's drain walk"
        admitting = {
            days: rung
            for days, rung in ladder.items()
            if 0 < rung["files"] <= G4_MAX_DELETE_FILES and rung["bytes"] <= G4_MAX_DELETE_BYTES
        }
        assert admitting, (
            "no ladder rung admits a positive count under both G4 caps -- _drain_walk would return "
            "(None, None) and defer the whole pass every week"
        )

        tables = set(reading.get("tables") or [])
        missing = _PRODUCTION_CATALOG_TABLE_FLOOR - tables
        assert not missing, (
            f"production-catalog floor name(s) {sorted(missing)} absent from `tables` -- this reading "
            "was not taken against the production catalog (the ducklake_smoke catalog carries no "
            "ops_* table). Re-take it against ducklake_ops with an explicit data_path and "
            "meta_schema; never relax the floor to admit the reading you have."
        )

        assert reading.get("ok") is True, f"ok={reading.get('ok')!r} -- the committed envelope is not a success response"
        assert reading.get("action") == "gc_ops", (
            f"action={reading.get('action')!r} -- the committed envelope is not a gc_ops response. "
            "action_clone_catalog reads a Neon copy-on-write branch at this same meta_schema and "
            "data_path, so `action` is what rules that out."
        )
        assert reading.get("dry_run") is True, (
            f"dry_run={reading.get('dry_run')!r} -- the committed reading must be a read-only probe, "
            "never a real destructive pass"
        )

        captured_at = reading.get("captured_at")
        deploy_run_id = reading.get("deploy_run_id")
        assert captured_at, "captured_at provenance attestation is missing"
        assert deploy_run_id == _DRAIN_DEPLOY_RUN_ID, (
            f"deploy_run_id={deploy_run_id!r} -- provenance must name run {_DRAIN_DEPLOY_RUN_ID}, the "
            "deploy-ducklake-lambdas.yml run whose completion anchors the captured_at bound below. A "
            "fixture re-taken after a later deploy must move BOTH provenance constants together."
        )
        captured_dt = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
        deploy_completion = datetime.fromisoformat(_DRAIN_DEPLOY_COMPLETED_AT)
        assert captured_dt > deploy_completion, (
            f"captured_at ({captured_at}) does not post-date deploy-ducklake-lambdas.yml run "
            f"{_DRAIN_DEPLOY_RUN_ID}'s completion ({_DRAIN_DEPLOY_COMPLETED_AT}) -- the reading may "
            "predate the drain code deploy"
        )

        broadest_rung_files = max((rung["files"] for rung in ladder.values()), default=0)
        implied_cycles = -(-broadest_rung_files // G4_MAX_DELETE_FILES) if broadest_rung_files else 0
        print(f"gc_ops dry_run baseline ladder: {ladder}")
        print(
            f"admitting rung(s) under G4 caps: {sorted(admitting, key=int)}; illustrative pre-expiry "
            f"implied drain-cycle estimate (broadest rung {broadest_rung_files} files / "
            f"{G4_MAX_DELETE_FILES} cap): {implied_cycles} -- rec-3870's N is re-grounded from the "
            "POST-expiry real-pass ladder, not this pre-expiry canary"
        )
