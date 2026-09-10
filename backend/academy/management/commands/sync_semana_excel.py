"""Sincroniza el roster de UNA semana desde el Excel de dirección deportiva.

El Excel de Iván tiene, por cada semana y en la fila 14, una cabecera del tipo
"AGOSTO 24 AL 30" seguida de cuatro columnas:

    col+0  ALTO RENDIMIENTO          (jugadores)
    col+1  JUNIOR PROGRAM FULL DAY   (jugadores)
    col+2  JUNIOR PROGRAM HALF DAY   (jugadores, y más abajo ENTRENADORES JUNIOR 7)
    col+3  ENTRENADORES ALTO.R       (entrenadores)

Este comando lee ese bloque y deja la BD alineada con él:

  * crea las fichas de jugador que faltan y reactiva las que estaban de baja,
  * corrige la escuela de cada jugador según la columna en la que aparece,
  * marca `disponible_semana` de los entrenadores que no salen esa semana,
  * crea / reactiva / renombra los entrenadores de la semana.

A diferencia de `import_alumnos`, la fuente aquí es la rejilla escrita a mano,
no el export del software de gestión: los jugadores creados NO tienen
`codigo_cliente`. Se marcan en `notas` para poder reconciliarlos después.

Con `--inferir-divisiones` además propone una división provisional para los
jugadores sin clasificar, deducida de con quién los pone Iván en el cuadrante
de esa misma pestaña (dos jugadores de la misma pista están a ±1 división).
Es una semilla para que el motor no quede ciego, NO una clasificación real:
queda anotada como provisional y hay que revisarla.

Uso:
    python manage.py sync_semana_excel --file ~/Downloads/2026.xlsx \
        --hoja AGOSTO --semana "AGOSTO 24 AL 30" --inferir-divisiones --dry-run
"""
import os
import re
import unicodedata
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academy.models import Division, Entrenador, Escuela, Jugador

FILA_CABECERA = 14
FILA_ROSTER_INI = 16
FILA_ROSTER_FIN = 89
DIAS_COLS = [1, 4, 7, 10, 13]          # Lunes..Viernes (col de la pista)
BANDAS = {"ALTO RENDIMIENTO", "JUNIOR PROGRAM", "INTENSIVO", "ADULTOS"}
RUIDO = re.compile(
    r"no entrena|no est|entrenadores|torneo|prueba$", re.I
)
# Nombres que el Excel escribe de varias formas para la misma persona.
ALIAS = {
    "JAVI BALLESTER": "Javier Ballester Galarza",
    "JENNIE ZHANG": "Jennie Zhangyi Ji (Yu)",
    "JENNY": "Jennie Zhangyi Ji (Yu)",
    "OJAS MALHORTA": "Ojas Malhotra",
    "MARIA ANDRIENKO": "Maria Adrienko",
    "MANU MENDEZ": "Manuel Méndez Domínguez",
    "BAI RUNCAY": "Bai Runkai (Yu)",
    "ALEX GARCIA": "Alejandro Garcia Carbajal",
    "NIK GUILIN": "Xu Guilin (Yu) Nik",
    "NIK": "Xu Guilin (Yu) Nik",
    "NAZIM": "Nazim Malikov",
    "ARJUN": "Arjun Malhotra",
    "SOHAM": "Sohan Malhotra",
    "SOHAN MALHOTRA": "Sohan Malhotra",
    "MATIAS": "Mathias Bourassa",
    "MATHIAS BOURASSA": "Mathias Bourassa",
    "PABLO PALOMARES": "Pablo Palomares Polanco",
    "MARC MARTI": "Marc Marin",
}
# Entrenadores: nombre corto en la BD -> nombre real en el Excel.
COACH_RENOMBRA = {
    "SALVA": "SALVA BARCALA", "SALVA B": "SALVA BARCALA",
    "MARIO": "MARIO MUNIESA", "MARIO M": "MARIO MUNIESA",
    "NACHO C": "NACHO CALVO",
    "VICTOR R": "VICTOR REDONDO",
    "SANTI": "SANTI PANZARASA", "SANTI P": "SANTI PANZARASA",
    "PABLO": "PABLO GIL", "PABLO G": "PABLO GIL",
    "JORGE I": "JORGE IBAÑEZ",
    "JORGE": "JORGE GARCIA",
    "BLAS": "BLAS GALLEGO",
    "EMILIO": "EMILIO SORIO", "EMILIO S": "EMILIO SORIO",
    "JAVI": "JAVI GIMENEZ", "JAVI G": "JAVI GIMENEZ",
    "SERGIO G": "SERGIO GALLEGO",
    "ALVARO": "ALVARO MANTOAN", "ALVARO M": "ALVARO MANTOAN",
    "ALVARO MANTUAN": "ALVARO MANTOAN",
    "MIKEL": "MIKEL ROMERO",
    "DANI": "DANI GIMENO", "DANI GIMENRO": "DANI GIMENO",
}


def _txt(v):
    return "" if v is None else str(v).strip()


def clave(nombre):
    """Clave de comparación: sin tildes, sin paréntesis, sin dígitos ni ruido."""
    s = _txt(nombre)
    s = "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^A-Za-z ]", " ", s)
    fuera = {"YU", "DE", "DEL", "LA", "EL", "CHICO", "CHICA", "ANOS",
             "MEDIO", "DIA", "PRUEBA"}
    return " ".join(
        w.upper() for w in s.split() if len(w) > 1 and w.upper() not in fuera
    )


def clave_semana(valor):
    """Clave de la cabecera de semana. A diferencia de `clave`, CONSERVA los
    dígitos: "AGOSTO 24 AL 30" y "AGOSTO 03 AL 09" deben distinguirse."""
    s = "".join(
        c for c in unicodedata.normalize("NFD", _txt(valor))
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(re.sub(r"[^A-Za-z0-9]", " ", s).upper().split())


def clave_coach(nombre):
    """Clave de entrenador. A diferencia de `clave`, CONSERVA las iniciales
    sueltas: "JORGE I" (Ibáñez) y "JORGE" (García) son personas distintas."""
    s = "".join(
        c for c in unicodedata.normalize("NFD", _txt(nombre))
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(re.sub(r"[^A-Za-z]", " ", s).upper().split())


def canon(nombre):
    """Nombre canónico del Excel: aplica los alias conocidos."""
    return ALIAS.get(clave(nombre), _txt(nombre))


def limpio(valor):
    """¿Es esta celda el nombre de una persona (y no una nota o cabecera)?"""
    s = _txt(valor)
    return bool(clave(s)) and not RUIDO.search(s)


class Command(BaseCommand):
    help = "Alinea jugadores y entrenadores con el roster de una semana del Excel."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Ruta del .xlsx")
        parser.add_argument("--hoja", default="AGOSTO", help="Pestaña (mes)")
        parser.add_argument(
            "--semana", required=True,
            help='Cabecera de la semana en la fila 14, p. ej. "AGOSTO 24 AL 30"',
        )
        parser.add_argument(
            "--inferir-divisiones", action="store_true",
            help="Propone división provisional deduciéndola del cuadrante.",
        )
        parser.add_argument("--dry-run", action="store_true")

    # -- lectura del Excel -------------------------------------------------
    def _abrir(self, path, hoja):
        try:
            import openpyxl
        except ImportError as exc:  # pragma: no cover
            raise CommandError("Falta openpyxl (pip install openpyxl).") from exc
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            raise CommandError(f"No existe el fichero {path}")
        wb = openpyxl.load_workbook(path, data_only=True)
        if hoja not in wb.sheetnames:
            raise CommandError(f"La pestaña {hoja!r} no existe. Hay: {wb.sheetnames}")
        return wb[hoja]

    def _roster(self, ws, semana):
        """Devuelve (alto_rendimiento, junior, entrenadores) de la semana."""
        col = None
        for c in range(1, ws.max_column + 1):
            if clave_semana(ws.cell(FILA_CABECERA, c).value) == clave_semana(semana):
                col = c
                break
        if col is None:
            raise CommandError(
                f"No encuentro la cabecera {semana!r} en la fila {FILA_CABECERA}."
            )
        ar, jp, coaches = [], [], []
        for fila in range(FILA_ROSTER_INI, FILA_ROSTER_FIN + 1):
            if limpio(ws.cell(fila, col).value):
                ar.append(_txt(ws.cell(fila, col).value))
            if limpio(ws.cell(fila, col + 1).value):
                jp.append(_txt(ws.cell(fila, col + 1).value))
            # col+2 mezcla jugadores de media jornada y, tras la sub-cabecera
            # "ENTRENADORES JUNIOR 7", entrenadores.
            if limpio(ws.cell(fila, col + 3).value):
                coaches.append(_txt(ws.cell(fila, col + 3).value))
        # Entrenadores junior: todo lo que va bajo la sub-cabecera en col+2.
        tras_cabecera = False
        for fila in range(FILA_ROSTER_INI, FILA_ROSTER_FIN + 1):
            v = _txt(ws.cell(fila, col + 2).value)
            if "ENTRENADOR" in v.upper():
                tras_cabecera = True
                continue
            if tras_cabecera and limpio(v):
                coaches.append(v)
            elif limpio(v):
                jp.append(v)
        return ar, jp, coaches

    def _cuadrante(self, ws):
        """Lista de pistas del mes: [[nombre, ...], ...] (solo jugadores)."""
        pistas = []
        for fila in range(1, ws.max_row + 1):
            if _txt(ws.cell(fila, 1).value).upper() not in BANDAS:
                continue
            for pista in range(8):
                base = fila + 1 + pista * 2
                for c0 in DIAS_COLS:
                    celdas = []
                    for rr, cc in (
                        (base, c0), (base, c0 + 1), (base, c0 + 2),
                        (base + 1, c0), (base + 1, c0 + 1), (base + 1, c0 + 2),
                    ):
                        if rr > ws.max_row:
                            continue
                        v = _txt(ws.cell(rr, cc).value)
                        if not v or re.fullmatch(r"\d+(\.0)?", v):
                            continue
                        celdas.append(v)
                    # Los entrenadores van en MAYÚSCULAS; los jugadores no.
                    jug = [x for x in celdas if not x.isupper() and limpio(x)]
                    if len(jug) >= 2:
                        pistas.append(jug)
        return pistas

    # -- inferencia de división -------------------------------------------
    def _inferir(self, pistas, niveles):
        """Propaga nivel por adyacencia de pista. Devuelve {clave: nivel}."""
        ady = defaultdict(Counter)
        for jug in pistas:
            ks = [clave(canon(x)) for x in jug]
            for i, a in enumerate(ks):
                for b in ks[i + 1:]:
                    if a and b and a != b:
                        ady[a][b] += 1
                        ady[b][a] += 1
        conocidos = dict(niveles)
        propuesto = {}
        for _ in range(3):                      # 3 pasadas: converge rápido
            nuevos = {}
            for k, vecinos in ady.items():
                if k in conocidos:
                    continue
                votos = [(conocidos[v], w) for v, w in vecinos.items()
                         if v in conocidos]
                if not votos:
                    continue
                total = sum(w for _, w in votos)
                nuevos[k] = round(sum(n * w for n, w in votos) / total)
            if not nuevos:
                break
            conocidos.update(nuevos)
            propuesto.update(nuevos)
        return propuesto

    # -- ejecución ---------------------------------------------------------
    def handle(self, *args, **opts):
        # Todo el trabajo va dentro de una transacción para que --dry-run pueda
        # ejecutar el flujo real y deshacerlo al final.
        with transaction.atomic():
            self._run(**opts)

    def _run(self, **opts):
        ws = self._abrir(opts["file"], opts["hoja"])
        ar, jp, coaches_excel = self._roster(ws, opts["semana"])
        seco = opts["dry_run"]

        esc_ar, _ = Escuela.objects.get_or_create(nombre="Alto Rendimiento")
        esc_jp, _ = Escuela.objects.get_or_create(nombre="Junior Program")

        # Índice de jugadores por clave de nombre.
        indice = {}
        for j in Jugador.objects.all():
            indice.setdefault(clave(j.nombre), j)

        def localizar(nombre):
            k = clave(canon(nombre))
            if k in indice:
                return indice[k]
            partes = set(k.split())
            for kk, j in indice.items():
                otras = set(kk.split())
                if partes and (partes <= otras or otras <= partes):
                    return j
            return None

        creados, reactivados, movidos, vistos = [], [], [], set()
        # La columna del Excel se llama "JUNIOR PROGRAM FULL DAY": esos niños
        # entrenan los cinco días, así que su cupo semanal no es el genérico.
        cupos = {esc_jp.id: 5}
        for nombres, escuela in ((ar, esc_ar), (jp, esc_jp)):
            for nombre in nombres:
                j = localizar(nombre)
                if j is None:
                    j = Jugador(
                        nombre=canon(nombre),
                        escuela=escuela,
                        activo=True,
                        notas="alta desde el cuadrante · sin codigo_cliente",
                        sesiones_semana=cupos.get(escuela.id),
                    )
                    if not seco:
                        j.save()
                        indice[clave(j.nombre)] = j
                    creados.append((j.nombre, escuela.nombre))
                else:
                    if not j.activo:
                        j.activo = True
                        reactivados.append(j.nombre)
                    if j.escuela_id != escuela.id:
                        movidos.append((j.nombre, j.escuela and j.escuela.nombre,
                                        escuela.nombre))
                        j.escuela = escuela
                    if j.sesiones_semana != cupos.get(escuela.id):
                        j.sesiones_semana = cupos.get(escuela.id)
                    if not seco:
                        j.save()
                vistos.add(j.pk or clave(j.nombre))

        # Jugadores con ficha que no están en el roster de la semana.
        fuera = [
            j.nombre for j in Jugador.objects.filter(activo=True)
            if j.pk not in vistos
        ]

        # -- divisiones provisionales -------------------------------------
        propuestas = []
        if opts["inferir_divisiones"]:
            niveles = {
                clave(n): lvl for n, lvl in Jugador.objects.filter(
                    activo=True, division__isnull=False
                ).values_list("nombre", "division__nivel")
            }
            inferido = self._inferir(self._cuadrante(ws), niveles)
            divs = {d.nivel: d for d in Division.objects.all()}
            for j in Jugador.objects.filter(activo=True, division__isnull=True):
                nivel = inferido.get(clave(j.nombre))
                if nivel is None or nivel not in divs:
                    continue
                propuestas.append((j.nombre, nivel))
                if not seco:
                    j.division = divs[nivel]
                    nota = "división provisional inferida del cuadrante"
                    j.notas = (j.notas + " · " + nota) if j.notas else nota
                    j.save(update_fields=["division", "notas"])

        # -- entrenadores ---------------------------------------------------
        # Nombre real -> lo que aparece en el Excel de la semana.
        quiere = set()
        for c in coaches_excel:
            nombre = re.sub(
                r"\s*(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado)\s*\d*",
                "", c, flags=re.I,
            ).strip()
            quiere.add(COACH_RENOMBRA.get(clave_coach(nombre), nombre).upper())

        renombrados, altas_c, apagados, fusionados = [], [], [], []
        reactivados_c = []
        por_clave = defaultdict(list)
        for e in Entrenador.objects.all():
            destino = COACH_RENOMBRA.get(clave_coach(e.nombre), e.nombre).upper()
            por_clave[destino].append(e)

        for destino, registros in por_clave.items():
            # El que tenga usuario o relaciones manda; el resto son duplicados.
            registros.sort(
                key=lambda e: (
                    e.user_id is not None,
                    e.jugadores_responsable.count(),
                    e.activo,
                ),
                reverse=True,
            )
            principal, duplicados = registros[0], registros[1:]
            if principal.nombre.upper() != destino:
                renombrados.append((principal.nombre, destino))
                principal.nombre = destino
            activo = destino in quiere or principal.gestiona_todos_jugadores
            if principal.activo != activo or principal.disponible_semana != activo:
                (apagados if not activo else reactivados_c).append(destino)
            principal.activo = activo or principal.activo
            principal.disponible_semana = activo
            if not seco:
                principal.save()
            for d in duplicados:
                fusionados.append((d.nombre, destino))
                if not seco:
                    d.delete()

        for destino in sorted(quiere):
            if destino not in por_clave:
                altas_c.append(destino)
                if not seco:
                    Entrenador.objects.create(
                        nombre=destino, activo=True, disponible_semana=True
                    )

        sin_division = Jugador.objects.filter(
            activo=True, division__isnull=True
        ).count()

        # -- informe ---------------------------------------------------------
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING(
            f"\nRoster {opts['semana']} — {len(ar)} alto rendimiento, "
            f"{len(jp)} junior, {len(quiere)} entrenadores"
        ))
        w(f"\nJugadores creados ({len(creados)}):")
        for n, e in creados:
            w(f"  + {n}  [{e}]")
        w(f"\nJugadores reactivados ({len(reactivados)}): {', '.join(reactivados) or '—'}")
        w(f"\nJugadores que cambian de escuela ({len(movidos)}):")
        for n, antes, ahora in movidos:
            w(f"  ~ {n}: {antes or 'sin escuela'} → {ahora}")
        w(f"\nCon ficha pero fuera del roster de esta semana ({len(fuera)}):")
        w("  " + (", ".join(fuera) or "—"))
        if opts["inferir_divisiones"]:
            w(f"\nDivisiones provisionales propuestas ({len(propuestas)}) "
              f"— REVISAR con dirección deportiva:")
            for n, lvl in sorted(propuestas, key=lambda t: t[1]):
                w(f"  · división {lvl}  {n}")
            w(f"  Siguen sin división: {sin_division}")
        w(f"\nEntrenadores renombrados ({len(renombrados)}):")
        for antes, ahora in renombrados:
            w(f"  ~ {antes} → {ahora}")
        w(f"\nEntrenadores duplicados fusionados ({len(fusionados)}):")
        for antes, ahora in fusionados:
            w(f"  − {antes} (duplicado de {ahora})")
        w(f"\nEntrenadores dados de alta ({len(altas_c)}): {', '.join(altas_c) or '—'}")
        w(f"\nEntrenadores sin trabajo esta semana ({len(apagados)}): "
          f"{', '.join(sorted(set(apagados))) or '—'}")
        if creados:
            w(self.style.WARNING(
                f"\n⚠ {len(creados)} jugadores creados sin codigo_cliente. "
                "Un `import_alumnos --prune` posterior los borraría: conviene "
                "reconciliarlos contra el export del software de gestión."
            ))
        w(f"\nEntrenadores reactivados ({len(reactivados_c)}): "
          f"{', '.join(sorted(set(reactivados_c))) or '—'}")
        if seco:
            w(self.style.WARNING("\n(dry-run: no se ha escrito nada)"))
            transaction.set_rollback(True)
