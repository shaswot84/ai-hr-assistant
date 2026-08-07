export function statusClass(status) {
  const s = String(status || "").toUpperCase();
  if (s === "INDEXED") return "badge ok";
  if (s === "FAILED") return "badge err";
  if (s === "PENDING" || s === "PROCESSING") return "badge busy";
  return "badge";
}

export function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function shortId(uuid) {
  return uuid ? uuid.slice(0, 8) : "—";
}
