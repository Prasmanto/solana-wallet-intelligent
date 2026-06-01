#!/bin/bash
# Production Health Audit Script
# Run on VPS: bash scripts/vps_health_audit.sh

echo "================================================================"
echo "PRODUCTION HEALTH AND DATA FLOW AUDIT"
echo "================================================================"
echo "Timestamp: $(date -u)"
echo "================================================================"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Check Docker containers
echo ""
echo "1. DOCKER CONTAINER STATUS"
echo "----------------------------------------------------------------"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(solana_intel|NAMES)"

# 2. Check Database Counts
echo ""
echo "2. DATABASE COUNTS"
echo "----------------------------------------------------------------"

RAW_COUNT=$(docker compose exec -T postgres psql -U solana_intel -d solana_wallet_intel -t -c "SELECT COUNT(*) FROM raw_events;" 2>/dev/null | tr -d '[:space:]')
POS_COUNT=$(docker compose exec -T postgres psql -U solana_intel -d solana_wallet_intel -t -c "SELECT COUNT(*) FROM wallet_positions;" 2>/dev/null | tr -d '[:space:]')
METRICS_COUNT=$(docker compose exec -T postgres psql -U solana_intel -d solana_wallet_intel -t -c "SELECT COUNT(*) FROM wallet_metrics;" 2>/dev/null | tr -d '[:space:]')
FEATURES_COUNT=$(docker compose exec -T postgres psql -U solana_intel -d solana_wallet_intel -t -c "SELECT COUNT(*) FROM wallet_features;" 2>/dev/null | tr -d '[:space:]')
PRED_COUNT=$(docker compose exec -T postgres psql -U solana_intel -d solana_wallet_intel -t -c "SELECT COUNT(*) FROM predictions;" 2>/dev/null | tr -d '[:space:]')

echo "raw_events:       ${RAW_COUNT:-0}"
echo "wallet_positions:  ${POS_COUNT:-0}"
echo "wallet_metrics:    ${METRICS_COUNT:-0}"
echo "wallet_features:   ${FEATURES_COUNT:-0}"
echo "predictions:       ${PRED_COUNT:-0}"

# 3. Check Latest Activity
echo ""
echo "3. LATEST ACTIVITY"
echo "----------------------------------------------------------------"

RAW_LATEST=$(docker compose exec -T postgres psql -U solana_intel -d solana_wallet_intel -t -c "SELECT MAX(created_at) FROM raw_events;" 2>/dev/null)
POS_LATEST=$(docker compose exec -T postgres psql -U solana_intel -d solana_wallet_intel -t -c "SELECT MAX(last_processed_at) FROM wallet_positions;" 2>/dev/null)
PRED_LATEST=$(docker compose exec -T postgres psql -U solana_intel -d solana_wallet_intel -t -c "SELECT MAX(created_at) FROM predictions;" 2>/dev/null)

echo "raw_events latest:       ${RAW_LATEST:-NO DATA}"
echo "wallet_positions latest: ${POS_LATEST:-NO DATA}"
echo "predictions latest:      ${PRED_LATEST:-NO DATA}"

# 4. Check Redis Streams
echo ""
echo "4. REDIS STREAMS"
echo "----------------------------------------------------------------"

for stream in "solana_intel.raw.pending" "solana_intel.raw.stored" "solana_intel.trade.normalized" "solana_intel.trade.enriched" "solana_intel.aggregated.features" "solana_intel.predictions" "solana_intel.rankings"; do
    COUNT=$(docker compose exec -T redis redis-cli XLEN "$stream" 2>/dev/null || echo "0")
    echo "$stream: $COUNT"
done

# 5. Check Worker Logs
echo ""
echo "5. WORKER LOGS (last 50 lines)"
echo "----------------------------------------------------------------"
docker compose logs worker --tail=50 2>/dev/null | tail -30

# 6. Summary
echo ""
echo "================================================================"
echo "SUMMARY"
echo "================================================================"

# Determine status
if [ "${RAW_COUNT:-0}" -gt 0 ] && [ "${POS_COUNT:-0}" -gt 0 ] && [ "${METRICS_COUNT:-0}" -gt 0 ] && [ "${PRED_COUNT:-0}" -gt 0 ]; then
    echo -e "${GREEN}✅ FULLY ACTIVE${NC} - All layers processing"
elif [ "${RAW_COUNT:-0}" -gt 0 ] && [ "${POS_COUNT:-0}" -gt 0 ]; then
    echo -e "${YELLOW}⚠️  PARTIALLY ACTIVE${NC} - Data pipeline only"
elif [ "${RAW_COUNT:-0}" -gt 0 ]; then
    echo -e "${YELLOW}⚠️  INGESTION ONLY${NC} - Events received but not processed"
else
    echo -e "${RED}❌ IDLE${NC} - No data in system"
fi

echo ""
echo "================================================================"
