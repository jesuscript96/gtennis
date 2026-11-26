"""Parejas que pueden repetir más días que el tope semanal (26/11/2026).

El director deportivo acepta que María Ruiz y Silvia (Shiying Xia) entrenen
juntas más días que el resto: tienen un nivel bastante distinto al del resto
de la escuela. No es un contrato ni una pareja obligatoria: solo se les quita
el tope de días juntos. Se buscan por nombre; si no están las dos, no se crea
nada. Lo creado queda en el archivo de migraciones: deshacerla lo quita."""
import unicodedata

from django.db import migrations, models

from users import archivo_migraciones as archivo

NOMBRE = "academy.0068_pareja_sin_tope"


def _clave(nombre):
    plano = unicodedata.normalize("NFKD", nombre or "")
    return " ".join("".join(c for c in plano if not unicodedata.combining(c)).lower().split())


def _una(Jugador, empieza):
    cand = [j for j in Jugador.objects.filter(activo=True) if _clave(j.nombre).startswith(empieza)]
    return cand[0] if len(cand) == 1 else None


def crear(apps, schema_editor):
    Jugador = apps.get_model("academy", "Jugador")
    Pareja = apps.get_model("academy", "PreferenciaPareja")
    maria, silvia = _una(Jugador, "maria ruiz naranjo"), _una(Jugador, "shiying xia")
    if maria is None or silvia is None:
        return
    if Pareja.objects.filter(jugador__in=[maria, silvia],
                             jugador_objetivo__in=[maria, silvia]).exists():
        return
    p = Pareja.objects.create(jugador=maria, jugador_objetivo=silvia,
                              tipo="SIN_TOPE", activa=True)
    archivo.guardar(apps, NOMBRE, "creado", p)


def deshacer(apps, schema_editor):
    archivo.deshacer(apps, NOMBRE)


class Migration(migrations.Migration):

    dependencies = [
        ("academy", "0067_puesto_a_quien_volvio_de_baja"),
        ("users", "0007_funciones_preparacion_fisica"),
    ]

    operations = [
        migrations.AlterField(
            model_name="preferenciapareja",
            name="tipo",
            field=models.CharField(
                choices=[("HARD", "Obligatoria (misma pista)"), ("SOFT", "Preferente (bonus)"),
                         ("SIN_TOPE", "Pueden repetir más días (sin tope)")],
                default="HARD", max_length=8),
        ),
        migrations.RunPython(crear, deshacer),
    ]
