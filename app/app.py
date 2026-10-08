"""
tramites-api: app de demo que simula un servicio de trámites.

- Expone métricas Prometheus en :8080/metrics (las scrapea VictoriaMetrics).
- Escribe logs JSON en /var/log/app/app.log (los levanta Alloy y los manda a Loki).
- Genera su propio tráfico con un hilo interno, así no hace falta un load generator aparte.
- Tiene modos de "caos" para que en la demo haya algo para investigar:
    POST /chaos?mode=pagos-errores   -> /api/pagos empieza a tirar 502 por timeout del gateway
    POST /chaos?mode=db-lenta        -> /api/expedientes se pone lento y el pool de DB se satura
    POST /chaos?mode=none            -> todo vuelve a la normalidad
"""
import json
import os
import random
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

SERVICE = "tramites-api"
LOG_PATH = os.environ.get("LOG_PATH", "/var/log/app/app.log")
RPS = float(os.environ.get("SIM_RPS", "8"))

REQUESTS = Counter(
    "http_requests_total", "Requests HTTP atendidos", ["endpoint", "method", "status"]
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "Latencia de requests HTTP",
    ["endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
DB_POOL_IN_USE = Gauge("db_pool_connections_in_use", "Conexiones del pool de DB en uso")
DB_POOL_MAX = Gauge("db_pool_connections_max", "Tamaño máximo del pool de DB")
CONSUMER_LAG = Gauge(
    "kafka_consumer_lag", "Lag del consumer de eventos de trámites", ["topic"]
)
CHAOS_MODE = Gauge("demo_chaos_mode", "Modo de caos activo (1 = activo)", ["mode"])

DB_POOL_MAX.set(20)

state = {"mode": "none"}
state_lock = threading.Lock()
log_lock = threading.Lock()

ENDPOINTS = {
    # endpoint: (peso de tráfico, latencia base en segundos)
    "/api/turnos": (5, 0.04),
    "/api/expedientes": (3, 0.08),
    "/api/pagos": (2, 0.12),
}


def log(level, msg, **fields):
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        + f".{int(time.time() * 1000) % 1000:03d}Z",
        "level": level,
        "service": SERVICE,
        "msg": msg,
        **fields,
    }
    line = json.dumps(entry, ensure_ascii=False)
    with log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    print(line, flush=True)


def set_mode(mode):
    with state_lock:
        state["mode"] = mode
    for m in ("pagos-errores", "db-lenta"):
        CHAOS_MODE.labels(mode=m).set(1 if m == mode else 0)
    log("info", f"modo de caos cambiado a '{mode}'", event="chaos_mode_changed")


def simulate_request(endpoint, method="GET"):
    """Simula atender un request: decide latencia, status y loguea."""
    with state_lock:
        mode = state["mode"]

    _, base = ENDPOINTS[endpoint]
    duration = random.expovariate(1 / base)
    status = 200
    trace_id = uuid.uuid4().hex
    user_id = f"u{random.randint(1000, 9999)}"
    level, msg, extra = "info", "request ok", {}

    # Ruido normal: algún 404 y algún 500 esporádico
    r = random.random()
    if r < 0.03:
        status, level, msg = 404, "warn", "recurso no encontrado"
    elif r < 0.035:
        status, level, msg = 500, "error", "error inesperado procesando request"
        extra["error"] = "NullPointer en mapeo de DTO"

    if mode == "pagos-errores" and endpoint == "/api/pagos" and random.random() < 0.45:
        duration = random.uniform(2.5, 5.0)
        status, level = 502, "error"
        msg = "timeout contactando gateway de pagos"
        extra.update(
            error="upstream timeout after 2500ms",
            upstream="gateway-pagos:443",
        )

    if mode == "db-lenta" and endpoint == "/api/expedientes":
        duration += random.uniform(0.6, 2.2)
        if duration > 1.5:
            level, msg = "warn", "query lenta en DB"
            extra.update(
                db_query="SELECT * FROM expedientes WHERE estado = ? ORDER BY fecha",
                db_duration_ms=int((duration - 0.1) * 1000),
            )
        if random.random() < 0.08:
            status, level = 503, "error"
            msg = "no hay conexiones disponibles en el pool de DB"
            extra["error"] = "pool exhausted (20/20)"

    REQUESTS.labels(endpoint=endpoint, method=method, status=str(status)).inc()
    LATENCY.labels(endpoint=endpoint).observe(duration)
    log(
        level,
        msg,
        endpoint=endpoint,
        method=method,
        status=status,
        duration_ms=int(duration * 1000),
        trace_id=trace_id,
        user_id=user_id,
        **extra,
    )
    return status, duration


def traffic_loop():
    endpoints = list(ENDPOINTS)
    weights = [ENDPOINTS[e][0] for e in endpoints]
    while True:
        ep = random.choices(endpoints, weights)[0]
        method = "POST" if ep == "/api/pagos" else random.choice(["GET", "GET", "POST"])
        simulate_request(ep, method)
        time.sleep(random.expovariate(RPS))


def background_gauges():
    lag = 50.0
    while True:
        with state_lock:
            mode = state["mode"]
        if mode == "db-lenta":
            DB_POOL_IN_USE.set(random.randint(17, 20))
            lag = min(lag * 1.15 + random.uniform(20, 60), 25000)
            if random.random() < 0.3:
                log("warn", "consumer atrasado procesando eventos", topic="tramites.eventos", lag=int(lag))
        else:
            DB_POOL_IN_USE.set(random.randint(3, 8))
            lag = max(lag * 0.8, random.uniform(20, 80))
        CONSUMER_LAG.labels(topic="tramites.eventos").set(int(lag))
        time.sleep(5)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/metrics":
            return self._send(200, generate_latest(), CONTENT_TYPE_LATEST)
        if path == "/healthz":
            return self._send(200, '{"status":"ok"}')
        if path in ENDPOINTS:
            status, _ = simulate_request(path, "GET")
            return self._send(status, json.dumps({"status": status}))
        if path == "/chaos":
            return self._send(200, json.dumps(state))
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/chaos":
            mode = parse_qs(parsed.query).get("mode", ["none"])[0]
            if mode not in ("none", "pagos-errores", "db-lenta"):
                return self._send(400, '{"error":"modo invalido"}')
            set_mode(mode)
            return self._send(200, json.dumps({"mode": mode}))
        if parsed.path == "/alert-webhook":
            # Receptor de las notificaciones de Grafana Alerting (contact point de la demo)
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                payload = json.loads(body)
                for a in payload.get("alerts", []):
                    log(
                        "warn" if a.get("status") == "firing" else "info",
                        f"alerta {a.get('status')}: {a.get('labels', {}).get('alertname')}",
                        event="grafana_alert",
                        alert_status=a.get("status"),
                    )
            except ValueError:
                pass
            return self._send(200, '{"status":"ok"}')
        if parsed.path in ENDPOINTS:
            status, _ = simulate_request(parsed.path, "POST")
            return self._send(status, json.dumps({"status": status}))
        self._send(404, '{"error":"not found"}')

    def log_message(self, *args):
        pass  # los access logs los generamos nosotros en JSON


if __name__ == "__main__":
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    set_mode(os.environ.get("CHAOS_MODE", "none"))
    log("info", "tramites-api iniciado", port=8080, sim_rps=RPS)
    threading.Thread(target=traffic_loop, daemon=True).start()
    threading.Thread(target=background_gauges, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
