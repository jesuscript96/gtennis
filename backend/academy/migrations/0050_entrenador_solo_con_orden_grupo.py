import unicodedata

from django.db import migrations, models


def _normal(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).lower().split())


# 14/10/2026: Dani Gimeno solo entra en pista con estos seis.
LISTA_DANI = [
    "carlos taberner", "carlos sanchez", "raul brancaccio",
    "carlos lopez", "carles cordoba", "yanaki milev",
]


def lista_de_dani(apps, schema_editor):
    Entrenador = apps.get_model("academy", "Entrenador")
    Jugador = apps.get_model("academy", "Jugador")
    dani = next((e for e in Entrenador.objects.all()
                 if _normal(e.nombre).startswith(("daniel gimeno", "dani gimeno"))), None)
    if dani is None:
        return
    jugadores = list(Jugador.objects.filter(activo=True))
    for nombre in LISTA_DANI:
        for j in jugadores:
            if _normal(j.nombre).startswith(nombre):
                dani.solo_con.add(j)


class Migration(migrations.Migration):

    dependencies = [
        ('academy', '0049_entrenador_tarde_solo_con'),
    ]

    operations = [
        migrations.RenameField(
            model_name='entrenador',
            old_name='tarde_solo_con',
            new_name='solo_con',
        ),
        migrations.AlterField(
            model_name='entrenador',
            name='solo_con',
            field=models.ManyToManyField(blank=True, related_name='entrenadores_dedicados', to='academy.jugador', verbose_name='Solo entra en pista con'),
        ),
        migrations.AddField(
            model_name='entrenador',
            name='orden_grupo',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.RunPython(lista_de_dani, migrations.RunPython.noop),
    ]
