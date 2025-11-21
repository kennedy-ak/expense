"""
Test script to verify PostgreSQL database connection
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://kennedy:Ybok7619.@157.173.118.68:5432/fintech_db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

def test_connection():
    """Test the database connection"""
    try:
        with app.app_context():
            # Try to execute a simple query
            result = db.session.execute(db.text('SELECT 1'))
            print("✅ Database connection successful!")
            print(f"✅ Connected to: {app.config['SQLALCHEMY_DATABASE_URI'].split('@')[1]}")
            return True
    except Exception as e:
        print(f"❌ Database connection failed!")
        print(f"❌ Error: {str(e)}")
        return False

if __name__ == '__main__':
    test_connection()
