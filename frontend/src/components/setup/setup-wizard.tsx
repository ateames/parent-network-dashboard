"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ConnectionsForm } from "@/components/settings/connections-form";
import { Button } from "@/components/ui/button";
import { usePutConnections, useSetupStatus } from "@/hooks/use-settings";

const STEPS = [
  "Welcome",
  "Dashboard",
  "Pi-hole & UniFi",
  "Syslog",
  "Done",
] as const;

function StepDots({ current }: { current: number }) {
  return (
    <ol className="flex flex-wrap gap-2" aria-label="Setup steps">
      {STEPS.map((label, index) => {
        const active = index === current;
        const done = index < current;
        return (
          <li
            key={label}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              active
                ? "bg-foreground text-background"
                : done
                  ? "bg-muted text-foreground"
                  : "bg-muted/50 text-muted-foreground"
            }`}
          >
            {index + 1}. {label}
          </li>
        );
      })}
    </ol>
  );
}

function WelcomeStep({
  syslogPort,
  onNext,
}: {
  syslogPort: number;
  onNext: () => void;
}) {
  const [hostHint, setHostHint] = useState("this Pi’s LAN IP");
  useEffect(() => {
    if (typeof window !== "undefined") {
      setHostHint(window.location.hostname);
    }
  }, []);

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">
          Set up Parent Network Dashboard
        </h1>
        <p className="text-sm text-muted-foreground">
          This wizard configures Pi-hole and UniFi connections on your home
          LAN. Household data stays on this device — nothing is sent to the
          cloud. Use UniFi session auth if you want Disable Internet controls.
        </p>
      </div>
      <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
        <li>
          Dashboard UI: <code>http://{hostHint}:3000</code>
        </li>
        <li>
          UniFi syslog destination:{" "}
          <code>
            {hostHint}:{syslogPort}
          </code>{" "}
          (UDP)
        </li>
        <li>
          Prefer LAN IPs over <code>.local</code> names inside Docker.
        </li>
      </ul>
      <Button type="button" onClick={onNext}>
        Continue
      </Button>
    </div>
  );
}

function DashboardStep({
  onNext,
  onBack,
}: {
  onNext: () => void;
  onBack: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight">Dashboard access</h2>
        <p className="text-sm text-muted-foreground">
          Sign-in uses the password printed by <code>install.sh</code> (or the
          values in <code>infra/.env</code>). On the next step you can optionally
          set a family password that is stored encrypted in the database.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button type="button" onClick={onNext}>
          Continue
        </Button>
      </div>
    </div>
  );
}

function ConnectionsStep({
  onNext,
  onBack,
}: {
  onNext: () => void;
  onBack: () => void;
}) {
  return (
    <div className="space-y-4">
      <ConnectionsForm
        title="Connect Pi-hole and UniFi"
        description="Enter LAN hosts and credentials. Use Test before continuing. You can change these later under Settings → Connections."
        showDashboardFields
        showInstructions
      />
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button type="button" onClick={onNext}>
          Continue to syslog
        </Button>
      </div>
    </div>
  );
}

function SyslogStep({
  syslogPort,
  onNext,
  onBack,
}: {
  syslogPort: number;
  onNext: () => void;
  onBack: () => void;
}) {
  const [hostHint, setHostHint] = useState("this-pi-lan-ip");
  useEffect(() => {
    if (typeof window !== "undefined") {
      setHostHint(window.location.hostname);
    }
  }, []);

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight">
          UniFi syslog (optional)
        </h2>
        <p className="text-sm text-muted-foreground">
          Point UniFi remote logging at this Pi so security events appear in the
          live feed. No password is required — traffic is one-way.
        </p>
      </div>
      <ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground">
        <li>
          In UniFi Network, open Settings → System → Advanced (or Control Plane
          → Integrations / System Logs / SIEM — labels vary by version).
        </li>
        <li>Enable remote logging / syslog / SIEM export.</li>
        <li>
          Set the server to <code>{hostHint}</code> and port{" "}
          <code>{syslogPort}</code> (UDP preferred).
        </li>
        <li>
          Save, then generate a known event (for example connect a Wi‑Fi
          client). Confirm later under Health → Sources.
        </li>
      </ol>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button type="button" onClick={onNext}>
          Continue
        </Button>
      </div>
    </div>
  );
}

function DoneStep({
  onFinish,
  pending,
}: {
  onFinish: () => void;
  pending: boolean;
}) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight">You’re ready</h2>
        <p className="text-sm text-muted-foreground">
          Connections are saved. The worker polls Pi-hole and UniFi on the next
          interval. Check Source Health if a source stays degraded.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={onFinish} disabled={pending}>
          {pending ? "Finishing…" : "Finish and sign in"}
        </Button>
        <Link
          href="/login"
          className="inline-flex h-8 items-center rounded-lg border border-border bg-background px-2.5 text-sm font-medium hover:bg-muted"
        >
          Skip to sign in
        </Link>
      </div>
    </div>
  );
}

export function SetupWizard() {
  const router = useRouter();
  const setup = useSetupStatus();
  const putConnections = usePutConnections();
  const [step, setStep] = useState(0);
  const [finishError, setFinishError] = useState<string | null>(null);

  useEffect(() => {
    if (setup.data?.setup_completed) {
      router.replace("/login");
    }
  }, [setup.data?.setup_completed, router]);

  const syslogPort = setup.data?.syslog_port ?? 5514;

  async function finish() {
    setFinishError(null);
    try {
      await putConnections.mutateAsync({ mark_setup_complete: true });
      router.replace("/login?next=/overview");
    } catch (error) {
      setFinishError(
        error instanceof Error ? error.message : "Couldn’t complete setup",
      );
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6">
      <StepDots current={step} />
      {step === 0 ? (
        <WelcomeStep syslogPort={syslogPort} onNext={() => setStep(1)} />
      ) : null}
      {step === 1 ? (
        <DashboardStep onBack={() => setStep(0)} onNext={() => setStep(2)} />
      ) : null}
      {step === 2 ? (
        <ConnectionsStep onBack={() => setStep(1)} onNext={() => setStep(3)} />
      ) : null}
      {step === 3 ? (
        <SyslogStep
          syslogPort={syslogPort}
          onBack={() => setStep(2)}
          onNext={() => setStep(4)}
        />
      ) : null}
      {step === 4 ? (
        <DoneStep onFinish={() => void finish()} pending={putConnections.isPending} />
      ) : null}
      {finishError ? (
        <p className="text-sm text-destructive" role="alert">
          {finishError}
        </p>
      ) : null}
    </div>
  );
}
