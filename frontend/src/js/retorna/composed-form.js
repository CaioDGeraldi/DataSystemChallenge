import { initialFormMode } from "./appearance.js";
const FORM_CONTROL_SELECTOR = [
  "input:not([type='hidden']):not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
].join(",");

function controlsForStep(step) {
  return Array.from(step.querySelectorAll(FORM_CONTROL_SELECTOR));
}

function firstInvalidControl(step) {
  return controlsForStep(step).find((control) => !control.checkValidity());
}

function firstInvalidControlInSteps(steps) {
  for (const step of steps) {
    const invalidControl = controlsForStep(step).find(
      (control) => !control.validity.valid,
    );
    if (invalidControl) {
      return invalidControl;
    }
  }
  return null;
}

export function composedFormPresentation(
  mode,
  activeStep,
  stepLabels,
  visitedSteps = [],
  sectionNavigation = false,
) {
  const stepMode = mode === "steps";
  const stepCount = stepLabels.length;
  const visited = new Set(visitedSteps);
  return {
    hiddenSteps: Array.from(
      { length: stepCount },
      (_, index) => stepMode && index !== activeStep,
    ),
    currentStep: stepMode ? activeStep : null,
    indicatorStates: stepLabels.map((_, index) => {
      if (!stepMode) {
        return "neutral";
      }
      if (index === activeStep) {
        return "current";
      }
      return visited.has(index) ? "visited" : "future";
    }),
    statusText: stepMode
      ? `${sectionNavigation ? "Seção" : "Etapa"} ${activeStep + 1} de ${stepCount} — ${stepLabels[activeStep]}`
      : "Todos os campos",
    previousHidden: !stepMode || activeStep === 0,
    nextHidden: !stepMode || activeStep === stepCount - 1,
    submitHidden: stepMode && !sectionNavigation && activeStep !== stepCount - 1,
    submitDisabled: stepMode && !sectionNavigation && activeStep !== stepCount - 1,
  };
}

export function bindComposedForms() {
  document.querySelectorAll('.retorna-data-form:not([data-composed-form]) [data-form-error-summary]')
    .forEach(summary => requestAnimationFrame(() => summary.focus()));
  document.querySelectorAll("[data-composed-form]").forEach((form) => {
    if (form.dataset.composedFormBound === "true") {
      return;
    }

    const steps = Array.from(form.querySelectorAll("[data-form-step]"));
    const indicators = Array.from(
      form.querySelectorAll("[data-form-step-indicator]"),
    );
    const indicatorList = form.querySelector("[data-form-step-list]");
    const status = form.querySelector("[data-form-step-status]");
    const sections = form.hasAttribute("data-form-sections");
    const sectionTriggers = Array.from(form.querySelectorAll("[data-form-section-trigger]"));
    const modeToggle = form.querySelector("[data-form-mode-toggle]");
    const previous = form.querySelector("[data-form-step-previous]");
    const next = form.querySelector("[data-form-step-next]");
    const submit = form.querySelector("[data-form-final-submit]");

    if (
      steps.length < 2 ||
      indicators.length !== steps.length ||
      !indicatorList ||
      !status ||
      (!sections && !modeToggle) ||
      (sections && sectionTriggers.length !== steps.length) ||
      !previous ||
      !next ||
      !submit
    ) {
      return;
    }

    let mode =
      sections ? "steps" : initialFormMode(form.dataset.composedFormInitialMode, document.documentElement.dataset.retornaFormMode);
    let activeStep = Math.max(
      0,
      steps.findIndex((step) => step.hasAttribute("data-step-has-errors")),
    );
    const visitedSteps = new Set([activeStep]);
    let handlingInvalidCycle = false;

    const updatePresentation = () => {
      form.dataset.composedFormMode = mode;
      const presentation = composedFormPresentation(
        mode,
        activeStep,
        steps.map((step) => step.dataset.stepLabel || "Etapa"),
        visitedSteps,
        sections,
      );

      steps.forEach((step, index) => {
        step.hidden = presentation.hiddenSteps[index];
      });

      indicators.forEach((indicator, index) => {
        if (index === presentation.currentStep) {
          indicator.setAttribute("aria-current", "step");
        } else {
          indicator.removeAttribute("aria-current");
        }
        if (sections) {
          const trigger = sectionTriggers[index];
          if (index === activeStep) trigger.setAttribute("aria-current", "step");
          else trigger.removeAttribute("aria-current");
          indicator.removeAttribute("aria-current");
        }
        indicator.dataset.stepState = presentation.indicatorStates[index];
      });

      status.textContent = presentation.statusText;
      if (modeToggle) {
        modeToggle.textContent = mode === "steps" ? "Exibir tudo" : "Exibir em etapas";
        modeToggle.setAttribute("aria-pressed", String(mode === "all"));
      }
      previous.hidden = presentation.previousHidden;
      next.hidden = presentation.nextHidden;
      submit.hidden = presentation.submitHidden;
      submit.disabled = presentation.submitDisabled;
    };

    const activateStep = (index, { focusHeading = false } = {}) => {
      activeStep = Math.min(Math.max(index, 0), steps.length - 1);
      visitedSteps.add(activeStep);
      updatePresentation();

      if (focusHeading) {
        steps[activeStep]
          .querySelector("legend, [data-form-step-heading]")
          ?.focus();
      }
    };

    if (modeToggle) modeToggle.hidden = false;
    sectionTriggers.forEach((trigger, index) => {
      trigger.addEventListener("click", () => activateStep(index, { focusHeading: true }));
    });
    indicatorList.hidden = false;
    status.hidden = false;
    form.dataset.composedFormBound = "true";
    updatePresentation();

    previous.addEventListener("click", () => {
      activateStep(activeStep - 1, { focusHeading: true });
    });

    next.addEventListener("click", () => {
      const invalidControl = sections ? null : firstInvalidControl(steps[activeStep]);
      if (invalidControl) {
        invalidControl.reportValidity();
        invalidControl.focus();
        return;
      }
      activateStep(activeStep + 1, { focusHeading: true });
    });

    submit.addEventListener("click", (event) => {
      if (mode !== "steps") {
        return;
      }

      const invalidControl = firstInvalidControlInSteps(steps);
      if (!invalidControl) {
        return;
      }

      event.preventDefault();
      const invalidStepIndex = steps.indexOf(
        invalidControl.closest("[data-form-step]"),
      );
      if (invalidStepIndex >= 0) {
        activateStep(invalidStepIndex);
      }
      invalidControl.reportValidity();
      invalidControl.focus();
    });

    modeToggle?.addEventListener("click", () => {
      mode = mode === "steps" ? "all" : "steps";
      updatePresentation();
      modeToggle.focus();
    });

    form.addEventListener(
      "invalid",
      (event) => {
        if (mode !== "steps" || handlingInvalidCycle) {
          return;
        }

        handlingInvalidCycle = true;
        const invalidStep = event.target.closest("[data-form-step]");
        const invalidStepIndex = steps.indexOf(invalidStep);
        if (invalidStepIndex >= 0 && invalidStepIndex !== activeStep) {
          activateStep(invalidStepIndex);
        }

        requestAnimationFrame(() => event.target.focus());
        setTimeout(() => {
          handlingInvalidCycle = false;
        }, 0);
      },
      true,
    );

    const errorSummary = form.querySelector("[data-form-error-summary]");
    if (errorSummary) {
      requestAnimationFrame(() => errorSummary.focus());
    }
  });
}
