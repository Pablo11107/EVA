#!/usr/bin/env bash
# Rellena en .env los secretos que no deben inventarse a mano:
#   - ENCRYPTION_SECRET: 32 caracteres aleatorios (clave de cifrado de Typebot)
#   - POSTGRES_PASSWORD y la misma contraseña dentro de DATABASE_URL
# Solo escribe los que estén vacíos o con el valor de ejemplo: ejecutarlo dos
# veces no cambia nada, y nunca rota una clave existente (ENCRYPTION_SECRET
# no se puede rotar sin perder lo cifrado).
set -euo pipefail

cd "$(dirname "$0")/.."
ENV=.env
[ -f "$ENV" ] || { cp .env.ejemplo "$ENV"; echo "Creado $ENV a partir de .env.ejemplo"; }
chmod 600 "$ENV"

aleatorio() { openssl rand -base64 "$1" | tr -d '\n=' | tr '+/' 'Aa' | head -c "$2"; }

if grep -q '^ENCRYPTION_SECRET=$' "$ENV"; then
  CLAVE=$(aleatorio 32 32)
  sed -i.bak "s#^ENCRYPTION_SECRET=\$#ENCRYPTION_SECRET=${CLAVE}#" "$ENV"
  echo "ENCRYPTION_SECRET generado"
fi

if grep -q '^POSTGRES_PASSWORD=$' "$ENV"; then
  PASS=$(aleatorio 36 40)
  sed -i.bak "s#^POSTGRES_PASSWORD=\$#POSTGRES_PASSWORD=${PASS}#" "$ENV"
  sed -i.bak "s#^DATABASE_URL=postgresql://postgres:[^@]*@#DATABASE_URL=postgresql://postgres:${PASS}@#" "$ENV"
  echo "POSTGRES_PASSWORD generado y copiado a DATABASE_URL"
fi

rm -f "$ENV.bak"

# Comprobación final: nada obligatorio vacío ni con valores de ejemplo.
PENDIENTES=$(grep -E '^(ENCRYPTION_SECRET|POSTGRES_PASSWORD|SMTP_PASSWORD|EVA_DOMINIO_VISOR|EVA_DOMINIO_EDITOR|EVA_PUBLIC_ID|ADMIN_EMAIL)=$' "$ENV" || true)
if grep -q 'postgres:CAMBIAR@' "$ENV"; then PENDIENTES="$PENDIENTES DATABASE_URL"; fi
if [ -n "$PENDIENTES" ]; then
  echo "Quedan por rellenar en $ENV:"; echo "$PENDIENTES" | sed 's/=$//; s/^/  - /'
  exit 1
fi
echo "Listo: $ENV completo (permisos 600)."
