#!/bin/bash
echo "🚀 Ice Reign Machine v6.8"

if [[ "$RENDER" == "true" ]]; then
    echo "📦 Render environment"
    cp requirements-render.txt requirements.txt
    pip install -r requirements.txt
    echo "✅ Build complete"
fi
