#!/usr/bin/env bash
# Verifica que todo el stack esté arriba y que el MCP responda.
set -uo pipefail
TOKEN="${MCP_GRAFANA_SERVER_TOKEN:-demo-token-cambiame}"
ok(){ printf "  \033[32m✔\033[0m %s\n" "$1"; }
ko(){ printf "  \033[31m✘\033[0m %s\n" "$1"; }

echo "Chequeando stack..."
curl -sf localhost:8090/healthz >/dev/null && ok "tramites-api" || ko "tramites-api (:8090)"
curl -sf localhost:8428/health >/dev/null && ok "VictoriaMetrics" || ko "VictoriaMetrics (:8428)"
curl -sf localhost:3100/ready >/dev/null && ok "Loki" || ko "Loki (:3100) — tarda ~15s en estar ready"
curl -sf localhost:3000/api/health >/dev/null && ok "Grafana" || ko "Grafana (:3000)"

n=$(curl -s 'localhost:8428/api/v1/query?query=count(http_requests_total)' | grep -o '"value":\[[^]]*\]' | grep -o '"[0-9]*"\]$' | tr -d '"]')
[[ -n "${n:-}" ]] && ok "VictoriaMetrics tiene $n series de http_requests_total" || ko "VictoriaMetrics todavía sin series de la app"

l=$(curl -s -G localhost:3100/loki/api/v1/labels | grep -c service_name)
[[ "$l" -gt 0 ]] && ok "Loki recibe logs de la app" || ko "Loki todavía sin logs (revisá: docker compose logs alloy)"

init='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"check","version":"0"}}}'
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST localhost:8000/mcp \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -d "$init")
[[ "$code" == "200" ]] && ok "mcp-grafana responde en :8000/mcp" || ko "mcp-grafana devolvió HTTP $code"
nocode=$(curl -s -o /dev/null -w '%{http_code}' -X POST localhost:8000/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d "$init")
[[ "$nocode" == "401" ]] && ok "sin token el MCP rechaza (401)" || ko "sin token el MCP devolvió $nocode (esperaba 401)"
