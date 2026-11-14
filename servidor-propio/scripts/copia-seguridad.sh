#!/usr/bin/env bash
# Copia de seguridad de la base de datos de Typebot (flujos, publicaciones,
# usuarios, resultados) en copias/typebot-AAAAMMDD-HHMM.sql.gz, y borrado de
# las copias con más de 30 días.
#
# Programar a diario, por ejemplo en /etc/cron.d/eva:
#   15 3 * * * eva /opt/eva/scripts/copia-seguridad.sh >> /var/log/eva-copias.log 2>&1
#
# La copia contiene los resultados (qué botones pulsó cada visitante y
# cuándo): es información de la empresa, se guarda con permisos 600 y se
# conserva el mismo tiempo que los resultados en la base de datos. Copiar
# también .env aparte: sin ENCRYPTION_SECRET la copia no sirve para
# restaurar credenciales (EVA no guarda ninguna, pero el editor podría).
set -euo pipefail

cd "$(dirname "$0")/.."
DESTINO=${EVA_COPIAS:-copias}
DIAS=${EVA_COPIAS_DIAS:-30}
mkdir -p "$DESTINO"
chmod 700 "$DESTINO"

ARCHIVO="$DESTINO/typebot-$(date +%Y%m%d-%H%M).sql.gz"
docker compose exec -T typebot-db pg_dump -U postgres --no-owner typebot | gzip -9 > "$ARCHIVO"
chmod 600 "$ARCHIVO"

# Una copia vacía o truncada no debe pasar desapercibida.
if [ "$(stat -f %z "$ARCHIVO" 2>/dev/null || stat -c %s "$ARCHIVO")" -lt 10000 ]; then
  echo "AVISO: la copia $ARCHIVO es sospechosamente pequeña" >&2
  exit 1
fi

find "$DESTINO" -name 'typebot-*.sql.gz' -mtime +"$DIAS" -delete
echo "$(date -Iseconds) copia $ARCHIVO ($(du -h "$ARCHIVO" | cut -f1))"

# Restaurar (en un servidor vacío, con el mismo .env):
#   gunzip -c copias/typebot-AAAAMMDD-HHMM.sql.gz | docker compose exec -T typebot-db psql -U postgres typebot
