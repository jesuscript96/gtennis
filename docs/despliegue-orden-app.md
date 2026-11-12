# Despliegue del orden de la aplicación: cómo hacerlo sin perder nada

Rama `claude/orden-app`. Escrito el 11/11/2026. Nada de esto se ha hecho todavía en
producción.

## Por qué no se puede perder nada

Hay tres protecciones independientes; basta una para recuperarlo todo.

1. **Tres copias antes de tocar producción**: instantánea del proveedor de la base,
   `pg_dump` completo y el JSON de `dumpdata` de siempre. El JSON se comprueba
   cargándolo en local (paso 3); el `pg_dump`, restaurándolo.
2. **Las migraciones guardan en la propia base todo lo que cambian o borran**, en
   la tabla `users_archivomigracion`: cada falta del parte semanal, cada fila de
   «Disp. entrenadores», cada interruptor, cada rol cambiado, cada bloque
   desactivado y cada torneo «Propuesto». Deshacerlas (`migrate … hacia atrás`)
   lo deja exactamente como estaba, sin necesitar las copias.
3. **Ensayo previo con la copia recién sacada**: el script
   `backend/scripts/ensayo_orden.py` reconstruye producción en un PostgreSQL de
   usar y tirar, migra, comprueba, deshace y compara fila a fila. Si no dice
   «BIEN», no se despliega.

Ensayo hecho el 11/11/2026 con la copia de producción del 27/10 (6.053 filas):
0 diferencias tras deshacer, nada borrado sin archivar, la versión vieja escribe
sin errores sobre la base nueva durante el despliegue y el repaso lo recoge.

## Lo que cambia en los datos al migrar

| Migración | Qué hace | Archivo |
|---|---|---|
| users.0005 | Crea el archivo de migraciones | — |
| users.0006 | Funciones iniciales (Dani, Pablo, Santi, Alberto); ivan.gallego → dirección; `ivan` inactivo; `administracion` → Administración | roles anteriores y funciones creadas |
| academy.0058 | Desactiva (no borra) los bloques sin color de Sergio e Iván | qué bloques |
| academy.0059, scheduling.0033, evaluaciones.0009 | Solo columnas nuevas, todas opcionales o con valor por defecto en la base | — |
| scheduling.0034 | Parte semanal (salvo «viene además») → faltas por fechas; «Disp. entrenadores» e interruptor → calendario del entrenador | cada fila borrada, entera |
| torneos.0009 / 0010 | «Propuesto» → «Validado» | qué torneos |

## Procedimiento

**Cuándo**: un día laborable a partir de las 21:00, con la generación de las 19:00
ya hecha (o un domingo por la mañana). Nunca entre las 18:45 y las 19:30, ni el
viernes de 16:15 a 17:00. Avisar al club de que durante ~20 minutos no apunten
nada.

### 0. Preparación (la víspera)

- `flyctl auth login` y comprobar dónde está la base:
  `fly secrets list -a gtennis-api-jesus` (sale `DATABASE_URL`, sin el valor),
  `fly postgres list` / `fly mpg list`. Si es Fly Postgres, anotar la app y el
  volumen (`fly volumes list -a <app-de-la-base>`).
- `pg_dump --version` tiene que ser igual o mayor que la versión del servidor
  (`brew install postgresql@16` o la que toque).
- Configurar el correo en Fly (`EMAIL_HOST`, `EMAIL_HOST_USER`,
  `EMAIL_HOST_PASSWORD`, `EMAIL_PORT`, `EMAIL_USE_TLS`) para «Aprobar y enviar».
- Ejecutar en producción `python manage.py lista_antigua_acceso` NO se puede aún
  (el comando es nuevo): se mira después del despliegue y se resuelve en Grupos.

### 1. Copias (con la app quieta)

```bash
# a) Instantánea del proveedor (si es Fly Postgres)
fly volumes snapshots create <vol-id> -a <app-de-la-base>

# b) pg_dump completo, por túnel
fly proxy 15432:5432 -a <app-de-la-base>        # en otra terminal
pg_dump -Fc -h localhost -p 15432 -U <usuario> <base> > backup_prod_AAAA-MM-DD_orden.dump

# c) JSON de siempre + recuento de filas
fly ssh console -a gtennis-api-jesus -C "sh -c 'cd /code && python manage.py dumpdata -e contenttypes -e auth.permission -e sessions -e admin --indent 0 -o /tmp/copia.json'"
fly ssh sftp get /tmp/copia.json backend/backup_prod_AAAA-MM-DD_orden.json -a gtennis-api-jesus
# recuento (scripts/recuento_shell.py, subido por base64 como otras veces) → recuento_antes.json
```

Las copias llevan contraseñas cifradas y tokens: se quedan en `backend/`
(`backup_*.json` está en `.gitignore`) y no se comparten.

### 2. Comprobar las copias

- `pg_restore --list backup_….dump | head` (que se lea entero).
- El recuento de filas del JSON tiene que coincidir con `recuento_antes.json`.

### 3. Ensayo con esa copia

```bash
backend/.venv/bin/python backend/scripts/ensayo_orden.py --copia backend/backup_prod_AAAA-MM-DD_orden.json
```

Tiene que acabar en `RESULTADO: BIEN`. El informe queda en
`$TMPDIR/ensayo_orden/informe.txt`.

### 4. Desplegar

1. Servidor primero, **sin hacer push**: un push a `main` despliega la web en
   Vercel al momento. Desde la rama ya puesta al día con `main` (y con el ensayo
   repetido si `main` trajo migraciones), `fly deploy -a gtennis-api-jesus`. El
   `release_command` migra; si una migración falla, Postgres la deshace entera y
   el despliegue se para con la versión vieja funcionando.
2. Repaso de lo que la versión vieja haya escrito durante el despliegue:
   `fly ssh console -C "sh -c 'cd /code && python manage.py unificar_faltas'"` y,
   si sale algo, `… unificar_faltas --aplicar`.
3. `python manage.py archivo_migraciones` (qué se archivó) y
   `python manage.py recuento --comparar recuento_antes.json` (los cambios tienen
   que ser solo los de la tabla de arriba).
4. Web después del servidor: ahora sí, merge en `main` y push (Vercel la publica).
5. Entrar con dirección, un head coach y un entrenador; mirar Cuadrante, Faltas
   y Grupos. `python manage.py lista_antigua_acceso` y resolver en Grupos lo que
   salga.
6. Los móviles con la app guardada tienen que recargarla una vez.

## Marcha atrás

**Siempre, primero, una copia nueva** (paso 1): guarda lo que se haya hecho
después de desplegar.

- **Deshacer el despliegue (mismo día)**: con el código NUEVO aún desplegado,
  ```bash
  python manage.py migrate scheduling 0032_edad_obligatoria
  python manage.py migrate torneos 0008_fecha_borrado
  python manage.py migrate evaluaciones 0008_traduccion_para_la_familia
  python manage.py migrate academy 0057_orden_division
  python manage.py migrate users 0003_alter_user_role
  ```
  y después desplegar la versión anterior (`fly deploy --image <imagen anterior>`
  o `fly releases` + revert) y la web anterior en Vercel. Lo que solo existe en
  la versión nueva (funciones dadas después, quién apuntó cada falta, envíos de
  informes) queda en la copia del principio de este apartado.
- **Desastre**: restaurar el `pg_dump` (o la instantánea del proveedor) del paso 1.
