.PHONY: help build push deploy test clean terraform-init terraform-plan terraform-apply terraform-destroy

# Default target
help:
	@echo "Available commands:"
	@echo "  build           - Build Docker image"
	@echo "  push            - Push Docker image to ECR"
	@echo "  deploy          - Deploy to ECS"
	@echo "  test            - Run tests and linting"
	@echo "  clean           - Clean up Docker images"
	@echo "  terraform-init  - Initialize Terraform"
	@echo "  terraform-plan  - Plan Terraform changes"
	@echo "  terraform-apply - Apply Terraform changes"
	@echo "  terraform-destroy - Destroy Terraform infrastructure"

# Docker commands
build:
	docker build -t story-tts:latest .

push:
	aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $(shell aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com
	docker tag story-tts:latest $(shell aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com/story-tts:latest
	docker push $(shell aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com/story-tts:latest

deploy: push
	aws ecs update-service --cluster story-tts-cluster --service story-tts-service --force-new-deployment

# Testing and linting
test:
	python -m pip install --upgrade pip
	pip install -r requirements.txt
	pip install pytest pytest-cov flake8 black
	flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127
	black --check --diff .
	pytest --cov=./ --cov-report=html

# Cleanup
clean:
	docker rmi story-tts:latest || true
	docker system prune -f

# Terraform commands
terraform-init:
	terraform init

terraform-plan:
	terraform plan

terraform-apply:
	terraform apply -auto-approve

terraform-destroy:
	terraform destroy -auto-approve

# Local development
run-local:
	python main.py

run-docker:
	docker run -p 8000:8000 -e QUEUE_URL=http://localhost:4566/000000000000/story-sqs-queue-tts story-tts:latest

# Health check
health:
	curl -f http://localhost:8000/healthz || echo "Service not healthy"

# Infrastructure info
info:
	@echo "Fetching infrastructure information from story-infra repository..."
	@echo "VPC ID: $(shell cd /Users/shanesepac/Documents/dump/cursor/video-generation/story-infra && terraform output -raw vpc_id)"
	@echo "Private Subnet IDs: $(shell cd /Users/shanesepac/Documents/dump/cursor/video-generation/story-infra && terraform output -raw private_subnet_ids)"
	@echo "ECS Cluster Name: $(shell cd /Users/shanesepac/Documents/dump/cursor/video-generation/story-infra && terraform output -raw ecs_cluster_name)"
	@echo "TTS Queue URL: $(shell cd /Users/shanesepac/Documents/dump/cursor/video-generation/story-infra && terraform output -raw task_queue_urls | jq -r '.TTS')"
