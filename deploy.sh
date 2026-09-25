#!/usr/bin/env bash
# Deploy de RAGBot en el servidor (subsecretar-ia.salta.gob.ar/ragbot)
# Uso:  ./deploy.sh            # git pull + build + up
#       ./deploy.sh --no-pull  # usa el código tal como está en el servidor
#       ./deploy.sh --logs     # además sigue los logs del backend al final
set -euo pipefail

cd "$(dirname "$0")"

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE="backend/.env"
DOMAIN="subsecretar-ia.salta.gob.ar"
PULL=true
FOLLOW_LOGS=false

for arg in "$@"; do
  case "$arg" in
    --no-pull) PULL=false ;;
    --logs)    FOLLOW_LOGS=true ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 1 ;;
  esac
done

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ── Requisitos ────────────────────────────────────────────────
command -v docker >/dev/null || fail "docker no está instalado"
docker compose version >/dev/null 2>&1 || fail "falta el plugin 'docker compose'"
[ -f "$ENV_FILE" ] || fail "no existe $ENV_FILE (copialo con scp; no va en el repo)"

# Variables obligatorias en el .env
for var in DATABASE_URL DATABASE_URL_SYNC SECRET_KEY; do
  grep -qE "^${var}=.+" "$ENV_FILE" || fail "$var no está definida en $ENV_FILE"
done
if grep -qE "^SECRET_KEY=(cambia_esto|changeme)" "$ENV_FILE"; then
  fail "SECRET_KEY sigue con el valor de ejemplo"
fi
grep -E "^ALLOWED_ORIGINS=" "$ENV_FILE" | grep -q "$DOMAIN" \
  || echo "AVISO: ALLOWED_ORIGINS en $ENV_FILE no incluye https://$DOMAIN"

# El .env tiene credenciales: que no lo lea cualquiera
chmod 600 "$ENV_FILE"

# ── Código ────────────────────────────────────────────────────
if $PULL; then
  log "Actualizando código (git pull --ff-only)"
  git pull --ff-only
fi

# ── Build y arranque ──────────────────────────────────────────
log "Construyendo y levantando servicios"
docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans

# ── Health check (el backend corre migraciones al arrancar) ───
log "Esperando que el backend esté healthy"
for i in $(seq 1 30); do
  status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' ragbot_backend 2>/dev/null || echo "missing")
  case "$status" in
    healthy) break ;;
    unhealthy|missing)
      docker compose -f "$COMPOSE_FILE" logs --tail=60 backend
      fail "el backend quedó '$status' (revisá los logs de arriba: DB remota, migraciones, .env)" ;;
  esac
  [ "$i" -eq 30 ] && { docker compose -f "$COMPOSE_FILE" logs --tail=60 backend; fail "timeout esperando al backend"; }
  sleep 5
done

# Prueba a través del nginx interno (lo que ve el nginx del host)
if curl -fsS -o /dev/null http://127.0.0.1:8080/; then
  echo "nginx interno OK (127.0.0.1:8080)"
else
  fail "el nginx interno no responde en 127.0.0.1:8080"
fi

log "Listo"
docker compose -f "$COMPOSE_FILE" ps
echo
echo "Dashboard: https://$DOMAIN/ragbot/"
echo "Recordá que el nginx del host necesita el bloque de docs/nginx-host-ragbot.conf"

$FOLLOW_LOGS && docker compose -f "$COMPOSE_FILE" logs -f backend
exit 0
