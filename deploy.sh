#!/bin/bash
echo "🚀 Ice Reign Machine v6.5"

if [[ "$RENDER" == "true" ]]; then
    echo "📦 Render environment"
    cp requirements-render.txt requirements.txt
    pip install -r requirements.txt
    python -c "import asyncio; from main import init_db; asyncio.run(init_db())"
    echo "✅ Build complete"
fi
