# AI-Powered Customer Analytics UI

Web-based user interface for the AI-powered customer analytics Lambda function with FastEmbed semantic search capabilities.

## Features

- **Customer Analysis**: Analyze individual customer behavior, engagement scores, and purchase patterns
- **Semantic Search**: AI-powered search to find similar customers using natural language queries
- **Cohort Analysis**: Analyze customer segments with filters for device, country, and age group
- **System Information**: View initialization status, dataset info, and AI model details

## Running the UI

1. Start a local HTTP server:
   ```bash
   cd ui
   python3 -m http.server 8000
   ```

2. Open your browser at: http://localhost:8000

3. Enter your API endpoint URL (from deployment output)

4. Click "Test Connection" to verify the connection

## API Request Format

The UI sends POST requests to the Lambda function with the following format:

### Customer Analysis
```json
{
  "requestType": "customer_analysis",
  "userId": "user_12345"
}
```

### Semantic Search
```json
{
  "requestType": "semantic_search",
  "query": "high value customers",
  "topN": 5
}
```

### Cohort Analysis
```json
{
  "requestType": "cohort_analysis",
  "filters": {
    "device": "mobile",
    "country": "USA",
    "age_group": "25-34"
  }
}
```

### System Info
```json
{
  "requestType": "system_info"
}
```

## Stopping the Server

Press `Ctrl+C` in the terminal where the HTTP server is running.
