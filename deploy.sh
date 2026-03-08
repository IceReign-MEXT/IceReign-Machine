#!/bin/bash
echo "🔥 Ice Reign Machine v7.0 - Production Build"

if [[ "$RENDER" == "true" ]]; then
    echo "📦 Render Environment Detected"
    
    # Use production requirements
    cp requirements.txt requirements-render.txt 2>/dev/null || true
    
    # Install dependencies
    pip install -r requirements.txt
    
    # Initialize database
    python -c "
import os
os.environ['DATABASE_URL'] = os.getenv('DATABASE_URL', '')
from main import init_database
init_database()
print('✅ Database ready')
" 2>/dev/null || echo "⚠️ DB init will run on startup"
    
    echo "✅ Build Complete - System Ready"
fi
