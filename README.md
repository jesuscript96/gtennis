# G Tenis — Web App

Automatización del cuadrante semanal de una academia de tenis de alto rendimiento
(Valencia). Monorepo: motor de emparejamiento (OR-Tools) + API (Django) + front
(Next.js).

## Arquitectura

| Pieza | Stack | Dónde (producción) |
|---|---|---|
| Frontend | Next.js (React) | Vercel (`frontend/`) |
| API + admin | Django + DRF | Render · Frankfurt (UE) |
| Motor | OR-Tools CP-SAT (Celery + cron) | Render · Frankfurt |
| BD | PostgreSQL | Render · Frankfurt (UE) |
| Fotos | Object storage S3 (UE) | URL en `Jugador.foto_url` |

> **RGPD**: se almacenan datos de salud (lesiones/bajas) = Art. 9 categoría
> especial, y hay menores. Producción **debe** correr en la UE y exige
> consentimiento (campo `consentimiento_rgpd` por jugador).

## Arranque local (rápido, SQLite)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_base                      # sedes, pistas, turnos, divisiones
python manage.py import_excel --file ~/Downloads/2026.xlsx   # jugadores/coaches reales
python manage.py createsuperuser
python manage.py runserver 8010        # 8000 suele estar ocupado por otros proyectos
```

> ⚠️ **Puerto**: usa un puerto dedicado (aquí `8010`). Si el backend comparte el
> 8000 con otra app (p. ej. un uvicorn/FastAPI), el frontend llama a la app
> equivocada y las páginas se rompen. `frontend/.env.local` ya apunta a `8010`.

Frontend (app de gestión):

```bash
cd frontend
# .env.local ya existe apuntando a http://localhost:8010/api
npm install && npm run dev          # http://localhost:3000
```

Entra en `http://localhost:3000/login` con el superusuario que creaste. La app
incluye CRUD completo de todas las entidades + el cuadrante con acciones.

## App de gestión (CRUDs completos)

Tras login (token DRF), la SPA cubre:

- **Panel** — métricas (jugadores, menores/RGPD, entrenadores, sedes, rencillas, contratos) y estado de la semana.
- **Cuadrante** — rejilla pistas × turnos con los 6 estados de color y **avatares** (jugadores con borde dorado, entrenadores con borde negro); botones **Generar semana**, **Regenerar tarde** y **Publicar**.
- **Ausencias y estados** — marca lesiones, torneos, climatología, etc. por jugador/día/turno. Tras marcar, **Generar/Regenerar** en el Cuadrante para que impacten.
- **Criterios del motor** — ajusta los **pesos** (prioridades) de los criterios blandos y la regla de vecindad sin tocar código.
- **Semanas** — crear, generar y publicar cuadrantes.
- **CRUD**: Jugadores, Entrenadores, Sedes, Pistas, Divisiones, Rencillas (vetos) y Contratos de patrocinio.

UI **glassmorphism (estilo Apple)** sobre imagen de fondo: `frontend/public/background.svg`
(sustituible por un `.jpg` real). Lectura pública; **escritura requiere login**
(`IsAuthenticatedOrReadOnly` + token DRF).

## Arranque con Docker (Postgres, como en producción)

```bash
docker compose up --build
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_base
```

## Estructura

```
backend/
  config/        settings, urls, celery
  users/         User con rol (SUPERADMIN/ENTRENADOR) — RBAC
  academy/       Sede, Pista, Turno, Division, Entrenador, Jugador, Rencilla, Contrato
                 + management/commands: seed_base, import_excel
  scheduling/    Semana, Disponibilidad, Asignacion, Estado + tasks (5 PM Rule)
  engine/        pairing.py (motor puro, testeable) + service.py (orquestación)
  integrations/  sesame.py (skeleton + fallback manual)
frontend/
  app/(auth)/login         pantalla de login
  app/(dash)/              panel, cuadrante, semanas + CRUD de cada entidad
  components/              Sidebar, ResourceCrud (CRUD genérico)
  lib/                     api.js (cliente + token), resources.js (config CRUD)
```

## Mapa PRD → código

| PRD | Estado | Dónde |
|---|---|---|
| §01 RBAC (3 roles) | ✅ | `users.User`, admin |
| §02 4 turnos + regeneración solo de tarde | ✅ | `engine.service.regenerate_afternoon` |
| §03 Matriz de estados (6 colores + subtipos) | ✅ | `scheduling.Estado` / `Disponibilidad` |
| §4.1 Regla de vecindad N±1 | ✅ (dura) | `engine.pairing` |
| §4.2 Rencillas (veto cruzado) | ✅ (dura) | `academy.Rencilla` + motor |
| §4.3 Antirrepetición / rotación | 🟡 (blanda, parejas + rotación coach) | `engine.service._recent_partners`, `_assign_coaches` |
| §4.4 Contrato patrocinio ≥1 mañana + ≥1 tarde | 🟡 (preferencia; garantía cross-turno pendiente) | `_assign_coaches` |
| §05 Capacidad + desbordamiento a satélites | ✅ | `engine.pairing` (densidad 2–4, satélites) |
| §06 API Sésame | 🟡 (skeleton + fallback manual) | `integrations.sesame` |
| §07 5 PM Rule (deadlines, generación domingo) | 🟡 (tasks + cron; falta email/push) | `scheduling.tasks`, `render.yaml` |

✅ implementado · 🟡 MVP / falta endurecer en fase siguiente.

## Tests

```bash
cd backend && python manage.py test engine
```
