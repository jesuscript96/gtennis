"""Ensayo del despliegue del orden de la aplicación sobre una copia de
producción, en un PostgreSQL de usar y tirar (11/11/2026).

    backend/.venv/bin/python backend/scripts/ensayo_orden.py --copia backup_prod_AAAA-MM-DD.json

1. Arranca un PostgreSQL propio en --trabajo (initdb la primera vez).
2. Con el código de producción (--ref, por defecto origin/main) crea la base y
   carga la copia: así está producción justo antes de desplegar.
3. Con el código nuevo (este árbol) migra, y comprueba que cada falta, cada
   fila de «Disp. entrenadores» y cada interruptor están en su sitio nuevo y en
   el archivo de migraciones.
4. Deshace las migraciones nuevas y compara la base, fila a fila y campo a
   campo, con la de antes de migrar: tiene que ser idéntica.
5. Vuelve a migrar, para ver que se puede repetir.

No toca ninguna otra base. Deja el informe en --trabajo/informe.txt.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
BACKEND = AQUI.parent
REPO = BACKEND.parent
PY = sys.executable
FUERA_DUMP = ["contenttypes", "auth.permission", "sessions", "admin"]
APPS = ["users", "academy", "scheduling", "torneos", "evaluaciones"]
PG = "/opt/homebrew/opt/postgresql@15/bin"
# PostgreSQL no arranca en macOS si el idioma del entorno no es válido.
os.environ["LC_ALL"] = "C"

informe = []


def log(*a):
    linea = " ".join(str(x) for x in a)
    print(linea, flush=True)
    informe.append(linea)


def run(cmd, cwd=None, env=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if check and r.returncode != 0:
        log("FALLO:", " ".join(map(str, cmd)))
        log(r.stdout[-4000:], r.stderr[-4000:])
        raise SystemExit(1)
    return r


def entorno(url):
    e = dict(os.environ)
    e.update(DATABASE_URL=url, ANTHROPIC_API_KEY="", GOOGLE_SERVICE_ACCOUNT_JSON="", DEBUG="true",
             SECRET_KEY="ensayo-local")
    return e


def manage(codigo, url, *args, check=True):
    return run([PY, "manage.py", *args], cwd=codigo, env=entorno(url), check=check)


def volcar(codigo, url, destino):
    excl = sum([["-e", x] for x in FUERA_DUMP], [])
    manage(codigo, url, "dumpdata", *excl, "--indent", "0", "-o", str(destino))
    return {(o["model"], str(o["pk"])): o["fields"] for o in json.load(open(destino))}


def comparar(a, b, ignorar_modelos=()):
    dif = []
    for k in sorted(set(a) | set(b)):
        if k[0] in ignorar_modelos:
            continue
        if k not in a:
            dif.append(f"sobra {k}")
        elif k not in b:
            dif.append(f"falta {k}")
        elif a[k] != b[k]:
            campos = [c for c in set(a[k]) | set(b[k]) if a[k].get(c) != b[k].get(c)]
            dif.append(f"cambia {k}: " + ", ".join(f"{c}: {a[k].get(c)!r} → {b[k].get(c)!r}" for c in campos))
    return dif


AUTOMATICOS = {"created_at", "updated_at", "creado", "actualizado", "creada", "actualizada"}


def contenido(d, ignorar_modelos=()):
    """Las filas por tabla sin su clave ni las horas automáticas: para comparar
    dos migraciones cuyas filas nuevas llevan claves distintas."""
    from collections import Counter
    out = {}
    for (m, _), f in d.items():
        if m in ignorar_modelos:
            continue
        limpio = {k: v for k, v in f.items() if k not in AUTOMATICOS}
        out.setdefault(m, Counter())[json.dumps(limpio, sort_keys=True, ensure_ascii=False)] += 1
    return out


def ultimas_migraciones(arbol):
    out = {}
    for app in APPS:
        nombres = sorted(p.stem for p in (arbol / app / "migrations").glob("0*.py"))
        out[app] = nombres[-1]
    return out


COMPROBAR = r'''
import json
from datetime import timedelta
from users.models import ArchivoMigracion
from scheduling.models import AusenciaJugador, Disponibilidad, DisponibilidadEntrenador
from academy.models import Entrenador, VacacionesEntrenador
N = "scheduling.0034_un_solo_registro_de_faltas"
problemas = []
quedan = Disponibilidad.objects.exclude(estado="EXTRA").count()
if quedan: problemas.append(f"quedan {quedan} faltas en el parte semanal")
if DisponibilidadEntrenador.objects.exists(): problemas.append("quedan filas de Disp. entrenadores")
if Entrenador.objects.filter(disponible_semana=False).exists(): problemas.append("quedan interruptores apagados")
borr = ArchivoMigracion.objects.filter(migracion=N, accion="borrado", modelo="scheduling.disponibilidad")
from scheduling.models import Semana
semanas = {s.pk: s.fecha_inicio for s in Semana.objects.all()}
sueltos = 0
for e in borr:
    d = e.datos
    fecha = semanas[d["semana_id"]] + timedelta(days=d["dia"])
    hay = AusenciaJugador.objects.filter(jugador_id=d["jugador_id"], fecha_inicio=fecha, fecha_fin=fecha,
                                         ambito=d["ambito"], estado=d["estado"], subtipo=d["subtipo"],
                                         tardia=d["tardia"]).exists()
    if not hay:
        if d["estado"] == "DISPONIBLE": sueltos += 1
        else: problemas.append(f"falta sin pasar: {d}")
creadas = ArchivoMigracion.objects.filter(migracion=N, accion="creado")
for e in creadas:
    M = {"scheduling.ausenciajugador": AusenciaJugador, "academy.vacacionesentrenador": VacacionesEntrenador}[e.modelo]
    if not M.objects.filter(pk=e.pk_original).exists(): problemas.append(f"no existe lo creado {e.modelo} {e.pk_original}")
resumen = {r["migracion"] + " " + r["accion"] + " " + r["modelo"]: r["n"] for r in
           ArchivoMigracion.objects.values("migracion", "accion", "modelo").order_by().annotate(n=__import__("django.db.models", fromlist=["Count"]).Count("id"))}
print(json.dumps({"problemas": problemas, "disponible_suelto": sueltos, "archivo": resumen}, ensure_ascii=False, indent=1))
'''

VIEJO_ESCRIBE = r"""
from datetime import date, timedelta
from academy.models import Entrenador, Jugador, VacacionesEntrenador
from scheduling.models import Disponibilidad, Semana
from evaluaciones.models import Informe
s = Semana.objects.order_by("-fecha_inicio").first()
j = Jugador.objects.filter(activo=True).order_by("pk").first()
e = Entrenador.objects.filter(activo=True).order_by("pk").first()
Disponibilidad.objects.update_or_create(semana=s, jugador=j, dia=3, ambito="DIA",
                                        defaults={"estado": "AUSENCIA_JUGADOR", "nota": "desde la versión vieja"})
VacacionesEntrenador.objects.create(entrenador=e, fecha_inicio=date.today(), fecha_fin=date.today(), motivo="vieja")
Entrenador.objects.filter(pk=e.pk).update(disponible_semana=False)
Informe.objects.create(jugador=j)
print("ok")
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copia", required=True, help="JSON de dumpdata de producción")
    ap.add_argument("--ref", default="origin/main", help="código de producción (git)")
    ap.add_argument("--trabajo", default=str(Path(os.environ.get("TMPDIR", "/tmp")) / "ensayo_orden"))
    ap.add_argument("--puerto", type=int, default=55432)
    ap.add_argument("--mantener", action="store_true", help="no parar PostgreSQL al acabar")
    o = ap.parse_args()
    t = Path(o.trabajo)
    t.mkdir(parents=True, exist_ok=True)
    datos = t / "pgdata"
    if not datos.exists():
        run([f"{PG}/initdb", "-D", str(datos), "-U", "ensayo", "-A", "trust", "-E", "UTF8"])
    run([f"{PG}/pg_ctl", "-D", str(datos), "-o", f"-p {o.puerto} -c unix_socket_directories=''",
         "-l", str(t / "pg.log"), "-w", "start"], check=False)
    url = f"postgresql://ensayo@127.0.0.1:{o.puerto}/ensayo"
    try:
        run([f"{PG}/dropdb", "-h", "127.0.0.1", "-p", str(o.puerto), "-U", "ensayo", "--if-exists", "ensayo"])
        run([f"{PG}/createdb", "-h", "127.0.0.1", "-p", str(o.puerto), "-U", "ensayo", "ensayo"])

        # Código de producción.
        prod = t / "prod"
        shutil.rmtree(prod, ignore_errors=True)
        prod.mkdir()
        tar = subprocess.run(["git", "-C", str(REPO), "archive", o.ref, "backend"], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(prod)], input=tar.stdout, check=True)
        prod_backend = prod / "backend"
        log(f"Código de producción: {o.ref}; copia: {o.copia}")

        manage(prod_backend, url, "migrate", "--noinput")
        # Las migraciones siembran datos; la copia trae los suyos (migrate +
        # flush + loaddata, como cuando se copió producción a local).
        manage(prod_backend, url, "flush", "--noinput")
        manage(prod_backend, url, "loaddata", str(Path(o.copia).resolve()))
        antes = volcar(prod_backend, url, t / "A_antes.json")
        log(f"1. Producción reconstruida: {len(antes)} filas.")

        # Migrar con el código nuevo.
        r = manage(BACKEND, url, "migrate", "--noinput")
        aplicadas = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("Applying")]
        log("2. Migraciones nuevas:\n   " + "\n   ".join(aplicadas))
        r = manage(BACKEND, url, "shell", "-c", COMPROBAR)
        comp = json.loads(r.stdout)
        log("3. Comprobación tras migrar:", json.dumps(comp, ensure_ascii=False, indent=1))
        despues = volcar(BACKEND, url, t / "B_despues.json")
        nuevas = [k for k in despues if k not in antes]
        quitadas = [k for k in antes if k not in despues]
        por = lambda ks: dict(sorted({m: sum(1 for x in ks if x[0] == m) for m, _ in ks}.items()))
        log("   Filas nuevas por tabla:", por(nuevas))
        log("   Filas quitadas por tabla (deben estar todas en el archivo):", por(quitadas))
        archivadas = {(e["fields"]["modelo"], e["fields"]["pk_original"]) for e in
                      [{"fields": f} for (m, _), f in despues.items() if m == "users.archivomigracion"]
                      if e["fields"]["accion"] == "borrado"}
        sin_archivo = [k for k in quitadas if k not in archivadas]
        log("   Quitadas que NO están en el archivo:", len(sin_archivo), sin_archivo[:5])

        # Deshacer con el código nuevo hasta el estado de producción.
        objetivo = ultimas_migraciones(prod_backend)
        for app in ["scheduling", "torneos", "evaluaciones", "academy", "users"]:
            manage(BACKEND, url, "migrate", app, objetivo[app], "--noinput")
        log("4. Deshecho hasta:", objetivo)
        vuelta = volcar(prod_backend, url, t / "C_deshecho.json")
        dif = comparar(antes, vuelta)
        log(f"   Diferencias con la producción original: {len(dif)}")
        for d in dif[:40]:
            log("   ", d)

        # Volver a migrar.
        manage(BACKEND, url, "migrate", "--noinput")
        otra = volcar(BACKEND, url, t / "D_otra_vez.json")
        c1 = contenido(despues, ("users.archivomigracion",))
        c2 = contenido(otra, ("users.archivomigracion",))
        dif2 = [m for m in sorted(set(c1) | set(c2)) if c1.get(m) != c2.get(m)]
        log(f"5. Migrar otra vez: {len(dif2)} tablas con contenido distinto de la primera vez"
            f" (sin contar el archivo ni las horas automáticas): {dif2}")
        # Mientras dura el despliegue, la versión vieja sigue atendiendo con la
        # base ya migrada: lo que escriba tiene que entrar y no perderse.
        r = manage(prod_backend, url, "shell", "-c", VIEJO_ESCRIBE, check=False)
        viejo_ok = r.returncode == 0 and "ok" in r.stdout
        log("6. La versión vieja escribe sobre la base nueva:", "sin errores" if viejo_ok else r.stderr[-1500:])
        antes_repaso = volcar(BACKEND, url, t / "E_antes_repaso.json")
        r = manage(BACKEND, url, "unificar_faltas", "--aplicar")
        log("   Repaso:", r.stdout.strip().replace("\n", " | "))
        nombre = next((l.split("«")[1].split("»")[0] for l in r.stdout.splitlines() if "«" in l), None)
        r2 = manage(BACKEND, url, "unificar_faltas")
        repaso_ok = "Nada que pasar" in r2.stdout
        log("   Después del repaso:", r2.stdout.strip().replace("\n", " | "))
        if nombre:
            manage(BACKEND, url, "archivo_migraciones", "--deshacer", nombre)
            tras = volcar(BACKEND, url, t / "F_repaso_deshecho.json")
            dif3 = comparar(antes_repaso, tras)
            log(f"   Deshacer el repaso: {len(dif3)} diferencias con antes del repaso.", dif3[:5])
            repaso_ok = repaso_ok and not dif3
        ok = not comp["problemas"] and not sin_archivo and not dif and viejo_ok and repaso_ok
        log("RESULTADO:", "BIEN: nada se pierde y se deshace exacto." if ok else "HAY PROBLEMAS (ver arriba).")
    finally:
        (t / "informe.txt").write_text("\n".join(informe))
        if not o.mantener:
            run([f"{PG}/pg_ctl", "-D", str(datos), "-m", "fast", "stop"], check=False)


if __name__ == "__main__":
    main()
