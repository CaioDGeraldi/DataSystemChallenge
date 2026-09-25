export function bindSidebarSections() {
  document.querySelectorAll("[data-sidebar-section-toggle]").forEach((toggle) => {
    if (toggle.dataset.sidebarSectionBound === "true") {
      return;
    }

    const section = toggle.closest("[data-sidebar-section]");
    const contentId = toggle.getAttribute("aria-controls");
    const content = contentId ? document.getElementById(contentId) : null;

    if (!section || !content || !section.contains(content)) {
      return;
    }

    toggle.dataset.sidebarSectionBound = "true";
    toggle.addEventListener("click", () => {
      const isExpanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!isExpanded));
      section.classList.toggle("is-collapsed", isExpanded);
    });
  });
}
