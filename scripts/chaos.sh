#!/usr/bin/env bash
# Uso: ./scripts/chaos.sh [pagos-errores|db-lenta|none|status]
set -euo pipefail
APP_URL="${APP_URL:-http://localhost:8090}"
mode="${1:-status}"
if [[ "$mode" == "status" ]]; then
  curl -s "$APP_URL/chaos"; echo
else
  curl -s -X POST "$APP_URL/chaos?mode=$mode"; echo
fi
