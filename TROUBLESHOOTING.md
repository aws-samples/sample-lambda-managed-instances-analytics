# Troubleshooting

> **For detailed container-specific troubleshooting, see [CONTAINER_IMAGE_CONFIG.md](CONTAINER_IMAGE_CONFIG.md#troubleshooting)**

### Issue: Stack in ROLLBACK_COMPLETE state
**Error**: `Stack:arn:aws:cloudformation:...:stack/lmi-customer-analytics-with-llm/... is in ROLLBACK_COMPLETE state and can not be updated.`

**Solution**: Delete the failed stack and redeploy
```bash
# Delete the failed stack
aws cloudformation delete-stack --stack-name lmi-customer-analytics-with-llm

# Wait for deletion to complete (optional but recommended)
aws cloudformation wait stack-delete-complete --stack-name lmi-customer-analytics-with-llm

# Then redeploy
cd sample-lambda-managed-instances-analytics
./deploy-lambda.sh
```

**Why this happens**: The stack failed during initial creation or an update, CloudFormation rolled back all changes, and now it's stuck in ROLLBACK_COMPLETE. This state exists to preserve error information, but the stack can't be modified - only deleted.

### Issue: Docker/Finch not running
**Solution**: Start Docker Desktop or Finch before running `sam build`
```bash
# Check if running
docker ps  # or: finch ps

# Start Finch if needed
finch vm start
```

### Issue: ECR authentication failed
**Solution**: Re-authenticate with ECR
```bash
aws ecr get-login-password --region us-east-1 | \
    finch login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com
```

### Issue: Lambda timeout during cold start
**Solution**: Timeout is set to 900 seconds (15 minutes), sufficient for loading data and model

### Issue: Out of memory error
**Solution**: Memory is set to 32GB. If needed, adjust `MemorySize` in template.yml

### Issue: CORS errors in UI
**Solution**: CORS headers are configured in Lambda responses. Clear browser cache and hard refresh (Ctrl+Shift+R)

### Issue: FastEmbed model initialization fails
**Solution**: Check CloudWatch logs for specific errors. Model is pre-downloaded during container build.

### Issue: "Read-only file system" error
**Solution**: FastEmbed uses `/tmp` directory for runtime caching. This is already configured.

### Issue: UI not loading or JavaScript errors
**Solution**: Clear browser cache and hard refresh (Ctrl+Shift+R or Cmd+Shift+R)

### Issue: 401 Unauthorized on API calls
**Solution**: Ensure you are signed in via the UI or have a valid Cognito JWT token. Tokens expire after 1 hour — sign in again to get a fresh token. For curl testing, re-run the `initiate-auth` command to get a new token.

### Issue: Cognito hosted UI not redirecting back
**Solution**: Ensure the callback URL in the Cognito User Pool Client matches exactly: `http://localhost:8000`. Check the `CallbackURLs` in template.yml if deploying to a different host.
