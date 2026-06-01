#!/bin/bash
# VPS Fix Script - Run on VPS to fix issues
# Usage: bash scripts/vps_fix.sh

echo "================================================================"
echo "VPS FIX SCRIPT"
echo "================================================================"
echo "This script will:"
echo "1. Create missing wallet_features table"
echo "2. Create consumer groups manually"
echo "3. Rebuild and restart containers"
echo "================================================================"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 1. Create wallet_features table
echo ""
echo "1. CREATING WALLET_FEATURES TABLE"
echo "----------------------------------------------------------------"

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

echo -e "${GREEN}✓ wallet_features table created${NC}"

# 2. Create consumer groups manually
echo ""
echo "2. CREATING CONSUMER GROUPS"
echo "----------------------------------------------------------------"

# Define all streams and groups
declare -A STREAMS=(
    ["solana_intel.raw.pending"]="ingestion"
    ["solana_intel.raw.stored"]="parser"
    ["solana_intel.trade.normalized"]="analytics"
    ["solana_intel.trade.enriched"]="aggregation"
    ["solana_intel.trade.enriched"]="alert"
    ["solana_intel.aggregated.features"]="prediction"
    ["solana_intel.predictions"]="ranking"
    ["solana_intel.rankings"]="paper_trading"
    ["solana_intel.dead_letter"]="dlq-processor"
)

for stream in "${!STREAMS[@]}"; do
    group="${STREAMS[$stream]}"
    echo "Creating group '$group' for stream '$stream'..."
    docker compose exec -T redis redis-cli XGROUP CREATE "$stream" "$group" 0 MKSTREAM 2>/dev/null || true
done

echo -e "${GREEN}✓ Consumer groups created${NC}"

# 3. Rebuild and restart containers
echo ""
echo "3. REBUILDING AND RESTARTING CONTAINERS"
echo "----------------------------------------------------------------"

echo "Stopping containers..."
docker compose down

echo "Building containers..."
docker compose build --no-cache

echo "Starting containers..."
docker compose up -d

echo -e "${GREEN}✓ Containers rebuilt and restarted${NC}"

# 4. Wait for services to be ready
echo ""
echo "4. WAITING FOR SERVICES..."
echo "----------------------------------------------------------------"

sleep 10

# 5. Verify
echo ""
echo "5. VERIFICATION"
echo "----------------------------------------------------------------"

echo "Container status:"
docker ps --format "table {{.Names}}\t{{.Status}}"

echo ""
echo "Consumer groups:"
docker compose exec -T redis redis-cli XINFO GROUPS solana_intel.raw.pending 2>/dev/null || echo "No groups yet"

echo ""
echo "Database tables:"
docker compose exec -T postgres psql -U solana_intel -d solana_wallet_intel -c "\dt" 2>/dev/null

echo ""
echo -e "${GREEN}================================================================${NC}"
echo -e "${GREEN}FIX COMPLETE${NC}"
echo -e "${GREEN}================================================================${NC}"
echo ""
echo "Next steps:"
echo "1. Send a test webhook event"
echo "2. Monitor worker logs: docker compose logs -f worker"
echo "3. Check database counts"
