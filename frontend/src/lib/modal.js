const openModals = [];
let savedBodyOverflow = "";

const FOCUSABLE = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export function modalFocus(node, options = {}) {
  const trigger = document.activeElement;

  if (openModals.length === 0) {
    savedBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  openModals.push(node);

  const focusInitial = () => {
    const target = node.querySelector("[data-modal-autofocus]") || node.querySelector(FOCUSABLE) || node;
    target.focus({ preventScroll: true });
  };

  const handleKeydown = (event) => {
    if (openModals.at(-1) !== node) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopImmediatePropagation();
      options.onEscape?.();
      return;
    }

    if (event.key !== "Tab") return;
    const focusable = [...node.querySelectorAll(FOCUSABLE)].filter(
      (element) => !element.hidden && element.getClientRects().length > 0,
    );
    if (focusable.length === 0) {
      event.preventDefault();
      node.focus();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  document.addEventListener("keydown", handleKeydown);
  queueMicrotask(focusInitial);

  return {
    update(nextOptions = {}) {
      options = nextOptions;
    },
    destroy() {
      document.removeEventListener("keydown", handleKeydown);
      const index = openModals.lastIndexOf(node);
      if (index >= 0) openModals.splice(index, 1);
      if (openModals.length === 0) document.body.style.overflow = savedBodyOverflow;
      if (trigger instanceof HTMLElement && trigger.isConnected) {
        queueMicrotask(() => trigger.focus({ preventScroll: true }));
      }
    },
  };
}
