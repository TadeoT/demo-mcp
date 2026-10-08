#!/usr/bin/env bash
# Registra el MCP de Grafana en Claude Code (transporte HTTP contra el contenedor)
TOKEN="${MCP_GRAFANA_SERVER_TOKEN:-demo-token-cambiame}"
claude mcp add --transport http grafana http://localhost:8000/mcp \
  --header "Authorization: Bearer ${TOKEN}"
claude mcp list
