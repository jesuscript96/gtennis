# Manual de pruebas — Feedback implementado

Guía rápida para probar en local todo lo implementado del feedback de Sergio.
Los datos de demo ya están sembrados.

---

## 1. Arrancar en local

Backend (Django, puerto 8010):
```bash
cd /Users/jvch/Desktop/GTennis/backend && .venv/bin/python manage.py runserver 8010
```

Frontend (Next.js; `.env.local` ya apunta a 8010):
```bash
cd /Users/jvch/Desktop/GTennis/frontend && npm run dev
```

> Ahora mismo ya están corriendo: **frontend en http://localhost:49179**, backend en http://localhost:8010. Si arrancas tú el frontend irá a http://localhost:3000 (o 3001 si está ocupado).

## 2. Accesos

| Rol | Usuario | Contraseña |
|-----|---------|-----------|
| Super Admin (dirección) | `ivan` | `gtennis123` |
| Coach | `coach` | `demo1234` |

## 3. Datos de demo ya preparados

- **Coach Demo** (`coach`/`demo1234`) con los entrenadores **BLAS** y **JORGE I** a su cargo.
- **6 jugadores** movidos a **Junior Program**.
- Preferencia de superficie **RESINA estricta** en **Carla Guerrero Blanco**.
- El cuadrante de la última semana ya está regenerado con todo esto.

Para deshacer el demo al terminar:
```bash
cd /Users/jvch/Desktop/GTennis/backend && .venv/bin/python manage.py seed_demo_pruebas --revert
```

---

## 4. Cómo probar cada punto

Entra como **ivan** salvo que se indique lo contrario.

### Datos base (aplicados por migración)
- **#7 Horarios + verano** — *Inicio*: el turno pone `08:00–10:00 (horario de verano)` (estamos en agosto). Los botones de turno muestran los horarios de verano.
- **#8 Recintos** — *Cuadrante*: las sedes salen en orden **Resort → Sta. Bárbara (3 tierra) → Poli Bétera (2) → Mas Camarena (1)**. Liria ya no aparece.
- **#1a Tipo de pista** — *Cuadrante*: punto de color junto a `P1…P8` (tierra = marrón, resina = azul). *Inicio → modo "Cancha"*: la cancha se pinta según la superficie. Editable en *Pistas*.

### Motor
- **#17 Tardes sin satélites** — *Cuadrante*: en **T1/T2** los jugadores solo caen en pistas del **Resort**; las sedes satélite quedan vacías por la tarde (por la mañana sí se usan).
- **#6 Junior Program** — es una **escuela** (tipo de jugador), **no** una columna. Sus jugadores solo entrenan en **M2** y solo en el **Resort**. Compruébalo en *Escuelas* (Junior Program → turno único **M2**, solo Resort **Sí**); en el *Cuadrante* esos jugadores solo salen en la columna M2 (compartida con el resto) y nunca en clubs satélite.
- **#1b Preferencia de superficie** — *Datos → Pref. superficie*: verás **Carla Guerrero Blanco → Resina (estricta)**. En el cuadrante, Carla solo aparece en pistas de resina (P7, P8, Poli Bétera, Mas Camarena), nunca en tierra. Crea otra con **+ Nuevo** y regenera para probar.

### #16 Rol Coach
1. Como **ivan**: en el menú aparece **Coaches**. Entra → verás **Coach Demo**. Puedes crear coaches y asignarles entrenadores (multi-selección).
2. Cierra sesión y entra como **coach / demo1234**:
   - Abajo el rol pone **Coach**; en el menú **NO** aparece "Coaches".
   - En *Jugadores* solo ves los jugadores de BLAS y JORGE I (no los 46).

### #5 Invitados
1. *Invitados* → rellena **Nombre**, **Grupo anfitrión** y los campos nuevos: **Edad**, **Superficie**, **Jugar con** (pareja) y **Misma pista obligatoria**. Pulsa *Solicitar*.
2. El **Coach** del entrenador solicitante recibe un aviso (*Avisos*).
3. Como **ivan**, pulsa **Aprobar**: se crea un jugador con esos datos, su preferencia de superficie y su pareja preferida.

### #12 Responsables (peso por entrenador)
- Se gestiona **desde el jugador**: *Jugadores* → botón **Entrenadores** en la fila. El **grupo principal** (entrenadores de su sub-columna) se lleva el **70%** y los **secundarios** (otras sub-columnas de su mismo bloque de color) el **30%**; dentro de cada grupo, a partes iguales. Añadir/quitar (eligiendo principal o secundario) recalcula solo. Ya no hay página "Responsables" separada.
- Ejemplo: *Anjali Vasanthan* (div 5, bloque azul) → principal Jorge I/Mario/Salva (≈23% cada uno = 70%), secundario Blas 30%. *Bárbara* (div 4) → principal Blas 70%, secundarios Jorge I/Mario/Salva 10% cada uno.

### #4 Reportar movimiento de escuela
- *Jugadores* → botón **Movimiento** en una fila → escribe la escuela donde lo has visto → se crea un aviso a **dirección** (míralo en *Avisos*). La escuela del jugador **no** cambia.

### #18 Baja de jugador
- *Jugadores* → **Editar** un jugador y desmarca **Activo** → se genera un aviso de baja a dirección (*Avisos*).

### Ya estaban (repaso rápido)
- **#2** varios responsables + prioridad (*Jugadores → Entrenadores*) · **#3** divisiones por entrenador (*Entrenadores*) · **#9** jugadores numerados (*Jugadores*) · **#10** torneo/franjas (*Disp. entrenadores*) · **#11** vacaciones (*Vacaciones*) · **#13** mantenimiento (*Mantenimiento*) · **#15** edad por fecha de nacimiento (*Jugadores → Editar*).

---

## 5. Nota sobre producción

Estos cambios están probados en local. El despliegue a producción es **en dos
pasos** (Vercel y Fly NO se disparan del mismo sitio):

1. **Frontend (Vercel)** — sí se auto-despliega al hacer `git push` a `main`.
2. **Backend (Fly)** — NO se auto-despliega con el push. Hay que lanzarlo a mano
   desde `backend/`:
   ```bash
   cd backend
   fly deploy --app gtennis-api-jesus --strategy rolling
   ```
   El `release_command` de `fly.toml` ejecuta automáticamente
   `python manage.py migrate --noinput && python manage.py seed_base`, así que
   las migraciones (incluidas las de datos de #7/#8/#12) se aplican solas sobre
   el Postgres de producción.

> Hecho el deploy, para marcar el feedback como resuelto en la app:
> ```bash
> fly ssh console -a gtennis-api-jesus -C "python manage.py sync_feedback_estados"
> ```

URLs de producción:
- App: <https://gtennis.vercel.app/>
- API: <https://gtennis-api-jesus.fly.dev/api/>
- Admin Django: <https://gtennis-api-jesus.fly.dev/admin/>
