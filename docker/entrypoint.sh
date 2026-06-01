#!/bin/bash
set -e

echo "=== Solana Wallet Intel ==="
echo "Role: ${SERVICE_ROLE:-api}"
echo "Env:  ${APP_ENV:-development}"

# Wait for dependent services
wait_for_service() {
    local host=$1 port=$2 name=$3
    echo "Waiting for $name ($host:$port)..."
    until pg_isready -h "$host" -p "$port" -q 2>/dev/null || \
          python3 -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(($host,$port)); s.close()" 2>/dev/null; do
        sleep 1
    done
    echo "$name is ready."
}

# Generic TCP check (works for both postgres and redis)
check_tcp() {
    local host=$1 port=$2 name=$3
    echo "Waiting for $name ($host:$port)..."
    for i in $(seq 1 30); do
        if python3 -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('${host}',${port})); s.close()" 2>/dev/null; then
            echo "$name is ready."
            return 0
        fi
        sleep 1
    done
    echo "ERROR: $name not available after 30s"
    exit 1
}

# Wait for infrastructure
check_tcp "${POSTGRES_HOST:-localhost}" "${POSTGRES_PORT:-5432}" "PostgreSQL"
check_tcp "${REDIS_HOST:-localhost}" "${REDIS_PORT:-6379}" "Redis"

# Run database migrations
echo "Running migrations..."
alembic upgrade head 2>/dev/null || echo "No migrations to apply or alembic not configured."

# Dispatch by role
case "${SERVICE_ROLE:-api}" in
    api)
        echo "Starting FastAPI server..."
        exec uvicorn app.main:app \
            --host 0.0.0.0 \
            --port 8000 \
            --reload \
            --log-level "$(echo ${LOG_LEVEL:-info} | tr '[:upper:]' '[:lower:]')" \
            --access-log
        ;;
    worker)
        echo "Starting async worker..."
        exec python3 -m app.workers.orchestrator
        ;;
    *)
        echo "Unknown SERVICE_ROLE: ${SERVICE_ROLE}"
        exit 1
        ;;
esac
