# Container Image Configuration

## Overview

The Lambda function is now configured to use **Container Image** deployment instead of ZIP deployment. This allows us to include FastEmbed and all dependencies without hitting the 250MB Lambda size limit.

## Configuration Details

### Lambda Function
- **Package Type**: Image (Container)
- **Base Image**: `public.ecr.aws/lambda/python:3.14`
- **Architecture**: x86_64
- **Memory**: 10GB (10240 MB)
- **Timeout**: 900 seconds (15 minutes)
- **Max Image Size**: 10GB (vs 250MB for ZIP)

### Dependencies Included in Container
```
pandas>=2.0.0
numpy>=1.24.0
pyarrow>=12.0.0
boto3>=1.28.0
fastembed==0.7.4
onnxruntime
psutil>=5.9.0
```

### Files Structure
```
customer_analytics/
├── Dockerfile          # Container build instructions
├── app.py             # Lambda handler with FastEmbed
└── requirements.txt   # All dependencies (no layers needed)
```

## Deployment Process

### Using Automated Scripts (Recommended)

**Step 1: Data Setup**
```bash
chmod +x setup-data.sh deploy-lambda.sh
./setup-data.sh
```

The script will:
1. Create/verify S3 bucket
2. Generate sample data
3. Upload data to S3
4. Display bucket name and file name for next step

**Step 2: Lambda Deployment**
```bash
./deploy-lambda.sh
```

The script will:
1. Authenticate with ECR (Docker/Finch)
2. Verify data exists in S3
3. **Build container image** (using Docker/Finch)
4. **Push image to ECR** (automatically created)
5. Deploy Lambda function with container image

### Manual Deployment
```bash
# Build container image
sam build

# Deploy (will create ECR repository automatically)
sam deploy \
    --stack-name lmi-customer-analytics-with-llm \
    --region us-east-1 \
    --parameter-overrides DataBucketName=<bucket> FileName=<file> \
    --capabilities CAPABILITY_IAM \
    --resolve-s3 \
    --resolve-image-repos
```

## Key Differences from ZIP Deployment

| Feature | ZIP Deployment | Container Image |
|---------|---------------|-----------------|
| Max Size | 250MB | 10GB |
| Layers | Required | Not needed |
| Build Tool | `sam build --use-container` | `sam build` |
| Dependencies | Limited | All included |
| FastEmbed | ❌ Too large | ✅ Fits easily |
| Cold Start | ~5-10s | ~10-20s |
| ECR Required | No | Yes |

## Build Time Expectations

- **First build**: 10-15 minutes (downloads base image, installs all dependencies)
- **Subsequent builds**: 2-5 minutes (uses cached layers)
- **Image size**: ~1.5-2GB (compressed)

## Container Build Process

1. **Base Image**: Pulls `public.ecr.aws/lambda/python:3.14`
2. **Install Dependencies**: Runs `pip install -r requirements.txt`
3. **Copy Code**: Adds `app.py` to container
4. **Push to ECR**: SAM automatically pushes to Amazon ECR
5. **Deploy**: Lambda pulls image from ECR

## ECR Repository

SAM will automatically create an ECR repository:
- **Name**: `lmi-customer-analytics-with-llm-customeranalyticsfunction-<hash>`
- **Region**: Same as deployment region
- **Lifecycle**: Images retained (manual cleanup needed)
- **Authentication**: Handled automatically by deploy-lambda.sh script

## Cleanup

When deleting the stack, also delete the ECR repository:

```bash
# Delete stack
sam delete --stack-name lmi-customer-analytics-with-llm --region us-east-1

# List ECR repositories
aws ecr describe-repositories --region us-east-1

# Delete ECR repository
aws ecr delete-repository \
    --repository-name lmi-customer-analytics-with-llm-customeranalyticsfunction-<hash> \
    --region us-east-1 \
    --force
```

## Troubleshooting

### Issue: Docker/Finch not running
**Solution**: Start Docker Desktop or Finch before running `sam build`

### Issue: ECR authentication failed
**Solution**: The deploy-lambda.sh script handles this automatically, but if needed manually:
```bash
# Get your AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Authenticate Docker
aws ecr get-login-password --region us-east-1 | \
    docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com

# Or authenticate Finch
aws ecr get-login-password --region us-east-1 | \
    finch login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com
```

### Issue: Build takes too long
**Solution**: First build is slow. Subsequent builds use cached layers and are much faster.

### Issue: Image too large
**Solution**: Container images support up to 10GB, so this shouldn't be an issue with current dependencies.

## Advantages of Container Image

✅ **No size limits** - Include FastEmbed, ONNX, and all dependencies
✅ **Consistent environment** - Same container locally and in Lambda
✅ **No layers needed** - All dependencies in one image
✅ **Better for ML** - Ideal for ML models and large libraries
✅ **Version control** - Image tags for versioning

## Disadvantages

⚠️ **Slower cold starts** - ~10-20s vs 5-10s for ZIP
⚠️ **ECR costs** - Storage costs for container images (~$0.10/GB/month)
⚠️ **Build time** - Initial build takes longer
⚠️ **Requires Docker/Finch** - Need container runtime for local builds

## Verification

After deployment, verify the container is working:

```bash
# Get API endpoint
aws cloudformation describe-stacks \
    --stack-name lmi-customer-analytics-with-llm \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
    --output text

# Test health endpoint
curl <api-endpoint>/health

# Test system info (should show FastEmbed loaded)
curl -X POST <api-endpoint> \
    -H 'Content-Type: application/json' \
    -d '{"requestType":"system_info"}'
```

The system_info response should show:
- `model_loaded: true`
- `model_name: "sentence-transformers/all-MiniLM-L6-v2"`
- `embedding_dimension: 384`

## Summary

Container image deployment enables the full AI-powered analytics with FastEmbed that was originally intended for this project. The trade-off is slightly longer cold starts and ECR storage costs, but you get the complete functionality with semantic search and AI-powered customer segmentation.

The deployment scripts (setup-data.sh and deploy-lambda.sh) handle all the complexity including ECR authentication, making the process straightforward and repeatable.
