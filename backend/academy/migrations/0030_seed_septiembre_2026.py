"""Lleva a producción el estado del curso 2026-2027 (septiembre).

Producción no tiene el Excel de la dirección deportiva, así que los datos que
se sacaron de él viajan aquí, en `academy/fixtures/septiembre_2026.json`:

  * los 4 bloques del organigrama, con qué divisiones entrena cada entrenador;
  * los jugadores con su división, escuela, edad y notas de horario;
  * quién administra a quién (todo el bloque sobre todos sus jugadores, sin
    porcentajes) y el contrato de patrocinio de Jorge García con Elina;
  * las bajas del campus de verano, como `activo = False` (no se borra a nadie);
  * qué franjas están dentro del alcance actual y los parámetros del motor,
    que se habían fijado a mano y por tanto no llegaban a producción.

Es idempotente y se casa por NOMBRE, no por id: se puede volver a lanzar sobre
una base que ya tenga fichas sin duplicarlas ni perder los códigos de cliente
que ya estén puestos.
"""
import json
import os

from django.db import migrations

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures", "septiembre_2026.json",
)


def _norm(nombre):
    import re
    import unicodedata

    s = "".join(c for c in unicodedata.normalize("NFD", str(nombre or ""))
                if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Za-z0-9 ]", " ", s).upper().split())


def forward(apps, schema_editor):
    if not os.path.exists(FIXTURE):
        return
    data = json.load(open(FIXTURE, encoding="utf-8"))

    Division = apps.get_model("academy", "Division")
    Escuela = apps.get_model("academy", "Escuela")
    Turno = apps.get_model("academy", "Turno")
    Entrenador = apps.get_model("academy", "Entrenador")
    Coach = apps.get_model("academy", "Coach")
    Jugador = apps.get_model("academy", "Jugador")
    Responsable = apps.get_model("academy", "ResponsableJugador")
    Contrato = apps.get_model("academy", "Contrato")

    for d in data["divisiones"]:
        Division.objects.update_or_create(nivel=d["nivel"],
                                          defaults={"nombre": d["nombre"]})
    divs = {d.nivel: d for d in Division.objects.all()}

    # Alcance de franjas: fuera la corta de 15:30-16:45 y las de escuela de
    # noche, que todavía no entran en el reparto automático.
    for t in data.get("turnos", []):
        Turno.objects.filter(codigo=t["codigo"]).update(
            nombre=t["nombre"], activo=t["activo"])
    turnos = {t.codigo: t for t in Turno.objects.all()}

    # Parámetros del motor, calibrados contra la semana real del 7 de
    # septiembre (2,29 jugadores por pista, 2,4 días y 4,1 sesiones por
    # jugador y semana).
    Config = apps.get_model("scheduling", "ConfiguracionMotor")
    motor = data.get("motor")
    if motor:
        Config.objects.update_or_create(pk=1, defaults=motor)

    for e in data["escuelas"]:
        Escuela.objects.update_or_create(
            nombre=e["nombre"],
            defaults={"turno_unico": turnos.get(e["turno"]),
                      "solo_central": e["solo_central"], "orden": e["orden"]},
        )
    escuelas = {e.nombre: e for e in Escuela.objects.all()}

    # -- entrenadores ------------------------------------------------------
    ents = {_norm(e.nombre): e for e in Entrenador.objects.all()}
    for e in data["entrenadores"]:
        obj = ents.get(_norm(e["nombre"]))
        if obj is None:
            obj = Entrenador.objects.create(nombre=e["nombre"])
            ents[_norm(e["nombre"])] = obj
        obj.nombre = e["nombre"]
        obj.activo = e["activo"]
        obj.disponible_semana = e["disponible_semana"]
        obj.gestiona_todos_jugadores = e["gestiona_todos"]
        obj.save()
        obj.divisiones_habilitadas.set([divs[n] for n in e["divisiones"] if n in divs])

    for c in data["coaches"]:
        obj, _ = Coach.objects.update_or_create(
            nombre=c["nombre"], defaults={"activo": c["activo"]})
        obj.entrenadores.set(
            [ents[_norm(n)] for n in c["entrenadores"] if _norm(n) in ents])

    # -- jugadores ---------------------------------------------------------
    jugs = {_norm(j.nombre): j for j in Jugador.objects.all()}
    for j in data["jugadores"]:
        obj = jugs.get(_norm(j["nombre"]))
        if obj is None:
            obj = Jugador.objects.create(nombre=j["nombre"])
            jugs[_norm(j["nombre"])] = obj
        obj.nombre = j["nombre"]
        obj.activo = j["activo"]
        obj.division = divs.get(j["division"])
        obj.escuela = escuelas.get(j["escuela"])
        obj.categoria = j["categoria"] or ""
        obj.notas = j["notas"] or ""
        obj.sesiones_semana = j["sesiones_semana"]
        obj.sesiones_dia_max = j["sesiones_dia_max"]
        obj.turno_manana = turnos.get(j["turno_manana"])
        obj.turno_tarde = turnos.get(j["turno_tarde"])
        if j["edad"] is not None:
            obj.edad = j["edad"]
            obj.es_menor = j["edad"] < 18
        # El código de cliente lo pone el software de gestión: si producción ya
        # tiene uno, manda el suyo.
        if obj.codigo_cliente is None and j["codigo_cliente"] is not None:
            if not Jugador.objects.filter(
                    codigo_cliente=j["codigo_cliente"]).exclude(pk=obj.pk).exists():
                obj.codigo_cliente = j["codigo_cliente"]
        obj.save()

        Responsable.objects.filter(jugador=obj).delete()
        for nom in j["responsables"]:
            ent = ents.get(_norm(nom))
            if ent:
                Responsable.objects.create(
                    jugador=obj, entrenador=ent, prioridad=1,
                    porcentaje_objetivo=0, activo=True)

    for c in data["contratos"]:
        jug, ent = jugs.get(_norm(c["jugador"])), ents.get(_norm(c["entrenador"]))
        if jug and ent:
            Contrato.objects.update_or_create(
                jugador=jug, entrenador=ent, defaults={"activo": True})


def backward(apps, schema_editor):
    """No deshace nada: son datos del club, no una estructura."""


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0029_turno_activo_y_franja_del_jugador"),
        ("scheduling", "0011_configuracionmotor_peso_pareja"),
    ]

    operations = [migrations.RunPython(forward, backward)]
