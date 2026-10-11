# DuckLake telemetry writer Lambda (T2.36, slice 2a-2, option D part 1; Decision 143 cl.3, Decision 213).
#
# Telemetry write verbs get their own function, execution role and AWS_IAM Function URL so telemetry
# identities never reach ops_* verbs and the shared catalog login. The role reaches S3 only on the
# isolated ducklake_smoke catalog's data prefix and its fenced blob root, and connects to the catalog as
# its own scoped login (aws_secretsmanager_secret.ducklake_telemetry_writer_dsn). Mirrors
# ducklake_maintenance_smoke.tf (the Decision 143 split precedent).
#
# ---------------------------------------------------------------------------
# APPLY POSTURE (environment-taxonomy.yaml guard_classification): the role CREATE and the
# aws_lambda_function_url change route the saved plan to the tf-gated-apply Environment. In-budget
# inline-policy writes and Lambda config changes auto-apply. Code ships through
# deploy-ducklake-lambdas.yml (build_lambda --deploy is break-glass only), never through this apply:
# the function below sets no source_code_hash (it is addressed by s3_bucket/s3_key; Terraform reads no
# build artifact, environment-taxonomy.yaml conformance) and keeps an ignore_changes block on it as the
# conformance marker and a backstop (Decision 125/126).
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "ducklake_telemetry_writer" {
  name              = "/aws/lambda/${local.ducklake_telemetry_writer_function}"
  retention_in_days = 14

  tags = {
    Name    = "DuckLake Telemetry Writer Logs"
    Purpose = "T2.36 ducklake_telemetry_writer runtime"
  }
}

resource "aws_iam_role" "ducklake_telemetry_writer" {
  # Decision 144 (T2.48): mandatory broad-but-bounded exec-identity boundary.
  name                 = "agent-platform-ducklake-telemetry-writer"
  description          = "Telemetry writer: S3 Get/Put on the smoke catalog data prefix and fenced blob root only, scoped catalog login read"
  permissions_boundary = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "ducklake_telemetry_writer" {
  name = "DuckLakeTelemetryWriterRuntime"
  role = aws_iam_role.ducklake_telemetry_writer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.ducklake_telemetry_writer.arn}:*"]
      },
      {
        # Scoped catalog login only; never the shared ducklake-neon-catalog-dsn.
        Sid      = "TelemetryDsnRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.ducklake_telemetry_writer_dsn.arn]
      },
      {
        # Smoke catalog data prefix ONLY. No Delete, and never the production ducklake/ prefix.
        Sid      = "TelemetryCatalogDataReadWrite"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/${local.ducklake_smoke_data_prefix}/*"]
      },
      {
        Sid      = "TelemetryCatalogDataList"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [aws_s3_bucket.data_lake.arn]
        Condition = {
          StringLike = {
            "s3:prefix" = ["${local.ducklake_smoke_data_prefix}/*"]
          }
        }
      },
      {
        # Fenced to the pinned catalog's blob root. No Delete: orphan deletion belongs to the maintenance role (rec-4033).
        Sid      = "TelemetryBlobReadWrite"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/${local.telemetry_blob_data_prefix}/${local.ducklake_telemetry_meta_schema}/*"]
      },
      {
        Sid      = "TelemetryBlobList"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.data_lake.arn]
        Condition = {
          StringLike = {
            "s3:prefix" = ["${local.telemetry_blob_data_prefix}/${local.ducklake_telemetry_meta_schema}/*"]
          }
        }
      },
      {
        # PutMetricData does not support resource-level scoping; constrain to the function's namespace.
        Sid      = "CloudWatchMetrics"
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "DuckLakeTelemetryWriter"
          }
        }
      },
    ]
  })
}

resource "aws_lambda_function" "ducklake_telemetry_writer" {
  function_name = local.ducklake_telemetry_writer_function
  description   = "T2.36 DuckLake telemetry writer. Env-pinned to the telemetry catalog; own role and scoped catalog login (Decision 213)."
  role          = aws_iam_role.ducklake_telemetry_writer.arn
  runtime       = "python3.12"
  handler       = "src.lambdas.ducklake_telemetry_writer.handler.handler"
  architectures = ["x86_64"]
  timeout       = 120
  memory_size   = 3008 # The writer's baseline (Decision 82).

  # Bounds catalog sessions to 5 containers (connection budget); slice 2c re-sizes it.
  reserved_concurrent_executions = 5

  s3_bucket = aws_s3_bucket.data_lake.id
  s3_key    = "lambda-packages/ducklake-telemetry-writer.zip"

  layers = [
    aws_lambda_layer_version.ducklake_deps.arn,
    aws_lambda_layer_version.ducklake_extensions.arn,
  ]

  environment {
    variables = {
      TELEMETRY_META_SCHEMA         = local.ducklake_telemetry_meta_schema
      TELEMETRY_DATA_PATH           = local.ducklake_smoke_data_path
      TELEMETRY_BLOB_ROOT           = local.ducklake_telemetry_blob_root
      DUCKLAKE_EXTENSION_DIRECTORY  = local.ducklake_extension_dir
      DUCKLAKE_FIELD_SEMANTICS_PATH = "/var/task/config/lambda/ducklake/field_semantics.yaml"
      TELEMETRY_DSN_SECRET_ID       = aws_secretsmanager_secret.ducklake_telemetry_writer_dsn.name
    }
  }

  depends_on = [
    aws_iam_role_policy.ducklake_telemetry_writer,
    aws_cloudwatch_log_group.ducklake_telemetry_writer,
  ]

  tags = {
    Name    = "DuckLake Telemetry Writer"
    Purpose = "T2.36 ducklake_telemetry_writer runtime"
  }

  # Decision 125/126 physical decoupling: code deploys go via the governed CD channel, not terraform.
  # No source_code_hash is set (Terraform reads no build artifact); this block is the conformance marker
  # and a backstop if the argument is ever reintroduced.
  lifecycle {
    ignore_changes = [source_code_hash]
  }
}

resource "aws_lambda_function_url" "ducklake_telemetry_writer" {
  function_name      = aws_lambda_function.ducklake_telemetry_writer.function_name
  authorization_type = "AWS_IAM"
}

resource "aws_ssm_parameter" "ducklake_telemetry_writer_url" {
  name  = "/agent-platform/ducklake/telemetry_writer_url"
  type  = "String"
  value = aws_lambda_function_url.ducklake_telemetry_writer.function_url

  tags = {
    Name    = "DuckLake Telemetry Writer URL"
    Purpose = "T2.36 endpoint discovery"
  }
}

resource "aws_cloudwatch_metric_alarm" "ducklake_telemetry_writer_errors" {
  alarm_name          = "ducklake-telemetry-writer-errors"
  alarm_description   = "DuckLake telemetry writer Lambda errors (loud-fail posture, Decision 55)."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 900
  statistic           = "Sum"
  threshold           = 0

  dimensions = {
    FunctionName = aws_lambda_function.ducklake_telemetry_writer.function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name    = "DuckLake Telemetry Writer Errors Alarm"
    Purpose = "T2.36 runtime error alert"
  }
}

output "ducklake_telemetry_writer_function_url" {
  description = "AWS_IAM Function URL for the ducklake_telemetry_writer Lambda."
  value       = aws_lambda_function_url.ducklake_telemetry_writer.function_url
}

output "ducklake_telemetry_writer_function_name" {
  description = "ducklake_telemetry_writer Lambda function name (governed CD deploy target)."
  value       = aws_lambda_function.ducklake_telemetry_writer.function_name
}
