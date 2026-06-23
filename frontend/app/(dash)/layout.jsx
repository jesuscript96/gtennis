"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "../../lib/api";
import Sidebar from "../../components/Sidebar";
import SettingsMenu from "../../components/SettingsMenu";

export default function DashLayout({ children }) {
  const router = useRouter();
  const [ok, setOk] = useState(false);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
    else setOk(true);
  }, [router]);

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
