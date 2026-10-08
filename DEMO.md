# Guion de la demo (~15 minutos)

La idea es contar una historia: primero el asistente descubre solo qué hay, después responde preguntas operativas comunes, y al final se rompe algo y lo investiga cruzando métricas y logs. Los prompts están pensados para pegarlos tal cual. Al lado de cada uno anoto qué tools del MCP debería usar, así podés señalarlo en pantalla mientras pasa.

Antes de empezar: stack arriba hace al menos 5 minutos, `./scripts/check.sh` todo en verde, `./scripts/chaos.sh none`, y Grafana abierto en el dashboard "Trámites API - Overview" en otra pestaña para mostrar que lo que dice el modelo coincide.

---

## Acto 1 — Descubrimiento (2 min)

> ¿Qué datasources tiene configurados Grafana y de qué tipo son?

Tools esperadas: `list_datasources`. Debería encontrar VictoriaMetrics (tipo prometheus) y Loki. Buen momento para explicar que VictoriaMetrics se registra como Prometheus y por eso el MCP le habla en PromQL sin nada especial.

> ¿Qué métricas hay disponibles de la app tramites-api? Explicame brevemente qué mide cada una.

Tools: `list_prometheus_metric_names`, `list_prometheus_metric_metadata`. El punto acá es que nadie le dijo los nombres de las métricas: los descubre.

> ¿Qué labels tienen los logs en Loki?

Tools: `list_loki_label_names`, `list_loki_label_values`. Va a encontrar `level`, `endpoint`, `service_name`, `job`, `env`.

---

## Acto 2 — Preguntas operativas de todos los días (4 min)

> ¿Cuántos requests por segundo está atendiendo tramites-api ahora, desglosado por endpoint?

Tools: `query_prometheus` con algo tipo `sum by (endpoint) (rate(http_requests_total[5m]))`. Mostrá la query que armó: es PromQL correcto escrito por el modelo.

> ¿Cuál es la latencia p95 y p99 de cada endpoint en la última media hora?

Tools: `query_prometheus_histogram` o `query_prometheus` con `histogram_quantile`. Comparalo con el panel del dashboard.

> Mostrame los últimos 10 errores en los logs y agrupalos por tipo.

Tools: `query_loki_logs` con `{service_name="tramites-api", level="error"}`. Lo esperable es que encuentre el ruido de fondo (500 con NullPointer) y lo identifique como algo esporádico.

> ¿Qué patrones de log aparecen más seguido?

Tools: `query_loki_patterns`. Esto es lindo de mostrar porque Loki agrupa los logs por estructura y el modelo te devuelve un resumen sin leer línea por línea.

> ¿Qué dashboards hay y qué paneles tiene el de tramites-api?

Tools: `search_dashboards`, `get_dashboard_summary`. Después: "dame el link directo al panel de latencia" → `generate_deeplink`. Hacé click en el link para mostrar que es real.

---

## Acto 3 — Se rompe algo (6 min)

En una terminal (idealmente sin que el público vea cuál modo elegiste):

```bash
./scripts/chaos.sh pagos-errores
```

Esperá 1–2 minutos para que se acumule señal. Después:

> Me están llegando quejas de que el sistema anda mal. ¿Podés revisar si hay algún problema en tramites-api en los últimos 10 minutos?

Esto es lo central de la demo. Lo que debería pasar, sin que le indiques nada más: consulta la tasa de error por endpoint, ve que `/api/pagos` tiene ~45% de 5xx, ve que la latencia de pagos se disparó, va a Loki filtrando por ese endpoint, encuentra "timeout contactando gateway de pagos" con `upstream=gateway-pagos:443`, y concluye que el problema es la dependencia externa y no la app. Si tiene que hacer algunas idas y vueltas, mejor: se ve el razonamiento.

> ¿Desde qué hora exactamente empezó y cuántos usuarios distintos fueron afectados?

Le obliga a hacer una query de rango y a usar LogQL con `| json` y `count by (user_id)` o similar.

Ahora cambiá de falla:

```bash
./scripts/chaos.sh db-lenta
```

> ¿Sigue el mismo problema o cambió algo?

Debería notar que pagos se recuperó y que ahora el problema es `/api/expedientes`: latencia alta, 503 por pool agotado, pool de DB al 90%+, lag del consumer de Kafka creciendo, y en los logs "query lenta en DB" con la query concreta. La gracia es que conecta cuatro señales distintas (latencia, errores, gauge del pool, lag) más los logs, y propone una causa raíz ("la query de expedientes por estado sin índice satura el pool").

Cerrá con:

```bash
./scripts/chaos.sh none
```

---

## Acto 4 — Seguridad y límites (2 min)

> Creame un dashboard nuevo con la tasa de error por endpoint.

Con `--disable-write` activo, la tool `update_dashboard` ni siquiera está disponible, así que el modelo va a decir que no puede. Es el momento de mostrar el compose y explicar: solo lectura, token bearer para los clientes, allowed-hosts, y en producción un service account Viewer en vez de admin. También mencionar que el contenido de los logs entra al contexto del LLM, así que en logs reales hay que pensar en enmascarar datos personales en Alloy antes de que lleguen a Loki.

Si querés mostrar escritura, sacá `--disable-write`, `docker compose up -d mcp-grafana`, reconectá el cliente y repetí el prompt.

---

## Si algo sale mal en vivo

- El modelo dice que no hay datos: chequeá el rango de tiempo que usó; a veces pide "última hora" y el stack tiene 3 minutos. Decile "usá los últimos 15 minutos".
- Loki sin logs: `docker compose logs alloy`. Si Alloy arrancó antes de que existiera el archivo, `docker compose restart alloy`.
- `query_loki_patterns` vacío: el pattern ingester necesita unos minutos de logs para detectar patrones.
- 401 en el cliente: el token del cliente no coincide con `MCP_GRAFANA_SERVER_TOKEN`.
- 403 en el MCP: el `Host` con el que llegás no está en `--allowed-hosts` (pasa si accedés por IP de la LAN en vez de localhost).
