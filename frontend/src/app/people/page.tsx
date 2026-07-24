import { Suspense } from "react";

import { PeoplePage } from "@/components/people/people-page";

function PeopleFallback() {
  return (
    <div className="space-y-6" aria-busy="true">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">People</h1>
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
      <div className="h-40 animate-pulse rounded-lg bg-muted/60" />
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<PeopleFallback />}>
      <PeoplePage />
    </Suspense>
  );
}
