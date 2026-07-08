const divLabel = (o) => o.nombre || `División ${o.nivel}`;

export const DIAS_LABELS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
const DIA_OPTS = DIAS_LABELS.map((label, value) => ({ value, label }));
const ESTADO_OPTS = [
  { value: "DISPONIBLE", label: "Disponible" },
  { value: "AUSENCIA_JUGADOR", label: "Ausencia jugador" },
  { value: "CALENTAMIENTO", label: "Calentamiento" },
  { value: "EN_TORNEO", label: "En torneo" },
  { value: "CLIMATOLOGIA", label: "Climatología" },
  { value: "AUSENCIA_COACH", label: "Ausencia coach" },
];
const SUBTIPO_OPTS = [
  { value: "LESION", label: "Lesión" },
  { value: "ENFERMEDAD", label: "Baja por enfermedad" },
  { value: "ESTUDIOS", label: "Estudios" },
  { value: "PRUEBA_MEDICA", label: "Prueba médica" },
  { value: "VACACIONES", label: "Vacaciones" },
  { value: "MILONGA", label: "Milonga" },
];
const AMBITO_OPTS = [
  { value: "DIA", label: "Todo el día" },
  { value: "MANANA", label: "Toda la mañana" },
  { value: "TARDE", label: "Toda la tarde" },
  { value: "M1", label: "Turno M1" },
  { value: "M2", label: "Turno M2" },
  { value: "T1", label: "Turno T1" },
  { value: "T2", label: "Turno T2" },
];

export const RESOURCES = {
  jugadores: {
    endpoint: "jugadores",
    title: "Jugadores",
    singular: "jugador",
    search: true,
    columns: [
      { key: "nombre", label: "Nombre" },
      { key: "edad", label: "Edad" },
      { key: "es_menor", label: "Menor", type: "bool" },
      { key: "division_nivel", label: "Div", render: (v) => (v ? `D${v}` : "—") },
      { key: "entrenador_nombre", label: "Responsable", render: (v) => v || "—" },
      { key: "consentimiento_rgpd", label: "RGPD", type: "bool" },
      { key: "activo", label: "Activo", type: "bool" },
    ],
    fields: [
      { name: "nombre", label: "Nombre", type: "text", required: true },
      { name: "edad", label: "Edad", type: "number" },
      { name: "division", label: "División", type: "fk", endpoint: "divisiones", optionLabel: divLabel },
      { name: "entrenador_responsable", label: "Entrenador responsable", type: "fk", endpoint: "entrenadores", optionLabel: (o) => o.nombre },
      { name: "consentimiento_rgpd", label: "Consentimiento RGPD (datos de salud)", type: "bool" },
      { name: "foto_url", label: "Foto (URL en storage UE)", type: "text" },
      { name: "notas", label: "Notas", type: "text" },
      { name: "activo", label: "Activo", type: "bool", default: true },
    ],
  },

  entrenadores: {
    endpoint: "entrenadores",
    title: "Entrenadores",
    singular: "entrenador",
    search: true,
    columns: [
      { key: "nombre", label: "Nombre" },
      { key: "activo", label: "Activo", type: "bool" },
      { key: "disponible_semana", label: "Disp. semana", type: "bool" },
      { key: "disponibilidad_notas", label: "Notas disponibilidad" },
    ],
    fields: [
      { name: "nombre", label: "Nombre", type: "text", required: true },
      { name: "disponibilidad_notas", label: "Notas de disponibilidad", type: "text" },
      { name: "disponible_semana", label: "Disponible esta semana (fallback manual)", type: "bool", default: true },
      { name: "activo", label: "Activo", type: "bool", default: true },
    ],
  },

  divisiones: {
    endpoint: "divisiones",
    title: "Divisiones",
    singular: "división",
    columns: [
      { key: "nivel", label: "Nivel" },
      { key: "nombre", label: "Nombre" },
    ],
    fields: [
      { name: "nivel", label: "Nivel", type: "number", required: true },
      { name: "nombre", label: "Nombre", type: "text" },
    ],
  },

  sedes: {
    endpoint: "sedes",
    title: "Sedes",
    singular: "sede",
    columns: [
      { key: "nombre", label: "Nombre" },
      { key: "es_satelite", label: "Satélite", type: "bool" },
      { key: "densidad_default", label: "Densidad" },
      { key: "densidad_max", label: "Densidad máx" },
      { key: "activa", label: "Activa", type: "bool" },
    ],
    fields: [
      { name: "nombre", label: "Nombre", type: "text", required: true },
      { name: "es_satelite", label: "Sede satélite (desbordamiento)", type: "bool" },
      { name: "densidad_default", label: "Densidad por defecto (jug/pista)", type: "number", default: 2 },
      { name: "densidad_max", label: "Densidad máxima (Sta. Bárbara hasta 4)", type: "number", default: 2 },
      { name: "orden_desbordamiento", label: "Orden de desbordamiento", type: "number", default: 0 },
      { name: "activa", label: "Activa", type: "bool", default: true },
    ],
  },

  pistas: {
    endpoint: "pistas",
    title: "Pistas",
    singular: "pista",
    columns: [
      { key: "sede_nombre", label: "Sede" },
      { key: "numero", label: "Número" },
      { key: "activa", label: "Activa", type: "bool" },
    ],
    fields: [
      { name: "sede", label: "Sede", type: "fk", endpoint: "sedes", optionLabel: (o) => o.nombre, required: true },
      { name: "numero", label: "Número", type: "number", required: true },
      { name: "activa", label: "Activa", type: "bool", default: true },
    ],
  },

  rencillas: {
    endpoint: "rencillas",
    title: "Rencillas (vetos)",
    singular: "rencilla",
    columns: [
      { key: "jugador_a_nombre", label: "Jugador A" },
      { key: "jugador_b_nombre", label: "Jugador B" },
      { key: "activa", label: "Activa", type: "bool" },
      { key: "motivo", label: "Motivo" },
    ],
    fields: [
      { name: "jugador_a", label: "Jugador A", type: "fk", endpoint: "jugadores", optionLabel: (o) => o.nombre, required: true },
      { name: "jugador_b", label: "Jugador B", type: "fk", endpoint: "jugadores", optionLabel: (o) => o.nombre, required: true },
      { name: "motivo", label: "Motivo", type: "text" },
      { name: "activa", label: "Activa", type: "bool", default: true },
    ],
  },

  contratos: {
    endpoint: "contratos",
    title: "Contratos de patrocinio",
    singular: "contrato",
    columns: [
      { key: "jugador_nombre", label: "Jugador" },
      { key: "entrenador_nombre", label: "Entrenador" },
      { key: "activo", label: "Activo", type: "bool" },
    ],
    fields: [
      { name: "jugador", label: "Jugador", type: "fk", endpoint: "jugadores", optionLabel: (o) => o.nombre, required: true },
      { name: "entrenador", label: "Entrenador", type: "fk", endpoint: "entrenadores", optionLabel: (o) => o.nombre, required: true },
      { name: "activo", label: "Activo", type: "bool", default: true },
    ],
  },

  disponibilidades: {
    endpoint: "disponibilidades",
    title: "Ausencias y estados",
    singular: "registro",
    help:
      "Aquí marcas las faltas y estados que IMPACTAN el cuadrante: lesión, " +
      "enfermedad, torneo, climatología, vacaciones, etc. Elige la temporalidad " +
      "(todo el día, toda la mañana, toda la tarde o un turno). Tras registrarlas, " +
      "ve al Cuadrante y pulsa «Generar semana» (o «Regenerar tarde») para aplicarlas.",
    columns: [
      { key: "jugador_nombre", label: "Jugador" },
      { key: "dia", label: "Día", render: (v) => DIAS_LABELS[v] },
      { key: "ambito_display", label: "Temporalidad" },
      { key: "estado_display", label: "Estado" },
      { key: "subtipo_display", label: "Motivo", render: (v) => v || "—" },
      { key: "nota", label: "Nota" },
    ],
    fields: [
      { name: "semana", label: "Semana", type: "fk", endpoint: "semanas", optionLabel: (o) => o.fecha_inicio, required: true },
      { name: "jugador", label: "Jugador", type: "fk", endpoint: "jugadores", optionLabel: (o) => o.nombre, required: true },
      { name: "dia", label: "Día", type: "select", numeric: true, options: DIA_OPTS, required: true },
      { name: "ambito", label: "Temporalidad", type: "select", options: AMBITO_OPTS, required: true },
      { name: "estado", label: "Estado", type: "select", options: ESTADO_OPTS, required: true },
      { name: "subtipo", label: "Motivo (si es ausencia de jugador)", type: "select", options: SUBTIPO_OPTS },
      { name: "nota", label: "Nota", type: "text" },
    ],
  },
};
