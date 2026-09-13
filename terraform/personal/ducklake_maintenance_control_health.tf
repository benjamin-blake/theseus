# ---------------------------------------------------------------------------
# Control-table invariant-violation CloudWatch metric alarm (T2.26
# control-table-class-and-counter-conformance), mirrors the circuit-breaker alarm in
# ducklake_maintenance.tf. Fires when ControlTableInvariantViolation >= 1 in a 5-minute window.
#
# Split into its own file (not appended to ducklake_maintenance.tf) so that file keeps exactly
# one aws_cloudwatch_metric_alarm block -- see tests/checks/iam_tf/test_ducklake_maintenance_tf_invariants.py
# (Decision 188 amending Decision 81 clause 6 / CD.33 H1), which asserts that invariant per file.
# Same terraform root/state as ducklake_maintenance.tf; the resource address is unaffected by
# which .tf file defines it.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ducklake_maintenance_control_table_invariant" {
  alarm_name          = "ducklake-maintenance-control-table-invariant"
  alarm_description   = "DuckLake control-class table invariant violated (row count / counter floor / live-file ceiling). T2.26."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ControlTableInvariantViolation"
  namespace           = "DuckLakeMaintenance"
  period              = 300
  statistic           = "Sum"
  threshold           = 1

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name    = "DuckLake Maintenance Control Table Invariant Alarm"
    Purpose = "T2.26 control-table-class-and-counter-conformance invariant alert"
  }
}
