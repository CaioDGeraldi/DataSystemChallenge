const MOBILE_BREAKPOINT = 768;

export function bindGentelellaShell() {
  const toggle = document.querySelector("[data-sidebar-toggle]");
  const sidebar = document.querySelector("#retorna-sidebar");
  const backdrop = document.querySelector("[data-sidebar-backdrop]");

  if (!toggle || !sidebar || !backdrop) {
    return;
  }

  document.documentElement.dataset.retornaShellEnhanced = "true";

  const isMobile = () => window.innerWidth <= MOBILE_BREAKPOINT;
  const getFocusableElements = () =>
    [...sidebar.querySelectorAll("a, button")].filter(
      (element) =>
        !element.hasAttribute("disabled") &&
        element.getAttribute("tabindex") !== "-1" &&
        element.getClientRects().length > 0,
    );

  const closeDrawer = ({ restoreFocus = false } = {}) => {
    document.body.classList.remove("sidebar-open");
    sidebar.classList.remove("open");
    backdrop.hidden = true;
    sidebar.inert = isMobile();
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Abrir menu principal");
    if (restoreFocus) {
      toggle.focus();
    }
  };

  const openDrawer = () => {
    document.body.classList.add("sidebar-open");
    sidebar.classList.add("open");
    backdrop.hidden = false;
    sidebar.inert = false;
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "Fechar menu principal");
    getFocusableElements()[0]?.focus();
  };

  const setRail = (enabled) => {
    document.body.classList.toggle("sidebar-rail", enabled);
    toggle.setAttribute("aria-expanded", enabled ? "false" : "true");
    toggle.setAttribute(
      "aria-label",
      enabled ? "Expandir menu principal" : "Recolher menu principal",
    );
  };

  toggle.addEventListener("click", () => {
    if (isMobile()) {
      if (document.body.classList.contains("sidebar-open")) {
        closeDrawer();
      } else {
        openDrawer();
      }
      return;
    }

    setRail(!document.body.classList.contains("sidebar-rail"));
  });

  backdrop.addEventListener("click", () => closeDrawer({ restoreFocus: true }));

  document.addEventListener("keydown", (event) => {
    const drawerOpen = document.body.classList.contains("sidebar-open");
    if (event.key === "Escape" && drawerOpen) {
      closeDrawer({ restoreFocus: true });
      return;
    }

    if (event.key === "Tab" && drawerOpen) {
      const focusable = getFocusableElements();
      const first = focusable[0];
      const last = focusable.at(-1);

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
  });

  window.addEventListener("resize", () => {
    if (!isMobile()) {
      closeDrawer();
      setRail(document.body.classList.contains("sidebar-rail"));
    } else {
      if (document.body.classList.contains("sidebar-open")) return;
      sidebar.inert = true;
      document.body.classList.remove("sidebar-rail");
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-label", "Abrir menu principal");
    }
  });

  if (isMobile()) {
    sidebar.inert = true;
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Abrir menu principal");
  }
}
