import json
import time
import gc
import logging
import os
import tempfile
import boto3
from io import BytesIO
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize S3 client
s3_client = boto3.client('s3')

# Global variables for persistence across invocations
customer_data = None
embedding_model = None
embeddings_cache = {}
initialization_status = {
    'data_loaded': False,
    'model_loaded': False,
    'initialization_time': None,
    'memory_usage_mb': None,
    'dataset_size': 0,
    'errors': []
}

# Import dependencies with fallback handling
try:
    import pandas as pd
    import numpy as np
    logger.info("✅ Successfully imported pandas and numpy from layers")
except ImportError as e:
    logger.error(f"❌ Failed to import pandas/numpy: {e}")
    initialization_status['errors'].append(f"pandas/numpy import failed: {e}")

try:
    from fastembed import TextEmbedding
    logger.info("✅ Successfully imported TextEmbedding from fastembed")
except ImportError as e:
    logger.error(f"❌ Failed to import TextEmbedding: {e}")
    initialization_status['errors'].append(f"TextEmbedding import failed: {e}")

try:
    import psutil
    logger.info("✅ Successfully imported psutil for memory monitoring")
except ImportError as e:
    logger.warning(f"⚠️ psutil not available for memory monitoring: {e}")
    psutil = None

def get_memory_usage():
    """Get current memory usage in MB"""
    if psutil:
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    return None

def load_customer_data_from_s3():
    """
    Load customer data from S3 Parquet file
    Similar to original app.py approach
    """
    global customer_data
    
    logger.info("🔄 Loading customer data from S3...")
    start_time = time.time()
    
    try:
        bucket = os.environ.get('DATA_BUCKET', 'customer-analytics-data')
        key = os.environ.get('FILE_NAME', 'customer_transactions.parquet')
        
        logger.info(f"� Loading data from s3://{bucket}/{key}")
        
        # Download data from S3
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        
        # Load into pandas DataFrame (in-memory)
        customer_data = pd.read_parquet(BytesIO(obj['Body'].read()))
        
        # Calculate memory usage
        data_size_gb = customer_data.memory_usage(deep=True).sum() / (1024**3)
        load_time = time.time() - start_time
        
        logger.info(f"✅ Loaded {len(customer_data):,} rows into memory")
        logger.info(f"💾 Memory usage: {data_size_gb:.2f} GB")
        logger.info(f"⏱️ Load time: {load_time:.2f} seconds")
        
        # Convert date columns to datetime if needed
        if 'transaction_date' in customer_data.columns:
            customer_data['transaction_date'] = pd.to_datetime(customer_data['transaction_date'])
        
        # Optimize data types for memory efficiency
        logger.info("🔧 Optimizing data types...")
        
        # Convert categorical columns
        categorical_columns = ['product_category', 'region', 'customer_segment']
        for col in categorical_columns:
            if col in customer_data.columns:
                customer_data[col] = customer_data[col].astype('category')
        
        # Optimize numeric columns if they exist
        if 'amount' in customer_data.columns:
            customer_data['amount'] = customer_data['amount'].astype('float32')
        
        logger.info(f"✅ Data optimization complete")
        logger.info(f"📊 Final memory usage: {customer_data.memory_usage(deep=True).sum() / (1024**3):.2f} GB")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to load data from S3: {str(e)}")
        import traceback
        traceback.print_exc()
        initialization_status['errors'].append(f"S3 data load failed: {e}")
        return False

def initialize_fastembed_model():
    """Initialize FastEmbed model with all-MiniLM-L6-v2"""
    global embedding_model
    
    logger.info("🔄 Initializing FastEmbed all-MiniLM-L6-v2 model...")
    start_time = time.time()
    
    try:
        # Try to use pre-downloaded model from container image first
        # If that fails, fall back to /tmp directory
        cache_dirs = [
            "/opt/fastembed_models",  # Pre-downloaded in container
            tempfile.mkdtemp(prefix="fastembed_cache_")  # Secure temp directory fallback
        ]
        
        model_initialized = False
        last_error = None
        
        for cache_dir in cache_dirs:
            try:
                logger.info(f"Attempting to load model from: {cache_dir}")
                
                # Initialize with the specific model requested
                embedding_model = TextEmbedding(
                    model_name="sentence-transformers/all-MiniLM-L6-v2",
                    cache_dir=cache_dir
                )
                
                # Test the model with a sample embedding
                test_embedding = list(embedding_model.embed(["test text"]))[0]
                
                initialization_time = time.time() - start_time
                logger.info(f"✅ FastEmbed model initialized from {cache_dir} in {initialization_time:.2f}s")
                logger.info(f"📐 Embedding dimension: {len(test_embedding)}")
                
                model_initialized = True
                break
                
            except Exception as e:
                last_error = e
                logger.warning(f"Failed to load from {cache_dir}: {e}")
                continue
        
        if not model_initialized:
            raise last_error or Exception("Failed to initialize model from any cache directory")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize FastEmbed model: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        initialization_status['errors'].append(f"FastEmbed initialization failed: {e}")
        return False

def generate_embeddings_cache(sample_size: int = 5000):
    """
    Pre-generate embeddings cache for semantic search
    This runs during initialization to avoid API Gateway timeouts
    """
    global customer_data, embedding_model, embeddings_cache
    
    if customer_data is None or embedding_model is None:
        logger.error("Cannot generate embeddings cache: data or model not loaded")
        return False
    
    try:
        cache_key = f"behavior_embeddings_{sample_size}"
        
        logger.info(f"🔄 Pre-generating embeddings cache for {sample_size} users...")
        start_time = time.time()
        
        # Get all unique users
        all_users = customer_data['user_id'].unique()
        
        # Use stratified sampling to ensure diverse user types
        logger.info("📊 Performing stratified sampling by activity level...")
        user_sessions = customer_data.groupby('user_id').size()
        
        # Categorize users by activity level
        high_activity = user_sessions[user_sessions >= user_sessions.quantile(0.75)].index
        medium_activity = user_sessions[(user_sessions >= user_sessions.quantile(0.25)) & 
                                       (user_sessions < user_sessions.quantile(0.75))].index
        low_activity = user_sessions[user_sessions < user_sessions.quantile(0.25)].index
        
        # Sample proportionally from each group (40% high, 40% medium, 20% low)
        n_high = min(len(high_activity), int(sample_size * 0.4))
        n_medium = min(len(medium_activity), int(sample_size * 0.4))
        n_low = min(len(low_activity), int(sample_size * 0.2))
        
        sampled_users = np.concatenate([
            np.random.choice(high_activity, n_high, replace=False),
            np.random.choice(medium_activity, n_medium, replace=False),
            np.random.choice(low_activity, n_low, replace=False)
        ])
        
        logger.info(f"✅ Sampled {len(sampled_users)} users (High: {n_high}, Medium: {n_medium}, Low: {n_low})")
        
        # Helper function to generate behavior description for a single user
        def generate_user_behavior(user_id):
            user_data = customer_data[customer_data['user_id'] == user_id]
            
            # Calculate key metrics
            avg_pages = user_data['pages_visited'].mean()
            avg_products = user_data['products_viewed'].mean()
            conversion_rate = user_data['purchased'].mean()
            avg_session_duration = user_data['session_duration'].mean()
            total_sessions = len(user_data)
            total_purchases = user_data['purchased'].sum()
            avg_purchase_value = user_data[user_data['purchased'] == 1]['purchase_value'].mean() if total_purchases > 0 else 0
            device = user_data['device'].iloc[0]
            country = user_data['country'].iloc[0]
            age_group = user_data['age_group'].iloc[0]
            
            # Build semantic description with key phrases matching common queries
            description_parts = []
            
            # Value/Premium level (for "high-value premium customers")
            if conversion_rate >= 0.4 and avg_purchase_value >= 75:
                description_parts.append("high-value premium customer")
            elif conversion_rate >= 0.2 and avg_purchase_value >= 50:
                description_parts.append("valuable customer")
            elif conversion_rate < 0.05:
                description_parts.append("window shopper")
            
            # Device preference (for "mobile preference", "desktop", "tablet")
            description_parts.append(f"with {device} preference")
            
            # Purchase frequency (for "frequent purchases")
            if conversion_rate >= 0.5:
                description_parts.append("makes frequent purchases")
            elif conversion_rate >= 0.2:
                description_parts.append("regular purchaser")
            elif conversion_rate >= 0.05:
                description_parts.append("occasional buyer")
            else:
                description_parts.append("rarely makes purchases")
            
            # Engagement level (for "highly engaged", "declining engagement")
            if avg_pages >= 10 and avg_session_duration >= 300:
                description_parts.append("highly engaged")
            elif avg_pages >= 5 and avg_session_duration >= 150:
                description_parts.append("moderately engaged")
            elif avg_pages < 3 and avg_session_duration < 100:
                description_parts.append("low engagement")
            
            # Browsing behavior (for "browse frequently", "view many products")
            if avg_products >= 5:
                description_parts.append("views many products")
            elif avg_products >= 2:
                description_parts.append("browses several items")
            
            # Activity/Loyalty (for "loyal customers", "visit regularly", "declining activity")
            if total_sessions >= 15:
                description_parts.append("loyal customer who visits regularly")
            elif total_sessions >= 8:
                description_parts.append("regular visitor")
            elif total_sessions <= 3:
                description_parts.append("low recent activity")
            
            # Conversion quality (for "excellent conversion rates")
            if conversion_rate >= 0.5:
                description_parts.append("with excellent conversion rates")
            elif conversion_rate >= 0.3:
                description_parts.append("with good conversion")
            
            # Session patterns (for "short sessions")
            if avg_session_duration < 100:
                description_parts.append("has short sessions")
            
            # Combine into natural description
            behavior_text = f"A {', '.join(description_parts[:3])}. {' '.join(description_parts[3:])}. From {country}, age {age_group}."
            
            return user_id, behavior_text
        
        # Use ThreadPoolExecutor to parallelize behavior description generation
        logger.info("🔄 Generating behavior descriptions (multithreaded)...")
        behavior_descriptions = []
        user_ids = []
        
        with ThreadPoolExecutor(max_workers=min(20, len(sampled_users))) as executor:
            # Submit all tasks
            future_to_user = {executor.submit(generate_user_behavior, user_id): user_id 
                              for user_id in sampled_users}
            
            # Collect results as they complete
            for future in as_completed(future_to_user):
                try:
                    user_id, behavior_text = future.result()
                    user_ids.append(user_id)
                    behavior_descriptions.append(behavior_text)
                except Exception as e:
                    logger.warning(f"Failed to generate behavior for user: {e}")
        
        logger.info(f"✅ Generated {len(behavior_descriptions)} behavior descriptions")
        
        # Compute embeddings for all behaviors
        logger.info(f"🔄 Computing embeddings for {len(behavior_descriptions)} descriptions...")
        embeddings_start = time.time()
        embeddings = list(embedding_model.embed(behavior_descriptions))
        embeddings_time = time.time() - embeddings_start
        logger.info(f"✅ Computed embeddings in {embeddings_time:.2f}s")
        
        # Cache the results
        embeddings_cache[cache_key] = {
            'behavior_descriptions': behavior_descriptions,
            'user_ids': user_ids,
            'embeddings': embeddings
        }
        
        total_cache_time = time.time() - start_time
        logger.info(f"✅ Embeddings cache generated in {total_cache_time:.2f}s total")
        logger.info(f"💾 Cache contains {len(user_ids)} user embeddings")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to generate embeddings cache: {e}")
        initialization_status['errors'].append(f"Embeddings cache generation failed: {e}")
        return False

def perform_module_initialization():
    """
    Perform all initialization at module level
    This runs once per Lambda container lifecycle
    """
    global customer_data, embedding_model, initialization_status
    
    logger.info("🚀 Starting module-level initialization...")
    total_start_time = time.time()
    
    try:
        # Load customer data from S3
        logger.info("📊 Loading customer dataset from S3...")
        data_start_time = time.time()
        data_success = load_customer_data_from_s3()
        data_time = time.time() - data_start_time
        
        if data_success and customer_data is not None and len(customer_data) > 0:
            initialization_status['data_loaded'] = True
            initialization_status['dataset_size'] = len(customer_data)
            logger.info(f"✅ Customer data loaded in {data_time:.2f}s")
        else:
            raise Exception("Customer data loading failed")
        
        # Initialize FastEmbed model
        logger.info("🤖 Initializing FastEmbed model...")
        model_success = initialize_fastembed_model()
        initialization_status['model_loaded'] = model_success
        
        if not model_success:
            raise Exception("FastEmbed model initialization failed")
        
        # Pre-generate embeddings cache for semantic search
        # Using 5000 users with stratified sampling for best quality
        logger.info("🔄 Pre-generating embeddings cache...")
        cache_start_time = time.time()
        cache_success = generate_embeddings_cache(sample_size=5000)
        cache_time = time.time() - cache_start_time
        
        if cache_success:
            logger.info(f"✅ Embeddings cache pre-generated in {cache_time:.2f}s")
            initialization_status['cache_pregenerated'] = True
        else:
            logger.warning("⚠️ Embeddings cache pre-generation failed, will generate on first search")
            initialization_status['cache_pregenerated'] = False
        
        # Record total initialization time and memory usage
        total_time = time.time() - total_start_time
        initialization_status['initialization_time'] = total_time
        initialization_status['memory_usage_mb'] = get_memory_usage()
        
        logger.info(f"🎉 Module initialization completed in {total_time:.2f}s")
        logger.info(f"📊 Dataset: {len(customer_data):,} records")
        logger.info(f"🤖 Model: {'✅ Loaded' if model_success else '❌ Failed'}")
        logger.info(f"💾 Cache: {'✅ Pre-generated' if initialization_status.get('cache_pregenerated') else '⚠️ Will generate on-demand'}")
        
        if initialization_status['memory_usage_mb']:
            logger.info(f"💾 Memory usage: {initialization_status['memory_usage_mb']:.2f} MB")
        
    except Exception as e:
        logger.warning(f"❌ Module initialization failed: {e}")
        initialization_status['errors'].append(f"Module initialization failed: {e}")
        raise

# ============================================================================
# MODULE-LEVEL INITIALIZATION - RUNS ONCE PER CONTAINER
# ============================================================================
perform_module_initialization()

# ============================================================================
# ANALYTICS FUNCTIONS
# ============================================================================

def perform_customer_analysis(user_id: str) -> Dict[str, Any]:
    """Analyze a specific customer's behavior"""
    global customer_data, embedding_model
    
    if customer_data is None:
        return {"error": "Customer data not initialized"}
    
    # Filter data for the specific customer
    user_data = customer_data[customer_data['user_id'] == user_id]
    
    if len(user_data) == 0:
        return {"error": f"User {user_id} not found"}
    
    # Calculate customer metrics
    total_sessions = len(user_data)
    avg_session_duration = float(user_data['session_duration'].mean())
    total_purchases = int(user_data['purchased'].sum())
    conversion_rate = total_purchases / total_sessions if total_sessions > 0 else 0
    total_spend = float(user_data['purchase_value'].sum())
    
    # Calculate engagement score (0-10 scale)
    # Cap each component to ensure the final score doesn't exceed 10
    engagement_score = (
        min(user_data['pages_visited'].mean() / 5, 1.0) * 0.3 +
        min(user_data['session_duration'].mean() / 300, 1.0) * 0.3 +
        min(user_data['products_viewed'].mean() / 3, 1.0) * 0.2 +
        min(conversion_rate, 1.0) * 0.2
    ) * 10
    
    # Ensure final score is capped at 10.0
    engagement_score = min(engagement_score, 10.0)
    
    # Generate customer segment using FastEmbed model
    segment = "Unknown"
    if embedding_model is not None:
        try:
            behavior_text = (
                f"User visits {user_data['pages_visited'].mean():.1f} pages per session, "
                f"spends {user_data['session_duration'].mean():.1f} seconds, "
                f"views {user_data['products_viewed'].mean():.1f} products, "
                f"has {conversion_rate:.1%} conversion rate"
            )
            
            embedding = list(embedding_model.embed([behavior_text]))[0]
            
            # Simple segmentation based on embedding similarity
            segment_descriptions = [
                "High-value loyal customer",
                "Frequent browser, rare purchaser", 
                "New customer with high potential",
                "At-risk customer, declining engagement",
                "Bargain hunter, price sensitive"
            ]
            segment_embeddings = list(embedding_model.embed(segment_descriptions))
            similarities = [np.dot(embedding, seg_emb) for seg_emb in segment_embeddings]
            segment = segment_descriptions[np.argmax(similarities)]
            
        except Exception as e:
            logger.warning(f"Segmentation failed: {e}")
    
    return {
        "user_id": user_id,
        "metrics": {
            "total_sessions": total_sessions,
            "avg_session_duration": avg_session_duration,
            "total_purchases": total_purchases,
            "conversion_rate": conversion_rate,
            "total_spend": total_spend,
            "engagement_score": float(engagement_score)
        },
        "segment": segment,
        "device_preference": user_data['device'].mode()[0],
        "recent_activity": user_data.sort_values('timestamp', ascending=False).head(5)[
            ['timestamp', 'pages_visited', 'products_viewed', 'purchased', 'purchase_value']
        ].to_dict('records')
    }


def perform_semantic_search(query: str, top_n: int = 5) -> Dict[str, Any]:
    """Search for similar customer behaviors using semantic search"""
    global customer_data, embedding_model, embeddings_cache
    
    if customer_data is None:
        return {"error": "Customer data not initialized"}
    
    if embedding_model is None:
        return {"error": "Embedding model not initialized"}
    
    try:
        # Encode the query
        query_embedding = list(embedding_model.embed([query]))[0]
        
        # Use pre-generated cache with 5000 users (stratified sampling)
        sample_size = 5000
        cache_key = f"behavior_embeddings_{sample_size}"
        
        # Check if cache exists (should be pre-generated during initialization)
        if cache_key not in embeddings_cache:
            logger.warning(f"⚠️ Cache not found, generating on-demand (this will take ~20-25s)...")
            generate_embeddings_cache(sample_size)
        
        # Get cached data
        cached_data = embeddings_cache[cache_key]
        
        # Normalize query embedding for cosine similarity
        query_norm = np.linalg.norm(query_embedding)
        if query_norm > 0:
            query_embedding_normalized = query_embedding / query_norm
        else:
            query_embedding_normalized = query_embedding
        
        # Calculate similarities sequentially (no multithreading)
        similarities = []
        for emb in cached_data['embeddings']:
            # Normalize the embedding
            emb_norm = np.linalg.norm(emb)
            if emb_norm > 0:
                emb_normalized = emb / emb_norm
            else:
                emb_normalized = emb
            # Calculate cosine similarity (dot product of normalized vectors)
            similarity = np.dot(query_embedding_normalized, emb_normalized)
            similarities.append(similarity)
        
        # Get top N results
        top_indices = np.argsort(similarities)[-top_n:][::-1]
        
        results = []
        for idx in top_indices:
            user_id = cached_data['user_ids'][idx]
            description = cached_data['behavior_descriptions'][idx]
            similarity = float(similarities[idx])
            
            # Get user metrics
            user_metrics = perform_customer_analysis(user_id)
            
            results.append({
                "user_id": user_id,
                "description": description,
                "similarity": similarity,
                "metrics": user_metrics.get("metrics", {})
            })
        
        return {
            "query": query,
            "results": results,
            "total_users_searched": len(cached_data['user_ids'])
        }
        
    except Exception as e:
        logger.error(f"Semantic search (no threading) failed: {e}")
        return {"error": f"Semantic search failed: {str(e)}"}

def analyze_cohort(filter_params: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze a cohort of customers based on filter parameters"""
    global customer_data
    
    if customer_data is None:
        return {"error": "Customer data not initialized"}
    
    try:
        # Apply filters
        filtered_data = customer_data.copy()
        
        for param, value in filter_params.items():
            if param in filtered_data.columns:
                filtered_data = filtered_data[filtered_data[param] == value]
        
        if len(filtered_data) == 0:
            return {"error": "No customers match the specified filters"}
        
        # Aggregate metrics
        cohort_size = filtered_data['user_id'].nunique()
        total_sessions = len(filtered_data)
        avg_sessions_per_user = total_sessions / cohort_size
        
        total_purchases = int(filtered_data['purchased'].sum())
        conversion_rate = total_purchases / total_sessions if total_sessions > 0 else 0
        
        total_revenue = float(filtered_data['purchase_value'].sum())
        avg_order_value = total_revenue / total_purchases if total_purchases > 0 else 0
        
        # Distribution analysis
        device_distribution = filtered_data['device'].value_counts(normalize=True).to_dict()
        age_distribution = filtered_data['age_group'].value_counts(normalize=True).to_dict()
        country_distribution = filtered_data['country'].value_counts(normalize=True).to_dict()
        
        return {
            "cohort_metrics": {
                "cohort_size": cohort_size,
                "total_sessions": total_sessions,
                "avg_sessions_per_user": float(avg_sessions_per_user),
                "total_purchases": total_purchases,
                "conversion_rate": float(conversion_rate),
                "total_revenue": total_revenue,
                "avg_order_value": float(avg_order_value)
            },
            "distributions": {
                "device": device_distribution,
                "age_group": age_distribution,
                "country": country_distribution
            },
            "filters_applied": filter_params
        }
        
    except Exception as e:
        logger.error(f"Cohort analysis failed: {e}")
        return {"error": f"Cohort analysis failed: {str(e)}"}

def get_system_info() -> Dict[str, Any]:
    """Get system information and initialization status"""
    global customer_data, embedding_model, initialization_status
    
    current_memory = get_memory_usage()
    
    return {
        "initialization_status": initialization_status,
        "current_memory_mb": current_memory,
        "dataset_info": {
            "loaded": customer_data is not None,
            "size": len(customer_data) if customer_data is not None else 0,
            "columns": list(customer_data.columns) if customer_data is not None else []
        },
        "model_info": {
            "loaded": embedding_model is not None,
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "embedding_dimension": 384
        },
        "cache_info": {
            "embeddings_cached": len(embeddings_cache),
            "cache_keys": list(embeddings_cache.keys())
        }
    }

# ============================================================================
# LAMBDA HANDLER
# ============================================================================

def lambda_handler(event, context):
    """
    Lambda function handler - all initialization already completed at module level
    This function only processes requests using pre-loaded data and models
    """
    try:
        # Handle health check endpoint (GET /health)
        if event.get('httpMethod') == 'GET' and event.get('path', '').endswith('/health'):
            if customer_data is not None and len(customer_data) > 0:
                memory_gb = customer_data.memory_usage(deep=True).sum() / (1024**3)
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': 'http://localhost:8000',
                        'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key',
                        'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
                    },
                    'body': json.dumps({
                        'status': 'healthy',
                        'rows': len(customer_data),
                        'memory_gb': f"{memory_gb:.2f}",
                        'model_loaded': embedding_model is not None,
                        'initialization_time': initialization_status.get('initialization_time')
                    })
                }
            else:
                return {
                    'statusCode': 503,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': 'http://localhost:8000',
                        'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key',
                        'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
                    },
                    'body': json.dumps({
                        'status': 'unhealthy',
                        'error': 'Data not loaded',
                        'errors': initialization_status.get('errors', [])
                    })
                }
        
        # Handle OPTIONS for CORS preflight
        if event.get('httpMethod') == 'OPTIONS':
            return {
                'statusCode': 200,
                'headers': {
                    'Access-Control-Allow-Origin': 'http://localhost:8000',
                    'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key',
                    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
                },
                'body': ''
            }
        
        # Parse request body for POST requests
        if event.get('body'):
            try:
                body = json.loads(event['body'])
            except json.JSONDecodeError:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': 'http://localhost:8000'
                    },
                    'body': json.dumps({"error": "Invalid JSON in request body"})
                }
        else:
            body = event
        
        # Log the incoming request
        request_type = body.get('requestType', 'unknown')
        logger.info(f"📥 Processing request: {request_type}")
        
        # Check initialization status
        if not initialization_status['data_loaded']:
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': 'http://localhost:8000'
                },
                'body': json.dumps({
                    "error": "Customer data not initialized",
                    "initialization_errors": initialization_status['errors']
                })
            }
        
        # Route requests based on type
        if request_type == 'customer_analysis':
            user_id = body.get('userId')
            if not user_id:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': 'http://localhost:8000'
                    },
                    'body': json.dumps({"error": "userId is required for customer analysis"})
                }
            result = perform_customer_analysis(user_id)
            
        elif request_type == 'semantic_search':
            query = body.get('query')
            if not query:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': 'http://localhost:8000'
                    },
                    'body': json.dumps({"error": "query is required for semantic search"})
                }
            top_n = body.get('topN', 5)
            result = perform_semantic_search(query, top_n)
        
            
        elif request_type == 'cohort_analysis':
            filter_params = body.get('filters', {})
            result = analyze_cohort(filter_params)
            
        elif request_type == 'system_info':
            result = get_system_info()
            
        else:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': 'http://localhost:8000'
                },
                'body': json.dumps({
                    "error": f"Unknown request type: {request_type}",
                    "supported_types": ["customer_analysis", "semantic_search", "cohort_analysis", "system_info"]
                })
            }
        
        # Return successful response
        return {
            'statusCode': 200,
            'body': json.dumps(result, default=str),  # Handle datetime serialization
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': 'http://localhost:8000',
                'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key',
                'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Request processing failed: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': 'http://localhost:8000'
            },
            'body': json.dumps({
                "error": f"Internal server error: {str(e)}",
                "request_type": body.get('requestType', 'unknown') if 'body' in locals() else 'unknown'
            })
        }
