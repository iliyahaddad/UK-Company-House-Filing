/* Small helpers shared by every page: fetch wrapper, safe DOM text, escaping. */
async function apiCall(url, options) {
  const opts = Object.assign({ headers: { "Content-Type": "application/json" } }, options || {});
  const res = await fetch(url, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok || !data || data.success === false) {
    const message = (data && data.error) || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return data;
}

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  for (const child of children || []) node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  return node;
}

function money(value) {
  const n = Number(value || 0);
  return n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function showNotice(container, kind, message) {
  container.innerHTML = "";
  container.appendChild(el("div", { class: `notice notice-${kind}` }, [message]));
}

function showErrors(container, err) {
  const items = err.message ? err.message.split("; ") : ["Something went wrong"];
  container.innerHTML = "";
  const box = el("div", { class: "notice notice-error" }, ["Could not complete this:"]);
  const list = el("ul", {}, items.map((line) => el("li", { text: line })));
  box.appendChild(list);
  container.appendChild(box);
}
