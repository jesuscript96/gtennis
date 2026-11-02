"""El PDF para la familia en su idioma (02/11/2026).

En la app todo se escribe y se revisa en español; solo el PDF que se envía a
una familia que lo pide en inglés sale traducido. La traducción se guarda en
la propia evaluación (`traduccion`) con una firma de los textos de origen: si
nadie cambia nada, no se vuelve a pedir a Claude. Si Claude falla, quien llama
recibe `ia.IANoDisponible`.
"""
import hashlib
import json

from . import catalogo, ia


def _traducir(obj, textos, origen, idioma):
    if idioma == origen or not textos:
        return textos
    jugador = obj.jugador
    nombre, sexo = jugador.nombre.split()[0], jugador.sexo or ""
    firma = hashlib.sha1(json.dumps([idioma, nombre, sexo, textos], sort_keys=True, ensure_ascii=False)
                         .encode()).hexdigest()
    cache = obj.traduccion or {}
    if cache.get("firma") == firma:
        return cache["textos"]
    out = ia.traducir(textos, idioma, nombre, sexo)
    obj.traduccion = {"firma": firma, "textos": out}
    obj.save(update_fields=["traduccion"])
    return out


def tenis(ev, idioma):
    """Los textos de la evaluación de tenis en `idioma`:
    `{"comentarios": {bloque: texto}, "fortalezas": [...], "mejoras": [...]}`."""
    fortalezas = [f for f in ev.fortalezas if f.strip()]
    mejoras = [m for m in ev.mejoras if m.strip()]
    textos = {f"c_{k}": c["pulido"] for k, c in ev.comentarios.items() if (c or {}).get("pulido")}
    textos.update({f"f_{i}": f for i, f in enumerate(fortalezas)})
    textos.update({f"m_{i}": m for i, m in enumerate(mejoras)})
    out = _traducir(ev, textos, ev.idioma, idioma)
    return {
        "comentarios": {k[2:]: v for k, v in out.items() if k.startswith("c_")},
        "fortalezas": [out[f"f_{i}"] for i in range(len(fortalezas))],
        "mejoras": [out[f"m_{i}"] for i in range(len(mejoras))],
    }


def fisica(evf, idioma):
    """Los textos del preparador físico (se escriben en español) en `idioma`."""
    textos = {k: v for k, v in evf.textos.items() if k in dict(catalogo.TEXTOS_FISICO) and (v or "").strip()}
    return _traducir(evf, textos, "ES", idioma)
