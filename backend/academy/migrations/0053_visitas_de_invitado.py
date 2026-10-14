from datetime import date

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


ESTADOS = {"APROBADO": "APROBADA", "PENDIENTE": "PENDIENTE", "RECHAZADO": "RECHAZADA"}


def a_visitas(apps, schema_editor):
    """Cada invitación pasa a ser una persona con sus visitas. Las que eran la
    misma persona (copiada con «Volver a invitar» o con el mismo jugador) se
    juntan en la primera."""
    Invitado = apps.get_model("academy", "Invitado")
    Visita = apps.get_model("academy", "VisitaInvitado")
    persona = {}
    for inv in Invitado.objects.order_by("created_at", "id"):
        raiz = inv
        vistos = set()
        while raiz.repite_de_id and raiz.repite_de_id not in vistos:
            vistos.add(raiz.id)
            raiz = Invitado.objects.get(pk=raiz.repite_de_id)
        if raiz.id == inv.id and inv.jugador_creado_id:
            raiz = persona.get(("j", inv.jugador_creado_id), inv)
        raiz = persona.get(("i", raiz.id), raiz)
        persona[("i", inv.id)] = raiz
        if inv.jugador_creado_id:
            persona.setdefault(("j", inv.jugador_creado_id), raiz)
        for clave, fila in (inv.fechas or {}).items():
            Visita.objects.get_or_create(
                invitado=raiz, fecha=date.fromisoformat(clave),
                defaults=dict(
                    manana=fila.get("manana"), tarde=fila.get("tarde"),
                    solicitante_id=inv.entrenador_solicitante_id,
                    estado=ESTADOS.get(inv.estado, "PENDIENTE"),
                    aprobado_por_id=inv.aprobado_por_id,
                ),
            )
        if raiz.id != inv.id:
            if inv.estado == "APROBADO" and raiz.estado != "APROBADO":
                raiz.estado, raiz.jugador_creado_id = "APROBADO", inv.jugador_creado_id
                raiz.save()
            inv.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('academy', '0052_invitado_fechas_concretas'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='VisitaInvitado',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField()),
                ('manana', models.CharField(blank=True, max_length=2, null=True)),
                ('tarde', models.CharField(blank=True, max_length=2, null=True)),
                ('estado', models.CharField(choices=[('PENDIENTE', 'Pendiente'), ('APROBADA', 'Aprobada'), ('RECHAZADA', 'Rechazada')], default='PENDIENTE', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('aprobado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('invitado', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='visitas', to='academy.invitado')),
                ('solicitante', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='academy.entrenador')),
            ],
            options={
                'verbose_name': 'Visita de invitado',
                'verbose_name_plural': 'Visitas de invitados',
                'ordering': ['fecha', 'invitado__nombre'],
                'constraints': [models.UniqueConstraint(fields=('invitado', 'fecha'), name='una_visita_por_dia')],
            },
        ),
        migrations.RunPython(a_visitas, migrations.RunPython.noop),
        migrations.RemoveField(model_name='invitado', name='fechas'),
        migrations.RemoveField(model_name='invitado', name='fecha_desde'),
        migrations.RemoveField(model_name='invitado', name='fecha_hasta'),
        migrations.RemoveField(model_name='invitado', name='repite_de'),
    ]
