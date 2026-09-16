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
  // Each fact gets its own chip: the old hyphen-joined string was unreadable against an application
  // name that contains hyphens of its own.
  const updateEngagementName = (saved = report) => {
    const heading = document.querySelector(".engagement-name");
    if (!heading) return;
    const engagement = saved.engagement || {};
    const appName = engagement.app_name?.trim();
    const testType = reportTypeLabels[engagement.report_type];
    const title = document.createElement("span");
    title.className = "engagement-title";
    title.textContent = appName && testType ? appName : "Application Penetration Testing";
    heading.replaceChildren(title);
    if (!appName || !testType) return;
    [[testType, false], [engagement.segment, false], [engagement.ci_number?.trim() || engagement.bsn_number?.trim(), true]]
      .filter(([value]) => value)
      .forEach(([value, mono]) => {
        const chip = document.createElement("span");
        chip.className = mono ? "fchip fchip-mono" : "fchip";
        chip.textContent = value;
        heading.append(chip);
      });
  };
  const localDraftPrefix = `vulnreport-pending:${reportId}`;
  const recoverySelectionKey = `vulnreport-recovery:${reportId}`;
  const tabRevisionKey = `vulnreport-saved-at:${reportId}`;
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
  const legacyLocalDraftKey = `${localDraftPrefix}:${tabId}`;
  const localDraftKey = `${legacyLocalDraftKey}:${crypto.randomUUID()}`;
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
  // Twin of docx_report.generation_issues; these carry the finding, so none is ever left empty.
  const requiresFragment = ["description", "recommended_remediation", "in_conclusion"];
  // Twin of report_service.RESOLVED_REMEDIATION.
  const RESOLVED_REMEDIATION = "None, the vulnerability has been remediated.";
  // Twin of report_service.status_conclusion_runs and STATUS_CONCLUSION_PATTERN. The builder and the
  // recogniser must stay a pair: relax one and every default on disk freezes at its stored title.
  const statusConclusionRuns = (title, statusWord) => [
    {text: `The finding "${title}" is ${statusWord === "Open" ? "still " : ""}`},
    {text: statusWord, bold: true},
    {text: "."},
  ];
  const STATUS_CONCLUSION_PATTERN = /^The finding "[\s\S]*" is(?: still)? (?:Open|Resolved)\./;
  const defaultConclusionSpan = text => {
    const stripped = text.trimEnd();
    const marker = 'The finding "';
    let index = stripped.lastIndexOf(marker);
    while (index >= 0) {
      const match = stripped.slice(index).match(STATUS_CONCLUSION_PATTERN);
      if (match) return [index, index + match[0].length];
      index = index > 0 ? stripped.lastIndexOf(marker, index - 1) : -1;
    }
    return null;
  };
  const defaultConclusionStart = text => {
    const span = defaultConclusionSpan(text);
    return span && span[1] === text.trimEnd().length ? span[0] : -1;
  };
  const runsUpTo = (runs, offset) => {
    const kept = [];
    let seen = 0;
    for (const run of runs) {
      if (seen >= offset) break;
      const text = run.text.slice(0, Math.min(run.text.length, offset - seen));
      if (text) kept.push({...run, text});
      seen += run.text.length;
    }
    return kept;
  };
  const runsAfter = (runs, offset) => {
    const kept = [];
    let seen = 0;
    for (const run of runs) {
      const start = Math.max(0, offset - seen);
      if (start < run.text.length) kept.push({...run, text:run.text.slice(start)});
      seen += run.text.length;
    }
    return kept;
  };
  // The list gutter draws the markers, so a pasted "1." would render as "1. 1.". A separator is
  // required, which is what keeps "1.2.3.4 is the host" intact; roman and lettered markers are too
  // close to prose to strip, and a wrong strip deletes text silently.
  const LIST_MARKER_PREFIX = /^\s*(\d{1,3}[.)]|\(\d{1,3}\)|[-*+•–—])\s+/;
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
  // Assigned by setup(); the server rejects a scope edit that strands a finding, so the save waits for a fix.
  let strandedByScopeEdit = () => [];
  let updateFindingSummary = () => {};
  const expandedFindingIds = new Set();
  // Tells "nothing opened yet" apart from "the tester closed them all"; an empty set alone would
  // re-open the first finding every time the table is rebuilt.
  let findingFoldDefaulted = false;
  // Creates stable client-side IDs for vulnerabilities, fragments, and evidence records.
  const id = (prefix) => `${prefix}_${crypto.randomUUID().replaceAll("-", "").slice(0, 8)}`;
  // Escapes text before it is inserted into generated HTML markup.
  const escape = (value) => String(value || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const libraryOptionMarkup = (entry, includePlaceholder = false) => {
    const tags = escape((entry.tags || []).join(", "));
    const warning = includePlaceholder && entry.requires_tester_input ? " | contains placeholder text" : "";
    return `<div class="library-entry" role="option" data-id="${escape(entry.library_id)}"><b>${escape(entry.title)}</b> <small>${tags}${warning}</small></div>`;
  };
  const libraryMatches = query => library.filter(entry => entry.title.toLowerCase().includes(query.toLowerCase()) || entry.tags.join(" ").toLowerCase().includes(query.toLowerCase()));
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
      localStorage.removeItem(legacyLocalDraftKey);
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
  function rememberTabRevision(savedAt) {
    if (!savedAt) return;
    try {
      const remembered = sessionStorage.getItem(tabRevisionKey);
      if (!remembered || Date.parse(savedAt) > Date.parse(remembered)) sessionStorage.setItem(tabRevisionKey, savedAt);
    } catch (error) { showRecoveryStorageWarning(error); }
  }
  rememberTabRevision(serverReport.saved_at);
  function applyServerRevision(savedAt) {
    if (!savedAt) return;
    report.saved_at = savedAt;
    previousReport.saved_at = savedAt;
    if (activeTextTransaction) activeTextTransaction.before.saved_at = savedAt;
    rememberTabRevision(savedAt);
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
    saveRevision += 1;
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
    // Reload only once the server has the undone state, so its page gate judges what the tester now has
    // rather than the state from before the undo.
    return save().then(() => {
      window.location.reload();
      return true;
    });
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
  // Each Setup card reports its own state on the right of its header strip, the way a Content
  // section reports its fragment count.
  const setupSectionSummary = section => {
    if (section.querySelector("#test-windows")) {
      const chosen = [...section.querySelectorAll('#test-windows input[type="checkbox"]')].filter(box => box.checked).length;
      return chosen ? `${chosen} selected` : "none selected";
    }
    if (section.querySelector("#test-accounts")) {
      const rows = section.querySelectorAll("#test-accounts tr").length;
      return `${rows} account${rows === 1 ? "" : "s"}`;
    }
    if (section.querySelector(".limitations-field")) {
      return section.querySelector("textarea")?.value.trim() ? "set" : "empty";
    }
    if (section.querySelector("#scope-grid")) {
      const targets = [...section.querySelectorAll("#scope-grid textarea")]
        .flatMap(input => input.value.split("\n"))
        .filter(line => line.trim() && !line.trimStart().startsWith("#")).length;
      return `${targets} target${targets === 1 ? "" : "s"}`;
    }
    const fields = [...section.querySelectorAll(".fields input, .fields select")];
    return fields.length ? `${fields.filter(field => field.value.trim()).length} of ${fields.length}` : "";
  };
  const updateSetupSectionSummaries = () => {
    if (root.dataset.step !== "setup") return;
    root.querySelectorAll(":scope > section").forEach(section => {
      const strip = section.querySelector(":scope > .scope-heading") || section.querySelector(":scope > h2");
      if (!strip) return;
      let count = strip.querySelector(".section-count");
      if (!count) {
        count = document.createElement("small");
        count.className = "section-count";
        strip.append(count);
      }
      count.textContent = setupSectionSummary(section);
    });
  };
  root.addEventListener("input", updateSetupValidationNotice);
  root.addEventListener("change", updateSetupValidationNotice);
  root.addEventListener("input", updateSetupSectionSummaries);
  root.addEventListener("change", updateSetupSectionSummaries);
  document.addEventListener("reportchange", updateSetupSectionSummaries);
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
    // Reveals the live per-finding count too, so the sentence above stops being the only signal and
    // starts naming what is missing. setup() declares its own #findings handle long after this runs.
    const findings = document.querySelector("#findings");
    if (findings) findings.dataset.validationAttempted = "true";
  }
  const activeTextEntry = () => {
    const activeElement = document.activeElement;
    return activeElement?.matches('input:not([type="checkbox"],[type="radio"],[type="file"]), textarea, [contenteditable="true"]') ? activeElement : null;
  };
  root.addEventListener("focusout", () => {
    queueMicrotask(() => {
      if (!activeTextEntry()) {
        finalizeTextTransaction();
        // The offer refresh sits out every tick while a field has focus, so leaving one is the
        // moment a banner earned by typing can finally appear. queueReportChange writes nothing.
        queueReportChange();
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
    if (saveConflict) {
      setSaveState(SAVE_STATES.CONFLICT);
      return false;
    }
    if (saveInFlight) return saveInFlight;
    if (!pendingSave || savedRevision >= saveRevision) return true;
    if (root.dataset.step === "setup" && !validateSetupInputs(false)) {
      setSaveState(SAVE_STATES.UNSAVED, "Correct invalid Setup fields");
      return false;
    }
    const stranded = root.dataset.step === "setup" ? strandedByScopeEdit() : [];
    if (stranded.length) {
      setSaveState(SAVE_STATES.UNSAVED, `Give ${stranded.join(", ")} another affected location`);
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
  // Uploads and library inserts reach the server outside the ordinary save, so `save()` reports
  // nothing pending while one is in flight. Navigation waits on this instead of stranding it.
  let pendingMutation = null;
  function trackMutation(start) {
    const task = pendingMutation ? pendingMutation.then(start) : start();
    const settled = task.catch(() => {});
    pendingMutation = settled;
    settled.then(() => { if (pendingMutation === settled) pendingMutation = null; });
    return task;
  }
  async function waitForMutations() {
    while (pendingMutation) await pendingMutation;
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
    // Back is never gated on any page: completeness is a forward requirement, and the flush below is
    // what protects the edits. Refusing here would skip that flush entirely.
    await waitForMutations();
    if (await save()) window.location.assign(link.dataset.href);
  }));
  const undo = async () => {
    finalizeTextTransaction();
    const action = undoHistory.pop();
    if (!action) return;
    redoHistory.push(action);
    if (!await restoreHistory(action, "undo")) {
      redoHistory.pop();
      undoHistory.push(action);
      storeHistory();
    }
  };
  const redo = async () => {
    const action = redoHistory.pop();
    if (!action) return;
    undoHistory.push(action);
    if (!await restoreHistory(action, "redo")) {
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
  window.addEventListener("pageshow", event => {
    const historyRestore = event.persisted || performance.getEntriesByType("navigation")[0]?.type === "back_forward";
    if (!historyRestore || pendingSave) return;
    try {
      const latest = sessionStorage.getItem(tabRevisionKey);
      if (latest && Date.parse(latest) > Date.parse(report.saved_at)) window.location.reload();
    } catch (error) { showRecoveryStorageWarning(error); }
  });
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
  // Any tester work at all, not just paragraph text: shared by the delete guard and the proof-of-concept offer.
  const fragmentHasContent = fragment => fragmentHasText(fragment)
    || (fragment.items || []).some(item => (item.runs || []).some(run => run.text?.trim()))
    || [...(fragment.header || []), ...(fragment.rows || []).flat()].some(cell => (cell.runs || []).some(run => run.text?.trim()))
    || Boolean(fragment.text?.trim() || fragment.caption?.trim() || fragment.evidence_id);
  const evidenceIdsIn = finding => new Set((finding.contents || []).flatMap(content => content.fragments || []).filter(fragment => fragment.evidence_id).map(fragment => fragment.evidence_id));
  const dropUnreferencedEvidence = previousIds => {
    if (!report.evidence || !previousIds.size) return;
    const stillUsed = new Set(report.vulnerabilities.flatMap(candidate => [...evidenceIdsIn(candidate)]));
    previousIds.forEach(evidenceId => { if (!stillUsed.has(evidenceId)) delete report.evidence[evidenceId]; });
  };
  const conclusionText = fragment => (fragment.runs || []).map(run => run.text).join("");
  const defaultSpanIn = fragment => fragment.type === "paragraph" ? defaultConclusionSpan(conclusionText(fragment)) : null;
  const isDefaultStatusConclusion = fragment => {
    const text = conclusionText(fragment);
    const span = defaultSpanIn(fragment);
    return span && span[0] === 0 && span[1] === text.trimEnd().length;
  };
  const hasDefaultStatusConclusion = fragment => defaultSpanIn(fragment) !== null;
  function syncConclusion(vulnerability) {
    const conclusion = vulnerability.contents?.find(content => content.type === "in_conclusion");
    if (!conclusion) return;
    const status = vulnerability.status === "resolved" ? "Resolved" : "Open";
    const paragraphs = conclusion.fragments.filter(fragment => fragment.type === "paragraph");
    const generated = paragraphs.find(fragment => fragment.generated === "status_conclusion");
    // The regex alone decides: the marker outlives the text and overwrote written conclusions.
    const defaultParagraph = paragraphs.find(hasDefaultStatusConclusion);
    if (!paragraphs.length) {
      // Created empty, never filled. The Content page offers the sentence instead.
      conclusion.fragments.unshift(newFragment("paragraph"));
    } else if (defaultParagraph) {
      const span = defaultSpanIn(defaultParagraph);
      delete defaultParagraph.generated;
      defaultParagraph.runs = [
        ...runsUpTo(defaultParagraph.runs || [], span[0]),
        ...statusConclusionRuns(vulnerability.title, status),
        ...runsAfter(defaultParagraph.runs || [], span[1]),
      ];
    }
    if (generated) conclusion.fragments = conclusion.fragments.filter(fragment => fragment === generated || fragment.type !== "paragraph" || fragmentHasText(fragment));
  }
  // Twin of report_service.content_types_for_status; the one owner of which sections a status prints.
  const contentTypesForStatus = status => status === "open_new"
    ? ["description","recommended_remediation","proof_of_concept"]
    : ["description","recommended_remediation","previous_proof_of_concept","proof_of_concept","in_conclusion"];
  // Twin of report_service.content_has_work. Boilerplate this app wrote itself does not count: it
  // is regenerated on demand, so counting it would make every finding look like it has work to lose.
  const contentHasWork = content => (content.fragments || [])
    .filter(fragment => !(fragment.generated || isDefaultStatusConclusion(fragment)))
    .some(fragment =>
      (fragment.runs || []).some(run => run.text?.trim())
      || (fragment.items || []).some(item => (item.runs || []).some(run => run.text?.trim()))
      || fragment.text?.trim() || fragment.caption?.trim() || fragment.evidence_id
      || [...(fragment.header || []), ...(fragment.rows || []).flat()].some(cell => (cell.runs || []).some(run => run.text?.trim())));
  function provision(vulnerability) {
    const types = contentTypesForStatus(vulnerability.status);
    const existing = Object.fromEntries((vulnerability.contents || []).map(content => [content.type, content]));
    // A status change must not destroy work. A section this status does not print is kept when it
    // still holds something written, so changing status and back brings the tester's work with it.
    // in_conclusion is the exception: it is a statement about the status, so carrying it would keep a
    // sentence the status has just made false. It is dropped, and offered back fresh on the way in.
    const carried = (vulnerability.contents || []).filter(content => !types.includes(content.type) && content.type !== "in_conclusion" && contentHasWork(content));
    vulnerability.contents = [...types.map(type => existing[type] || {type, fragments:[]}), ...carried];
    const required = {description:["paragraph"], recommended_remediation:["paragraph"], previous_proof_of_concept:["numbered_list","image"], proof_of_concept:["numbered_list","image"], in_conclusion:[]};
    vulnerability.contents.forEach(content => {
      if (content.fragments.length || !required[content.type]) return;
      required[content.type].forEach(type => content.fragments.push(newFragment(type)));
    });
    vulnerability.contents.forEach(content => { if (content.type.endsWith("proof_of_concept")) ensureProofSteps(content); });
    const remediation = vulnerability.contents.find(content => content.type === "recommended_remediation");
    if (vulnerability.status === "resolved") remediation.fragments = [{frag_id:id("f"), type:"paragraph", generated:"resolved_remediation", runs:[{text:RESOLVED_REMEDIATION}]}];
    else {
      // Reopening a finding leaves boilerplate describing a remediation that no longer happened.
      const kept = remediation.fragments.filter(fragment => fragment.generated !== "resolved_remediation");
      remediation.fragments = kept.length ? kept : [newFragment("paragraph")];
    }
    syncConclusion(vulnerability);
    syncEvidenceImageSlots(vulnerability);
  }
  // The sentence names the finding and its status, so a rename or a status change can leave a
  // tester-written conclusion describing something no longer true. Boilerplate is re-derived
  // silently as before; only prose is worth interrupting for. Returns whether it rewrote anything.
  const conclusionParagraphText = finding => {
    const first = finding.contents?.find(content => content.type === "in_conclusion")?.fragments.find(fragment => fragment.type === "paragraph");
    return first ? conclusionText(first) : "";
  };
  // syncConclusion has already rewritten the sentence by the time this runs at every call site, so
  // the caller passes what the paragraph said beforehand. Boilerplate gets a notice rather than a
  // choice: "keep mine" on a sentence the app owns is a promise the next save would undo, because
  // provision re-derives any paragraph that still contains a recognised sentence.
  async function offerConclusionRewrite(finding, previousText) {
    const conclusion = finding.contents?.find(content => content.type === "in_conclusion");
    if (!conclusion || !contentTypesForStatus(finding.status).includes("in_conclusion")) return false;
    const first = conclusion.fragments.find(fragment => fragment.type === "paragraph");
    if (!first || first.generated || !fragmentHasText(first)) return false;
    const statusWord = finding.status === "resolved" ? "Resolved" : "Open";
    const derived = statusConclusionRuns(finding.title, statusWord).map(run => run.text).join("");
    const before = previousText ?? conclusionText(first);
    // Nothing to announce when there was no sentence: a status change that brings the section back
    // creates one rather than updating one.
    if (!before.trim()) return false;
    const span = defaultConclusionSpan(before);
    // Nothing to announce when the sentence did not move: both open statuses read "Open".
    if (span && before.slice(span[0], span[1]) === derived) return false;
    if (span) {
      await window.vrDialog.ask({
        title: "The closing sentence was updated",
        message: `The standard closing sentence now reads "${derived}". Replace it with your own wording before generating.`,
        actions: [{key: "ok", label: "OK", tone: "primary"}],
      });
      // syncConclusion already wrote it, so nothing here changed and no caller needs to re-render.
      return false;
    }
    if (!await window.vrDialog.confirm({
      title: "Replace the conclusion?",
      message: `This finding's conclusion reads "${before}". The standard sentence would now read "${derived}".`,
      confirmLabel: "Replace it",
      cancelLabel: "Keep mine",
    })) return false;
    first.runs = statusConclusionRuns(finding.title, statusWord);
    return true;
  }
  const scopeTargetIds = scope => scope?.target_ids || [];
  // Twin of report_service.location_lines: blanks are nothing, a "#" line is a note to the tester,
  // and a repeat is the same place said twice. The raw text stays in the draft; it just never counts.
  const locationLines = values => {
    const cleaned = [];
    (values || []).forEach(value => {
      const text = String(value ?? "").trim();
      if (text && !text.startsWith("#") && !cleaned.includes(text)) cleaned.push(text);
    });
    return cleaned;
  };
  const customLocationValues = scope => Object.entries(scope?.custom_locations || {})
    .filter(([environment]) => report.engagement.tested_environments.includes(environment))
    .flatMap(([, byChannel]) => Object.entries(byChannel || {})
      .filter(([channel]) => report.engagement.tested_channels.includes(channel))
      .flatMap(([, locations]) => locationLines(locations)));
  // Twin of report_service.scope_has_location. Selected targets are a presence check; a typed line
  // counts only while the engagement still covers what it was typed under.
  const scopeHasLocation = finding => scopeTargetIds(finding.scope).length > 0 || customLocationValues(finding.scope).length > 0;
  const scopeEnvironments = scope => {
    const environments = [];
    const add = environment => { if (environment && !environments.includes(environment)) environments.push(environment); };
    scopeTargetIds(scope).forEach(targetId => add(report.scope_targets.find(target => target.target_id === targetId)?.environment));
    Object.entries(scope?.custom_locations || {}).forEach(([environment, byChannel]) => {
      // A line typed under coverage the engagement has since dropped is out of scope, whatever it says.
      if (!report.engagement.tested_environments.includes(environment)) return;
      const covered = Object.entries(byChannel || {}).filter(([channel]) => report.engagement.tested_channels.includes(channel));
      if (covered.some(([, locations]) => locationLines(locations).length)) add(environment);
    });
    return environments;
  };
  const affectedEnvironments = finding => scopeEnvironments(finding.scope);
  // Twin of models.CHANNELS; the one canonical app-type order on this side.
  const CHANNELS = ["web", "api", "mobile"];
  const channelLabels = {web:"Web", api:"API", mobile:"Mobile"};
  // Twin of report_service.affected_channels; keep both in step.
  const affectedChannels = finding => {
    const scope = finding.scope;
    const channels = [];
    const add = channel => { if (channel && !channels.includes(channel)) channels.push(channel); };
    (scope?.target_ids || []).forEach(targetId => add(report.scope_targets.find(target => target.target_id === targetId)?.channel));
    Object.entries(scope?.custom_locations || {}).forEach(([environment, byChannel]) => {
      if (!report.engagement.tested_environments.includes(environment)) return;
      Object.entries(byChannel || {}).forEach(([channel, locations]) => {
        if (report.engagement.tested_channels.includes(channel) && locationLines(locations).length) add(channel);
      });
    });
    return channels;
  };
  const libraryEntryFor = finding => library.find(candidate => candidate.library_id === finding.library_ref?.library_id) || null;
  // Twin of report_service.applicable_poc_variants.
  const applicablePocVariants = finding => {
    const available = libraryEntryFor(finding)?.proof_of_concept || {};
    const channels = affectedChannels(finding);
    return CHANNELS.filter(channel => channels.includes(channel) && (available[channel] || []).length);
  };
  const environmentName = environment => environment === "production" ? "Production" : "Non-Production";
  const imagesForEnvironment = (finding, environment) => finding.contents.filter(content => content.type !== "previous_proof_of_concept").flatMap(content => (content.fragments || []).filter(fragment => fragment.type === "image" && fragment.environment === environment));
  // Twin of report_service.sync_evidence_image_slots; keep both in step. Coverage is a property of
  // the proof of concept alone, so a carried previous-PoC image is never relabelled or counted here.
  const syncEvidenceImageSlots = finding => {
    const environments = affectedEnvironments(finding);
    // An empty slot for an environment the finding no longer affects is nobody's to fill, so it goes
    // rather than lingering as a second demand. An uploaded screenshot stays exactly where it is:
    // relabelling it would file the tester's evidence under a heading it never belonged to.
    finding.contents.filter(content => content.type !== "previous_proof_of_concept").forEach(content => {
      content.fragments = content.fragments.filter(fragment => !(
        fragment.type === "image" && fragment.environment && !environments.includes(fragment.environment)
        && !fragment.evidence_id && !fragment.caption?.trim()));
    });
    const proof = finding.contents.find(content => content.type === "proof_of_concept");
    const images = finding.contents.filter(content => content.type !== "previous_proof_of_concept").flatMap(content => content.fragments.filter(fragment => fragment.type === "image"));
    const covered = () => (proof?.fragments || []).filter(fragment => fragment.type === "image").map(fragment => fragment.environment);
    let missing = environments.filter(environment => !covered().includes(environment));
    images.filter(image => !image.environment).forEach(image => { image.environment = missing.shift() || environments[0] || null; });
    missing = environments.filter(environment => !covered().includes(environment));
    missing.forEach(environment => { const image = newFragment("image"); image.environment = environment; proof?.fragments.push(image); });
    // A carried previous-PoC slot still needs an environment to render under, even though it never
    // counts as this engagement's coverage. Provisioning creates it blank, so nothing else would.
    const previous = finding.contents.find(content => content.type === "previous_proof_of_concept");
    (previous?.fragments || []).forEach(fragment => {
      if (fragment.type === "image" && !fragment.environment && environments.length) fragment.environment = environments[0];
    });
  };
  // Single owner of the rule: provisioning guarantees these fragments exist, so allowing a delete
  // would only have the next save put one back and make the editor look like it lost the change.
  const deletionBlockedReason = (fragment, content, finding) => {
    if (requiresFragment.includes(content.type)) {
      return content.fragments.length === 1 ? `${contentNames[content.type]} always keeps one fragment.` : null;
    }
    if (!content.type.endsWith("proof_of_concept")) return null;
    const sameType = content.fragments.filter(candidate => candidate.type === fragment.type);
    if (fragment.type === "numbered_list") return sameType.length === 1 ? "A proof of concept always keeps one list of steps." : null;
    if (fragment.type !== "image") return null;
    if (content.type === "previous_proof_of_concept") return sameType.length === 1 ? "The previous proof of concept always keeps one image." : null;
    if (!fragment.environment || !affectedEnvironments(finding).includes(fragment.environment)) return null;
    return sameType.filter(image => image.environment === fragment.environment).length === 1
      ? `${environmentName(fragment.environment)} evidence is required while this finding affects it.`
      : null;
  };
  // Twin of report_service.ensure_proof_steps; keep both in step. Steps are the substance of a proof
  // of concept, so one numbered list survives deletion, a status change, and a library replace.
  const ensureProofSteps = content => {
    if (!content.fragments.some(fragment => fragment.type === "numbered_list")) content.fragments.unshift(newFragment("numbered_list"));
  };
  // Deep-clones library fragments with fresh frag_ids; frag_id uniqueness is report-wide, so nothing
  // copied in from the library may keep its original id. Shared by every replace/merge offer.
  const remintFragments = fragments => { const copied = JSON.parse(JSON.stringify(fragments)); copied.forEach(fragment => { fragment.frag_id = id("f"); }); return copied; };
  // Twin of report_service.merge_step_lists; adjacent steps are one procedure, while an intervening
  // note or other fragment is an ordering boundary that appended content must not cross.
  const mergeStepLists = fragments => {
    const merged = [];
    fragments.forEach(fragment => {
      const previous = merged[merged.length - 1];
      if (fragment.type === "numbered_list" && previous?.type === "numbered_list") {
        const items = [...(previous.items || []), ...(fragment.items || [])];
        const written = items.filter(item => (item.runs || []).some(run => run.text.trim()));
        previous.items = written.length ? written : items.slice(0, 1);
      } else merged.push(fragment);
    });
    return merged;
  };
  // Twin of report_service.apply_poc_variant; keep both in step. mode "replace" overwrites the
  // non-image fragments; "merge" appends the library's steps after what is already there.
  const applyPocVariant = (finding, steps, variants, mode = "replace") => {
    const proof = finding.contents.find(content => content.type === "proof_of_concept");
    if (!proof) return;
    const images = proof.fragments.filter(fragment => fragment.type === "image");
    const kept = mode === "merge" ? proof.fragments.filter(fragment => fragment.type !== "image") : [];
    proof.fragments = [...mergeStepLists([...kept, ...remintFragments(steps)]), ...images];
    ensureProofSteps(proof);
    finding.poc_variants ||= [];
    variants.forEach(variant => { if (!finding.poc_variants.includes(variant)) finding.poc_variants.push(variant); });
    // A refusal is per app type, so installing one must not clear the others.
    finding.poc_variant_declined = (finding.poc_variant_declined || []).filter(channel => !variants.includes(channel));
  };
  const pocStepsFor = (finding, variant) => libraryEntryFor(finding)?.proof_of_concept?.[variant] || null;
  // The conclusion quotes the steps, so only prose-bearing fragments have a "last line" at all. An
  // image or table has none, and a command line or a heading quoted into a conclusion reads as a bug.
  // Consequence: a proof of concept ending in a code block is offered the line above it.
  const pocLastStep = finding => {
    const fragments = finding.contents?.find(content => content.type === "proof_of_concept")?.fragments || [];
    for (let index = fragments.length - 1; index >= 0; index -= 1) {
      const fragment = fragments[index];
      if (!["numbered_list", "bulleted_list", "note"].includes(fragment.type)) continue;
      const values = fragment.type === "note"
        ? [(fragment.runs || []).map(run => run.text).join("")]
        : (fragment.items || []).map(item => (item.runs || []).map(run => run.text).join(""));
      const lines = values.flatMap(value => value.split(/\r?\n/));
      const last = lines.map(line => line.trim()).filter(Boolean).pop();
      if (last) return last;
    }
    return "";
  };
  // A library entry's description/recommended_remediation fragments, for the Content-page offer.
  const libraryContentFor = (entry, type) => entry?.contents?.find(content => content.type === type)?.fragments || [];
  // Absent, null and false read identically to a tester, but the server dumps every optional field
  // explicitly, so a freshly typed section changes shape the first time it is saved. Coerce rather
  // than strip, or a fingerprint taken before a save stops matching the moment the save returns.
  const normalizedRuns = runs => (runs || []).map(run => [run.text || "", run.bold ? 1 : 0, run.italic ? 1 : 0, run.underline ? 1 : 0]);
  const normalizedCells = cells => (cells || []).map(cell => normalizedRuns(cell.runs));
  const normalizedSection = fragments => JSON.stringify((fragments || []).map(fragment => [
    fragment.type, normalizedRuns(fragment.runs), normalizedCells(fragment.items),
    normalizedCells(fragment.header), (fragment.rows || []).map(normalizedCells),
    fragment.text || "", fragment.caption || "", fragment.evidence_id || "",
    fragment.environment || "", fragment.generated || "",
    // continue_numbering is deliberately absent. The library offer asks whether this section still
    // matches the entry's content, and numbering presentation is not content -- including it would
    // make ticking the box re-open an offer whose only remedy would wipe the tick.
  ]));
  // frag_ids are reminted on every copy, so they are the one thing two identical sections never share.
  const sameFragments = (left, right) => normalizedSection(left) === normalizedSection(right);
  // 32-bit FNV-1a over the same normalisation. Client-only: Python stores the string and never
  // computes it, so this is not a twin. A collision hides one banner until the next edit, and the
  // length prefix means a collision needs a matching length too.
  const sectionFingerprint = fragments => {
    const text = normalizedSection(fragments);
    let hash = 0x811c9dc5;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 0x01000193);
    }
    return `${text.length}-${(hash >>> 0).toString(16)}`;
  };
  // Dismissals of the conclusion step offer, for this sitting only. The persisted record cannot do
  // this job: while the conclusion is still boilerplate the offer is meant to keep standing, so a
  // Dismiss that only wrote to the draft would be redrawn immediately and mean nothing.
  const dismissedStepOffers = new Set();
  const dismissedSentenceOffers = new Set();
  // Whether the tester has written any steps. Images are excluded deliberately: a screenshot is not
  // a step, and "I have a screenshot but no steps" is exactly the state worth offering.
  const pocHasWrittenSteps = finding => (finding.contents?.find(content => content.type === "proof_of_concept")?.fragments || [])
    .some(fragment => fragment.type !== "image" && fragmentHasContent(fragment));
  // Single owner of "which sections still have an unanswered library offer", so the Content-page
  // banners and the review panel can never disagree about what is outstanding.
  const pendingLibraryOffers = finding => {
    const entry = libraryEntryFor(finding);
    if (!entry) return [];
    const offers = ["description", "recommended_remediation"]
      // Stays first: a resolved finding's remediation renders locked, with no fragment editors, so
      // a banner there would offer an action the tester has no way to complete.
      .filter(type => !(finding.status === "resolved" && type === "recommended_remediation"))
      .filter(type => libraryContentFor(entry, type).length)
      .map(type => ({type, fragments: finding.contents?.find(content => content.type === type)?.fragments || []}))
      // Offering what the section already holds is noise; offering what the tester already answered
      // for this exact content is nagging. Both release the moment the section changes again.
      .filter(({type, fragments}) => !sameFragments(fragments, libraryContentFor(entry, type)))
      .filter(({type, fragments}) => finding.content_offer_dismissed?.[type] !== sectionFingerprint(fragments))
      .map(({type}) => ({type, entry}));
    const variants = applicablePocVariants(finding)
      // A decline is permanent; an install is not. Emptying the steps you pulled in re-offers them,
      // because the record of installing them describes content that is no longer there.
      .filter(variant => !(finding.poc_variant_declined || []).includes(variant))
      .filter(variant => !pocHasWrittenSteps(finding) || !(finding.poc_variants || []).includes(variant));
    if (variants.length) offers.push({type:"proof_of_concept", entry, variants});
    return offers;
  };
  // Initializes the setup page's engagement metadata, coverage, and scope controls.
  function setup() {
    const environmentLabels = {production:"Production", non_production:"Non-Production"};
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
      app_name: characterRule("Application name", /^[\p{L}\p{Nd} :;.()\-]$/u),
      ci_number: characterRule("CI number", /^[\p{L}\p{Nd}-]$/u),
      bsn_number: characterRule("BSN number", /^[\p{L}\p{Nd}-]$/u),
      app_owner: characterRule("Application owner", /^[\p{L} \-]$/u),
      tester: characterRule("Tester", /^[\p{L} \-]$/u),
      limitations: characterRule("Limitations", /^[\p{L}\p{Nd} /,.;:()&'"\-\r\n]$/u),
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
    // Twin of the last two branches of models.resolve_tested_channels: never fall back to web while
    // the report's own targets can answer, because that would drop every API and mobile location.
    if (!report.engagement.tested_channels?.length) {
      const present = CHANNELS.filter(channel => report.scope_targets.some(target => target.channel === channel));
      report.engagement.tested_channels = present.length ? present : ["web"];
    }
    report.engagement.test_windows ||= {};
    ["production", "non_production"].forEach(environment => {
      report.engagement.test_windows[environment] ||= {
        start_date: environment === "production" ? report.engagement.start_date : null,
        end_date: environment === "production" ? report.engagement.end_date : null,
        test_time: "Anytime",
      };
      if (report.engagement.test_windows[environment].test_time == null) report.engagement.test_windows[environment].test_time = "Anytime";
    });
    report.engagement.test_accounts ||= [{user_role:"N/A", username:"N/A"}];
    if (report.engagement.limitations == null) report.engagement.limitations = "N/A";
    report.scope_text ||= {};
    ["production", "non_production"].forEach(environment => {
      report.scope_text[environment] ||= {};
      CHANNELS.forEach(channel => {
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
    // Mirrors the server's removal guard so Setup can warn before a save is rejected. A typed-in
    // location only counts while the engagement still covers both its environment and its app type.
    const scopeReaches = (scope, targets, coverage) => {
      if ((scope?.target_ids || []).some(targetId => targets.some(target => target.target_id === targetId))) return true;
      return Object.entries(scope?.custom_locations || {})
        .filter(([environment]) => !coverage || coverage.environments.includes(environment))
        .flatMap(([, byChannel]) => Object.entries(byChannel || {})
          .filter(([channel]) => !coverage || coverage.channels.includes(channel))
          .flatMap(([, values]) => locationLines(values)))
        .length > 0;
    };
    const findingsStrandedBy = (environments, channels) => {
      const surviving = (report.scope_targets || []).filter(target => environments.includes(target.environment) && channels.includes(target.channel));
      return (report.vulnerabilities || [])
        .filter(finding => scopeReaches(finding.scope, report.scope_targets || []) && !scopeReaches(finding.scope, surviving, {environments, channels}))
        .map(finding => finding.title || "Untitled finding");
    };
    const confirmScopeLoss = async (environments, channels, change) => {
      const doomed = new Set((report.scope_targets || [])
        .filter(target => !environments.includes(target.environment) || !channels.includes(target.channel))
        .map(target => target.target_id));
      const stranded = findingsStrandedBy(environments, channels);
      const impact = scopeChangeImpact(doomed);
      if (!stranded.length && !impact.findings) return true;
      const lines = [];
      if (impact.findings) lines.push(`${impact.findings} finding${impact.findings === 1 ? "" : "s"} lose a selected location.`);
      if (stranded.length) lines.push(`${stranded.length} will be left with no affected location at all, and the report cannot be saved until you give ${stranded.length === 1 ? "it" : "them"} one.`);
      // Screenshots are kept, not deleted -- but an unlabelled one blocks generation until it is
      // reassigned or removed, so the tester hears it here rather than from the readiness panel.
      if (impact.images) lines.push(`${impact.images} screenshot${impact.images === 1 ? "" : "s"} keep their file but lose their environment, and must be reassigned or deleted before the report can be generated.`);
      return window.vrDialog.confirm({
        title: `${change}?`,
        message: lines.join(" "),
        list: stranded,
        confirmLabel: "Make the change anyway",
        cancelLabel: "Keep the current coverage",
        tone: "danger",
      });
    };
    const count = (total, word) => `${total} ${word}${total === 1 ? "" : "s"}`;
    // Everything an app type owns goes when it is unchecked, so the dialog counts it before asking.
    const channelRemovalImpact = channel => {
      const targetIds = new Set((report.scope_targets || []).filter(target => target.channel === channel).map(target => target.target_id));
      const endpointsIn = finding => Object.values(finding.scope?.custom_locations || {})
        .reduce((total, byChannel) => total + (byChannel?.[channel] || []).filter(value => value.trim()).length, 0);
      const findings = (report.vulnerabilities || []).filter(finding =>
        (finding.scope?.target_ids || []).some(targetId => targetIds.has(targetId)) || endpointsIn(finding));
      return {
        targets: targetIds.size,
        findings: findings.map(finding => finding.title || "Untitled finding"),
        endpoints: (report.vulnerabilities || []).reduce((total, finding) => total + endpointsIn(finding), 0),
      };
    };
    // The tester agreed to lose these targets, so clear the selections pointing at them rather than
    // leaving the page holding IDs the next save would drop. An image for an environment the finding
    // no longer reaches keeps its file but loses its label, so the readiness panel asks for a new one
    // instead of the report silently omitting it.
    const dropTargetsEverywhere = targetIds => {
      if (!targetIds.size) return;
      (report.vulnerabilities || []).forEach(finding => {
        const scope = finding.scope || {};
        const had = scopeEnvironments({target_ids:scope.target_ids || []});
        scope.target_ids = (scope.target_ids || []).filter(targetId => !targetIds.has(targetId));
        targetIds.forEach(targetId => { delete scope.location_values?.[targetId]; });
        const kept = scopeEnvironments({target_ids:scope.target_ids});
        // A typed-in endpoint keeps its environment alive even with no target selected there.
        const typed = Object.entries(scope.custom_locations || {})
          .filter(([, byChannel]) => Object.values(byChannel || {}).flat().some(value => value.trim()))
          .map(([environment]) => environment);
        const lost = had.filter(environment => !kept.includes(environment) && !typed.includes(environment));
        if (!lost.length) return;
        (finding.contents || []).forEach(content => {
          // Previous proof of concept records an earlier engagement, so its labels are history.
          if (content.type === "previous_proof_of_concept") return;
          (content.fragments || []).forEach(fragment => {
            if (fragment.type === "image" && lost.includes(fragment.environment)) fragment.environment = null;
          });
        });
      });
    };
    // What a scope change costs the findings, for a dialog that has to say so before it happens.
    const scopeChangeImpact = targetIds => {
      let findings = 0;
      let images = 0;
      (report.vulnerabilities || []).forEach(finding => {
        const scope = finding.scope || {};
        const selected = scope.target_ids || [];
        if (!selected.some(targetId => targetIds.has(targetId))) return;
        findings += 1;
        const kept = scopeEnvironments({target_ids:selected.filter(targetId => !targetIds.has(targetId))});
        const typed = Object.entries(scope.custom_locations || {})
          .filter(([, byChannel]) => Object.values(byChannel || {}).flat().some(value => value.trim()))
          .map(([environment]) => environment);
        const lost = scopeEnvironments({target_ids:selected}).filter(environment => !kept.includes(environment) && !typed.includes(environment));
        if (!lost.length) return;
        (finding.contents || []).forEach(content => {
          if (content.type === "previous_proof_of_concept") return;
          images += (content.fragments || []).filter(fragment => fragment.type === "image" && lost.includes(fragment.environment)).length;
        });
      });
      return {findings, images};
    };
    const dropChannelEverywhere = channel => {
      const targetIds = new Set((report.scope_targets || []).filter(target => target.channel === channel).map(target => target.target_id));
      Object.values(report.scope_text || {}).forEach(byChannel => { if (byChannel) byChannel[channel] = ""; });
      // Typed endpoints go first, so an environment kept alive only by one under this app type
      // counts as lost when the image labels are reconsidered.
      (report.vulnerabilities || []).forEach(finding => {
        const scope = finding.scope || {};
        Object.entries(scope.custom_locations || {}).forEach(([environment, byChannel]) => {
          delete byChannel?.[channel];
          if (!Object.keys(byChannel || {}).length) delete scope.custom_locations[environment];
        });
      });
      dropTargetsEverywhere(targetIds);
      report.scope_targets = (report.scope_targets || []).filter(target => target.channel !== channel);
    };
    const confirmChannelRemoval = async channel => {
      const impact = channelRemovalImpact(channel);
      if (!impact.targets && !impact.findings.length) return true;
      const stranded = findingsStrandedBy(report.engagement.tested_environments, report.engagement.tested_channels.filter(value => value !== channel));
      const losses = [impact.targets && `${count(impact.targets, "scope target")} in Setup`, impact.endpoints && count(impact.endpoints, "additional affected endpoint")].filter(Boolean);
      return window.vrDialog.confirm({
        title: `Remove ${channelLabels[channel]} from the scope?`,
        message: `${losses.join(", and ")} will be deleted, along with every ${channelLabels[channel]} affected location selected in the findings below.${stranded.length ? ` ${count(stranded.length, "finding")} will be left with no affected location at all.` : ""} This cannot be undone.`,
        list: impact.findings,
        confirmLabel: `Remove ${channelLabels[channel]} anyway`,
        cancelLabel: "Keep this app type",
        tone: "danger",
      });
    };
    // Mirrors reconcile_targets: a target only survives an edit if its exact text is still listed
    // under an app type the report still covers.
    const survivingAfterScopeText = () => report.scope_targets.filter(target => {
      if (!report.engagement.tested_channels.includes(target.channel)) return false;
      const text = report.scope_text?.[target.environment]?.[target.channel];
      if (text === undefined) return true;
      return text.split(/\r?\n/).map(value => value.trim()).filter(value => value && !value.startsWith("#")).includes(target.value);
    });
    // The server refuses to strand a finding, so catch it here rather than letting the save fail.
    const scopeTextStrandedFindings = () => {
      const surviving = survivingAfterScopeText();
      if (surviving.length === report.scope_targets.length) return [];
      const coverage = {environments: report.engagement.tested_environments, channels: report.engagement.tested_channels};
      return report.vulnerabilities
        .filter(finding => scopeReaches(finding.scope, report.scope_targets) && !scopeReaches(finding.scope, surviving, coverage))
        .map(finding => finding.title || "Untitled finding");
    };
    strandedByScopeEdit = scopeTextStrandedFindings;
    const confirmScopeTextLoss = async () => {
      const surviving = new Set(survivingAfterScopeText().map(target => target.target_id));
      const doomed = new Set((report.scope_targets || []).filter(target => !surviving.has(target.target_id)).map(target => target.target_id));
      const stranded = scopeTextStrandedFindings();
      const impact = scopeChangeImpact(doomed);
      if (!stranded.length && !impact.findings) return true;
      const lines = [];
      if (impact.findings) lines.push(`${impact.findings} finding${impact.findings === 1 ? "" : "s"} point at a target you are removing or renaming, and lose it.`);
      if (stranded.length) lines.push(`${stranded.length} will be left with no location at all, and the report cannot be saved until ${stranded.length === 1 ? "it gets" : "they get"} another.`);
      if (impact.images) lines.push(`${impact.images} screenshot${impact.images === 1 ? "" : "s"} keep their file but lose their environment, and must be reassigned or deleted before the report can be generated.`);
      return window.vrDialog.confirm({
        title: "Change these scope targets?",
        message: lines.join(" "),
        list: stranded,
        confirmLabel: "Change them anyway",
        cancelLabel: "Keep the current targets",
        tone: "danger",
      });
    };
    const renderCoverage = () => {
      configuration.innerHTML = "";
      const typeGroup = document.createElement("div");
      typeGroup.className = "test-type-select";
      const typeHeading = document.createElement("span");
      typeHeading.textContent = "App Types";
      const typeOptions = document.createElement("div");
      typeOptions.className = "test-type-options";
      // Rendered from the static channel list, never from tested_channels: an imported empty
      // selection would otherwise show no boxes on the only page that can put one back.
      CHANNELS.forEach(channel => {
        const option = document.createElement("label");
        option.className = "coverage-option";
        const box = document.createElement("input");
        box.type = "checkbox";
        box.value = channel;
        box.checked = report.engagement.tested_channels.includes(channel);
        box.setAttribute("aria-label", `Test ${channelLabels[channel]}`);
        if (box.checked && report.engagement.tested_channels.length === 1) {
          box.disabled = true;
          option.title = "A report has to cover at least one app type.";
        }
        box.onchange = async () => {
          if (!box.checked && !await confirmChannelRemoval(channel)) {
            box.checked = true;
            return;
          }
          if (!box.checked) dropChannelEverywhere(channel);
          report.engagement.tested_channels = box.checked
            ? CHANNELS.filter(value => value === channel || report.engagement.tested_channels.includes(value))
            : report.engagement.tested_channels.filter(value => value !== channel);
          renderCoverage();
          scheduleSave();
        };
        option.append(box, document.createTextNode(channelLabels[channel]));
        typeOptions.append(option);
      });
      typeGroup.append(typeHeading, typeOptions);
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
        panel.querySelector("input[type=checkbox]").onchange = async event => {
          const values = report.engagement.tested_environments;
          const next = event.target.checked ? [...values, environment] : values.filter(item => item !== environment);
          if (!event.target.checked && !await confirmScopeLoss(next, report.engagement.tested_channels, `Remove ${label}`)) {
            event.target.checked = true;
            return;
          }
          // The server rebuilds scope_targets from the surviving environments, so clear the
          // selections that pointed into this one before they reach a save that would drop them.
          if (!event.target.checked) dropTargetsEverywhere(new Set((report.scope_targets || []).filter(target => target.environment === environment).map(target => target.target_id)));
          report.engagement.tested_environments = next;
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
        CHANNELS.filter(channel => report.engagement.tested_channels.includes(channel)).forEach(channel => {
          const label = document.createElement("label");
          label.textContent = channelLabels[channel];          const textarea = document.createElement("textarea");
          textarea.value = report.scope_text[environment][channel];
          // Two lines to start, then grow with the target list instead of scrolling.
          textarea.rows = 2;
          const grow = () => {
            textarea.style.height = "auto";
            textarea.style.height = `${textarea.scrollHeight}px`;
          };
          textarea.oninput = () => { report.scope_text[environment][channel] = textarea.value; grow(); if ([...root.querySelectorAll("#scope-grid textarea")].some(input => input.value.split("\n").some(value => value.trim() && !value.trimStart().startsWith("#")))) root.querySelectorAll("#scope-grid textarea.validation-error").forEach(input => input.classList.remove("validation-error")); scheduleSave(); };
          textarea.onfocus = () => { textarea.dataset.scopeTextBefore = textarea.value; };
          // Confirm on commit rather than per keystroke, so a half-typed target never counts as removed.
          textarea.onchange = async () => {
            if (textarea.dataset.scopeTextBefore === undefined || textarea.dataset.scopeTextBefore === textarea.value) return;
            if (await confirmScopeTextLoss()) {
              const surviving = new Set(survivingAfterScopeText().map(target => target.target_id));
              dropTargetsEverywhere(new Set((report.scope_targets || []).filter(target => !surviving.has(target.target_id)).map(target => target.target_id)));
              textarea.dataset.scopeTextBefore = textarea.value;
              return;
            }
            textarea.value = textarea.dataset.scopeTextBefore;
            report.scope_text[environment][channel] = textarea.value;
            grow();
            scheduleSave();
          };
          if (channel === "mobile") wireSetupRule(textarea, mobileScopeRule, `${environmentLabels[environment]} Mobile scope`);
          label.append(textarea);
          panel.append(label);
          // Outside the label so it stays out of the textarea's accessible name. Delete this together
          // with the mobile scope table when the .docx template gains one.
          if (channel === "mobile") {
            const note = document.createElement("p");
            note.className = "scope-note";
            note.textContent = "Mobile scope does not appear in the generated report yet.";
            panel.append(note);
          }
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
    const locationGroups = {production:[], non_production:[]};
    report.scope_targets.forEach(target => locationGroups[target.environment]?.push(target));
    const locationLabels = {production:"Production", non_production:"Non-Production"};
    const clearValidationError = event => {
      const control = event.target;
      if (control.matches(".finding-title-cell input.validation-error") && control.value.trim()) control.classList.remove("validation-error");
      if (control.matches("select.validation-error") && control.value) control.classList.remove("validation-error");
      if (control.matches("[data-location], [data-custom-location]")) {
        const locationRow = control.closest("tr");
        const hasLocation = locationRow?.querySelector("[data-location]:checked") || [...(locationRow?.querySelectorAll("[data-custom-location]") || [])].some(input => locationLines(input.value.split(/\r?\n/)).length);
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
        const hasLocation = locationRow?.querySelector("[data-location]:checked") || [...(locationRow?.querySelectorAll("[data-custom-location]") || [])].some(input => locationLines(input.value.split(/\r?\n/)).length);
        locationRow?.querySelectorAll(".location-group").forEach(group => group.classList.toggle("validation-error", !hasLocation));
      });
    };
    updateFindingSummary = () => {
      const summary = document.querySelector("#finding-summary");
      const note = document.querySelector("#finding-validation-note");
      if (!summary) return;
      const heading = document.querySelector('#setup[data-step="findings"] .section-title h1');
      if (heading) {
        let total = heading.querySelector(".nav-count");
        if (!total) {
          total = document.createElement("span");
          total.className = "nav-count";
          heading.append(total);
        }
        total.textContent = report.vulnerabilities.length;
      }
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
    // Losing an environment's last location strands that environment's evidence, so confirm before dropping it.
    const settleScopeChange = async (finding, previousScope) => {
      const remaining = affectedEnvironments(finding);
      const lost = scopeEnvironments(previousScope).filter(environment => !remaining.includes(environment));
      if (!lost.length) return true;
      const stranded = lost.filter(environment => imagesForEnvironment(finding, environment).some(image => image.evidence_id || image.caption?.trim()));
      if (stranded.length) {
        const names = stranded.map(environmentName).join(" and ");
        const agreed = await window.vrDialog.confirm({
          title: `Remove the ${names} evidence from this finding?`,
          message: `This finding no longer has a ${names} affected location, so its ${names} screenshots and captions cannot appear in the report.`,
          confirmLabel: "Remove that evidence",
          cancelLabel: "Keep the affected location",
          tone: "danger",
        });
        if (!agreed) {
          finding.scope = previousScope;
          return false;
        }
      }
      const previousEvidence = evidenceIdsIn(finding);
      lost.forEach(environment => finding.contents.forEach(content => {
        if (content.type === "previous_proof_of_concept") return;
        content.fragments = (content.fragments || []).filter(fragment => !(fragment.type === "image" && fragment.environment === environment));
      }));
      dropUnreferencedEvidence(previousEvidence);
      syncEvidenceImageSlots(finding);
      return true;
    };
    // A title match applies the finding's non-content fields immediately and silently; each content
    // section offers its own keep/replace/add banner on the Content page instead of one whole-finding confirm.
    const replaceFromLibrary = (finding, entry) => {
      applyLibraryEntry(finding, entry);
      return true;
    };
    const applyLibraryEntry = (finding, entry) => {
      if (finding.library_ref?.library_id !== entry.library_id) {
        finding.poc_variants = [];
        finding.poc_variant_declined = [];
        finding.content_offer_resolved = {};
        // The fingerprint describes the section, not the entry, so without this a dismissal taken
        // against the old entry would go on suppressing the new one's offer.
        finding.content_offer_dismissed = {};
      }
      Object.assign(finding, {title:entry.title, likelihood:entry.default_likelihood, impact:entry.default_impact, severity:entry.default_severity || "informational", library_ref:{library_id:entry.library_id, source_id:entry.source_id, inserted_at:new Date().toISOString()}});
      // The only title write that did not re-derive the sentence. Harmless while the server fixed it
      // on the next save; not harmless now the tester is prompted about that sentence right here.
      syncConclusion(finding);
    };
    const foldAllFindings = document.querySelector("#fold-all-findings");
    const anyFindingExpanded = () => report.vulnerabilities.some(finding => expandedFindingIds.has(finding.uid));
    const updateFoldAllFindings = () => {
      if (!foldAllFindings) return;
      const open = anyFindingExpanded();
      foldAllFindings.hidden = !report.vulnerabilities.length;
      foldAllFindings.textContent = open ? "Collapse all" : "Expand all";
      foldAllFindings.setAttribute("aria-pressed", String(open));
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
        // A textarea measured while hidden reports no height, so re-measure when the row is shown.
        const growLocationValue = textarea => { textarea.style.height = "auto"; textarea.style.height = `${Math.max(28, textarea.scrollHeight)}px`; };
        const setExpanded = expanded => {
          row.classList.toggle("finding-expanded", expanded);
          locationRow.hidden = !expanded;
          toggle.setAttribute("aria-expanded", String(expanded));
          toggle.title = expanded ? "Hide affected locations" : "Show affected locations";
          if (expanded) expandedFindingIds.add(finding.uid);
          else expandedFindingIds.delete(finding.uid);
          updateFoldAllFindings();
          if (expanded) locationRow.querySelectorAll("textarea.location-value").forEach(growLocationValue);
        };
        toggle.onclick = () => setExpanded(!row.classList.contains("finding-expanded"));
        setExpanded(expandedFindingIds.has(finding.uid) || (index === 0 && !findingFoldDefaulted));
        if (index === 0) findingFoldDefaulted = true;
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
        const idDisplay = document.createElement("button");
        idDisplay.className = "finding-id-display";
        idDisplay.type = "button";
        idDisplay.setAttribute("aria-label", "Edit vulnerability ID");
        // Rebuilding the table to swap button for field would take focus and fold state with it.
        const showId = () => {
          idDisplay.textContent = idInput.value || "\u2014";
          idDisplay.classList.toggle("is-empty", !idInput.value);
        };
        const setIdEditing = editing => {
          idInput.hidden = !editing;
          idDisplay.hidden = editing;
          if (editing) idInput.focus();
          else showId();
        };
        idDisplay.addEventListener("click", () => setIdEditing(true));
        idInput.addEventListener("input", showId);
        idInput.addEventListener("blur", () => { setIdEditing(false); scheduleSave(); });
        idInput.insertAdjacentElement("beforebegin", idDisplay);
        setIdEditing(false);
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
          const channels = CHANNELS.filter(channel => (report.engagement.tested_channels || []).includes(channel));
          // Split the endpoint boxes by app type only when there is more than one; otherwise the channel is implied.
          channels.forEach(channel => {
          const customEditor = document.createElement("label");
          const customInputWrapper = document.createElement("div");
          const customGutter = document.createElement("div");
          const customInput = document.createElement("textarea");
          const customMeasure = document.createElement("div");
          customEditor.className = "location-lines-editor";
          customEditor.append(document.createTextNode(channels.length > 1 ? `Additional affected ${channel.toUpperCase()} endpoints` : "Additional affected endpoints"));
          customInputWrapper.className = "location-lines-input";
          customGutter.className = "location-lines-gutter";
          customGutter.setAttribute("aria-hidden", "true");
          customInput.className = "location-lines-textarea";
          customInput.dataset.customLocation = environment;
          customInput.dataset.customChannel = channel;
          customInput.rows = 1;
          customInput.placeholder = "One endpoint per line";
          customInput.setAttribute("aria-label", channels.length > 1 ? `${locationLabels[environment]} ${channel.toUpperCase()} affected endpoints` : `${locationLabels[environment]} affected endpoints`);
          customInput.value = (finding.scope.custom_locations?.[environment]?.[channel] || []).join("\n");
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
            const byChannel = finding.scope.custom_locations[environment] ||= {};
            if (values.length) byChannel[channel] = values;
            else delete byChannel[channel];
            if (!Object.keys(byChannel).length) delete finding.scope.custom_locations[environment];
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
        });
        locationRow.querySelectorAll("input.location-value").forEach(input => {
          const textarea = document.createElement("textarea");
          [...input.attributes].forEach(attribute => textarea.setAttribute(attribute.name, attribute.value));
          textarea.rows = 1;
          textarea.value = input.value;
          textarea.oninput = () => {
            finding.scope.location_values ||= {};
            finding.scope.location_values[textarea.dataset.locationValue] = textarea.value;
            scheduleSave();
          };
          input.replaceWith(textarea);
        });
        locationRow.querySelectorAll("textarea.location-value").forEach(textarea => {
          textarea.addEventListener("input", () => growLocationValue(textarea));
          growLocationValue(textarea);
        });
      });
    };
    const renderFindings = () => { findingBody.innerHTML = ""; report.vulnerabilities.forEach((finding, index) => { const row = document.createElement("tr"); const selectedTargets = finding.scope.target_ids || []; const locationValues = finding.scope.location_values || {}; const locationControls = Object.entries(locationGroups).filter(([, targets]) => targets.length).map(([environment, targets]) => `<fieldset class="location-group" data-location-group="${environment}"><legend>${locationLabels[environment]}</legend>${targets.length > 1 ? `<label class="select-all"><input type="checkbox" data-select-all="${environment}" ${targets.every(target => selectedTargets.includes(target.target_id)) ? "checked" : ""}>Select all</label>` : ""}<div class="location-checklist">${targets.map(target => `<div class="location-option"><label class="location-toggle"><input type="checkbox" data-location="${environment}" value="${target.target_id}" aria-label="Select ${escape(target.value)}" ${selectedTargets.includes(target.target_id) ? "checked" : ""}></label>${selectedTargets.includes(target.target_id) ? `<input class="location-value" data-location-value="${target.target_id}" value="${escape(locationValues[target.target_id] ?? target.value)}" aria-label="Location value for ${escape(target.value)}">` : `<span class="location-preview">${escape(target.value)}</span>`}</div>`).join("")}</div></fieldset>`).join("") || "<span class=\"muted\">Add targets in setup.</span>"; row.innerHTML = `<td class="finding-title-cell"><input value="${escape(finding.title)}" role="combobox" aria-autocomplete="list" aria-expanded="false" autocomplete="off" placeholder="Search or select a vulnerability"><div class="row-library-results" role="listbox"></div></td><td>${select(severity, finding.likelihood, true)}</td><td>${select(severity, finding.impact, true)}</td><td>${select(severity, finding.severity)}</td><td><input value="${escape(finding.display_id || "")}" inputmode="numeric" maxlength="5" pattern="[0-9]*" autocomplete="off"></td><td>${select(statuses.map(x=>x[0]), finding.status)}</td><td><button class="danger" type="button">Delete</button></td>`; const locationRow = document.createElement("tr"); locationRow.className = "finding-location-row"; locationRow.innerHTML = `<td colspan="7"><div class="finding-location"><strong>Location</strong><div class="location-controls">${locationControls}</div></div></td>`; const controls = row.querySelectorAll("input,select"); const titleInput = controls[0]; const rowResults = row.querySelector(".row-library-results"); const clearResults = () => { rowResults.innerHTML = ""; titleInput.setAttribute("aria-expanded", "false"); };
      let titleBeforeEdit = finding.title || "";
      let conclusionBeforeEdit = conclusionParagraphText(finding);
      const renderRowResults = () => { const matches = libraryMatches(titleInput.value); rowResults.innerHTML = matches.map(entry => libraryOptionMarkup(entry)).join(""); rowResults.style.width = `${document.querySelector("#library-search").getBoundingClientRect().width}px`; const requiredHeight = Math.min(rowResults.scrollHeight, 300) + 8; rowResults.classList.toggle("opens-up", window.innerHeight - titleInput.getBoundingClientRect().bottom < requiredHeight); titleInput.setAttribute("aria-expanded", String(matches.length > 0)); rowResults.querySelectorAll("[data-id]").forEach(item => item.onclick = async () => { const entry = library.find(candidate => candidate.library_id === item.dataset.id); if (!entry || finding.library_ref?.library_id === entry.library_id) { clearResults(); return; } if (await replaceFromLibrary(finding, entry, titleBeforeEdit)) { renderFindings(); scheduleSave(); } }); };
      titleInput.oninput = event => { finding.title = event.target.value; syncConclusion(finding); renderRowResults(); scheduleSave(); }; titleInput.onfocus = () => { titleBeforeEdit = finding.title || ""; conclusionBeforeEdit = conclusionParagraphText(finding); renderRowResults(); }; titleInput.onkeydown = event => { if (event.key === "Escape") clearResults(); };
      // A committed title that names a library entry pulls that entry in; any other title is just a rename.
      titleInput.onchange = async () => {
        const typed = titleInput.value.trim().toLowerCase();
        const entry = library.find(candidate => candidate.title.trim().toLowerCase() === typed);
        const swapped = Boolean(entry) && finding.library_ref?.library_id !== entry.library_id && await replaceFromLibrary(finding, entry, titleBeforeEdit);
        const rewrote = await offerConclusionRewrite(finding, conclusionBeforeEdit);
        if (swapped || rewrote) { renderFindings(); scheduleSave(); }
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
      controls[5].onchange = async event => {
        const nextStatus = event.target.value;
        const nextTypes = contentTypesForStatus(nextStatus);
        // Only sections holding something are worth a warning, and they are hidden rather than
        // deleted, so the dialog must not threaten a loss that no longer happens.
        const hidden = finding.contents.filter(content => !nextTypes.includes(content.type) && contentHasWork(content)).map(content => optionLabel(content.type));
        const replacesRemediation = nextStatus === "resolved" && finding.status !== "resolved";
        if ((hidden.length || replacesRemediation) && !await window.vrDialog.confirm({title: "Change the status of this finding?", message: hidden.length ? `This will take ${hidden.join(", ")} out of the report. Nothing is deleted, and changing the status back brings it all with it.` : "This will replace the recommended remediation.", confirmLabel: "Change the status", cancelLabel: "Keep the current status", tone: hidden.length ? "default" : "danger"})) {
          event.target.value = finding.status;
          return;
        }
        finding.status = nextStatus;
        const conclusionBeforeStatus = conclusionParagraphText(finding);
        provision(finding);
        // Strictly after the status dialog settles: vrDialog cancels whatever is already open.
        await offerConclusionRewrite(finding, conclusionBeforeStatus);
        scheduleSave();
      };
      const updateLocations = async () => {
        const targetIds = [...locationRow.querySelectorAll("[data-location]:checked")].map(input => input.value);
        const values = {...(finding.scope.location_values || {})};
        targetIds.forEach(targetId => { if (values[targetId] === undefined) values[targetId] = report.scope_targets.find(target => target.target_id === targetId).value; });
        Object.keys(values).forEach(targetId => { if (!targetIds.includes(targetId)) delete values[targetId]; });
        const custom = {};
        locationRow.querySelectorAll("[data-custom-location]").forEach(input => { const environment = input.dataset.customLocation; const channel = input.dataset.customChannel; const values = input.value.split(/\r?\n/).map(value => value.trim()).filter(Boolean); if (values.length) ((custom[environment] ||= {})[channel] ||= []).push(...values); });
        locationRow.querySelectorAll("[data-select-all]").forEach(control => { const options = locationRow.querySelectorAll(`[data-location="${control.dataset.selectAll}"]`); control.checked = [...options].every(option => option.checked); });
        const previousScope = finding.scope;
        finding.scope = {mode:"custom", target_ids:targetIds, location_values:values, custom_locations:custom};
        await settleScopeChange(finding, previousScope);
        renderFindings();
        scheduleSave();
      };
      locationRow.querySelectorAll("[data-location]").forEach(control => control.onchange = updateLocations);
      locationRow.querySelectorAll("[data-location-value]").forEach(input => input.oninput = () => { finding.scope.location_values ||= {}; finding.scope.location_values[input.dataset.locationValue] = input.value; scheduleSave(); });
      locationRow.querySelectorAll("[data-custom-location]").forEach(input => {
        input.onfocus = () => { input.dataset.scopeBeforeEdit = JSON.stringify(finding.scope); };
        // Clearing the last custom location for an environment drops it, so settle on commit rather than per keystroke.
        input.onchange = async () => {
          const snapshot = input.dataset.scopeBeforeEdit;
          if (!snapshot) return;
          if (!await settleScopeChange(finding, JSON.parse(snapshot))) { renderFindings(); return; }
          scheduleSave();
        };
      });
      locationRow.querySelectorAll("[data-select-all]").forEach(control => control.onchange = () => { locationRow.querySelectorAll(`[data-location="${control.dataset.selectAll}"]`).forEach(option => { option.checked = control.checked; }); updateLocations(); });
      // Deleting a finding takes its content and screenshots with it, so it needs the same guard as a library replace.
      row.querySelector("button").onclick = async () => {
        const evidenceCount = evidenceIdsIn(finding).size;
        const written = finding.contents?.some(content => (content.fragments || []).some(fragmentHasContent));
        const label = finding.title?.trim() || "this untitled finding";
        const losses = [written && "everything written on the Content page", evidenceCount && `${evidenceCount} uploaded screenshot${evidenceCount === 1 ? "" : "s"}`].filter(Boolean);
        if (losses.length && !await window.vrDialog.confirm({title: `Delete ${label}?`, message: `This also removes ${losses.join(" and ")}.`, confirmLabel: "Delete the finding", cancelLabel: "Keep it", tone: "danger"})) return;
        const previousEvidence = evidenceIdsIn(finding);
        report.vulnerabilities.splice(index, 1);
        dropUnreferencedEvidence(previousEvidence);
        renderFindings();
        scheduleSave();
      };
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
    if (foldAllFindings) foldAllFindings.onclick = () => {
      const collapsing = anyFindingExpanded();
      expandedFindingIds.clear();
      if (!collapsing) report.vulnerabilities.forEach(finding => expandedFindingIds.add(finding.uid));
      // Marks the default as spent, or the rebuild would re-open the first finding after a collapse.
      findingFoldDefaulted = true;
      renderFindings();
      updateFoldAllFindings();
    };
    updateFoldAllFindings();
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
      results.querySelectorAll("[data-id]").forEach(item => item.onclick = () => trackMutation(async () => {
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
      }));
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
      const requiredDates = [...root.querySelectorAll('#test-windows input[type="date"]')];
      const incompleteSetup = [...requiredMetadata, ...requiredDates].filter(input => !input?.value.trim());
      const missingEnvironment = !root.querySelector('#test-windows input[type="checkbox"]:checked');
      const missingScopePanels = [...root.querySelectorAll("#scope-grid .scope-panel")].filter(panel => ![...panel.querySelectorAll("textarea")].some(input => input.value.split("\n").some(value => value.trim() && !value.trimStart().startsWith("#"))));
      if (incompleteSetup.length || missingEnvironment || missingScopePanels.length) {
        if (reveal) {
          const setupNotice = document.querySelector("#setup-validation-note");
          if (setupNotice) setupNotice.dataset.validationAttempted = "true";
          incompleteSetup.forEach(input => input.classList.add("validation-error"));
          missingScopePanels.forEach(panel => panel.querySelectorAll("textarea").forEach(input => input.classList.add("validation-error")));
          const firstIncomplete = incompleteSetup[0] || missingScopePanels[0]?.querySelector("textarea");
          firstIncomplete?.scrollIntoView({behavior:"smooth", block:"center"});
          firstIncomplete?.focus({preventScroll:true});
          setSaveState(SAVE_STATES.UNSAVED, missingEnvironment ? "Select at least one test environment" : incompleteSetup.length ? "Complete the highlighted application details and testing dates" : "Define at least one scope target for each selected environment");
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
    const validateCurrentPage = root.dataset.step === "setup" ? validateSetupPage : validateFindingsPage;
    document.querySelector("#next").onclick = async event => {
      event.preventDefault();
      if (!validateCurrentPage(true)) return;
      await waitForMutations();
      const saved = await save();
      if (saved && document.querySelector("#save-button").dataset.saveState === SAVE_STATES.SAVED) {
        const nextPage = root.dataset.step === "setup" ? "findings" : "edit";
        window.location.assign(`/reports/${reportId}/${nextPage}`);
      }
    };
  }
  // Creates the minimum valid data structure for a requested fragment type.
  function newFragment(type) { const fragment = {frag_id:id("f"),type}; if (type === "paragraph" || type === "note") fragment.runs = []; else if (type.endsWith("list")) Object.assign(fragment,{items:[{runs:[]}],continue_numbering:false}); else if (type === "table") Object.assign(fragment,{header:[{runs:[]}],rows:[[{runs:[]}]]}); else if (type === "image") Object.assign(fragment,{evidence_id:null,caption:"",width_mm:null}); else if (type === "code_block") Object.assign(fragment,{caption:null,text:""}); else fragment.text=""; return fragment; }
  const EVIDENCE_ICONS = {
    image: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="m3 15 4.5-4.5a2 2 0 0 1 2.8 0L15 15"/><circle cx="15.5" cy="8.5" r="1.2"/></svg>',
    earlier: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 15l6-6 6 6"/></svg>',
    later: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
    replace: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/></svg>',
    browse: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h6l2 2h10v10H3z"/></svg>',
    remove: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16"/><path d="M9 6V4h6v2"/><path d="M6 6l1 14h10l1-14"/></svg>',
  };
  // One screenshot in an evidence set. Order is the fragment order, so the position control writes
  // straight into content.fragments and the report comes out in the order the tiles are shown.
  function renderEvidenceTile(fragment, content, rerender, finding, position) {
    const evidence = report.evidence?.[fragment.evidence_id];
    const tile = document.createElement("div");
    tile.className = `evidence-tile${evidence ? " has-evidence" : ""}`;
    tile.dataset.fragmentId = fragment.frag_id;
    tile.tabIndex = 0;
    tile.setAttribute("aria-label", `${contentNames[content.type]} screenshot ${position}, paste to attach`);
    const upload = document.createElement("input");
    upload.type = "file";
    upload.accept = "image/*";
    upload.id = `${fragment.frag_id}-upload`;
    upload.hidden = true;

    const uploadImage = selectedFile => trackMutation(async () => {
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
    });
    upload.onchange = () => {
      const selectedFile = upload.files?.[0];
      upload.value = "";
      uploadImage(selectedFile);
    };
    tile.onpaste = event => {
      const pasted = [...(event.clipboardData?.files || [])].find(item => item.type.startsWith("image/"));
      if (!pasted) return;
      event.preventDefault();
      uploadImage(pasted);
    };

    // Position is the one control a tester reaches for most, so it sits on the tile and takes
    // either a click or a drag.
    const spine = document.createElement("div");
    spine.className = "evidence-spine";
    const moveTile = offset => {
      const from = content.fragments.indexOf(fragment);
      const to = from + offset;
      if (to < 0 || to >= content.fragments.length || content.fragments[to].type !== "image") return;
      [content.fragments[from], content.fragments[to]] = [content.fragments[to], content.fragments[from]];
      rerender();
      scheduleSave();
    };
    const orderButton = (offset, label, glyph) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = offset < 0 ? "evidence-order-earlier" : "evidence-order-later";
      button.innerHTML = glyph;
      button.title = label;
      button.setAttribute("aria-label", `${label} screenshot ${position}`);
      button.tabIndex = -1;
      const neighbour = content.fragments[content.fragments.indexOf(fragment) + offset];
      button.disabled = !neighbour || neighbour.type !== "image";
      button.onclick = () => moveTile(offset);
      return button;
    };
    const number = document.createElement("span");
    number.className = "evidence-order-number";
    number.textContent = position;
    number.draggable = true;
    number.title = "Drag to reposition";
    number.ondragstart = event => { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/plain", fragment.frag_id); tile.classList.add("is-dragging"); };
    number.ondragend = () => tile.classList.remove("is-dragging");
    spine.append(number, orderButton(-1, "Move earlier", EVIDENCE_ICONS.earlier), orderButton(1, "Move later", EVIDENCE_ICONS.later));

    // Filled, the thumbnail is the way to inspect the screenshot at full size; empty, it is the
    // file picker. Either way it is the largest thing to aim at.
    const thumb = document.createElement(evidence ? "button" : "label");
    thumb.className = "evidence-thumb";
    if (evidence) {
      thumb.type = "button";
      thumb.title = evidence.original_name || "Open screenshot";
      thumb.setAttribute("aria-label", `Open screenshot ${position}`);
      const preview = document.createElement("img");
      preview.className = "image-preview";
      preview.src = `/reports/${reportId}/evidence/${fragment.evidence_id}`;
      preview.alt = evidence.original_name || "Uploaded evidence";
      preview.draggable = false;
      thumb.append(preview);
      thumb.onclick = () => {
        const dialog = document.createElement("dialog");
        dialog.className = "image-dialog";
        dialog.innerHTML = `<button class="subtle" type="button" aria-label="Close image">Close</button><img src="/reports/${reportId}/evidence/${fragment.evidence_id}" alt="${escape(evidence.original_name || "Uploaded evidence")}">`;
        dialog.querySelector("button").onclick = () => dialog.close();
        dialog.onclick = event => { if (event.target === dialog) dialog.close(); };
        dialog.onclose = () => dialog.remove();
        document.body.append(dialog);
        dialog.showModal();
      };
    } else {
      thumb.htmlFor = upload.id;
      thumb.innerHTML = `${EVIDENCE_ICONS.image}<span>Drop, paste<br>or click</span>`;
    }

    const meta = document.createElement("div");
    meta.className = "evidence-meta";
    const caption = document.createElement("input");
    caption.className = "evidence-caption";
    caption.value = fragment.caption || "";
    caption.placeholder = "Caption, printed under the figure";
    caption.setAttribute("aria-label", `Screenshot ${position} caption`);
    caption.oninput = () => { fragment.caption = caption.value; scheduleSave(); };
    const facts = document.createElement("div");
    facts.className = "evidence-facts";
    // A historical image is labelled with where it was found, so the current scope neither
    // narrows the choice nor answers it for the tester.
    const historical = content.type === "previous_proof_of_concept";
    const imageEnvironments = historical ? ["production", "non_production"] : affectedEnvironments(finding);
    if (!historical && imageEnvironments.length === 1) {
      fragment.environment = imageEnvironments[0];
      const environmentValue = document.createElement("span");
      environmentValue.className = "evidence-environment-value";
      environmentValue.textContent = imageEnvironments[0] === "production" ? "Production" : "Non-Production";
      facts.append(environmentValue);
    } else {
      if (!historical && !imageEnvironments.includes(fragment.environment)) fragment.environment = imageEnvironments[0] || null;
      const environmentSelect = document.createElement("select");
      environmentSelect.className = `evidence-environment${fragment.environment ? "" : " is-unset"}`;
      environmentSelect.setAttribute("aria-label", `${contentNames[content.type]} image environment`);
      const unset = historical && !fragment.environment ? '<option value="" selected>Select an environment</option>' : "";
      environmentSelect.innerHTML = unset + imageEnvironments.map(environment => `<option value="${environment}" ${fragment.environment === environment ? "selected" : ""}>${environment === "production" ? "Production" : "Non-Production"}</option>`).join("");
      environmentSelect.onchange = () => { fragment.environment = environmentSelect.value || null; rerender(); scheduleSave(); };
      facts.append(environmentSelect);
    }
    const size = document.createElement("small");
    size.className = "evidence-size";
    size.textContent = evidence ? `${evidence.width_px} x ${evidence.height_px}` : "No image yet";
    const acts = document.createElement("div");
    acts.className = "evidence-acts";
    const replace = document.createElement("label");
    replace.className = "evidence-replace";
    replace.htmlFor = upload.id;
    replace.innerHTML = evidence ? EVIDENCE_ICONS.replace : EVIDENCE_ICONS.browse;
    replace.title = evidence ? "Replace image" : "Browse for an image";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.innerHTML = EVIDENCE_ICONS.remove;
    remove.title = "Delete screenshot";
    remove.setAttribute("aria-label", `Delete screenshot ${position}`);
    const blockedReason = deletionBlockedReason(fragment, content, finding);
    if (blockedReason) {
      remove.disabled = true;
      remove.title = blockedReason;
    } else {
      remove.onclick = () => { content.fragments.splice(content.fragments.indexOf(fragment), 1); rerender(); scheduleSave(); };
    }
    acts.append(replace, remove);
    facts.append(size, acts);
    meta.append(caption, facts);

    const main = document.createElement("div");
    main.className = "evidence-main";
    main.append(thumb, meta);

    tile.ondragover = event => { event.preventDefault(); event.dataTransfer.dropEffect = event.dataTransfer.types.includes("Files") ? "copy" : "move"; tile.classList.add("is-drop-target"); };
    tile.ondragleave = () => tile.classList.remove("is-drop-target");
    tile.ondrop = event => {
      event.preventDefault();
      tile.classList.remove("is-drop-target");
      const droppedFile = [...(event.dataTransfer.files || [])].find(item => item.type.startsWith("image/"));
      if (droppedFile) { uploadImage(droppedFile); return; }
      const draggedId = event.dataTransfer.getData("text/plain");
      const from = content.fragments.findIndex(item => item.frag_id === draggedId);
      const to = content.fragments.indexOf(fragment);
      if (from < 0 || from === to || content.fragments[from].type !== "image") return;
      const [dragged] = content.fragments.splice(from, 1);
      content.fragments.splice(to, 0, dragged);
      rerender();
      scheduleSave();
    };
    tile.append(spine, main, upload);
    return tile;
  }
  // A run of adjacent image fragments, shown as one set so the screenshots read and reorder together.
  function renderEvidenceSet(images, content, rerender, finding) {
    const article = document.createElement("article");
    article.className = "fragment evidence-fragment";
    article.innerHTML = `<div class="fragment-head"><span class="tag">evidence</span><button class="fragment-move-up" type="button" aria-label="Move evidence up" title="Move up">&#8593;</button><button class="fragment-move-down" type="button" aria-label="Move evidence down" title="Move down">&#8595;</button></div>`;
    const first = content.fragments.indexOf(images[0]);
    const last = content.fragments.indexOf(images[images.length - 1]);
    // The whole run travels together, by stepping the one neighbouring fragment over it.
    const moveSet = offset => {
      const target = offset < 0 ? first - 1 : last + 1;
      if (target < 0 || target >= content.fragments.length) return;
      const [neighbour] = content.fragments.splice(target, 1);
      content.fragments.splice(offset < 0 ? last : first, 0, neighbour);
      rerender();
      scheduleSave();
    };
    const moveUp = article.querySelector(".fragment-move-up");
    const moveDown = article.querySelector(".fragment-move-down");
    moveUp.disabled = first === 0;
    moveDown.disabled = last === content.fragments.length - 1;
    moveUp.tabIndex = -1;
    moveDown.tabIndex = -1;
    moveUp.onclick = () => moveSet(-1);
    moveDown.onclick = () => moveSet(1);
    const set = document.createElement("div");
    set.className = "evidence-set";
    images.forEach((image, index) => set.append(renderEvidenceTile(image, content, rerender, finding, index + 1)));
    const add = document.createElement("button");
    add.type = "button";
    add.className = "evidence-add";
    add.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>Add another screenshot';
    add.onclick = () => {
      const image = newFragment("image");
      const environments = affectedEnvironments(finding);
      const existing = finding.contents.flatMap(item => item.fragments.filter(candidate => candidate.type === "image"));
      image.environment = environments.find(environment => !existing.some(candidate => candidate.environment === environment)) || environments[0] || null;
      content.fragments.splice(last + 1, 0, image);
      rerender();
      scheduleSave();
    };
    set.append(add);
    article.append(set);
    return article;
  }
  // Renders one content fragment with its type-specific editing controls.
  // How many items a continued list has to count past. The scan stops at the start of its own
  // section, which is what stops a proof of concept continuing the previous proof of concept.
  const numberingOffset = (fragment, content) => {
    const fragments = content?.fragments || [];
    const index = fragments.indexOf(fragment);
    if (index < 1 || !fragment.continue_numbering) return 0;
    let offset = 0;
    for (let scan = index - 1; scan >= 0; scan -= 1) {
      const earlier = fragments[scan];
      if (earlier.type !== "numbered_list") continue;
      offset += (earlier.items || []).filter(item => (item.runs || []).some(run => run.text?.trim())).length;
      // Keep walking only while that list is itself continuing something.
      if (!earlier.continue_numbering) break;
    }
    return offset;
  };
  function renderFragment(fragment, content, rerender, finding) {
    const card = document.createElement("article"); card.className="fragment"; card.dataset.fragmentId = fragment.frag_id; card.tabIndex = -1; card.innerHTML=`<div class="fragment-head"><button class="fragment-drag-handle" type="button" draggable="true" aria-label="Drag to reorder fragment" title="Drag to reorder">::</button><span class="tag">${fragment.type.replaceAll("_"," ")}</span><button class="fragment-move-up" type="button" aria-label="Move fragment up" title="Move up">&#8593;</button><button class="fragment-move-down" type="button" aria-label="Move fragment down" title="Move down">&#8595;</button><button class="danger fragment-delete" type="button" aria-label="Delete fragment" title="Delete">&#215;</button></div>`;
    const removeButton = card.querySelector(".danger");
    const blockedReason = deletionBlockedReason(fragment, content, finding);
    if (blockedReason) {
      removeButton.disabled = true;
      removeButton.title = blockedReason;
    } else {
      removeButton.onclick = () => { content.fragments.splice(content.fragments.indexOf(fragment), 1); rerender(); scheduleSave(); };
    }
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
      // Inserted from here, never from the shared head markup, so every other fragment head is
      // untouched. A label rather than a button: a head rule sizes every button to a 20px square.
      if (numbered) {
        const fragments = content?.fragments || [];
        const index = fragments.indexOf(fragment);
        const canContinue = fragments.slice(0, Math.max(index, 0)).some(earlier => earlier.type === "numbered_list");
        // A set flag is never hidden, even if the list it continued has since been deleted.
        if (canContinue || fragment.continue_numbering) {
          const toggle = document.createElement("label");
          toggle.className = "list-continue";
          toggle.classList.toggle("is-on", Boolean(fragment.continue_numbering));
          const box = document.createElement("input");
          box.type = "checkbox";
          box.checked = Boolean(fragment.continue_numbering);
          box.onchange = () => { fragment.continue_numbering = box.checked; rerender(); scheduleSave(); };
          toggle.append(box, document.createTextNode("Continue numbering"));
          toggle.title = fragment.continue_numbering
            ? `Continues the list above; this list starts at ${numberingOffset(fragment, content) + 1}.`
            : "Carry on from the numbers of the list above, instead of starting at 1.";
          card.querySelector(".fragment-head .tag").after(toggle);
        }
      }
      input.className = "list-textarea";
      input.setAttribute("aria-label", `${numbered ? "Numbered" : "Bulleted"} list items`);
      input.placeholder = "One item per line";
      input.rows = 1;
      input.value = fragment.items.map(item => item.runs.map(run => run.text).join("").replace(/\r?\n/g, " ")).join("\n");
      measure.className = "list-line-measure";
      editor.append(gutter, input, measure);
      const renderGutter = () => {
        // Read at paint time, never captured: the repaint below relies on a fresh count.
        let itemNumber = numberingOffset(fragment, content);
        renderLineMarkers(input, gutter, measure, line => line.trim() ? numbered ? `${++itemNumber}.` : "\u2022" : "", "list-marker");
      };
      // So a list can repaint the gutters of the ones continuing it without a pane rebuild.
      input.renderGutter = renderGutter;
      const repaintChain = () => {
        const fragments = content?.fragments || [];
        for (let scan = fragments.indexOf(fragment) + 1; scan > 0 && scan < fragments.length; scan += 1) {
          const later = fragments[scan];
          if (later.type !== "numbered_list") continue;
          if (!later.continue_numbering) break;
          card.parentElement?.querySelector(`[data-fragment-id="${later.frag_id}"] .list-textarea`)?.renderGutter?.();
        }
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
        repaintChain();
        changed();
      };
      // Bracketed by finalize so the strip is one undo step, not folded into the whole time the
      // tester spent in this field. oninput stays the only writer of fragment.items.
      input.onpaste = event => {
        const pasted = event.clipboardData?.getData("text/plain");
        if (!pasted) return;
        event.preventDefault();
        finalizeTextTransaction();
        const selectionStart = input.selectionStart;
        const lineStart = input.value.lastIndexOf("\n", selectionStart - 1) + 1;
        const startsItem = !input.value.slice(lineStart, selectionStart).trim();
        const cleaned = pasted.split(/\r?\n/)
          .map((line, index) => index || startsItem ? line.replace(LIST_MARKER_PREFIX, "") : line)
          .join("\n");
        input.setRangeText(cleaned, selectionStart, input.selectionEnd, "end");
        input.oninput();
        finalizeTextTransaction();
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
      // A structural edit redraws from the model, so anything on screen that has not reached it yet
      // would be dropped. Rendering order puts the header first, then each row left to right.
      const commitCells = () => {
        const cells = [...fragment.header, ...fragment.rows.flat()];
        [...table.querySelectorAll(".table-cell-input")].forEach((input, index) => {
          if (cells[index]) cells[index].runs = input.value ? [{text:input.value}] : [];
        });
      };
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
        removeButton.onclick = () => { commitCells(); fragment.rows.splice(rowIndex, 1); rerender(); changed(); };
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
      addRow.onclick = () => { commitCells(); fragment.rows.push(Array.from({length:columnCount}, () => ({runs:[]}))); rerender(); changed(); };
      const addColumn = document.createElement("button");
      addColumn.type = "button";
      addColumn.textContent = "Add column";
      addColumn.onclick = () => { commitCells(); fragment.header.push({runs:[]}); fragment.rows.forEach(row => row.push({runs:[]})); rerender(); changed(); };
      const removeColumn = document.createElement("select");
      removeColumn.className = "table-remove-select";
      removeColumn.setAttribute("aria-label", "Remove table column");
      removeColumn.disabled = columnCount === 1;
      removeColumn.innerHTML = `<option value="">Remove column...</option>${fragment.header.map((cell, index) => `<option value="${index}">Column ${index + 1}</option>`).join("")}`;
      removeColumn.onchange = () => {
        if (removeColumn.value === "") return;
        const columnIndex = Number(removeColumn.value);
        commitCells();
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
      // Images never reach here: the content loop routes each run of them to renderEvidenceSet.
      card.append(renderEvidenceTile(fragment, content, rerender, finding, 1));
    } else {
      const isCode = fragment.type === "code_block";
      const input = document.createElement("textarea");
      const label = isCode ? "Paste the command or response" : "Optional instance title here";
      input.className = isCode ? "code-block" : "instance-title-input";
      input.value = fragment.text || "";
      input.placeholder = label;
      input.setAttribute("aria-label", label);
      input.rows = 1;
      const fit = () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`; };
      fit();
      document.fonts?.ready.then(fit);
      input.oninput = () => { fragment.text = input.value; fit(); changed(); };
      card.append(input);
    }
    return card;
  }
  // Renders the current multi-finding content editor and its navigation rail.
  function continuousEditor() {
    const nav = document.querySelector("#finding-nav");
    const pane = document.querySelector("#finding-editor");
    // Pasting with nothing focused fills the first empty slot on screen; a card that took the paste itself has already cancelled it.
    document.addEventListener("paste", event => {
      if (event.defaultPrevented) return;
      pane?.querySelector('.content-block:not([data-content-type="previous_proof_of_concept"]) .evidence-tile:not(.has-evidence)')?.onpaste?.(event);
    });
    report.vulnerabilities.forEach(finding => { syncConclusion(finding); syncEvidenceImageSlots(finding); });
    let selectedFindingUid = report.vulnerabilities[0]?.uid;
    let expandedContentTypes;
    let engagementContextOpen = false;
    let reviewTargetId = null;
    // A `<details>` rendered `open` unconditionally springs back the moment an autosave rebuilds.
    const collapsedReviewGroups = new Set();
    // One shape for every library prompt, quieter than the section it offers to rewrite.
    const buildOffer = (className, message) => {
      const banner = document.createElement("div");
      banner.className = className;
      banner.innerHTML = '<svg class="offer-mark" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M3.6 2.4h5.7l3.1 3.1v8.1a1 1 0 0 1-1 1H3.6a1 1 0 0 1-1-1V3.4a1 1 0 0 1 1-1Z"/><path d="M9.2 2.4v3.2h3.2"/><path d="M5.3 9h5.4M5.3 11.4h3.6"/></svg><div class="offer-body"><p></p><div class="offer-actions"></div></div>';
      banner.querySelector("p").textContent = message;
      return {banner, body: banner.querySelector(".offer-body"), actions: banner.querySelector(".offer-actions")};
    };
    const offerButton = (label, kind, onclick) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = kind === "primary" ? "primary" : kind === "dismiss" ? "subtle offer-dismiss" : "subtle";
      button.textContent = label;
      button.onclick = onclick;
      return button;
    };
    // Held as state rather than left behind as a class, so a re-render cannot drop the highlight
    // before the tester has dealt with the field.
    const showReviewTarget = () => {
      pane.querySelectorAll(".is-review-target").forEach(node => node.classList.remove("is-review-target"));
      const target = reviewTargetId && pane.querySelector(`[data-fragment-id="${reviewTargetId}"]`);
      if (!target) return;
      target.classList.add("is-review-target");
    };
    const ordered = () => report.vulnerabilities.slice().sort((left, right) => severity.indexOf(left.severity) - severity.indexOf(right.severity) || left.title.localeCompare(right.title));
    const updateReadinessPanel = () => {
      const panel = document.querySelector("#editor-notifications");
      const count = document.querySelector("#issue-count");
      if (!panel || !count) return [];
      const hasText = runs => Array.isArray(runs) && runs.some(run => run.text?.trim());
      const placeholderPattern = /\(\s*insert[^)]*\)|insert\s+(technology|version|eol\s+date|cves|latest)\s+\w*\s*here/i;
      const fragmentText = fragment => {
        if (fragment.runs) return fragment.runs.map(run => run.text).join("");
        if (fragment.items) return fragment.items.flatMap(item => item.runs).map(run => run.text).join(" ");
        if (fragment.type === "table") return [...fragment.header, ...fragment.rows.flat()].flatMap(cell => cell.runs).map(run => run.text).join(" ");
        return [fragment.text, fragment.caption].filter(Boolean).join(" ");
      };
      const fragmentIssues = finding => {
        // An image for an environment this finding does not affect is not the tester's to complete.
        const relevant = affectedEnvironments(finding);
        const printed = contentTypesForStatus(finding.status);
        // Environments the per-environment rule already reports, so a slot serving one stays quiet.
        const proofImages = (finding.contents.find(content => content.type === "proof_of_concept")?.fragments || []).filter(fragment => fragment.type === "image");
        const uncovered = relevant.filter(environment => !proofImages.some(image => image.environment === environment && image.evidence_id));
        // A section this status does not print is carried for safekeeping, not for completing.
        return finding.contents.filter(content => printed.includes(content.type)).flatMap(content => {
        const contentLabel = contentNames[content.type];
        const missingFragment = requiresFragment.includes(content.type) && !content.fragments.length
          ? [{contentLabel, fragmentLabel:"at least one fragment", message:"is required"}]
          : [];
        return [...missingFragment, ...content.fragments.flatMap(fragment => {
        const issues = [];
        // Twin of report_service.fragment_applies: a stale image is neither the tester's to finish
        // nor ours to render, so nothing about it is reported, its caption included.
        const staleImage = fragment.type === "image" && content.type !== "previous_proof_of_concept"
          && Boolean(fragment.environment) && !relevant.includes(fragment.environment);
        if (staleImage) return issues;
        // Twin of the in_conclusion rule in docx_report.generation_issues. Carries a fragmentId so
        // the review panel's arrow lands on the paragraph and the field is marked incomplete.
        // Nothing but the sentence counts; text either side of it is the tester's own conclusion.
        if (content.type === "in_conclusion" && isDefaultStatusConclusion(fragment)) {
          issues.push({contentLabel, fragmentLabel:optionLabel("paragraph"), message:"still holds the default sentence", fragmentId:fragment.frag_id});
          return issues;
        }
        if (fragment.runs && !hasText(fragment.runs)) issues.push({contentLabel, fragmentLabel:optionLabel(fragment.type), message:"text is required", fragmentId:fragment.frag_id});
        if (fragment.items) {
          // Steps are one textarea, so a per-line message would point at a field the tester cannot see.
          const steps = content.type.endsWith("proof_of_concept") && fragment.type === "numbered_list";
          if (steps) { if (fragment.items.some(item => !hasText(item.runs))) issues.push({contentLabel, fragmentLabel:"Steps to reproduce", message:"requires text", fragmentId:fragment.frag_id}); }
          else issues.push(...fragment.items.flatMap((item, itemIndex) => hasText(item.runs) ? [] : [{contentLabel, fragmentLabel:`item ${itemIndex + 1}`, message:"text is required", fragmentId:fragment.frag_id}]));
        }
        if (fragment.type === "table") {
          const cells = [...fragment.header, ...fragment.rows.flat()];
          if (cells.some(cell => !hasText(cell.runs))) issues.push({contentLabel, fragmentLabel:"table", message:"every cell is required", fragmentId:fragment.frag_id});
        }
        if (fragment.type === "image" && (content.type === "previous_proof_of_concept" || !fragment.environment || relevant.includes(fragment.environment))) {
          const environment = fragment.environment === "production" ? "Production" : fragment.environment === "non_production" ? "Non-Production" : "Unassigned";
          const missing = [!fragment.environment && "environment", !fragment.evidence_id && "image", !fragment.caption?.trim() && "caption"].filter(Boolean);
          // "Production evidence image required" already names this slot; listing its parts repeats it.
          const alreadyNamed = content.type === "proof_of_concept" && !fragment.evidence_id && uncovered.includes(fragment.environment);
          if (missing.length && !alreadyNamed) issues.push({contentLabel, fragmentLabel:`${environment} evidence`, message:`requires ${missing.join(" and ")}`, fragmentId:fragment.frag_id, evidenceSlot:true});
        }
        if (!fragment.runs && !fragment.items && fragment.type !== "table" && fragment.type !== "image" && fragment.type !== "instance_title" && !fragment.text?.trim()) issues.push({contentLabel, fragmentLabel:optionLabel(fragment.type), message:"text is required", fragmentId:fragment.frag_id});
        if (placeholderPattern.test(fragmentText(fragment))) issues.push({contentLabel, fragmentLabel:optionLabel(fragment.type), message:"replace placeholder text", fragmentId:fragment.frag_id, level:"warning"});
        return issues;
        })];
        });
      };
      const issues = report.vulnerabilities.flatMap(finding => {
        const label = finding.title || "Untitled finding";
        const missing = [];
        if (!finding.title?.trim()) missing.push("finding name");
        if (![finding.likelihood, finding.impact, finding.severity, finding.status].every(Boolean)) missing.push("assessment details");
        if (!scopeHasLocation(finding)) missing.push("affected location");
        const proof = finding.contents.find(content => content.type === "proof_of_concept");
        const images = (proof?.fragments || []).filter(fragment => fragment.type === "image");
        const missingEvidence = affectedEnvironments(finding).filter(environment => !images.some(image => image.environment === environment && image.evidence_id));
        const environmentIssues = missingEvidence.map(environment => {
          const slot = images.find(image => image.environment === environment && !image.evidence_id);
          return {
            finding,
            contentType: "proof_of_concept",
            contentLabel: contentNames.proof_of_concept,
            fragmentLabel: "evidence",
            // Points at the slot the tester has to fill, so the jump lands on the tile and not the section.
            fragmentId: slot?.frag_id,
            evidenceSlot: true,
            message: `${environment === "production" ? "Production" : "Non-Production"} evidence image required`,
          };
        });
        // Ordered by section so every proof of concept row sits with the others.
        const order = ["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"];
        const rank = issue => {
          const type = issue.contentType || Object.keys(contentNames).find(key => contentNames[key] === issue.contentLabel);
          const index = order.indexOf(type);
          return index < 0 ? -1 : index;
        };
        const perFinding = [...environmentIssues, ...fragmentIssues(finding).map(issue => ({finding, ...issue}))]
          .sort((left, right) => rank(left) - rank(right));
        return [...(missing.length ? [{finding, message:missing.join(", ")}] : []), ...perFinding];
      });
      count.textContent = issues.length ? `${issues.length} to fill in` : "Ready";
      count.dataset.state = issues.length ? "issues" : "ready";
      // Empty evidence slots are never ringed, and a jump silences the rest so it stands alone.
      const incomplete = reviewTargetId ? new Set() : new Set(issues
        .filter(issue => issue.fragmentId && !issue.evidenceSlot && (issue.level || "error") === "error")
        .map(issue => issue.fragmentId));
      pane.querySelectorAll("[data-fragment-id]").forEach(node => node.classList.toggle("is-incomplete", incomplete.has(node.dataset.fragmentId)));
      // Each section carries its own count, so a tester scrolling the page sees the gap without the panel.
      const typeByLabel = Object.fromEntries(Object.entries(contentNames).map(([type, label]) => [label, type]));
      const openByType = {};
      issues.filter(issue => issue.finding?.uid === selectedFindingUid).forEach(issue => {
        const type = issue.contentLabel ? typeByLabel[issue.contentLabel] : (/evidence image required/.test(issue.message) ? "proof_of_concept" : null);
        if (type) openByType[type] = (openByType[type] || 0) + 1;
      });
      pane.querySelectorAll("[data-content-type]").forEach(block => {
        const flag = block.querySelector(".content-flag");
        if (!flag) return;
        const open = openByType[block.dataset.contentType] || 0;
        flag.hidden = !open;
        flag.textContent = open ? `${open} to fill in` : "";
      });
      const generateButton = document.querySelector("#generate-report");
      if (generateButton) {
        generateButton.disabled = Boolean(issues.length) || generateButton.dataset.busy === "true";
        generateButton.title = issues.length ? "Fill in the remaining details before generating" : "Generate Word report";
      }
      // One card per finding, so a finding with five gaps reads as one row rather than five.
      // Library offers ride along as warnings: they are suggestions, so they are listed but never
      // counted, or the verdict and the Generate button would disagree with the server.
      const offers = report.vulnerabilities.flatMap(finding => pendingLibraryOffers(finding).map(offer => ({
        finding,
        level: "warning",
        suggestion: true,
        contentType: offer.type,
        contentLabel: contentNames[offer.type],
        fragmentLabel: offer.variants ? `saved ${offer.variants.map(variant => channelLabels[variant]).join(" and ")} steps` : "saved library content",
        message: "can be used or dismissed",
      })));
      const rows = [...issues, ...offers];
      const groups = [];
      rows.forEach(row => {
        const group = groups.find(candidate => candidate.finding === row.finding);
        if (group) group.issues.push(row);
        else groups.push({finding:row.finding, issues:[row]});
      });
      const renderGroup = group => {
        const errors = group.issues.filter(issue => (issue.level || "error") === "error").length;
        const level = errors ? "error" : "warning";
        const cells = group.issues.map(({finding, message, fragmentId, contentType, contentLabel, fragmentLabel, level: rowLevel, suggestion}) => {
          const target = `data-review-finding="${escape(finding.uid)}"${fragmentId ? ` data-review-fragment="${escape(fragmentId)}"` : ""}${contentType ? ` data-review-content="${escape(contentType)}"` : ""}`;
          return `<tr class="review-row" data-level="${rowLevel || "error"}"><td class="review-content"><i aria-hidden="true"></i>${escape(contentLabel || "Finding")}${fragmentLabel ? `<small>${escape(fragmentLabel)}</small>` : ""}</td><td class="review-need">${suggestion ? '<em class="review-tag">Suggested</em>' : ""}${escape(message)}</td><td class="review-arrow"><button type="button" ${target} title="Go to" aria-label="Go to ${escape(contentLabel || "finding")}">&#8594;</button></td></tr>`;
        }).join("");
        // Suggestions are never counted with gaps, or the badge would disagree with the Generate button.
        return `<details class="review-group" data-level="${level}" data-review-group="${escape(group.finding.uid)}"${collapsedReviewGroups.has(group.finding.uid) ? "" : " open"}><summary><span class="review-caret" aria-hidden="true"></span><span class="review-group-title">${escape(group.finding.title || "Untitled finding")}</span><span class="review-group-count" data-level="${level}">${errors || group.issues.length}</span></summary><table class="review-table"><thead><tr><th>Content</th><th>Needs</th><th></th></tr></thead><tbody>${cells}</tbody></table></details>`;
      };
      panel.innerHTML = rows.length
        ? groups.map(renderGroup).join("")
        : '<div class="review-empty">Every finding is complete. The report is ready to generate.</div>';
      const foldAllReview = document.querySelector("#review-fold-all");
      const reviewGroups = [...panel.querySelectorAll(".review-group")];
      const updateFoldAllReview = () => {
        if (!foldAllReview) return;
        foldAllReview.hidden = !reviewGroups.length;
        const open = reviewGroups.some(group => group.open);
        const label = open ? "Collapse all" : "Expand all";
        foldAllReview.setAttribute("aria-label", label);
        foldAllReview.title = label;
        foldAllReview.setAttribute("aria-pressed", String(!open));
      };
      reviewGroups.forEach(group => {
        // `toggle` fires a tick late; a save landing in that gap would rebuild from stale state.
        group.querySelector("summary").addEventListener("click", () => {
          if (group.open) collapsedReviewGroups.add(group.dataset.reviewGroup);
          else collapsedReviewGroups.delete(group.dataset.reviewGroup);
        });
        group.addEventListener("toggle", updateFoldAllReview);
      });
      if (foldAllReview) foldAllReview.onclick = () => {
        const collapsing = reviewGroups.some(group => group.open);
        // `toggle` fires asynchronously, so the set is written here too or a save landing in the
        // same tick rebuilds the panel from stale state.
        reviewGroups.forEach(group => {
          group.open = !collapsing;
          if (collapsing) collapsedReviewGroups.add(group.dataset.reviewGroup);
          else collapsedReviewGroups.delete(group.dataset.reviewGroup);
        });
        updateFoldAllReview();
      };
      updateFoldAllReview();
      // The whole row is the target; the arrow stays a real button so keyboard and AT still reach it.
      panel.querySelectorAll(".review-row").forEach(row => {
        row.onclick = event => {
          if (event.target.closest("button")) return;
          row.querySelector("[data-review-finding]")?.click();
        };
      });
      panel.querySelectorAll("[data-review-finding]").forEach(button => button.onclick = () => {
        const findingUid = button.dataset.reviewFinding;
        const fragmentId = button.dataset.reviewFragment;
        const contentType = button.dataset.reviewContent;
        reviewTargetId = fragmentId || null;
        let rerender = false;
        if (selectedFindingUid !== findingUid) {
          selectedFindingUid = findingUid;
          expandedContentTypes = undefined;
          rerender = true;
        }
        // A collapsed section hides the banner the tester was just sent to.
        if (contentType && expandedContentTypes && !expandedContentTypes.has(contentType)) {
          expandedContentTypes.add(contentType);
          rerender = true;
        }
        if (rerender) render();
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            const target = fragmentId ? pane.querySelector(`[data-fragment-id="${fragmentId}"]`)
              : contentType ? pane.querySelector(`[data-offer-for="${contentType}"]`) || pane.querySelector(`[data-content-type="${contentType}"]`)
              : document.getElementById(`finding-${findingUid}`);
            target?.scrollIntoView({behavior:"smooth", block:"center"});
            target?.focus?.({preventScroll:true});
            showReviewTarget();
            updateReadinessPanel();
          });
        });
      });
      return issues;
    };
    document.addEventListener("reportchange", updateReadinessPanel);
    // The jump marker is a pointer, not a verdict: it lets go when the tester looks elsewhere.
    document.addEventListener("click", event => {
      if (!reviewTargetId) return;
      // A click in the panel is how a jump is asked for, so it must not undo the one just made.
      if (event.target.closest("#editor-notifications, .is-review-target")) return;
      reviewTargetId = null;
      showReviewTarget();
      updateReadinessPanel();
    });
    // The banners are pure functions of current state, so they can be rebuilt without redrawing the
    // pane. Declared out here, taking the finding explicitly, so both render() and the refresh below
    // produce byte-identical nodes from one source.
    let contentOffersFor = () => [];
    // render() is the only thing that rebuilds the pane, and typing never calls it -- deliberately,
    // because it would destroy the caret. Without this, an offer earned by an edit waited for a
    // section toggle or a reload. reportchange already fires 100ms after every keystroke.
    const refreshContentOffers = () => {
      // Never while a field has focus: it covers the caret's own block and, because description sits
      // beside remediation in one grid row, the sibling that would otherwise move it.
      if (activeTextEntry()) return;
      const finding = report.vulnerabilities.find(candidate => candidate.uid === selectedFindingUid);
      if (!finding) return;
      pane.querySelectorAll(".content-block.is-expanded").forEach(block => {
        const content = finding.contents?.find(candidate => candidate.type === block.dataset.contentType);
        if (!content) return;
        const existing = [...block.querySelectorAll(":scope > .content-offer, :scope > .poc-offer")];
        const fresh = contentOffersFor(finding, content);
        // Replacing an unchanged banner would swap a button out from under a click.
        if (existing.map(node => node.outerHTML).join("") === fresh.map(node => node.outerHTML).join("")) return;
        existing.forEach(node => node.remove());
        const anchor = block.querySelector(":scope > .content-toggle");
        if (anchor && fresh.length) anchor.after(...fresh);
      });
    };
    document.addEventListener("reportchange", refreshContentOffers);
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
          const newFinding = {uid:id("v"), title:"", severity:"informational", status:"open_new", scope:{mode:"custom",target_ids:[],location_values:{},custom_locations:{}}, contents:[]};
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
      navHeading.innerHTML = `<b>Findings</b><span class="nav-count">${findings.length}</span>`;
      nav.append(navHeading);
      findings.forEach(finding => {
        const findingId = `finding-${finding.uid}`;
        const jump = document.createElement("button");
        jump.className = `finding-nav severity-${finding.severity || "informational"}${finding.uid === selectedFindingUid ? " active" : ""}`;
        jump.dataset.findingId = findingId;
        jump.innerHTML = `<span class="finding-nav-title">${escape(finding.title || "Untitled finding")}</span><span class="finding-nav-meta"><em>${escape(finding.severity || "informational")}</em><i aria-hidden="true">&middot;</i><span>${escape(finding.display_id || "No ID")}</span></span>`;
        jump.onclick = () => { selectedFindingUid = finding.uid; expandedContentTypes = undefined; render(); };
        nav.append(jump);
        // A long list can leave the open finding scrolled out of the rail, which is the other half
        // of losing track of it. Scrolled by hand rather than with scrollIntoView, which would move
        // every scrollable ancestor too and undo the pane position render() has just restored.
        if (finding.uid === selectedFindingUid) requestAnimationFrame(() => {
          const item = jump.getBoundingClientRect();
          const rail = nav.getBoundingClientRect();
          if (item.top < rail.top) nav.scrollTop -= rail.top - item.top;
          else if (item.bottom > rail.bottom) nav.scrollTop += item.bottom - rail.bottom;
        });
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
        return `<div class="engagement-context-env"><b>${escape(contextLabels[environment])}</b><small>${escape(dates)} &middot; ${escape(testWindow.test_time || "Anytime")}</small>${list}</div>`;
      }).join("");
      context.innerHTML = `<summary>Engagement scope</summary><div class="engagement-context-body">${body || `<p class="engagement-context-empty">No environments selected</p>`}</div>`;
      const selectedFinding = findings.find(finding => finding.uid === selectedFindingUid);
      nav.append(context);
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
        if (finding.scope?.mode === "custom") Object.entries(finding.scope?.custom_locations || {}).forEach(([environment, byChannel]) => locationsByEnvironment[environment]?.push(...Object.values(byChannel || {}).flat().filter(value => value.trim())));
        const locationGroups = [["production", "Production"], ["non_production", "Non-Production"]]
          .filter(([environment]) => locationsByEnvironment[environment].length)
          .map(([environment, label]) => {
            const values = locationsByEnvironment[environment];
            const summary = `${values.length} endpoint${values.length === 1 ? "" : "s"}`;
            // The full list is the chip's own accessible name too, so the hover popover stays a convenience.
            return `<span class="fchip fchip-locations" tabindex="0" aria-label="${escape(label)}: ${escape(values.join(", "))}">${label} &middot; ${summary}<span class="fchip-pop" aria-hidden="true"><b>${label}</b><ul>${values.map(value => `<li>${escape(value)}</li>`).join("")}</ul></span></span>`;
          })
          .join("");
        const severityWord = finding.severity || "informational";
        const statusWord = statuses.find(status => status[0] === finding.status)?.[1] || finding.status;
        box.innerHTML = `<header class="finding-header"><div class="section-title finding-title"><h1>${escape(finding.title || "Untitled finding")}</h1></div><div class="finding-chips"><span class="fchip fchip-sev" data-severity="${escape(severityWord)}"><i aria-hidden="true"></i>${escape(severityWord)}</span><span class="fchip">Likelihood <b>${escape(finding.likelihood || "not set")}</b></span><span class="fchip">Impact <b>${escape(finding.impact || "not set")}</b></span><span class="fchip">${escape(statusWord)}</span><span class="fchip fchip-mono">${escape(finding.display_id || "No ID")}</span>${locationGroups || '<span class="fchip">No locations</span>'}</div></header>`;
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
          const finishTitle = async () => {
            if (titleCommitted) return;
            titleCommitted = true;
            const conclusionBefore = conclusionParagraphText(finding);
            finding.title = titleInput.value.trim();
            syncConclusion(finding);
            await offerConclusionRewrite(finding, conclusionBefore);
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
                if (entry) { titleInput.value = entry.title; finishTitle(); }
              };
            });
          };
          titleInput.oninput = renderResults;
          titleInput.onfocus = renderResults;
          titleInput.onkeydown = event => { if (event.key === "Enter") finishTitle(); if (event.key === "Escape") clearResults(); };
          titleInput.onblur = () => setTimeout(finishTitle, 150);
        };
        if (expandedContentTypes === undefined) expandedContentTypes = new Set(finding.contents.map(content => content.type));
        // Pure function of current state, so render() and the reportchange refresh build the
        // same nodes. Returns them rather than appending, which is what lets the refresh
        // replace only the banners without redrawing the section around them.
        contentOffersFor = (finding, content) => {
          const nodes = [];
          // Both can show at once. Order mirrors the paragraphs they produce: quoted step above,
          // standard sentence below, so the pair reads as a preview of the finished section.
          if (content.type === "in_conclusion" && contentTypesForStatus(finding.status).includes("in_conclusion")) {
            const resolved = finding.conclusion_offer_resolved || [];
            const lastStep = pocLastStep(finding);
            // A conclusion still holding nothing but the standard sentence holds nothing the tester
            // chose, so a step they answered against an older conclusion no longer describes anything.
            const onlyDefault = content.fragments.length === 1 && hasDefaultStatusConclusion(content.fragments[0]) && isDefaultStatusConclusion(content.fragments[0]);
            const stepKey = `${finding.uid}|${lastStep}`;
            if (lastStep && !dismissedStepOffers.has(stepKey) && (onlyDefault || !resolved.includes(lastStep))) {
              const first = content.fragments.find(fragment => fragment.type === "paragraph");
              const firstText = first ? conclusionText(first) : "";
              const sentenceStart = first ? defaultConclusionStart(firstText) : -1;
              const prefix = sentenceStart >= 0 ? firstText.slice(0, sentenceStart).trimEnd() : firstText;
              // Only a paragraph still holding a line this banner wrote is replaced; once the tester
              // edits it, it is theirs and a corrected step is inserted as a new one instead.
              const quoted = first && resolved.includes(prefix) ? first : null;
              const resolve = write => {
                if (write && first && sentenceStart >= 0 && (!prefix || quoted)) {
                  first.runs = [{text:`${lastStep} `}, ...runsAfter(first.runs || [], sentenceStart)];
                }
                else if (write && quoted) quoted.runs = [{text:lastStep}];
                else if (write) content.fragments.unshift(Object.assign(newFragment("paragraph"), {runs:[{text:lastStep}]}));
                if (!write) dismissedStepOffers.add(stepKey);
                finding.conclusion_offer_resolved = [...new Set([...resolved, lastStep])];
                render();
                scheduleSave();
              };
              const {banner, actions} = buildOffer("content-offer", `Start the conclusion with your last step: "${lastStep}"`);
              banner.dataset.conclusionStep = lastStep;
              actions.append(
                offerButton(quoted ? "Update the quoted step" : "Use it", "primary", () => resolve(true)),
                offerButton("Dismiss", "dismiss", () => resolve(false)),
              );
              nodes.push(banner);
            }
            const emptied = content.fragments.filter(fragment => fragment.type === "paragraph" && !fragmentHasText(fragment));
            if (emptied.length && !content.fragments.some(hasDefaultStatusConclusion)) {
              const {banner, actions} = buildOffer("content-offer", "The standard closing sentence is missing. Put it back as a starting point; you will still need to replace it with your own wording before generating.");
              banner.dataset.conclusionRestore = "";
              actions.append(offerButton("Put it back", "primary", () => {
                emptied[emptied.length - 1].runs = statusConclusionRuns(finding.title, finding.status === "resolved" ? "Resolved" : "Open");
                // Back to boilerplate means the conclusion holds nothing the tester chose, so an
                // earlier "not that step" no longer describes anything and the offer starts over.
                finding.conclusion_offer_resolved = [];
                render();
                scheduleSave();
              }));
              nodes.push(banner);
            }
            const writtenParagraphs = content.fragments.filter(fragment => fragment.type === "paragraph" && fragmentHasText(fragment));
            // Written, but not stating where the finding landed. Offered, never written for them:
            // their wording is the conclusion, and only they can say whether it is kept.
            if (!emptied.length && writtenParagraphs.length && !content.fragments.some(hasDefaultStatusConclusion) && !dismissedSentenceOffers.has(finding.uid)) {
              const {banner, actions} = buildOffer("content-offer", "This conclusion does not state whether the finding is open or resolved.");
              banner.dataset.conclusionSentence = "";
              const target = writtenParagraphs[writtenParagraphs.length - 1];
              const apply = mode => {
                const sentence = statusConclusionRuns(finding.title, finding.status === "resolved" ? "Resolved" : "Open");
                target.runs = mode === "replace" ? sentence : [...(target.runs || []), {text:" "}, ...sentence];
                if (mode === "replace") finding.conclusion_offer_resolved = [];
                render();
                scheduleSave();
              };
              actions.append(
                offerButton("Add it to the end", "primary", () => apply("append")),
                offerButton("Replace what I wrote", "subtle", () => apply("replace")),
                offerButton("Dismiss", "dismiss", () => { dismissedSentenceOffers.add(finding.uid); render(); }),
              );
              nodes.push(banner);
            }
          }
          if (content.type === "proof_of_concept") {
            // Derived from current state, so it survives a reload and can never double-fire or leak a missed event.
            const offered = pendingLibraryOffers(finding).find(offer => offer.type === "proof_of_concept")?.variants || [];
            if (offered.length) {
              const written = pocHasWrittenSteps(finding);
              const chosen = new Set(offered);
              const {banner, body, actions} = buildOffer("poc-offer", offered.length === 1
                ? `Saved ${channelLabels[offered[0]]} steps are available for this finding.`
                : `This finding affects ${offered.map(variant => channelLabels[variant]).join(" and ")}. Saved steps exist for both; they arrive as one list you can edit.`);
              banner.dataset.pocOffer = offered.join(" ");
              banner.dataset.offerFor = content.type;
              const install = mode => {
                const picked = offered.filter(variant => chosen.has(variant));
                applyPocVariant(finding, picked.flatMap(variant => pocStepsFor(finding, variant) || []), picked, mode);
                render();
                scheduleSave();
              };
              const accept = offerButton(written ? "Use saved steps" : "Fill from library", "primary", () => install("replace"));
              const add = offerButton("Add below", "subtle", () => install("merge"));
              const refuse = offerButton(written ? "Keep mine" : "Dismiss", "dismiss", () => {
                finding.poc_variant_declined = [...new Set([...(finding.poc_variant_declined || []), ...offered])];
                render();
                scheduleSave();
              });
              if (offered.length > 1) {
                const picker = document.createElement("div");
                picker.className = "offer-channels";
                offered.forEach(variant => {
                  const toggle = document.createElement("button");
                  toggle.type = "button";
                  toggle.textContent = channelLabels[variant];
                  toggle.setAttribute("aria-pressed", "true");
                  toggle.setAttribute("aria-label", `Include ${channelLabels[variant]} steps`);
                  toggle.onclick = () => {
                    const on = toggle.getAttribute("aria-pressed") !== "true";
                    toggle.setAttribute("aria-pressed", String(on));
                    if (on) chosen.add(variant); else chosen.delete(variant);
                    accept.disabled = add.disabled = !chosen.size;
                  };
                  picker.append(toggle);
                });
                body.insertBefore(picker, actions);
              }
              actions.append(accept, add, refuse);
              nodes.push(banner);
            }
          }
          if (content.type === "description" || content.type === "recommended_remediation") {
            // Derived from current state, like the proof-of-concept offer: survives a reload, never double-fires.
            const offer = pendingLibraryOffers(finding).find(candidate => candidate.type === content.type);
            if (offer) {
              const entry = offer.entry;
              const libraryFragments = libraryContentFor(entry, content.type);
              const written = content.fragments.some(fragment => fragmentHasContent(fragment));
              const resolve = mode => {
                const previousEvidence = mode === "replace" ? evidenceIdsIn(finding) : null;
                (finding.content_offer_resolved ||= {})[content.type] = entry.library_id;
                if (mode !== "keep") {
                  const copied = remintFragments(libraryFragments);
                  content.fragments = mode === "replace" ? copied : [...(written ? content.fragments : []), ...copied];
                }
                if (previousEvidence) dropUnreferencedEvidence(previousEvidence);
                // Recorded after the mutation, so the rule reads as one sentence: the banner
                // remembers what the section looked like when the tester left it. "Add below"
                // needs it most, since merged content still differs from the entry.
                (finding.content_offer_dismissed ||= {})[content.type] = sectionFingerprint(content.fragments);
                render();
                scheduleSave();
              };
              const {banner, actions} = buildOffer("content-offer", `The library has a saved ${contentNames[content.type]} for this finding.`);
              banner.dataset.contentOffer = content.type;
              banner.dataset.offerFor = content.type;
              actions.append(
                offerButton(written ? "Use library version" : "Fill from library", "primary", () => resolve("replace")),
                offerButton("Add below", "subtle", () => resolve("merge")),
                offerButton(written ? "Keep mine" : "Dismiss", "dismiss", () => resolve("keep")),
              );
              nodes.push(banner);
            }
          }
          return nodes;
        };
        const buildContentBlock = content => {
          const block = document.createElement("div");
          const isExpanded = expandedContentTypes.has(content.type);
          block.className = `content-block${isExpanded ? " is-expanded" : ""}`;
          block.dataset.contentType = content.type;
          const heading = document.createElement("button");
          heading.className = "content-toggle";
          heading.type = "button";
          heading.setAttribute("aria-expanded", String(isExpanded));
          heading.innerHTML = `<span>${contentNames[content.type]}</span><span class="content-flag" aria-hidden="true" hidden></span><small>${content.fragments.length} fragment${content.fragments.length === 1 ? "" : "s"}</small>`;
          // Rebuilding the pane loses the reading position, so the toggled block is put back where it sat.
          heading.onclick = () => {
            const paneTop = pane.getBoundingClientRect().top;
            const anchor = Math.max(block.getBoundingClientRect().top - paneTop, 0);
            if (isExpanded) expandedContentTypes.delete(content.type); else expandedContentTypes.add(content.type);
            render();
            const moved = pane.querySelector(`[data-content-type="${content.type}"]`);
            if (!moved) return;
            pane.scrollTop += moved.getBoundingClientRect().top - paneTop - anchor;
            moved.querySelector(".content-toggle")?.focus({preventScroll:true});
          };
          block.append(heading);
          if (!isExpanded) return block;
          block.append(...contentOffersFor(finding, content));
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
            const locked = document.createElement("p");
            locked.className = "content-locked";
            locked.textContent = "Locked for resolved findings. The remediation reads \u201cNone, the vulnerability has been remediated.\u201d";
            block.append(locked);
          } else {
            for (let index = 0; index < content.fragments.length; index += 1) {
              if (content.fragments[index].type !== "image") { block.append(renderFragment(content.fragments[index], content, render, finding)); continue; }
              const run = [];
              while (index < content.fragments.length && content.fragments[index].type === "image") { run.push(content.fragments[index]); index += 1; }
              index -= 1;
              block.append(renderEvidenceSet(run, content, render, finding));
            }
            appendFragmentMenu();
          }
          return block;
        };
        // Description sits beside its remediation, and on a retest last year's proof sits beside
        // this year's, because those are the pairs a reader compares. Everything else runs full width.
        // A section this status does not print is carried for safekeeping and stays out of the page.
        const printedContents = finding.contents.filter(content => contentTypesForStatus(finding.status).includes(content.type));
        const blocks = new Map(printedContents.map(content => [content.type, buildContentBlock(content)]));
        const paired = new Set();
        const pairUp = (left, right) => {
          const first = blocks.get(left);
          const second = blocks.get(right);
          if (!first || !second) return;
          const row = document.createElement("div");
          row.className = "content-row";
          row.append(first, second);
          box.append(row);
          paired.add(left);
          paired.add(right);
        };
        pairUp("description", "recommended_remediation");
        pairUp("previous_proof_of_concept", "proof_of_concept");
        printedContents.forEach(content => {
          if (!paired.has(content.type)) box.append(blocks.get(content.type));
        });
        pane.append(box);
      });
      updateReadinessPanel();
      showReviewTarget();
      if (focusedFindingUid) {
        requestAnimationFrame(() => { const focusedFinding = document.getElementById(`finding-${focusedFindingUid}`); focusedFinding?.scrollIntoView({behavior:"smooth", block:"start"}); focusedFinding?.focus({preventScroll:true}); });
      } else if (restoreScroll) {
        pane.scrollTop = restoreScroll;
      }
    };
    render();
  }
  root.id === "setup" ? setup() : continuousEditor();
  updateSetupSectionSummaries();
  updateEngagementName(serverReport);
})();
