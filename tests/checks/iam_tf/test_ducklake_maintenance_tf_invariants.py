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
gc_ops EventBridge rule ships DISABLED, no S3 lifecycle configuration targets the data-lake bucket,
the maintenance role's IAM stays unwidened, the liveness alarm treats missing data as breaching,
and the gc_ops cron does not collide with this singleton's other two 6-hourly cadences.
"""

from __future__ import annotations

import re
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
_LIFECYCLE_CONFIG_RE = re.compile(r'resource\s+"aws_s3_bucket_lifecycle_configuration"\s+"(\w+)"\s*\{')
_CRON_MINUTE_RE = re.compile(r'schedule_expression\s*=\s*"cron\((\d+)\s')


class TestProductionGcRuleInvariants:
    """production-gc-and-storage-stability (T2.18 c2): the gc_ops rule + its two alarms, and the
    no-lifecycle-on-the-lakehouse invariant."""

    def test_gc_ops_rule_is_created_disabled(self) -> None:
        text = _ADMIN_TF.read_text(encoding="utf-8")
        block = _find_resource_block(text, "aws_cloudwatch_event_rule", "ducklake_maintenance_gc_ops")
        m = re.search(r'state\s*=\s*"([^"]*)"', block)
        assert m is not None, "gc_ops rule has no state attribute"
        assert m.group(1) == "DISABLED", "the gc_ops rule must ship DISABLED (Decisions 125/126 code/infra decoupling)"

    def test_no_lifecycle_configuration_targets_the_data_lake_bucket(self) -> None:
        """Sweep the WHOLE terraform/personal directory, not just _ADMIN_TF/_SMOKE_TF -- the sole
        existing lifecycle config (ducklake_catalog_dr.tf) legitimately targets the DR bucket, and
        a two-file-only sweep could never see a future lifecycle rule added elsewhere (e.g. s3.tf)."""
        for tf_file in sorted(_TERRAFORM_PERSONAL_DIR.glob("*.tf")):
            text = tf_file.read_text(encoding="utf-8")
            for match in _LIFECYCLE_CONFIG_RE.finditer(text):
                block = _find_resource_block(text, "aws_s3_bucket_lifecycle_configuration", match.group(1))
                assert "aws_s3_bucket.data_lake" not in block, (
                    f"{tf_file.name}: aws_s3_bucket_lifecycle_configuration {match.group(1)!r} targets "
                    "the data-lake bucket -- an age-based expiration rule the catalog knows nothing "
                    "about is over-reclaim BY CONFIGURATION (production-gc-and-storage-stability)."
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
