import "./globals.css";

export const metadata = {
  title: "G Tenis · Cuadrante",
  description: "Cuadrante de la academia de alto rendimiento",
};

export default function RootLayout({ children }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
