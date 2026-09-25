#!/usr/bin/env bash
# Deploy de RAGBot SIN docker (backend con systemd, dashboard estático servido por Apache).
# Uso:  ./deploy-nodocker.sh                 # pull + deps python + migraciones + restart
#       ./deploy-nodocker.sh --install-deps  # además instala paquetes del sistema (apt) y redis
#       ./deploy-nodocker.sh --no-pull       # sin git pull
# Requiere sudo para: apt, instalar la unidad systemd y reiniciar el servicio.
set -euo pipefail

cd "$(dirname "$0")"
APP_DIR="$(pwd)"
APP_USER="${APP_USER:-$(id -un)}"       # usuario que corre el servicio (override: APP_USER=ragbot ./deploy-nodocker.sh)
APP_PORT="${APP_PORT:-8040}"            # puerto local del backend; si está ocupado: APP_PORT=8051 ./deploy-nodocker.sh
BACKEND="$APP_DIR/backend"
ENV_FILE="$BACKEND/.env"
VENV="$BACKEND/.venv"
DOMAIN="subsecretar-ia.salta.gob.ar"
PULL=true
INSTALL_DEPS=false

for arg in "$@"; do
  case "$arg" in
    --no-pull)      PULL=false ;;
    --install-deps) INSTALL_DEPS=true ;;
    -h|--help)      sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 1 ;;
  esac
done

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ── Requisitos ────────────────────────────────────────────────
[ -f "$ENV_FILE" ] || fail "no existe $ENV_FILE (copialo con scp; no va en el repo)"
for var in DATABASE_URL DATABASE_URL_SYNC SECRET_KEY; do
  grep -qE "^${var}=.+" "$ENV_FILE" || fail "$var no está definida en $ENV_FILE"
done
grep -qE "^SECRET_KEY=(cambia_esto|changeme)" "$ENV_FILE" && fail "SECRET_KEY sigue con el valor de ejemplo"
grep -E "^ALLOWED_ORIGINS=" "$ENV_FILE" | grep -q "$DOMAIN" \
  || echo "AVISO: ALLOWED_ORIGINS en $ENV_FILE no incluye https://$DOMAIN"
chmod 600 "$ENV_FILE"

if $INSTALL_DEPS; then
  log "Instalando paquetes del sistema"
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-dev gcc g++ libpq-dev curl redis-server
  sudo systemctl enable --now redis-server
fi
command -v python3 >/dev/null || fail "falta python3"
python3 -c 'import venv, ensurepip' 2>/dev/null || fail "falta python3-venv (usá --install-deps)"

# ── Código ────────────────────────────────────────────────────
if $PULL; then
  log "Actualizando código (git pull --ff-only)"
  git pull --ff-only
fi

# ── Entorno Python ────────────────────────────────────────────
log "Preparando venv y dependencias"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
if grep -qE "^DEFAULT_EMBEDDING_PROVIDER=sentence_transformers" "$ENV_FILE"; then
  "$VENV/bin/pip" install --quiet -r "$BACKEND/requirements.txt"
else
  # sentence-transformers arrastra torch (varios GB) y solo se usa con ese proveedor
  grep -viE "^sentence-transformers" "$BACKEND/requirements.txt" > "$VENV/requirements.filtered.txt"
  "$VENV/bin/pip" install --quiet -r "$VENV/requirements.filtered.txt"
fi

# ── Directorios de datos ──────────────────────────────────────
mkdir -p "$BACKEND"/{uploads,logs} "$BACKEND"/static/{avatars,org_logos,branding}

# ── Migraciones (contra la base remota del .env) ──────────────
log "Corriendo migraciones"
( cd "$BACKEND" && set -a && . "$ENV_FILE" && set +a && PYTHONPATH="$BACKEND" "$VENV/bin/alembic" upgrade head )

# ── Puerto libre (si es nuestro propio servicio no cuenta como ocupado) ──
if ! systemctl is-active --quiet ragbot && ss -ltn "sport = :$APP_PORT" | grep -q LISTEN; then
  ss -ltnp "sport = :$APP_PORT" || true
  fail "el puerto $APP_PORT ya está en uso por otro proceso; elegí otro con APP_PORT=<puerto> (y ajustá docs/apache-ragbot.conf)"
fi

# ── Servicio systemd ──────────────────────────────────────────
log "Instalando y reiniciando servicio ragbot"
sed -e "s#@APP_DIR@#$APP_DIR#g" -e "s#@APP_USER@#$APP_USER#g" -e "s#@APP_PORT@#$APP_PORT#g" docs/ragbot.service \
  | sudo tee /etc/systemd/system/ragbot.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable ragbot >/dev/null
sudo systemctl restart ragbot

# ── Health check ──────────────────────────────────────────────
log "Esperando al backend"
for i in $(seq 1 30); do
  curl -fsS -o /dev/null http://127.0.0.1:$APP_PORT/health && break
  [ "$i" -eq 30 ] && { sudo journalctl -u ragbot -n 60 --no-pager; fail "el backend no respondió (logs arriba)"; }
  sleep 2
done

log "Listo"
systemctl --no-pager --lines=0 status ragbot | head -4
echo
echo "Dashboard: https://$DOMAIN/ragbot/"
echo "Backend en 127.0.0.1:$APP_PORT (el ProxyPass de Apache debe apuntar a ese puerto)"
echo "Si es la primera vez: pegá docs/apache-ragbot.conf en el VirtualHost, ajustá la ruta del Alias"
echo "  y corré:  sudo a2enmod proxy proxy_http headers rewrite && sudo apachectl configtest && sudo systemctl reload apache2"
echo "Logs: sudo journalctl -u ragbot -f"
