import { Suspense } from "react";

import { FindingsPage } from "@/components/findings/findings-page";

function FindingsFallback() {
  return (
    <div className="space-y-6" aria-busy="true">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Findings</h1>
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
      <div className="h-40 animate-pulse rounded-lg bg-muted/60" />
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<FindingsFallback />}>
      <FindingsPage />
    </Suspense>
  );
}
