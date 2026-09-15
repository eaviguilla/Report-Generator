(() => {
  const diagnostics = window.VulnReportDiagnostics;
  const main = document.querySelector("main");
  main?.setAttribute("tabindex", "-1");
  document.querySelector(".skip-link")?.addEventListener("click", event => {
    event.preventDefault();
    history.replaceState(null, "", event.currentTarget.getAttribute("href"));
    main?.focus({preventScroll:true});
    main?.scrollIntoView({block:"start"});
  });
  const rows = document.querySelector("#report-rows");
  const legacyReports = document.querySelector("#legacy-reports");
  const status = document.querySelector("#manager-status");
  const importInput = document.querySelector("#import-report");
  const importCommand = document.querySelector("#import-command");
  const appSearch = document.querySelector("#app-search");
  let openAppFolders = new Set();
  const formatDate = value => new Intl.DateTimeFormat(undefined, {dateStyle:"medium", timeStyle:"short"}).format(new Date(value));
  const setStatus = value => { status.textContent = value; };
  const responseError = (response, operation, fallback) => diagnostics.fromResponse(response, operation, fallback);
  const showError = (error, operation, fallback) => {
    diagnostics.show(error, operation, {fallback});
    setStatus(fallback);
  };
  const groupReportsByFolder = reports => {
    const groups = new Map();
    reports.forEach(report => {
      const folder = report.app_folder || "Unassigned";
      if (!groups.has(folder)) groups.set(folder, []);
      groups.get(folder).push(report);
    });
    return [...groups.values()];
  };
  const setHeaderCount = (selector, total, noun) => {
    const chip = document.querySelector(selector);
    if (!chip) return;
    chip.replaceChildren(Object.assign(document.createElement("b"), {textContent: String(total)}), document.createTextNode(` ${noun}${total === 1 ? "" : "s"}`));
    chip.hidden = !total;
  };
  // Drawn rather than lettered, so four actions per row stop shouting in red and blue.
  const ACTION_PATHS = {
    rename: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    duplicate: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
    export: '<path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    delete: '<path d="M4 6h16"/><path d="M9 6V4h6v2"/><path d="M6 6l1 14h10l1-14"/>',
    save: '<path d="m5 13 4 4L19 7"/>',
  };
  const actionIcon = key => `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ACTION_PATHS[key]}</svg>`;
  const row = report => {
    const reportId = escapeHtml(report.report_id);
    const reportUrlId = encodeURIComponent(report.report_id);
    return `<article class="report-row"><a class="report-name" href="/reports/${reportUrlId}/setup"><b>${escapeHtml(report.app_name)}</b><small>${reportId}</small></a><time datetime="${escapeHtml(report.saved_at)}">${formatDate(report.saved_at)}</time><span class="report-findings">${report.finding_count}</span><div class="report-actions"><button type="button" data-rename="${reportId}" data-name="${escapeHtml(report.app_name)}" aria-label="Rename" title="Rename application">${actionIcon("rename")}</button><button type="button" data-duplicate="${reportId}" aria-label="Duplicate" title="Duplicate report">${actionIcon("duplicate")}</button><a href="/reports/${reportUrlId}/export" aria-label="Export" title="Export ZIP">${actionIcon("export")}</a><button class="report-delete" type="button" data-delete="${reportId}" aria-label="Delete" title="Delete report">${actionIcon("delete")}</button></div></article>`;
  };
  const load = async () => {
    const [response, legacyResponse] = await Promise.all([fetch("/reports"), fetch("/reports/legacy")]);
    if (!response.ok) throw await responseError(response, "list_reports", "Unable to load reports");
    if (!legacyResponse.ok) throw await responseError(legacyResponse, "list_legacy_reports", "Unable to load legacy reports");
    const [reports, legacy] = await Promise.all([response.json(), legacyResponse.json()]);
    const groups = groupReportsByFolder(reports).sort((left, right) => (left[0].app_folder || "Unassigned").localeCompare(right[0].app_folder || "Unassigned"));
    setHeaderCount("#draft-count", reports.length, "draft");
    setHeaderCount("#app-count", groups.length, "application");
    rows.innerHTML = groups.length ? groups.map(group => { const folder = group[0].app_folder || "Unassigned"; return `<details class="app-group" data-app-name="${escapeHtml(folder)}"${openAppFolders.has(folder) ? " open" : ""}><summary><span class="app-caret" aria-hidden="true"></span><span class="app-group-name">${escapeHtml(folder)}</span><span class="app-group-count">${group.length}</span></summary><div class="app-group-body"><div class="app-group-columns"><span>Report</span><span>Last saved</span><span>Findings</span><span aria-label="Actions"></span></div><div class="app-group-rows">${group.map(row).join("")}</div></div></details>`; }).join("") : '<div class="empty-reports">No reports yet.</div>';
    rows.querySelectorAll(".app-group").forEach(group => group.addEventListener("toggle", () => {
      if (group.open) openAppFolders.add(group.dataset.appName);
      else openAppFolders.delete(group.dataset.appName);
    }));
    rows.querySelectorAll("[data-delete]").forEach(button => button.onclick = async () => {
      if (!await window.vrDialog.confirm({title: "Delete this report?", message: "This also removes its evidence files.", confirmLabel: "Delete the report", cancelLabel: "Keep it", tone: "danger"})) return;
      try {
        const response = await fetch(`/reports/${button.dataset.delete}`, {method:"DELETE"});
        if (!response.ok) throw await responseError(response, "delete_report", "Unable to delete report");
        diagnostics.clear();
        await load();
        setStatus("Report deleted.");
      } catch (error) {
        showError(error, "delete_report", "Unable to delete report");
      }
    });
    legacyReports.innerHTML = legacy.length ? `<div class="legacy-heading">Legacy drafts</div>${legacy.map(report => `<article class="legacy-report"><span><b>${escapeHtml(report.report_id)}</b><small>${escapeHtml(report.reason)}</small></span>${report.repairable ? `<button type="button" data-repair="${escapeHtml(report.report_id)}">Repair duplicate IDs</button>` : ""}</article>`).join("")}` : "";
    legacyReports.querySelectorAll("[data-repair]").forEach(button => button.onclick = async () => {
      try {
        const response = await fetch(`/reports/${button.dataset.repair}/repair`, {method:"POST"});
        if (!response.ok) throw await responseError(response, "repair_report", "Unable to repair this legacy draft");
        diagnostics.clear();
        await load();
        setStatus("Legacy draft repaired.");
      } catch (error) {
        showError(error, "repair_report", "Unable to repair this legacy draft");
      }
    });
    rows.querySelectorAll("[data-rename]").forEach(button => button.onclick = async () => {
      const article = button.closest(".report-row");
      const currentName = article.querySelector(".report-name b");
      if (!button.dataset.editing) {
        const input = document.createElement("input");
        input.className = "report-rename-input";
        input.type = "text";
        input.value = button.dataset.name;
        input.setAttribute("aria-label", "Application name");
        input.onkeydown = event => {
          if (event.key === "Enter") button.click();
          if (event.key === "Escape") load();
        };
        currentName.replaceWith(input);
        button.dataset.editing = "true";
        // The accessible name lives on aria-label now, so the icon alone would keep announcing "Rename".
        button.setAttribute("aria-label", "Save");
        button.title = "Save application name";
        button.innerHTML = actionIcon("save");
        input.focus();
        input.select();
        return;
      }
      const appName = article.querySelector(".report-rename-input").value.trim();
      try {
        const response = await fetch(`/reports/${button.dataset.rename}/name`, {method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({app_name:appName})});
        if (!response.ok) throw await responseError(response, "rename_report", "Unable to rename report");
        diagnostics.clear();
        await load();
        setStatus("Report renamed.");
      } catch (error) {
        showError(error, "rename_report", "Unable to rename report");
      }
    });
    rows.querySelectorAll("[data-duplicate]").forEach(button => button.onclick = async () => {
      try {
        const response = await fetch(`/reports/${button.dataset.duplicate}/duplicate`, {method:"POST"});
        if (!response.ok) throw await responseError(response, "duplicate_report", "Unable to duplicate report");
        const {report_id: reportId} = await response.json();
        diagnostics.clear();
        location.href = `/reports/${reportId}/setup`;
      } catch (error) {
        showError(error, "duplicate_report", "Unable to duplicate report");
      }
    });
    filterApps();
  };
  const filterApps = () => {
    const query = appSearch.value.trim().toLowerCase();
    rows.querySelectorAll(".app-group").forEach(group => {
      const matches = group.dataset.appName.toLowerCase().includes(query);
      group.hidden = !matches;
      group.open = Boolean(query && matches);
    });
  };
  const escapeHtml = value => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  importInput.onchange = async () => {
    const file = importInput.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    setStatus("Importing...");
    try {
      const response = await fetch("/reports/import", {method:"POST", body:form});
      if (!response.ok) throw await responseError(response, "import_report", "Import failed");
      const {report_id: reportId} = await response.json();
      diagnostics.clear();
      location.href = `/reports/${reportId}/setup`;
    } catch (error) {
      showError(error, "import_report", "Select a valid VulnReport ZIP or JSON export, or a report DOCX");
    }
    finally { importInput.value = ""; }
  };
  importCommand.onclick = () => importInput.click();
  appSearch.oninput = filterApps;
  load().catch(error => showError(error, "load_report_manager", "Unable to load reports"));
})();