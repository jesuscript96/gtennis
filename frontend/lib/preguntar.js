"use client";

/**
 * Una pregunta con varias respuestas, en una ventana encima de la página
 * (window.confirm solo sabe decir sí o no). Devuelve el `valor` de la opción
 * elegida, o null si se cierra. No depende de React: se llama desde lib/api.
 */
export function preguntar({ titulo, texto = "", lista = [], opciones }) {
  return new Promise((resolver) => {
    const fondo = document.createElement("div");
    fondo.className = "pregunta-fondo";
    const caja = document.createElement("div");
    caja.className = "pregunta-caja";
    caja.setAttribute("role", "dialog");
    caja.setAttribute("aria-modal", "true");
    const h = document.createElement("h3");
    h.textContent = titulo;
    caja.appendChild(h);
    if (texto) {
      const p = document.createElement("p");
      p.textContent = texto;
      caja.appendChild(p);
    }
    if (lista.length) {
      const ul = document.createElement("ul");
      for (const linea of lista) {
        const li = document.createElement("li");
        li.textContent = linea;
        ul.appendChild(li);
      }
      caja.appendChild(ul);
    }
    const botones = document.createElement("div");
    botones.className = "pregunta-botones";
    const cerrar = (valor) => {
      document.removeEventListener("keydown", tecla);
      fondo.remove();
      resolver(valor);
    };
    const tecla = (e) => { if (e.key === "Escape") cerrar(null); };
    for (const o of opciones) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `btn${o.tipo ? " " + o.tipo : ""}`;
      b.textContent = o.texto;
      if (o.ayuda) b.title = o.ayuda;
      b.onclick = () => cerrar(o.valor);
      botones.appendChild(b);
    }
    caja.appendChild(botones);
    fondo.appendChild(caja);
    fondo.addEventListener("click", (e) => { if (e.target === fondo) cerrar(null); });
    document.addEventListener("keydown", tecla);
    document.body.appendChild(fondo);
    botones.querySelector("button")?.focus();
  });
}
