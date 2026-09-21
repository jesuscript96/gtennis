import { resource } from "./api";

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
// Con la hora delante: el entrenador piensa en «la de las diez y media», no
// en un código. Faltaba JP desde que entró el curso de septiembre.
const AMBITO_OPTS = [
  { value: "DIA", label: "Todo el día" },
  { value: "MANANA", label: "Toda la mañana" },
  { value: "TARDE", label: "Toda la tarde" },
  { value: "M1", label: "M1 · 8:30-10:00" },
  { value: "M2", label: "M2 · 10:30-12:30" },
  { value: "JP", label: "Junior Program · 12:30-14:30" },
  { value: "T1", label: "T1 · 14:15-15:30" },
  { value: "T2", label: "T2 · 15:30-17:30" },
];
const PRIORIDAD_OPTS = [
  { value: "ALTA", label: "Alta" },
  { value: "MEDIA", label: "Media" },
  { value: "BAJA", label: "Baja" },
];
const FEEDBACK_ESTADO_OPTS = [
  { value: "NUEVO", label: "Nuevo" },
  { value: "EN_PROGRESO", label: "En progreso" },
  { value: "HECHO", label: "Hecho" },
  { value: "DESCARTADO", label: "Descartado" },
];
// Etiqueta de turno con la hora delante: se piensa en «la de las diez y
// media», no en un código.
const turnoLabel = (t) => `${t.codigo} · ${String(t.hora_inicio).slice(0, 5)}`;
const esManana = (t) => ["M1", "M2"].includes(t.codigo);
const esTarde = (t) => ["T1", "T2"].includes(t.codigo);
const AYUDA_TURNO = "Vacío = cualquiera de las dos (el motor elige, y solo una al día).";

const fmtFecha = (v) => {
  if (!v) return "—";
  try { return new Date(v).toLocaleDateString("es-ES"); } catch { return v; }
};

export const RESOURCES = {
  jugadores: {
    endpoint: "jugadores",
    title: "Jugadores",
    singular: "jugador",
    search: true,
    numbered: true,
    filters: [
      { name: "escuela", label: "Escuela", type: "fk", endpoint: "escuelas", optionLabel: (o) => o.nombre, todas: "Todas las escuelas", extra: [{ value: "sin", label: "Sin escuela" }] },
      { name: "todos", label: "Ver también los dados de baja", type: "bool", value: "1" },
    ],
    columns: [
      { key: "codigo_cliente", label: "Cód.", render: (v) => v ?? "—" },
      { key: "nombre", label: "Nombre" },
      // La edad sale de la fecha de nacimiento; se enseñan las dos porque
      // todavía hay alumnos antiguos de los que solo consta el número.
      { key: "edad", label: "Edad", render: (v, row) => (row.fecha_nacimiento ? `${v ?? "—"} · ${fmtFecha(row.fecha_nacimiento)}` : v ?? "—") },
      { key: "es_menor", label: "Menor", type: "bool" },
      { key: "escuela_nombre", label: "Escuela", render: (v) => v || "—" },
      { key: "division_nivel", label: "Div", render: (v) => (v ? `D${v}` : "—") },
      { key: "entrenador_nombre", label: "Responsable", render: (v) => v || "—" },
      { key: "fecha_alta", label: "Alta", render: (v) => (v ? fmtFecha(v) : "—") },
      { key: "horario", label: "Días distintos", render: (v) => (v && v.length ? `${v.length}` : "—") },
      { key: "activo", label: "Activo", type: "bool" },
    ],
    fields: [
      { name: "nombre", label: "Nombre", type: "text", required: true },
      { name: "codigo_cliente", label: "Código de cliente (TPC/Drive)", type: "number" },
      { name: "escuela", label: "Escuela", type: "fk", endpoint: "escuelas", optionLabel: (o) => o.nombre, help: "Alto Rendimiento, Junior Program o Escuela. Se puede cambiar en cualquier momento." },
      // La edad se calcula sola a partir de la fecha; no se teclea.
      { name: "fecha_nacimiento", label: "Fecha de nacimiento", type: "date", help: "La edad se calcula sola." },
      { name: "sexo", label: "Chico o chica", type: "select", options: [
        { value: "CHICO", label: "Chico" },
        { value: "CHICA", label: "Chica" },
      ], help: "Un chico no comparte pista con una chica de división más baja. «—» = sin declarar, no se le aplica la regla." },
      { name: "division", label: "División", type: "fk", endpoint: "divisiones", optionLabel: divLabel },
      { name: "entrenador_responsable", label: "Entrenador responsable (principal)", type: "fk", endpoint: "entrenadores", optionLabel: (o) => o.nombre },
      { name: "turno_manana", label: "Entrena por la mañana en", type: "fk", endpoint: "turnos", optionLabel: turnoLabel, filtra: esManana, help: AYUDA_TURNO },
      { name: "turno_tarde", label: "Entrena por la tarde en", type: "fk", endpoint: "turnos", optionLabel: turnoLabel, filtra: esTarde, help: AYUDA_TURNO },
      { name: "vecindad", label: "Con qué divisiones entrena", type: "select", options: [
        { value: "CLUB", label: "La del club (la horquilla general)" },
        { value: "SOLO", label: "Solo su división" },
        { value: "ARRIBA", label: "Su división y la de encima (D−1)" },
        { value: "ABAJO", label: "Su división y la de debajo (D+1)" },
        { value: "AMBAS", label: "Su división y las dos vecinas (±1)" },
      ], help: "Regla dura: nunca se rompe. Sirve para el alumno que solo entrena con su nivel o con el de encima. La D1 es la más alta." },
      // La D1 es la división más alta: «hacia arriba» es con la de número menor.
      { name: "pareja_division", label: "Se empareja preferentemente", type: "select", options: [
        { value: "ARRIBA", label: "Hacia arriba · con la división mejor (D−1)" },
        { value: "ABAJO", label: "Hacia abajo · con la división de debajo (D+1)" },
      ], help: "Siempre dentro de ±1 división. «—» = le da igual. La D1 es la más alta." },
      { name: "fecha_alta", label: "Fecha de alta", type: "date", help: "El día que empieza a entrenar. Hasta esa fecha no entra en los entrenamientos. Vacío = desde siempre." },
      { name: "fecha_baja", label: "Fecha de baja", type: "date", help: "Último día que entrena. Vacío = sigue en activo." },
      { name: "consentimiento_rgpd", label: "Consentimiento RGPD (datos de salud)", type: "bool" },
      { name: "foto_url", label: "Foto (URL en storage UE)", type: "text" },
      { name: "notas", label: "Notas", type: "text" },
      { name: "activo", label: "Activo", type: "bool", default: true },
    ],
    rowActions: [
      {
        label: "Entrenadores",
        onClick: (row) => {
          window.location.href = `/jugador-responsables?jugador=${row.id}&nombre=${encodeURIComponent(row.nombre)}`;
        },
      },
      {
        // Las dos franjas fijas están en la ficha; aquí se ven los días que se
        // salen de lo habitual, que necesitan rejilla y no caben en el formulario.
        label: "Turnos",
        onClick: (row) => {
          window.location.href = `/jugador-turnos?jugador=${row.id}`;
        },
      },
      {
        // Ojo: esto NO cambia la escuela, solo avisa a dirección. Cambiarla se
        // hace en Editar. El botón se llamaba "Movimiento" y se confundía con
        // el cambio de verdad.
        label: "Avisar",
        onClick: async (row) => {
          const escuela = window.prompt(
            `¿En qué escuela o grupo has visto a ${row.nombre}?\n\n` +
            "Esto solo avisa a dirección; NO le cambia la escuela. Para " +
            "cambiársela, usa Editar."
          );
          if (escuela === null) return;
          const nota = window.prompt("Nota (opcional):") || "";
          try {
            const r = await resource("jugadores").action(row.id, "reportar_movimiento", { escuela_observada: escuela, nota });
            window.alert(`Aviso enviado a dirección (${r.avisos_creados} aviso/s). La escuela no ha cambiado.`);
          } catch (e) {
            window.alert(String(e.message || e));
          }
        },
      },
    ],
  },

  entrenadores: {
    endpoint: "entrenadores",
    title: "Entrenadores",
    singular: "entrenador",
    search: true,
    columns: [
      { key: "nombre", label: "Nombre" },
      { key: "turnos_display", label: "Franjas" },
      { key: "activo", label: "Activo", type: "bool" },
      { key: "disponible_semana", label: "Disp. semana", type: "bool" },
    ],
    fields: [
      { name: "nombre", label: "Nombre", type: "text", required: true },
      { name: "turno_manana", label: "Da clase por la mañana en", type: "fk", endpoint: "turnos", optionLabel: turnoLabel, filtra: esManana, help: "Vacío = cualquiera: entra siempre que haya jugadores suyos disponibles." },
      { name: "turno_tarde", label: "Da clase por la tarde en", type: "fk", endpoint: "turnos", optionLabel: turnoLabel, filtra: esTarde, help: "Vacío = cualquiera: entra siempre que haya jugadores suyos disponibles." },
      { name: "disponibilidad_notas", label: "Notas de disponibilidad", type: "text" },
      { name: "disponible_semana", label: "Disponible esta semana (fallback manual)", type: "bool", default: true },
      { name: "activo", label: "Activo", type: "bool", default: true },
    ],
  },

  responsables: {
    endpoint: "responsables",
    title: "Responsables de jugador",
    singular: "responsable",
    help: "Con quién entrena cada jugador y en qué proporción: prioridad 1 = principal, 2 = secundario (mínimo 10%). Mejor desde Jugadores → «Entrenadores», que comprueba que sumen 100. Al añadir o quitar aquí se reparte solo: los secundarios al 10% y el principal, lo que queda.",
    columns: [
      { key: "jugador_nombre", label: "Jugador" },
      { key: "entrenador_nombre", label: "Entrenador" },
      { key: "prioridad", label: "Prioridad" },
      { key: "porcentaje_objetivo", label: "% objetivo", render: (v) => (v ? `${v}%` : "—") },
      { key: "activo", label: "Activo", type: "bool" },
    ],
    fields: [
      { name: "jugador", label: "Jugador", type: "fk", endpoint: "jugadores", optionLabel: (o) => o.nombre, required: true },
      { name: "entrenador", label: "Entrenador", type: "fk", endpoint: "entrenadores", optionLabel: (o) => o.nombre, required: true },
      { name: "prioridad", label: "Prioridad (1 = principal)", type: "number", default: 1 },
      { name: "porcentaje_objetivo", label: "% (se calcula solo; edítalo para forzar)", type: "number", default: 0 },
      { name: "activo", label: "Activo", type: "bool", default: true },
    ],
  },

  vacaciones: {
    endpoint: "vacaciones",
    title: "Vacaciones de entrenadores",
    singular: "periodo de vacaciones",
    help: "Periodos de vacaciones o baja de los entrenadores. El motor no los asigna en esas fechas.",
    columns: [
      { key: "entrenador_nombre", label: "Entrenador" },
      { key: "fecha_inicio", label: "Desde" },
      { key: "fecha_fin", label: "Hasta" },
      { key: "motivo", label: "Motivo", render: (v) => v || "—" },
    ],
    fields: [
      { name: "entrenador", label: "Entrenador", type: "fk", endpoint: "entrenadores", optionLabel: (o) => o.nombre, required: true },
      { name: "fecha_inicio", label: "Desde", type: "date", required: true },
      { name: "fecha_fin", label: "Hasta", type: "date", required: true },
      { name: "motivo", label: "Motivo", type: "text" },
    ],
  },

  disponibilidad_entrenador: {
    endpoint: "disponibilidades-entrenador",
    title: "Disponibilidad de entrenadores",
    singular: "registro",
    help: "Marca torneos y franjas horarias en las que un entrenador puede o no entrenar (ej. de torneo por la tarde pero disponible por la mañana). Sin fila = disponible todo el día.",
    columns: [
      { key: "entrenador_nombre", label: "Entrenador" },
      { key: "dia", label: "Día", render: (v) => DIAS_LABELS[v] },
      { key: "estado_display", label: "Estado" },
      { key: "hora_desde", label: "Desde", render: (v) => (v ? v.slice(0, 5) : "—") },
      { key: "hora_hasta", label: "Hasta", render: (v) => (v ? v.slice(0, 5) : "—") },
      { key: "nota", label: "Nota" },
    ],
    fields: [
      { name: "semana", label: "Semana", type: "fk", endpoint: "semanas", optionLabel: (o) => o.fecha_inicio, required: true },
      { name: "entrenador", label: "Entrenador", type: "fk", endpoint: "entrenadores", optionLabel: (o) => o.nombre, required: true },
      { name: "dia", label: "Día", type: "select", numeric: true, options: DIA_OPTS, required: true },
      { name: "estado", label: "Estado", type: "select", options: [{ value: "DISPONIBLE", label: "Disponible" }, { value: "TORNEO", label: "En torneo (parcial)" }, { value: "AUSENTE", label: "No disponible" }], required: true, default: "DISPONIBLE" },
      { name: "hora_desde", label: "Disponible desde (opcional)", type: "time" },
      { name: "hora_hasta", label: "Disponible hasta (opcional)", type: "time" },
      { name: "nota", label: "Nota", type: "text" },
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
      { key: "superficie", label: "Superficie", render: (v) => (v === "TIERRA" ? "Tierra batida" : v === "RESINA" ? "Resina" : "—") },
      { key: "activa", label: "Activa", type: "bool" },
    ],
    fields: [
      { name: "sede", label: "Sede", type: "fk", endpoint: "sedes", optionLabel: (o) => o.nombre, required: true },
      { name: "numero", label: "Número", type: "number", required: true },
      { name: "superficie", label: "Superficie", type: "select", options: [{ value: "TIERRA", label: "Tierra batida" }, { value: "RESINA", label: "Resina" }], default: "RESINA" },
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
      { key: "tipo", label: "Tipo", render: (v) => (v === "BLANDO" ? "Blando" : "Duro") },
      { key: "activo", label: "Activo", type: "bool" },
    ],
    fields: [
      { name: "jugador", label: "Jugador", type: "fk", endpoint: "jugadores", optionLabel: (o) => o.nombre, required: true },
      { name: "entrenador", label: "Entrenador", type: "fk", endpoint: "entrenadores", optionLabel: (o) => o.nombre, required: true },
      { name: "tipo", label: "Tipo de contrato", type: "select", required: true, default: "DURO", options: [
        { value: "DURO", label: "Duro · siempre con él" },
        { value: "BLANDO", label: "Blando · primero su grupo, y con él cuando pueda" },
      ], help: "Blando: el entrenador atiende antes a su grupo y va con este jugador solo si no deja otra pista sin entrenador." },
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
      { name: "ambitos", label: "¿Qué se pierde? Puedes marcar varias franjas",
        type: "multiselect", options: AMBITO_OPTS, required: true, soloCrear: true,
        exclusivas: ["DIA", "MANANA", "TARDE"], default: ["DIA"] },
      { name: "ambito", label: "Temporalidad", type: "select", options: AMBITO_OPTS,
        required: true, soloEditar: true },
      { name: "estado", label: "Estado", type: "select", options: ESTADO_OPTS, required: true },
      { name: "subtipo", label: "Motivo (si es ausencia de jugador)", type: "select", options: SUBTIPO_OPTS },
      { name: "nota", label: "Nota", type: "text" },
    ],
  },

  mantenimiento: {
    endpoint: "mantenimiento",
    title: "Mantenimiento",
    singular: "tarea",
    search: true,
    help: "Tareas de mantenimiento del club. Al crear una, se genera un aviso in-app a dirección. (El aviso al móvil llegará cuando haya canal de notificación.)",
    columns: [
      { key: "titulo", label: "Tarea" },
      { key: "responsable", label: "Responsable", render: (v) => v || "—" },
      { key: "fecha_limite", label: "Límite", render: (v) => v || "—" },
      { key: "estado_display", label: "Estado" },
    ],
    fields: [
      { name: "titulo", label: "Tarea", type: "text", required: true },
      { name: "descripcion", label: "Descripción", type: "textarea" },
      { name: "responsable", label: "Responsable / personal", type: "text" },
      { name: "fecha_limite", label: "Fecha límite", type: "date" },
      { name: "estado", label: "Estado", type: "select", options: [{ value: "PENDIENTE", label: "Pendiente" }, { value: "EN_CURSO", label: "En curso" }, { value: "HECHA", label: "Hecha" }], default: "PENDIENTE" },
    ],
  },

  feedback: {
    endpoint: "feedback",
    title: "Feedback y peticiones",
    singular: "feedback",
    search: true,
    help:
      "Registra feedback y nuevas peticiones: quién lo pide, qué prioridad " +
      "merece (alta / media / baja) y qué se solicita. Se ordenan por prioridad.",
    columns: [
      { key: "prioridad_display", label: "Prioridad" },
      { key: "autor", label: "Solicita" },
      { key: "titulo", label: "Título", render: (v) => v || "—" },
      { key: "descripcion", label: "Petición", render: (v) => (v && v.length > 80 ? v.slice(0, 80) + "…" : v || "—") },
      { key: "estado_display", label: "Estado" },
      { key: "created_at", label: "Fecha", render: fmtFecha },
    ],
    fields: [
      { name: "autor", label: "Quién lo solicita", type: "text", required: true },
      { name: "prioridad", label: "Prioridad", type: "select", options: PRIORIDAD_OPTS, required: true, default: "MEDIA" },
      { name: "titulo", label: "Título (breve, opcional)", type: "text" },
      { name: "descripcion", label: "Qué se solicita", type: "textarea", required: true },
      { name: "estado", label: "Estado", type: "select", options: FEEDBACK_ESTADO_OPTS, default: "NUEVO" },
    ],
  },

  coaches: {
    endpoint: "coaches",
    title: "Coaches",
    singular: "coach",
    search: true,
    help:
      "Rol intermedio (#16): un coach ve a sus entrenadores y a todos los " +
      "jugadores de esos entrenadores. Asígnale aquí sus entrenadores. Para " +
      "darle acceso con usuario y contraseña, créalo desde el alta de usuario.",
    columns: [
      { key: "nombre", label: "Nombre" },
      { key: "usuario_username", label: "Usuario", render: (v) => v || "— (sin login)" },
      { key: "entrenadores_display", label: "Entrenadores a cargo" },
      { key: "activo", label: "Activo", type: "bool" },
    ],
    fields: [
      { name: "nombre", label: "Nombre", type: "text", required: true },
      { name: "entrenadores", label: "Entrenadores a cargo", type: "mfk", endpoint: "entrenadores", optionLabel: (o) => o.nombre, help: "El coach verá a todos los jugadores de estos entrenadores." },
      { name: "activo", label: "Activo", type: "bool", default: true },
    ],
  },

  preferencias_superficie: {
    endpoint: "preferencias-superficie",
    title: "Preferencias de superficie",
    singular: "preferencia",
    help:
      "Jugadores que deben entrenar en un tipo de pista (tierra o rápida), por " +
      "un periodo o de forma indefinida. Si es estricta, el motor nunca los " +
      "pone en otra superficie.",
    columns: [
      { key: "jugador_nombre", label: "Jugador" },
      { key: "superficie_display", label: "Superficie" },
      { key: "fecha_desde", label: "Desde", render: (v) => v || "Ya" },
      { key: "fecha_hasta", label: "Hasta", render: (v) => v || "Indefinido" },
      { key: "estricta", label: "Estricta", type: "bool" },
    ],
    fields: [
      { name: "jugador", label: "Jugador", type: "fk", endpoint: "jugadores", optionLabel: (o) => o.nombre, required: true },
      { name: "superficie", label: "Superficie", type: "select", options: [{ value: "TIERRA", label: "Tierra batida" }, { value: "RESINA", label: "Resina" }], required: true, default: "TIERRA" },
      { name: "fecha_desde", label: "Desde (vacío = ya)", type: "date" },
      { name: "fecha_hasta", label: "Hasta (vacío = indefinido)", type: "date" },
      { name: "estricta", label: "Estricta (el motor nunca usa otra superficie)", type: "bool", default: true },
    ],
  },

  escuelas: {
    endpoint: "escuelas",
    title: "Escuelas",
    singular: "escuela",
    help:
      "Escuelas/programas del club. Si fijas un «turno único», los jugadores de " +
      "esa escuela solo entrenan en ese turno (p. ej. Junior Program → M2). " +
      "«Solo Resort» evita que se ubiquen en clubs satélite.",
    columns: [
      { key: "nombre", label: "Nombre" },
      { key: "turno_unico_codigo", label: "Turno único", render: (v) => v || "Todos" },
      { key: "solo_central", label: "Solo Resort", type: "bool" },
      { key: "activa", label: "Activa", type: "bool" },
    ],
    fields: [
      { name: "nombre", label: "Nombre", type: "text", required: true },
      { name: "turno_unico", label: "Turno único (vacío = todos los turnos)", type: "fk", endpoint: "turnos", optionLabel: (o) => `${o.codigo} · ${(o.hora_inicio || "").slice(0, 5)}-${(o.hora_fin || "").slice(0, 5)}` },
      { name: "solo_central", label: "Solo Resort (sin clubs satélite)", type: "bool" },
      { name: "orden", label: "Orden", type: "number", default: 0 },
      { name: "activa", label: "Activa", type: "bool", default: true },
    ],
  },
};
