export function bindUserMenu() {
  const trigger = document.querySelector("[data-user-menu-trigger]");
  const menu = document.querySelector("[data-user-menu]");

  if (!trigger || !menu) {
    return;
  }

  document.documentElement.dataset.retornaUserMenuEnhanced = "true";

  const close = ({ restoreFocus = false } = {}) => {
    menu.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    if (restoreFocus) {
      trigger.focus();
    }
  };

  const open = () => {
    menu.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    menu.querySelector("a, button")?.focus();
  };

  trigger.addEventListener("click", () => {
    if (menu.hidden) {
      open();
    } else {
      close();
    }
  });

  document.addEventListener("click", (event) => {
    if (!menu.hidden && !event.target.closest(".retorna-user-menu")) {
      close();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !menu.hidden) {
      close({ restoreFocus: true });
    }
  });
}
