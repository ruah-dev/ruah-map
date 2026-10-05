provider "aws" { region = "eu-central-1" }

data "archive_file" "worker" {
  type        = "zip"
  source_dir  = "${path.module}/../../services/worker"
  output_path = "${path.module}/worker.zip"
}

resource "aws_sqs_queue" "orders" {
  name = "acme-orders"
}

resource "aws_s3_bucket" "uploads" {
  bucket = "acme-uploads"
}

resource "aws_iam_role" "worker" {
  name = "acme-worker"
  assume_role_policy = jsonencode({ Version = "2012-10-17" })
}

data "aws_iam_policy_document" "worker" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.uploads.arn}/*"]
  }
}

resource "aws_iam_role_policy" "worker" {
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}

resource "aws_lambda_function" "worker" {
  function_name = "acme-worker"
  filename      = data.archive_file.worker.output_path
  role          = aws_iam_role.worker.arn
  handler       = "handler.main.handler"
  environment {
    variables = { BUCKET = aws_s3_bucket.uploads.bucket }
  }
}

resource "aws_lambda_event_source_mapping" "orders" {
  event_source_arn = aws_sqs_queue.orders.arn
  function_name    = aws_lambda_function.worker.arn
}

resource "aws_db_instance" "main" {
  identifier = "acme-db"
  engine     = "postgres"
  vpc_security_group_ids = [aws_security_group.db.id]
}

resource "aws_security_group" "db" {
  name = "db"
  ingress {
    from_port = 5432
  }
}

module "net" {
  source = "./modules/net"
}
