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

    // The sentence is for the tester; the code is what finds this failure in the error log.
    const code = document.createElement("p");
    code.className = "diagnostic-code";
    const codeLabel = document.createElement("span");
    codeLabel.textContent = "Code";
    const codeValue = document.createElement("code");
    codeValue.textContent = [diagnostic.operation, diagnostic.status, diagnostic.code, diagnostic.reference].filter(Boolean).join(" / ");
    code.append(codeLabel, codeValue);

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

    panel.append(headingRow, message, code);
    if (actions.childElementCount) panel.append(actions);
    document.body.append(panel);
    requestAnimationFrame(() => panel.focus({preventScroll:true}));
    return normalized;
  };

  window.VulnReportDiagnostics = {clear, fromResponse, normalize, show};

  window.addEventListener("error", event => {
    const error = normalize(event.error || new Error(event.message || "Browser resource failed"), "client_runtime");
    show(error, "client_runtime", {title: "Browser error"});
  });

  window.addEventListener("unhandledrejection", event => {
    const error = normalize(event.reason instanceof Error ? event.reason : new Error(String(event.reason || "Unhandled promise rejection")), "unhandled_promise");
    show(error, "unhandled_promise", {title: "Browser error"});
  });
})();
