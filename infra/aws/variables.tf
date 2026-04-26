variable "aws_region" {
  description = "AWS region for the ECS demo environment."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name prefix for provisioned resources."
  type        = string
  default     = "error-budget-gate"
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the deploy role, formatted as owner/repo."
  type        = string
  default     = "saicharankarasala/Error-budget-aware-deployment-gate-design"
}

variable "github_branch" {
  description = "Protected branch allowed to deploy."
  type        = string
  default     = "main"
}

variable "stable_container_image" {
  description = "Stable task image. CI normally writes the ECR image URI here."
  type        = string
  default     = "public.ecr.aws/docker/library/python:3.13-slim"
}

variable "canary_container_image" {
  description = "Canary task image. CI normally writes the ECR image URI here."
  type        = string
  default     = "public.ecr.aws/docker/library/python:3.13-slim"
}

variable "stable_weight" {
  description = "ALB traffic weight for stable target group."
  type        = number
  default     = 100

  validation {
    condition     = var.stable_weight >= 0 && var.stable_weight <= 100
    error_message = "stable_weight must be between 0 and 100."
  }
}

variable "canary_weight" {
  description = "ALB traffic weight for canary target group."
  type        = number
  default     = 0

  validation {
    condition     = var.canary_weight >= 0 && var.canary_weight <= 100
    error_message = "canary_weight must be between 0 and 100."
  }
}

variable "desired_count" {
  description = "Desired task count per ECS service."
  type        = number
  default     = 1
}

variable "container_port" {
  description = "Application container port."
  type        = number
  default     = 8000
}

