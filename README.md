# Demo: Grafana MCP leyendo métricas y logs

Un entorno local para mostrar cómo un asistente (Claude, Copilot, Cursor, lo que sea que hable MCP) consulta Grafana en lenguaje natural: arma PromQL contra VictoriaMetrics, LogQL contra Loki, y cruza las dos cosas para investigar un incidente.

```
 tramites-api ──/metrics──▶ VictoriaMetrics ──┐
      │                                       ├──▶ Grafana ◀── mcp-grafana (:8000/mcp) ◀── Claude / IDE
      └──app.log──▶ Alloy ──▶ Loki ───────────┘
```

| Servicio | Puerto | Para qué |
|---|---|---|
| tramites-api | 8090 | App falsa de trámites (turnos, expedientes, pagos). Genera tráfico solo y tiene modos de caos. |
| VictoriaMetrics | 8428 | Métricas. Registrada en Grafana como datasource tipo Prometheus. |
| Loki | 3100 | Logs, con pattern ingester activado. |
| Alloy | 12345 | Tailea el log JSON de la app, saca `level`/`endpoint` como labels y `trace_id` como structured metadata. |
| Grafana | 3000 | admin / admin. Datasources y dashboard "Trámites API - Overview" ya provisionados. |
| mattermost-mock | 8065 | Mock de Mattermost: recibe los webhooks de Grafana Alerting y los muestra como chat en http://localhost:8065. Las alertas están en `grafana/provisioning/alerting/`. |
| mcp-grafana | 8000 | Servidor MCP oficial de Grafana, streamable-http en `/mcp`, solo lectura y con token. |

## Levantarlo

```bash
cp .env.example .env        # opcional, los defaults funcionan
docker compose up -d --build
# esperá ~30s y:
./scripts/check.sh
```

`check.sh` verifica que cada pieza esté arriba, que VictoriaMetrics ya tenga series, que Loki ya reciba logs, que el MCP conteste el `initialize` con token y que lo rechace sin token.

Dejalo corriendo unos 5–10 minutos antes de la demo para que haya historia en los gráficos.

## Conectar un cliente MCP

**Claude Code** (lo más directo):

```bash
./clients/claude-code.sh
# equivale a:
claude mcp add --transport http grafana http://localhost:8000/mcp --header "Authorization: Bearer demo-token-cambiame"
```

**Claude Desktop**: copiá el bloque de `clients/claude_desktop_config.json` a tu `claude_desktop_config.json`. Esa variante corre el MCP por stdio en un contenedor efímero enganchado a la red del compose, porque Desktop maneja stdio de forma nativa.

**VS Code**: `clients/vscode-mcp.json` va en `.vscode/mcp.json`.

**MCP Inspector** (para mostrar las tools "en crudo", sin LLM): `npx @modelcontextprotocol/inspector`, transporte Streamable HTTP, URL `http://localhost:8000/mcp`, header `Authorization: Bearer demo-token-cambiame`.

## Modos de caos

```bash
./scripts/chaos.sh pagos-errores   # ~45% de /api/pagos devuelve 502 por timeout del gateway, latencia 2.5–5s
./scripts/chaos.sh db-lenta        # /api/expedientes se pone lento, pool de DB al 90-100%, sube el lag de Kafka, algunos 503
./scripts/chaos.sh none            # vuelve a la normalidad
./scripts/chaos.sh status
```

Siempre hay un poco de ruido de fondo (≈3% de 404 y ≈0,5% de 500 con "NullPointer en mapeo de DTO") para que el modelo tenga que distinguir señal de ruido.

El guion paso a paso está en [DEMO.md](DEMO.md).

## Notas de seguridad (vale la pena mencionarlas en la demo)

- El MCP corre con `--disable-write`: puede leer dashboards, consultar datasources y alertas, pero no crear ni modificar nada. Si querés mostrar que también puede crear un dashboard, sacá esa línea del compose y hacé `docker compose up -d mcp-grafana`.
- `MCP_GRAFANA_SERVER_TOKEN` obliga a los clientes a mandar `Authorization: Bearer`. Sin eso, el MCP queda abierto a cualquiera que llegue al puerto.
- `--allowed-hosts` limita el header `Host` para cortar ataques de DNS rebinding desde el navegador.
- Para la demo el MCP usa usuario/contraseña de admin. En serio, creá un service account con rol **Viewer** (o RBAC fino: `datasources:query` sobre los UIDs que correspondan) y pasalo en `GRAFANA_SERVICE_ACCOUNT_TOKEN`. En Kubernetes se puede montar como Secret y usar `GRAFANA_SERVICE_ACCOUNT_TOKEN_FILE`, que se relee en cada request y soporta rotación sin reiniciar.
- Lo que el modelo lee de los logs entra a su contexto. Si los logs tienen datos personales (DNI, CUIT, mails), eso viaja al proveedor del LLM. Para logs reales conviene enmascarar en Alloy antes de Loki.

## Apagar

```bash
docker compose down        # conserva datos
docker compose down -v     # borra todo, incluidos los volúmenes
```

## Llevarlo al stack real

VictoriaMetrics funciona con las tools de Prometheus del MCP porque habla PromQL/MetricsQL; alcanza con que el datasource en Grafana sea tipo `prometheus`. Si tenés Tempo como datasource, el MCP también expone `find_slow_requests` (vía Sift, que es de Grafana Cloud). En Kubernetes está el chart oficial `grafana/grafana-mcp` del repo de helm-charts de Grafana.
