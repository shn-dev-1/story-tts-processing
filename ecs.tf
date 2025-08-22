# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "tts_app" {
  name              = "/ecs/story-tts"
  retention_in_days = 30

  tags = {
    Name        = "${var.app_name}-log-group"
    Environment = var.environment
    Purpose     = "TTS Application Logs"
  }
}

# ECS Task Definition
resource "aws_ecs_task_definition" "tts_app" {
  family                   = "${var.app_name}-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = data.terraform_remote_state.story_infra.outputs.ecs_task_execution_role_arn
  task_role_arn            = data.terraform_remote_state.story_infra.outputs.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name  = "${var.app_name}-container"
      image = "${aws_ecr_repository.tts_app.repository_url}:${var.app_image_tag}"

      portMappings = [
        {
          containerPort = var.app_port
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "QUEUE_URL"
          value = data.terraform_remote_state.story_infra.outputs.task_queue_urls["TTS"]
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        },
        {
          name  = "KOKORO_VOICE"
          value = "af_heart"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.tts_app.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:${var.app_port}/healthz || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      essential = true
    }
  ])

  tags = {
    Name        = "${var.app_name}-task-definition"
    Environment = var.environment
    Purpose     = "TTS Application Task Definition"
  }
}

# ECS Service
resource "aws_ecs_service" "tts_app" {
  name            = "${var.app_name}-service"
  cluster         = data.terraform_remote_state.story_infra.outputs.ecs_cluster_name
  task_definition = aws_ecs_task_definition.tts_app.arn
  desired_count   = var.app_count
  launch_type     = "FARGATE"

  network_configuration {
    security_groups  = [aws_security_group.tts_app.id]
    subnets          = data.terraform_remote_state.story_infra.outputs.private_subnet_ids
    assign_public_ip = false
  }

  # Enable service discovery for internal communication
  service_registries {
    registry_arn = aws_service_discovery_service.tts_app.arn
  }

  depends_on = [
    aws_ecs_task_definition.tts_app,
    aws_service_discovery_service.tts_app
  ]

  tags = {
    Name        = "${var.app_name}-ecs-service"
    Environment = var.environment
    Purpose     = "TTS Application ECS Service"
  }
}

# Service Discovery Namespace
resource "aws_service_discovery_private_dns_namespace" "tts_app" {
  name        = "${var.app_name}.local"
  description = "Private DNS namespace for TTS application"
  vpc         = data.terraform_remote_state.story_infra.outputs.vpc_id

  tags = {
    Name        = "${var.app_name}-service-discovery-namespace"
    Environment = var.environment
    Purpose     = "TTS Application Service Discovery"
  }
}

# Service Discovery Service
resource "aws_service_discovery_service" "tts_app" {
  name = "${var.app_name}-service"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.tts_app.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = {
    Name        = "${var.app_name}-service-discovery-service"
    Environment = var.environment
    Purpose     = "TTS Application Service Discovery"
  }
}
