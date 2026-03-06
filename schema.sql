-- ICE REIGN PLATFORM SCHEMA
-- Run this in Supabase SQL Editor

-- 1. DEVELOPER SUBSCRIPTIONS (Your Revenue Source)
CREATE TABLE dev_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id TEXT UNIQUE NOT NULL,
    username TEXT,
    email TEXT,
    tier TEXT CHECK(tier IN ('none', 'basic', 'pro', 'enterprise')) DEFAULT 'none',
    status TEXT CHECK(status IN ('active', 'expired', 'cancelled')) DEFAULT 'expired',
    sol_wallet TEXT, -- Dev's wallet for receiving payments
    subscription_start TIMESTAMP,
    subscription_end TIMESTAMP,
    monthly_revenue_sol DECIMAL(20,9) DEFAULT 0,
    total_revenue_sol DECIMAL(20,9) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 2. PAYMENT TRANSACTIONS (Track all revenue)
CREATE TABLE platform_payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dev_id UUID REFERENCES dev_subscriptions(id),
    amount_sol DECIMAL(20,9) NOT NULL,
    amount_usd DECIMAL(10,2),
    payment_type TEXT CHECK(payment_type IN ('subscription', 'distribution_fee', 'priority_fee')),
    tx_signature TEXT UNIQUE,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 3. TOKEN CAMPAIGNS (What gets distributed)
CREATE TABLE token_campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dev_id UUID REFERENCES dev_subscriptions(id),
    token_mint TEXT NOT NULL,
    token_symbol TEXT,
    token_name TEXT,
    total_supply DECIMAL(20,9),
    airdrop_allocation DECIMAL(20,9), -- How much for airdrop
    per_user_amount DECIMAL(20,9),
    eligibility_type TEXT CHECK(eligibility_type IN ('first_come', 'engagement_score', 'random', 'holder_snapshot')),
    eligibility_config JSONB, -- Min messages, account age, etc.
    status TEXT CHECK(status IN ('detected', 'configuring', 'active', 'completed', 'cancelled')) DEFAULT 'detected',
    launch_detected_at TIMESTAMP,
    distribution_start TIMESTAMP,
    distribution_end TIMESTAMP,
    total_recipients INT DEFAULT 0,
    successful_distributions INT DEFAULT 0,
    platform_fee_paid DECIMAL(20,9) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 4. RECIPIENTS (Users who receive airdrops)
CREATE TABLE airdrop_recipients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID REFERENCES token_campaigns(id),
    telegram_id TEXT NOT NULL,
    telegram_username TEXT,
    sol_wallet TEXT NOT NULL,
    engagement_score INT DEFAULT 0, -- Messages, reactions, invites
    status TEXT CHECK(status IN ('pending', 'eligible', 'distributed', 'failed')) DEFAULT 'pending',
    distribution_tx TEXT,
    distributed_at TIMESTAMP,
    UNIQUE(campaign_id, telegram_id)
);

-- 5. GROUP PROTECTION (Anti-spam)
CREATE TABLE protected_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dev_id UUID REFERENCES dev_subscriptions(id),
    telegram_chat_id TEXT UNIQUE NOT NULL,
    group_name TEXT,
    group_username TEXT,
    member_count INT DEFAULT 0,
    messages_scanned INT DEFAULT 0,
    spam_blocked INT DEFAULT 0,
    bots_banned INT DEFAULT 0,
    airdrop_claims INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    added_at TIMESTAMP DEFAULT NOW()
);

-- 6. ENGAGEMENT TRACKING (For eligibility)
CREATE TABLE user_engagement (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id UUID REFERENCES protected_groups(id),
    telegram_id TEXT NOT NULL,
    message_count INT DEFAULT 0,
    reaction_count INT DEFAULT 0,
    invite_count INT DEFAULT 0,
    first_seen TIMESTAMP DEFAULT NOW(),
    last_active TIMESTAMP DEFAULT NOW(),
    UNIQUE(group_id, telegram_id)
);

-- 7. PLATFORM STATS (Your dashboard)
CREATE TABLE platform_stats (
    id SERIAL PRIMARY KEY,
    total_devs INT DEFAULT 0,
    active_campaigns INT DEFAULT 0,
    total_distributed_sol DECIMAL(20,9) DEFAULT 0,
    platform_revenue_sol DECIMAL(20,9) DEFAULT 0,
    spam_blocked_total INT DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_campaigns_status ON token_campaigns(status);
CREATE INDEX idx_recipients_campaign ON airdrop_recipients(campaign_id);
CREATE INDEX idx_payments_dev ON platform_payments(dev_id);
CREATE INDEX idx_engagement_group ON user_engagement(group_id, telegram_id);
