# G Tenis — Manual de producción (para Sergio)

> Aplicación web para automatizar el cuadrante semanal de la academia.
> Última actualización: despliegue del feedback Fase 1 (commit `bc3702c`).

---

## 1. Accesos

| Qué | URL |
|-----|-----|
| **App (lo que usa el club)** | <https://gtennis.vercel.app/> |
| **Admin Django (solo dirección/dev)** | <https://gtennis-api-jesus.fly.dev/admin/> |
| **API (inspección rápida)** | <https://gtennis-api-jesus.fly.dev/api/> |

> Toda la app está en la UE (Frankfurt) por RGPD: hay datos de salud (lesiones)
> y menores.

### Usuarios y roles

Hay **tres roles**. El menú lateral cambia según el tuyo:

| Rol | Qué ve | Usuario demo |
|-----|--------|--------------|
| **Super Admin (Dirección)** | Todo: jugadores, entrenadores, cuadrante, escuelas, coaches, avisos, feedback | `ivan` / `gtennis123` |
| **Coach** | Jugadores de **sus entrenadores**, cuadrante, avisos. No ve "Coaches" ni "Feedback" | `coach` / `demo1234` |
| **Entrenador** | Solo sus jugadores y su disponibilidad | (uno por entrenador real) |

- Crear coaches y entrenadores: **Dirección** desde la app o desde el admin Django.
- Resetear contraseñas: desde el admin Django → *Users* → usuario → *Set password*.

---

## 2. Qué hay nuevo en este despliegue (feedback Fase 1)

Estos son los puntos del backlog de Sergio que ya están en producción:

### Datos corregidos (lo que generaba quejas)
- **#7 Horarios + verano** — Los 4 turnos ya tienen horario de invierno y de
  verano. En agosto se muestra el de verano. Si los botones del cuadrante
  muestran `08:00–10:00` es correcto (horario de verano).
- **#8 Orden de recintos** — Sedes en orden: **Resort → Sta. Bárbara →
  Poli Bétera → Mas Camarena**. Liria está **desactivada**.
- **#1a Tipo de pista** — Cada pista tiene superficie (tierra/resina); se ve
  como punto de color junto al número (P1…P8). Editable en *Pistas*.
- **#12 Reparto de %** — Los responsables ya reparten **70% principal / 30%
  secundarios** automáticamente. Antes todos estaban a 0%.

### Motor
- **#17 Tardes sin satélites** — En T1/T2 los jugadores solo caen en el
  **Resort**. Los clubs satélite quedan vacíos por la tarde (por la mañana sí
  se usan). Si sobra gente, va al banquillo (no se spillea a satélites).
- **#6 Junior Program** — Es una **escuela**, no una columna. Sus jugadores
  solo entrenan en la franja **M2** y siempre en el **Resort**. Verifícalo en
  *Escuelas* (Junior Program → turno único M2, solo Resort Sí).
- **#1b Preferencia de superficie** — En *Datos → Pref. superficie* puedes
  fijar que un jugador juegue siempre en tierra o resina (estricto o
  preferente). El motor lo respeta al emparejar.

### Organización
- **#16 Rol Coach** — Nuevo rol intermedio. Dirección crea Coaches y les
  asigna entrenadores. Un Coach ve a todos los jugadores de sus entrenadores
  (no a los 46). Un Entrenador sigue viendo solo los suyos.
- **#5 Invitados** — Formulario ampliado: **edad**, **superficie**,
  **jugar con** (pareja) y **misma pista obligatoria**. Al aprobarse, se crea
  el jugador con su preferencia y su pareja. El Coach del entrenador
  solicitante recibe aviso.
- **#4 Reportar movimiento de escuela** — En *Jugadores*, botón *Movimiento*
  en la fila → escribe la escuela donde lo has visto → genera un aviso a
  dirección. **La escuela del jugador no cambia automáticamente.**
- **#18 Baja de jugador** — Al desmarcar *Activo* en un jugador, se genera un
  aviso de baja a dirección (en *Avisos*).

### Ya estaban (repaso)
- #2 varios responsables + prioridad · #3 divisiones por entrenador · #9
  jugadores numerados · #10 torneo/franjas · #11 vacaciones · #13
  mantenimiento (aviso in-app) · #15 edad por fecha de nacimiento.

### Pendiente / fuera de esta fase
- **#14 Web público en inglés** — fuera de scope.
- **#18 Notificación WhatsApp** — de momento solo aviso in-app (decisión
  tomada con el cliente).

> Para probar cada punto en local con datos de demo, ver
> [`docs/manual-pruebas.md`](./manual-pruebas.md).

---

## 3. Operación del día a día

### Generar la semana
1. *Cuadrante* → **Generar semana** (crea el borrador con el motor).
2. Si hay cambios de última hora (lesiones, torneos, climatología), márcalos
   en *Ausencias y estados* y pulsa **Regenerar tarde** (no toca la mañana).
3. Cuando esté OK: **Publicar**.

### Cosas que se pueden hacer sin tocar código
- Ajustar pesos de criterios del motor: *Criterios del motor*.
- Crear/editar jugadores, entrenadores, sedes, pistas, divisiones, rencillas
  (vetos) y contratos de patrocinio.
- Cambiar coaches de un entrenador o responsables de un jugador (recalcula %).
- Ver avisos pendientes en *Avisos* (invitados, movimientos, bajas, mantenimiento).

---

## 4. Cómo se hace un despliegue (runbook)

> **Importante:** Vercel y Fly **no se despliegan igual**.

### Frontend (Vercel) — automático
Cualquier `git push` a `main` despliega el frontend automáticamente en
1–2 min. No hay que hacer nada.

### Backend (Fly) — manual
Fly **no** escucha el repo. Tras un `git push` que toque `backend/`:

```bash
cd backend
fly deploy --app gtennis-api-jesus --strategy rolling
```

- El `release_command` de `fly.toml` ejecuta **automáticamente**
  `python manage.py migrate --noinput && python manage.py seed_base`.
  Las migraciones nuevas (incluidas las de datos) se aplican solas sobre el
  Postgres de producción.
- Duración típica: 2–4 min. Estrategia *rolling* = sin corte de servicio.
- Monitor: <https://fly.io/apps/gtennis-api-jesus/monitoring>

### Comandos útiles (Fly)

```bash
# Ver estado de máquinas
fly status -a gtennis-api-jesus

# Ver logs en vivo
fly logs -a gtennis-api-jesus

# Abrir shell de Django en prod
fly ssh console -a gtennis-api-jesus -C "python manage.py shell"

# Aplicar una migración concreta a mano (rara vez hace falta)
fly ssh console -a gtennis-api-jesus -C "python manage.py migrate"

# Marcar el feedback como resuelto (tras comprobar que un punto ya va)
fly ssh console -a gtennis-api-jesus -C "python manage.py sync_feedback_estados"

# Backup de la BD Postgres
fly pg backup -a gtennis-api-jesus-db
```

### Vercel (frontend)

```bash
# Lista de deploys
vercel ls gtennis

# Promocionar un deploy antiguo a producción (rollback)
vercel promote <deployment-url> --scope jesusvchs-projects
```

---

## 5. Arquitectura (resumen)

| Pieza | Stack | Dónde |
|-------|-------|-------|
| Frontend | Next.js 15 + React 19 | Vercel · `gtennis.vercel.app` |
| API + admin | Django + DRF | Fly · `gtennis-api-jesus.fly.dev` (región `fra`) |
| Worker | Celery (tareas 5 PM Rule) | Fly · proceso `celery` |
| BD | PostgreSQL 17 | Fly · `gtennis-api-jesus-db` |
| Repositorio | GitHub | <https://github.com/jesuscript96/gtennis> |

> ⚠️ El `render.yaml` del repo es un blueprint **no usado** en producción.
> El despliegue real es el de Fly (`backend/fly.toml`).

---

## 6. Si algo va mal

### "La app no carga"
1. Comprueba <https://gtennis.vercel.app/> (frontend) y
   <https://gtennis-api-jesus.fly.dev/api/> (backend) por separado.
2. Si solo falla el frontend: `vercel ls gtennis`, promociona el penúltimo
   deploy.
3. Si solo falla el backend: `fly status -a gtennis-api-jesus` y `fly logs`.

### "El cuadrante sale raro / sin jugadores"
- Comprueba que el jugador tenga *entrenador* y *división* asignados.
- Si eres Coach/Entrenador: recuerda que solo ves a los **tuyos**.
- Re-genera la semana: a veces hay cambios pendientes sin aplicar.

### "Los horarios salen mal otra vez"
- Son datos, no código. Verifica en el admin Django → *Turnos* que los campos
  `hora_inicio`, `hora_fin`, `hora_inicio_verano`, `hora_fin_verano` están
  poblados. La migración `0014` ya los deja bien.

### "Un responsable tiene % = 0"
- Edita y guarda al responsable desde la app (recalcula) o ejecuta
  `fly ssh console -a gtennis-api-jesus -C "python manage.py repartir_porcentajes"`.

---

## 7. Contacto y siguientes pasos

- **Siguiente fase del feedback:** ver `docs/plan-feedback.md` (secciones 5 y 6).
- **Para probar en local** con datos de demo: ver `docs/manual-pruebas.md`.
- **Reportar un bug:** abrir issue en el repo de GitHub o avisar a dev.

*Documento mantenido por dev. Última revisión: alineado con commit `bc3702c`
(feedback Fase 1, deployado el 12 ago 2026).*
