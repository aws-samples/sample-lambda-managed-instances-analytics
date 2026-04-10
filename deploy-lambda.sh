#!/bin/bash

set -e  # Exit on any error

# Parse flags
DEPLOY_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --deploy-only) DEPLOY_ONLY=true ;;
    esac
done

echo "=========================================="
echo "LMI - Customer Analytics - Lambda Deployment"
if [ "$DEPLOY_ONLY" = true ]; then
    echo "Mode: Deploy Only (skipping build)"
else
    echo "SAM Build + Deploy (Container Image)"
fi
echo "=========================================="
echo ""

# Prompt for configuration
echo "Configuration Setup"
echo "-------------------"

read -p "Enter AWS Region [us-east-1]: " AWS_REGION
AWS_REGION="${AWS_REGION:-us-east-1}"

read -p "Enter AWS Profile [default]: " AWS_PROFILE
AWS_PROFILE="${AWS_PROFILE:-default}"

read -p "Enter Stack Name [lmi-customer-analytics-with-llm]: " STACK_NAME
STACK_NAME="${STACK_NAME:-lmi-customer-analytics-with-llm}"

if [ "$DEPLOY_ONLY" = false ]; then

read -p "Enter S3 Bucket Name (where data is stored): " BUCKET_NAME
if [ -z "$BUCKET_NAME" ]; then
    echo "Error: S3 bucket name is required!"
    echo "Please run ./setup-data.sh first to create bucket and upload data"
    exit 1
fi

read -p "Enter Data File Name: " DATA_FILE
DATA_FILE="${DATA_FILE:-customer_transactions_1M_rows.parquet}"

read -p "Enter Subnet IDs for capacity provider (Minimum 1, recommended atleast 2 across AZs for resiliency, comma separated): " SUBNET_IDS
if [ -z "$SUBNET_IDS" ]; then
    echo "Error: At least one Subnet ID is required (comma separated,recommend atleast 2 across AZs for resiliency)!"
    exit 1
fi

read -p "Enter Security Group ID for capacity provider: " SECURITY_GROUP_ID
if [ -z "$SECURITY_GROUP_ID" ]; then
    echo "Error: Security Group ID is required!"
    exit 1
fi

echo ""
echo "Using Configuration:"
echo "  Region: ${AWS_REGION}"
echo "  Profile: ${AWS_PROFILE}"
echo "  Stack Name: ${STACK_NAME}"
echo "  S3 Bucket: ${BUCKET_NAME}"
echo "  Data File: ${DATA_FILE}"
echo "  Subnet IDs: ${SUBNET_IDS}"
echo "  Security Group ID: ${SECURITY_GROUP_ID}"
echo ""

# Verify bucket and file exist
echo "Verifying S3 bucket and data file..."
if ! aws s3 ls "s3://${BUCKET_NAME}/${DATA_FILE}" --profile "${AWS_PROFILE}" 2>&1 | grep -q -F "${DATA_FILE}"; then
    echo "Error: Data file not found in S3!"
    echo "Expected: s3://${BUCKET_NAME}/${DATA_FILE}"
    echo ""
    echo "Please run ./setup-data.sh first to generate and upload data"
    exit 1
fi
echo "✓ Data file verified in S3"
echo ""

# Step 1: Authenticate with ECR (for container push)
echo "Step 1: Authenticating with ECR..."
AWS_ACCOUNT_ID="$(aws sts get-caller-identity --profile "${AWS_PROFILE}" --query Account --output text)"
echo "AWS Account ID: ${AWS_ACCOUNT_ID}"

# Try Docker first, fallback to Finch
if command -v finch &> /dev/null; then
    echo "Using Finch for container operations..."
    aws ecr get-login-password --region "${AWS_REGION}" --profile "${AWS_PROFILE}" | \
        finch login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
    echo "✓ Finch authenticated with ECR"
elif command -v docker &> /dev/null; then
    echo "Using Docker for container operations..."
    aws ecr get-login-password --region "${AWS_REGION}" --profile "${AWS_PROFILE}" | \
        docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
    echo "✓ Docker authenticated with ECR"
else
    echo "Warning: Neither Docker nor Finch found. SAM will attempt to authenticate automatically."
fi
echo ""

# Step 2: Build SAM application with container image
echo "Step 2: Building SAM application as container image..."
echo "Note: This uses Finch/Docker to build the Lambda container with FastEmbed"
echo "Expected time: 10-15 minutes for first build, 2-5 minutes for subsequent builds"
echo ""
sam build
echo "✓ Build complete"
echo ""

# Step 3: Deploy SAM application
echo "Step 3: Deploying SAM application..."
sam deploy \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --profile "${AWS_PROFILE}" \
    --parameter-overrides \
        "DataBucketName=${BUCKET_NAME}" \
        "FileName=${DATA_FILE}" \
        "SubnetIds=${SUBNET_IDS}" \
        "SecurityGroupId=${SECURITY_GROUP_ID}" \
    --capabilities CAPABILITY_IAM \
    --resolve-s3 \
    --resolve-image-repos \
    --no-disable-rollback \
    --no-fail-on-empty-changeset \
    --config-file samconfig.toml \
    --no-confirm-changeset \
    --config-env default

else
    # Deploy-only mode: use samconfig.toml for saved parameters
    echo ""
    echo "Deploying with saved configuration from samconfig.toml..."
    sam deploy \
        --config-file samconfig.toml \
        --resolve-image-repos \
        --region "${AWS_REGION}" \
        --profile "${AWS_PROFILE}" \
        --no-confirm-changeset \
        --no-fail-on-empty-changeset
fi

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Getting stack outputs..."
API_ENDPOINT="$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --profile "${AWS_PROFILE}" \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
    --output text)"

COGNITO_DOMAIN="$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --profile "${AWS_PROFILE}" \
    --query 'Stacks[0].Outputs[?OutputKey==`CognitoDomain`].OutputValue' \
    --output text)"

COGNITO_CLIENT_ID="$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --profile "${AWS_PROFILE}" \
    --query 'Stacks[0].Outputs[?OutputKey==`CognitoClientId`].OutputValue' \
    --output text)"

COGNITO_USER_POOL_ID="$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --profile "${AWS_PROFILE}" \
    --query 'Stacks[0].Outputs[?OutputKey==`CognitoUserPoolId`].OutputValue' \
    --output text)"

# Strip https:// from domain for app.js config
_COGNITO_DOMAIN_BARE="${COGNITO_DOMAIN#https://}"

echo ""
echo "API Endpoint: ${API_ENDPOINT}"
echo "Cognito Domain: ${COGNITO_DOMAIN}"
echo "Cognito Client ID: ${COGNITO_CLIENT_ID}"
echo "Cognito User Pool ID: ${COGNITO_USER_POOL_ID}"
echo ""

echo "=========================================="
echo "Step 4: Configure UI Authentication"
echo "=========================================="
echo ""
echo "Generating ui/config.js with Cognito configuration..."

# Update config.js with Cognito settings (gitignored)
if [ -d "ui" ]; then
    cat > ui/config.js << EOF
// Auto-generated by deploy-lambda.sh — do not commit
var COGNITO_DOMAIN = '${_COGNITO_DOMAIN_BARE}';
var COGNITO_APP_CLIENT = '${COGNITO_CLIENT_ID}';
EOF
    echo "✓ ui/config.js generated with Cognito config"
else
    echo "⚠️  ui/ directory not found. Create ui/config.js manually:"
    echo "    var COGNITO_DOMAIN = '${_COGNITO_DOMAIN_BARE}';"
    echo "    var COGNITO_APP_CLIENT = '${COGNITO_CLIENT_ID}';"
fi
echo ""

echo "=========================================="
echo "Step 5: Create Test User"
echo "=========================================="
echo ""
read -p "Enter email for test user [skip to skip]: " TEST_USER_EMAIL
if [ -n "${TEST_USER_EMAIL}" ] && [ "${TEST_USER_EMAIL}" != "skip" ]; then
    read -s -p "Enter password (min 8 chars, upper+lower+number+symbol): " TEST_USER_PASSWORD
    echo ""
    aws cognito-idp admin-create-user \
        --user-pool-id "${COGNITO_USER_POOL_ID}" \
        --username "${TEST_USER_EMAIL}" \
        --temporary-password 'TempPass1!' \
        --region "${AWS_REGION}" \
        --profile "${AWS_PROFILE}" 2>/dev/null || echo "  (User may already exist)"
    aws cognito-idp admin-set-user-password \
        --user-pool-id "${COGNITO_USER_POOL_ID}" \
        --username "${TEST_USER_EMAIL}" \
        --password "${TEST_USER_PASSWORD}" \
        --permanent \
        --region "${AWS_REGION}" \
        --profile "${AWS_PROFILE}"
    echo "✓ Test user created: ${TEST_USER_EMAIL}"
else
    echo "Skipped. Create a user manually:"
    echo "  aws cognito-idp admin-create-user --user-pool-id ${COGNITO_USER_POOL_ID} --username user@example.com --temporary-password 'TempPass1!' --region ${AWS_REGION}"
    echo "  aws cognito-idp admin-set-user-password --user-pool-id ${COGNITO_USER_POOL_ID} --username user@example.com --password 'YourPass1!' --permanent --region ${AWS_REGION}"
fi
echo ""

echo "=========================================="
echo "Test the API (requires auth token)"
echo "=========================================="
echo ""
echo "Get a token via CLI:"
echo "  TOKEN=\$(aws cognito-idp initiate-auth --auth-flow USER_PASSWORD_AUTH --client-id ${COGNITO_CLIENT_ID} --auth-parameters USERNAME=<email>,PASSWORD='<password>' --query 'AuthenticationResult.IdToken' --output text --region ${AWS_REGION})"
echo ""
_HEALTH_ENDPOINT="${API_ENDPOINT/analytics/health}"
echo "Health Check:"
echo "  curl -H \"Authorization: \$TOKEN\" ${_HEALTH_ENDPOINT}"
echo ""
echo "System Info:"
echo "  curl -X POST ${API_ENDPOINT} -H 'Content-Type: application/json' -H \"Authorization: \$TOKEN\" -d '{\"requestType\":\"system_info\"}'"
echo ""
echo "Customer Analysis:"
echo "  curl -X POST ${API_ENDPOINT} -H 'Content-Type: application/json' -H \"Authorization: \$TOKEN\" -d '{\"requestType\":\"customer_analysis\",\"userId\":\"user_000001\"}'"
echo ""
echo "Semantic Search:"
echo "  curl -X POST ${API_ENDPOINT} -H 'Content-Type: application/json' -H \"Authorization: \$TOKEN\" -d '{\"requestType\":\"semantic_search\",\"query\":\"high value customers\",\"topN\":5}'"
echo ""
echo "=========================================="
echo "Start the UI Server"
echo "=========================================="
echo ""
echo "To start the local UI server, run:"
echo "  cd ui"
echo "  python3 -m http.server 8000"
echo ""
echo "Then open your browser at: http://localhost:8000"
echo "Click 'Sign In' to authenticate, then enter endpoint: ${API_ENDPOINT}"
echo ""
