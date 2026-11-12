# Lo mismo que `manage.py recuento`, pero para la versión que aún no tiene ese
# comando (la de producción antes de desplegar). Solo lee:
#
#   python manage.py shell < scripts/recuento_shell.py > recuento_antes.json
#
# Después de desplegar: python manage.py recuento --comparar recuento_antes.json
import json

from django.apps import apps

FUERA = {"contenttypes", "auth.permission", "sessions", "admin"}
out = {}
for m in apps.get_models():
    clave = f"{m._meta.app_label}.{m._meta.model_name}"
    if m._meta.app_label in FUERA or clave in FUERA or not m._meta.managed:
        continue
    out[clave] = m._default_manager.count()
print(json.dumps(dict(sorted(out.items())), indent=1))
