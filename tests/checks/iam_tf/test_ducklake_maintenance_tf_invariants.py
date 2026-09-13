"""Standing guard: no CloudWatch alarm description on the DuckLake maintenance alarms pins a
THRESHOLD SHAPE (T2.18, Decision 188 amending Decision 81 clause 6 / CD.33 H1).

Block-scoped, not whole-file: each terraform file holds exactly one aws_cloudwatch_metric_alarm
resource (measured), but a SIBLING non-alarm field (e.g. an EventBridge rule's own description) can
carry a legitimate numeric that a whole-file assertion would false-positive on. The assertion is a
SHAPE check (a percentage bound or a byte-unit bound), never any-digit: the rewritten descriptions
retain their "T2.18[ c9] / CD.33 H1" provenance tag, which an any-digit assertion would reject.
Uses the resource-header brace-balanced slice pattern from
tests/checks/iam_tf/test_oidc_trust_slug_invariants.py.
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


class TestAlarmDescriptionsPinNoThreshold:
    def test_admin_tf_has_exactly_one_alarm_block(self) -> None:
        assert len(_alarm_blocks_from_text(_ADMIN_TF.read_text(encoding="utf-8"))) == 1

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
