import StatusBadge from "@/components/ui/StatusBadge";
import type { RecommendationStrength } from "@/lib/forecast-workflow-types";
const variants = { strong: "success", moderate: "info", weak: "warning", not_available: "neutral" } as const;
export default function RecommendationStrengthBadge({ strength }: { strength: RecommendationStrength }) { return <StatusBadge label={strength === "not_available" ? "Not available" : strength} variant={variants[strength]} />; }
