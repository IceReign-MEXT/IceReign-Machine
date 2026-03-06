# Ice Reign Machine V5

Autonomous Airdrop Empire - Telegram bot for token devs.

## Revenue Model
- Subscriptions: Basic/Pro/Enterprise → SOL_MAIN
- Distribution fees: 1% of all airdrops → SOL_MAIN
- Priority fees: Fast distribution → SOL_MAIN

## Deployment
1. Set environment variables in Render dashboard
2. Deploy with `render.yaml`
3. Set Helius webhook to `https://your-app.onrender.com/helius/webhook`

## Security
- `.env` is gitignored - never commit credentials
- Database: Supabase PostgreSQL
- Solana: Helius RPC
