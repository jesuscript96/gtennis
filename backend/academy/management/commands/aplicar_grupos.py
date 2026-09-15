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
# Fuente: pestaña «GRUPOS TODOS» del CALENDARIO 2026.
#   · Entrenadores por división: filas 67-70 (coach arriba, entrenadores abajo).
#     No cambian de un curso a otro.
#   · Jugadores por nivel: «NIVELES PARA ENTRENAMIENTOS», filas 87-102.
# Desde septiembre de 2026 la escala es de 9 niveles, con la misma numeración
# que la fila de divisiones de los entrenadores: 1-3 Dani Gimeno, 4-6 Pablo Gil,
# 7-8 Santi Panzarasa y 9 Álvaro Mantoan. La columna N (los chinos) no lleva
# número en la fila de niveles: va con Álvaro, Alberto y Jorge Milla, que es lo
# que dice su cabecera, y toma la división de ese bloque.
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
              "Toprak Avcibasi", "Elina Avanesyan"]),
            (["JAVI GIMENEZ", "BLAS GALLEGO", "EMILIO SORIO"], 3,
             ["Enzo Helguera", "Marc Martin Roca", "Fermin Barcala", "Chimo Minguez",
              "Javi Ballester"]),
        ],
    },
    {
        "head": "PABLO GIL",
        "divisiones": [4, 5, 6],
        "columnas": [
            (["PABLO GIL"], 4, ["Maria Adrienko", "Eric Badenes"]),
            (["MARIO MUNIESA", "JORGE IBAÑEZ"], 5,
             ["Marcos Romero", "Vicent Baixauli", "Carla Guerrero", "Ojas Malhorta",
              "Diego Vilches", "Ciaran Kanani"]),
            (["SALVA BARCALA"], 6, ["Dani Martins", "Manuel Mendez"]),
        ],
    },
    {
        "head": "SANTI PANZARASA",
        "divisiones": [7, 8],
        "columnas": [
            (["PATRICIO"], 7,
             ["Marta Crespo", "Valeriia Bokova", "Eugenia Álvarez", "Victoria Schneider",
              "Amparo Gil", "Rodrigo López", "Jinxuan Liao Bonnie"]),
            (["NACHO CALVO"], 8, ["Huaqi Li", "Natalia Botea", "Anjali Vasanthan"]),
        ],
    },
    {
        "head": "ALVARO MANTOAN",
        "divisiones": [9],
        "columnas": [
            (["ALVARO MANTOAN", "ALBERTO", "JORGE MILLA"], 9,
             ["Nik Guilin", "Arrow 13", "Valentina Andrea 13", "Maria Ruiz",
              "Tomkin Deng", "Shiying Xia 14 Silvia"]),
            # Columna N: sin número en la fila de niveles.
            (["ALVARO MANTOAN", "ALBERTO", "JORGE MILLA"], 9,
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
    # Ximo se escribe también con Ch en valenciano.
    "CHIMO MINGUEZ": "Ximo Minguez",
    # El organigrama anterior le dio de alta como «TOM KIM» porque la ficha de
    # «Tomkin Deng Mai 12 AÑOS» estaba inactiva; se sigue usando la activa.
    "TOMKIN DENG": "TOM KIM",
    # En producción la ficha del head coach lleva el nombre completo.
    "DANI GIMENO": "Daniel Gimeno",
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


def fuera_de_servicio(nombre):
    """¿Está en NO_DISPONIBLES? Por clave y no letra a letra: la tabla escribe
    «JORGE IBAÑEZ» y en producción la ficha se llama «Jorge Ibañez»."""
    return clave(nombre) in {clave(n) for n in NO_DISPONIBLES}


class Command(BaseCommand):
    help = "Aplica el organigrama de grupos: capacidad por división y responsable único."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        with transaction.atomic():
            self._run(**opts)

    # -- localizadores -----------------------------------------------------
    def _buscar(self, modelo, nombre, idx):
        """La ficha que corresponde a un nombre de la tabla de dirección.

        Primero el nombre tal cual y, solo si no aparece, su alias: los alias
        son variantes de una base concreta («Ximo» en una, «Chimo Minguez
        Ribera» en otra) y no pueden tapar a una ficha que ya se llama como en
        la tabla. Y entre las que casan gana la activa: una ficha vieja dada de
        baja no puede quedarse con el nombre de una que está en activo.
        """
        textos = [nombre]
        alias = ALIAS.get(clave(nombre))
        if alias:
            textos.append(alias)
        for solo_activas in (True, False):
            for texto in textos:
                k = clave(texto)
                tk = set(k.split())
                if not tk:
                    continue
                exacta = idx.get(k)
                if exacta is not None and (exacta.activo or not solo_activas):
                    return exacta
                for kk, obj in idx.items():
                    if solo_activas and not obj.activo:
                        continue
                    tv = set(kk.split())
                    if tv and (tk <= tv or tv <= tk):
                        return obj
        return None

    def _coach_del_bloque(self, head, crear=True):
        """El coach de un bloque, y los duplicados que hay que retirar.

        Conviven coaches creados con su usuario («PABLO») y otros que creaba
        este mismo comando con el nombre del head («PABLO GIL»). Se queda el que
        tiene usuario, que es con el que se entra a la app.
        """
        tk = set(clave(head).split())
        candidatos = []
        for c in Coach.objects.all():
            tc = set(clave(c.nombre).split())
            if tc and (tc <= tk or tk <= tc):
                candidatos.append(c)
        candidatos.sort(key=lambda c: (c.user_id is None, not c.activo, c.id))
        if not candidatos:
            return (Coach.objects.create(nombre=head, activo=True) if crear else None), []
        return candidatos[0], [c for c in candidatos[1:] if c.activo]

    def _run(self, **opts):
        w = self.stdout.write
        seco = opts["dry_run"]
        # La escala la marca el organigrama, no la base: si la dirección añade
        # un nivel (la 9, en septiembre de 2026) se crea aquí.
        niveles = {n for b in BLOQUES for n in b["divisiones"]}
        niveles |= {d for b in BLOQUES for _c, d, _j in b["columnas"]}
        for n in sorted(niveles):
            Division.objects.get_or_create(nivel=n, defaults={"nombre": f"División {n}"})
        divs = {d.nivel: d for d in Division.objects.all()}
        # Con dos fichas del mismo nombre, se queda la activa (va la última).
        jidx, eidx = {}, {}
        for j in Jugador.objects.order_by("activo", "id"):
            jidx[clave(j.nombre)] = j
        for e in Entrenador.objects.order_by("activo", "id"):
            eidx[clave(e.nombre)] = e

        altas_e, altas_j, sin_div, redivs, resp_nuevos = [], [], [], [], []
        coaches_retirados = []
        # Nombres de la tabla que no coinciden letra a letra con su ficha: es
        # donde se cuela un emparejamiento equivocado, así que se enseñan.
        aproximados = []
        capacidades = defaultdict(set)
        vistos = set()
        # Cuántos alumnos lleva ya cada entrenador como responsable de ficha.
        # Sirve para repartir la sub-columna en partes iguales cuando la firman
        # varios (Javi / Blas / Emilio) en vez de cargárselos todos al primero.
        carga = defaultdict(int)

        for bloque in BLOQUES:
            head = bloque["head"]
            plantel = {head}
            for cols, _d, _j in bloque["columnas"]:
                plantel.update(cols)
            # 1) Capacidad de entrenar = las divisiones del bloque, para todos.
            for nom in plantel:
                ent = self._buscar(Entrenador, nom, eidx)
                if ent is not None and clave(ent.nombre) != clave(nom):
                    aproximados.append(("entrenador", nom, ent.nombre))
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
                    ent.disponible_semana = not fuera_de_servicio(nom)
                    ent.save(update_fields=["activo", "disponible_semana"])

            # 2) Coach del bloque, con su equipo colgando. Se reusa el que ya
            #    exista con ese nombre —el que tiene usuario, que es con el que
            #    se entra— y los duplicados se retiran: si no, el bloque sale
            #    partido en dos en la pestaña de grupos.
            coach, duplicados = self._coach_del_bloque(head, crear=not seco)
            coaches_retirados.extend(
                (d.nombre, coach.nombre if coach else head) for d in duplicados
            )
            if not seco:
                for dup in duplicados:
                    dup.entrenadores.clear()
                    dup.activo = False
                    dup.save(update_fields=["activo"])
                coach.activo = True
                coach.save(update_fields=["activo"])
                equipo = [self._buscar(Entrenador, n, eidx) for n in plantel]
                coach.entrenadores.set([e for e in equipo if e])

            # 3) Jugadores: división + responsable único (el de su sub-columna).
            for cols, div, jugadores in bloque["columnas"]:
                for nom in jugadores:
                    jug = self._buscar(Jugador, nom, jidx)
                    if jug is not None and clave(jug.nombre) != clave(nom):
                        aproximados.append(("jugador", nom, jug.nombre))
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
                    # Responsable de ficha: uno solo, el de su sub-columna. Es
                    # el grupo al que pertenece el alumno y quien responde por
                    # él; si la columna la firman varios, se reparten.
                    dueno = None
                    candidatos = [
                        e for e in (self._buscar(Entrenador, c, eidx) for c in sorted(cols))
                        if e is not None
                    ]
                    if candidatos:
                        # Quien está fuera de servicio (Jorge Ibáñez, en China)
                        # sigue en el bloque pero no responde por nadie.
                        dueno = min(candidatos, key=lambda e: (
                            fuera_de_servicio(e.nombre), carga[e.pk], e.nombre))
                        carga[dueno.pk] += 1
                    if not seco:
                        jug.division = divs.get(div)
                        jug.activo = True
                        if dueno is not None:
                            jug.entrenador_responsable = dueno
                        jug.save(update_fields=[
                            "division", "activo", "entrenador_responsable",
                        ])
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

        fuera_jug = [j for j in Jugador.objects.filter(activo=True)
                     if j.pk not in vistos]
        fuera = [j.nombre for j in fuera_jug]
        # Quien tenía grupo y ya no aparece en el organigrama deja el grupo: si
        # no, la pestaña de grupos le seguiría enseñando con su entrenador de
        # antes. No se le da de baja ni se le toca la división.
        salen = sorted(j.nombre for j in fuera_jug if j.entrenador_responsable_id)
        for j in fuera_jug:
            if j.entrenador_responsable_id:
                ResponsableJugador.objects.filter(jugador=j).delete()
                j.entrenador_responsable = None
                j.save(update_fields=["entrenador_responsable"])

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
        vistos_aprox = sorted(set(aproximados))
        w(self.style.MIGRATE_HEADING(
            f"\nNOMBRES QUE CASAN POR PARECIDO ({len(vistos_aprox)})"))
        for tipo, en_tabla, en_ficha in vistos_aprox:
            w(f"  {tipo:10s} {en_tabla:28s} → {en_ficha}")
        w(self.style.MIGRATE_HEADING(f"\nALTAS ({len(altas_j)} jugadores, {len(altas_e)} entrenadores)"))
        for n, d, b in altas_j:
            w(f"  jugador  div {d}  {n:28s} [{b}]")
        for n in altas_e:
            w(f"  entrenador  {n}")
        w(self.style.WARNING(
            f"\nACTIVOS QUE NO ESTÁN EN EL ORGANIGRAMA ({len(fuera)})"))
        w("  " + ", ".join(sorted(fuera)))
        w("  → ni se les da de baja ni se les cambia la división.")
        w(self.style.WARNING(f"\nSALEN DE SU GRUPO ({len(salen)})"))
        w("  " + (", ".join(salen) or "—"))
        w("  → tenían responsable y no están en el organigrama: pasan a «Sin grupo».")
        if coaches_retirados:
            w(self.style.WARNING(
                f"\nCOACHES DUPLICADOS RETIRADOS ({len(coaches_retirados)})"))
            for viejo, queda in coaches_retirados:
                w(f"  {viejo}  → el bloque queda en «{queda}»")
        if seco:
            w(self.style.WARNING("\n(dry-run: no se ha escrito nada)"))
            transaction.set_rollback(True)
