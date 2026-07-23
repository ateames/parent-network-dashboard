import { HealthStatus } from "@/components/health/health-status";

export default function HealthPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Health</h1>
        <p className="text-sm text-muted-foreground">
          Backend connectivity through the server-side proxy.
        </p>
      </div>
      <HealthStatus />
    </div>
  );
}
