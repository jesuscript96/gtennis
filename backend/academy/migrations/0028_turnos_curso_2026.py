"""Horario de curso 2026-2027 (septiembre en adelante).

Los turnos que había eran los de verano (5 franjas, 8:00-16:30). El curso tiene
ocho, con horas distintas y tres franjas de tarde nuevas — las de la escuela y
el grupo de división 8, que en julio y agosto estaban vacías y por eso nunca
aparecieron:

    M1  08:30-10:00     T1  14:15-15:30     T4  17:30-19:15
    M2  10:30-12:30     T2  15:30-16:45     T5  19:15-21:15
    JP  12:30-14:30     T3  15:30-17:30

T2 y T3 se solapan en el tiempo: son bloques distintos que conviven en pistas
distintas (T2 apenas se usa). El motor no impide hoy que una misma pista se
reserve en dos turnos solapados; queda anotado.

Los horarios de verano se conservan en `hora_inicio_verano`/`hora_fin_verano`
para que julio y agosto sigan resolviéndose con sus franjas.
"""
from datetime import time

from django.db import migrations

TURNOS = [
    # codigo, nombre,           bloque,   inicio,       fin,          verano_ini,   verano_fin,  orden
    ("M1", "Mañana 1",          "MANANA", time(8, 30),  time(10, 0),  time(8, 0),   time(10, 0),  1),
    ("M2", "Mañana 2",          "MANANA", time(10, 30), time(12, 30), time(10, 0),  time(12, 0),  2),
    ("JP", "Junior Program",    "MANANA", time(12, 30), time(14, 30), time(12, 0),  time(14, 0),  3),
    ("T1", "Tarde 1",           "TARDE",  time(14, 15), time(15, 30), time(14, 0),  time(15, 15), 4),
    ("T2", "Tarde 2",           "TARDE",  time(15, 30), time(16, 45), time(15, 15), time(16, 30), 5),
    ("T3", "Escuela tarde",     "TARDE",  time(15, 30), time(17, 30), None,         None,         6),
    ("T4", "Escuela noche",     "TARDE",  time(17, 30), time(19, 15), None,         None,         7),
    ("T5", "Adultos",           "TARDE",  time(19, 15), time(21, 15), None,         None,         8),
]


def forward(apps, schema_editor):
    Turno = apps.get_model("academy", "Turno")
    Asignacion = apps.get_model("scheduling", "Asignacion")
    Semana = apps.get_model("scheduling", "Semana")

    # El histórico guardado era de pruebas, no de producción, y está montado
    # sobre las franjas de verano. Se limpia para partir del curso actual.
    Asignacion.objects.all().delete()
    Semana.objects.all().delete()

    for cod, nom, blo, ini, fin, vini, vfin, orden in TURNOS:
        Turno.objects.update_or_create(
            codigo=cod,
            defaults={
                "nombre": nom, "bloque": blo,
                "hora_inicio": ini, "hora_fin": fin,
                "hora_inicio_verano": vini, "hora_fin_verano": vfin,
                "orden": orden,
            },
        )
    Turno.objects.exclude(codigo__in=[t[0] for t in TURNOS]).delete()


def backward(apps, schema_editor):
    Turno = apps.get_model("academy", "Turno")
    Turno.objects.filter(codigo__in=("T3", "T4", "T5")).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0027_jugador_sesiones_dia_max_jugador_sesiones_semana"),
        ("scheduling", "0011_configuracionmotor_peso_pareja"),
    ]

    operations = [migrations.RunPython(forward, backward)]
