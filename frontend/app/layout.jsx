import "./globals.css";

export const metadata = {
  title: "G Tenis · Cuadrante",
  description: "Cuadrante de la academia de alto rendimiento",
  manifest: "/manifest.webmanifest",
  applicationName: "GTennis",
  appleWebApp: {
    capable: true,
    title: "GTennis",
    statusBarStyle: "black-translucent",
  },
  icons: {
    icon: [
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
  formatDetection: { telephone: false },
  other: {
    // Refuerzo para iOS antiguos: lanza en modo app (pantalla completa).
    "apple-mobile-web-app-capable": "yes",
  },
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
  themeColor: "#c96442",
};

export default function RootLayout({ children }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
