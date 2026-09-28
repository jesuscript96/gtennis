"""Paso 3: construir el calendario final (torneo × semana) con jugadores, coaches, cierres e incidencias."""
import datetime as dt
import json
import re
from collections import defaultdict, Counter
import merge
from merge import clusters, ref, SHEET_SHORT, GRID, entries, Y25
from names import split_players, resolve_player, resolve_coach, fold, AMBIG, P
from tourn import category, cities, level

BASE = merge.BASE
PRIO = ["DISTRIBUCION CALENDARIO TODO", "GRUPO PABLO", "GRUPO SANTI", "GRUPO SALVA", "GRUPO VICTOR M.", "ALVARO",
        "GRUPO JORGE", "Grupo Mario", "Grupo Futures", "Grupo ATPChgFutures", "GRUPO SALVA 2", "NACHO CALVO"]
LISTS = {"DISTRIBUCION CALENDARIO TODO", "GRUPO PABLO", "GRUPO SANTI", "GRUPO SALVA", "GRUPO VICTOR M.", "ALVARO"}
MARIO_COL = {"?COL_E": "E", "?COL_F": "F", "?COL_G": "G", "?COL_H": "H"}

incid = []


def inc(tipo, semana, torneo, detalle, fuente="", gravedad="media"):
    incid.append(dict(tipo=tipo, semana=semana, torneo=torneo, detalle=detalle, fuente=fuente, gravedad=gravedad))


for n in merge.NOTES:
    inc(n["tipo"], "", "", n["detalle"], f"{SHEET_SHORT.get(n['sheet'], n['sheet'])} fila {n['row']}", "baja")


def clean(t):
    t = re.sub(r"^\s*-\s*", "", t or "")
    t = re.sub(r"\s*\*\s*$", "", t)
    t = t.replace("|", " ")
    return re.sub(r"\s+", " ", t).strip(" /")


def parse_cierre(v, week):
    """→ (fecha|None, texto). Acepta ISO, dd/mm/yyyy, dd/mm, «Cierre 22/12/2025 18:00», «CIERRA 09»…"""
    if not v:
        return None, ""
    t = str(v)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", t)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), t
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", t)
    if m:
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        try:
            return dt.date(y, int(m.group(2)), int(m.group(1))), t
        except ValueError:
            return None, t
    if re.search(r"\bal\b|\bdel\b|CLUB DE TENIS|COLLAO|FINDE|Finales|semana|TODAS", t, re.I):
        return None, "NOFECHA:" + t
    m = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!/\d)", t)
    if m:
        try:
            return dt.date(week.year if int(m.group(2)) <= week.month + 1 else week.year - 1, int(m.group(2)), int(m.group(1))), t
        except ValueError:
            return None, t
    MESES = dict(enero=1, febrero=2, marzo=3, abril=4, mayo=5, junio=6, julio=7, agosto=8, septiembre=9, octubre=10, noviembre=11, diciembre=12)
    m = re.search(r"(\d{1,2})\s+(" + "|".join(MESES) + r")", t, re.I)
    if m:
        return dt.date(week.year, MESES[m.group(2).lower()], int(m.group(1))), t
    m = re.search(r"(?:lunes|cierra)\s+(\d{1,2})\b|\b(\d{1,2})\s+cierra", t, re.I)
    if m:
        dd = int(m.group(1) or m.group(2))
        mo = week.month if dd <= week.day + 6 else week.month - 1
        try:
            return dt.date(week.year, mo, dd), t
        except ValueError:
            return None, t
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", t.strip())
    if m:
        try:
            return dt.date(week.year, int(m.group(2)), int(m.group(1))), t
        except ValueError:
            return None, t
    return None, t


tournaments = []
for c in clusters:
    items = sorted(c["items"], key=lambda i: (PRIO.index(i["sheet"]), i["row"]))
    week = dt.date.fromisoformat(c["week"])
    cats = [i["_cat"] for i in items if i["_cat"] != "Otros"]
    cat = max(set(cats), key=cats.count) if cats else "Otros"
    # nombre: la fila de una hoja-lista si existe; si no, el texto más completo
    named = [i for i in items if i["sheet"] in LISTS and i["kind"] in ("conv", "opcion")]
    named = [i for i in named if i["_cat"] != "Otros" and i["_cities"]] or named
    if named:
        name = clean(named[0]["_txt"])
    else:
        opts = [i for i in items if i["kind"] == "opcion"]
        name = clean(max((opts or items), key=lambda i: len(i["_txt"]))["_txt"])
    variants = sorted({clean(i["_txt"]) for i in items} - {name})

    # jugadores
    pmap = {}   # nombre -> dict

    def addp(nm, estado, fuente, detalle="", cands=(), dudoso=False, tok=""):
        d = pmap.setdefault(nm, dict(nombre=nm, estados=set(), fuentes=[], detalles=[], cands=set(), dudoso=False, toks=set()))
        d["estados"].add(estado); d["fuentes"].append(fuente); d["cands"] |= set(cands); d["toks"].add(tok)
        if detalle:
            d["detalles"].append(detalle)
        d["dudoso"] |= dudoso

    for i in items:
        if i["kind"] == "conv" and i.get("players_raw"):
            for tok, doubt in split_players(i["players_raw"]):
                nm, st, cands = resolve_player(tok, i["sheet"], i["row"])
                addp(nm, st, ref(i), cands=cands, dudoso=doubt, tok=fold(tok))
        if i["kind"] == "cell":
            pc = i["player_col"]
            if i["sheet"] == "Grupo Mario" and pc in MARIO_COL:
                nm, st, cands = f"Sin identificar (hoja Mario, col. {MARIO_COL[pc]})", "desconocido", []
            else:
                nm, st, cands = resolve_player(pc, i["sheet"], i["row"])
            raw = i.get("_txt_orig") or i["torneo"]
            det = raw if fold(raw) != fold(name) else ""
            doubt = "?" in (i["torneo"] or "") or bool(re.search(r"^puede|ver segun", i["torneo"] or "", re.I))
            if re.search(r"no jug", i["torneo"] or "", re.I):
                det = "No jugó (según la hoja)"
            mo = re.match(r"\s*opc\s*(\d)", i["torneo"] or "", re.I)
            if mo:
                det = f"Opción {mo.group(1)} (hoja de Santi)"
            if i["sheet"] == "NACHO CALVO":
                det = "Planificación de Bonnie (hoja Nacho Calvo)"
            addp(nm, st, ref(i), det, cands, doubt, fold(pc))
    # un nombre suelto ambiguo sobra si su candidato ya está escrito con apellido en otra hoja
    for nm in list(pmap):
        d = pmap[nm]
        if d["estados"] <= {"inferido", "ambiguo"} and d["cands"]:
            explicit = [k for k in pmap if k != nm and k in d["cands"]
                        and ("ok" in pmap[k]["estados"] or "ambiguo" in d["estados"])]
            others = [k for k in d["cands"] if k != nm]
            if nm in d["cands"] and any(k in pmap and "ok" in pmap[k]["estados"] for k in [nm]):
                continue
            if explicit and nm not in explicit:
                # ¿el mismo token apunta a quien ya está? p.ej. DIEGO (Pablo) junto a DIEGO V (Maestra)
                tgt = explicit[0]
                pmap[tgt]["fuentes"] += d["fuentes"]; pmap[tgt]["detalles"] += d["detalles"]
                del pmap[nm]
    for d in pmap.values():
        if "ok" in d["estados"]:
            d["certeza"] = "confirmado"
        elif "inferido" in d["estados"]:
            d["certeza"] = "deducido"
        else:
            d["certeza"] = "sin identificar"
        if d["dudoso"]:
            d["certeza"] += " · pendiente (?)"

    # coaches que acompañan (hojas-lista) y entrenador de referencia (rejillas)
    acomp, acomp_estado, refcoach = [], set(), defaultdict(set)
    pl_names = list(pmap)
    for i in items:
        if i.get("coach_role") == "acompaña" and i.get("coach_raw") and (i["kind"] in ("conv", "opcion") or (i["kind"] == "cell" and i.get("_via_row"))):
            cs, st = resolve_coach(i["coach_raw"], name, pl_names)
            for x in cs:
                if x not in acomp:
                    acomp.append(x)
            acomp_estado.add(st)
        if i.get("coach_role") == "responsable" and i["kind"] == "cell":
            cs, _ = resolve_coach(i["coach_raw"])
            pn = [p for p in pmap if ref(i) in pmap[p]["fuentes"]]
            for p in pn:
                refcoach[p] |= set(cs)
    if "Víctor M." in acomp and any(i["sheet"] == "GRUPO VICTOR M." for i in items):
        pass
    # «Víctor M.» en su propia hoja es el responsable, no necesariamente acompañante
    if [a for a in acomp if a not in ("Sí, con coach (sin nombre)", "Sin acompañante", "No va coach", "Por decidir")]:
        acomp = [a for a in acomp if a != "Sí, con coach (sin nombre)"]
    vm_only = not any(i.get("coach_role") == "acompaña" and "VICTOR M" in fold(i.get("coach_raw") or "") for i in items)
    if vm_only:
        acomp = [a for a in acomp if a != "Víctor M."]
    for i in items:
        if i["sheet"] == "GRUPO VICTOR M." and i["kind"] == "conv":
            for p in pmap:
                if ref(i) in pmap[p]["fuentes"]:
                    refcoach[p].add("Víctor M.")

    # cierres
    cierres = {}
    notas_t = []
    for i in items:
        if i.get("cierre"):
            d, t = parse_cierre(i["cierre"], week)
            if t in ("NUEVO", "-", "semana", "Finales", "Finales Domingo", "Campeona Jennie") or t.startswith("NOFECHA:"):
                if t == "NUEVO":
                    cierres.setdefault("(torneo nuevo en el calendario)", []).append(ref(i))
                elif t.startswith("NOFECHA:"):
                    notas_t.append(t[8:])
                continue
            cierres.setdefault((d.isoformat() if d else t), []).append(ref(i))

    named_coach = [a for a in acomp if a not in ("No va coach", "Sin acompañante", "Sí, con coach (sin nombre)",
                                                 "Sin asignar (S/A)", "Por decidir")]
    kind = "convocatoria" if (pmap or named_coach) else "calendario"
    t = dict(week=c["week"], name=name, cat=cat, variants=variants, kind=kind,
             players=[dict(nombre=d["nombre"], certeza=d["certeza"], fuentes=sorted(set(d["fuentes"])),
                           detalle="; ".join(sorted(set(d["detalles"]))),
                           grupo=P.get(d["nombre"], {}).get("grupo", ""),
                           entrenador_ref=sorted(refcoach.get(d["nombre"], set())))
                      for d in sorted(pmap.values(), key=lambda d: d["nombre"])],
             acompanan=acomp, acomp_estado=sorted(acomp_estado),
             cierres=cierres, notas=sorted(set(notas_t)), sources=[ref(i) for i in items],
             sheets=sorted({SHEET_SHORT[i["sheet"]] for i in items}),
             list_sheets=sorted({i["sheet"] for i in items if i["sheet"] in LISTS}),
             cities=sorted(set().union(*(i["_cities"] for i in items))),
             levels=sorted({i["_level"] for i in items if i["_level"]}))
    tournaments.append(t)

# ------------------------------------------------------------ incidencias
tw = defaultdict(list)
for t in tournaments:
    tw[t["week"]].append(t)


def wk_label(w):
    d = dt.date.fromisoformat(w)
    return f"{d:%d/%m}"


for t in tournaments:
    w = dt.date.fromisoformat(t["week"])
    good = []
    for k, refs in t["cierres"].items():
        if k.startswith("("):
            continue
        try:
            d = dt.date.fromisoformat(k)
        except ValueError:
            inc("Cierre ilegible", t["week"], t["name"], f"El cierre «{k}» no es una fecha válida.", ", ".join(refs))
            continue
        if d > w + dt.timedelta(days=6):
            alt = d.replace(year=d.year - 1)
            hint = f" Probablemente {alt:%d/%m/%Y}." if 0 < (w - alt).days < 60 else " Revisar la fecha."
            inc("Cierre posterior al torneo", t["week"], t["name"],
                f"Cierre {d:%d/%m/%Y}, posterior a la semana del torneo ({w:%d/%m/%Y}).{hint}", ", ".join(refs), "alta")
        elif d.year < w.year and (w - d).days > 60:
            inc("Cierre con año anterior", t["week"], t["name"],
                f"Cierre {d:%d/%m/%Y} para un torneo de la semana del {w:%d/%m/%Y}: el año parece copiado de la plantilla "
                f"(sería {d.replace(year=d.year + 1):%d/%m/%Y}).", ", ".join(refs), "alta")
        else:
            good.append(d)
    if len(set(good)) > 1:
        inc("Cierre distinto según la hoja", t["week"], t["name"],
            "; ".join(f"{k} ({', '.join(v)})" for k, v in t["cierres"].items()), "", "media")
    for p in t["players"]:
        if "pendiente" in p["certeza"]:
            inc("Jugador pendiente de confirmar", t["week"], t["name"],
                f"{p['nombre']} aparece con «?»{(' — ' + p['detalle']) if p['detalle'] else ''}.", ", ".join(p["fuentes"]), "baja")
        if p["certeza"].startswith("sin identificar"):
            inc("Jugador sin identificar", t["week"], t["name"], f"«{p['nombre']}»: no se sabe quién es.",
                ", ".join(p["fuentes"]), "media")

# mismo torneo en semanas distintas según la hoja
keys = defaultdict(list)
for t in tournaments:
    if t["list_sheets"] or t["kind"] == "convocatoria":
        keys[t["cat"]].append(t)
seen = set()
for cat, ts in keys.items():
    for a in ts:
        for b in ts:
            if a is b or a["week"] >= b["week"]:
                continue
            da, db = dt.date.fromisoformat(a["week"]), dt.date.fromisoformat(b["week"])
            if (db - da).days != 7 or not (set(a["cities"]) & set(b["cities"])):
                continue
            if set(a["sheets"]) & set(b["sheets"]):
                continue
            k = (a["name"], b["name"], a["week"])
            if k in seen:
                continue
            seen.add(k)
            inc("Mismo torneo en semanas distintas", a["week"], a["name"],
                f"{', '.join(a['sheets'])} lo ponen en la semana del {da:%d/%m}; {', '.join(b['sheets'])} en la del "
                f"{db:%d/%m} («{b['name']}»). Puede ser un torneo a caballo entre dos semanas.", "", "media")

# mismo sitio, distinto nivel en la misma semana
for w, ts in tw.items():
    for i, a in enumerate(ts):
        for b in ts[i + 1:]:
            if a["cat"] == b["cat"] and set(a["cities"]) & set(b["cities"]) and a["levels"] and b["levels"] \
                    and set(a["levels"]) != set(b["levels"]) and (a["kind"] == "convocatoria" or b["kind"] == "convocatoria") \
                    and a["cat"] in ("ITF M", "ITF W", "ITF Junior"):
                inc("Nivel distinto según la hoja", w, a["name"],
                    f"«{a['name']}» ({', '.join(a['sheets'])}) frente a «{b['name']}» ({', '.join(b['sheets'])}).", "", "media")
# dentro de un mismo torneo, números de categoría distintos (ITF 300 vs J200)
for t in tournaments:
    if t["cat"] == "ITF Junior":
        nums = set()
        for v in [t["name"]] + t["variants"]:
            m = re.search(r"\b(?:ITF\s*J?|J)\s?(30|60|100|200|300|500)\b", fold(v))
            if m:
                nums.add(m.group(1))
        if len(nums) > 1:
            inc("Nivel distinto según la hoja", t["week"], t["name"],
                f"Se escribe con niveles distintos: {', '.join('J' + n for n in sorted(nums, key=int))} ({' / '.join([t['name']] + t['variants'])}).",
                "", "media")

WEEKEND = {"Champions Cup/Bowl", "Copa Faulcombridge", "Young Tennis Tour", "Circuito Tecnifibre", "Circuito Provincial",
           "Circuito Diputación", "Mutua Madrid Open Sub-16", "Valencia Tennis Tour", "Absoluto / Open",
           "Torneo Femenino Generalitat", "Spartan Tour", "Circuito G"}
# jugador en dos torneos a la vez
for w, ts in tw.items():
    who = defaultdict(list)
    for t in ts:
        if t["kind"] != "convocatoria":
            continue
        for p in t["players"]:
            if p["nombre"].startswith("Sin identificar") or t["cat"] in WEEKEND:
                continue
            if re.search(r"Opción|Planificación", p["detalle"]):
                continue
            who[p["nombre"]].append(t)
    for p, lst in who.items():
        if len(lst) > 1:
            inc("Jugador en dos torneos la misma semana", w, " / ".join(x["name"] for x in lst),
                f"{p} figura en {len(lst)} torneos: " + "; ".join(f"«{x['name']}» ({', '.join(x['sheets'])})" for x in lst)
                + ". Puede ser correcto (fin de semana + entre semana, u opciones alternativas).", "", "baja")

# maestra frente a hojas de grupo
for t in tournaments:
    srcs = defaultdict(set)
    for p in t["players"]:
        for f in p["fuentes"]:
            srcs[f.split(" ")[0]].add(p["nombre"])
    if "Maestra" in srcs:
        for sh, ps in srcs.items():
            if sh == "Maestra" or sh in ("ATP/Chall./Futures", "Futures", "Nacho"):
                continue
            falta = {x for x in ps - srcs["Maestra"] if not x.startswith("Sin identificar")}
            if falta:
                inc("La hoja maestra no recoge a todos", t["week"], t["name"],
                    f"La hoja de {sh} incluye a {', '.join(sorted(falta))}, que no está{'n' if len(falta) > 1 else ''} en la maestra.",
                    "", "media")

# actividades (no torneo)
activ = []
for r in entries:
    if r["kind"] == "activ":
        who = r.get("player_col")
        if who:
            names_ = [resolve_player(who, r["sheet"], r["row"])[0]]
        else:
            names_ = [resolve_player(tk, r["sheet"], r["row"])[0] for tk, _ in split_players(r.get("players_raw") or "")] or ["(sin jugador)"]
        for nm in names_:
            activ.append(dict(week=r["week"], jugador=nm, texto=clean(r["torneo"]).capitalize(), fuente=ref(r)))

# restos 2025
y25 = []
for r in Y25:
    y25.append(dict(hoja=SHEET_SHORT.get(r["sheet"], r["sheet"]), fila=r["row"], semana=r.get("week") or "",
                    torneo=clean(r.get("torneo") or ""), cierre=r.get("cierre", ""), coach=r.get("coach_raw", ""),
                    jugadores=r.get("players_raw", "")))

# criterios de identificación usados
crit = Counter()
for t in tournaments:
    for p in t["players"]:
        if p["certeza"].startswith("deducido"):
            crit[p["nombre"]] += 1

json.dump(dict(tournaments=tournaments, incid=incid, activ=activ, y25=y25, crit=crit), open(BASE + "final.json", "w"),
          ensure_ascii=False, indent=1, default=list)
if __name__ == "__main__":
    print(len(tournaments), Counter(t["kind"] for t in tournaments))
    print(Counter(i["tipo"] for i in incid))
    print(len(activ), len(y25))
    allp = Counter(p["nombre"] for t in tournaments if t["kind"] == "convocatoria" for p in t["players"])
    print(len(allp), "jugadores")
    coaches = Counter(a for t in tournaments for a in t["acompanan"])
    print(coaches)
