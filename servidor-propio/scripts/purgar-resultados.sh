#!/usr/bin/env bash
# Plazo de conservación automático: borra los resultados (conversaciones) con
# más de EVA_RETENCION_DIAS días (90 por defecto) y las sesiones de chat sin
# actividad en 7 días.
#
# Es lo que el anexo de protección de datos describe como «tarea manual» en la
# nube de Typebot; aquí deja de ser manual. Programar a diario, después de la
# copia de seguridad:
#   45 3 * * * eva /opt/eva/scripts/purgar-resultados.sh >> /var/log/eva-purga.log 2>&1
#
# Qué contiene un resultado de EVA: fecha, botones pulsados y si llegó al
# final. No hay texto libre, ni IP, ni datos del navegador. Las tablas
# dependientes (Answer, AnswerV2, Log, VisitedEdge, SetVariableHistoryItem)
# se borran en cascada por las claves ajenas del esquema de Typebot.
set -euo pipefail

cd "$(dirname "$0")/.."
DIAS=${EVA_RETENCION_DIAS:-90}
case "$DIAS" in ''|*[!0-9]*) echo "EVA_RETENCION_DIAS debe ser un número de días" >&2; exit 2;; esac

SQL=$(cat <<EOF
\\set ON_ERROR_STOP on
WITH borrados AS (
  DELETE FROM "Result" WHERE "createdAt" < now() - interval '${DIAS} days' RETURNING 1
) SELECT count(*) AS resultados_borrados FROM borrados;
WITH borradas AS (
  DELETE FROM "ChatSession" WHERE "updatedAt" < now() - interval '7 days' RETURNING 1
) SELECT count(*) AS sesiones_borradas FROM borradas;
EOF
)

echo "$(date -Iseconds) purga: resultados de más de ${DIAS} días"
printf '%s\n' "$SQL" | docker compose exec -T typebot-db psql -U postgres -d typebot -q -t -A
