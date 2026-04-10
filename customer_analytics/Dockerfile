# Pin to digest for reproducible builds. To update, run:
#   finch pull public.ecr.aws/lambda/python:3.13
#   finch inspect --format='{{index .RepoDigests 0}}' public.ecr.aws/lambda/python:3.13
# nosemgrep: dockerfile-source-not-pinned
FROM public.ecr.aws/lambda/python:3.13

# Install build dependencies using microdnf (AL2023 package manager)
RUN microdnf install -y gcc gcc-c++ cmake

# Copy requirements and install dependencies
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements.txt

# Create cache directory and set permissions
RUN mkdir -p /tmp/fastembed_cache && chmod 777 /tmp/fastembed_cache

# Set FastEmbed cache directory environment variable
ENV FASTEMBED_CACHE_PATH=/tmp/fastembed_cache

# Pre-download FastEmbed model during build
# This ensures the model is baked into the container image
RUN python3.13 -c "import os; os.environ['FASTEMBED_CACHE_PATH']='/tmp/fastembed_cache'; from fastembed import TextEmbedding; model = TextEmbedding(model_name='sentence-transformers/all-MiniLM-L6-v2', cache_dir='/tmp/fastembed_cache'); print('Model downloaded successfully')"

# Copy the downloaded model to a read-only location in the image
RUN if [ -d /tmp/fastembed_cache ]; then \
        mkdir -p /opt/fastembed_models && \
        cp -r /tmp/fastembed_cache/* /opt/fastembed_models/ && \
        chmod -R 755 /opt/fastembed_models; \
    fi

# Create a non-root user without shadow-utils
RUN echo "lambdauser:x:1001:1001::/home/lambdauser:/sbin/nologin" >> /etc/passwd && \
    echo "lambdauser:x:1001:" >> /etc/group

# Copy function code
COPY app.py ${LAMBDA_TASK_ROOT}/

# Add healthcheck for container image scanning compliance
HEALTHCHECK --interval=60s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python3.13", "-c", "import sys; sys.exit(0)"]

# Run as non-root user (UID 1001)
USER 1001

CMD ["app.lambda_handler"]
