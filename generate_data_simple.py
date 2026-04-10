import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime, timedelta
import random

def generate_sample_data(num_rows=1_000_000, output_file='customer_transactions_1M_rows.parquet'):
    """
    Generate sample customer behavioral data for AI-powered analytics
    Schema matches app.py expectations for FastEmbed analysis
    """
    print(f"Generating {num_rows:,} sample customer sessions...")
    
    # Set random seed for reproducibility
    random.seed(42)
    
    # Generate unique user IDs (100k unique users with multiple sessions each)
    num_users = 100_000
    user_ids = [f"user_{i:06d}" for i in range(num_users)]
    
    # Configuration
    devices = ['mobile', 'desktop', 'tablet']
    age_groups = ['18-24', '25-34', '35-44', '45-54', '55+']
    countries = ['USA', 'UK', 'Canada', 'Germany', 'France', 'Japan', 'Australia', 'India', 'Brazil', 'Mexico']
    
    # Generate data in chunks to manage memory
    chunk_size = 100_000
    writer = None
    schema = None
    
    for i in range(0, num_rows, chunk_size):
        current_chunk_size = min(chunk_size, num_rows - i)
        print(f"Generating chunk {i//chunk_size + 1}/{(num_rows-1)//chunk_size + 1}...")
        
        # Generate data lists
        chunk_user_ids = [random.choice(user_ids) for _ in range(current_chunk_size)]  # nosec B311
        
        # Generate timestamps (last 2 years)
        chunk_timestamps = [
            (datetime.now() - timedelta(days=random.randint(0, 730))).isoformat()  # nosec B311
            for _ in range(current_chunk_size)
        ]
        
        # Session duration (30 seconds to 30 minutes)
        chunk_session_duration = [random.randint(30, 1800) for _ in range(current_chunk_size)]  # nosec B311
        
        # Pages visited (1-20 pages)
        chunk_pages_visited = [random.randint(1, 20) for _ in range(current_chunk_size)]  # nosec B311
        
        # Products viewed (0-10 products)
        chunk_products_viewed = [random.randint(0, 10) for _ in range(current_chunk_size)]  # nosec B311
        
        # Purchased (boolean - 10% conversion rate)
        chunk_purchased = [random.random() < 0.1 for _ in range(current_chunk_size)]  # nosec B311
        
        # Purchase value (0 if not purchased, 10-500 if purchased)
        chunk_purchase_value = [
            round(random.uniform(10, 500), 2) if purchased else 0.0  # nosec B311
            for purchased in chunk_purchased
        ]
        
        # Device type
        chunk_device = [random.choice(devices) for _ in range(current_chunk_size)]  # nosec B311
        
        # Age group
        chunk_age_group = [random.choice(age_groups) for _ in range(current_chunk_size)]  # nosec B311
        
        # Country
        chunk_country = [random.choice(countries) for _ in range(current_chunk_size)]  # nosec B311
        
        # Create PyArrow table
        table = pa.table({
            'user_id': chunk_user_ids,
            'timestamp': chunk_timestamps,
            'session_duration': chunk_session_duration,
            'pages_visited': chunk_pages_visited,
            'products_viewed': chunk_products_viewed,
            'purchased': chunk_purchased,
            'purchase_value': chunk_purchase_value,
            'device': chunk_device,
            'age_group': chunk_age_group,
            'country': chunk_country
        })
        
        # Write to parquet file
        if writer is None:
            schema = table.schema
            writer = pq.ParquetWriter(output_file, schema, compression='snappy')
        
        writer.write_table(table)
    
    # Close writer
    if writer:
        writer.close()
    
    print(f"✓ Generated {num_rows:,} rows")
    print(f"✓ Saved to {output_file}")
    
    # Read back for statistics
    print("\nReading file for statistics...")
    table = pq.read_table(output_file)
    
    print("\nSample Statistics:")
    print(f"Total sessions: {len(table):,}")
    print(f"File: {output_file}")
    
    # Calculate some basic stats
    user_ids_list = table['user_id'].to_pylist()
    purchased_list = table['purchased'].to_pylist()
    purchase_values = table['purchase_value'].to_pylist()
    
    unique_users = len(set(user_ids_list))
    total_purchases = sum(purchased_list)
    total_revenue = sum(purchase_values)
    conversion_rate = (total_purchases / len(table)) * 100
    
    print(f"Unique users: {unique_users:,}")
    print(f"Total purchases: {total_purchases:,}")
    print(f"Conversion rate: {conversion_rate:.2f}%")
    print(f"Total revenue: ${total_revenue:,.2f}")
    print(f"Avg order value: ${total_revenue/total_purchases:.2f}" if total_purchases > 0 else "N/A")
    
    # Show schema
    print("\nSchema:")
    for field in table.schema:
        print(f"  - {field.name}: {field.type}")

if __name__ == '__main__':
    # Generate 1M rows for analysis
    generate_sample_data(num_rows=1_000_000, output_file='customer_transactions_1M_rows.parquet')
