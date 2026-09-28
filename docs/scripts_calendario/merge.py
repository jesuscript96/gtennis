"""Paso 2: agrupar entradas del mismo torneo en la misma semana y resolver jugadores/coaches."""
import json
import re
from collections import defaultdict
from names import split_players, resolve_player, resolve_coach, fold, AMBIG
from tourn import category, cities, level

BASE = "/private/tmp/claude-501/-Users-jvch-Desktop-AutomatoWebs-GTennis/a7ac7fa3-9e9e-4f68-b12b-3599a6ea7cc8/scratchpad/tor/"
D = json.load(open(BASE + "raw.json"))
R = [r for r in D["records"] if r["kind"] != "y2025" and r["week"] and r["week"] >= "2025-12-29"]
Y25 = [r for r in D["records"] if r["kind"] == "y2025" or (r["week"] and r["week"] < "2025-12-29")]
NOTES = list(D["notes"])
try:
    from overrides import SAME, SPLIT, NAME, CELL_TO_ROW_OFF
except ImportError:
    SAME, SPLIT, NAME, CELL_TO_ROW_OFF = [], [], {}, set()

SHEET_SHORT = {"DISTRIBUCION CALENDARIO TODO": "Maestra", "GRUPO PABLO": "Pablo", "GRUPO SALVA": "Salva",
               "GRUPO SANTI": "Santi", "GRUPO VICTOR M.": "Víctor M.", "ALVARO": "Álvaro",
               "Grupo ATPChgFutures": "ATP/Chall./Futures", "Grupo Futures": "Futures", "GRUPO SALVA 2": "Salva 2",
               "GRUPO JORGE": "Jorge", "Grupo Mario": "Mario", "NACHO CALVO": "Nacho Calvo (Bonnie)"}


GRID = {"Grupo ATPChgFutures", "Grupo Futures", "GRUPO SALVA 2", "GRUPO JORGE", "Grupo Mario", "NACHO CALVO"}


def ref(r):
    return f"{SHEET_SHORT[r['sheet']]} {r['col']}{r['row']}"


# ---- 1) fila «cont»: jugadores en fila sin torneo → al torneo anterior de la misma hoja
prev = {}
entries = []
for r in R:
    if r["kind"] == "cont":
        p = prev.get(r["sheet"])
        if p is not None and r.get("players_raw"):
            p["players_raw"] = (p.get("players_raw") + ", " if p.get("players_raw") else "") + r["players_raw"]
            p["kind"] = "conv"
            p.setdefault("extra_rows", []).append(r["row"])
        continue
    if r["kind"] in ("conv", "opcion") and r["sheet"] not in ("Grupo ATPChgFutures", "Grupo Futures", "GRUPO SALVA 2",
                                                                 "GRUPO JORGE", "Grupo Mario", "NACHO CALVO"):
        prev[r["sheet"]] = r
    entries.append(r)

# ---- 2) celdas de jugador en hojas con columna de torneo (Santi): si la celda nombra el torneo de su fila, se unen
for r in entries:
    r["_key"] = None
    txt = r["torneo"] or ""
    r["_txt"] = re.sub(r"^(OPC\s*\d+\s*:\s*)", "", txt, flags=re.I).strip()
    if r["sheet"] == "GRUPO VICTOR M.":  # «(MARCOS ROMERO)», «(ERIC BADENES)»: jugador, no sede
        r["_txt"] = re.sub(r"\((MARCOS ROMERO|ERIC BADENES)\)", "", r["_txt"]).strip()
    r["_cat"] = category(r["_txt"], r.get("categoria_col"))
    r["_cities"] = cities(r["_txt"])
    r["_level"] = level(r["_txt"])
    if r["kind"] == "cell" and r.get("row_torneo") and (r["sheet"], r["row"], r["col"]) not in CELL_TO_ROW_OFF:
        rc = category(r["row_torneo"])
        if rc == r["_cat"] or r["_cat"] == "Otros" or not (r["_cities"] - cities(r["row_torneo"])):
            r["_txt_orig"] = r["_txt"]
            r["_cat"], r["_cities"], r["_level"] = rc, cities(r["row_torneo"]) | r["_cities"], level(r["row_torneo"]) or r["_level"]
            r["_via_row"] = r["row_torneo"]


# ---- 2b) celdas de rejilla: el circuito sale de la columna-calendario del mismo grupo y semana
opts = defaultdict(list)
for r in entries:
    if r["kind"] == "opcion" and r.get("categoria_col"):
        opts[(r["sheet"], r["week"])].append(r)
for r in entries:
    if r["kind"] != "cell" or r.get("_via_row"):
        continue
    cand = [o for o in opts[(r["sheet"], r["week"])] if o["_cities"] & r["_cities"]
            and (not r["_level"] or not o["_level"] or o["_level"] == r["_level"])]
    if cand:
        o = cand[0]
        r["_cat"], r["_level"] = o["_cat"], r["_level"] or o["_level"]
        r["_cities"] |= o["_cities"]
    elif r["_cat"] == "Otros":
        m = re.search(r"\b(15|25)\b", fold(r["_txt"]))
        if m and r["sheet"] in ("Grupo Futures", "Grupo ATPChgFutures"):
            r["_cat"], r["_level"] = "ITF M", "M" + m.group(1)
        m = re.search(r"\b(50|75|100|125|175)\b", fold(r["_txt"]))
        if r["_cat"] == "Otros" and m and r["sheet"] in ("Grupo ATPChgFutures", "GRUPO SALVA 2"):
            r["_cat"] = "Challenger"

# ---- 3) clusters por semana
def compatible(a, b):
    if a["_cat"] != b["_cat"]:
        return False
    if a["_level"] and b["_level"] and a["_level"] != b["_level"]:
        return False
    if not a["_cities"] or not b["_cities"]:
        return False
    return bool(a["_cities"] & b["_cities"])


by_week = defaultdict(list)
for r in entries:
    if r["kind"] == "activ":
        continue
    by_week[r["week"]].append(r)

clusters = []
for w in sorted(by_week):
    items = by_week[w]
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            ka, kb = ref(a), ref(b)
            if any({ka, kb} <= set(s) for s in SPLIT):
                continue
            if compatible(a, b) or any({ka, kb} <= set(s) for s in SAME):
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i, it in enumerate(items):
        groups[find(i)].append(it)
    gl = list(groups.values())

    def gcities(g):
        return set().union(*(i["_cities"] for i in g))

    def glevel(g):
        return {i["_level"] for i in g if i["_level"]}

    def gcat(g):
        cs = [i["_cat"] for i in g if i["_cat"] != "Otros"]
        return max(set(cs), key=cs.count) if cs else "Otros"

    def has_assign(g):
        return any(i["kind"] in ("conv", "cell") or i["sheet"] not in GRID for i in g)

    # (a) torneos sin ciudad («M25», «Us open», «2da fase Provincial»): al único compatible de la semana
    empties = defaultdict(list)
    for g in [g for g in gl if not gcities(g) and gcat(g) != "Otros"]:
        empties[(gcat(g), frozenset(glevel(g)))].append(g)
    for gs in empties.values():
        for g in gs[1:]:
            gs[0].extend(g); gl.remove(g)
    changed = True
    while changed:
        changed = False
        for g in [g for g in gl if not gcities(g) and gcat(g) != "Otros"]:
            same = [h for h in gl if h is not g and gcat(h) == gcat(g)
                    and (not glevel(g) or not glevel(h) or glevel(g) & glevel(h))]
            pref = [h for h in same if has_assign(h)] or same
            if len(pref) == 1:
                pref[0].extend(g); gl.remove(g); changed = True
                break
    # (b) textos sin circuito («Torrente», «Catarroja», «GANDIA»): al único torneo de la semana con esa ciudad
    for g in [g for g in gl if gcat(g) == "Otros"]:
        cand = [h for h in gl if h is not g and gcat(h) != "Otros" and gcities(h) & gcities(g)]
        if len(cand) == 1:
            cand[0].extend(g); gl.remove(g)
    for g in gl:
        clusters.append(dict(week=w, items=g))

json.dump(dict(clusters=clusters, notes=NOTES), open(BASE + "clusters.json", "w"), ensure_ascii=False, default=list)

if __name__ == "__main__":
    for c in clusters:
        its = c["items"]
        kinds = {i["kind"] for i in its}
        cat = its[0]["_cat"]
        names = sorted({i["_txt"] for i in its})
        print(f"{c['week']} [{cat}] {' | '.join(names)[:230]}  <{', '.join(ref(i) for i in its)[:200]}>{' *CONV' if kinds & {'conv','cell'} else ''}")
