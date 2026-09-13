// Promise-based replacement for window.confirm, so prompts can offer more than two answers
// and can be styled with the app's theme. Shared by app.js and manager.js.
(() => {
  "use strict";

  const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  let openDialog = null;

  const ask = ({title, message, list, actions}) => new Promise(resolve => {
    // A second prompt would trap focus behind the first, so settle the open one first.
    if (openDialog) openDialog.settle("cancel");

    const returnFocusTo = document.activeElement;
    const backdrop = document.createElement("div");
    backdrop.className = "vr-dialog-backdrop";
    backdrop.dataset.dialog = "";

    const panel = document.createElement("div");
    panel.className = "vr-dialog";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");

    const heading = document.createElement("h2");
    heading.id = `vr-dialog-title-${Math.random().toString(36).slice(2, 8)}`;
    heading.textContent = title;
    panel.setAttribute("aria-labelledby", heading.id);
    panel.append(heading);

    String(message || "").split("\n\n").filter(Boolean).forEach(paragraph => {
      const text = document.createElement("p");
      text.textContent = paragraph;
      panel.append(text);
    });

    if (list && list.length) {
      const items = document.createElement("ul");
      list.forEach(entry => {
        const item = document.createElement("li");
        item.textContent = entry;
        items.append(item);
      });
      panel.append(items);
    }

    const buttonRow = document.createElement("div");
    buttonRow.className = "vr-dialog-actions";
    panel.append(buttonRow);

    const settle = key => {
      if (openDialog !== handle) return;
      openDialog = null;
      document.removeEventListener("keydown", onKeydown, true);
      backdrop.remove();
      if (returnFocusTo?.isConnected) returnFocusTo.focus();
      resolve(key);
    };
    const handle = {settle};

    actions.forEach(action => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.dialogAction = action.key;
      button.className = action.tone || "subtle";
      button.textContent = action.label;
      button.onclick = () => settle(action.key);
      buttonRow.append(button);
    });

    const cancelKey = (actions.find(action => action.cancel) || actions[actions.length - 1]).key;
    function onKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        settle(cancelKey);
        return;
      }
      if (event.key !== "Tab") return;
      // Keep focus inside the dialog while it is the only thing the tester can act on.
      const stops = [...panel.querySelectorAll(FOCUSABLE)];
      if (!stops.length) return;
      const edge = event.shiftKey ? stops[0] : stops[stops.length - 1];
      if (document.activeElement === edge || !panel.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? stops[stops.length - 1] : stops[0]).focus();
      }
    }

    backdrop.onmousedown = event => { if (event.target === backdrop) settle(cancelKey); };
    document.addEventListener("keydown", onKeydown, true);
    backdrop.append(panel);
    document.body.append(backdrop);
    openDialog = handle;
    // Focus the safe answer, never a destructive one, so a stray Enter cannot discard work.
    (panel.querySelector('[data-dialog-action].primary') || buttonRow.lastElementChild)?.focus();
  });

  const confirm = ({title, message, list, confirmLabel = "OK", cancelLabel = "Cancel", tone = "primary"}) =>
    ask({title, message, list, actions: [
      {key: "confirm", label: confirmLabel, tone},
      {key: "cancel", label: cancelLabel, cancel: true},
    ]}).then(key => key === "confirm");

  window.vrDialog = {ask, confirm};
})();
