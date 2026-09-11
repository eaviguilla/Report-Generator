(() => {
  const panelId = "app-diagnostics";

  const messageFromDetail = (detail, fallback) => {
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const messages = detail.map(item => item?.msg).filter(Boolean);
      if (messages.length) return messages.join("; ");
    }
    if (detail && typeof detail === "object") {
      const message = detail.message || detail.detail;
      if (message) {
        const issues = Array.isArray(detail.issues) ? detail.issues.filter(Boolean) : [];
        return issues.length ? `${message}: ${issues.join("; ")}` : String(message);
      }
    }
    return fallback;
  };

  const normalize = (error, operation, fallback = "Operation failed") => {
    const source = error instanceof Error ? error : new Error(String(error || fallback));
    const existing = source.diagnostic || {};
    source.diagnostic = {
      operation,
      status: source.status || existing.status || "Client",
      message: source.message || existing.message || fallback,
      function: existing.function || operation,
      method: existing.method || "Client",
      path: existing.path || location.pathname,
      timestamp: existing.timestamp || new Date().toISOString(),
      reference: existing.reference || `client-${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`,
      code: existing.code || source.name || "client_error",
      exception_type: existing.exception_type || source.name,
      log_file: existing.log_file,
      recoverable: existing.recoverable,
      latest_saved_at: existing.latest_saved_at,
      client_stack: existing.reference ? undefined : source.stack,
      ...existing,
    };
    return source;
  };

  const fromResponse = async (response, operation, fallback = "Request failed") => {
    const responseText = await response.text();
    let payload;
    try {
      payload = responseText ? JSON.parse(responseText) : {};
    } catch {
      payload = {};
    }
    const diagnostic = payload.error || {};
    const message = diagnostic.message || messageFromDetail(payload.detail, `${fallback} (${response.status})`);
    const error = new Error(message);
    error.status = response.status;
    error.detail = payload.detail;
    error.diagnostic = {
      operation,
      status: response.status,
      function: diagnostic.function || operation,
      method: diagnostic.method,
      path: diagnostic.path || new URL(response.url).pathname,
      timestamp: diagnostic.timestamp || new Date().toISOString(),
      reference: diagnostic.reference || response.headers.get("X-VulnReport-Error") || `http-${response.status}`,
      code: diagnostic.code || `http_${response.status}`,
      message,
      log_file: diagnostic.log_file,
      exception_type: diagnostic.exception_type,
      recoverable: diagnostic.recoverable,
      latest_saved_at: diagnostic.latest_saved_at,
    };
    return error;
  };

  const clear = () => document.getElementById(panelId)?.remove();

  const technicalText = diagnostic => {
    const entries = [
      ["Operation", diagnostic.operation],
      ["Server function", diagnostic.function],
      ["Status", diagnostic.status],
      ["Code", diagnostic.code],
      ["Method", diagnostic.method],
      ["Path", diagnostic.path],
      ["Time", diagnostic.timestamp],
      ["Reference", diagnostic.reference],
      ["Exception", diagnostic.exception_type],
      ["Client location", diagnostic.client_location],
      ["Server log", diagnostic.log_file],
    ].filter(([, value]) => value !== undefined && value !== null && value !== "");
    const lines = entries.map(([label, value]) => `${label}: ${value}`);
    if (diagnostic.client_stack) lines.push("", diagnostic.client_stack);
    return lines.join("\n");
  };

  const show = (error, operation, options = {}) => {
    clear();
    const normalized = normalize(error, operation, options.fallback);
    const diagnostic = normalized.diagnostic;
    const panel = document.createElement("section");
    panel.id = panelId;
    panel.className = `app-diagnostics ${options.kind || "error"}`;
    panel.dataset.operation = diagnostic.operation;
    panel.dataset.code = diagnostic.code;
    panel.setAttribute("role", "alert");
    panel.setAttribute("aria-live", "assertive");
    panel.tabIndex = -1;

    const headingRow = document.createElement("div");
    headingRow.className = "diagnostic-heading";
    const heading = document.createElement("h2");
    heading.textContent = options.title || (diagnostic.status === 409 ? "Save conflict" : "Operation failed");
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "diagnostic-dismiss";
    dismiss.textContent = "Dismiss";
    dismiss.addEventListener("click", clear);
    headingRow.append(heading, dismiss);

    const message = document.createElement("p");
    message.className = "diagnostic-message";
    message.textContent = diagnostic.message;

    const summary = document.createElement("dl");
    summary.className = "diagnostic-summary";
    [
      ["Operation", diagnostic.operation],
      ["Function", diagnostic.function],
      ["Status", diagnostic.status],
      ["Reference", diagnostic.reference],
    ].forEach(([label, value]) => {
      if (value === undefined || value === null || value === "") return;
      const term = document.createElement("dt");
      term.textContent = label;
      const description = document.createElement("dd");
      description.textContent = String(value);
      summary.append(term, description);
    });

    const details = document.createElement("details");
    details.className = "diagnostic-details";
    const detailsSummary = document.createElement("summary");
    detailsSummary.textContent = "Technical details";
    const pre = document.createElement("pre");
    pre.textContent = technicalText(diagnostic);
    details.append(detailsSummary, pre);

    const actions = document.createElement("div");
    actions.className = "diagnostic-actions";
    (options.actions || []).forEach(action => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = action.primary ? "primary" : "subtle";
      button.textContent = action.label;
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await action.run(normalized);
        } catch (actionError) {
          show(actionError, action.operation || operation, {title: "Recovery failed"});
        } finally {
          button.disabled = false;
        }
      });
      actions.append(button);
    });

    panel.append(headingRow, message, summary, details);
    if (actions.childElementCount) panel.append(actions);
    document.body.append(panel);
    requestAnimationFrame(() => panel.focus({preventScroll:true}));
    return normalized;
  };

  window.VulnReportDiagnostics = {clear, fromResponse, normalize, show};

  window.addEventListener("error", event => {
    const error = normalize(event.error || new Error(event.message || "Browser resource failed"), "client_runtime");
    error.diagnostic.client_location = [event.filename, event.lineno, event.colno].filter(Boolean).join(":");
    show(error, "client_runtime", {title: "Browser error"});
  });

  window.addEventListener("unhandledrejection", event => {
    const error = normalize(event.reason instanceof Error ? event.reason : new Error(String(event.reason || "Unhandled promise rejection")), "unhandled_promise");
    show(error, "unhandled_promise", {title: "Browser error"});
  });
})();

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
