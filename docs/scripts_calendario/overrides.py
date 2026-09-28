"""Uniones y separaciones decididas a mano tras revisar el Excel (referencias «Hoja ColFila»)."""
SAME = [
    # «Open Banc Sabadell Valencia» es el Trofeo Conde de Godó de Valencia (Victoria, con Jorge I.)
    ["Maestra C33", "Jorge D8", "Jorge E8"],
    # «ITF FRANCIA» con Marcos Romero y Víctor M. = ITF J30 Compiègne (Francia) de esa semana
    ["Maestra C168", "Pablo C137"],
    # Babolat Cup en el CT Español = Babolat Cup Valencia
    ["Maestra C163", "Santi C107"],
    # «GANDIA» / «DENIA» con Javi G. en semana de Futures = M25 Gandía / M25 Dénia
    ["Maestra C188", "Pablo C156"], ["Maestra C196", "Pablo C164"],
    # Absoluto El Collao (Víctor M.) = Open de la Cerámica, El Collao (Álvaro)
    ["Víctor M. B19", "Álvaro B65"],
    # Campeonato de España Junior: Reus (Pablo) / Tarragona (Álvaro) / sin sede (Maestra)
    ["Maestra C210", "Pablo C177", "Álvaro B87"],
    # Open Santa Apolonia (Torrent) y la celda «Torrente» de Mateo Álvarez
    ["Pablo C216", "ATP/Chall./Futures R41"],
]
SPLIT = []
NAME = {}
CELL_TO_ROW_OFF = set()
