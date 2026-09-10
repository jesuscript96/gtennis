"""Aplica el organigrama de grupos de la dirección deportiva (septiembre 2026).

El modelo tiene DOS ejes independientes, y hasta ahora estaban mezclados:

  CAPACIDAD DE ENTRENAR — la marca la división. Cada bloque cubre un rango de
  divisiones y todos sus entrenadores pueden entrenar a cualquier jugador de
  esas divisiones. Sin pesos ni porcentajes: las únicas excepciones son un
  contrato de patrocinio o una rencilla.  → `Entrenador.divisiones_habilitadas`

  ADMINISTRACIÓN EN LA APP — todos los entrenadores del bloque pueden editar la
  ficha de cualquier jugador del bloque y declararle ausencias. La sub-columna
  de la tabla no restringe tampoco aquí; es solo cómo la dirección agrupa la
  lista. Los administradores lo ven todo por su rol.  → `ResponsableJugador`

Esto sustituye al reparto anterior por porcentajes (prioridad 1/2 con 70/30),
que no correspondía a nada real y además concentraba la carga: el motor elegía
siempre al entrenador con más déficit de porcentaje y nunca llegaba a
equilibrar.

Idempotente. Uso:
    python manage.py aplicar_grupos --dry-run
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from academy.models import (
    Coach, Contrato, Division, Entrenador, Jugador, ResponsableJugador,
)

# ── Organigrama ────────────────────────────────────────────────────────────
# Cada bloque: head coach (que también entrena), las divisiones que cubre y
# las sub-columnas. La sub-columna solo decide QUIÉN ADMINISTRA; para entrenar
# vale cualquier entrenador del bloque.
BLOQUES = [
    {
        "head": "DANI GIMENO",
        "divisiones": [1, 2, 3],
        "columnas": [
            (["VICTOR REDONDO"], 1,
             ["Carlos Taberner", "Carlos Sanchez", "Raúl Brancaccio"]),
            (["JAVI GIMENEZ", "BLAS GALLEGO", "EMILIO SORIO"], 2,
             ["Carlos Lopez", "Carles cordoba", "Ignacio Parisca", "Sergio Planella",
              "Lucca Helguera", "Alejandro Garcia", "Mateo Alvarez", "Yanaki Milev",
              "Toprak"]),
            (["JAVI GIMENEZ", "BLAS GALLEGO", "EMILIO SORIO"], 3,
             ["Enzo Helguera", "Maria Adrienko", "Marc Martin Roca", "Diego Vilches",
              "Fermin Barcala", "Ximo Minguez", "Ciaran Kanani"]),
        ],
    },
    {
        "head": "PABLO GIL",
        "divisiones": [4, 5],
        "columnas": [
            # Confirmado por dirección: la columna de Pablo es división 4.
            (["PABLO GIL"], 4,
             ["Javi Ballester", "Eric Badenes", "Carla Guerrero"]),
            (["MARIO MUNIESA", "JORGE IBAÑEZ"], 4,
             ["Marcos Romero", "Vicent Baixauli", "Marta Crespo", "Valeriia Bokova",
              "Ojas Malhorta", "Jinxuan Liao Bonnie"]),
            (["SALVA BARCALA"], 5,
             ["Amparo Gil", "Natalia Botea", "Anjali Vasanthan", "Rodrigo López",
              "Manuel Mendez"]),
        ],
    },
    {
        "head": "SANTI PANZARASA",
        "divisiones": [6, 7],
        "columnas": [
            (["PATRICIO"], 6,
             ["Dani Martins", "Eugenia Álvarez", "Victoria Schneider",
              "Yashvardhan Singh"]),
            (["NACHO CALVO"], 7,
             ["Nik Guilin", "Huaqi Li", "Valentina Andrea 13", "Arrow 12",
              "Maria Ruiz", "TOM KIM"]),
        ],
    },
    {
        "head": "ALVARO MANTOAN",
        "divisiones": [8],
        "columnas": [
            (["ALVARO MANTOAN", "ALBERTO", "JORGE MILLA"], 8,
             ["Ruohan Xu", "Jennie Zhang", "Yuantian Gao", "Kevin (zunwen wang)",
              "Yushuo Li 14 (chico)", "Pablo Pérez Fajardo", "Octavio Alcaraz",
              "Kandi Xu 15años (YU)", "Carol Grao", "Tal Or", "Xuancheng kairi 12",
              "Gavin Dai", "Yanqiedeng Wang 13"]),
        ],
    },
]
# Entrenador particular: contrato de patrocinio (jugador ↔ entrenador fijo).
CONTRATOS = [("JORGE GARCIA", "Elina Avanesyan")]
# Entrenadores fuera de servicio esta temporada, con motivo.
NO_DISPONIBLES = {"JORGE IBAÑEZ": "en China"}
# Variantes de nombre entre la tabla de la dirección y las fichas de la app.
ALIAS = {
    "JAVI BALLESTER": "Javier Ballester Galarza",
    "OJAS MALHORTA": "Ojas Malhotra",
    "JENNIE ZHANG": "Jennie Zhangyi Ji (Yu)",
    "ELINA AVANESYAN": "Elina Avanesian",
    "NIK GUILIN": "Xu Guilin (Yu) Nik",
    "MANUEL MENDEZ": "Manuel Méndez Domínguez",
    "RUOHAN XU": "Ruohan Xu (Yu)",
    "MARIA ADRIENKO": "Maria Adrienko",
}


def clave(nombre):
    import re
    import unicodedata
    s = "".join(
        c for c in unicodedata.normalize("NFD", str(nombre or ""))
        if unicodedata.category(c) != "Mn"
    )
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^A-Za-z ]", " ", s)
    fuera = {"YU", "DE", "DEL", "LA", "EL", "CHICO", "CHICA", "ANOS", "MEDIO",
             "DIA", "PRUEBA"}
    return " ".join(
        w.upper() for w in s.split() if len(w) > 1 and w.upper() not in fuera
    )


class Command(BaseCommand):
    help = "Aplica el organigrama de grupos: capacidad por división y responsable único."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        with transaction.atomic():
            self._run(**opts)

    # -- localizadores -----------------------------------------------------
    def _buscar(self, modelo, nombre, idx):
        k = clave(ALIAS.get(clave(nombre), nombre))
        if k in idx:
            return idx[k]
        tk = set(k.split())
        for kk, obj in idx.items():
            tv = set(kk.split())
            if tk and tv and (tk <= tv or tv <= tk) and len(tk & tv) >= 1:
                return obj
        return None

    def _run(self, **opts):
        w = self.stdout.write
        seco = opts["dry_run"]
        divs = {d.nivel: d for d in Division.objects.all()}
        jidx, eidx = {}, {}
        for j in Jugador.objects.all():
            jidx.setdefault(clave(j.nombre), j)
        for e in Entrenador.objects.all():
            eidx.setdefault(clave(e.nombre), e)

        altas_e, altas_j, sin_div, redivs, resp_nuevos = [], [], [], [], []
        capacidades = defaultdict(set)
        vistos = set()

        for bloque in BLOQUES:
            head = bloque["head"]
            plantel = {head}
            for cols, _d, _j in bloque["columnas"]:
                plantel.update(cols)
            # 1) Capacidad de entrenar = las divisiones del bloque, para todos.
            for nom in plantel:
                ent = self._buscar(Entrenador, nom, eidx)
                if ent is None:
                    altas_e.append(nom)
                    if not seco:
                        ent = Entrenador.objects.create(nombre=nom, activo=True)
                        eidx[clave(nom)] = ent
                    else:
                        continue
                capacidades[ent.pk] |= set(bloque["divisiones"])
                if not seco:
                    ent.activo = True
                    ent.disponible_semana = nom not in NO_DISPONIBLES
                    ent.save(update_fields=["activo", "disponible_semana"])

            # 2) Coach del bloque, con su equipo colgando.
            if not seco:
                head_ent = self._buscar(Entrenador, head, eidx)
                coach, _ = Coach.objects.update_or_create(
                    nombre=head, defaults={"activo": True}
                )
                equipo = [self._buscar(Entrenador, n, eidx) for n in plantel]
                coach.entrenadores.set([e for e in equipo if e])

            # 3) Jugadores: división + responsable único (el de su sub-columna).
            for cols, div, jugadores in bloque["columnas"]:
                for nom in jugadores:
                    jug = self._buscar(Jugador, nom, jidx)
                    if jug is None:
                        altas_j.append((nom, div, head))
                        if seco:
                            continue
                        jug = Jugador.objects.create(
                            nombre=nom, activo=True, division=divs.get(div),
                            notas="alta desde el organigrama de septiembre",
                        )
                        jidx[clave(nom)] = jug
                    vistos.add(jug.pk)
                    actual = jug.division.nivel if jug.division else None
                    if actual != div:
                        redivs.append((jug.nombre, actual, div))
                    if not seco:
                        jug.division = divs.get(div)
                        jug.activo = True
                        jug.save(update_fields=["division", "activo"])
                        # Administración: TODO el bloque, sin pesos.
                        ResponsableJugador.objects.filter(jugador=jug).delete()
                        for cn in sorted(plantel):
                            ent = self._buscar(Entrenador, cn, eidx)
                            if ent:
                                ResponsableJugador.objects.create(
                                    jugador=jug, entrenador=ent, prioridad=1,
                                    porcentaje_objetivo=0, activo=True,
                                )
                    resp_nuevos.append((jug.nombre if jug else nom, sorted(plantel)))

        # 4) Capacidades y contratos.
        if not seco:
            for pk, niveles in capacidades.items():
                Entrenador.objects.get(pk=pk).divisiones_habilitadas.set(
                    [divs[n] for n in niveles if n in divs]
                )
            for ent_nom, jug_nom in CONTRATOS:
                ent = self._buscar(Entrenador, ent_nom, eidx)
                jug = self._buscar(Jugador, jug_nom, jidx)
                if ent and jug:
                    Contrato.objects.update_or_create(
                        jugador=jug, entrenador=ent, defaults={"activo": True}
                    )

        fuera = [j.nombre for j in Jugador.objects.filter(activo=True)
                 if j.pk not in vistos]

        # -- informe ---------------------------------------------------------
        w(self.style.MIGRATE_HEADING("\nCAPACIDAD DE ENTRENAR (por división)"))
        for bloque in BLOQUES:
            plantel = {bloque["head"]}
            for c, _d, _j in bloque["columnas"]:
                plantel.update(c)
            nota = "".join(f"  ⚠ {n}: {m}" for n, m in NO_DISPONIBLES.items()
                           if n in plantel)
            w(f"  divisiones {bloque['divisiones']} → {', '.join(sorted(plantel))}{nota}")
        w(self.style.MIGRATE_HEADING("\nADMINISTRACIÓN (quién puede editar a quién)"))
        porcol = defaultdict(list)
        for nom, cols in resp_nuevos:
            porcol[", ".join(cols)].append(nom)
        for col, jugs in porcol.items():
            w(f"  {len(jugs):>2} jugadores ← {col}")
        w(self.style.MIGRATE_HEADING(f"\nDIVISIONES CORREGIDAS ({len(redivs)})"))
        for n, a, b in sorted(redivs, key=lambda x: x[2]):
            w(f"  {str(a):>4} → {b}   {n}")
        w(self.style.MIGRATE_HEADING(f"\nALTAS ({len(altas_j)} jugadores, {len(altas_e)} entrenadores)"))
        for n, d, b in altas_j:
            w(f"  jugador  div {d}  {n:28s} [{b}]")
        for n in altas_e:
            w(f"  entrenador  {n}")
        w(self.style.WARNING(
            f"\nACTIVOS QUE NO ESTÁN EN EL ORGANIGRAMA ({len(fuera)})"))
        w("  " + ", ".join(sorted(fuera)))
        w("  → no se tocan: probablemente son Junior Program o bajas que se\n"
          "    confirmarán con la recogida de ausencias.")
        if seco:
            w(self.style.WARNING("\n(dry-run: no se ha escrito nada)"))
            transaction.set_rollback(True)
