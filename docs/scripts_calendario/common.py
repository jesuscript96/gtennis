import datetime as dt
import json
import re

BASE = "/private/tmp/claude-501/-Users-jvch-Desktop-AutomatoWebs-GTennis/a7ac7fa3-9e9e-4f68-b12b-3599a6ea7cc8/scratchpad/tor/"
F = json.load(open(BASE + "final.json"))
T = F["tournaments"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
MES3 = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

KEEP_UP = {"ITF", "WTA", "ATP", "CH", "IBP", "MARCA", "CT", "CV", "TTK", "US", "AO", "CPV", "CD", "CC", "CDR", "CCVM",
           "UAE", "II", "III", "IV", "XI", "XLV", "XXXIX", "XXX", "SUB", "ABS", "GS", "JGS", "RPT", "IALE", "YTT", "TT",
           "FTCV", "BCN", "VLC", "RN"}


def pretty(name):
    t = re.sub(r"\s+", " ", name).strip()
    words = []
    for w in t.split(" "):
        core = re.sub(r"[^\wÁÉÍÓÚÑÜáéíóúñü]", "", w)
        if re.search(r"\b[JMW]\d{2,3}\b", w, re.I) and "/" in w:
            words.append(w.upper()); continue
        if core.upper() in KEEP_UP or re.fullmatch(r"[JMW]\d+|[JMW]\dO+|\d+\w*", core, re.I):
            words.append(w.upper() if core.upper() in KEEP_UP or re.fullmatch(r"[JMW]\d+", core, re.I) else w)
        elif w.isupper() and len(core) > 1:
            words.append(w.capitalize() if not w.startswith("(") else "(" + w[1:].capitalize())
        else:
            words.append(w)
    out = " ".join(words)
    out = re.sub(r"(?<=\s)(De|Del|Y|Al|A|En)\b", lambda m: m.group(1).lower(), out)
    return out[0].upper() + out[1:] if out else out


def short(name, n=46):
    t = pretty(name)
    t = re.sub(r"\b(todas las categor[ií]as|todas categor[ií]as|fin de semana|finde|\(hard\)|hard|masc y fem)\b", "", t, flags=re.I)
    t = re.sub(r"\(\s*\)", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -·,")
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def wrange(w):
    d = dt.date.fromisoformat(w)
    e = d + dt.timedelta(days=6)
    if d.month == e.month:
        return f"{d.day}–{e.day} {MESES[d.month - 1]} {d.year}"
    if d.year == e.year:
        return f"{d.day} {MESES[d.month - 1]} – {e.day} {MESES[e.month - 1]} {e.year}"
    return f"{d.day} {MESES[d.month - 1]} {d.year} – {e.day} {MESES[e.month - 1]} {e.year}"


def wshort(w):
    d = dt.date.fromisoformat(w)
    return f"{d.day} {MES3[d.month - 1]}"


def fdate(iso):
    try:
        d = dt.date.fromisoformat(iso)
        return f"{d:%d/%m/%Y}"
    except ValueError:
        return iso


WEEKS = sorted({t["week"] for t in T})
ALLWEEKS = []
d = dt.date(2025, 12, 29)
while d <= dt.date(2026, 12, 28):
    ALLWEEKS.append(d.isoformat())
    d += dt.timedelta(days=7)


def weekno(w):
    return ALLWEEKS.index(w)  # 0 = semana del 29/12/2025


CAT_ORDER = ["Grand Slam", "ATP", "WTA", "Copa Davis", "Challenger", "ITF M", "ITF W", "ITF Junior", "Tennis Europe",
             "Campeonato de España", "Campeonato autonómico/nacional", "Campeonato regional", "MARCA", "IBP",
             "Rafa Nadal Tour", "Mutua Madrid Open Sub-16", "TTK Warriors", "Babolat Cup", "Absoluto / Open",
             "Torneo Femenino Generalitat", "Champions Cup/Bowl", "Copa Faulcombridge", "Young Tennis Tour",
             "Circuito Tecnifibre", "Circuito Provincial", "Circuito Diputación", "Valencia Tennis Tour",
             "Circuito More&Tennis", "Spartan Tour", "Circuito G", "Otros"]


def catkey(c):
    return CAT_ORDER.index(c) if c in CAT_ORDER else 99


def coach_text(t):
    parts = []
    if t["acompanan"]:
        parts.append(", ".join(t["acompanan"]))
    return "; ".join(parts)


def ref_text(t):
    by = {}
    for p in t["players"]:
        for c in p["entrenador_ref"]:
            by.setdefault(c, []).append(p["nombre"].split(" (")[0].split(" ")[0] if False else p["nombre"])
    return by
