import StatusBadge from "@/components/ui/StatusBadge";
import type { RuntimeValidationResponseSuccess } from "@/lib/runtime/contracts";
import type { WorkflowMode } from "@/lib/forecast-workflow-types";
import DatasetAssessmentOption from "./DatasetAssessmentOption";
import QuickForecastOption from "./QuickForecastOption";

function workflowEligibility(mode: WorkflowMode, response: RuntimeValidationResponseSuccess | null) {
  if (!response) return { eligible: false, reasons: ["Authoritative validation is required."] };
  if (mode === "quick_forecast") return response.eligibility.quickForecast;
  const assessment = response.eligibility.assessDataset;
  return {
    eligible: assessment.eligible && assessment.assessmentStatus === "full_assessment_eligible",
    reasons: assessment.reasons,
  };
}

export default function WorkflowChoice({
  value,
  response,
  validatedWorkflowMode,
  onChange,
}: {
  value: WorkflowMode | null;
  response: RuntimeValidationResponseSuccess | null;
  validatedWorkflowMode: WorkflowMode | null;
  onChange: (value: WorkflowMode) => void;
}) {
  return (
    <fieldset>
      <legend className="text-lg font-semibold text-ink">Choose workflow</legend>
      <p className="mt-1 text-sm text-ink-muted">
        Eligibility comes from the authoritative validation record. Runtime workspaces are workflow-specific.
      </p>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {(["quick_forecast", "assess_dataset"] as const).map((mode) => {
          const eligibility = workflowEligibility(mode, response);
          const revalidationRequired = Boolean(validatedWorkflowMode && validatedWorkflowMode !== mode);
          return (
            <label
              key={mode}
              className={`cursor-pointer rounded-xl border p-5 ${value === mode ? "border-accent bg-accent/10" : "border-border-subtle bg-surface"}`}
            >
              <input
                type="radio"
                className="sr-only"
                name="workflow-mode"
                checked={value === mode}
                onChange={() => onChange(mode)}
              />
              {mode === "quick_forecast" ? (
                <QuickForecastOption selected={value === mode} />
              ) : (
                <DatasetAssessmentOption selected={value === mode} />
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <StatusBadge
                  label={eligibility.eligible ? "Authoritatively eligible" : "Not eligible"}
                  variant={eligibility.eligible ? "success" : "warning"}
                />
                {revalidationRequired ? <StatusBadge label="Revalidation required" variant="warning" /> : null}
              </div>
              {!eligibility.eligible ? (
                <ul className="mt-3 space-y-1 text-xs text-ink-muted">
                  {eligibility.reasons.map((reason, index) => <li key={`${mode}-${index}`}>• {reason}</li>)}
                </ul>
              ) : null}
              {revalidationRequired ? (
                <p className="mt-3 text-xs text-warning">
                  Selecting this path returns to Validate and creates a new workflow-specific workspace.
                </p>
              ) : null}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
