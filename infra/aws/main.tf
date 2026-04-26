data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_region" "current" {}

resource "random_id" "suffix" {
  byte_length = 3
}

locals {
  name        = "${var.project_name}-${random_id.suffix.hex}"
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)
  cidr_blocks = ["10.42.1.0/24", "10.42.2.0/24"]
  tags = {
    Project     = var.project_name
    ManagedBy   = "terraform"
    Environment = "demo"
  }
}

resource "aws_vpc" "this" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = merge(local.tags, { Name = local.name })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = local.name })
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.this.id
  cidr_block              = local.cidr_blocks[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true
  tags                    = merge(local.tags, { Name = "${local.name}-public-${count.index + 1}" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = "${local.name}-public" })
}

resource "aws_route" "internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Public HTTP access to the deployment gate demo ALB."
  vpc_id      = aws_vpc.this.id
  tags        = local.tags
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 80
  ip_protocol       = "tcp"
  to_port           = 80
}

resource "aws_vpc_security_group_egress_rule" "alb_all" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "service" {
  name        = "${local.name}-service"
  description = "Allow ALB to reach ECS tasks."
  vpc_id      = aws_vpc.this.id
  tags        = local.tags
}

resource "aws_vpc_security_group_ingress_rule" "service_from_alb" {
  security_group_id            = aws_security_group.service.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = var.container_port
  ip_protocol                  = "tcp"
  to_port                      = var.container_port
}

resource "aws_vpc_security_group_egress_rule" "service_all" {
  security_group_id = aws_security_group.service.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_ecr_repository" "app" {
  name                 = local.name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.tags
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = 14
  tags              = local.tags
}

resource "aws_ecs_cluster" "this" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = local.tags
}

resource "aws_prometheus_workspace" "this" {
  alias = local.name
  tags  = local.tags
}

resource "aws_lb" "this" {
  name               = local.name
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
  tags               = local.tags
}

resource "aws_lb_target_group" "stable" {
  name        = "${local.name}-stable"
  port        = var.container_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.this.id

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 15
    matcher             = "200"
    path                = "/healthz"
    timeout             = 5
    unhealthy_threshold = 2
  }

  tags = local.tags
}

resource "aws_lb_target_group" "canary" {
  name        = "${local.name}-canary"
  port        = var.container_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.this.id

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 15
    matcher             = "200"
    path                = "/healthz"
    timeout             = 5
    unhealthy_threshold = 2
  }

  tags = local.tags
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "forward"
    forward {
      target_group {
        arn    = aws_lb_target_group.stable.arn
        weight = var.stable_weight
      }
      target_group {
        arn    = aws_lb_target_group.canary.arn
        weight = var.canary_weight
      }
      stickiness {
        enabled  = false
        duration = 1
      }
    }
  }
}

resource "aws_ecs_task_definition" "stable" {
  family                   = "${local.name}-stable"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "app"
      image     = var.stable_container_image
      essential = true
      portMappings = [
        {
          containerPort = var.container_port
          hostPort      = var.container_port
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "APP_VERSION", value = "stable" },
        { name = "APP_ROLE", value = "stable" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.app.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "stable"
        }
      }
    }
  ])

  tags = local.tags
}

resource "aws_ecs_task_definition" "canary" {
  family                   = "${local.name}-canary"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "app"
      image     = var.canary_container_image
      essential = true
      portMappings = [
        {
          containerPort = var.container_port
          hostPort      = var.container_port
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "APP_VERSION", value = "canary" },
        { name = "APP_ROLE", value = "canary" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.app.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "canary"
        }
      }
    }
  ])

  tags = local.tags
}

resource "aws_ecs_service" "stable" {
  name            = "${local.name}-stable"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.stable.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.stable.arn
    container_name   = "app"
    container_port   = var.container_port
  }

  network_configuration {
    assign_public_ip = true
    security_groups  = [aws_security_group.service.id]
    subnets          = aws_subnet.public[*].id
  }

  depends_on = [aws_lb_listener.http]
  tags       = local.tags
}

resource "aws_ecs_service" "canary" {
  name            = "${local.name}-canary"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.canary.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.canary.arn
    container_name   = "app"
    container_port   = var.container_port
  }

  network_configuration {
    assign_public_ip = true
    security_groups  = [aws_security_group.service.id]
    subnets          = aws_subnet.public[*].id
  }

  depends_on = [aws_lb_listener.http]
  tags       = local.tags
}

