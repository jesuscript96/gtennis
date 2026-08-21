"use client";

import { useEffect, useState } from "react";

// Devuelve true cuando el viewport es de tamaño móvil/tablet (drawer + táctil).
// Mismo breakpoint que el CSS del drawer (860px).
export function useIsMobile(maxWidth = 860) {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${maxWidth}px)`);
    const update = () => setIsMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [maxWidth]);

  return isMobile;
}
