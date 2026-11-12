#!/bin/sh
# Copias y comprobaciones de producción para desplegar el orden de la
# aplicación (12/11/2026). Solo lee. Se lanza desde cualquier sitio:
#
#   sh backend/scripts/copias_prod.sh antes     # antes de desplegar
#   sh backend/scripts/copias_prod.sh despues   # en cuanto acabe el despliegue
#
# Deja los ficheros en backend/backup_prod_<fecha>_<fase>_* (fuera de git).
set -eu
FASE=${1:?"Uso: copias_prod.sh antes|despues"}
APP=gtennis-api-jesus
DB=gtennis-api-jesus-db
RAIZ=$(cd "$(dirname "$0")/../.." && pwd)
SAL="$RAIZ/backend/backup_prod_$(date +%Y-%m-%d_%H%M)_$FASE"

# Ejecuta un script de shell en una máquina (subido en base64, como siempre).
remoto() {  # remoto <app> <script>
  B=$(printf '%s' "$2" | base64 | tr -d '\n')
  fly ssh console -a "$1" -C "sh -c 'echo $B | base64 -d > /tmp/orden.sh && sh /tmp/orden.sh'"
}
traer() {  # traer <app> <remoto> <local>
  rm -f "$3"
  fly ssh sftp get -a "$1" "$2" "$3" >/dev/null
  echo "  $(basename "$3"): $(wc -c < "$3" | tr -d ' ') bytes"
}

RECUENTO=$(cat "$RAIZ/backend/scripts/recuento_shell.py")

if [ "$FASE" = antes ]; then
  echo "1/3 Copia completa (JSON), asignaciones y recuento…"
  remoto "$APP" "set -e
cd /code
python manage.py dumpdata -e contenttypes -e auth.permission -e sessions -e admin --indent 0 -o /tmp/orden_copia.json
python manage.py dumpdata scheduling.semana scheduling.asignacion scheduling.quitadoamano --indent 0 -o /tmp/orden_asignaciones.json
cat > /tmp/recuento.py <<'PY'
$RECUENTO
PY
python manage.py shell < /tmp/recuento.py > /tmp/orden_recuento.json"
  traer "$APP" /tmp/orden_copia.json "${SAL}_copia.json"
  traer "$APP" /tmp/orden_asignaciones.json "${SAL}_asignaciones.json"
  traer "$APP" /tmp/orden_recuento.json "${SAL}_recuento.json"

  echo "2/3 pg_dump completo en la máquina de la base…"
  if remoto "$DB" 'set -e
U="postgres://postgres:$OPERATOR_PASSWORD@localhost:5433"
BD=$(psql "$U/postgres" -Atc "select datname from pg_database where not datistemplate and datname not in ('"'"'postgres'"'"','"'"'repmgr'"'"') order by 1" | head -1)
pg_dump -Fc "$U/$BD" -f /tmp/orden_copia.dump
echo "base: $BD"'; then
    traer "$DB" /tmp/orden_copia.dump "${SAL}_pgdump.dump"
  else
    echo "  AVISO: no se pudo hacer el pg_dump; quedan la instantánea del volumen y el JSON."
  fi
  echo "3/3 Hecho."
else
  echo "1/1 Asignaciones, recuento y repaso tras desplegar…"
  remoto "$APP" "set -e
cd /code
python manage.py dumpdata scheduling.semana scheduling.asignacion scheduling.quitadoamano --indent 0 -o /tmp/orden_asignaciones.json
python manage.py recuento > /tmp/orden_recuento.json
{ python manage.py unificar_faltas; echo ---; python manage.py archivo_migraciones; echo ---; python manage.py lista_antigua_acceso; } > /tmp/orden_estado.txt 2>&1"
  traer "$APP" /tmp/orden_asignaciones.json "${SAL}_asignaciones.json"
  traer "$APP" /tmp/orden_recuento.json "${SAL}_recuento.json"
  traer "$APP" /tmp/orden_estado.txt "${SAL}_estado.txt"
  echo "Hecho."
fi
