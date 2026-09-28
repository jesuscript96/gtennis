"""Reconocer que dos textos distintos son el mismo torneo (dentro de una semana)."""
import re
from names import fold

# categoría: (patrón sobre el texto plegado, etiqueta)
CATS = [
    (r"\bDAVIS\b", "Copa Davis"),
    (r"\bUS OPEN\b|\bROLAND GARROS\b|\bWIMBLEDON\b|\bAUSTRALIAN OPEN\b|\bAO\b|\bGS\b|\bGSL\b", "Grand Slam"),
    (r"\bWTA\b", "WTA"),
    (r"\bATP\b|\bM1000\b|\bMONTE CARLO 1000\b|\bINDIAN WELLS\b|\bMIAMI\b|\bCINCIN+ATI\b|\bQUALY (INDIAN|MIAMI)", "ATP"),
    (r"\bCH\b|\bCHALLENGER\b|\bCHLLANGER\b", "Challenger"),
    (r"\bM\s?(15|25)\b|\bMS5 H\b", "ITF M"),
    (r"\bW\s?(15|35|50|75|100)\b", "ITF W"),
    (r"\bITF\b.*\bJ\s?\d|\bJ\s?(30|60|100|200|300|500)\b|\bJ3OO\b|\bJ6O\b|\bJGS\b|\bITF (FRANCIA|HOLANDA|BEJAR|LEIRIA|PORTO|GIRONA)\b|\bITF 300\b|\bPRE ?QUALY ITF\b|\bPREQUALY ITF\b|\bPRE QUALY J30\b|\bJM\b", "ITF Junior"),
    (r"\bTENNIS EUROPE\b", "Tennis Europe"),
    (r"\bMARCA\b|\bMARCAS\b", "MARCA"),
    (r"\bIBP\s?\d*\b", "IBP"),
    (r"\bMUTUA\b", "Mutua Madrid Open Sub-16"),
    (r"\bRAFA NADAL\b", "Rafa Nadal Tour"),
    (r"\bCHAMP?IONS? (CUP|BOWL)\b|\bCHAMPIONSCUP\b|\bCHAMPIOS CUP\b|\bCHAMPIONS\b", "Champions Cup/Bowl"),
    (r"\bFAUL?C?O?U?M?BRIDGE\b|\bFAULDCOMBRIDGE\b|\bFAULCOMBRIDGE\b|\bFALCOUMBRIDGE\b|\bFALCOMBRIDGE\b|\bCOPA FAULC", "Copa Faulcombridge"),
    (r"\bWARRIORS?\b|\bWARRRIOS\b|\bTTK\b", "TTK Warriors"),
    (r"\bYOUNG\b|\bYTT\b|\bAS YOUNG\b", "Young Tennis Tour"),
    (r"\bTECNIFIBRE\b|\bTECNIFBRE\b", "Circuito Tecnifibre"),
    (r"\bBABOLAT\b", "Babolat Cup"),
    (r"\bPROVINCIAL\b|\bCPV\b|\bCIRCUITO P\b|\bPRV\b|^DAVID FERRER$", "Circuito Provincial"),
    (r"\bTORNEO FEMENINO\b", "Torneo Femenino Generalitat"),
    (r"\bMORE ?(AND|&)? ?TEN+IS\b|\bMORETENNIS\b", "Circuito More&Tennis"),
    (r"\bDIPUTACION\b|\bALGETENIS\b", "Circuito Diputación"),
    (r"\bPRE ?QUALY\b|\bPREQUALI\b", "ITF Junior"),
    (r"\bMANUEL ALONSO\b", "Campeonato de España"),
    (r"\bVALENCIA TENNIS TOUR\b|\bVALENCIA TENIS TOUR\b", "Valencia Tennis Tour"),
    (r"\bCAMPEONATO (DE )?ESPANA\b|\bCAMP ESP\b|\bCAMPONATO DE ESPANA\b", "Campeonato de España"),
    (r"\bREGI?ONAL\b|\bCOMUNIDAD VALENCIANA\b", "Campeonato regional"),
    (r"\bFEMENINO GENERALITAT\b", "Torneo Femenino Generalitat"),
    (r"\bCAMPEONATO DE\b", "Campeonato autonómico/nacional"),
    (r"\bABSOLUT|\bABS\b|\bOPEN\b", "Absoluto / Open"),
    (r"\bMORE ?(AND|&)? ?TEN+IS\b|\bMORETENNIS\b", "Circuito More&Tennis"),
    (r"\bSPARTAN\b", "Spartan Tour"),
    (r"\bCIRCUITO G\b", "Circuito G"),
]

STOP = set("""ITF WTA ATP CH CHALLENGER CHALLENGE SLAM MARCA MARCAS BY WILSON IBP MUTUA SUB RAFA NADAL TOUR CHAMPIONS CHAMPION
CHAMPIOS CHAMIONS CUP BOWL COPA CIRCUITO FAULCOMBRIDGE FALCOUMBRIDGE FALCOMBRIDGE FAULDCOMBRIDGE WARRIORS WARRIOR WARRRIOS TTK
YOUNG TENNIS TENIS TT YTT AS TECNIFIBRE TECNIFBRE BABOLAT PROVINCIAL CPV FASE PRUEBA MASTER MASTERS TODAS LAS CATEGORIAS
CATEGORIA CATEGORIAS TODAS FIN DE SEMANA SEMANA FINDE FINES HARD DURA TIERRA CLAY INDOOR IH CL H C G QUICK ALBERO RAPIDA
OUTDOOR CHICOS CHICAS MASCULINO FEMENINO Y EL LA LOS DEL AL DE A EN Q QS MD J JM JGS GS GSL W M MS ESP EUR USD ITA FRA POR
GER CHI BRA ARG ESPANA PORTUGAL FRANCIA ITALIA MEXICO MEX EGIPTO TUNEZ TURQUIA MARRUECOS PREVIA PREV SABADO ENE FEB MAR ABR
MAY JUN JUL AGO SEP SEPT OCT NOV DIC ENERO FEBRERO MARZO ABRIL MAYO JUNIO JULIO AGOSTO SEPTIEMBRE OCTUBRE NOVIEMBRE
DICIEMBRE ALE ALEV ALEVIN INF INFANTIL CAD CADETE JUN JUNIOR BEN BENJAMIN ABSOLUTO ABSOLUTA ABSOLUT ABS OPEN NACIONAL
CAMPEONATO REGIONAL REGINAL COMUNIDAD VALENCIANA CT C T CLUB CD TENNIS TENIS TENNIS CENTER SPORT SPORTING DIPUTACION
TORNEO PRE QUALY PREQUALY QUALIFYING QUALIFY SINGLES START FINAL TUESDAY SATURDAY SUNDAY THURSDAY NUEVO VA SOLO OPC
SI NO GENERALITAT FEDE JUVENIL SPARTAN MORETENNIS MORE AND ENTRESEMANA SORTEO CIERRA HASTA S ESTAR LAS VEGAS2
TODO GRAN PREMIO CAMPONATO CAMP ESP""".split())

CITY_ALIASES = {
    "OPORTO": "PORTO", "BAYONE": "BAIONA", "BAYONA": "BAIONA", "SANXENSO": "SANXENXO", "SANSENXO": "SANXENXO",
    "BENCIARLO": "BENICARLO", "ISMALIA": "ISMAILIA", "COMPIAGNE": "COMPIEGNE", "GERONA": "GIRONA",
    "VALLDOREIX": "VALLDOREIX", "VALL": "VALLDOREIX", "OREIX": "VALLDOREIX", "PENACANADA": "PENACANADA",
    "BISQUERT": "BIXQUERT", "TERRASA": "TERRASSA", "XATIVA": "XATIVA", "CINCINATI": "CINCINNATI",
    "SETUBAL": "SETUBAL", "TELDE": "TELDE", "MONTERREY": "MONTERREY", "NUEVO": "MONTERREY", "LEON": "MONTERREY",
    "CARLET": "CARLET", "SABADELL": "SABADELL", "CAIRO": "CAIRO", "EQUELITE": "EQUELITE", "VILLENA": "VILLENA",
    "GTENN": "GTENNIS", "GTENNNIS": "GTENNIS", "VALENCIA": "VALENCIA", "VLC": "VALENCIA", "SZCEZCIN": "SZCZECIN",
    "CEUTA": "CEUTA", "ANTALYA": "ANTALYA", "TORRENTE": "TORRENT", "MELILLA": "MELILLA", "CATARROJAABSOLUTO": "CATARROJA",
    "JAEN": "ALCALA LA REAL", "BETERA": "BETERA", "CASTELLON": "CASTELLON", "NULES": "NULES", "EQUELITE": "ALICANTE", "FERRERO": "ALICANTE", "SALADAR": "SILLA", "SEVILLE": "SEVILLA", "TORRENTE": "TORRENT", "BARCELONA": "BARCELONA", "BCN": "BARCELONA",
    "GODO": "GODO", "CAIXA": "CAIXA", "JAVEA": "JAVEA", "ALMORADI": "ALMORADI",
}


def category(text, hint=None):
    f = fold(text)
    for pat, lab in CATS:
        if re.search(pat, f):
            return lab
    if hint:
        h = fold(hint)
        for pat, lab in CATS:
            if re.search(pat, h):
                return lab
        if "FUTURE" in h:
            return "ITF M"
        if "ITF" in h:
            return "ITF Junior"
    return "Otros"


def cities(text):
    f = fold(text)
    f = re.sub(r"\b\d+\b", " ", f)
    toks = [t for t in f.split() if t not in STOP and len(t) > 2 and not re.fullmatch(r"[A-Z]{0,2}\d+[A-Z]?|\d+[A-Z]{1,3}", t)]
    return {CITY_ALIASES.get(t, t) for t in toks}


def level(text):
    """nivel dentro de la categoría (J30, M25, 75…) para no fundir torneos distintos en la misma ciudad"""
    f = fold(text)
    m = re.search(r"\bJ\s?(30|60|100|200|300|500)\b|\bJ(3OO|6O)\b", f)
    if m:
        v = m.group(1) or m.group(2)
        return "J" + v.replace("O", "0")
    m = re.search(r"\b([MW])\s?(15|25|35|50)\b", f)
    if m:
        return m.group(1) + m.group(2)
    if re.search(r"CAMP?E?ONATO", f):
        m = re.search(r"\b(CADETE|ALEVIN|INFANTIL|JUNIOR)\b", f)
        if m:
            return m.group(1)
    return None
