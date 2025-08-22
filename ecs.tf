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
        },
        {
          name  = "DYNAMODB_TABLE"
          value = data.terraform_remote_state.story_infra.outputs.story_video_tasks_table_name
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

  network_configuration {
    security_groups  = [data.terraform_remote_state.story_infra.outputs.ecs_tasks_security_group_id]
    subnets          = data.terraform_remote_state.story_infra.outputs.private_subnet_ids
    assign_public_ip = false
  }

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 100
  }

  depends_on = [
    aws_ecs_task_definition.tts_app
  ]

  tags = {
    Name        = "${var.app_name}-ecs-service"
    Environment = var.environment
    Purpose     = "TTS Application ECS Service"
  }
}