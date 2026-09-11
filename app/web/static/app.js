(() => {
  const root = document.querySelector("main[data-report]");
  if (!root) return;
  const diagnostics = window.VulnReportDiagnostics;
  root.tabIndex = -1;
  document.querySelector(".skip-link")?.addEventListener("click", event => {
    event.preventDefault();
    history.replaceState(null, "", event.currentTarget.getAttribute("href"));
    root.focus({preventScroll:true});
    root.scrollIntoView({block:"start"});
  });
  const serverReport = JSON.parse(root.dataset.report);
  let report = serverReport;
  const reportId = report.report_id;
  const reportTypeLabels = {annual_pentest:"Annual Pentest", retest:"Retest", deployment_pentest:"Deployment Pentest", new_test:"New Test"};
  // The header names the engagement only once both halves are saved; a missing half falls back.
  const updateEngagementName = (saved = report) => {
    const heading = document.querySelector(".engagement-name");
    if (!heading) return;
    const appName = saved.engagement?.app_name?.trim();
    const testType = reportTypeLabels[saved.engagement?.report_type];
    heading.textContent = appName && testType ? `${appName} - ${testType}` : "Application Penetration Testing";
  };
  const localDraftPrefix = `vulnreport-pending:${reportId}`;
  const recoverySelectionKey = `vulnreport-recovery:${reportId}`;
  let recoveryStorageError = null;
  let tabId;
  try {
    tabId = sessionStorage.getItem("vulnreport-tab-id");
    if (!tabId) {
      tabId = crypto.randomUUID();
      sessionStorage.setItem("vulnreport-tab-id", tabId);
    }
  } catch (error) {
    recoveryStorageError = error;
    tabId = crypto.randomUUID();
  }
  const localDraftKey = `${localDraftPrefix}:${tabId}`;
  const historyKey = `vulnreport-history:${reportId}`;
  let recoveredDraft = false;
  let recoveryCandidate = null;
  let restoredDraftKey = null;
  try {
    const draftKeys = Array.from({length:localStorage.length}, (_, index) => localStorage.key(index))
      .filter(key => key === localDraftPrefix || key?.startsWith(`${localDraftPrefix}:`));
    const drafts = draftKeys.flatMap(key => {
      try {
        const cached = JSON.parse(localStorage.getItem(key));
        const envelope = cached?.report ? cached : {
          schemaVersion: 1,
          reportId,
          tabId: "legacy",
          baseSavedAt: cached?.saved_at,
          capturedAt: cached?.saved_at,
          editRevision: 0,
          report: cached,
        };
        if (envelope.reportId !== reportId || envelope.report?.report_id !== reportId) throw new Error("Draft does not match this report");
        return [{key, envelope}];
      } catch {
        localStorage.removeItem(key);
        return [];
      }
    }).sort((left, right) => (Date.parse(right.envelope.capturedAt) || 0) - (Date.parse(left.envelope.capturedAt) || 0));
    const selectedKey = sessionStorage.getItem(recoverySelectionKey);
    sessionStorage.removeItem(recoverySelectionKey);
    const selectedDraft = drafts.find(draft => draft.key === selectedKey);
    if (selectedDraft) {
      report = selectedDraft.envelope.report;
      recoveredDraft = true;
      restoredDraftKey = selectedDraft.key;
    } else {
      recoveryCandidate = drafts[0] || null;
    }
  } catch (error) {
    recoveryStorageError ||= error;
  }
  const clone = value => JSON.parse(JSON.stringify(value));
  const maxHistoryEntries = 20;
  let undoHistory = [];
  let redoHistory = [];
  try {
    ({undoHistory = [], redoHistory = []} = JSON.parse(sessionStorage.getItem(historyKey) || "{}"));
  } catch (error) {
    recoveryStorageError ||= error;
    try { sessionStorage.removeItem(historyKey); } catch (removeError) { recoveryStorageError ||= removeError; }
  }
  let previousReport = clone(report);
  let activeTextTransaction = null;
  const library = JSON.parse(root.dataset.library || "[]");
  const severity = ["critical", "high", "medium", "low", "informational"];
  const statuses = [["open_new", "Open (New)"], ["open_previously_discovered", "Open (Previously Discovered)"], ["resolved", "Resolved"]];
  const contentNames = {description:"Description", recommended_remediation:"Recommended Remediation", previous_proof_of_concept:"Previous Proof of Concept", proof_of_concept:"Proof of Concept", in_conclusion:"In Conclusion"};
  const allowed = {description:["paragraph","numbered_list","bulleted_list","image","table","note","code_block"], recommended_remediation:["paragraph","numbered_list","bulleted_list","image","table","note","code_block"], previous_proof_of_concept:["numbered_list","image","bulleted_list","instance_title","note","code_block"], proof_of_concept:["numbered_list","image","bulleted_list","instance_title","note","code_block"], in_conclusion:["paragraph","note"]};
  let autoSaveTimer;
  const autoSaveDelay = Math.max(100, Number(window.VULNREPORT_AUTOSAVE_IDLE_MS ?? window.VULNREPORT_AUTOSAVE_INTERVAL_MS) || 5000);
  let localDraftTimer;
  let reportChangeTimer;
  let pendingSave = false;
  let saveRevision = 0;
  let savedRevision = 0;
  let saveRetryCount = 0;
  const maxSaveRetries = 3;
  let saveInFlight = null;
  let saveConflict = null;
  let allowUnsavedUnload = false;
  let recoveryStorageWarningShown = false;
  const SAVE_STATES = Object.freeze({
    UNSAVED: "unsaved",
    SAVING: "saving",
    SAVED: "saved",
    FAILED: "failed",
    CONFLICT: "conflict",
    RECOVERED: "recovered",
  });
  let validateSetupInputs = () => true;
  let validateCurrentPage = () => true;
  let updateFindingSummary = () => {};
  const expandedFindingIds = new Set();
  // Creates stable client-side IDs for vulnerabilities, fragments, and evidence records.
  const id = (prefix) => `${prefix}_${crypto.randomUUID().replaceAll("-", "").slice(0, 8)}`;
  // Escapes text before it is inserted into generated HTML markup.
  const escape = (value) => String(value || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const libraryOptionMarkup = (entry, includePlaceholder = false) => {
    const tags = escape((entry.tags || []).join(", "));
    const warning = includePlaceholder && entry.requires_tester_input ? " | contains placeholder text" : "";
    return `<div class="library-entry" role="option" data-id="${escape(entry.library_id)}"><b>${escape(entry.title)}</b> <small>${tags}${warning}</small></div>`;
  };
  function renderLineMarkers(input, gutter, measure, markerText, markerClass) {
    const style = getComputedStyle(input);
    const contentWidth = input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    Object.assign(measure.style, {
      width:`${Math.max(1, contentWidth)}px`,
      fontFamily:style.fontFamily,
      fontSize:style.fontSize,
      fontWeight:style.fontWeight,
      fontStyle:style.fontStyle,
      letterSpacing:style.letterSpacing,
      lineHeight:style.lineHeight,
      overflowWrap:style.overflowWrap,
      wordBreak:style.wordBreak,
    });
    gutter.innerHTML = "";
    input.value.split(/\r?\n/).forEach(line => {
      measure.textContent = line || " ";
      const marker = document.createElement("span");
      marker.className = markerClass;
      marker.style.height = `${measure.offsetHeight}px`;
      marker.style.lineHeight = style.lineHeight;
      marker.textContent = markerText(line);
      gutter.append(marker);
    });
  }
  let comboboxId = 0;
  function wireLibraryCombobox(input, listbox) {
    if (!input || !listbox || input.dataset.keyboardReady) return;
    input.dataset.keyboardReady = "true";
    listbox.id ||= `library-options-${++comboboxId}`;
    input.setAttribute("aria-controls", listbox.id);
    let activeIndex = -1;
    const options = () => [...listbox.querySelectorAll('[role="option"]')];
    const setActive = index => {
      const available = options();
      activeIndex = available.length ? (index + available.length) % available.length : -1;
      available.forEach((option, optionIndex) => {
        option.id ||= `${listbox.id}-${optionIndex}`;
        option.setAttribute("aria-selected", String(optionIndex === activeIndex));
      });
      if (activeIndex >= 0) {
        input.setAttribute("aria-activedescendant", available[activeIndex].id);
        available[activeIndex].scrollIntoView({block:"nearest"});
      } else {
        input.removeAttribute("aria-activedescendant");
      }
    };
    new MutationObserver(() => setActive(-1)).observe(listbox, {childList:true});
    input.addEventListener("keydown", event => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        if (!options().length) return;
        event.preventDefault();
        setActive(activeIndex + (event.key === "ArrowDown" ? 1 : -1));
      } else if (event.key === "Enter" && activeIndex >= 0) {
        event.preventDefault();
        event.stopImmediatePropagation();
        options()[activeIndex]?.click();
      } else if (event.key === "Escape") {
        setActive(-1);
      }
    });
  }
  // Converts stored option values into their tester-facing labels.
  const optionLabel = (value) => statuses.find(status => status[0] === value)?.[1] || value.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
  // Renders a select element, including a disabled placeholder when required.
  const select = (values, current, nullable = false) => `<select>${nullable || (!current && values === severity) ? `<option value="" disabled ${!current ? "selected" : ""}>-</option>` : ""}${values.map(value => `<option value="${value}" ${value === current ? "selected" : ""}>${optionLabel(value)}</option>`).join("")}</select>`;
  // Updates the visible autosave state in the page header.
  function setSaveState(state, label) {
    const saveButton = document.querySelector("#save-button");
    if (!saveButton) return;
    const savedAt = new Date(report.saved_at);
    const savedTime = Number.isNaN(savedAt.getTime()) ? "" : new Intl.DateTimeFormat(undefined, {hour:"2-digit", minute:"2-digit", hourCycle:"h23"}).format(savedAt);
    const labels = {
      [SAVE_STATES.UNSAVED]: "Unsaved changes",
      [SAVE_STATES.SAVING]: "Saving...",
      [SAVE_STATES.SAVED]: savedTime ? `Saved ${savedTime}` : "Saved",
      [SAVE_STATES.FAILED]: "Save failed - Retry",
      [SAVE_STATES.CONFLICT]: "Resolve conflict",
      [SAVE_STATES.RECOVERED]: "Recovered changes",
    };
    saveButton.dataset.saveState = state;
    saveButton.textContent = label || labels[state];
    saveButton.disabled = state === SAVE_STATES.SAVED;
    saveButton.setAttribute("aria-live", "polite");
    saveButton.setAttribute("aria-busy", String(state === SAVE_STATES.SAVING));
    saveButton.title = state === SAVE_STATES.SAVED && savedTime ? `Last saved ${savedAt.toLocaleString()}` : "";
  }
  setSaveState(SAVE_STATES.SAVED);
  function showRecoveryStorageWarning(error) {
    if (!error) return;
    recoveryStorageError = error;
    const currentDiagnostic = document.querySelector("#app-diagnostics");
    if (recoveryStorageWarningShown && currentDiagnostic?.dataset.code === "recovery_storage_unavailable") return;
    recoveryStorageWarningShown = true;
    const warning = new Error("Browser recovery storage is unavailable. Server saves still work, but unsaved changes will not survive closing this tab.");
    warning.diagnostic = {status:"Browser", code:"recovery_storage_unavailable", exception_type:error.name};
    diagnostics.show(warning, "access_browser_recovery", {title:"Browser recovery unavailable", kind:"warning"});
  }
  showRecoveryStorageWarning(recoveryStorageError);
  function persistLocalDraft() {
    clearTimeout(localDraftTimer);
    try {
      localStorage.setItem(localDraftKey, JSON.stringify({
        schemaVersion: 1,
        reportId,
        tabId,
        baseSavedAt: report.saved_at,
        capturedAt: new Date().toISOString(),
        editRevision: saveRevision,
        report,
      }));
      return true;
    } catch (error) {
      showRecoveryStorageWarning(error);
      return false;
    }
  }
  function queueLocalDraft() {
    clearTimeout(localDraftTimer);
    localDraftTimer = window.setTimeout(persistLocalDraft, 150);
  }
  function queueBackendSave(delay = autoSaveDelay) {
    clearTimeout(autoSaveTimer);
    autoSaveTimer = window.setTimeout(() => {
      autoSaveTimer = undefined;
      if (pendingSave) void save();
    }, delay);
  }
  function clearLocalDraft() {
    clearTimeout(localDraftTimer);
    try {
      localStorage.removeItem(localDraftKey);
      if (restoredDraftKey && restoredDraftKey !== localDraftKey) localStorage.removeItem(restoredDraftKey);
      restoredDraftKey = null;
    } catch (error) { showRecoveryStorageWarning(error); }
  }
  function showLocalRecovery(candidate) {
    const basedOnCurrentRevision = candidate.envelope.baseSavedAt === serverReport.saved_at;
    const error = new Error(basedOnCurrentRevision
      ? "Unsaved changes from an earlier session are available."
      : "A local draft was created from an older saved version of this report.");
    error.diagnostic = {
      status: "Local",
      code: basedOnCurrentRevision ? "local_draft_available" : "stale_local_draft",
      timestamp: candidate.envelope.capturedAt,
    };
    diagnostics.show(error, "recover_local_draft", {
      title: "Unsaved changes found",
      kind: "warning",
      actions: [
        {
          label: "Restore",
          primary: true,
          operation: "restore_local_draft",
          run: () => {
            try {
              sessionStorage.setItem(recoverySelectionKey, candidate.key);
            } catch (error) {
              showRecoveryStorageWarning(error);
              return;
            }
            window.location.reload();
          },
        },
        {
          label: "Discard",
          operation: "discard_local_draft",
          run: () => {
            try {
              localStorage.removeItem(candidate.key);
            } catch (error) {
              showRecoveryStorageWarning(error);
              return;
            }
            diagnostics.clear();
            setSaveState(SAVE_STATES.SAVED);
          },
        },
      ],
    });
  }
  function queueReportChange() {
    clearTimeout(reportChangeTimer);
    reportChangeTimer = window.setTimeout(() => {
      reportChangeTimer = undefined;
      document.dispatchEvent(new Event("reportchange"));
    }, 100);
  }
  function applyServerRevision(savedAt) {
    if (!savedAt) return;
    report.saved_at = savedAt;
    previousReport.saved_at = savedAt;
    if (activeTextTransaction) activeTextTransaction.before.saved_at = savedAt;
  }
  function applyServerMetadata(savedReport) {
    applyServerRevision(savedReport.saved_at);
    for (const field of ["app_id", "_folder_name_hint"]) {
      report[field] = clone(savedReport[field]);
      previousReport[field] = clone(savedReport[field]);
      if (activeTextTransaction) activeTextTransaction.before[field] = clone(savedReport[field]);
    }
  }
  const sameValue = (left, right) => JSON.stringify(left) === JSON.stringify(right);
  const isRecord = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const stableItemKey = value => {
    if (!isRecord(value)) return null;
    const key = ["uid", "frag_id", "target_id", "evidence_id", "type"].find(candidate => value[candidate] != null);
    return key ? `${key}:${value[key]}` : null;
  };
  function reconcileCanonicalObject(live, sent, canonical) {
    let changed = false;
    const keys = new Set([...Object.keys(sent || {}), ...Object.keys(canonical || {})]);
    keys.forEach(key => {
      // scope_text is client-only; the server consumes it into scope_targets and never echoes it back.
      if (["saved_at", "app_id", "_folder_name_hint", "scope_text"].includes(key)) return;
      const sentValue = sent?.[key];
      const canonicalValue = canonical?.[key];
      if (sameValue(sentValue, canonicalValue)) return;
      const liveValue = live?.[key];
      if (Array.isArray(sentValue) && Array.isArray(canonicalValue) && Array.isArray(liveValue)) {
        const keyed = [sentValue, canonicalValue, liveValue].every(items => {
          const itemKeys = items.map(stableItemKey);
          return itemKeys.every(Boolean) && new Set(itemKeys).size === itemKeys.length;
        });
        if (keyed) {
          const sentByKey = new Map(sentValue.map(item => [stableItemKey(item), item]));
          const canonicalByKey = new Map(canonicalValue.map(item => [stableItemKey(item), item]));
          const liveByKey = new Map(liveValue.map(item => [stableItemKey(item), item]));
          canonicalByKey.forEach((canonicalItem, itemKey) => {
            const sentItem = sentByKey.get(itemKey);
            const liveItem = liveByKey.get(itemKey);
            if (sentItem && liveItem) {
              changed = reconcileCanonicalObject(liveItem, sentItem, canonicalItem) || changed;
            } else if (!sentItem && !liveItem) {
              liveValue.push(clone(canonicalItem));
              changed = true;
            }
          });
          sentByKey.forEach((sentItem, itemKey) => {
            if (canonicalByKey.has(itemKey)) return;
            const liveIndex = liveValue.findIndex(item => stableItemKey(item) === itemKey);
            if (liveIndex >= 0 && sameValue(liveValue[liveIndex], sentItem)) {
              liveValue.splice(liveIndex, 1);
              changed = true;
            }
          });
        } else if (sameValue(liveValue, sentValue)) {
          liveValue.splice(0, liveValue.length, ...clone(canonicalValue));
          changed = true;
        }
      } else if (isRecord(sentValue) && isRecord(canonicalValue) && isRecord(liveValue)) {
        changed = reconcileCanonicalObject(liveValue, sentValue, canonicalValue) || changed;
      } else if (sameValue(liveValue, sentValue)) {
        if (canonicalValue === undefined) delete live[key];
        else live[key] = clone(canonicalValue);
        changed = true;
      }
    });
    return changed;
  }
  function applyCanonicalReport(sentReport, savedReport) {
    reconcileCanonicalObject(report, sentReport, savedReport);
    reconcileCanonicalObject(previousReport, sentReport, savedReport);
    if (activeTextTransaction) reconcileCanonicalObject(activeTextTransaction.before, sentReport, savedReport);
    applyServerMetadata(savedReport);
  }
  function clearSaveConflict() {
    saveConflict = null;
    const saveButton = document.querySelector("#save-button");
    if (saveButton) delete saveButton.dataset.action;
  }
  function markSaveConflict(error, operation = "save_report") {
    const normalized = diagnostics.normalize(error, operation, "This report changed elsewhere");
    saveConflict = normalized.diagnostic;
    pendingSave = true;
    persistLocalDraft();
    const saveButton = document.querySelector("#save-button");
    if (saveButton) saveButton.dataset.action = "resolve";
    setSaveState(SAVE_STATES.CONFLICT);
    diagnostics.show(normalized, operation, {
      title: "Save conflict",
      kind: "conflict",
      actions: [
        {
          label: "Save my version",
          primary: true,
          operation: "resolve_save_conflict",
          run: async conflictError => {
            const latestSavedAt = conflictError.diagnostic.latest_saved_at;
            if (!latestSavedAt) throw new Error("The latest report revision is unavailable. Load the latest version instead.");
            applyServerRevision(latestSavedAt);
            clearSaveConflict();
            pendingSave = true;
            saveRevision += 1;
            diagnostics.clear();
            setSaveState(SAVE_STATES.SAVING);
            await save();
          },
        },
        {
          label: "Load latest",
          operation: "load_latest_report",
          run: () => {
            clearLocalDraft();
            try { sessionStorage.removeItem(historyKey); } catch (error) { showRecoveryStorageWarning(error); }
            clearSaveConflict();
            allowUnsavedUnload = true;
            window.location.reload();
          },
        },
      ],
    });
  }
  function showOperationError(error, operation, fallback) {
    const normalized = diagnostics.show(error, operation, {fallback});
    if (operation === "save_report") setSaveState(SAVE_STATES.FAILED);
    else setSaveState(pendingSave && savedRevision < saveRevision ? SAVE_STATES.UNSAVED : SAVE_STATES.SAVED);
    return normalized;
  }
  function diff(before, after, path = []) {
    if (before === after) return [];
    const bothObjects = before && after && typeof before === "object" && typeof after === "object" && !Array.isArray(before) && !Array.isArray(after);
    if (!bothObjects) return [{path, beforePresent:true, before:clone(before), afterPresent:true, after:clone(after)}];
    const changes = [];
    new Set([...Object.keys(before), ...Object.keys(after)]).forEach(key => {
      if (!(key in before)) changes.push({path:[...path, key], beforePresent:false, afterPresent:true, after:clone(after[key])});
      else if (!(key in after)) changes.push({path:[...path, key], beforePresent:true, before:clone(before[key]), afterPresent:false});
      else changes.push(...diff(before[key], after[key], [...path, key]));
    });
    return changes;
  }
  function applyChanges(target, changes, direction) {
    [...changes].reverse().forEach(change => {
      const useBefore = direction === "undo";
      const present = useBefore ? change.beforePresent : change.afterPresent;
      let parent = target;
      change.path.slice(0, -1).forEach(key => { parent = parent[key]; });
      const key = change.path.at(-1);
      if (present) parent[key] = clone(useBefore ? change.before : change.after);
      else delete parent[key];
    });
  }
  function updateHistoryControls() {
    const undoButton = document.querySelector("#undo-button");
    const redoButton = document.querySelector("#redo-button");
    if (undoButton) undoButton.disabled = !undoHistory.length;
    if (redoButton) redoButton.disabled = !redoHistory.length;
  }
  function storeHistory() {
    let stored = true;
    try { sessionStorage.setItem(historyKey, JSON.stringify({undoHistory, redoHistory})); } catch (error) { stored = false; showRecoveryStorageWarning(error); }
    updateHistoryControls();
    return stored;
  }
  function restoreHistory(action, direction) {
    const priorPendingSave = pendingSave;
    applyChanges(report, action.changes, direction);
    previousReport = clone(report);
    activeTextTransaction = null;
    pendingSave = true;
    const rollback = () => {
      applyChanges(report, action.changes, direction === "undo" ? "redo" : "undo");
      previousReport = clone(report);
      pendingSave = priorPendingSave;
      if (priorPendingSave) persistLocalDraft(); else clearLocalDraft();
      return false;
    };
    if (!persistLocalDraft() || !storeHistory()) return rollback();
    try {
      sessionStorage.setItem(recoverySelectionKey, localDraftKey);
    } catch (error) {
      showRecoveryStorageWarning(error);
      return rollback();
    }
    allowUnsavedUnload = true;
    window.location.reload();
    return true;
  }
  function finalizeTextTransaction() {
    if (!activeTextTransaction) return;
    activeTextTransaction.action.changes = diff(activeTextTransaction.before, report);
    if (!activeTextTransaction.action.changes.length) {
      const index = undoHistory.indexOf(activeTextTransaction.action);
      if (index >= 0) undoHistory.splice(index, 1);
    }
    activeTextTransaction = null;
    previousReport = clone(report);
    storeHistory();
  }
  const updateSetupValidationNotice = () => {
    if (root.dataset.step !== "setup") return;
    const notice = document.querySelector("#setup-validation-note");
    if (!notice?.dataset.validationAttempted) return;
    const missing = [];
    if (!root.querySelector('[data-path="engagement.app_name"]')?.value.trim()) missing.push("application name");
    if (!root.querySelector('[data-path="engagement.segment"]')?.value) missing.push("segment");
    if (!root.querySelector('[data-path="engagement.report_type"]')?.value) missing.push("report type");
    const ciNumber = root.querySelector('[data-path="engagement.ci_number"]')?.value.trim();
    const bsnNumber = root.querySelector('[data-path="engagement.bsn_number"]')?.value.trim();
    if (!ciNumber && !bsnNumber) missing.push("CI or BSN number");
    if (!root.querySelector('[data-path="engagement.tester"]')?.value.trim()) missing.push("tester");
    if (!root.querySelector('#test-windows input[type="checkbox"]:checked')) missing.push("selected environment");
    if ([...root.querySelectorAll('#test-windows input[type="date"]')].some(input => !input.value)) missing.push("testing dates");
    ["production", "non_production"].forEach(environment => {
      const panel = root.querySelector(`#scope-grid .scope-panel.${environment}`);
      if (panel && ![...panel.querySelectorAll("textarea")].some(input => input.value.split("\n").some(value => value.trim() && !value.trimStart().startsWith("#")))) missing.push(`${environment.replace("_", "-")} scope target`);
    });
    const invalidMessages = [...new Set(
      [...root.querySelectorAll("[data-setup-validated]")]
        .filter(input => !input.validity.valid)
        .map(input => input.validationMessage)
        .filter(Boolean)
    )];
    const messages = [];
    if (missing.length) messages.push(`Missing: ${missing.join(", ")}`);
    if (invalidMessages.length) messages.push(`Invalid: ${invalidMessages.join("; ")}`);
    notice.hidden = !messages.length;
    notice.textContent = messages.length ? `${messages.join(". ")}.` : "";
  };
  root.addEventListener("input", updateSetupValidationNotice);
  root.addEventListener("change", updateSetupValidationNotice);
  const routeGate = new URLSearchParams(window.location.search).get("incomplete");
  if (routeGate === "setup") {
    const notice = document.querySelector("#setup-validation-note");
    if (notice) {
      notice.hidden = false;
      notice.dataset.validationAttempted = "true";
      notice.textContent = "Complete the highlighted Setup requirements before continuing.";
    }
  }
  if (routeGate === "findings") {
    const notice = document.querySelector("#finding-validation-note");
    if (notice) {
      notice.hidden = false;
      notice.textContent = "Add at least one complete finding before continuing to Content.";
    }
  }
  const activeTextEntry = () => {
    const activeElement = document.activeElement;
    return activeElement?.matches('input:not([type="checkbox"],[type="radio"],[type="file"]), textarea, [contenteditable="true"]') ? activeElement : null;
  };
  root.addEventListener("focusout", () => {
    queueMicrotask(() => {
      if (!activeTextEntry()) {
        finalizeTextTransaction();
      }
    });
  });
  // Records edits locally; persistence happens on a 30-second cadence, manual save, or navigation.
  function scheduleSave() {
    saveRetryCount = 0;
    const textEntry = activeTextEntry();
    if (textEntry && activeTextTransaction?.input === textEntry) {
      saveRevision += 1;
      pendingSave = true;
      queueLocalDraft();
      queueBackendSave();
      setSaveState(SAVE_STATES.UNSAVED);
      queueReportChange();
      return;
    }
    if (!textEntry) finalizeTextTransaction();
    const changes = diff(previousReport, report);
    if (changes.length) {
      const action = {changes};
      undoHistory.push(action);
      if (undoHistory.length > maxHistoryEntries) undoHistory.shift();
      redoHistory.length = 0;
      activeTextTransaction = textEntry ? {input:textEntry, before:clone(previousReport), action} : null;
      storeHistory();
      previousReport = clone(report);
    }
    saveRevision += 1;
    pendingSave = true;
    queueLocalDraft();
    queueBackendSave();
    setSaveState(SAVE_STATES.UNSAVED);
    queueReportChange();
  }
  // Sends the current report object to the server for validation and atomic saving.
  async function save(successStatus) {
    if (saveConflict) return false;
    if (saveInFlight) return saveInFlight;
    if (!pendingSave || savedRevision >= saveRevision) return true;
    if (root.dataset.step === "setup" && !validateSetupInputs(false)) {
      setSaveState(SAVE_STATES.UNSAVED, "Correct invalid Setup fields");
      return false;
    }
    clearTimeout(autoSaveTimer);
    saveInFlight = (async () => {
      try {
        setSaveState(SAVE_STATES.SAVING);
        while (savedRevision < saveRevision) {
          const revision = saveRevision;
          const sentReport = clone(report);
          const response = await fetch(`/reports/${reportId}`, {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(sentReport)});
          if (!response.ok) throw await diagnostics.fromResponse(response, "save_report", "Save failed");
          const saved = await response.json();
          applyCanonicalReport(sentReport, saved.report);
          if (!activeTextTransaction) previousReport = clone(report);
          savedRevision = revision;
          if (savedRevision === saveRevision) {
            pendingSave = false;
            clearLocalDraft();
            const visibleDiagnostic = document.querySelector("#app-diagnostics");
            if (saveRetryCount && visibleDiagnostic?.dataset.operation === "save_report") diagnostics.clear();
            if (recoveryStorageError) showRecoveryStorageWarning(recoveryStorageError);
            saveRetryCount = 0;
            setSaveState(successStatus ? SAVE_STATES.SAVING : SAVE_STATES.SAVED, successStatus);
            updateEngagementName();
          } else {
            pendingSave = true;
            queueLocalDraft();
            setSaveState(SAVE_STATES.SAVING);
          }
        }
        return true;
      } catch (error) {
        if (error.status === 409) {
          markSaveConflict(error, "save_report");
          return false;
        }
        pendingSave = true;
        persistLocalDraft();
        showOperationError(error, "save_report", "Save failed");
        if ((!error.status || error.status >= 500) && saveRetryCount < maxSaveRetries) {
          saveRetryCount += 1;
          queueBackendSave(autoSaveDelay * (2 ** (saveRetryCount - 1)));
        }
        return false;
      } finally {
        saveInFlight = null;
      }
    })();
    return saveInFlight;
  }
  document.querySelector("#save-button")?.addEventListener("click", () => {
    if (document.querySelector("#save-button")?.dataset.action === "resolve") {
      document.querySelector("#app-diagnostics")?.focus({preventScroll:true});
      return;
    }
    if (root.dataset.step === "setup" && !validateSetupInputs(true)) {
      setSaveState(SAVE_STATES.UNSAVED, "Correct invalid Setup fields");
      return;
    }
    saveRetryCount = 0;
    save();
  });
  document.querySelector("#generate-report")?.addEventListener("click", async event => {
    const button = event.currentTarget;
    if (button.dataset.busy === "true") return;
    const label = button.textContent;
    button.dataset.busy = "true";
    button.disabled = true;
    button.textContent = pendingSave || savedRevision < saveRevision ? "Saving..." : "Generating...";
    if (!(await save()) || pendingSave || savedRevision < saveRevision) {
      delete button.dataset.busy;
      button.textContent = label;
      button.disabled = false;
      return;
    }
    button.textContent = "Generating...";
    try {
      const response = await fetch(`/reports/${reportId}/generate`, {method:"POST"});
      if (!response.ok) throw await diagnostics.fromResponse(response, "generate_report_to_folder", "Generation failed");
      const generated = await response.json();
      if (document.querySelector("#app-diagnostics")?.dataset.operation === "generate_report_to_folder") diagnostics.clear();
      button.textContent = "Generate Report";
      delete button.dataset.busy;
      button.disabled = false;
      const status = document.querySelector("#generate-status");
      if (status) {
        status.hidden = false;
        status.textContent = `Your Word report is ready. Look for "${generated.filename}" inside the app's "generated" folder.`;
        status.title = generated.path;
      }
    } catch (error) {
      showOperationError(error, "generate_report_to_folder", "Generation failed");
      delete button.dataset.busy;
      button.textContent = label;
      button.disabled = false;
    }
  });
  document.querySelectorAll(".back-link").forEach(link => link.addEventListener("click", async event => {
    event.preventDefault();
    // Going back is never gated: the tester is on their way to fix the gaps.
    if (!document.querySelector("#editor") && !validateCurrentPage(true)) {
      return;
    }
    if (await save()) window.location.assign(link.dataset.href);
  }));
  const undo = () => {
    finalizeTextTransaction();
    const action = undoHistory.pop();
    if (!action) return;
    redoHistory.push(action);
    if (!restoreHistory(action, "undo")) {
      redoHistory.pop();
      undoHistory.push(action);
      storeHistory();
    }
  };
  const redo = () => {
    const action = redoHistory.pop();
    if (!action) return;
    undoHistory.push(action);
    if (!restoreHistory(action, "redo")) {
      undoHistory.pop();
      redoHistory.push(action);
      storeHistory();
    }
  };
  document.querySelector("#undo-button")?.addEventListener("click", undo);
  document.querySelector("#redo-button")?.addEventListener("click", redo);
  document.addEventListener("keydown", event => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== "z") return;
    event.preventDefault();
    if (event.shiftKey) redo(); else undo();
  });
  updateHistoryControls();
  window.addEventListener("pagehide", () => {
    if (!pendingSave) return;
    clearTimeout(autoSaveTimer);
    finalizeTextTransaction();
    persistLocalDraft();
  });
  window.addEventListener("beforeunload", event => {
    if (allowUnsavedUnload || saveRevision <= savedRevision) return;
    persistLocalDraft();
    event.preventDefault();
    event.returnValue = "";
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && pendingSave) void save();
  });
  if (recoveredDraft) {
    saveRevision += 1;
    pendingSave = true;
    setSaveState(SAVE_STATES.RECOVERED);
    queueBackendSave();
  } else if (recoveryCandidate) {
    showLocalRecovery(recoveryCandidate);
  }
  // Converts editor DOM content into normalized, storage-safe rich-text runs.
  function runsFrom(element) {
    const output = [];
    const walk = (node, format = {}) => {
      if (node.nodeType === Node.TEXT_NODE && node.nodeValue) output.push({text:node.nodeValue, ...format});
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const tag = node.tagName.toLowerCase();
      const next = {...format, bold:format.bold || tag === "b" || tag === "strong", italic:format.italic || tag === "i" || tag === "em", underline:format.underline || tag === "u"};
      node.childNodes.forEach(child => walk(child, next));
    };
    element.childNodes.forEach(child => walk(child));
    const runs = output.reduce((all, run) => { const prior = all.at(-1); if (prior && prior.bold === run.bold && prior.italic === run.italic && prior.underline === run.underline) prior.text += run.text; else all.push(run); return all; }, []).filter(run => run.text).map(run => { if (!run.bold) delete run.bold; if (!run.italic) delete run.italic; if (!run.underline) delete run.underline; return run; });
    while (runs[0]?.text.trim() === "") runs.shift();
    while (runs.at(-1)?.text.trim() === "") runs.pop();
    return runs;
  }
  // Re-fits on width changes only, and off the observer frame; resizing inline would loop the observer.
  const observeWidth = (element, onWidthChange) => {
    let lastWidth = null;
    new ResizeObserver(() => {
      if (element.clientWidth === lastWidth) return;
      lastWidth = element.clientWidth;
      requestAnimationFrame(onWidthChange);
    }).observe(element);
  };
  // Builds a bold/italic/underline editor and reports normalized runs on change.
  function rich(runs, onChange, includeToolbar = true, placeholder = "") {
    const wrap = document.createElement("div"); wrap.innerHTML = `${includeToolbar ? '<div class="toolbar" role="toolbar" aria-label="Text formatting"><button type="button" tabindex="-1" title="Bold" aria-label="Bold"><b>B</b></button><button type="button" tabindex="-1" title="Italic" aria-label="Italic"><i>I</i></button><button type="button" tabindex="-1" title="Underline" aria-label="Underline"><u>U</u></button></div>' : ""}<div class="rich" contenteditable="true" role="textbox" aria-multiline="true"></div>`;
    const input = wrap.querySelector(".rich"); input.innerHTML = runs.map(run => `${run.bold ? "<b>" : ""}${run.italic ? "<i>" : ""}${run.underline ? "<u>" : ""}${escape(run.text)}${run.underline ? "</u>" : ""}${run.italic ? "</i>" : ""}${run.bold ? "</b>" : ""}`).join("");
    if (placeholder) { input.dataset.placeholder = placeholder; input.setAttribute("aria-label", placeholder); }
    const resize = () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`; };
    wrap.querySelectorAll("button").forEach((button, index) => button.onclick = () => { input.focus(); document.execCommand(["bold", "italic", "underline"][index]); onChange(runsFrom(input)); });
    input.onpaste = event => { event.preventDefault(); document.execCommand("insertText", false, event.clipboardData?.getData("text/plain") || ""); requestAnimationFrame(() => { resize(); onChange(runsFrom(input)); }); };
    input.oninput = () => { resize(); onChange(runsFrom(input)); };
    requestAnimationFrame(resize);
    // Height is frozen at construction, so re-measure once fonts settle and on every width change.
    document.fonts?.ready.then(resize);
    observeWidth(input, resize);
    return wrap;
  }
  // Ensures a finding has the content blocks and required starter fragments for its status.
  const fragmentHasText = fragment => (fragment.runs || []).some(run => run.text?.trim());
  const isDefaultStatusConclusion = fragment => fragment.type === "paragraph" && /^The finding ".*" is(?: still)? (?:Open|Resolved)\.$/.test((fragment.runs || []).map(run => run.text).join(""));
  function syncConclusion(vulnerability) {
    const conclusion = vulnerability.contents?.find(content => content.type === "in_conclusion");
    if (!conclusion) return;
    const status = vulnerability.status === "resolved" ? "Resolved" : "Open";
    const paragraphs = conclusion.fragments.filter(fragment => fragment.type === "paragraph");
    const generated = paragraphs.find(fragment => fragment.generated === "status_conclusion");
    let defaultParagraph = generated || paragraphs.find(isDefaultStatusConclusion) || paragraphs.find(fragment => !fragmentHasText(fragment));
    if (!defaultParagraph && !paragraphs.length) {
      defaultParagraph = newFragment("paragraph");
      conclusion.fragments.unshift(defaultParagraph);
    }
    if (defaultParagraph && (generated || !fragmentHasText(defaultParagraph) || isDefaultStatusConclusion(defaultParagraph))) {
      delete defaultParagraph.generated;
      defaultParagraph.runs = [{text: `The finding "${vulnerability.title}" is ${status === "Open" ? "still " : ""}`}, {text:status, bold:true}, {text:"."}];
    }
    if (generated) conclusion.fragments = conclusion.fragments.filter(fragment => fragment === generated || fragment.type !== "paragraph" || fragmentHasText(fragment));
  }
  function provision(vulnerability) {
    const types = vulnerability.status === "open_new" ? ["description","recommended_remediation","proof_of_concept"] : ["description","recommended_remediation","previous_proof_of_concept","proof_of_concept","in_conclusion"];
    const existing = Object.fromEntries((vulnerability.contents || []).map(content => [content.type, content]));
    vulnerability.contents = types.map(type => existing[type] || {type, fragments:[]});
    const required = {description:["paragraph"], recommended_remediation:["paragraph"], previous_proof_of_concept:["numbered_list","image"], proof_of_concept:["numbered_list","image"], in_conclusion:[]};
    vulnerability.contents.forEach(content => {
      if (content.fragments.length) return;
      const present = new Set(content.fragments.map(fragment => fragment.type));
      required[content.type].forEach(type => { if (!present.has(type)) content.fragments.push(newFragment(type)); });
    });
    if (vulnerability.status === "resolved") { const remediation = vulnerability.contents.find(content => content.type === "recommended_remediation"); remediation.fragments = [{frag_id:id("f"),type:"paragraph",runs:[{text:"None, the vulnerability has been remediated."}]}]; }
    syncConclusion(vulnerability);
    syncEvidenceImageSlots(vulnerability);
  }
  const scopeTargetIds = scope => {
    const mode = scope?.mode || "custom";
    if (mode === "custom") return scope?.target_ids || [];
    if (mode === "all") return report.scope_targets.map(target => target.target_id);
    const environment = mode === "all_production" ? "production" : "non_production";
    return report.scope_targets.filter(target => target.environment === environment).map(target => target.target_id);
  };
  const scopeHasLocation = finding => scopeTargetIds(finding.scope).length > 0 || (finding.scope?.mode === "custom" && Object.values(finding.scope?.custom_locations || {}).flat().some(value => value.trim()));
  const scopeEnvironments = scope => {
    const environments = [];
    const add = environment => { if (environment && !environments.includes(environment)) environments.push(environment); };
    scopeTargetIds(scope).forEach(targetId => add(report.scope_targets.find(target => target.target_id === targetId)?.environment));
    if ((scope?.mode || "custom") === "custom") Object.entries(scope?.custom_locations || {}).forEach(([environment, locations]) => { if (locations.some(value => value.trim())) add(environment); });
    return environments;
  };
  const affectedEnvironments = finding => scopeEnvironments(finding.scope);
  const environmentName = environment => environment === "production" ? "Production" : "Non-Production";
  const imagesForEnvironment = (finding, environment) => finding.contents.flatMap(content => (content.fragments || []).filter(fragment => fragment.type === "image" && fragment.environment === environment));
  const syncEvidenceImageSlots = finding => {
    const environments = affectedEnvironments(finding);
    const images = finding.contents.flatMap(content => content.fragments.filter(fragment => fragment.type === "image"));
    if (environments.length === 1) images.forEach(image => { image.environment = environments[0]; });
    let missing = environments.filter(environment => !images.some(image => image.environment === environment));
    images.filter(image => !image.environment).forEach(image => { image.environment = missing.shift() || environments[0] || null; });
    missing = environments.filter(environment => !images.some(image => image.environment === environment));
    const proof = finding.contents.find(content => content.type === "proof_of_concept");
    missing.forEach(environment => { const image = newFragment("image"); image.environment = environment; proof?.fragments.push(image); });
  };
  // Initializes the setup page's engagement metadata, coverage, and scope controls.
  function setup() {
    const environmentLabels = {production:"Production", non_production:"Non-Production"};
    const channelLabels = {api:"API", web:"Web", mobile:"Mobile"};
    const testTypes = {web:{label:"Web App", channels:["web"]}, api:{label:"API", channels:["api"]}, mobile:{label:"Mobile", channels:["mobile"]}, web_api:{label:"Web App + API", channels:["web", "api"]}};
    const nonProductionLabels = ["UAT", "TEST/MO", "DEV"];
    const characterNames = new Map([
      [" ","space"], ["\t","tab"], ["\n","line feed"], ["\r","carriage return"], ["!","exclamation mark"], ['"',"double quote"], ["#","number sign"], ["$","dollar sign"], ["%","percent sign"], ["&","ampersand"], ["'","apostrophe"], ["(","left parenthesis"], [")","right parenthesis"], ["*","asterisk"], ["+","plus sign"], [",","comma"], ["-","hyphen"], [".","period"], ["/","slash"], [":","colon"], [";","semicolon"], ["<","less-than sign"], ["=","equals sign"], [">","greater-than sign"], ["?","question mark"], ["@","at sign"], ["[","left bracket"], ["\\","backslash"], ["]","right bracket"], ["^","caret"], ["_","underscore"], ["`","grave accent"], ["{","left brace"], ["|","vertical bar"], ["}","right brace"], ["~","tilde"],
    ]);
    const digitNames = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];
    const characterName = character => characterNames.get(character) || (/^[0-9]$/.test(character) ? `digit ${digitNames[Number(character)]}` : `Unicode U+${character.codePointAt(0).toString(16).toUpperCase().padStart(4, "0")}`);
    const invalidCharacterMessage = (label, characters) => `${label} contains invalid character${characters.length === 1 ? "" : "s"}: ${characters.map(character => `${JSON.stringify(character)} (${characterName(character)})`).join(", ")}`;
    const characterRule = (label, allowed) => {
      const invalidCharacters = value => [...new Set([...value].filter(character => !allowed.test(character)))];
      return {label, invalidCharacters, valid:value => !invalidCharacters(value).length};
    };
    const usernameCharacters = characterRule("Username", /^[A-Za-z0-9._@\\-]$/);
    const mobileScopeCharacters = characterRule("Mobile scope", /^[\p{L}\p{Nd} :'"/.,\-_&]$/u);
    const mobileScopeInvalidCharacters = value => mobileScopeCharacters.invalidCharacters(
      value.split(/\r?\n/).filter(line => line.trim() && !line.trimStart().startsWith("#")).join("")
    );
    const mobileScopeRule = {
      label:"Mobile scope",
      invalidCharacters:mobileScopeInvalidCharacters,
      valid:value => !mobileScopeInvalidCharacters(value).length,
    };
    const setupRules = {
      app_name: characterRule("Application name", /^[\p{L}\p{Nd} :()\-]$/u),
      ci_number: characterRule("CI number", /^[\p{L}\p{Nd}-]$/u),
      bsn_number: characterRule("BSN number", /^[\p{L}\p{Nd}-]$/u),
      app_owner: characterRule("Application owner", /^[\p{L} \-]$/u),
      tester: characterRule("Tester", /^[\p{L} \-]$/u),
      limitations: characterRule("Limitations", /^[\p{L}\p{Nd} /,.()&'"\-\r\n]$/u),
      time: characterRule("Time", /^[\p{L}\p{Nd} :/\-]$/u),
      userRole: characterRule("User role", /^[\p{L}\p{Nd} /\-]$/u),
      username: {...usernameCharacters, valid:value => !value || value === "N/A" || /^[A-Za-z0-9](?:[A-Za-z0-9._@\\-]*[A-Za-z0-9])?$/.test(value), message:label => `${label} must start and end with a letter or number`},
    };
    const setupNotice = document.querySelector("#setup-validation-note");
    const showRuleState = (input, invalid, marker) => {
      if (invalid) {
        input.dataset[marker] = "true";
        input.classList.add("validation-error");
        input.setAttribute("aria-invalid", "true");
      } else if (input.dataset[marker]) {
        delete input.dataset[marker];
        input.classList.remove("validation-error");
        input.removeAttribute("aria-invalid");
      }
    };
    const wireSetupRule = (input, rule, label = rule.label) => {
      input.dataset.setupValidated = "true";
      const validate = () => {
        const invalid = !rule.valid(input.value);
        const invalidCharacters = rule.invalidCharacters?.(input.value) || [];
        const message = invalidCharacters.length ? invalidCharacterMessage(label, invalidCharacters) : rule.message?.(label);
        input.setCustomValidity(invalid ? message : "");
        showRuleState(input, invalid, "ruleInvalid");
      };
      input.addEventListener("input", validate);
      input.addEventListener("change", validate);
      validate();
    };
    validateSetupInputs = reveal => {
      const invalidInputs = [...root.querySelectorAll("[data-setup-validated]")].filter(input => !input.validity.valid);
      if (reveal && invalidInputs.length) {
        if (setupNotice) setupNotice.dataset.validationAttempted = "true";
        invalidInputs.forEach(input => input.classList.add("validation-error"));
        updateSetupValidationNotice();
        invalidInputs[0].scrollIntoView({behavior:"smooth", block:"center"});
        invalidInputs[0].focus({preventScroll:true});
        invalidInputs[0].reportValidity();
      }
      return !invalidInputs.length;
    };
    report.engagement.tested_environments ||= ["production", "non_production"];
    report.engagement.test_type ||= "web";
    report.engagement.test_windows ||= {};
    ["production", "non_production"].forEach(environment => {
      report.engagement.test_windows[environment] ||= {
        start_date: environment === "production" ? report.engagement.start_date : null,
        end_date: environment === "production" ? report.engagement.end_date : null,
        test_time: "Any time",
      };
      if (report.engagement.test_windows[environment].test_time == null) report.engagement.test_windows[environment].test_time = "Any time";
    });
    report.engagement.test_accounts ||= [{user_role:"N/A", username:"N/A"}];
    if (report.engagement.limitations == null) report.engagement.limitations = "N/A";
    report.scope_text ||= {};
    ["production", "non_production"].forEach(environment => {
      report.scope_text[environment] ||= {};
      ["api", "web", "mobile"].forEach(channel => {
        if (report.scope_text[environment][channel] === undefined) {
          report.scope_text[environment][channel] = report.scope_targets.filter(target => target.environment === environment && target.channel === channel).sort((left, right) => left.order - right.order).map(target => target.value).join("\n");
        }
      });
    });
    root.querySelectorAll("[data-path]").forEach(input => {
      const [section, field] = input.dataset.path.split(".");
      input.value = report[section][field] ?? "";
      const grow = input.tagName === "TEXTAREA"
        ? () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`; }
        : null;
      if (grow) {
        input.rows = 1;
        grow();
        document.fonts?.ready.then(grow);
        observeWidth(input, grow);
      }
      input.oninput = () => { report[section][field] = input.value || (input.matches('select, input[type="date"]') ? null : ""); if (input.value.trim()) input.classList.remove("validation-error"); grow?.(); scheduleSave(); };
      if (setupRules[field]) wireSetupRule(input, setupRules[field]);
    });
    const accountBody = document.querySelector("#test-accounts");
    if (accountBody) {
      const renderAccounts = () => {
        accountBody.innerHTML = "";
        report.engagement.test_accounts.forEach((account, index) => {
          const row = document.createElement("tr");
          row.innerHTML = `<td><input aria-label="User role ${index + 1}" value="${escape(account.user_role)}"></td><td><input aria-label="Username ${index + 1}" value="${escape(account.username)}"></td><td><button class="remove-test-account" type="button" aria-label="Remove test account ${index + 1}" title="Remove account">x</button></td>`;
          const [roleInput, usernameInput] = row.querySelectorAll("input");
          roleInput.oninput = () => { account.user_role = roleInput.value; scheduleSave(); };
          usernameInput.oninput = () => { account.username = usernameInput.value; scheduleSave(); };
          wireSetupRule(roleInput, setupRules.userRole, `User role ${index + 1}`);
          wireSetupRule(usernameInput, setupRules.username, `Username ${index + 1}`);
          row.querySelector("button").onclick = () => { report.engagement.test_accounts.splice(index, 1); renderAccounts(); scheduleSave(); };
          accountBody.append(row);
        });
      };
      document.querySelector("#add-test-account").onclick = () => {
        report.engagement.test_accounts.push({user_role:"", username:""});
        renderAccounts();
        accountBody.lastElementChild?.querySelector("input")?.focus();
        scheduleSave();
      };
      renderAccounts();
    }
    const configuration = document.querySelector("#test-configuration");
    const windows = document.querySelector("#test-windows");
    const scopeGrid = document.querySelector("#scope-grid");
    const selected = (values, value) => values.includes(value);
    if (configuration && windows && scopeGrid) {
    const renderCoverage = () => {
      configuration.innerHTML = "";
      const typeGroup = document.createElement("label");
      typeGroup.className = "test-type-select";
      typeGroup.innerHTML = `<span>Test Surface</span><select>${Object.entries(testTypes).map(([value, type]) => `<option value="${value}" ${report.engagement.test_type === value ? "selected" : ""}>${type.label}</option>`).join("")}</select>`;
      typeGroup.querySelector("select").onchange = event => {
        report.engagement.test_type = event.target.value;
        renderCoverage();
        scheduleSave();
      };
      configuration.append(typeGroup);
      windows.innerHTML = "";
      Object.entries(environmentLabels).forEach(([environment, label]) => {
        const window = report.engagement.test_windows[environment];
        const panel = document.createElement("div");
        panel.className = "environment-window";
        const isSelected = selected(report.engagement.tested_environments, environment);
        // Non-Production shows its report name as a picker; the checkbox keeps the stable environment name.
        const name = environment === "non_production"
          ? `<select class="coverage-name" aria-label="Non-Production name" title="Labels the Proof of Concept evidence in the generated report" ${isSelected ? "" : "disabled"}>${nonProductionLabels.map(value => `<option value="${value}" ${report.engagement.non_production_label === value ? "selected" : ""}>${value}</option>`).join("")}</select>`
          : label;
        panel.innerHTML = `<label class="coverage-option"><input type="checkbox" value="${environment}" aria-label="${label}" ${isSelected ? "checked" : ""}>${name}</label>${isSelected ? `<div class="date-pair"><label>Start<input type="date" aria-label="${label} start date"></label><label>End<input type="date" aria-label="${label} end date"></label><label>Time<input type="text" aria-label="${label} time"></label></div>` : ""}`;
        const coverageName = panel.querySelector(".coverage-name");
        if (coverageName) {
          coverageName.onchange = event => {
            report.engagement.non_production_label = event.target.value;
            scheduleSave();
          };
        }
        panel.querySelector("input[type=checkbox]").onchange = event => {
          const values = report.engagement.tested_environments;
          report.engagement.tested_environments = event.target.checked ? [...values, environment] : values.filter(item => item !== environment);
          renderCoverage();
          scheduleSave();
        };
        if (!isSelected) {
          windows.append(panel);
          return;
        }
        const [startDate, endDate] = panel.querySelectorAll("input[type=date]");
        const timeInput = panel.querySelector('input[type="text"]');
        startDate.value = window.start_date || "";
        endDate.value = window.end_date || "";
        timeInput.value = window.test_time;
        startDate.oninput = () => { window.start_date = startDate.value || null; if (startDate.value) startDate.classList.remove("validation-error"); scheduleSave(); };
        endDate.oninput = () => { window.end_date = endDate.value || null; if (endDate.value) endDate.classList.remove("validation-error"); scheduleSave(); };
        timeInput.oninput = () => { window.test_time = timeInput.value; scheduleSave(); };
        wireSetupRule(timeInput, setupRules.time, `${label} time`);
        [startDate, endDate].forEach(input => { input.dataset.setupValidated = "true"; });
        const validateDateOrder = () => {
          startDate.max = endDate.value;
          endDate.min = startDate.value;
          const invalid = Boolean(startDate.value && endDate.value && startDate.value > endDate.value);
          const message = invalid ? `${label} start date cannot be after its end date` : "";
          startDate.setCustomValidity(message);
          endDate.setCustomValidity(message);
          showRuleState(startDate, invalid, "dateOrderInvalid");
          showRuleState(endDate, invalid, "dateOrderInvalid");
        };
        startDate.addEventListener("input", validateDateOrder);
        endDate.addEventListener("input", validateDateOrder);
        validateDateOrder();
        windows.append(panel);
      });
      scopeGrid.innerHTML = "";
      report.engagement.tested_environments.forEach(environment => {
        const panel = document.createElement("div");
        panel.className = `scope-panel ${environment}`;
        panel.innerHTML = `<h2>${environmentLabels[environment]}</h2>`;
        testTypes[report.engagement.test_type].channels.forEach(channel => {
          const label = document.createElement("label");
          label.textContent = channelLabels[channel];
          const textarea = document.createElement("textarea");
          textarea.value = report.scope_text[environment][channel];
          // Two lines to start, then grow with the target list instead of scrolling.
          textarea.rows = 2;
          const grow = () => {
            textarea.style.height = "auto";
            textarea.style.height = `${textarea.scrollHeight}px`;
          };
          textarea.oninput = () => { report.scope_text[environment][channel] = textarea.value; grow(); if ([...root.querySelectorAll("#scope-grid textarea")].some(input => input.value.split("\n").some(value => value.trim() && !value.trimStart().startsWith("#")))) root.querySelectorAll("#scope-grid textarea.validation-error").forEach(input => input.classList.remove("validation-error")); scheduleSave(); };
          if (channel === "mobile") wireSetupRule(textarea, mobileScopeRule, `${environmentLabels[environment]} Mobile scope`);
          label.append(textarea);
          panel.append(label);
          grow();
          document.fonts?.ready.then(grow);
          observeWidth(textarea, grow);
        });
        scopeGrid.append(panel);
      });
    };
    renderCoverage();
    }
    const findingBody = document.querySelector("#findings");
    if (findingBody) {
    report.vulnerabilities.forEach(finding => {
      if (finding.scope?.mode !== "custom") finding.scope.target_ids = scopeTargetIds(finding.scope);
    });
    const libraryMatches = query => library.filter(entry => entry.title.toLowerCase().includes(query.toLowerCase()) || entry.tags.join(" ").toLowerCase().includes(query.toLowerCase()));
    const locationGroups = {production:[], non_production:[]};
    report.scope_targets.forEach(target => locationGroups[target.environment]?.push(target));
    const locationLabels = {production:"Production", non_production:"Non-Production"};
    const clearValidationError = event => {
      const control = event.target;
      if (control.matches(".finding-title-cell input.validation-error") && control.value.trim()) control.classList.remove("validation-error");
      if (control.matches("select.validation-error") && control.value) control.classList.remove("validation-error");
      if (control.matches("[data-location], [data-custom-location]")) {
        const locationRow = control.closest("tr");
        const hasLocation = locationRow?.querySelector("[data-location]:checked") || [...(locationRow?.querySelectorAll("[data-custom-location]") || [])].some(input => input.value.trim());
        if (hasLocation) locationRow.querySelectorAll(".location-group.validation-error").forEach(group => group.classList.remove("validation-error"));
        requestAnimationFrame(showFindingValidationErrors);
      }
    };
    findingBody.addEventListener("input", clearValidationError);
    findingBody.addEventListener("change", clearValidationError, true);
    const labelAssessmentPlaceholders = () => {
      findingBody.querySelectorAll("tr:not(.finding-location-row)").forEach(row => {
        const title = row.querySelector(".finding-title-cell input");
        if (title) title.placeholder = "Finding Name";
        const idInput = row.querySelectorAll("input")[1];
        if (idInput) idInput.placeholder = "Vuln ID";
        const selects = row.querySelectorAll("select");
        ["Likelihood", "Impact", "Severity", "Status"].forEach((label, index) => {
          const control = selects[index];
          control?.setAttribute("aria-label", label);
          const placeholder = control?.querySelector('option[value=""]');
          if (placeholder) placeholder.textContent = label;
        });
      });
    };
    const showFindingValidationErrors = () => {
      if (findingBody.dataset.validationAttempted !== "true") return;
      findingBody.querySelectorAll("tr:not(.finding-location-row)").forEach(row => {
        row.querySelector(".finding-title-cell input")?.classList.toggle("validation-error", !row.querySelector(".finding-title-cell input").value.trim());
        row.querySelectorAll("select").forEach(control => control.classList.toggle("validation-error", !control.value));
        const locationRow = row.nextElementSibling;
        const hasLocation = locationRow?.querySelector("[data-location]:checked") || [...(locationRow?.querySelectorAll("[data-custom-location]") || [])].some(input => input.value.trim());
        locationRow?.querySelectorAll(".location-group").forEach(group => group.classList.toggle("validation-error", !hasLocation));
      });
    };
    updateFindingSummary = () => {
      const summary = document.querySelector("#finding-summary");
      const note = document.querySelector("#finding-validation-note");
      if (!summary) return;
      const counts = Object.fromEntries(severity.map(level => [level, 0]));
      report.vulnerabilities.forEach(finding => { if (counts[finding.severity] !== undefined) counts[finding.severity] += 1; });
      summary.innerHTML = `Finding Summary: ${severity.map(level => `<b class="summary-${level}">${counts[level]} ${level}</b>`).join("")}`;
      if (findingBody.dataset.validationAttempted !== "true") return;
      const incomplete = report.vulnerabilities.map(finding => {
        const missing = [];
        if (!finding.title?.trim()) missing.push("finding name");
        if (!finding.likelihood) missing.push("likelihood");
        if (!finding.impact) missing.push("impact");
        if (!finding.severity) missing.push("severity");
        if (!finding.status) missing.push("status");
        if (!scopeHasLocation(finding)) missing.push("affected location");
        return missing;
      }).filter(missing => missing.length);
      note.hidden = !incomplete.length;
      note.textContent = incomplete.length ? `${incomplete.length} finding${incomplete.length === 1 ? " is" : "s are"} incomplete: ${incomplete[0].join(", ")}.` : "";
    };
    const evidenceIdsIn = finding => new Set((finding.contents || []).flatMap(content => content.fragments || []).filter(fragment => fragment.evidence_id).map(fragment => fragment.evidence_id));
    // Losing an environment's last location strands that environment's evidence, so confirm before dropping it.
    const settleScopeChange = (finding, previousScope) => {
      const remaining = affectedEnvironments(finding);
      const lost = scopeEnvironments(previousScope).filter(environment => !remaining.includes(environment));
      if (!lost.length) return true;
      const stranded = lost.filter(environment => imagesForEnvironment(finding, environment).some(image => image.evidence_id || image.caption?.trim()));
      if (stranded.length) {
        const names = stranded.map(environmentName).join(" and ");
        const question = `Remove the ${names} evidence from this finding?\n\nThis finding no longer has a ${names} affected location, so its ${names} screenshots and captions cannot appear in the report.\n\nOK - remove that evidence\nCancel - keep the affected location`;
        if (!window.confirm(question)) {
          finding.scope = previousScope;
          return false;
        }
      }
      const previousEvidence = evidenceIdsIn(finding);
      lost.forEach(environment => finding.contents.forEach(content => {
        content.fragments = (content.fragments || []).filter(fragment => !(fragment.type === "image" && fragment.environment === environment));
      }));
      dropUnreferencedEvidence(previousEvidence);
      syncEvidenceImageSlots(finding);
      return true;
    };
    const dropUnreferencedEvidence = previousIds => {
      if (!report.evidence || !previousIds.size) return;
      const stillUsed = new Set(report.vulnerabilities.flatMap(candidate => [...evidenceIdsIn(candidate)]));
      previousIds.forEach(evidenceId => { if (!stillUsed.has(evidenceId)) delete report.evidence[evidenceId]; });
    };
    // Pulling in a library entry swaps the whole body, so tester work in that finding cannot survive.
    const replaceFromLibrary = (finding, entry, previousTitle) => {
      const warning = `Replace this finding with the library version?\n\n"${entry.title}" is saved in the vulnerability library.\n\nUsing it will erase everything written for this finding on the Content page, including any screenshots that were uploaded.\n\nOK - use the library version\nCancel - keep the current content and finding name`;
      if (!window.confirm(warning)) {
        finding.title = previousTitle ?? finding.title;
        syncConclusion(finding);
        renderFindings();
        scheduleSave();
        return false;
      }
      const previousEvidence = evidenceIdsIn(finding);
      applyLibraryEntry(finding, entry);
      dropUnreferencedEvidence(previousEvidence);
      return true;
    };
    const applyLibraryEntry = (finding, entry) => {
      Object.assign(finding, {title:entry.title, likelihood:entry.default_likelihood, impact:entry.default_impact, severity:entry.default_severity || "informational", library_ref:{library_id:entry.library_id, source_id:entry.source_id, inserted_at:new Date().toISOString()}, contents:JSON.parse(JSON.stringify(entry.contents || []))});
      finding.contents.forEach(content => content.fragments.forEach(fragment => { fragment.frag_id = id("f"); }));
      provision(finding);
    };
    const enhanceFindingRows = () => {
      const targetById = new Map(report.scope_targets.map(target => [target.target_id, target]));
      findingBody.querySelectorAll("tr:not(.finding-location-row)").forEach((row, index) => {
        if (row.dataset.enhanced) return;
        row.dataset.enhanced = "true";
        const finding = report.vulnerabilities[index];
        const locationRow = row.nextElementSibling;
        const locationHeading = locationRow.querySelector(".finding-location > strong");
        locationHeading.textContent = "Affected Locations";
        const locationHeadingRow = document.createElement("div");
        locationHeadingRow.className = "location-heading";
        const locationNotice = document.createElement("span");
        locationNotice.textContent = "Added or modified locations do not affect the report scope.";
        locationHeading.replaceWith(locationHeadingRow);
        locationHeadingRow.append(locationHeading, locationNotice);
        const toggle = document.createElement("button");
        toggle.className = "finding-fold-toggle";
        toggle.type = "button";
        toggle.title = "Show affected locations";
        row.querySelector(".finding-title-cell").prepend(toggle);
        const setExpanded = expanded => {
          row.classList.toggle("finding-expanded", expanded);
          locationRow.hidden = !expanded;
          toggle.setAttribute("aria-expanded", String(expanded));
          toggle.title = expanded ? "Hide affected locations" : "Show affected locations";
          if (expanded) expandedFindingIds.add(finding.uid);
          else expandedFindingIds.delete(finding.uid);
        };
        toggle.onclick = () => setExpanded(!row.classList.contains("finding-expanded"));
        setExpanded(expandedFindingIds.has(finding.uid) || index === 0 && !expandedFindingIds.size);
        const titleInput = row.querySelector(".finding-title-cell input");
        wireLibraryCombobox(titleInput, row.querySelector(".row-library-results"));
        if (titleInput.value.trim()) {
          const titleDisplay = document.createElement("button");
          titleDisplay.className = "finding-title-display";
          titleDisplay.type = "button";
          titleDisplay.setAttribute("aria-label", "Edit finding name");
          titleDisplay.innerHTML = "<span></span>";
          const titleText = titleDisplay.querySelector("span");
          const setEditing = editing => {
            titleInput.hidden = !editing;
            titleText.hidden = editing;
            if (editing) titleInput.focus();
            else titleText.textContent = titleInput.value;
          };
          titleText.textContent = titleInput.value;
          titleDisplay.addEventListener("click", () => setEditing(true));
          titleInput.addEventListener("input", () => { titleText.textContent = titleInput.value; });
          titleInput.addEventListener("blur", () => { setEditing(false); scheduleSave(); });
          titleInput.insertAdjacentElement("beforebegin", titleDisplay);
          setEditing(false);
        }
        const idInput = row.querySelector("td:nth-child(5) input");
        idInput.inputMode = "numeric";
        idInput.pattern = "[0-9]*";
        idInput.addEventListener("input", event => { event.target.value = event.target.value.replace(/\D/g, "").slice(0, 5); }, true);
        if (idInput.value.trim()) {
          const idDisplay = document.createElement("button");
          idDisplay.className = "finding-id-display";
          idDisplay.type = "button";
          idDisplay.setAttribute("aria-label", "Edit vulnerability ID");
          idDisplay.textContent = idInput.value;
          const setIdEditing = editing => {
            idInput.hidden = !editing;
            idDisplay.hidden = editing;
            if (editing) idInput.focus();
            else idDisplay.textContent = idInput.value;
          };
          idDisplay.addEventListener("click", () => setIdEditing(true));
          idInput.addEventListener("input", () => { idDisplay.textContent = idInput.value; });
          idInput.addEventListener("blur", () => {
            if (idInput.value.trim()) setIdEditing(false);
            else renderFindings();
            scheduleSave();
          });
          idInput.insertAdjacentElement("beforebegin", idDisplay);
          setIdEditing(false);
        } else {
          idInput.addEventListener("blur", () => { if (idInput.value.trim()) renderFindings(); });
        }
        row.querySelectorAll("select").forEach((control, controlIndex) => {
          if (controlIndex > 2) return;
          const setBadge = () => {
            severity.forEach(level => control.classList.remove(`assessment-${level}`));
            if (severity.includes(control.value)) control.classList.add(`assessment-${control.value}`);
          };
          setBadge();
          control.addEventListener("change", setBadge);
        });
        locationRow.querySelectorAll(".location-group").forEach(group => {
          const checklist = group.querySelector(".location-checklist");
          const selectAllInput = group.querySelector("input[data-select-all]");
          if (selectAllInput) {
            const locationOptions = [...group.querySelectorAll("[data-location]")];
            const allSelected = locationOptions.length && locationOptions.every(option => option.checked);
            const selectAllButton = document.createElement("button");
            selectAllButton.type = "button";
            selectAllButton.className = `select-all${allSelected ? " is-selected" : ""}`;
            selectAllButton.textContent = allSelected ? "Deselect all" : "Select all";
            selectAllButton.onclick = () => { locationOptions.forEach(option => { option.checked = !allSelected; }); locationOptions[0]?.dispatchEvent(new Event("change", {bubbles:true})); };
            selectAllInput.closest("label").replaceWith(selectAllButton);
          }
          const grouped = new Map();
          checklist.querySelectorAll(".location-option:not(.custom-location)").forEach(option => {
            const channel = targetById.get(option.querySelector("[data-location]")?.value)?.channel;
            if (!channel) return;
            if (!grouped.has(channel)) {
              const section = document.createElement("div");
              section.className = "location-channel";
              section.innerHTML = `<b>${channel.toUpperCase()}</b>`;
              grouped.set(channel, section);
              checklist.append(section);
            }
            grouped.get(channel).append(option);
          });
          locationRow.querySelectorAll(".location-preview").forEach(preview => {
            const checkbox = preview.closest(".location-option")?.querySelector("[data-location]");
            preview.addEventListener("click", () => checkbox?.click());
          });
          checklist.querySelectorAll(".custom-location").forEach(option => option.remove());
          group.querySelector(".add-location")?.remove();
          const environment = group.dataset.locationGroup;
          const customEditor = document.createElement("label");
          const customInputWrapper = document.createElement("div");
          const customGutter = document.createElement("div");
          const customInput = document.createElement("textarea");
          const customMeasure = document.createElement("div");
          customEditor.className = "location-lines-editor";
          customEditor.append(document.createTextNode("Additional affected endpoints"));
          customInputWrapper.className = "location-lines-input";
          customGutter.className = "location-lines-gutter";
          customGutter.setAttribute("aria-hidden", "true");
          customInput.className = "location-lines-textarea";
          customInput.dataset.customLocation = environment;
          customInput.rows = 1;
          customInput.placeholder = "One endpoint per line";
          customInput.setAttribute("aria-label", `${locationLabels[environment]} affected endpoints`);
          customInput.value = (finding.scope.custom_locations?.[environment] || []).join("\n");
          customMeasure.className = "location-lines-measure";
          customInputWrapper.append(customGutter, customInput, customMeasure);
          const renderCustomGutter = () => renderLineMarkers(customInput, customGutter, customMeasure, line => line.trim() ? "\u2022" : "", "affected-endpoint-marker");
          const resizeCustomLocations = () => {
            customInput.style.height = "auto";
            customInput.style.height = `${Math.max(28, customInput.scrollHeight)}px`;
            renderCustomGutter();
          };
          customInput.oninput = () => {
            const values = customInput.value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
            finding.scope.custom_locations ||= {};
            if (values.length) finding.scope.custom_locations[environment] = values;
            else delete finding.scope.custom_locations[environment];
            resizeCustomLocations();
            scheduleSave();
          };
          let customInputWidth = 0;
          new ResizeObserver(() => {
            if (customInput.clientWidth !== customInputWidth) {
              customInputWidth = customInput.clientWidth;
              requestAnimationFrame(resizeCustomLocations);
            }
          }).observe(customInput);
          customEditor.append(customInputWrapper);
          group.append(customEditor);
          requestAnimationFrame(resizeCustomLocations);
        });
        locationRow.querySelectorAll("input.location-value").forEach(input => {
          const textarea = document.createElement("textarea");
          [...input.attributes].forEach(attribute => textarea.setAttribute(attribute.name, attribute.value));
          textarea.rows = 1;
          textarea.value = input.value;
          textarea.oninput = () => {
            if (textarea.dataset.locationValue) {
              finding.scope.location_values ||= {};
              finding.scope.location_values[textarea.dataset.locationValue] = textarea.value;
            } else {
              finding.scope.custom_locations ||= {};
              const values = finding.scope.custom_locations[textarea.dataset.customLocation] ||= [];
              values[Number(textarea.dataset.customIndex)] = textarea.value;
            }
            scheduleSave();
          };
          input.replaceWith(textarea);
        });
        locationRow.querySelectorAll("textarea.location-value").forEach(textarea => {
          const resize = () => { textarea.style.height = "auto"; textarea.style.height = `${textarea.scrollHeight}px`; };
          textarea.addEventListener("input", resize);
          resize();
        });
      });
    };
    const renderFindings = () => { findingBody.innerHTML = ""; report.vulnerabilities.forEach((finding, index) => { const row = document.createElement("tr"); const selectedTargets = finding.scope.mode === "custom" ? finding.scope.target_ids : []; const locationValues = finding.scope.location_values || {}; const customLocations = finding.scope.custom_locations || {}; const locationControls = Object.entries(locationGroups).filter(([, targets]) => targets.length).map(([environment, targets]) => `<fieldset class="location-group" data-location-group="${environment}"><legend>${locationLabels[environment]}</legend>${targets.length > 1 ? `<label class="select-all"><input type="checkbox" data-select-all="${environment}" ${targets.every(target => selectedTargets.includes(target.target_id)) ? "checked" : ""}>Select all</label>` : ""}<div class="location-checklist">${targets.map(target => `<div class="location-option"><label class="location-toggle"><input type="checkbox" data-location="${environment}" value="${target.target_id}" aria-label="Select ${escape(target.value)}" ${selectedTargets.includes(target.target_id) ? "checked" : ""}></label>${selectedTargets.includes(target.target_id) ? `<input class="location-value" data-location-value="${target.target_id}" value="${escape(locationValues[target.target_id] ?? target.value)}" aria-label="Location value for ${escape(target.value)}">` : `<span class="location-preview">${escape(target.value)}</span>`}</div>`).join("")}${(customLocations[environment] || []).map((value, customIndex) => `<div class="location-option custom-location"><button class="remove-location" type="button" data-remove-location="${environment}" data-custom-index="${customIndex}" aria-label="Remove custom ${locationLabels[environment]} location" title="Remove location">x</button><input class="location-value" data-custom-location="${environment}" data-custom-index="${customIndex}" value="${escape(value)}" aria-label="Custom ${locationLabels[environment]} location"></div>`).join("")}</div><button class="subtle add-location" type="button" data-add-location="${environment}">Add location</button></fieldset>`).join("") || "<span class=\"muted\">Add targets in setup.</span>"; row.innerHTML = `<td class="finding-title-cell"><input value="${escape(finding.title)}" role="combobox" aria-autocomplete="list" aria-expanded="false" autocomplete="off" placeholder="Search or select a vulnerability"><div class="row-library-results" role="listbox"></div></td><td>${select(severity, finding.likelihood, true)}</td><td>${select(severity, finding.impact, true)}</td><td>${select(severity, finding.severity)}</td><td><input value="${escape(finding.display_id || "")}" inputmode="numeric" maxlength="5" pattern="[0-9]*" autocomplete="off"></td><td>${select(statuses.map(x=>x[0]), finding.status)}</td><td><button class="danger" type="button">Delete</button></td>`; const locationRow = document.createElement("tr"); locationRow.className = "finding-location-row"; locationRow.innerHTML = `<td colspan="7"><div class="finding-location"><strong>Location</strong><div class="location-controls">${locationControls}</div></div></td>`; const controls = row.querySelectorAll("input,select"); const titleInput = controls[0]; const rowResults = row.querySelector(".row-library-results"); const clearResults = () => { rowResults.innerHTML = ""; titleInput.setAttribute("aria-expanded", "false"); };
      let titleBeforeEdit = finding.title || "";
      const renderRowResults = () => { const matches = libraryMatches(titleInput.value); rowResults.innerHTML = matches.map(entry => libraryOptionMarkup(entry)).join(""); rowResults.style.width = `${document.querySelector("#library-search").getBoundingClientRect().width}px`; const requiredHeight = Math.min(rowResults.scrollHeight, 300) + 8; rowResults.classList.toggle("opens-up", window.innerHeight - titleInput.getBoundingClientRect().bottom < requiredHeight); titleInput.setAttribute("aria-expanded", String(matches.length > 0)); rowResults.querySelectorAll("[data-id]").forEach(item => item.onclick = () => { const entry = library.find(candidate => candidate.library_id === item.dataset.id); if (!entry || finding.library_ref?.library_id === entry.library_id) { clearResults(); return; } if (replaceFromLibrary(finding, entry, titleBeforeEdit)) { renderFindings(); scheduleSave(); } }); };
      titleInput.oninput = event => { finding.title = event.target.value; syncConclusion(finding); renderRowResults(); scheduleSave(); }; titleInput.onfocus = () => { titleBeforeEdit = finding.title || ""; renderRowResults(); }; titleInput.onkeydown = event => { if (event.key === "Escape") clearResults(); };
      // A committed title that names a library entry pulls that entry in; any other title is just a rename.
      titleInput.onchange = () => {
        const typed = titleInput.value.trim().toLowerCase();
        const entry = library.find(candidate => candidate.title.trim().toLowerCase() === typed);
        if (!entry || finding.library_ref?.library_id === entry.library_id) return;
        if (replaceFromLibrary(finding, entry, titleBeforeEdit)) { renderFindings(); scheduleSave(); }
      };
      titleInput.onblur = () => setTimeout(clearResults, 150);
      controls[1].onchange = event => { finding.likelihood = event.target.value || null; scheduleSave(); };
      controls[2].onchange = event => { finding.impact = event.target.value || null; scheduleSave(); };
      controls[3].onchange = event => { finding.severity = event.target.value; scheduleSave(); };
      controls[4].oninput = event => {
        const field = event.target;
        const digits = field.value.replace(/\D/g, "").slice(0, 5);
        if (field.value !== digits) {
          const caret = Math.max(0, (field.selectionStart ?? digits.length) - (field.value.length - digits.length));
          field.value = digits;
          field.setSelectionRange(caret, caret);
        }
        finding.display_id = digits || null;
        scheduleSave();
      };
      controls[5].onchange = event => {
        const nextStatus = event.target.value;
        const nextTypes = nextStatus === "open_new" ? ["description", "recommended_remediation", "proof_of_concept"] : ["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"];
        const discarded = finding.contents.filter(content => !nextTypes.includes(content.type)).map(content => optionLabel(content.type));
        const replacesRemediation = nextStatus === "resolved" && finding.status !== "resolved";
        if ((discarded.length || replacesRemediation) && !window.confirm(`Changing status will ${discarded.length ? `discard ${discarded.join(", ")}` : "replace the recommended remediation"}. Continue?`)) {
          event.target.value = finding.status;
          return;
        }
        finding.status = nextStatus;
        provision(finding);
        scheduleSave();
      };
      const updateLocations = () => {
        const targetIds = [...locationRow.querySelectorAll("[data-location]:checked")].map(input => input.value);
        const values = {...(finding.scope.location_values || {})};
        targetIds.forEach(targetId => { if (values[targetId] === undefined) values[targetId] = report.scope_targets.find(target => target.target_id === targetId).value; });
        Object.keys(values).forEach(targetId => { if (!targetIds.includes(targetId)) delete values[targetId]; });
        const custom = {};
        locationRow.querySelectorAll("[data-custom-location]").forEach(input => { const environment = input.dataset.customLocation; const values = input.value.split(/\r?\n/).map(value => value.trim()).filter(Boolean); if (values.length) (custom[environment] ||= []).push(...values); });
        locationRow.querySelectorAll("[data-select-all]").forEach(control => { const options = locationRow.querySelectorAll(`[data-location="${control.dataset.selectAll}"]`); control.checked = [...options].every(option => option.checked); });
        const previousScope = finding.scope;
        finding.scope = {mode:"custom", target_ids:targetIds, location_values:values, custom_locations:custom};
        settleScopeChange(finding, previousScope);
        renderFindings();
        scheduleSave();
      };
      locationRow.querySelectorAll("[data-location]").forEach(control => control.onchange = updateLocations);
      locationRow.querySelectorAll("[data-location-value]").forEach(input => input.oninput = () => { finding.scope.location_values ||= {}; finding.scope.location_values[input.dataset.locationValue] = input.value; scheduleSave(); });
      locationRow.querySelectorAll("[data-custom-location]").forEach(input => {
        input.onfocus = () => { input.dataset.scopeBeforeEdit = JSON.stringify(finding.scope); };
        input.oninput = () => { finding.scope.custom_locations ||= {}; const values = finding.scope.custom_locations[input.dataset.customLocation] ||= []; values[Number(input.dataset.customIndex)] = input.value; scheduleSave(); };
        // Clearing the last custom location for an environment drops it, so settle on commit rather than per keystroke.
        input.onchange = () => {
          const snapshot = input.dataset.scopeBeforeEdit;
          if (!snapshot) return;
          if (!settleScopeChange(finding, JSON.parse(snapshot))) { renderFindings(); return; }
          scheduleSave();
        };
      });
      locationRow.querySelectorAll("[data-add-location]").forEach(button => button.onclick = () => { const environment = button.dataset.addLocation; finding.scope.custom_locations ||= {}; (finding.scope.custom_locations[environment] ||= []).push(""); renderFindings(); locationRow.querySelector(`[data-custom-location="${environment}"]:last-child`)?.focus(); scheduleSave(); });
      locationRow.querySelectorAll("[data-remove-location]").forEach(button => button.onclick = () => {
        const previousScope = JSON.parse(JSON.stringify(finding.scope));
        const values = finding.scope.custom_locations?.[button.dataset.removeLocation] || [];
        values.splice(Number(button.dataset.customIndex), 1);
        settleScopeChange(finding, previousScope);
        renderFindings();
        scheduleSave();
      });
      locationRow.querySelectorAll("[data-select-all]").forEach(control => control.onchange = () => { locationRow.querySelectorAll(`[data-location="${control.dataset.selectAll}"]`).forEach(option => { option.checked = control.checked; }); updateLocations(); });
      row.querySelector("button").onclick = () => { report.vulnerabilities.splice(index,1); renderFindings(); scheduleSave(); };
      findingBody.append(row, locationRow);
    });
  };
    renderFindings();
    enhanceFindingRows();
    labelAssessmentPlaceholders();
    updateFindingSummary();
    new MutationObserver(() => { enhanceFindingRows(); labelAssessmentPlaceholders(); showFindingValidationErrors(); updateFindingSummary(); }).observe(findingBody, {childList:true});
    const addFinding = () => { report.vulnerabilities.push({uid:id("v"),title:"",severity:null,status:"open_new",scope:{mode:"custom",target_ids:[],location_values:{},custom_locations:{}},contents:[]}); renderFindings(); scheduleSave(); };
    document.querySelector("#add-finding").onclick = addFinding;
    const emptyAdd = document.querySelector("#empty-add-finding");
    if (emptyAdd) emptyAdd.onclick = addFinding;
    const results = document.querySelector("#library-results");
    const search = document.querySelector("#search");
    wireLibraryCombobox(search, results);
    const renderLibraryResults = () => {
      const query = search.value.toLowerCase();
      const matches = libraryMatches(query);
      results.innerHTML = matches.map(entry => libraryOptionMarkup(entry, true)).join("");
      search.setAttribute("aria-expanded", String(matches.length > 0));
      results.querySelectorAll("[data-id]").forEach(item => item.onclick = async () => {
        try {
          setSaveState(SAVE_STATES.SAVING, "Adding...");
          if (!(await save("Adding..."))) return;
          const response = await fetch(`/reports/${reportId}/library/${item.dataset.id}`, {method:"POST", headers:{"X-Report-Saved-At":report.saved_at}});
          if (!response.ok) throw await diagnostics.fromResponse(response, "insert_library", "Unable to add finding");
          const mutation = await response.json();
          applyServerRevision(mutation.saved_at);
          const finding = mutation.finding;
          report.vulnerabilities.push(finding);
          results.innerHTML = "";
          search.value = "";
          search.setAttribute("aria-expanded", "false");
          renderFindings();
          const addedRow = findingBody.lastElementChild;
          addedRow?.scrollIntoView({behavior:"smooth", block:"center"});
          addedRow?.querySelector("input")?.focus();
          scheduleSave();
          await save();
        } catch (error) {
          if (error.status === 409) markSaveConflict(error, "insert_library");
          else showOperationError(error, "insert_library", "Unable to add finding");
        }
      });
    };
    search.oninput = renderLibraryResults;
    search.onfocus = renderLibraryResults;
    search.onkeydown = event => {
      if (event.key === "Escape") {
        results.innerHTML = "";
        search.setAttribute("aria-expanded", "false");
      }
    };
    search.onblur = () => setTimeout(() => { results.innerHTML = ""; search.setAttribute("aria-expanded", "false"); }, 150);
    }
    const validateSetupPage = reveal => {
      if (!validateSetupInputs(reveal)) {
        if (reveal) {
          setSaveState(SAVE_STATES.UNSAVED, "Correct invalid Setup fields");
        }
        return false;
      }
      const requiredMetadata = [root.querySelector('[data-path="engagement.segment"]'), root.querySelector('[data-path="engagement.app_name"]'), root.querySelector('[data-path="engagement.report_type"]'), root.querySelector('[data-path="engagement.tester"]')];
      const identityInputs = [root.querySelector('[data-path="engagement.ci_number"]'), root.querySelector('[data-path="engagement.bsn_number"]')];
      const requiredDates = [...root.querySelectorAll('#test-windows input[type="date"]')];
      const incompleteSetup = [...requiredMetadata, ...requiredDates].filter(input => !input?.value.trim());
      const missingIdentity = !identityInputs.some(input => input?.value.trim());
      const missingEnvironment = !root.querySelector('#test-windows input[type="checkbox"]:checked');
      const missingScopePanels = [...root.querySelectorAll("#scope-grid .scope-panel")].filter(panel => ![...panel.querySelectorAll("textarea")].some(input => input.value.split("\n").some(value => value.trim() && !value.trimStart().startsWith("#"))));
      if (incompleteSetup.length || missingIdentity || missingEnvironment || missingScopePanels.length) {
        if (reveal) {
          const setupNotice = document.querySelector("#setup-validation-note");
          if (setupNotice) setupNotice.dataset.validationAttempted = "true";
          incompleteSetup.forEach(input => input.classList.add("validation-error"));
          identityInputs.forEach(input => input.classList.toggle("validation-error", missingIdentity));
          missingScopePanels.forEach(panel => panel.querySelectorAll("textarea").forEach(input => input.classList.add("validation-error")));
          const firstIncomplete = incompleteSetup[0] || (missingIdentity ? identityInputs[0] : null) || missingScopePanels[0]?.querySelector("textarea");
          firstIncomplete?.scrollIntoView({behavior:"smooth", block:"center"});
          firstIncomplete?.focus({preventScroll:true});
          setSaveState(SAVE_STATES.UNSAVED, missingEnvironment ? "Select at least one test environment" : incompleteSetup.length || missingIdentity ? "Complete the highlighted application details and testing dates" : "Define at least one scope target for each selected environment");
          updateSetupValidationNotice();
        }
        return false;
      }
      return true;
    };
    const validateFindingsPage = reveal => {
      const incomplete = report.vulnerabilities.map((finding, index) => ({
        index,
        title: !finding.title?.trim(),
        assessment: [finding.likelihood, finding.impact, finding.severity, finding.status].map(value => !value),
        location: !scopeHasLocation(finding)
      })).filter(finding => finding.title || finding.assessment.some(Boolean) || finding.location);
      if (!report.vulnerabilities.length || incomplete.length) {
        if (reveal) {
          findingBody.dataset.validationAttempted = "true";
          incomplete.forEach(finding => {
            const row = findingBody.children[finding.index * 2];
            row?.querySelector(".finding-title-cell input")?.classList.toggle("validation-error", finding.title);
            row?.querySelectorAll("select").forEach((control, controlIndex) => control.classList.toggle("validation-error", finding.assessment[controlIndex]));
            if (finding.location) {
              row?.nextElementSibling?.querySelectorAll(".location-group").forEach(group => group.classList.add("validation-error"));
              const toggle = row?.querySelector(".finding-fold-toggle");
              if (toggle?.getAttribute("aria-expanded") === "false") toggle.click();
            }
          });
          const firstRow = incomplete.length ? findingBody.children[incomplete[0].index * 2] : null;
          firstRow?.scrollIntoView({behavior:"smooth", block:"center"});
          if (!report.vulnerabilities.length) document.querySelector("#add-finding")?.focus({preventScroll:true});
          setSaveState(SAVE_STATES.UNSAVED, "Enter a finding name, complete the highlighted fields, and select or add a location for every finding");
          updateFindingSummary();
        }
        return false;
      }
      return true;
    };
    validateCurrentPage = root.dataset.step === "setup" ? validateSetupPage : validateFindingsPage;
    document.querySelector("#next").onclick = async event => {
      event.preventDefault();
      if (!validateCurrentPage(true)) return;
      const saved = await save();
      if (saved && document.querySelector("#save-button").dataset.saveState === SAVE_STATES.SAVED) {
        const nextPage = root.dataset.step === "setup" ? "findings" : "edit";
        window.location.assign(`/reports/${reportId}/${nextPage}`);
      }
    };
  }
  // Creates the minimum valid data structure for a requested fragment type.
  function newFragment(type) { const fragment = {frag_id:id("f"),type}; if (type === "paragraph" || type === "note") fragment.runs = []; else if (type.endsWith("list")) fragment.items = [{runs:[]}]; else if (type === "table") Object.assign(fragment,{header:[{runs:[]}],rows:[[{runs:[]}]]}); else if (type === "image") Object.assign(fragment,{evidence_id:null,caption:"",width_mm:null}); else if (type === "code_block") Object.assign(fragment,{caption:null,text:""}); else fragment.text=""; return fragment; }
  // Renders one content fragment with its type-specific editing controls.
  function renderFragment(fragment, content, rerender, finding) {
    const card = document.createElement("article"); card.className="fragment"; card.dataset.fragmentId = fragment.frag_id; card.tabIndex = -1; card.innerHTML=`<div class="fragment-head"><button class="fragment-drag-handle" type="button" draggable="true" aria-label="Drag to reorder fragment" title="Drag to reorder">::</button><span class="tag">${fragment.type.replaceAll("_"," ")}</span><button class="fragment-move-up" type="button" aria-label="Move fragment up" title="Move up">&#8593;</button><button class="fragment-move-down" type="button" aria-label="Move fragment down" title="Move down">&#8595;</button><button class="danger" type="button">Delete</button></div>`; card.querySelector(".danger").onclick=()=>{content.fragments.splice(content.fragments.indexOf(fragment),1);rerender();scheduleSave();};
    const moveFragment = offset => {
      const fromIndex = content.fragments.indexOf(fragment);
      const toIndex = fromIndex + offset;
      if (fromIndex < 0 || toIndex < 0 || toIndex >= content.fragments.length) return;
      content.fragments.splice(fromIndex, 1);
      content.fragments.splice(toIndex, 0, fragment);
      rerender();
      scheduleSave();
    };
    const moveUp = card.querySelector(".fragment-move-up");
    const moveDown = card.querySelector(".fragment-move-down");
    moveUp.disabled = content.fragments.indexOf(fragment) === 0;
    moveDown.disabled = content.fragments.indexOf(fragment) === content.fragments.length - 1;
    moveUp.onclick = () => moveFragment(-1);
    moveDown.onclick = () => moveFragment(1);
    // Reorder and drag stay out of the tab chain; the field is the tab stop.
    moveUp.tabIndex = -1;
    moveDown.tabIndex = -1;
    const dragHandle = card.querySelector(".fragment-drag-handle");
    dragHandle.tabIndex = -1;
    dragHandle.ondragstart = event => { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/plain", fragment.frag_id); card.classList.add("is-dragging"); };
    dragHandle.ondragend = () => card.classList.remove("is-dragging");
    card.ondragover = event => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; };
    card.ondrop = event => {
      event.preventDefault();
      const draggedId = event.dataTransfer.getData("text/plain");
      const fromIndex = content.fragments.findIndex(item => item.frag_id === draggedId);
      const toIndex = content.fragments.indexOf(fragment);
      if (fromIndex < 0 || fromIndex === toIndex) return;
      const [dragged] = content.fragments.splice(fromIndex, 1);
      content.fragments.splice(toIndex, 0, dragged);
      rerender();
      scheduleSave();
    };
    const changed=()=>scheduleSave();
    const fragmentPlaceholders = {paragraph: "Write the paragraph", note: "Write the note"};
    if (fragment.runs) {
      const editor = rich(fragment.runs, runs=>{fragment.runs=runs;changed();}, fragment.type !== "note", fragmentPlaceholders[fragment.type] || "Write the text");
      const toolbar = editor.querySelector(".toolbar");
      if (toolbar) card.querySelector(".fragment-head .tag").after(toolbar);
      card.append(editor);
    }
    else if (fragment.items) {
      const editor = document.createElement("div");
      const gutter = document.createElement("div");
      const input = document.createElement("textarea");
      const measure = document.createElement("div");
      const numbered = fragment.type === "numbered_list";
      editor.className = "list-text-editor";
      gutter.className = "list-gutter";
      gutter.setAttribute("aria-hidden", "true");
      input.className = "list-textarea";
      input.setAttribute("aria-label", `${numbered ? "Numbered" : "Bulleted"} list items`);
      input.placeholder = "One item per line";
      input.rows = 1;
      input.value = fragment.items.map(item => item.runs.map(run => run.text).join("").replace(/\r?\n/g, " ")).join("\n");
      measure.className = "list-line-measure";
      editor.append(gutter, input, measure);
      const renderGutter = () => {
        let itemNumber = 0;
        renderLineMarkers(input, gutter, measure, line => line.trim() ? numbered ? `${++itemNumber}.` : "\u2022" : "", "list-marker");
      };
      const resize = () => {
        input.style.height = "auto";
        input.style.height = `${Math.max(34, input.scrollHeight)}px`;
        renderGutter();
      };
      input.oninput = () => {
        const lines = input.value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
        fragment.items = (lines.length ? lines : [""]).map(text => ({runs:text ? [{text}] : []}));
        resize();
        changed();
      };
      let observedWidth = 0;
      new ResizeObserver(() => {
        if (input.clientWidth !== observedWidth) {
          observedWidth = input.clientWidth;
          requestAnimationFrame(resize);
        } else {
          renderGutter();
        }
      }).observe(input);
      card.append(editor);
      requestAnimationFrame(resize);
    }
    else if (fragment.type === "table") {
      const columnCount = Math.max(fragment.header.length, ...fragment.rows.map(row => row.length), 1);
      while (fragment.header.length < columnCount) fragment.header.push({runs:[]});
      fragment.rows.forEach(row => { while (row.length < columnCount) row.push({runs:[]}); });
      const value = cell => cell.runs.map(run => run.text).join("");
      const resizeTableRow = row => {
        const inputs = [...row.querySelectorAll(".table-cell-input")];
        inputs.forEach(input => { input.style.height = "auto"; });
        const height = Math.max(37, ...inputs.map(input => input.scrollHeight));
        inputs.forEach(input => { input.style.height = `${height}px`; });
      };
      const cellInput = (cell, placeholder) => {
        const input = document.createElement("textarea");
        input.className = "table-cell-input";
        input.value = value(cell);
        input.placeholder = placeholder;
        input.rows = 1;
        const fitToText = () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`; };
        fitToText();
        document.fonts?.ready.then(fitToText);
        input.oninput = () => { cell.runs = input.value ? [{text:input.value}] : []; resizeTableRow(input.closest("tr")); changed(); };
        return input;
      };
      const table = document.createElement("table");
      table.className = "table-fragment";
      const header = document.createElement("thead");
      const headerRow = document.createElement("tr");
      fragment.header.forEach((cell, index) => { const headerCell = document.createElement("th"); headerCell.append(cellInput(cell, `Header ${index + 1}`)); headerRow.append(headerCell); });
      const actionHeader = document.createElement("th");
      actionHeader.className = "table-row-action";
      actionHeader.setAttribute("aria-label", "Row actions");
      headerRow.append(actionHeader);
      header.append(headerRow);
      table.append(header);
      const body = document.createElement("tbody");
      fragment.rows.forEach((row, rowIndex) => {
        const bodyRow = document.createElement("tr");
        row.forEach((cell, columnIndex) => { const bodyCell = document.createElement("td"); bodyCell.append(cellInput(cell, `Row ${rowIndex + 1}, column ${columnIndex + 1}`)); bodyRow.append(bodyCell); });
        const actionCell = document.createElement("td");
        actionCell.className = "table-row-action";
        const removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.className = "remove-table-row";
        removeButton.textContent = "x";
        removeButton.title = "Remove row";
        removeButton.setAttribute("aria-label", `Remove row ${rowIndex + 1}`);
        removeButton.disabled = fragment.rows.length === 1;
        removeButton.onclick = () => { fragment.rows.splice(rowIndex, 1); rerender(); changed(); };
        actionCell.append(removeButton);
        bodyRow.append(actionCell);
        body.append(bodyRow);
      });
      table.append(body);
      const controls = document.createElement("div");
      controls.className = "table-controls";
      const addRow = document.createElement("button");
      addRow.type = "button";
      addRow.textContent = "Add row";
      addRow.onclick = () => { fragment.rows.push(Array.from({length:columnCount}, () => ({runs:[]}))); rerender(); changed(); };
      const addColumn = document.createElement("button");
      addColumn.type = "button";
      addColumn.textContent = "Add column";
      addColumn.onclick = () => { fragment.header.push({runs:[]}); fragment.rows.forEach(row => row.push({runs:[]})); rerender(); changed(); };
      const removeColumn = document.createElement("select");
      removeColumn.className = "table-remove-select";
      removeColumn.setAttribute("aria-label", "Remove table column");
      removeColumn.disabled = columnCount === 1;
      removeColumn.innerHTML = `<option value="">Remove column...</option>${fragment.header.map((cell, index) => `<option value="${index}">Column ${index + 1}</option>`).join("")}`;
      removeColumn.onchange = () => {
        if (removeColumn.value === "") return;
        const columnIndex = Number(removeColumn.value);
        fragment.header.splice(columnIndex, 1);
        fragment.rows.forEach(row => row.splice(columnIndex, 1));
        rerender();
        changed();
      };
      controls.append(addRow, addColumn, removeColumn);
      card.append(table, controls);
      requestAnimationFrame(() => {
        table.querySelectorAll("tr").forEach(resizeTableRow);
      });
    }
    else if (fragment.type === "image") {
      const upload = document.createElement("input");
      upload.type = "file";
      upload.accept = "image/*";
      upload.id = `${fragment.frag_id}-upload`;
      upload.hidden = true;
      const caption = document.createElement("input");
      caption.className = "evidence-caption";
      caption.value = fragment.caption || "";
      caption.placeholder = "Evidence caption required";
      caption.oninput = () => { fragment.caption = caption.value; changed(); };
      const evidence = report.evidence?.[fragment.evidence_id];
      const evidenceCard = document.createElement("div");
      evidenceCard.className = `evidence-card${evidence ? " has-evidence" : ""}`;
      const previewArea = document.createElement(evidence ? "button" : "label");
      previewArea.className = "evidence-preview";
      if (evidence) {
        previewArea.type = "button";
        previewArea.title = "Open image";
        previewArea.setAttribute("aria-label", "Open evidence image");
      } else {
        previewArea.htmlFor = upload.id;
        previewArea.innerHTML = '<span aria-hidden="true">+</span><b>Add image</b><small>PNG, JPG, or GIF</small>';
      }
      const details = document.createElement("div");
      details.className = "evidence-details";
      const imageEnvironments = affectedEnvironments(finding);
      const environmentLabel = document.createElement("label");
      environmentLabel.textContent = "Environment";
      if (imageEnvironments.length === 1) {
        fragment.environment = imageEnvironments[0];
        const environmentValue = document.createElement("span");
        environmentValue.className = "evidence-environment-value";
        environmentValue.textContent = imageEnvironments[0] === "production" ? "Production" : "Non-Production";
        environmentLabel.append(environmentValue);
      } else {
        if (!imageEnvironments.includes(fragment.environment)) fragment.environment = imageEnvironments[0] || null;
        const environmentSelect = document.createElement("select");
        environmentSelect.className = "evidence-environment";
        environmentSelect.setAttribute("aria-label", `${contentNames[content.type]} image environment`);
        environmentSelect.innerHTML = imageEnvironments.map(environment => `<option value="${environment}" ${fragment.environment === environment ? "selected" : ""}>${environment === "production" ? "Production" : "Non-Production"}</option>`).join("");
        environmentSelect.onchange = () => { fragment.environment = environmentSelect.value; rerender(); changed(); };
        environmentLabel.append(environmentSelect);
      }
      details.append(environmentLabel);
      details.insertAdjacentHTML("beforeend", `<label>Caption</label>`);
      details.append(caption);
      const fileRow = document.createElement("div");
      fileRow.className = "evidence-file";
      if (evidence) {
        const preview = document.createElement("img");
        preview.className = "image-preview";
        preview.src = `/reports/${reportId}/evidence/${fragment.evidence_id}`;
        preview.alt = evidence.original_name || "Uploaded evidence";
        previewArea.append(preview);
        previewArea.onclick = () => {
          const dialog = document.createElement("dialog");
          dialog.className = "image-dialog";
          dialog.innerHTML = `<button class="subtle" type="button" aria-label="Close image">Close</button><img src="${preview.src}" alt="${escape(preview.alt)}">`;
          dialog.querySelector("button").onclick = () => dialog.close();
          dialog.onclick = event => { if (event.target === dialog) dialog.close(); };
          dialog.onclose = () => dialog.remove();
          document.body.append(dialog);
          dialog.showModal();
        };
        fileRow.innerHTML = `<span>${escape(evidence.original_name || "Image")}</span><small>${evidence.width_px} x ${evidence.height_px}</small>`;
      } else {
        fileRow.innerHTML = "<span>No image attached</span>";
      }
      const replace = document.createElement("label");
      replace.className = "evidence-replace";
      replace.htmlFor = upload.id;
      replace.textContent = evidence ? "Replace image" : "Choose image";
      details.append(fileRow, replace);
      upload.onchange = async () => {
        const selectedFile = upload.files?.[0];
        if (!selectedFile) return;
        const formData = new FormData();
        formData.append("file", selectedFile);
        try {
          setSaveState(SAVE_STATES.SAVING, "Uploading...");
          if (!(await save("Uploading..."))) return;
          const response = await fetch(`/reports/${reportId}/evidence`, {method:"POST", headers:{"X-Report-Saved-At":report.saved_at}, body:formData});
          if (!response.ok) throw await diagnostics.fromResponse(response, "upload_evidence", "Upload failed");
          const mutation = await response.json();
          applyServerRevision(mutation.saved_at);
          const evidenceRecord = mutation.evidence;
          report.evidence ||= {};
          report.evidence[evidenceRecord.evidence_id] = evidenceRecord;
          fragment.evidence_id = evidenceRecord.evidence_id;
          rerender();
          scheduleSave();
          await save();
        } catch (error) {
          if (error.status === 409) markSaveConflict(error, "upload_evidence");
          else showOperationError(error, "upload_evidence", "Upload failed");
        }
      };
      evidenceCard.append(previewArea, details, upload);
      card.append(evidenceCard);
    } else {
      const isCode = fragment.type === "code_block";
      const input = document.createElement(isCode ? "textarea" : "input");
      const label = isCode ? "Paste the command or response" : "Instance title, for example the login endpoint";
      input.className = isCode ? "code-block" : "instance-title-input";
      input.value = fragment.text || "";
      input.placeholder = label;
      input.setAttribute("aria-label", label);
      if (isCode) {
        input.rows = 1;
        const fit = () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`; };
        fit();
        document.fonts?.ready.then(fit);
        input.oninput = () => { fragment.text = input.value; fit(); changed(); };
      } else {
        input.oninput = () => { fragment.text = input.value; changed(); };
      }
      card.append(input);
    }
    return card;
  }
  // Renders the current multi-finding content editor and its navigation rail.
  function continuousEditor() {
    const nav = document.querySelector("#finding-nav");
    const pane = document.querySelector("#finding-editor");
    report.vulnerabilities.forEach(finding => { syncConclusion(finding); syncEvidenceImageSlots(finding); });
    let selectedFindingUid = report.vulnerabilities[0]?.uid;
    let expandedContentTypes;
    let engagementContextOpen = false;
    const libraryMatches = query => library.filter(entry => entry.title.toLowerCase().includes(query.toLowerCase()) || entry.tags.join(" ").toLowerCase().includes(query.toLowerCase()));
    const applyLibraryEntry = (finding, entry) => {
      Object.assign(finding, {title:entry.title, likelihood:entry.default_likelihood, impact:entry.default_impact, severity:entry.default_severity || "informational", library_ref:{library_id:entry.library_id, source_id:entry.source_id, inserted_at:new Date().toISOString()}, contents:JSON.parse(JSON.stringify(entry.contents || []))});
      finding.contents.forEach(content => content.fragments.forEach(fragment => { fragment.frag_id = id("f"); }));
      provision(finding);
    };
    const ordered = () => report.vulnerabilities.slice().sort((left, right) => severity.indexOf(left.severity) - severity.indexOf(right.severity) || left.title.localeCompare(right.title));
    const updateReadinessPanel = () => {
      const panel = document.querySelector("#editor-notifications");
      const count = document.querySelector("#issue-count");
      if (!panel || !count) return [];
      const hasText = runs => Array.isArray(runs) && runs.some(run => run.text?.trim());
      const placeholderPattern = /\(\s*insert[^)]*\)|insert\s+(technology|version|eol\s+date|cves|latest)\s+\w*\s*here|\[value_taken_from/i;
      const fragmentText = fragment => {
        if (fragment.runs) return fragment.runs.map(run => run.text).join("");
        if (fragment.items) return fragment.items.flatMap(item => item.runs).map(run => run.text).join(" ");
        if (fragment.type === "table") return [...fragment.header, ...fragment.rows.flat()].flatMap(cell => cell.runs).map(run => run.text).join(" ");
        return [fragment.text, fragment.caption].filter(Boolean).join(" ");
      };
      const fragmentIssues = finding => {
        // An image for an environment this finding does not affect is not the tester's to complete.
        const relevant = affectedEnvironments(finding);
        return finding.contents.flatMap(content => content.fragments.flatMap(fragment => {
        const contentLabel = contentNames[content.type];
        const issues = [];
        if (fragment.runs && !hasText(fragment.runs)) issues.push({contentLabel, fragmentLabel:optionLabel(fragment.type), message:"text is required", fragmentId:fragment.frag_id});
        if (fragment.items) {
          const itemLabel = content.type.endsWith("proof_of_concept") ? "step" : "item";
          issues.push(...fragment.items.flatMap((item, itemIndex) => hasText(item.runs) ? [] : [{contentLabel, fragmentLabel:`${itemLabel} ${itemIndex + 1}`, message:"text is required", fragmentId:fragment.frag_id}]));
        }
        if (fragment.type === "table") {
          const cells = [...fragment.header, ...fragment.rows.flat()];
          if (cells.some(cell => !hasText(cell.runs))) issues.push({contentLabel, fragmentLabel:"table", message:"every cell is required", fragmentId:fragment.frag_id});
        }
        if (fragment.type === "image" && (!fragment.environment || relevant.includes(fragment.environment))) {
          const environment = fragment.environment === "production" ? "Production" : fragment.environment === "non_production" ? "Non-Production" : "Unassigned";
          const missing = [!fragment.environment && "environment", !fragment.evidence_id && "image", !fragment.caption?.trim() && "caption"].filter(Boolean);
          if (missing.length) issues.push({contentLabel, fragmentLabel:`${environment} image`, message:`${missing.join(" and ")} required`, fragmentId:fragment.frag_id});
        }
        if (!fragment.runs && !fragment.items && fragment.type !== "table" && fragment.type !== "image" && !fragment.text?.trim()) issues.push({contentLabel, fragmentLabel:optionLabel(fragment.type), message:"text is required", fragmentId:fragment.frag_id});
        if (placeholderPattern.test(fragmentText(fragment))) issues.push({contentLabel, fragmentLabel:optionLabel(fragment.type), message:"replace placeholder text", fragmentId:fragment.frag_id, level:"warning"});
        return issues;
        }));
      };
      const issues = report.vulnerabilities.flatMap(finding => {
        const label = finding.title || "Untitled finding";
        const missing = [];
        if (!finding.title?.trim()) missing.push("finding name");
        if (![finding.likelihood, finding.impact, finding.severity, finding.status].every(Boolean)) missing.push("assessment details");
        if (!scopeHasLocation(finding)) missing.push("affected location");
        const images = finding.contents.flatMap(content => content.fragments.filter(fragment => fragment.type === "image"));
        const missingEvidence = affectedEnvironments(finding).filter(environment => !images.some(image => image.environment === environment && image.evidence_id));
        const environmentIssues = missingEvidence.map(environment => ({finding, message:`${environment === "production" ? "Production" : "Non-Production"} evidence image required`}));
        return [...(missing.length ? [{finding, message:missing.join(", ")}] : []), ...environmentIssues, ...fragmentIssues(finding).map(issue => ({finding, ...issue}))];
      });
      count.textContent = issues.length ? `${issues.length} issue${issues.length === 1 ? "" : "s"}` : "Ready";
      count.dataset.state = issues.length ? "issues" : "ready";
      const generateButton = document.querySelector("#generate-report");
      if (generateButton) {
        generateButton.disabled = Boolean(issues.length) || generateButton.dataset.busy === "true";
        generateButton.title = issues.length ? "Resolve review issues before generating" : "Generate Word report";
      }
      // One card per finding, so a finding with five gaps reads as one row rather than five.
      const groups = [];
      issues.forEach(issue => {
        const group = groups.find(candidate => candidate.finding === issue.finding);
        if (group) group.issues.push(issue);
        else groups.push({finding:issue.finding, issues:[issue]});
      });
      const renderGroup = group => `<details class="review-group" data-level="${group.issues.some(issue => (issue.level || "error") === "error") ? "error" : "warning"}" open><summary><span class="review-group-title">${escape(group.finding.title || "Untitled finding")}</span><span class="review-group-count">${group.issues.length} issue${group.issues.length === 1 ? "" : "s"}</span></summary>${group.issues.map(({finding, message, fragmentId, contentLabel, fragmentLabel, level}) => `<div class="review-item" data-level="${level || "error"}"><span class="review-icon" aria-hidden="true">!</span><div><span class="review-detail">${contentLabel ? `${escape(contentLabel)}: ${escape(fragmentLabel)} ${escape(message)}` : escape(message)}</span><button type="button" data-review-finding="${escape(finding.uid)}"${fragmentId ? ` data-review-fragment="${escape(fragmentId)}"` : ""}>Go to</button></div></div>`).join("")}</details>`;
      panel.innerHTML = issues.length
        ? groups.map(renderGroup).join("")
        : '<div class="review-empty">All existing finding details are complete.</div>';
      panel.querySelectorAll("[data-review-finding]").forEach(button => button.onclick = () => {
        const findingUid = button.dataset.reviewFinding;
        const fragmentId = button.dataset.reviewFragment;
        if (selectedFindingUid !== findingUid) {
          selectedFindingUid = findingUid;
          expandedContentTypes = undefined;
          render();
        }
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            const target = fragmentId ? pane.querySelector(`[data-fragment-id="${fragmentId}"]`) : document.getElementById(`finding-${findingUid}`);
            target?.scrollIntoView({behavior:"smooth", block:"center"});
            target?.focus?.({preventScroll:true});
          });
        });
      });
      return issues;
    };
    validateCurrentPage = reveal => {
      const issues = updateReadinessPanel();
      if (!issues.length) return true;
      if (reveal) {
        const firstIssue = document.querySelector("#editor-notifications [data-review-finding]");
        firstIssue?.click();
        firstIssue?.focus({preventScroll:true});
      }
      return false;
    };
    document.addEventListener("reportchange", updateReadinessPanel);
    const render = (focusedFindingUid) => {
      // Rebuilding the pane resets its scroll, which would throw the tester back to the top after an upload.
      const restoreScroll = pane.scrollTop;
      const findings = ordered();
      if (!findings.some(finding => finding.uid === selectedFindingUid)) {
        selectedFindingUid = findings[0]?.uid;
        expandedContentTypes = undefined;
      }
      nav.innerHTML = "";
      pane.innerHTML = "";
      if (!findings.length) {
        pane.innerHTML = "<section><h1>No findings yet</h1><p>Add a vulnerability to begin its content.</p><button class=\"add-vulnerability\" type=\"button\">Add vulnerability</button></section>";
        pane.querySelector(".add-vulnerability").onclick = () => {
          const newFinding = {uid:id("v"), title:"", severity:"informational", status:"open_new", scope:{mode:"all",target_ids:[]}, contents:[]};
          provision(newFinding);
          report.vulnerabilities.push(newFinding);
          render();
          scheduleSave();
          document.getElementById(`finding-${newFinding.uid}`)?.scrollIntoView({behavior:"smooth", block:"start"});
          document.getElementById(`finding-${newFinding.uid}`)?.querySelector(".edit-title")?.click();
        };
        return;
      }
      const navHeading = document.createElement("div");
      navHeading.className = "finding-nav-heading";
      navHeading.innerHTML = `<b>Findings (${findings.length})</b><small>Sorted by severity, then name</small>`;
      nav.append(navHeading);
      findings.forEach(finding => {
        const findingId = `finding-${finding.uid}`;
        const jump = document.createElement("button");
        jump.className = `finding-nav severity-${finding.severity || "informational"}${finding.uid === selectedFindingUid ? " active" : ""}`;
        jump.dataset.findingId = findingId;
        jump.innerHTML = `<span class="finding-nav-title">${escape(finding.title || "Untitled finding")}</span><span class="finding-nav-meta"><span>${escape(finding.display_id || "No ID")}</span><i aria-label="${escape(finding.severity || "informational")} severity"></i></span>`;
        jump.onclick = () => { selectedFindingUid = finding.uid; expandedContentTypes = undefined; render(); };
        nav.append(jump);
      });
      // Setup context travels to Content so evidence choices don't depend on memory.
      const contextLabels = {production: "Production", non_production: "Non-Production"};
      const context = document.createElement("details");
      context.className = "engagement-context";
      context.open = engagementContextOpen;
      context.ontoggle = () => { engagementContextOpen = context.open; };
      const environments = (report.engagement.tested_environments || []).filter(environment => contextLabels[environment]);
      const body = environments.map(environment => {
        const testWindow = report.engagement.test_windows?.[environment] || {};
        const dates = [testWindow.start_date, testWindow.end_date].filter(Boolean).join(" to ") || "No dates";
        const targets = report.scope_targets.filter(target => target.environment === environment).sort((left, right) => left.order - right.order);
        const list = targets.length
          ? `<ul>${targets.map(target => `<li><span>${escape(String(target.channel || "").toUpperCase())}</span>${escape(target.value)}</li>`).join("")}</ul>`
          : `<p class="engagement-context-empty">No scope targets</p>`;
        return `<div class="engagement-context-env"><b>${escape(contextLabels[environment])}</b><small>${escape(dates)} &middot; ${escape(testWindow.test_time || "Any time")}</small>${list}</div>`;
      }).join("");
      context.innerHTML = `<summary>Engagement scope</summary><div class="engagement-context-body">${body || `<p class="engagement-context-empty">No environments selected</p>`}</div>`;
      nav.append(context);
      const selectedFinding = findings.find(finding => finding.uid === selectedFindingUid);
      if (selectedFinding) [selectedFinding].forEach(finding => {
        const index = findings.indexOf(finding);
        const findingId = `finding-${finding.uid}`;
        const box = document.createElement("section");
        box.className = "finding-card";
        box.id = findingId;
        box.tabIndex = -1;
        const targetsById = new Map(report.scope_targets.map(target => [target.target_id, target]));
        const locationsByEnvironment = {production: [], non_production: []};
        scopeTargetIds(finding.scope).forEach(targetId => {
          const target = targetsById.get(targetId);
          if (target) locationsByEnvironment[target.environment].push(finding.scope.location_values?.[targetId] || target.value);
        });
        if (finding.scope?.mode === "custom") Object.entries(finding.scope?.custom_locations || {}).forEach(([environment, locations]) => locationsByEnvironment[environment]?.push(...locations.filter(value => value.trim())));
        const locationGroups = [["production", "Production"], ["non_production", "Non-Production"]]
          .filter(([environment]) => locationsByEnvironment[environment].length)
          .map(([environment, label]) => `<span><em>${label}</em><b>${locationsByEnvironment[environment].map(escape).join(", ")}</b></span>`)
          .join("");
        box.innerHTML = `<header class="finding-header"><div class="section-title finding-title"><h1>${escape(finding.title || "Untitled finding")}</h1></div><div class="finding-summary finding-assessment"><div><span>Likelihood</span><b class="summary-${escape(finding.likelihood || "informational")}">${escape(finding.likelihood || "Not set")}</b></div><div><span>Impact</span><b class="summary-${escape(finding.impact || "informational")}">${escape(finding.impact || "Not set")}</b></div><div><span>Severity</span><b class="summary-${escape(finding.severity || "informational")}">${escape(finding.severity || "Not set")}</b></div><div><span>Vuln ID</span><b class="finding-id-value">${escape(finding.display_id || "No ID")}</b></div><div class="finding-status"><span>Status</span><b>${escape(statuses.find(status => status[0] === finding.status)?.[1] || finding.status)}</b></div></div></header><div class="finding-locations"><span>Affected locations</span><div>${locationGroups || "Not set"}</div></div>`;
        const titleHeading = box.querySelector(".finding-title h1");
        const titleButton = document.createElement("button");
        titleButton.className = "edit-title";
        titleButton.type = "button";
        titleButton.title = "Edit finding name";
        titleButton.textContent = finding.title || "Untitled finding";
        titleHeading.replaceChildren(titleButton);
        titleButton.onclick = () => {
          const heading = box.querySelector(".finding-title h1");
          const titleEditor = document.createElement("div");
          titleEditor.className = "editor-title-search";
          titleEditor.innerHTML = '<input role="combobox" aria-autocomplete="list" aria-expanded="false" autocomplete="off" placeholder="Finding Name"><div class="row-library-results" role="listbox"></div>';
          const titleInput = titleEditor.querySelector("input");
          const results = titleEditor.querySelector(".row-library-results");
          wireLibraryCombobox(titleInput, results);
          titleInput.value = finding.title;
          heading.replaceWith(titleEditor);
          titleInput.focus();
          let titleCommitted = false;
          const finishTitle = () => {
            if (titleCommitted) return;
            titleCommitted = true;
            finding.title = titleInput.value.trim();
            syncConclusion(finding);
            render();
            scheduleSave();
          };
          const clearResults = () => { results.innerHTML = ""; titleInput.setAttribute("aria-expanded", "false"); };
          const renderResults = () => {
            const matches = libraryMatches(titleInput.value);
            results.innerHTML = matches.map(entry => libraryOptionMarkup(entry)).join("");
            titleInput.setAttribute("aria-expanded", String(matches.length > 0));
            results.querySelectorAll("[data-id]").forEach(item => {
              item.onmousedown = event => event.preventDefault();
              // Renaming here never replaces content; library swaps belong to the Findings page.
              item.onclick = () => {
                const entry = library.find(candidate => candidate.library_id === item.dataset.id);
                if (entry) { finding.title = entry.title; syncConclusion(finding); finishTitle(); }
              };
            });
          };
          titleInput.oninput = renderResults;
          titleInput.onfocus = renderResults;
          titleInput.onkeydown = event => { if (event.key === "Enter") finishTitle(); if (event.key === "Escape") clearResults(); };
          titleInput.onblur = () => setTimeout(finishTitle, 150);
        };
        if (expandedContentTypes === undefined) expandedContentTypes = new Set(finding.contents.map(content => content.type));
        finding.contents.forEach(content => {
          const block = document.createElement("div");
          const isExpanded = expandedContentTypes.has(content.type);
          block.className = `content-block${isExpanded ? " is-expanded" : ""}`;
          const heading = document.createElement("button");
          heading.className = "content-toggle";
          heading.type = "button";
          heading.setAttribute("aria-expanded", String(isExpanded));
          heading.innerHTML = `<span>${contentNames[content.type]}</span><small>${content.fragments.length} fragment${content.fragments.length === 1 ? "" : "s"}</small>`;
          heading.onclick = () => { if (isExpanded) expandedContentTypes.delete(content.type); else expandedContentTypes.add(content.type); render(finding.uid); };
          block.append(heading);
          if (!isExpanded) { box.append(block); return; }
          if (content.type === "in_conclusion") {
            const guidance = document.createElement("p");
            guidance.className = "content-guidance";
            guidance.textContent = "Include a brief justification or explanation.";
            block.append(guidance);
          }
          const appendFragmentMenu = () => {
            const menu = document.createElement("select");
            menu.className = "add-fragment";
            menu.setAttribute("aria-label", `Add fragment to ${contentNames[content.type]}`);
            menu.innerHTML = `<option value="">+ Add a fragment</option>${allowed[content.type].map(type => `<option value="${type}">${type.replaceAll("_", " ")}</option>`).join("")}`;
            menu.onchange = () => {
              if (!menu.value) return;
              const fragment = newFragment(menu.value);
              if (fragment.type === "image") {
                const environments = affectedEnvironments(finding);
                const existing = finding.contents.flatMap(item => item.fragments.filter(candidate => candidate.type === "image"));
                fragment.environment = environments.find(environment => !existing.some(image => image.environment === environment)) || environments[0] || null;
              }
              content.fragments.push(fragment);
              render();
              scheduleSave();
            };
            block.append(menu);
          };
          if (finding.status === "resolved" && content.type === "recommended_remediation") {
            block.append(document.createTextNode("Locked for resolved findings."));
          } else {
            content.fragments.forEach(fragment => block.append(renderFragment(fragment, content, render, finding)));
            appendFragmentMenu();
          }
          box.append(block);
        });
        pane.append(box);
      });
      updateReadinessPanel();
      if (focusedFindingUid) {
        requestAnimationFrame(() => { const focusedFinding = document.getElementById(`finding-${focusedFindingUid}`); focusedFinding?.scrollIntoView({behavior:"smooth", block:"start"}); focusedFinding?.focus({preventScroll:true}); });
      } else if (restoreScroll) {
        pane.scrollTop = restoreScroll;
      }
    };
    render();
  }
  root.id === "setup" ? setup() : continuousEditor();
  updateEngagementName(serverReport);
})();
