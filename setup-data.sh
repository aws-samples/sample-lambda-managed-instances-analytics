#!/bin/bash

set -e  # Exit on any error

echo "=========================================="
echo "LMI - Customer Analytics - Data Setup"
echo "Generate Data + Upload to S3"
echo "=========================================="
echo ""

# Prompt for configuration
echo "Configuration Setup"
echo "-------------------"

read -p "Enter AWS Region [us-east-1]: " AWS_REGION
AWS_REGION="${AWS_REGION:-us-east-1}"

read -p "Enter AWS Profile [default]: " AWS_PROFILE
AWS_PROFILE="${AWS_PROFILE:-default}"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)

echo ""
echo "Using Configuration:"
echo "  Region: ${AWS_REGION}"
echo "  Profile: ${AWS_PROFILE}"
echo ""

# Configuration
DATA_FILE="customer_transactions_1M_rows.parquet"

# Step 1: S3 Bucket Configuration
echo "Step 1: S3 Bucket Configuration"
read -p "Enter S3 bucket name (press Enter to create new bucket): " BUCKET_NAME

if [ -z "$BUCKET_NAME" ]; then
    BUCKET_NAME="lmi-customer-analytics-data-${TIMESTAMP}"
    echo "Creating new bucket: ${BUCKET_NAME}"
    aws s3 mb "s3://${BUCKET_NAME}" --region "${AWS_REGION}" --profile "${AWS_PROFILE}"
    echo "✓ Bucket created successfully"
else
    echo "Using existing bucket: ${BUCKET_NAME}"
    if aws s3 ls "s3://${BUCKET_NAME}" --profile "${AWS_PROFILE}" 2>&1 | grep -q 'NoSuchBucket'; then
        echo "Bucket does not exist. Creating: ${BUCKET_NAME}"
        aws s3 mb "s3://${BUCKET_NAME}" --region "${AWS_REGION}" --profile "${AWS_PROFILE}"
        echo "✓ Bucket created successfully"
    else
        echo "✓ Bucket exists"
    fi
fi

# Enable versioning for data protection
echo "Enabling S3 bucket versioning..."
aws s3api put-bucket-versioning \
    --bucket "${BUCKET_NAME}" \
    --versioning-configuration Status=Enabled \
    --region "${AWS_REGION}" \
    --profile "${AWS_PROFILE}"
echo "✓ Bucket versioning enabled"
echo ""

# Step 2: Setup virtual environment and install dependencies
echo "Step 2: Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

source venv/bin/activate
echo "✓ Virtual environment activated"

echo "Installing Python dependencies..."
pip install pyarrow
if [ $? -ne 0 ]; then
    echo "Error: Failed to install pyarrow"
    deactivate
    exit 1
fi
echo "✓ Dependencies installed"
echo ""

# Step 3: Generate data
echo "Step 3: Generating 1M rows of sample data..."
python generate_data_simple.py
if [ $? -ne 0 ]; then
    echo "Error: Failed to generate data"
    deactivate
    exit 1
fi
echo "✓ Data generation complete"

deactivate
echo ""

# Step 4: Upload data to S3
echo "Step 4: Uploading ${DATA_FILE} to S3..."
if aws s3 ls "s3://${BUCKET_NAME}/${DATA_FILE}" --profile "${AWS_PROFILE}" 2>&1 | grep -q "${DATA_FILE}"; then
    echo "✓ File already exists in S3, skipping upload"
else
    aws s3 cp "${DATA_FILE}" "s3://${BUCKET_NAME}/${DATA_FILE}" --profile "${AWS_PROFILE}"
    echo "✓ Data uploaded successfully"
fi
echo ""

echo "=========================================="
echo "Data Setup Complete!"
echo "=========================================="
echo ""
echo "S3 Bucket: ${BUCKET_NAME}"
echo "Data File: ${DATA_FILE}"
echo "S3 URI: s3://${BUCKET_NAME}/${DATA_FILE}"
echo ""
echo "Next Steps:"
echo "  1. Run ./deploy-lambda.sh to build and deploy the Lambda function"
echo "  2. Use the bucket name: ${BUCKET_NAME}"
echo "  3. Use the file name: ${DATA_FILE}"
echo ""
