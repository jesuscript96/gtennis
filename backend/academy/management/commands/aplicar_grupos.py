"""Aplica el organigrama de la dirección deportiva (septiembre de 2026).

De la pestaña «GRUPOS TODOS» del CALENDARIO 2026 salen tres cosas distintas:

  NIVEL — «NIVELES PARA ENTRENAMIENTO» (filas 87-102). Es la división del
  alumno y solo sirve para emparejarle con otros.  → `Jugador.division`

  GESTIÓN — la tabla de encima (filas 67-82): cada columna es un entrenador
  con los alumnos que gestiona.  → `Jugador.entrenador_responsable`

  ENTRENAMIENTO — la misma tabla: el entrenador de su columna es su principal
  y el resto de su grupo, secundarios con un 10% cada uno, que es el mínimo
  (`academy.pesos`).  → `ResponsableJugador`

Los porcentajes se retocan después a mano en la ficha del alumno. Volver a
pasar el comando los devuelve a la regla; el informe dice a cuántos.

Idempotente. Uso:
    python manage.py aplicar_grupos --dry-run
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from academy.models import (
    Coach, Contrato, Division, Entrenador, Jugador, ResponsableJugador,
)
from academy.pesos import guardar as guardar_pesos, reparto_por_defecto

# ── Gestión y entrenamiento: la tabla de las filas 67-82 ────────────────────
# Cada bloque: su coach y sus columnas, cada una con el entrenador (o los
# entrenadores) de arriba y sus alumnos debajo. Los entrenadores van con el
# nombre completo: el buscador difuso confunde «VICTOR R.» con Víctor M y
# «JORGE I.» con Jorge García.
BLOQUES = [
    {
        "head": "DANI GIMENO",
        "divisiones": [1, 2, 3],
        "columnas": [
            (["VICTOR REDONDO"],
             ["Carlos Taberner", "Carlos Sanchez", "Raúl Brancaccio"]),
            (["JAVI GIMENEZ", "BLAS GALLEGO", "EMILIO SORIO"],
             ["Carlos Lopez", "Carles cordoba", "Ignacio Parisca", "Sergio Planella",
              "Lucca Helguera", "Alejandro Garcia", "Mateo Alvarez", "Yanaki Milev",
              "Toprak Avcibasi"]),
            (["JAVI GIMENEZ", "BLAS GALLEGO", "EMILIO SORIO"],
             ["Enzo Helguera", "Maria Adrienko", "Marc Martin Roca", "Diego Vilches",
              "Fermin Barcala", "Chimo Minguez", "Ciaran Kanani"]),
        ],
    },
    {
        "head": "PABLO GIL",
        "divisiones": [4, 5, 6],
        "columnas": [
            (["PABLO GIL"], ["Javi Ballester", "Eric Badenes", "Carla Guerrero"]),
            (["MARIO MUNIESA", "JORGE IBAÑEZ"],
             ["Marcos Romero", "Vicent Baixauli", "Marta Crespo", "Valeriia Bokova",
              "Ojas Malhorta", "Jinxuan Liao Bonnie"]),
            (["SALVA BARCALA"],
             ["Amparo Gil", "Natalia Botea", "Anjali Vasanthan", "Rodrigo López",
              "Manuel Mendez"]),
        ],
    },
    {
        "head": "SANTI PANZARASA",
        "divisiones": [7, 8],
        "columnas": [
            (["PATRICIO"], ["Dani Martins", "Eugenia Álvarez", "Victoria Schneider"]),
            (["NACHO CALVO"],
             ["Nik Guilin", "Huaqi Li", "Shiying Xia 14 Silvia", "Arrow 13",
              "Maria Ruiz", "Valentina Andrea 13", "Tomkin Deng"]),
        ],
    },
    {
        "head": "ALVARO MANTOAN",
        "divisiones": [9],
        "columnas": [
            (["ALVARO MANTOAN", "ALBERTO", "JORGE MILLA"],
             ["Ruohan Xu", "Jennie Zhang", "Yuantian Gao", "Kevin (zunwen wang)",
              "Yushuo Li 14 (chico)", "Pablo Pérez Fajardo", "Octavio Alcaraz",
              "Kandi Xu 15años (YU)", "Carol Grao", "Tal Or", "Xuancheng kairi 12",
              "Gavin Dai", "Yanqiedeng Wang 13"]),
        ],
    },
]
# Grupos de un entrenador suelto, fuera de los bloques (filas 81-82).
PARTICULARES = [("JORGE GARCIA", ["Elina Avanesyan"])]

# ── Nivel: «NIVELES PARA ENTRENAMIENTO», filas 87-102 ───────────────────────
# La columna N (los chinos) no lleva número en la fila de niveles: va con la 9.
NIVELES = {
    1: ["Carlos Taberner", "Carlos Sanchez", "Raúl Brancaccio"],
    2: ["Carlos Lopez", "Carles cordoba", "Ignacio Parisca", "Sergio Planella",
        "Lucca Helguera", "Alejandro Garcia", "Mateo Alvarez", "Yanaki Milev",
        "Toprak Avcibasi", "Elina Avanesyan"],
    3: ["Enzo Helguera", "Marc Martin Roca", "Fermin Barcala", "Chimo Minguez",
        "Javi Ballester"],
    4: ["Maria Adrienko", "Eric Badenes"],
    5: ["Marcos Romero", "Vicent Baixauli", "Carla Guerrero", "Ojas Malhorta",
        "Diego Vilches", "Ciaran Kanani"],
    6: ["Dani Martins", "Manuel Mendez"],
    7: ["Marta Crespo", "Valeriia Bokova", "Eugenia Álvarez", "Victoria Schneider",
        "Amparo Gil", "Rodrigo López", "Jinxuan Liao Bonnie"],
    8: ["Huaqi Li", "Natalia Botea", "Anjali Vasanthan"],
    9: ["Nik Guilin", "Arrow 13", "Valentina Andrea 13", "Maria Ruiz", "Tomkin Deng",
        "Shiying Xia 14 Silvia",
        "Ruohan Xu", "Jennie Zhang", "Yuantian Gao", "Kevin (zunwen wang)",
        "Yushuo Li 14 (chico)", "Pablo Pérez Fajardo", "Octavio Alcaraz",
        "Kandi Xu 15años (YU)", "Carol Grao", "Tal Or", "Xuancheng kairi 12",
        "Gavin Dai", "Yanqiedeng Wang 13"],
}

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
    help = "Aplica el organigrama: nivel, responsable y porcentajes de entrenamiento."

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
        for n in NIVELES:
            Division.objects.get_or_create(nivel=n, defaults={"nombre": f"División {n}"})
        divs = {d.nivel: d for d in Division.objects.all()}
        # Con dos fichas del mismo nombre, se queda la activa (va la última).
        jidx, eidx = {}, {}
        for j in Jugador.objects.order_by("activo", "id"):
            jidx[clave(j.nombre)] = j
        for e in Entrenador.objects.order_by("activo", "id"):
            eidx[clave(e.nombre)] = e

        altas_e, altas_j, aproximados = set(), [], set()
        redivs, cambios_resp, columnas, coaches_retirados = [], [], [], []
        vistos, pesos_cambian = set(), 0
        # Si una columna la firman varios, sus alumnos se reparten entre ellos
        # como responsables.
        carga = defaultdict(int)

        def ficha(modelo, idx, nom):
            obj = self._buscar(modelo, nom, idx)
            if obj is not None and clave(obj.nombre) != clave(nom):
                aproximados.add((modelo.__name__.lower(), nom, obj.nombre))
            return obj

        grupos = [(b["head"], b["columnas"]) for b in BLOQUES]
        grupos += [(None, [([ent], alumnos)]) for ent, alumnos in PARTICULARES]
        for head, cols in grupos:
            plantel = list(dict.fromkeys(
                ([head] if head else []) + [n for arriba, _a in cols for n in arriba]
            ))
            ents = {}
            for nom in plantel:
                ent = ficha(Entrenador, eidx, nom)
                if ent is None:
                    altas_e.add(nom)
                    if seco:
                        continue
                    ent = Entrenador.objects.create(nombre=nom, activo=True)
                    eidx[clave(nom)] = ent
                if not seco:
                    ent.activo = True
                    ent.disponible_semana = not fuera_de_servicio(nom)
                    ent.save(update_fields=["activo", "disponible_semana"])
                ents[nom] = ent

            if head is not None:
                # Coach del bloque, con su equipo colgando. Se reusa el que ya
                # exista —el que tiene usuario— y los duplicados se retiran: si
                # no, el bloque sale partido en dos en la pestaña de grupos.
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
                    coach.entrenadores.set(ents.values())

            # Quien está fuera de servicio sigue en su bloque, pero ni gestiona
            # ni entrena a nadie.
            en_servicio = [n for n in plantel if n in ents and not fuera_de_servicio(n)]
            for arriba, alumnos in cols:
                principales = [n for n in arriba if n in en_servicio]
                reparto = reparto_por_defecto(
                    principales, sorted(n for n in en_servicio if n not in principales)
                )
                columnas.append((head, arriba, len(alumnos), reparto))
                filas = sorted((ents[n].pk, p, c) for n, p, c in reparto)
                for nom in alumnos:
                    jug = ficha(Jugador, jidx, nom)
                    if jug is None:
                        altas_j.append((nom, head or arriba[0]))
                        if seco:
                            continue
                        jug = Jugador.objects.create(
                            nombre=nom, activo=True,
                            notas="alta desde el organigrama de septiembre",
                        )
                        jidx[clave(nom)] = jug
                    vistos.add(jug.pk)
                    dueno = None
                    if principales:
                        dueno = min((ents[n] for n in principales),
                                    key=lambda e: (carga[e.pk], e.nombre))
                        carga[dueno.pk] += 1
                        if jug.entrenador_responsable_id != dueno.pk:
                            antes = (jug.entrenador_responsable.nombre
                                     if jug.entrenador_responsable_id else "—")
                            cambios_resp.append((jug.nombre, antes, dueno.nombre))
                    actuales = sorted(
                        ResponsableJugador.objects.filter(jugador=jug, activo=True)
                        .values_list("entrenador_id", "prioridad", "porcentaje_objetivo")
                    )
                    if actuales != filas:
                        pesos_cambian += 1
                    if not seco:
                        jug.activo = True
                        if dueno is not None:
                            jug.entrenador_responsable = dueno
                        jug.save(update_fields=["activo", "entrenador_responsable"])
                        guardar_pesos(jug, filas)

        # Nivel: la división, que solo sirve para emparejar.
        con_nivel = set()
        for nivel, nombres in NIVELES.items():
            for nom in nombres:
                jug = ficha(Jugador, jidx, nom)
                if jug is None:
                    continue
                con_nivel.add(jug.pk)
                actual = jug.division.nivel if jug.division_id else None
                if actual != nivel:
                    redivs.append((jug.nombre, actual, nivel))
                    if not seco:
                        jug.division = divs[nivel]
                        jug.save(update_fields=["division"])
        sin_nivel = sorted(Jugador.objects.filter(pk__in=vistos - con_nivel)
                           .values_list("nombre", flat=True))
        nivel_sin_grupo = sorted(Jugador.objects.filter(pk__in=con_nivel - vistos)
                                 .values_list("nombre", flat=True))

        if not seco:
            for b in BLOQUES:
                divs_b = b.get("divisiones", [])
                plantel = list(dict.fromkeys([b["head"]] + [n for arriba, _a in b["columnas"] for n in arriba]))
                for nom in plantel:
                    ent = self._buscar(Entrenador, nom, eidx)
                    if ent:
                        ent.divisiones_habilitadas.set([divs[n] for n in divs_b if n in divs])

            for ent_nom, jug_nom in CONTRATOS:
                ent = self._buscar(Entrenador, ent_nom, eidx)
                jug = self._buscar(Jugador, jug_nom, jidx)
                if ent and jug:
                    Contrato.objects.update_or_create(
                        jugador=jug, entrenador=ent, defaults={"activo": True}
                    )

        # Quien no está en el organigrama deja su grupo: si no, seguiría saliendo
        # con sus entrenadores de antes. No se le da de baja ni se le toca el nivel.
        fuera_jug = [j for j in Jugador.objects.filter(activo=True) if j.pk not in vistos]
        fuera = sorted(j.nombre for j in fuera_jug)
        salen = sorted(j.nombre for j in fuera_jug
                       if j.entrenador_responsable_id or j.responsables.exists())
        if not seco:
            for j in fuera_jug:
                guardar_pesos(j, [])
                if j.entrenador_responsable_id:
                    j.entrenador_responsable = None
                    j.save(update_fields=["entrenador_responsable"])

        # -- informe ---------------------------------------------------------
        w(self.style.MIGRATE_HEADING("\nGRUPOS · principal y secundarios"))
        for head, arriba, n, reparto in columnas:
            principal = " · ".join(f"{e} {c}%" for e, p, c in reparto if p == 1)
            secundarios = ", ".join(f"{e} {c}%" for e, p, c in reparto if p == 2)
            w(f"  {head or '—':16s} {' / '.join(arriba):40s} {n:>2} alumnos  {principal}"
              + (f"  + {secundarios}" if secundarios else ""))
        for nom, motivo in NO_DISPONIBLES.items():
            w(f"  ⚠ {nom}: {motivo}. Sigue en su bloque, pero ni gestiona ni entrena a nadie.")
        w(self.style.MIGRATE_HEADING(f"\nRESPONSABLES QUE CAMBIAN ({len(cambios_resp)})"))
        for nom, antes, despues in sorted(cambios_resp):
            w(f"  {nom:32s} {antes} → {despues}")
        w(self.style.MIGRATE_HEADING(f"\nPORCENTAJES QUE CAMBIAN: {pesos_cambian} alumnos"))
        w(self.style.MIGRATE_HEADING(f"\nNIVELES CORREGIDOS ({len(redivs)})"))
        for nom, antes, despues in sorted(redivs, key=lambda x: (x[2], x[0])):
            w(f"  {str(antes):>4} → {despues}   {nom}")
        w(self.style.MIGRATE_HEADING(f"\nNOMBRES QUE CASAN POR PARECIDO ({len(aproximados)})"))
        for tipo, en_tabla, en_ficha in sorted(aproximados):
            w(f"  {tipo:10s} {en_tabla:28s} → {en_ficha}")
        w(self.style.MIGRATE_HEADING(
            f"\nALTAS ({len(altas_j)} jugadores, {len(altas_e)} entrenadores)"))
        for nom, grupo in altas_j:
            w(f"  jugador     {nom:28s} [{grupo}]")
        for nom in sorted(altas_e):
            w(f"  entrenador  {nom}")
        if sin_nivel or nivel_sin_grupo:
            w(self.style.WARNING("\nNIVEL Y GRUPO QUE NO CUADRAN"))
            w("  en un grupo sin nivel: " + (", ".join(sin_nivel) or "—"))
            w("  con nivel sin grupo:   " + (", ".join(nivel_sin_grupo) or "—"))
        w(self.style.WARNING(f"\nACTIVOS QUE NO ESTÁN EN EL ORGANIGRAMA ({len(fuera)})"))
        w("  " + (", ".join(fuera) or "—"))
        w(self.style.WARNING(f"\nSALEN DE SU GRUPO ({len(salen)})"))
        w("  " + (", ".join(salen) or "—"))
        w("  → sin responsable ni porcentajes, a «Sin grupo». Ni baja ni cambio de nivel.")
        if coaches_retirados:
            w(self.style.WARNING(
                f"\nCOACHES DUPLICADOS RETIRADOS ({len(coaches_retirados)})"))
            for viejo, queda in coaches_retirados:
                w(f"  {viejo}  → el bloque queda en «{queda}»")
        if seco:
            w(self.style.WARNING("\n(dry-run: no se ha escrito nada)"))
            transaction.set_rollback(True)
