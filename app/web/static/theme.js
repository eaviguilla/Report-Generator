// Theme toggle. The initial value is set pre-paint by the inline script in _theme_boot.html.
(() => {
  const button = document.querySelector("#theme-toggle");
  if (!button) return;
  const label = () => {
    const dark = document.documentElement.dataset.theme === "dark";
    button.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    button.setAttribute("aria-pressed", String(dark));
  };
  label();
  button.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("vr-theme", next); } catch (error) { /* private mode */ }
    label();
  });
})();
