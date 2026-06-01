#!/bin/bash
# Quick VPS Fix - Creates missing table and consumer groups
# Usage: bash scripts/vps_quick_fix.sh

echo "================================================================"
echo "QUICK VPS FIX"
echo "================================================================"

# 1. Create wallet_features table
echo ""
echo "1. Creating wallet_features table..."

docker compose exec -T postgres psql -U solana_intel -d solana_wallet_intel << 'EOF'
CREATE TABLE IF NOT EXISTS wallet_features (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_address VARCHAR(44) NOT NULL,
    time_window VARCHAR(10) NOT NULL,
    volume FLOAT NOT NULL DEFAULT 0.0,
    tx_frequency BIGINT NOT NULL DEFAULT 0,
    avg_interval FLOAT NOT NULL DEFAULT 0.0,
    token_diversity BIGINT NOT NULL DEFAULT 0,
    buy_count BIGINT NOT NULL DEFAULT 0,
    sell_count BIGINT NOT NULL DEFAULT 0,
    transfer_count BIGINT NOT NULL DEFAULT 0,
    buy_sell_ratio FLOAT NOT NULL DEFAULT 0.0,
    interaction_score FLOAT NOT NULL DEFAULT 0.0,
    features_json JSONB,
    computed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_wallet_features_wallet ON wallet_features (wallet_address);
CREATE INDEX IF NOT EXISTS ix_wallet_features_window ON wallet_features (wallet_address, time_window);
CREATE INDEX IF NOT EXISTS ix_wallet_features_time ON wallet_features (computed_at);
EOF

echo "✓ Done"

# 2. Create consumer groups
echo ""
echo "2. Creating consumer groups..."

for group_info in \
    "solana_intel.raw.pending:ingestion" \
    "solana_intel.raw.stored:parser" \
    "solana_intel.trade.normalized:analytics" \
    "solana_intel.trade.enriched:aggregation" \
    "solana_intel.trade.enriched:alert" \
    "solana_intel.aggregated.features:prediction" \
    "solana_intel.predictions:ranking" \
    "solana_intel.rankings:paper_trading" \
    "solana_intel.dead_letter:dlq-processor"
do
    stream="${group_info%%:*}"
    group="${group_info##*:}"
    echo -n "  $stream -> $group: "
    docker compose exec -T redis redis-cli XGROUP CREATE "$stream" "$group" 0 MKSTREAM 2>&1 | grep -v "OK" || echo "OK"
done

echo ""
echo "✓ Done"

# 3. Restart worker container
echo ""
echo "3. Restarting worker container..."

docker compose restart worker

echo "✓ Done"

# 4. Wait and check
echo ""
echo "4. Waiting 5 seconds..."

sleep 5

# 5. Show status
echo ""
echo "5. Current Status"
echo "----------------------------------------------------------------"

echo "Containers:"
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "(solana_intel|NAMES)"

echo ""
echo "Consumer groups for raw.pending:"
docker compose exec -T redis redis-cli XINFO GROUPS solana_intel.raw.pending 2>/dev/null || echo "None"

echo ""
echo "Recent worker logs:"
docker compose logs worker --tail=10 2>&1 | grep -v "NOGROUP"

echo ""
echo "================================================================"
echo "FIX COMPLETE"
echo "================================================================"
echo ""
echo "Now send a test webhook event to verify the pipeline works."
