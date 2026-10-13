"""Grupos de gestión según la tabla del club del 13/10/2026.

Cada columna es un entrenador con los jugadores que gestiona; cada color, un
grupo de gestión (el bloque de su head coach): el entrenador ve y edita
también a los jugadores de las demás columnas de su color, y los suyos le
salen primero.

  * Amarillo (Dani):  Víctor R., Javi, Blas y Emilio.
  * Turquesa (Pablo): Pablo, Mario / Jorge I. (comparten gestión) y Salva.
  * Naranja (Santi):  Patricio y Nacho.
  * Elina va con Jorge García, que es dirección y ya ve a todos.
  * Jorge I. está en China: sigue compartiendo la gestión con Mario; lo de no
    ponerle en pista no cambia aquí.

Los nombres se casan con las fichas por `clave()` y, si no, por parecido
(la tabla escribe «Maria Andrienko» y la ficha es «Maria Adrienko»); todo lo
que no casa letra a letra sale listado. A los jugadores de baja se les pone
igualmente su entrenador, sin darles de alta. Quien no tiene ficha solo se
avisa: el alta la hace administración.

Idempotente. Uso:
    python manage.py grupos_gestion            # ensayo, no guarda
    python manage.py grupos_gestion --aplicar
"""
from difflib import SequenceMatcher

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academy.management.commands.aplicar_grupos import clave
from academy.models import Coach, Entrenador, Jugador
from users.models import User

# color → (usuario del head coach, [(entrenadores de la columna, jugadores)]).
# Con dos entrenadores en la columna, el primero es el responsable y el
# segundo comparte la gestión.
COLORES = {
    "amarillo": ("daniel.gimeno", [
        (["Victor Redondo"], [
            "Carlos Taberner", "Carlos Sanchez", "Raúl Brancaccio"]),
        (["Javi Gimenez"], [
            "Carlos Lopez", "Carles cordoba", "Ignacio Parisca", "Yanaki Milev",
            "Lucca Helguera"]),
        (["Blas Gallego"], [
            "Toprak Avcibasi", "Alejandro Garcia", "Mateo Alvarez",
            "Sergio Planella"]),
        (["Emilio Sorio"], [
            "Enzo Helguera", "Maria Andrienko", "Marc Martin Roca",
            "Diego Vilches", "Fermin Barcala", "Chimo Minguez", "Ciaran Kanani",
            "Yagiz Yildiz 17", "Ziya Aiberk 17"]),
    ]),
    "turquesa": ("pablo.gil", [
        (["Pablo Gil"], [
            "Javi Ballester", "Eric Badenes", "Carla Guerrero",
            "Nazim Malikov 17"]),
        (["Mario Muniesa", "Jorge Ibañez"], [
            "Marcos Romero", "Vicent Baixauli", "Marta Crespo",
            "Valeriia Bokova", "Ojas Malhorta", "Anjali Vasanthan",
            "Jinxuan Liao Bonnie"]),
        (["Salva Barcala"], [
            "Amparo Gil", "Natalia Botea", "Rodrigo López", "Manuel Mendez",
            "Barbara Peñaranda"]),
    ]),
    "naranja": ("santi.panzarassa", [
        (["Patricio rodriguez"], [
            "Dani Martins", "Eugenia Álvarez", "Victoria Schneider",
            "Haode Chen"]),
        (["Nacho Calvo"], [
            "Nik Guilin", "Huaqi Li", "Shiying Xia 14 Silvia", "Arrow Meister",
            "Maria Ruiz", "Mario Vaselinov", "Valentina Andrea 13",
            "Tomkin Deng"]),
    ]),
}
# Fuera de los colores: dirección.
SUELTOS = [(["Jorge Garcia"], ["Elina AVANESYAN"])]


def _casan(a, b):
    """¿Dos palabras de un nombre son la misma? Igual, una abrevia a la otra
    («JAVI» / «JAVIER») o una errata («MALHORTA» / «MALHOTRA»)."""
    if a == b:
        return True
    if min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)):
        return True
    return min(len(a), len(b)) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.8


def buscar(nombre, fichas):
    """La ficha de `nombre` entre `fichas`: (ficha, cómo casó) o (None, motivo).

    Por orden: la clave idéntica; las palabras de una contenidas en la otra;
    y, por último, palabra a palabra por parecido. En cada paso, si casan
    varias gana la activa, y si siguen siendo varias no se elige ninguna.
    """
    k = clave(nombre)
    tk = set(k.split())
    if not tk:
        return None, "nombre vacío"

    def contenidas(kv):
        tv = set(kv.split())
        return bool(tv) and (tk <= tv or tv <= tk)

    def parecidas(kv):
        tv = set(kv.split())
        if not tv:
            return False
        corto, largo = (tk, tv) if len(tk) <= len(tv) else (tv, tk)
        return all(any(_casan(a, b) for b in largo) for a in corto)

    for como, criterio in (("exacta", lambda kv: kv == k),
                           ("contenida", contenidas),
                           ("parecido", parecidas)):
        cand = [f for f in fichas if criterio(clave(f.nombre))]
        if len(cand) > 1:
            activas = [f for f in cand if f.activo]
            cand = activas or cand
        if len(cand) > 1 and isinstance(cand[0], Jugador):
            # Fichas duplicadas (Tomkin): la buena es la que tiene código.
            con_codigo = [f for f in cand if f.codigo_cliente]
            cand = con_codigo if len(con_codigo) == 1 else cand
        if len(cand) == 1:
            return cand[0], como
        if cand:
            return None, "varias fichas: " + ", ".join(
                f"{f.nombre} (#{f.pk})" for f in cand)
    return None, "sin ficha"


class Command(BaseCommand):
    help = "Grupos de gestión según la tabla del club del 13/10/2026."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true")

    def handle(self, *args, aplicar=False, **opts):
        with transaction.atomic():
            self._cambios()
            if not aplicar:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Ensayo: no se ha guardado nada."))

    def _cambios(self):
        w = self.stdout.write
        entrenadores = list(Entrenador.objects.all())
        jugadores = list(Jugador.objects.all())
        aproximados, sin_ficha, de_baja = [], [], []

        def ent(nombre):
            e, como = buscar(nombre, entrenadores)
            if e is None:
                raise CommandError(f"Entrenador «{nombre}»: {como}")
            if como != "exacta":
                aproximados.append(f"entrenador «{nombre}» → {e.nombre}")
            return e

        # 1. Cada color es el bloque de su head coach, que lo lleva puesto.
        grupos = []
        w("GRUPOS DE GESTIÓN")
        for color, (usuario, columnas) in COLORES.items():
            try:
                coach = User.objects.get(username=usuario).coach
            except (User.DoesNotExist, Coach.DoesNotExist):
                raise CommandError(f"«{usuario}» no tiene coach")
            ficha = getattr(coach.user, "entrenador", None)
            miembros = {ficha} if ficha else set()
            for nombres, _j in columnas:
                miembros.update(ent(n) for n in nombres)
            antes = set(coach.entrenadores.all())
            if antes != miembros:
                coach.entrenadores.set(miembros)
                fuera = ", ".join(sorted(e.nombre for e in antes - miembros))
                dentro = ", ".join(sorted(e.nombre for e in miembros - antes))
                w(f"  {coach.nombre}: entran [{dentro}] · salen [{fuera}]")
            if (coach.color, coach.activo) != (color, True):
                coach.color, coach.activo = color, True
                coach.save(update_fields=["color", "activo"])
            grupos.append(coach.pk)
            w(f"  {color} ({coach.nombre}): "
              + ", ".join(sorted(e.nombre for e in miembros)))
        for c in Coach.objects.exclude(color="").exclude(pk__in=grupos):
            w(f"  {c.nombre}: deja de ser grupo de gestión ({c.color})")
            c.color = ""
            c.save(update_fields=["color"])

        # 2. Quién gestiona a cada jugador.
        w("\nGESTIÓN")
        columnas = [c for _u, cols in COLORES.values() for c in cols] + SUELTOS
        en_tabla, cambios = set(), 0
        for nombres, alumnos in columnas:
            responsable, *co = [ent(n) for n in nombres]
            for nombre in alumnos:
                j, como = buscar(nombre, jugadores)
                if j is None:
                    sin_ficha.append(f"{nombre} ({responsable.nombre}): {como}")
                    continue
                # Que la tabla omita el segundo apellido es lo normal; se
                # avisa de las erratas y de cuando la ficha dice menos.
                if como == "parecido" or (
                        como == "contenida"
                        and not set(clave(nombre).split()) <= set(clave(j.nombre).split())):
                    aproximados.append(f"«{nombre}» → {j.nombre}")
                if j.pk in en_tabla:
                    raise CommandError(f"{j.nombre} sale dos veces en la tabla")
                en_tabla.add(j.pk)
                if not j.activo:
                    de_baja.append(f"{j.nombre} ({responsable.nombre})")
                antes = (j.entrenador_responsable, set(j.cogestores.all()))
                if antes == (responsable, set(co)):
                    continue
                cambios += 1
                j.entrenador_responsable = responsable
                j.save(update_fields=["entrenador_responsable"])
                j.cogestores.set(co)
                quien = lambda r, c: " y ".join(  # noqa: E731
                    [r.nombre if r else "nadie"] + sorted(x.nombre for x in c))
                w(f"  {j.nombre}: {quien(*antes)} → {quien(responsable, co)}")
        w(f"  {cambios} cambios; {len(en_tabla)} jugadores en la tabla.")

        # 3. Lo que hay que mirar a mano.
        if aproximados:
            w("\nNOMBRES QUE CASAN POR PARECIDO (revisar)")
            for linea in aproximados:
                w(f"  {linea}")
        if de_baja:
            w("\nDE BAJA: se les pone su entrenador, pero siguen sin entrenar")
            for linea in de_baja:
                w(f"  {linea}")
        if sin_ficha:
            w(self.style.WARNING("\nSIN FICHA: no se ha hecho nada (alta pendiente)"))
            for linea in sin_ficha:
                w(f"  {linea}")
        de_la_tabla = {e.pk for nombres, _a in columnas for e in map(ent, nombres)}
        sobran = (Jugador.objects.filter(activo=True, entrenador_responsable__in=de_la_tabla)
                  .exclude(pk__in=en_tabla).select_related("entrenador_responsable"))
        if sobran:
            w("\nACTIVOS QUE NO SALEN EN LA TABLA: se quedan como están")
            for j in sobran:
                w(f"  {j.nombre} ({j.entrenador_responsable.nombre})")
