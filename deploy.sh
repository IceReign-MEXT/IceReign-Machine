#!/bin/bash
echo "🚀 Ice Reign Machine Deployment"
if [[ "$RENDER" == "true" ]]; then
    echo "📦 Render environment detected"
    cp requirements-render.txt requirements.txt
    pip install -r requirements.txt
    python -c "import asyncio; from main import init_db; asyncio.run(init_db())"
    echo "✅ Deployment complete"
fi
