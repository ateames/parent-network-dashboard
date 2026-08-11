import { SetupWizard } from "@/components/setup/setup-wizard";

export default function SetupPage() {
  return (
    <div className="min-h-dvh bg-[radial-gradient(circle_at_top,_oklch(0.97_0.02_240),_oklch(0.96_0.01_80))] px-4 py-10">
      <SetupWizard />
    </div>
  );
}
