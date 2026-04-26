resource "aws_cloudwatch_dashboard" "slo" {
  dashboard_name = local.name

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ALB 5xx Error Rate"
          region = data.aws_region.current.name
          view   = "timeSeries"
          stat   = "Sum"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", aws_lb.this.arn_suffix],
            [".", "RequestCount", ".", "."]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Target Response Time p95"
          region = data.aws_region.current.name
          view   = "timeSeries"
          stat   = "p95"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.this.arn_suffix]
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Stable vs Canary Healthy Hosts"
          region = data.aws_region.current.name
          view   = "timeSeries"
          stat   = "Average"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "HealthyHostCount", "TargetGroup", aws_lb_target_group.stable.arn_suffix, "LoadBalancer", aws_lb.this.arn_suffix, { label = "stable" }],
            [".", ".", ".", aws_lb_target_group.canary.arn_suffix, ".", ".", { label = "canary" }]
          ]
        }
      },
      {
        type   = "text"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          markdown = "### Deployment safety controls\n- ECS deployment circuit breaker enabled with rollback\n- ALB stable/canary weighted target groups\n- GitHub Actions uses OIDC and least-privilege deploy role\n- Burn-rate gate blocks deployment before rollout"
        }
      }
    ]
  })
}

