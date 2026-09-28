"""Identificación de jugadores y coaches a partir de lo escrito a mano en el Excel."""
import re
import unicodedata


def fold(t):
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 ]", " ", t)).strip().upper()


# ------------------------------------------------------------------ jugadores
# nombre canónico -> (grupo/escuela orientativo, alias exactos ya "fold")
P = {}


def pl(name, *aliases, grupo=""):
    P[name] = dict(grupo=grupo, aliases={fold(a) for a in aliases} | {fold(name)})


# Alto rendimiento — profesionales y Futures
pl("Carlos Taberner", "TABERNER", "CARLOS TABERNER", grupo="Pro")
pl("Carlos Sánchez Jover", "SANCHEZ", "CARLOS SANCHEZ", "CARLOS SANCHEZ 370", grupo="Pro")
pl("Raúl Brancaccio", "BRANCACCIO", "RAUL BRANCACCIO", grupo="Pro")
pl("Carlos López Montagud", "CARLOS LOPEZ", grupo="Pro")
pl("Félix Gil", "FELIX", "FELIX GIL", grupo="Pro")
pl("Pablo Llamas", "PABLO LLAMAS", grupo="Pro")
pl("Elina Avanesian", "ELINA", "ELINA AVANESYAN", grupo="Pro")
pl("Yanaki Milev", "YANAKI MILEV", grupo="Futures")
pl("Ignacio Parisca", "PARISCA", "NACHO PARISCA", grupo="Futures")
pl("Carles Córdoba", "CORDOBA", "CARLES", "CARLES CORDOBA", grupo="Futures")
pl("Toprak Avcibasi", "TOPRAK", grupo="Futures")
pl("Alejandro García Carbajal", "ALEX", "ALEX GARCIA", grupo="Futures")
pl("Marc Martín Roca", "MARC MARTIN", grupo="Futures")
pl("Sergio Planella", "PLANELLA", "SERGIO PLANELLA", grupo="Futures")
pl("Mateo Álvarez", "MATEO", "MATEO ALVAREZ", grupo="Futures")
pl("María Andrienko", "MARIA ANDRIENKO", grupo="Futures")
pl("Lucca Helguera", "LUCCA", "LUCCA HELGUERA", grupo="Futures")
pl("Andrés Santamarta", "ANDRES SANTAMARTA", grupo="Futures")
pl("Barry", "BARRY", grupo="Futures")
pl("Bai Runkai", "BAI", grupo="Futures")
pl("Eugenia Zozaya", "EUGENIA ZOZAYA", grupo="Futures")
pl("Emma Ghibardato", "EMMA", grupo="Futures")
# ITF junior / nacionales
pl("Javier Ballester", "JAVI", "JAVI BALLESTER", grupo="Pablo")
pl("David Mas", "DAVID M", "DAVID MAS", grupo="Pablo/Salva")
pl("David Castillo", "DAVID C", "DAVID CASTILLO", grupo="Víctor M.")
pl("Ia Teporoca", "IA", grupo="Pablo")
pl("Noa Ribera", "NOA", "NOA RIBERA", grupo="Pablo")
pl("Bárbara Peñaranda", "BARBARA", grupo="Pablo")
pl("Daniela Martínez", "DANIELA", "DANIELA M", grupo="Pablo")
pl("Eric Badenes", "ERIC BADENES", grupo="Pablo/Víctor M.")
pl("Carla Guerrero", "CARLA GUERRERO", grupo="Pablo")
pl("Marcos Romero", "MARCOS", "MARCOS ROMERO", grupo="Víctor M.")
pl("Vicent Baixauli", "VICENT", "VICENT BAIXAULI", grupo="Víctor M.")
pl("Marta Crespo", "MARTA", "MARTA CRESPO", grupo="Víctor M.")
pl("Valeriia Bokova", "VALERIA", "VALERIA BOKOVA", grupo="Víctor M./Santi")
pl("Victoria Schneider", "VICTORIA", "VIKTORIA", "VICTORIA SCHNEIDER", grupo="Jorge I.")
pl("Enzo Helguera", "ENZO", grupo="Salva")
pl("Fermín Barcala", "FERMIN", "FERMIN BARCALA", grupo="Salva")
pl("Juan Esteban Inostroza", "JUAN I", grupo="Salva")
pl("Diego Vilches", "DIEGO V", grupo="Salva")
pl("Diego Inostroza", "DIEGO I", "DIEGO INOSTROZA", grupo="Álvaro")
pl("Cristian Borriello", "BORRIELO", "CHRISTIAN BORRIELLO", grupo="Mario")
pl("Guennouini Abdelaziz", "ABDE", grupo="Salva")
pl("Nacho Martínez", "NACHO", "NACHO MARTINEZ", grupo="Salva")
pl("Antonio Campoy", "ANTONIO", grupo="Salva")
pl("Tomás Lázaro", "TOMAS", "TOMAS LAZARO", grupo="Salva")
pl("Rodrigo López", "RODRI", "RODRI LOPEZ", "RODRIGO", "RORIGO", "RODRIGO LOPEZ", grupo="Salva")
pl("Omar Ally", "OMAR", grupo="Salva")
pl("Andy Liu", "ANDY", "ANDY LIU", grupo="Salva")
pl("Rohin", "ROHIN", grupo="Salva")
pl("Ciarán Kanani", "CIARAN", grupo="Salva")
pl("Ashmita Mitra", "ASMITHA", "ASHMITA", grupo="Salva")
pl("Anjali Vasanthan", "ANJALI", grupo="Salva")
pl("Ojas Malhotra", "OJAS", grupo="Pablo")
pl("Natalia Botea", "NATALIA", "NATALIA BOTEA", grupo="Santi")
pl("Ximo Mínguez", "XIMO", grupo="Emilio")
pl("Manuel Méndez (Manu)", "MANU", grupo="Víctor M.")
pl("Miguel Uriarte", "MIGUEL UR", grupo="")
pl("Yushuo Li", "YUSHUO LI", grupo="Álvaro")
pl("Dani Martins", "DANI MARTINS", grupo="Víctor M.")
pl("Nico Arias", "NICO", "NICO ARIAS", grupo="Salva (2025)")
# Santi
pl("Huaqi Li", "HUAQI", "HUAQI LI", "HUAQUI LI", grupo="Santi")
pl("Xu Guilin (Nik)", "NIK", "NICK", "NIK GUILIN", "XU GUILLIN", grupo="Santi")
pl("Eugenia Álvarez", "EUGENIA ALVAREZ", grupo="Santi")
pl("María Ruiz", "MARIA RUIZ", grupo="Santi")
pl("Aarish", "AARISH", grupo="Santi")
pl("Viraj", "VIRAJ", grupo="Santi")
pl("Yashvardhan Singh", "YASHVARDHAN", grupo="Santi")
pl("Elene Churruca", "ELENE", "ELENE CHURRUCA", grupo="Santi")
pl("Jinxuan Liao (Bonnie)", "BONNIE", "JINXUAN LIAO", grupo="Santi/Nacho C.")
pl("Ruth Moscardó", "RUTH", "RUTH MOSCARDO", grupo="Santi")
pl("Bernardo Peñaranda", "BERNARDO", "BERNARDO P", "BERNARDO PENARANDA", grupo="Santi")
pl("Daniel (sin apellido)", "DANIEL", grupo="Santi")
# Álvaro / Junior Program y escuela
pl("Amparo Gil", "AMPARO", "AMPARO GIL", "AMPA GIL", grupo="Álvaro")
pl("Jennie Zhang", "JENNIE", "JENNIE ZHANG", grupo="Álvaro")
pl("Ruohan Xu", "RUOHAN", "RUOHAN XU", grupo="Álvaro")
pl("Selena Yunshi Qi", "SELENA", "SELENA YUNSHI", "SELENA YUNSHI QI", "SELENA YUNSHI QI U11", "YUNSHI QI SELENA", grupo="Álvaro")
pl("Marc Marín", "MARC MARIN", grupo="Álvaro")
pl("Pau Marín", "PAU MARIN", grupo="Álvaro")
pl("Alex Pardo", "ALEX PARDO", grupo="Álvaro")
pl("Han Yu Lin", "HAN YU LIN", "HAN YU", "HAN A YU LIN", grupo="Álvaro")
pl("Eric López", "ERIC LOPEZ", "ERIC LOPEZ LOPEZ", "ERIC LOPEZ LOPEZ 12", grupo="Álvaro")
pl("Tal Or", "TAL OR", "TAL OR 13", grupo="Álvaro")
pl("Zunwen Wang (Kevin)", "ZUNWEN WANG", grupo="Álvaro")
pl("Marco Pérez Mingo", "MARCO PEREZ", "MARCO PEREZ MINGO", grupo="Álvaro")
pl("Octavio Alcaraz", "OCTAVIO ALCARAZ", "OCTAVIO ACARAZ", "OCTAVIO ALCARAZ 13", grupo="Álvaro")
pl("Xiyue Zhang (Luna)", "XIYUE ZHANG", "ZHANG XIYUE", "ZHANG XIYUE LUNA 12", "ZHANG XIYUE LUNA JUNIOR PROGRAM", grupo="Álvaro")
pl("Edgar Rouge", "EDGAR ROUGE", grupo="Álvaro")
pl("Sofía Fandos", "SOFIA FANDOS", "SOFIA F", grupo="Álvaro")
pl("Alejandro Mora", "ALEJANDRO MORA", grupo="Álvaro")
pl("Paula Mora", "PAULA MORA", grupo="Álvaro")
pl("Álvaro Alario", "ALVARO ALARIO", "ALVARO A", grupo="Álvaro")
pl("Martina Alario", "MARTINA ALARIO", "MARTINA A", grupo="Álvaro")
pl("Yuantian Gao", "GAO", "YUANTIA GAO", "YUANTIAN GAO", "YUANTIAN GAO MI 12", grupo="Álvaro")
pl("Hugo Montalbán", "HUGO", "HUGO MONTALBAN", "H MONTALBAN", grupo="Álvaro")
pl("Julián Finol", "JULIAN FINOL", grupo="Álvaro")
pl("Pablo Castelló", "PABLO CASTELLO FUSTER", grupo="Álvaro")
pl("Andrés Vivancos", "ANDRES VIVANCOS", grupo="Álvaro")
pl("Pablo Pérez Fajardo", "PABLO PEREZ", "PABLO FAJARDO", "PABLO PEREZ FAJARDO", grupo="Álvaro")
pl("Carla Chisvert", "CARLA CHISVERT", "CARLA CHISVRT", grupo="Álvaro")
pl("Miguel Vidal", "MIGUEL VIDAL", grupo="Álvaro")
pl("Víctor Peralta", "V PERALTA", "VICTOR P", "VICTOR PERALTA", grupo="Álvaro")
pl("Nico L. (sin apellido)", "NICO L", grupo="Álvaro")
pl("Arjun Malhotra", "ARJUN MALHOTRA", grupo="Álvaro")
pl("Álvaro Salvador", "ALVARO SALVADOR", "ALVARO SALVADOR GRANGEL", grupo="Álvaro")
pl("Valentina Salvador", "VALENTINA SALVADOR", grupo="Álvaro")
pl("Lucía Valero", "LUCIA VALERO", grupo="Álvaro")
pl("Lluís Domènech", "LLUIS DOMENECH", grupo="Álvaro")
pl("Lucas Reig", "LUCAS REIG", grupo="Álvaro")
pl("Izan Mullor", "IZAN MULLOR", grupo="Álvaro")
pl("Elena (sin apellido)", "ELENA", grupo="Álvaro")

ALIAS = {}
for name, d in P.items():
    for a in d["aliases"]:
        assert a not in ALIAS or ALIAS[a] == name, (a, name, ALIAS.get(a))
        ALIAS[a] = name

# Nombres sueltos que corresponden a más de una persona: candidatos + a quién se atribuye por defecto según la hoja
AMBIG = {
    "DIEGO": dict(cands=["Diego Vilches", "Diego Inostroza"],
                  default={"ALVARO": "Diego Inostroza", "*": "Diego Vilches"}),
    "DAVID": dict(cands=["David Mas", "David Castillo"],
                  default={"GRUPO PABLO": "David Mas"}),
    "ERIC": dict(cands=["Eric Badenes", "Eric López"],
                 default={"ALVARO": "Eric López", "*": "Eric Badenes"}),
    "CARLA": dict(cands=["Carla Guerrero", "Carla Chisvert"],
                  default={"ALVARO": "Carla Chisvert", "*": "Carla Guerrero"}),
    "EUGENIA": dict(cands=["Eugenia Álvarez", "Eugenia Zozaya"], default={"*": "Eugenia Álvarez"}),
    "MARIA": dict(cands=["María Ruiz", "María Andrienko"], default={"*": "María Ruiz"}),
    "MIGUEL": dict(cands=["Miguel Uriarte", "Miguel Vidal"],
                   default={"ALVARO": "Miguel Vidal", "*": "Miguel Uriarte"}),
    "JUAN": dict(cands=["Juan Esteban Inostroza"], default={"*": "Juan Esteban Inostroza"}),
    "MARC": dict(cands=["Marc Martín Roca", "Marc Marín"], default={"*": "Marc Martín Roca"}),
}
# Correcciones por fila concreta, cuando el contexto lo deja claro (hoja, fila, alias) -> nombre
ROW_FIX = {
    # M15/W15 Getxo y ITF Béjar: convocatorias del grupo Futures de Javi G. (van con Emma) → Eugenia Zozaya
    ("DISTRIBUCION CALENDARIO TODO", 175, "EUGENIA"): "Eugenia Zozaya",
    ("DISTRIBUCION CALENDARIO TODO", 194, "EUGENIA"): "Eugenia Zozaya",
}

# Trozos que no son jugadores
NOT_PLAYER = re.compile(r"^(SE JUEGA|SUB \d+|CAMPEONA)", re.I)


def split_players(raw):
    """Parte una celda de jugadores en trozos. Devuelve [(texto, dudoso)]."""
    t = raw.replace("\n", " ")
    t = re.sub(r"\((\d+)\)\s*(?=[A-Za-zÁÉÍÓÚ])", r"(\1), ", t)  # «López(12)Octavio» → separa
    t = re.sub(r"\)\s*(?=[A-Z][a-z])", "), ", t)             # «(Luna junior program)Gao»
    t = t.replace("Pau y marc Marín Terol", "Pau Marin, Marc Marin")
    t = re.sub(r"Alejandro y paula Mora", "Alejandro Mora, Paula Mora", t, flags=re.I)
    t = re.sub(r"Alvaro y Martina Alario", "Alvaro Alario, Martina Alario", t, flags=re.I)
    t = re.sub(r"TOMAS\s+Eric", "TOMAS, Eric", t)
    t = re.sub(r"MIGUEL$", "MIGUEL", t)
    out = []
    for p in re.split(r"\s*,\s*|\s+-\s*|\s*-\s+|/|\s*-(?=[A-ZÁÉÍÓÚ])|(?<=[A-Za-zÁÉÍÓÚ.])-\s*", t):
        p = p.strip(" .")
        if not p or NOT_PLAYER.match(p):
            continue
        doubt = "?" in p
        out.append((p.replace("?", "").strip(" ."), doubt))
    return out


def resolve_player(tok, sheet, row):
    """→ (nombre, estado) con estado en {'ok','inferido','ambiguo','desconocido'} y lista de candidatos."""
    f = fold(tok)
    f = re.sub(r"\s+\d+$", "", f) if f not in ALIAS else f
    if (sheet, row, f) in ROW_FIX:
        return ROW_FIX[(sheet, row, f)], "inferido", []
    if f in ALIAS:
        return ALIAS[f], "ok", []
    if f in AMBIG:
        a = AMBIG[f]
        d = a["default"].get(sheet, a["default"].get("*"))
        if not d:
            return f"{tok.strip().title()} (¿{' o '.join(c.split()[-1] for c in a['cands'])}?)", "ambiguo", a["cands"]
        return d, "inferido", a["cands"]
    return tok.strip().title(), "desconocido", []


# ------------------------------------------------------------------ coaches
SIN = "Sin acompañante"
COACH_MAP = {
    "SALVA": ["Salva Barcala"], "RICARDO": ["Ricardo"], "PABLO": ["Pablo Gil"], "MARIO": ["Mario Muniesa"],
    "SANTI": ["Santi Panzarasa"], "VICTOR M": ["Víctor M."], "VICTOR M Y SANTI P": ["Víctor M.", "Santi Panzarasa"],
    "PABLO NACHO": ["Pablo Gil", "Nacho Calvo"], "ALVARO M": ["Álvaro Mantoan"], "ALVARO MANTUOAN": ["Álvaro Mantoan"],
    "ALVARO": ["Álvaro Mantoan"], "VIRTOR R": ["Víctor Redondo"], "VICTOR R": ["Víctor Redondo"],
    "VICTOR": ["Víctor Redondo"], "VICTOR MARCOS": ["Víctor Redondo", "Marcos E."], "PATO": ["Patricio Rodríguez"],
    "PATRICIO": ["Patricio Rodríguez"], "JAVI": ["Javi Giménez"], "JAVI G": ["Javi Giménez"],
    "SANTI ALVARO": ["Santi Panzarasa", "Álvaro Mantoan"], "SANTI SALVA": ["Santi Panzarasa", "Salva Barcala"],
    "NACHO": ["Nacho Calvo"], "NACHO C": ["Nacho Calvo"], "NACHO CALVO": ["Nacho Calvo"], "IVAN": ["Iván"],
    "SERGIO": ["Sergio G."], "SERGIO G": ["Sergio G."], "BLAS": ["Blas Gallego"], "EMILIO": ["Emilio Sorio"],
    "EMILIO S": ["Emilio Sorio"], "EMILIO IVAN": ["Emilio Sorio", "Iván"], "JAVI BLAS": ["Javi Giménez", "Blas Gallego"],
    "DANI G": ["Dani Gimeno"], "MARCOS E": ["Marcos E."], "IVAN G": ["Iván G."], "JORGE G": ["Jorge García"],
    "JORGE I": ["Jorge Ibáñez"], "JORGE IBANEZ": ["Jorge Ibáñez"], "SALVA RICARDO": ["Salva Barcala", "Ricardo"],
    "ANNA": ["Anna M."],
    "VA SOLO": [SIN], "VA SOLA": [SIN], "SOLO": [SIN], "SOLA": [SIN], "SOLAS": [SIN], "VAN SOLOS": [SIN],
    "SIN ACOMPANAMIENTO": [SIN], "S A": ["Sin asignar (S/A)"],
    "SI": ["Sí, con coach (sin nombre)"], "NO": ["No va coach"], "": [], "VER": ["Por decidir"],
}


def resolve_coach(raw, torneo="", players=()):
    f = fold(raw)
    if f.startswith("SERGIO JORGE"):
        return ["Sergio G.", "Jorge García"], "inferido"
    if f in ("", "?"):
        return ([] if f == "" else ["Por decidir"]), "ok"
    if f == "JORGE":
        t = fold(torneo)
        if "Victoria Schneider" in players or "RAFA NADAL" in t or "SABADELL" in t:
            return ["Jorge Ibáñez"], "inferido"
        if "Elina Avanesian" in players or re.search(r"WTA|QUALY|US OPEN", t):
            return ["Jorge García"], "inferido"
        return ["Jorge (¿García o Ibáñez?)"], "ambiguo"
    if f in COACH_MAP:
        return COACH_MAP[f], "ok"
    return [raw.strip()], "desconocido"
