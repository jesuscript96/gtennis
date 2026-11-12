/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Pantallas que se juntaron con otra el 10/11/2026: un enlace o favorito
  // antiguo lleva a la nueva en vez de dar «página no encontrada». Las que aún
  // existen como página las redirige el menú (RUTAS_VIEJAS en lib/menu.js).
  async redirects() {
    return [
      { source: "/ausencias", destination: "/faltas", permanent: false },
      { source: "/ausencias-fechas", destination: "/faltas", permanent: false },
      { source: "/vacaciones", destination: "/mi-agenda", permanent: false },
      { source: "/disponibilidad-entrenador", destination: "/mi-agenda", permanent: false },
      { source: "/responsables", destination: "/jugadores", permanent: false },
      { source: "/semana", destination: "/cuadrante?vista=semana", permanent: false },
      { source: "/divisiones", destination: "/grupos?vista=division", permanent: false },
    ];
  },
};

export default nextConfig;
