# Plan de ejecución — Feedback de producción

> Documento vivo. Recoge el estado real del backlog de feedback de la academia
> (endpoint de producción `/api/feedback/`), la verificación de despliegue, las
> decisiones tomadas con el cliente y el plan de ejecución por fases.
>
> **Última revisión:** alineado con el commit `951db25` (roadmap de feedback) y
> los datos observados en producción (Fly.io + Vercel) en la sesión actual.

---

## 1. Contexto

- **App:** GTennis — generador de cuadrantes semanal de entrenamientos para una
  academia de tenis. Backend Django + DRF (OR-Tools para el solver), frontend
  Next.js.
- **Producción:**
  - Backend: **Fly.io** — `https://gtennis-api-jesus.fly.dev` (`fly.toml`,
    región `fra`, Postgres vía `DATABASE_URL`).
  - Frontend: **Vercel** — `https://gtennis.vercel.app`.
  - El `render.yaml` del repo es un blueprint **no usado** en producción.
- **Módulo de feedback:** endpoint público de lectura `/api/feedback/`
  (`academy/views.py:234`). Hoy hay **18 entradas** repartidas en prioridad
  Alta / Media / Baja, todas en estado `NUEVO`.
- **Roadmap en código:** el commit `951db25` implementa los items #2, #3, #5
  (flujo), #6 (parcial), #10, #11, #12 (parcial), #13 (parcial) y añade los
  modelos de `Aviso`, `Invitado`, `Escuela`, `ResponsableJugador`,
  `VacacionesEntrenador`, `DisponibilidadEntrenador`, `TareaMantenimiento`.

---

## 2. Review: estado de cada item vs. código

**Leyenda:** ✅ completo (modelo + motor + UI) · 🟡 parcial · 🔴 no empezado ·
⏭️ fuera de scope

| ID  | Prior. | Título                              | Estado   | Nota clave                                                                                  |
|-----|--------|-------------------------------------|----------|---------------------------------------------------------------------------------------------|
| 1   | Baja   | Tipo de pistas (tierra/rápida)      | 🟡       | Dato existe; el motor no lo usa. Decidido: añadir preferencia por jugador.                  |
| 2   | Alta   | Varios responsables + prioridad     | ✅       | Cablado en `_assign_coaches` (`service.py:141`).                                            |
| 3   | Alta   | Divisiones habilitadas x entrenador | ✅       | Cablado en `_coach_capacita` (`service.py:133`).                                            |
| 4   | Media  | Movimientos entre escuelas          | 🟡       | `Aviso.MOVIMIENTO` existe pero **no hay acción para crearlo**.                              |
| 5   | Alta   | Jugador invitado                    | 🟡       | Aprobación ✅; faltan datos del invitado, pareja preferida y notificar al Coach.             |
| 6   | Media  | Junior Program (12-14h)             | 🔴       | La escuela es dato; **no hay franja JP ni aislamiento en el motor**.                        |
| 7   | Alta   | Horarios turnos + verano            | ✅ / ⚠️  | Código bien pero **seed NO aplicado en prod** → "horarios raros".                           |
| 8   | Alta   | Orden de recintos                   | ✅ / ⚠️  | Igual: código bien, **seed NO aplicado en prod**.                                           |
| 9   | Media  | Numerar jugadores de lista          | ✅       | `RESOURCES.jugadores.numbered = true`.                                                      |
| 10  | Alta   | Disp. entrenador (torneo + franja)  | ✅       | `DisponibilidadEntrenador.disponible_en`.                                                   |
| 11  | Baja   | Vacaciones                          | ✅       | El motor excluye por rango de fechas.                                                       |
| 12  | Alta   | % entrenos con un entrenador        | 🟡       | Lógica existe; en prod los 52 responsables tienen % = 0.                                    |
| 13  | Baja   | Mantenimiento                       | ✅       | Con "in-app only" → completo (aviso a dirección en `views.py:222`).                         |
| 14  | Baja   | Web público en inglés               | ⏭️      | Fuera de scope de la app.                                                                   |
| 15  | Baja   | Edad desde fecha nacimiento         | ✅       | `Jugador.save()` recalcula edad y `es_menor`.                                               |
| 16  | Media  | Rol "Coach" intermedio              | 🔴       | Solo 2 roles; permisos binarios (`is_superadmin`).                                          |
| 17  | Media  | Tardes nunca satélites              | 🔴       | El motor no distingue bloque.                                                               |
| 18  | Media  | Notificación de baja (WhatsApp)     | 🔴→🟡    | Reducido a aviso in-app al dar de baja.                                                     |

**Resumen:** 9 completos, 4 parciales, 4 no empezados, 1 fuera de scope.

---

## 3. Verificación de despliegue

### 3.1 Backend (Fly.io) — código desplegado, datos rotos

Todos los endpoints nuevos del roadmap responden en producción (`responsables`,
`escuelas`, `mantenimiento`, `invitados`→401, `disponibilidades-entrenador`→401,
etc.). **Pero el comando `seed_sedes` nunca se ha ejecutado en prod**, y el
`release_command` del `fly.toml` solo lanza `migrate` + `seed_base`:

```
# backend/fly.toml:13
release_command = 'sh -c "python manage.py migrate --noinput && python manage.py seed_base"'
```

Discrepancias observadas en prod (vs. lo que deja `seed_sedes.py`):

| Dato en prod                       | Debería ser                                       |
|------------------------------------|---------------------------------------------------|
| Liria **activa** con 2 pistas      | Desactivada ("no pongas otro club")               |
| **Falta Mas Camarena**             | Sede 4, 1 pista resina                            |
| "Bétera"                           | "Poli Bétera"                                     |
| Sta. Bárbara **4 pistas resina**   | 3 pistas **tierra**                               |
| Resort: 8 pistas **todas resina**  | Pistas 1-6 **tierra**, 7-8 resina                 |
| M1 = 08:30-**10:00**, sin verano   | 08:30-10:30 normal / 08:00-10:00 verano           |
| `hora_*_verano` = null (4 turnos)  | Poblados para jul/ago                             |

Esto explica literalmente el grito de Sergio "#7 SEGUIMOS CON HORARIOS RAROS".

Otros desajustes:
- **#12:** los 52 `ResponsableJugador` cargados (migración `0010_seed_responsables`)
  están **todos con `prioridad=1` y `porcentaje_objetivo=0`**.
- Divisiones (D1-D8), escuelas (Alto Rendimiento + Junior Program),
  entrenadores con `divisiones_habilitadas`: ✅ correctos.

### 3.2 Frontend (Vercel) — desplegado

Las 11 páginas responden 200 en `https://gtennis.vercel.app`:
`/`, `/cuadrante`, `/semana`, `/jugadores`, `/entrenadores`, `/responsables`,
`/vacaciones`, `/disponibilidad-entrenador`, `/invitados`, `/mantenimiento`,
`/avisos`, `/feedback`.

El frontend está al día con el commit `951db25`.

### 3.3 Sistema de permisos actual (base para el rol Coach)

Patrón existente en `scheduling/views.py`:
- `_entrenador()` → `getattr(request.user, "entrenador", None)`.
- `Entrenador.gestiona_todos_jugadores` (flag) + `puede_gestionar(jugador)`.
- Aplicado en `DisponibilidadViewSet`, `DisponibilidadEntrenadorViewSet`.
- `User.Role` solo tiene `SUPERADMIN` y `ENTRENADOR` (`users/models.py:10`).
- 8 puntos del código checkean `is_superadmin` (en `academy/views.py` y
  `scheduling/views.py`) — todos los hereda el nuevo rol Coach vía helper.

---

## 4. Decisiones tomadas con el cliente

- **Notificaciones (#13 y #18):** se quedan **dentro de la app** (aviso in-app
  vía modelo `Aviso`). Nada de WhatsApp por ahora. Con esto:
  - #13 queda **completo** ya.
  - #18 queda reducido a "crear un `Aviso` al dar de baja".
- **Reparto de % (#12):** patrón canónico **70 / 15 / 15** (principal / 2º / 3º).
  Automático según el nº de responsables del jugador.
- **#6 Junior Program:** 5º turno fijo aislado (12:00-14:00 verano / 12:30-14:00
  invierno). Los jugadores JP **solo juegan en esa franja**, siempre en Resort
  (sin satélites), densidad hasta 4 manual.
- **#17 Tardes sin satélites:** **restricción dura**. El desbordamiento va a
  banquillo (no se spillea a satélites).
- **#4 Movimientos:** notifica a (entrenador del jugador + coach + dirección).
  **No cambia la escuela automáticamente.**
- **#5 Invitados:** se asocia a entrenador o jugador. Quién puede crear:
  Entrenador (su grupo), Coach, Dirección. Notificación **siempre** al Coach del
  entrenador + Dirección.
- **#1 Superficie:** puede haber criterio de tipo de pista asociado a jugadores,
  por tiempo (fecha desde/hasta) o indefinidamente.
- **#16 Rol Coach:**
  - Un Coach tiene **entrenadores asignados**.
  - Un Entrenador solo ve a **sus jugadores**; un Coach ve a **todos los
    jugadores de sus entrenadores**.
  - Cada rol solo ve lo que le corresponde.
  - **SuperAdmin crea Coaches. Coaches y SuperAdmin crean Entrenadores.**

---

## 5. Plan de ejecución

### Visión general

| Fase | Items            | Esfuerzo   | Dependencia            |
|------|------------------|------------|------------------------|
| 0    | #7, #8, #12 datos| Bajo       | Ninguna                |
| 1    | #16              | Medio-alto | Fundacional            |
| 2    | #17, #6, #1      | Medio      | Fase 0 (datos)         |
| 3    | #5, #4, #12      | Medio      | Fase 1 (permisos)      |
| 4    | #18              | Bajo       | Fase 1                 |
| 5    | Despliegue + QA  | —          | Al final de cada fase  |

Orden de ataque: **0 → 1 → 2 → 3 → 4**. Fase 0 desbloquea la queja inmediata;
Fase 1 antes que 3/4 porque los permisos de Coach son cimiento de #4 y #5.

### FASE 0 — Desbloquear producción (datos)

**Ticket 0.1 — Aplicar `seed_sedes` en Fly**
- Añadir `seed_sedes` al `release_command` de `backend/fly.toml:13`:
  ```
  release_command = 'sh -c "python manage.py migrate --noinput && python manage.py seed_base && python manage.py seed_sedes"'
  ```
- Ejecutarlo cuanto antes via `fly ssh console -a gtennis-api-jesus --command "python manage.py seed_sedes"` (idempotente).
- Verificación: `curl /api/sedes/` (4 sedes, Liria off, superficies correctas) y
  `curl /api/turnos/` (`hora_*_verano` poblados, M1 = 08:30-10:30).

**Ticket 0.2 — Re-armar % de responsables (70-15-15)**
- `Jugador.repartir_porcentajes()`: reparte según nº de responsables
  (1→100, 2→70/30, 3→70/15/15, >3→reparto equitativo).
- Llamarlo al guardar desde `ResponsableJugadorViewSet`.
- Management command `repartir_porcentajes` + migración de datos
  `0014_repartir_porcentajes.py` para arreglar los 52 existentes.
- **Bloqueador:** falta saber quién es el 2º/3º entrenador de cada jugador
  (Excel fuente o alta manual). Hasta entonces, el principal queda a 100%.

### FASE 1 — Rol "Coach" + permisos transversales (#16)

**Ticket 1.1 — Modelo Coach y relación**
- `User.Role.COACH`; properties `is_coach` e `is_direccion` (= superadmin o coach).
- Nuevo modelo `Coach` (espejo de `Entrenador`): `user` OneToOne, `nombre`,
  `activo`, `entrenadores` M2M→`Entrenador`.
- Migración + admin.

**Ticket 1.2 — Alcance de datos por rol**
- `academy/scope.py`:
  - `jugadores_visibles(user)`: SuperAdmin → todos; Coach → jugadores de sus
    entrenadores; Entrenador → `entrenador.jugadores_permitidos()`.
  - `entrenadores_visibles(user)` para Coach.

**Ticket 1.3 — Aplicar scope a viewsets**
- `JugadorViewSet.get_queryset` (hoy solo `activo=True`).
- Extender el patrón `_entrenador()` con rama Coach en: `DisponibilidadViewSet`,
  `DisponibilidadEntrenadorViewSet`, `AsignacionViewSet`, `AvisoViewSet`,
  `InvitadoViewSet`.

**Ticket 1.4 — Permisos de creación de usuarios**
- Endpoint `/api/users/` (o ampliar admin): solo SuperAdmin crea Coaches;
  Coaches y SuperAdmin crean Entrenadores. Chequeo de rol en `perform_create`.

**Ticket 1.5 — Frontend Coach**
- `Sidebar.jsx`: label "Super Admin / Coach / Entrenador".
- Si Coach: menú añade "Mis entrenadores" y oculta lo no procedente.
- `lib/api.js`: propagar `is_coach` desde `/auth/me/`.

### FASE 2 — Motor de emparejamiento

**Ticket 2.1 — #17: Tardes nunca satélites (duro)**
- `engine/service.py`: en turnos `bloque=TARDE`, pasar a `solve_pairing` solo
  courts de sedes **no satélite**.
- Desbordamiento → `report["unassigned"]` / banquillo (ya existe).
- Frontend: aviso visible en `semana/page.jsx` si hay no asignados por la tarde.

**Ticket 2.2 — #6: Junior Program como 5º turno aislado**
- Modelo: `Turno.solo_escuela` FK→`Escuela` nullable. Seed: turno JP
  (12:00-14:00 verano / 12:30-14:00 invierno), `solo_escuela=Junior Program`.
- Motor: para turnos con `solo_escuela`, solo jugadores de esa escuela; en el
  resto, excluir jugadores de escuelas con turno propio (JP no sale en M1/M2).
  Courts JP: solo Resort, densidad hasta 4.
- Frontend: el cuadrante ya pinta por turno → JP aparece como columna nueva.

**Ticket 2.3 — #1: Preferencia de superficie por jugador**
- Nuevo modelo `PreferenciaSuperficie`: `jugador` FK, `superficie` (TIERRA/RESINA),
  `fecha_desde`, `fecha_hasta` (nullable = indefinido), `estricta` (default True).
- Motor (`pairing.py`): `Player.superficie_pref` + restricción dura si `estricta`.
- `service.py`: inyectar preferencias activas (por fecha) en `_available_players`.
- Frontend: nueva sección `/preferencias-superficie` + campo en ficha de jugador.

### FASE 3 — Bucle de entrenadores

**Ticket 3.1 — #5: Datos del invitado + notificación al Coach**
- `Invitado`: añadir `division` FK, `edad`, `nivel`, `superficie_pref`. Al
  aprobar, el `Jugador` temporal se crea con estos datos propios.
- `InvitadoViewSet.perform_create`: además del aviso a dirección, crear `Aviso`
  a cada Coach del entrenador solicitante.
- Quién crea: Entrenador (su grupo), Coach, Dirección. Validar scope.
- Frontend `/invitados`: ampliar form con los nuevos campos.

**Ticket 3.2 — #5: Pareja preferida del invitado**
- Nuevo modelo `PreferenciaPareja`: `invitado`/`jugador` FK, `jugador_objetivo`
  FK, `tipo` (HARD/SOFT).
- Motor: HARD → forzar misma pista; SOFT → bonus en el objetivo.
- Frontend: en detalle del invitado, "Jugar con: [select jugador]".

**Ticket 3.3 — #4: Reportar movimiento de escuela**
- Acción `JugadorViewSet.reportar_movimiento` (POST): `jugador`, `escuela
  observada`, `nota` → `Aviso(tipo=MOVIMIENTO, para_direccion=True)` + aviso al
  entrenador actual del jugador.
- Permisos: Entrenador (sus jugadores), Coach (sus entrenadores), Dirección.
- No cambia la escuela automáticamente.
- Frontend: botón "Reportar movimiento" en fila/ficha de jugador.

**Ticket 3.4 — #12: Contrato vs Responsable**
- Mantener ambos conceptos:
  - `Contrato` = sponsor **duro** (player↔coach siempre juntos).
  - `ResponsableJugador` = **ponderación 70/15/15** (la que usa el motor).
- Añadir `Contrato.porcentaje` opcional (0-100, informativo) — la lógica del
  motor sigue usando `ResponsableJugador`.
- Frontend: pestaña "Responsables" dentro de la ficha de jugador, con reparto
  70/15/15 automático.

### FASE 4 — Bajas in-app (#18)

**Ticket 4.1 — Aviso al dar de baja**
- `JugadorViewSet.perform_update`: si `activo` cambia True→False, crear
  `Aviso(para_direccion=True, tipo=GENERAL, titulo="Baja: <nombre>")`.
- Alternativa adicional: `Disponibilidad` con `subtipo=VACACIONES` → aviso
  (bajas temporales).
- Mireia: crearle usuario (Coach o SuperAdmin). Si el aviso debe ir **solo a
  ella**, `Aviso.usuario = mireia` — **pendiente de decisión de rol**.

### FASE 5 — Despliegue y verificación

- Tras cada fase: commit + push (Fly redeploya con el nuevo `release_command`)
  + Vercel redeploy.
- Verificación de datos: scripts `curl` a prod (sedes, turnos, superficies, %).
- Feedback: actualizar `estado=HECHO` en las entradas resueltas vía API (con
  token de admin) a medida que se completen.

---

## 6. Pendientes que frenan (requieren input del cliente)

1. **Excel de responsables** con 2º y 3º entrenador por jugador (para el
   reparto 70/15/15 real). Sin esto, los 52 actuales se quedan al 100% del
   principal. ¿Excel o alta manual por UI?
2. **Rol de Mireia** (#18): ¿Coach o SuperAdmin? Y si el aviso debe ir solo a
   ella, hay que crearle usuario.
3. **#12 G1 (sin responder):** confirmar mantener `Contrato` (duro) +
   `ResponsableJugador` (ponderado) como dos conceptos distintos.
4. **Acceso a Fly:** ¿OK para correr `fly ssh console` contra
   `gtennis-api-jesus`, o lo hace el cliente / se espera al próximo deploy?

---

## 7. Referencias rápidas en el código

| Qué                                 | Dónde                                   |
|-------------------------------------|-----------------------------------------|
| Modelo `Feedback`                   | `backend/academy/models.py:489`         |
| ViewSet + serializer de Feedback    | `backend/academy/views.py:234`          |
| Motor (solver bridge)               | `backend/engine/service.py`             |
| Solver puro (OR-Tools)              | `backend/engine/pairing.py`             |
| Seed de sedes/turnos                | `backend/academy/management/commands/seed_sedes.py` |
| Migraciones de roadmap              | `backend/academy/migrations/0005…0013`  |
| Config REST + permisos              | `backend/config/settings.py:112-122`    |
| Roles de usuario                    | `backend/users/models.py:10`            |
| Config de Fly (release_command)     | `backend/fly.toml:13`                   |
| Recursos del frontend (CRUD)        | `frontend/lib/resources.js`             |
| Menú lateral                        | `frontend/components/Sidebar.jsx`       |
