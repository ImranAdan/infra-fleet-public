# ECR repository for application images (long-lived)
#
# This lives in the permanent stack so that nightly destroy/rebuild cycles
# in staging do not remove published images.

removed {
  from = aws_ecr_repository.flask_hello_world

  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_ecr_lifecycle_policy.flask_hello_world

  lifecycle {
    destroy = false
  }
}

resource "aws_ecr_repository" "load_harness" {
  name                 = "load-harness"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name        = "load-harness"
    Environment = "shared"
    ManagedBy   = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "load_harness" {
  repository = aws_ecr_repository.load_harness.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images, expire older"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

output "load_harness_repository_url" {
  description = "ECR URI for the load-harness application"
  value       = aws_ecr_repository.load_harness.repository_url
}
