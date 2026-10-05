// The report pages' save code; docs/DATA_MAP.md §9 and §10 describe it.
(() => {
  const clone = value => JSON.parse(JSON.stringify(value));
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
  const activeTextEntry = () => {
    const activeElement = document.activeElement;
    return activeElement?.matches('input:not([type="checkbox"],[type="radio"],[type="file"]), textarea, [contenteditable="true"]') ? activeElement : null;
  };
  // app.js calls this once per report page; it returns the report the page edits, the server's or a recovery copy.
  function start({root, serverReport, saveCheck, onSaved}) {
    const diagnostics = window.VulnReportDiagnostics;
    const reportId = serverReport.report_id;
    let report = serverReport;
    const localDraftPrefix = `vulnreport-pending:${reportId}`;
    const recoverySelectionKey = `vulnreport-recovery:${reportId}`;
    const tabRevisionKey = `vulnreport-saved-at:${reportId}`;
    const timestampMicros = value => {
      const milliseconds = Date.parse(value);
      if (!Number.isFinite(milliseconds)) return 0;
      const submillisecond = String(value).match(/\.\d{3}(\d{1,3})/)?.[1] || "";
      return milliseconds * 1000 + Number(submillisecond.padEnd(3, "0"));
    };
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
      }).sort((left, right) => timestampMicros(right.envelope.capturedAt) - timestampMicros(left.envelope.capturedAt));
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
    if (!Array.isArray(report.scope_targets)) report.scope_targets = clone(serverReport.scope_targets || []);
    if (!Array.isArray(report.vulnerabilities)) report.vulnerabilities = clone(serverReport.vulnerabilities || []);
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
    let pendingScopeDecision = false;
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
        if (!remembered || timestampMicros(savedAt) > timestampMicros(remembered)) sessionStorage.setItem(tabRevisionKey, savedAt);
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
        // Removing an evidence record here lets the next save prune its file, and a redo restores the
        // record pointing at a file nothing can bring back. Records are dropped by explicit action.
        if (!present && change.path[0] === "evidence" && change.path.length === 2) return;
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
    function holdSaves(held) {
      pendingScopeDecision = held;
    }
    function hasUnsavedEdits() {
      return pendingSave || savedRevision < saveRevision;
    }
    // Sends the current report object to the server for validation and atomic saving.
    async function save(successStatus) {
      if (saveConflict) {
        setSaveState(SAVE_STATES.CONFLICT);
        return false;
      }
      if (pendingScopeDecision) {
        setSaveState(SAVE_STATES.UNSAVED, "Confirm the scope target change");
        return false;
      }
      if (saveInFlight) return saveInFlight;
      if (!pendingSave || savedRevision >= saveRevision) return true;
      const held = saveCheck?.();
      if (held) {
        setSaveState(SAVE_STATES.UNSAVED, held);
        return false;
      }
      clearTimeout(autoSaveTimer);
      saveInFlight = (async () => {
        try {
          setSaveState(SAVE_STATES.SAVING);
          while (savedRevision < saveRevision) {
            if (pendingScopeDecision) {
              setSaveState(SAVE_STATES.UNSAVED, "Confirm the scope target change");
              return false;
            }
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
              onSaved();
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
      const held = saveCheck?.();
      if (held) {
        setSaveState(SAVE_STATES.UNSAVED, held);
        return;
      }
      saveRetryCount = 0;
      save();
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
        if (latest && timestampMicros(latest) > timestampMicros(report.saved_at)) window.location.reload();
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
    return {report, scheduleSave, save, setSaveState, SAVE_STATES, trackMutation, waitForMutations, markSaveConflict, showOperationError, applyServerRevision, finalizeTextTransaction, holdSaves, hasUnsavedEdits};
  }
  window.vrSave = {start, reconcileCanonicalObject, isRecord, activeTextEntry};
})();
