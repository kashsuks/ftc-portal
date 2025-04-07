import os
from dotenv import load_dotenv
import psycopg2
from main import createDatabaseSchema, connectDb

# Load environment variables
load_dotenv()

# Get database URL from environment
db_url = os.getenv('DATABASE_URL')

if not db_url:
    print("Error: DATABASE_URL not found in .env file")
    exit(1)

# Connect to database
print("Connecting to database...")
if connectDb(db_url):
    print("Connected successfully!")
    
    # Create schema
    print("Creating database schema...")
    if createDatabaseSchema():
        print("Schema created successfully!")
    else:
        print("Failed to create schema")
else:
    print("Failed to connect to database")