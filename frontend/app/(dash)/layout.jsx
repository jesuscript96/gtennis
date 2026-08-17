"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getToken } from "../../lib/api";
import { canVisit } from "../../lib/perms";
import Sidebar from "../../components/Sidebar";
import SettingsMenu from "../../components/SettingsMenu";

export default function DashLayout({ children }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ok, setOk] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    // Guard por rol: si la ruta exige más nivel del que tiene, al inicio.
    if (!canVisit(pathname)) {
      router.replace("/");
      return;
    }
    setOk(true);
  }, [router, pathname]);

  if (!ok) return null;

  return (
    <div className="shell">
      <Sidebar />
      <main className="content">
        <div className="topbar">
          <SettingsMenu align="right" />
        </div>
        {children}
      </main>
    </div>
  );
}
