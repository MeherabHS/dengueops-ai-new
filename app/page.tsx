import HeroSection from "@/components/home/HeroSection";
import ProblemSection from "@/components/home/ProblemSection";
import WorkflowSection from "@/components/home/WorkflowSection";
import CoreModulesSection from "@/components/home/CoreModulesSection";
import ComparisonSection from "@/components/home/ComparisonSection";
import DataEthicsSection from "@/components/home/DataEthicsSection";
import EvaluationFitSection from "@/components/home/EvaluationFitSection";
import UserRolesSection from "@/components/home/UserRolesSection";
import PrototypePreviewSection from "@/components/home/PrototypePreviewSection";
import FinalCTA from "@/components/home/FinalCTA";
import AuthorsSection from "@/components/ui/AuthorsSection";

export const metadata = {
  title: "DengueOps AI — Simulation-Based Dengue Surge Preparedness DSS",
  description:
    "Converting lag-aware dengue forecasts into empirical range evidence, preparedness planning scenarios, bed pressure estimates, and public health action priorities. IEEE ICADHI 2026.",
};

export default function HomePage() {
  return (
    <div className="bg-page">
      {/* 1. Hero */}
      <HeroSection />

      {/* 2. Problem */}
      <ProblemSection />

      {/* 3. Solution workflow */}
      <WorkflowSection />

      {/* 4. Core modules */}
      <CoreModulesSection />

      {/* 5. Comparison */}
      <ComparisonSection />

      {/* 6. Data & ethics */}
      <DataEthicsSection />

      {/* 7. Evaluation fit */}
      <EvaluationFitSection />

      {/* 8. User roles */}
      <UserRolesSection />

      {/* 9. Live prototype preview */}
      <PrototypePreviewSection />

      {/* 10. Final CTA */}
      <FinalCTA />

      {/* 11. Authors */}
      <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 pb-16">
        <AuthorsSection />
      </div>
    </div>
  );
}
