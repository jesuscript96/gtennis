import { redirect } from "next/navigation";

// El Now vive ahora en Inicio ("/"). Mantenemos /ahora como redirección.
export default function AhoraRedirect() {
  redirect("/");
}
