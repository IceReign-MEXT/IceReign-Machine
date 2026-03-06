#!/bin/bash
echo "🚀 Deploying Ice Reign Machine V5..."

# Install dependencies
pip install -r requirements.txt

# Run database migrations (manual step - run schema.sql in Supabase)

# Start with gunicorn for production
gunicorn -w 4 -b 0.0.0.0:$PORT main:flask_app --daemon

# Or run directly for testing
python main.py

echo "✅ Deployment complete"
