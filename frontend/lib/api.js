const BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";

export function getToken() {
  return typeof window !== "undefined" ? localStorage.getItem("gt_token") : null;
}
export function getUser() {
  try {
    return JSON.parse(localStorage.getItem("gt_user"));
  } catch {
    return null;
  }
}
function setAuth(data) {
  localStorage.setItem("gt_token", data.token);
  localStorage.setItem("gt_user", JSON.stringify(data));
}
export function logout() {
  localStorage.removeItem("gt_token");
  localStorage.removeItem("gt_user");
}

async function req(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const t = getToken();
  if (t) headers["Authorization"] = `Token ${t}`;
  const res = await fetch(`${BASE}${path}`, { ...opts, headers, cache: "no-store" });
  if (res.status === 401 && typeof window !== "undefined") {
    logout();
    if (!path.startsWith("/auth/")) window.location.href = "/login";
  }
  if (!res.ok) {
    let detail;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text();
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function login(username, password) {
  const data = await req("/auth/token/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  setAuth(data);
  return data;
}

function rows(data) {
  return data && data.results ? data.results : data || [];
}

export function resource(name) {
  return {
    list: async (q = "") => rows(await req(`/${name}/${q}`)),
    create: (body) => req(`/${name}/`, { method: "POST", body: JSON.stringify(body) }),
    update: (id, body) =>
      req(`/${name}/${id}/`, { method: "PATCH", body: JSON.stringify(body) }),
    remove: (id) => req(`/${name}/${id}/`, { method: "DELETE" }),
  };
}

export const getLatestSemana = async () => {
  const r = rows(await req("/semanas/?limit=1"));
  return r[0] || null;
};
export const getCuadrante = (id, dia) => req(`/semanas/${id}/cuadrante/?dia=${dia}`);
export const generarSemana = (id) =>
  req(`/semanas/${id}/generar/`, { method: "POST", body: "{}" });
export const regenerarTarde = (id, dia) =>
  req(`/semanas/${id}/regenerar_tarde/`, { method: "POST", body: JSON.stringify({ dia }) });
export const publicarSemana = (id) =>
  req(`/semanas/${id}/publicar/`, { method: "POST", body: "{}" });

export const getConfig = () => req("/configuracion/");
export const saveConfig = (body) =>
  req("/configuracion/", { method: "PATCH", body: JSON.stringify(body) });
