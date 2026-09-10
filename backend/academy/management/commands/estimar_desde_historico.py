"""Extrae de los cuadrantes ya montados por dirección deportiva las dos cosas
que la app no tiene por ninguna otra vía: cuánto entrena cada jugador y en qué
nivel juega.

El libro de Excel guarda unos ocho meses de cuadrantes reales (~7.400 pistas).
De ahí salen:

  * FRECUENCIA (medida, no estimada): cuántas sesiones por semana ha hecho de
    verdad cada jugador. Va a `Jugador.sesiones_semana` y es lo que permite al
    motor repartir la dosis como la reparte Iván, en vez de dar a todos igual.

  * DIVISIÓN (estimada): dos jugadores en la misma pista tienen nivel parecido,
    así que el nivel se propaga por el grafo de co-pista desde los jugadores ya
    clasificados. Promediar comprime el rango hacia el centro, así que se
    re-expande para que la dispersión case con la de los niveles conocidos.

La estimación de división NO es una clasificación: el comando la valida
leave-one-out contra los jugadores que sí tienen división y publica el acierto,
y solo escribe sobre los que están sin clasificar, dejando nota en `notas`.

Uso:
    python manage.py estimar_desde_historico --file ~/Downloads/2026.xlsx --dry-run
    python manage.py estimar_desde_historico --file ~/Downloads/2026.xlsx \
        --meses JULIO AGOSTO          # de qué pestañas medir la frecuencia
"""
import os
import re
import unicodedata
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academy.models import Division, Jugador

# Cabeceras de bloque de pistas. El formato de invierno pone "PISTA" en la
# columna A; el de verano, el nombre de la banda.
BANDAS = {"ALTO RENDIMIENTO", "JUNIOR PROGRAM", "INTENSIVO", "ADULTOS", "PISTA"}
DIAS = [1, 4, 7, 10, 13, 17]        # columna de cada día (lunes..sábado)
RUIDO = re.compile(r"no entrena|no est|torneo|alquiler|^otra$|^libre$|entrenadores", re.I)
# Iván pega al nombre anotaciones de ejercicio y de horario:
# "Huaqi Li saques", "Marcos Romero 30 min cubos", "Noa Ribera 8.30".
FUERA = {
    "YU", "DE", "DEL", "LA", "EL", "CHICO", "CHICA", "ANOS", "MEDIO", "DIA",
    "PRUEBA", "ENTRENADORES", "JUNIOR", "PISTA", "TORNEO", "TORNEOS",
    "ALQUILER", "OTRA", "LIBRE", "SAQUES", "RESTOS", "CUBOS", "VOLEAS",
    "PUNTOS", "CONTROLES", "SOLO", "MIN", "HORA", "PARTIDOS", "DOBLES",
    "WINNER", "HERMANO", "HERMANA", "RECUPERA", "LUNES", "MARTES",
    "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO", "NO", "SI",
    "ENTRENA", "ESTA", "FISICO", "CALIENTA", "CALENTAR", "VUELVE", "PONLO",
    "RAPIDA", "TIERRA", "HOY", "PRACTICAS", "GIMNASIO", "GYM", "DESCANSA",
    "TARDE", "MANANA", "SOLA", "JUNTO", "CON", "MAS", "POR",
}
SEMANAS_POR_MES = 4.3


def _t(v):
    return "" if v is None else str(v).strip()


def clave(nombre):
    s = "".join(
        c for c in unicodedata.normalize("NFD", _t(nombre))
        if unicodedata.category(c) != "Mn"
    )
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^A-Za-z ]", " ", s)
    return " ".join(
        w.upper() for w in s.split() if len(w) > 1 and w.upper() not in FUERA
    )


class Command(BaseCommand):
    help = "Estima frecuencia y división de los jugadores desde el histórico."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument(
            "--meses", nargs="*", default=["JULIO", "AGOSTO"],
            help="Pestañas de las que medir la frecuencia (régimen actual).",
        )
        parser.add_argument(
            "--min-coincidencias", type=int, default=8,
            help="Coincidencias de pista mínimas para fiarse de una división.",
        )
        parser.add_argument(
            "--dosis-plena", action="store_true",
            help="Usar la dosis completa de cada jugador, asumiendo que TODOS "
                 "están presentes esta semana. Por defecto la dosis se pondera "
                 "por la presencia histórica, porque la app no sabe quién falta.",
        )
        parser.add_argument("--dry-run", action="store_true")

    # -- lectura ----------------------------------------------------------
    def _leer(self, path):
        try:
            import openpyxl
        except ImportError as exc:  # pragma: no cover
            raise CommandError("Falta openpyxl.") from exc
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            raise CommandError(f"No existe {path}")
        wb = openpyxl.load_workbook(path, data_only=True)
        ses = defaultdict(Counter)          # jugador -> (hoja, semana) -> sesiones
        edges = Counter()
        pistas = 0
        for ws in wb.worksheets:
            if ws.max_row < 50:
                continue
            # Cada semana arranca con "LUNES nn" en la columna A. Sin esto no
            # se puede saber en cuántas semanas ha estado un jugador, y la
            # frecuencia sale diluida entre semanas en las que ni estaba.
            semana = 0
            for f in range(1, ws.max_row + 1):
                if re.match(r"LUNES\s*\d+", _t(ws.cell(f, 1).value).upper()):
                    semana += 1
                if _t(ws.cell(f, 1).value).upper() not in BANDAS:
                    continue
                for p in range(8):
                    b = f + 1 + p * 2
                    if b + 1 > ws.max_row:
                        break
                    for c0 in DIAS:
                        if c0 + 2 > ws.max_column:
                            continue
                        celdas = []
                        for rr, cc in (
                            (b, c0), (b, c0 + 1), (b, c0 + 2),
                            (b + 1, c0), (b + 1, c0 + 1), (b + 1, c0 + 2),
                        ):
                            v = _t(ws.cell(rr, cc).value)
                            if not v or re.fullmatch(r"\d+(\.0)?", v):
                                continue
                            # Una celda puede llevar dos jugadores:
                            # "Maria Kolas/Enzo Helguera".
                            celdas.extend(
                                x for x in re.split(r"\s*[/+]\s*", v) if x.strip()
                            )
                        # Los entrenadores van en MAYÚSCULAS; el resto, jugadores.
                        nom = [
                            clave(x) for x in celdas
                            if not x.isupper() and clave(x) and not RUIDO.search(x)
                        ]
                        nom = [n for n in nom if n]
                        if not nom:
                            continue
                        pistas += 1
                        for n in nom:
                            ses[n][(ws.title, semana)] += 1
                        for i in range(len(nom)):
                            for j in range(i + 1, len(nom)):
                                if nom[i] != nom[j]:
                                    edges[frozenset((nom[i], nom[j]))] += 1
        return ses, edges, pistas

    def _anclar(self, ses, edges):
        """Ancla el histórico al roster de la app.

        El Excel escribe el mismo nombre de muchas formas ("Jennie Zhang",
        "Jennie Zhang fisico", "Jennie Zhangyi Ji") y con erratas
        ("Victoria Schnnaider"). En vez de intentar limpiar el histórico —
        que es un juego infinito de palabras sueltas — se toma como verdad la
        lista de jugadores de la app y se le atribuye cada nombre del
        histórico que comparta un apellido con él.

        Devuelve (sesiones, adyacencia, claves_por_jugador, nombres_sueltos)
        con todo ya reducido a las claves canónicas de la app.
        """
        from difflib import SequenceMatcher

        fichas = {clave(j.nombre): clave(j.nombre).split()
                  for j in Jugador.objects.filter(activo=True)}

        def parecidos(a, b):
            """¿Son el mismo token? Admite truncamientos ("Manu"/"Manuel",
            "Zhang"/"Zhangyi") y erratas ("Schnnaider"/"Schneider")."""
            if a == b:
                return True
            corto, largo = (a, b) if len(a) <= len(b) else (b, a)
            if len(corto) >= 4 and largo.startswith(corto):
                return True
            return (len(corto) >= 5
                    and SequenceMatcher(None, a, b).ratio() >= 0.82)

        def dueño(nombre):
            """A qué jugador de la app pertenece este nombre del histórico.

            Se exige que TODOS los tokens con cuerpo del nombre histórico
            queden explicados por el nombre de la ficha. Sin esa condición,
            "Andrés Vivancos" caía en Andrés Santamarta y "Eric López" en
            Eric Badenes: compartir el nombre de pila no es identidad.
            """
            tn = [t for t in nombre.split() if len(t) > 1]
            if not tn:
                return None
            mejor, mejor_sc = None, 0
            for k, tk in fichas.items():
                casan = sum(1 for t in tn if any(parecidos(t, u) for u in tk))
                if not casan:
                    continue
                # Un token de 4+ letras que no case con nada de la ficha es un
                # apellido ajeno: no es la misma persona.
                conflicto = any(
                    len(t) >= 4 and not any(parecidos(t, u) for u in tk)
                    for t in tn
                )
                if conflicto:
                    continue
                if casan > mejor_sc:
                    mejor, mejor_sc = k, casan
            return mejor

        mapa = {n: dueño(n) for n in set(ses)}
        sueltas = sum(1 for v in mapa.values() if v is None)
        ses2 = defaultdict(Counter)
        for n, c in ses.items():
            if mapa[n]:
                ses2[mapa[n]].update(c)
        ady = defaultdict(Counter)
        for par, w_ in edges.items():
            a, b = (mapa.get(x) for x in par)
            if a and b and a != b:
                ady[a][b] += w_
                ady[b][a] += w_
        porjug = defaultdict(list)
        for n, d in mapa.items():
            if d:
                porjug[d].append(n)
        return ses2, ady, porjug, sueltas

    # -- estimación de división -------------------------------------------
    @staticmethod
    def _media(ady, cur, n):
        vec = [(cur[m], w) for m, w in ady[n].items() if m in cur]
        if not vec:
            return None
        tw = sum(w for _, w in vec)
        return sum(l * w for l, w in vec) / tw

    def _estimar(self, ady, anclas, objetivo, rondas=4):
        cur = dict(anclas)
        out = {}
        for _ in range(rondas):
            nuevos = {}
            for n in objetivo:
                v = self._media(ady, cur, n)
                if v is not None:
                    nuevos[n] = v
            if not nuevos:
                break
            cur.update(nuevos)
            out.update(nuevos)
        if not out or len(anclas) < 5:
            return out
        # Corrección de contracción: promediar aplasta el rango hacia el
        # centro. Se mide cuánto lo aplasta sobre los propios anclajes y se
        # re-expande con ese factor.
        base = []
        for m in anclas:
            v = self._media(ady, {x: y for x, y in anclas.items() if x != m}, m)
            if v is not None:
                base.append(v)
        if len(base) < 5:
            return out
        ref = list(anclas.values())
        mu_r = sum(ref) / len(ref)
        sd_r = (sum((x - mu_r) ** 2 for x in ref) / len(ref)) ** 0.5
        mu_b = sum(base) / len(base)
        sd_b = (sum((x - mu_b) ** 2 for x in base) / len(base)) ** 0.5
        k = (sd_r / sd_b) if sd_b > 1e-6 else 1.0
        return {n: min(8.0, max(1.0, mu_r + (v - mu_b) * k)) for n, v in out.items()}

    def _validar(self, ady, anclas):
        """Leave-one-out: ¿cuánto acierta el método sobre los ya clasificados?"""
        err = Counter()
        for n, real in anclas.items():
            resto = {m: v for m, v in anclas.items() if m != n}
            est = self._estimar(ady, resto, [n], rondas=1).get(n)
            if est is not None:
                err[round(est) - real] += 1
        return err

    def handle(self, *args, **opts):
        with transaction.atomic():
            self._run(**opts)

    def _run(self, **opts):
        w = self.stdout.write
        ses, edges, pistas = self._leer(opts["file"])
        ses, ady, enc_keys, sueltas = self._anclar(ses, edges)
        w(self.style.MIGRATE_HEADING(
            f"\nHistórico: {pistas} pistas, {len(ses)} jugadores, "
            f"{sum(sum(c.values()) for c in ady.values()) // 2} coincidencias"
        ))

        activos = list(Jugador.objects.filter(activo=True).select_related("division"))
        enc = {j.pk: clave(j.nombre) for j in activos if clave(j.nombre) in ses}
        w(f"Fichas localizadas en el histórico: {len(enc)} de {len(activos)}")
        w(f"Nombres del histórico sin ficha en la app: {sueltas} "
          f"(ex-alumnos, invitados y celdas con texto libre)")

        # --- FRECUENCIA (medida) -----------------------------------------
        meses = [m.upper() for m in opts["meses"]]

        def ritmo(n, solo_meses):
            """Sesiones por semana CONTANDO SOLO LAS SEMANAS EN LAS QUE ESTUVO.

            Dividir entre las semanas del calendario subestima a quien lleva
            poco en la academia: un niño que llega en agosto y entrena a
            diario saldría con un cupo de 1 si se reparten sus sesiones entre
            los dos meses.
            """
            if not n:
                return 0, 0
            items = [
                (k, c) for k, c in ses[n].items()
                if not solo_meses or k[0].upper().startswith(tuple(meses))
            ]
            if not items:
                return 0, 0
            return sum(c for _, c in items), len(items)

        # Semanas que cubre cada periodo, para poder medir la presencia.
        sem_periodo = len({k for n in ses for k in ses[n]
                           if k[0].upper().startswith(tuple(meses))}) or 1
        sem_total = len({k for n in ses for k in ses[n]}) or 1

        cambios_f, sin_dato = [], []
        for j in activos:
            n = enc.get(j.pk)
            reciente, sem_r = ritmo(n, True)
            curso, sem_c = ritmo(n, False)
            # Presencia: en qué fracción de las semanas del periodo aparece.
            # La dosis dice cuánto entrena CUANDO ESTÁ; sin saber quién falta,
            # aplicarla a todo el roster pide 409 sesiones/semana cuando la
            # academia monta 210. Ponderar por presencia deja el volumen en su
            # sitio; con `--dosis-plena` se usa la dosis real, que es lo
            # correcto en cuanto haya datos de ausencias.
            presencia = 1.0 if opts["dosis_plena"] else min(
                1.0, (sem_r / sem_periodo) if reciente else (sem_c / sem_total)
            ) if (reciente or curso) else 1.0
            if reciente:
                objetivo = max(1, round(reciente / sem_r * presencia))
                fuente = f"{sem_r}/{sem_periodo} sem."
            elif curso:
                # Alumno de curso escolar que no ha hecho verano: su ritmo
                # normal sigue siendo el del curso.
                objetivo = max(1, round(curso / sem_c * presencia))
                fuente = f"curso, {sem_c}/{sem_total} sem."
            else:
                # Sin historial NO significa "no entrena" — significa que no
                # sabemos. Se deja a null para que use el cupo por defecto del
                # motor; poner 0 lo dejaría fuera del cuadrante por un dato
                # que falta, no por una decisión de dirección deportiva.
                objetivo, fuente = None, "sin datos"
                sin_dato.append(j.nombre)
            if j.sesiones_semana != objetivo:
                cambios_f.append((j.nombre, j.sesiones_semana, objetivo, reciente or curso, fuente))
            if not opts["dry_run"]:
                j.sesiones_semana = objetivo
                j.save(update_fields=["sesiones_semana"])

        # --- DIVISIÓN (estimada + validada) -------------------------------
        anclas = {enc[j.pk]: j.division.nivel for j in activos
                  if j.division and j.pk in enc}
        err = self._validar(ady, anclas)
        n_val = sum(err.values())
        sin_div = [j for j in activos if not j.division and j.pk in enc]
        est = self._estimar(ady, anclas, [enc[j.pk] for j in sin_div])
        divs = {d.nivel: d for d in Division.objects.all()}
        puestas, flojas = [], []
        for j in sin_div:
            n = enc[j.pk]
            v = est.get(n)
            if v is None:
                continue
            peso = sum(ady[n].values())
            nivel = min(8, max(1, round(v)))
            if peso < opts["min_coincidencias"]:
                flojas.append((j.nombre, nivel, peso))
                continue
            puestas.append((j.nombre, nivel, peso))
            if not opts["dry_run"]:
                j.division = divs.get(nivel)
                nota = f"división estimada del histórico ({peso} coincidencias)"
                j.notas = (j.notas + " · " + nota) if j.notas else nota
                j.save(update_fields=["division", "notas"])

        # --- informe ------------------------------------------------------
        w(self.style.MIGRATE_HEADING(
            f"\n1) FRECUENCIA medida en {', '.join(meses)}, sobre las semanas "
            "en que cada jugador aparece"
        ))
        w(f"   Jugadores con cupo cambiado: {len(cambios_f)}")
        for nom, antes, ahora, tot, fuente in sorted(
            cambios_f, key=lambda x: -(x[2] or 0)
        )[:15]:
            w(f"     {nom:32s} {antes} → {ahora}/sem  ({tot} sesiones, {fuente})")
        w(f"   Sin historial, se quedan con el cupo por defecto: {len(sin_dato)}")
        if sin_dato:
            w("     " + ", ".join(sorted(sin_dato)))

        w(self.style.MIGRATE_HEADING("\n2) DIVISIÓN estimada — validación leave-one-out"))
        if n_val:
            ex = err[0]
            pm1 = err[0] + err[1] + err[-1]
            mae = sum(abs(e) * c for e, c in err.items()) / n_val
            w(f"   Sobre {n_val} jugadores ya clasificados:")
            w(f"     acierto exacto ....... {ex}/{n_val} = {100*ex/n_val:.0f}%")
            w(f"     dentro de ±1 división  {pm1}/{n_val} = {100*pm1/n_val:.0f}%")
            w(f"     error absoluto medio . {mae:.2f} divisiones")
        w(f"   Divisiones asignadas: {len(puestas)}")
        for nom, nivel, peso in sorted(puestas, key=lambda x: x[1]):
            w(f"     división {nivel}  {nom:32s} ({peso} coincidencias)")
        if flojas:
            w(f"   Descartadas por pocas coincidencias (<{opts['min_coincidencias']}): "
              f"{len(flojas)}")
            for nom, nivel, peso in flojas:
                w(f"     ~div {nivel}?  {nom:32s} ({peso})")
        quedan = sum(1 for j in activos if not j.division) if opts["dry_run"] else \
            Jugador.objects.filter(activo=True, division__isnull=True).count()
        w(self.style.WARNING(
            f"\n   Las divisiones estimadas son PROVISIONALES (±1 en {100*(err[0]+err[1]+err[-1])/max(1,n_val):.0f}% "
            "de los casos) y quedan anotadas en `notas`. Hay que revisarlas."
        ))
        if opts["dry_run"]:
            w(self.style.WARNING("\n(dry-run: no se ha escrito nada)"))
            transaction.set_rollback(True)
