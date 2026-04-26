output "alb_url" {
  description = "Public URL for the ECS demo service."
  value       = "http://${aws_lb.this.dns_name}"
}

output "ecr_repository_url" {
  description = "ECR repository for application images."
  value       = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "stable_service_name" {
  description = "Stable ECS service name."
  value       = aws_ecs_service.stable.name
}

output "canary_service_name" {
  description = "Canary ECS service name."
  value       = aws_ecs_service.canary.name
}

output "github_deploy_role_arn" {
  description = "IAM role ARN to store as AWS_ROLE_TO_ASSUME in GitHub Actions secrets."
  value       = aws_iam_role.github_deploy.arn
}

output "prometheus_workspace_endpoint" {
  description = "AWS Managed Prometheus remote write/query endpoint."
  value       = aws_prometheus_workspace.this.prometheus_endpoint
}

output "cloudwatch_dashboard_name" {
  description = "CloudWatch dashboard provisioned for the deployment gate."
  value       = aws_cloudwatch_dashboard.slo.dashboard_name
}

