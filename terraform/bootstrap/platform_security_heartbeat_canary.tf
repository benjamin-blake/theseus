# Guaranteed IAM-event source for the platform-security-iam-event-heartbeat alarm (rec-4044,
# Decision 202 clause 5). Without this, the heartbeat's only IAM traffic was GitHub's
# terraform-drift refresh, which starts on a throttled 3-6 hour cron: the heartbeat false-alarmed
# on empty hours that carried no real signal. This canary makes one IAM read every 5 minutes,
# Terraform-owned, so the heartbeat's blinding signal (it fires 60-105 minutes after the last
# delivered IAM event) is proven live instead of riding on unrelated CI traffic.
#
# Step Functions, not a direct Scheduler target: EventBridge Scheduler's universal targets reject
# get*/list* API actions (Scheduler user guide, unsupported-api-actions), so Scheduler cannot call
# iam:GetRole directly. The one-Task state machine below makes the call through the aws-sdk
# integration instead.
#
# Scheduler, not an EventBridge scheduled rule: CI's permissions boundary
# (github_ci_apply_boundary.tf) grants events:* in its DataPlaneAllow statement, but no
# scheduler:* verb. A rule-based beat would sit inside CI's reach; a Scheduler-based one does not.
#
# Fail-closed by design: the heartbeat counts delivered IAM events reaching the trail's log group,
# never a canary self-report, so no action on the canary (disabling its schedule, breaking its
# role) can make the heartbeat read OK while the IAM event path is actually blind -- it can only
# starve the heartbeat, which is the alarm's job to catch. Any write to the schedule additionally
# fires platform-security-detector-tamper (the scheduler-write clause in platform_security_alarms.tf).
#
# Single-region rule holds (Decision 202 clause 4): EventBridge Scheduler and Step Functions are
# regional resources in var.aws_region; the IAM call itself goes to IAM's global endpoint, so the
# resulting CloudTrail event still travels the multi-region/global-events path the heartbeat is
# built to prove, exactly as every other IAM event does.
locals {
  platform_security_heartbeat_canary_role_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PlatformSecurityHeartbeatCanaryGetRole"
        Effect   = "Allow"
        Action   = "iam:GetRole"
        Resource = "arn:aws:iam::${var.account_id}:role/platform-security-heartbeat-canary"
      },
    ]
  })

  platform_security_heartbeat_scheduler_role_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PlatformSecurityHeartbeatSchedulerStartExecution"
        Effect   = "Allow"
        Action   = "states:StartExecution"
        Resource = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:platform-security-heartbeat-canary"
      },
    ]
  })

  # Heredoc, not jsonencode: the test suite parses this literal document with json.loads. No
  # interpolation is needed -- the canary's own role name is a fixed literal, matching the name of
  # aws_iam_role.platform_security_heartbeat_canary above.
  platform_security_heartbeat_canary_definition = <<-JSON
  {
    "TimeoutSeconds": 30,
    "StartAt": "GetRole",
    "States": {
      "GetRole": {
        "Type": "Task",
        "Resource": "arn:aws:states:::aws-sdk:iam:getRole",
        "Parameters": {
          "RoleName": "platform-security-heartbeat-canary"
        },
        "ResultPath": null,
        "End": true
      }
    }
  }
  JSON
}

resource "aws_iam_role" "platform_security_heartbeat_canary" {
  name        = "platform-security-heartbeat-canary"
  description = "Heartbeat canary state machine's execution role: iam:GetRole on itself only (Decision 202)"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "states.amazonaws.com" }
        Action    = "sts:AssumeRole"
        Condition = {
          StringEquals = { "aws:SourceAccount" = var.account_id }
          ArnLike      = { "aws:SourceArn" = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:platform-security-heartbeat-canary" }
        }
      },
    ]
  })
}

resource "aws_iam_role_policy" "platform_security_heartbeat_canary" {
  name   = "platform-security-heartbeat-canary"
  role   = aws_iam_role.platform_security_heartbeat_canary.id
  policy = local.platform_security_heartbeat_canary_role_policy_json

  lifecycle {
    precondition {
      # Inline-policy hard limit is 10,240 B; a LimitExceeded is invisible to plan, surfaces at apply.
      condition     = length(jsonencode(jsondecode(local.platform_security_heartbeat_canary_role_policy_json))) <= 10240
      error_message = "platform-security-heartbeat-canary inline policy exceeds the 10,240 B inline-policy limit."
    }
  }
}

# EventBridge Scheduler presents the schedule GROUP's ARN as aws:SourceArn when it assumes an
# execution role (Scheduler user guide, cross-service-confused-deputy-prevention execution-role
# example), never the individual schedule's ARN -- a schedule-ARN condition would deny every beat.
# A dedicated group (platform-security-heartbeat, below) narrows this trust to this canary alone.
resource "aws_iam_role" "platform_security_heartbeat_scheduler" {
  name        = "platform-security-heartbeat-scheduler"
  description = "EventBridge Scheduler's role for the heartbeat canary: states:StartExecution only (Decision 202)"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "scheduler.amazonaws.com" }
        Action    = "sts:AssumeRole"
        Condition = {
          StringEquals = { "aws:SourceAccount" = var.account_id }
          ArnLike      = { "aws:SourceArn" = "arn:aws:scheduler:${var.aws_region}:${var.account_id}:schedule-group/platform-security-heartbeat" }
        }
      },
    ]
  })
}

resource "aws_iam_role_policy" "platform_security_heartbeat_scheduler" {
  name   = "platform-security-heartbeat-scheduler"
  role   = aws_iam_role.platform_security_heartbeat_scheduler.id
  policy = local.platform_security_heartbeat_scheduler_role_policy_json

  lifecycle {
    precondition {
      # Inline-policy hard limit is 10,240 B; a LimitExceeded is invisible to plan, surfaces at apply.
      condition     = length(jsonencode(jsondecode(local.platform_security_heartbeat_scheduler_role_policy_json))) <= 10240
      error_message = "platform-security-heartbeat-scheduler inline policy exceeds the 10,240 B inline-policy limit."
    }
  }
}

# STANDARD, not EXPRESS: 90-day execution history is the canary's own failure evidence (a failed
# beat needs no Retry/Catch -- the heartbeat itself is the alarm on a missing beat).
resource "aws_sfn_state_machine" "platform_security_heartbeat_canary" {
  name       = "platform-security-heartbeat-canary"
  role_arn   = aws_iam_role.platform_security_heartbeat_canary.arn
  type       = "STANDARD"
  definition = local.platform_security_heartbeat_canary_definition
}

resource "aws_scheduler_schedule_group" "platform_security_heartbeat" {
  name = "platform-security-heartbeat"
}

resource "aws_scheduler_schedule" "platform_security_heartbeat_canary" {
  name       = "platform-security-heartbeat-canary"
  group_name = aws_scheduler_schedule_group.platform_security_heartbeat.name

  schedule_expression = "rate(5 minutes)"
  state               = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sfn_state_machine.platform_security_heartbeat_canary.arn
    role_arn = aws_iam_role.platform_security_heartbeat_scheduler.arn

    retry_policy {
      # A retry must never spill into the next 5-minute beat.
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 240
    }
  }

  # No beat fires before both roles hold their grants.
  depends_on = [
    aws_iam_role_policy.platform_security_heartbeat_canary,
    aws_iam_role_policy.platform_security_heartbeat_scheduler,
  ]
}
