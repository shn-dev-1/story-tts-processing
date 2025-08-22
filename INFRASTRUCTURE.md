# Infrastructure Documentation

This document describes the Terraform infrastructure and deployment setup for the Story TTS Processing application.

## Overview

The infrastructure is designed to deploy the TTS application to ECS Fargate within a private VPC, using VPC endpoints for secure AWS service communication. The application processes SQS messages to generate TTS audio and aligned subtitles, storing results in S3.

**Important**: This infrastructure automatically fetches required values from the `story-infra` repository's Terraform state, eliminating the need to manually configure many variables.

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   SQS Queue    │    │   ECS Fargate   │    │   S3 Bucket     │
│   (TTS Jobs)   │───▶│   (TTS App)     │───▶│   (Output)      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌─────────────────┐
                       │   DynamoDB      │
                       │   (Metadata)    │
                       └─────────────────┘
```

## Components

### 1. ECR Repository
- **Purpose**: Stores Docker images for the TTS application
- **Features**: 
  - Image scanning enabled
  - Lifecycle policies for cleanup
  - ECS task execution permissions

### 2. ECS Fargate Service
- **Purpose**: Runs the TTS application containers
- **Configuration**:
  - CPU: 1024 (1 vCPU)
  - Memory: 2048 MiB
  - Network mode: awsvpc
  - Health checks via `/healthz` endpoint

### 3. Security Groups
- **TTS App SG**: Allows health checks and outbound traffic
- **VPC Endpoints SG**: Secures AWS service communication
- **ECS Tasks SG**: Referenced from existing infrastructure

### 4. Service Discovery
- **Private DNS namespace**: `story-tts.local`
- **Service registration**: Automatic service discovery within VPC

### 5. CloudWatch Logs
- **Log group**: `/ecs/story-tts`
- **Retention**: 30 days
- **Stream prefix**: `ecs`

## Prerequisites

### Required Infrastructure (from story-infra repository)
The following resources must exist in the `story-infra` repository and be accessible via S3 remote state:
- VPC with private subnets
- ECS cluster (`story-tts-cluster`)
- SQS queue (`story-sqs-queue-tts`)
- S3 bucket for output files
- DynamoDB table for metadata
- IAM roles for ECS tasks
- VPC endpoints for AWS services

### Remote State Configuration
This infrastructure automatically fetches values from the `story-infra` repository:
```hcl
data "terraform_remote_state" "story_infra" {
  backend = "s3"
  config = {
    bucket         = "story-service-terraform-state"
    key            = "terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "story-terraform-lock"
  }
}
```

### Required Variables (Application-specific only)
```hcl
# AWS Configuration
aws_region = "us-east-1"
environment = "production"

# Application Configuration
app_name = "story-tts"
ecr_repository_name = "story-tts"
app_image_tag = "latest"
app_count = 1

# ECS Configuration
cpu = 1024
memory = 2048
app_port = 8000
```

## Deployment

### 1. Initialize Terraform
```bash
terraform init
```

### 2. Configure Variables
Copy `terraform.tfvars.example` to `terraform.tfvars` and update with your values:
```bash
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your application-specific values
```

### 3. Plan Changes
```bash
terraform plan
```

### 4. Apply Infrastructure
```bash
terraform apply
```

### 5. Deploy Application
```bash
# Build and push Docker image
make build
make push

# Deploy to ECS
make deploy
```

## GitHub Actions Workflows

### 1. Deploy Workflow (`deploy.yml`)
- **Trigger**: Push to main branch or PR
- **Actions**:
  - Build Docker image
  - Push to ECR
  - Fetch infrastructure values from AWS
  - Deploy to ECS
  - Comment on PRs

### 2. Terraform Workflow (`terraform.yml`)
- **Trigger**: Changes to Terraform files
- **Actions**:
  - Validate Terraform configuration
  - Plan changes
  - Apply on main branch
  - Comment on PRs

### 3. Test Workflow (`test.yml`)
- **Trigger**: Push to main/develop or PR
- **Actions**:
  - Run linting (flake8, black)
  - Execute tests (pytest)
  - Generate coverage reports

## Environment Variables

### Application Environment Variables
- `QUEUE_URL`: Automatically fetched from SQS queue
- `AWS_REGION`: AWS region for service calls
- `KOKORO_VOICE`: Default voice for TTS generation

### Required AWS Secrets
- `AWS_ACCESS_KEY_ID`: AWS access key
- `AWS_SECRET_ACCESS_KEY`: AWS secret key

## Monitoring and Logging

### CloudWatch Logs
- Application logs are automatically sent to CloudWatch
- Log retention is set to 30 days
- Logs include container stdout/stderr

### Health Checks
- ECS health checks via `/healthz` endpoint
- 30-second intervals with 5-second timeout
- 3 retries before marking unhealthy

### Metrics
- ECS service metrics (CPU, memory, network)
- SQS queue metrics (message count, processing time)
- S3 bucket metrics (storage, requests)

## Security

### Network Security
- All ECS tasks run in private subnets
- No direct internet access
- Communication via VPC endpoints

### IAM Security
- Least privilege access to AWS services
- Task execution role for ECS agent
- Task role for application permissions

### Container Security
- Image scanning enabled in ECR
- Non-root user in container
- Health checks for container monitoring

## Troubleshooting

### Common Issues

#### 1. ECS Service Not Starting
- Check CloudWatch logs for container errors
- Verify IAM role permissions
- Check security group rules

#### 2. SQS Message Processing Issues
- Verify queue URL in environment variables
- Check IAM permissions for SQS access
- Monitor CloudWatch logs for errors

#### 3. S3 Upload Failures
- Verify S3 bucket permissions
- Check VPC endpoint configuration
- Monitor network connectivity

### Debugging Commands
```bash
# Check ECS service status
aws ecs describe-services --cluster story-tts-cluster --services story-tts-service

# View CloudWatch logs
aws logs tail /ecs/story-tts --follow

# Check SQS queue status
aws sqs get-queue-attributes --queue-url $QUEUE_URL --attribute-names All

# Get infrastructure information
make info
```

## Cost Optimization

### Resource Sizing
- Start with 1 vCPU and 2GB memory
- Monitor usage and adjust as needed
- Use Fargate Spot for non-critical workloads

### Storage Optimization
- ECR lifecycle policies for image cleanup
- CloudWatch log retention (30 days)
- S3 lifecycle policies for output files

## Scaling

### Horizontal Scaling
- Adjust `app_count` variable for more instances
- Use Application Auto Scaling for dynamic scaling
- Monitor SQS queue depth for scaling decisions

### Vertical Scaling
- Adjust CPU and memory in task definition
- Monitor CloudWatch metrics for resource usage
- Test performance with different configurations

## Backup and Recovery

### Data Backup
- S3 versioning for output files
- DynamoDB point-in-time recovery
- ECR image tags for rollback

### Disaster Recovery
- Multi-AZ deployment across subnets
- Cross-region S3 replication (if needed)
- Terraform state backup in S3

## Maintenance

### Regular Tasks
- Update base images for security patches
- Review and rotate IAM credentials
- Monitor and adjust resource allocation
- Review CloudWatch logs for issues

### Updates
- Use blue-green deployment for zero-downtime updates
- Test changes in staging environment
- Monitor metrics during and after updates

## Remote State Integration

### Benefits
- **Automatic Configuration**: No need to manually specify VPC IDs, subnet IDs, etc.
- **Consistency**: Always uses the latest values from the infrastructure repository
- **Maintenance**: Changes to infrastructure automatically propagate to this application
- **Reduced Errors**: Eliminates manual configuration mistakes

### How It Works
1. Terraform reads the remote state from S3 backend (`story-service-terraform-state` bucket)
2. Extracts required values (VPC ID, subnet IDs, queue URLs, etc.)
3. Uses these values in the TTS application infrastructure
4. Ensures consistency between infrastructure and application

### Required Permissions
The Terraform execution must have access to:
- Read the remote state file
- Access AWS resources referenced in the remote state
- Create and manage ECR, ECS, and related resources
