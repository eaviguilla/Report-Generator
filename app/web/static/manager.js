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
  const row = report => {
    const reportId = escapeHtml(report.report_id);
    const reportUrlId = encodeURIComponent(report.report_id);
    return `<article class="report-row"><a class="report-name" href="/reports/${reportUrlId}/setup"><b>${escapeHtml(report.app_name)}</b><small>${reportId}</small></a><time datetime="${escapeHtml(report.saved_at)}">${formatDate(report.saved_at)}</time><span>${report.finding_count}</span><div class="report-actions"><button type="button" data-rename="${reportId}" data-name="${escapeHtml(report.app_name)}" title="Rename application">Rename</button><button type="button" data-duplicate="${reportId}" title="Duplicate report">Duplicate</button><a href="/reports/${reportUrlId}/export" title="Export ZIP">Export</a><button type="button" data-delete="${reportId}" title="Delete report">Delete</button></div></article>`;
  };
  const load = async () => {
    const [response, legacyResponse] = await Promise.all([fetch("/reports"), fetch("/reports/legacy")]);
    if (!response.ok) throw await responseError(response, "list_reports", "Unable to load reports");
    if (!legacyResponse.ok) throw await responseError(legacyResponse, "list_legacy_reports", "Unable to load legacy reports");
    const [reports, legacy] = await Promise.all([response.json(), legacyResponse.json()]);
    const groups = groupReportsByFolder(reports).sort((left, right) => (left[0].app_folder || "Unassigned").localeCompare(right[0].app_folder || "Unassigned"));
    rows.innerHTML = groups.length ? groups.map(group => { const folder = group[0].app_folder || "Unassigned"; return `<details class="app-group" data-app-name="${escapeHtml(folder)}"${openAppFolders.has(folder) ? " open" : ""}><summary><span class="app-group-name">${escapeHtml(folder)}</span><span>${group.length} report${group.length === 1 ? "" : "s"}</span></summary><div class="app-group-columns"><span>Report</span><span>Last saved</span><span>Findings</span><span aria-label="Actions"></span></div><div class="app-group-rows">${group.map(row).join("")}</div></details>`; }).join("") : '<div class="empty-reports">No reports yet.</div>';
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
        button.textContent = "Save";
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