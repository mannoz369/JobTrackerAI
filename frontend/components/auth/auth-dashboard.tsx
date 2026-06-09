"use client";

import {
  Activity,
  Bell,
  BriefcaseBusiness,
  CheckCircle2,
  Database,
  Inbox,
  LogOut,
  Mail,
  RefreshCw,
  Settings,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  API_BASE_URL,
  type AuthStatus,
  type GmailWatchState,
  disconnectedStatus,
  fetchAuthStatus,
  googleOAuthStartUrl,
  logout,
} from "@/lib/api";

const navItems = [
  { label: "Connection", href: "/", icon: Activity, active: true },
  { label: "Applications", href: "/dashboard", icon: BriefcaseBusiness },
  { label: "Review", href: "/dashboard/review", icon: Inbox },
  { label: "Settings", href: "/dashboard/settings", icon: Settings },
];

const readinessChecks = [
  {
    label: "API health",
    value: "GET /health",
    icon: Activity,
    tone: "text-teal-700",
  },
  {
    label: "MongoDB users",
    value: "OAuth metadata store",
    icon: Database,
    tone: "text-slate-700",
  },
  {
    label: "Token storage",
    value: "Encrypted server-side",
    icon: ShieldCheck,
    tone: "text-amber-700",
  },
];

type LoadState = "loading" | "ready" | "error";

export function AuthDashboard() {
  const [status, setStatus] = useState<AuthStatus>(disconnectedStatus);
  const [loadState, setLoadState] = useState<LoadState>("loading");

  const loadStatus = useCallback(async () => {
    setLoadState("loading");
    try {
      setStatus(await fetchAuthStatus());
      setLoadState("ready");
    } catch {
      setStatus(disconnectedStatus);
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const connectionLabel = useMemo(() => {
    if (loadState === "loading") {
      return "Checking";
    }
    if (status.connected) {
      return "Connected";
    }
    if (status.authenticated) {
      return "Signed in";
    }
    return "Disconnected";
  }, [loadState, status.authenticated, status.connected]);

  async function handleLogout() {
    try {
      setStatus(await logout());
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }

  return (
    <main className="shell-grid min-h-screen">
      <div className="min-h-screen bg-background/88">
        <header className="border-b bg-card/95">
          <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:justify-between lg:px-8">
            <div>
              <p className="text-xs font-semibold uppercase text-teal-700">
                JobTracker
              </p>
              <h1 className="mt-1 text-2xl font-semibold text-foreground">
                Gmail connection
              </h1>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="inline-flex h-10 items-center gap-2 rounded-md border bg-muted px-3 text-sm text-muted-foreground">
                <UserRound aria-hidden="true" className="size-4" />
                {connectionLabel}
              </span>
              <Button asChild variant="outline">
                <a href={`${API_BASE_URL}/health`}>
                  <Activity aria-hidden="true" />
                  API health
                </a>
              </Button>
            </div>
          </div>
        </header>

        <div className="mx-auto grid max-w-7xl gap-6 px-5 py-6 lg:grid-cols-[240px_1fr] lg:px-8">
          <aside className="h-fit rounded-lg border bg-card p-2">
            <nav aria-label="Primary navigation" className="grid gap-1">
              {navItems.map((item) => (
                <a
                  aria-current={item.active ? "page" : undefined}
                  className={`flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium ${
                    item.active
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
                  href={item.href}
                  key={item.label}
                >
                  <item.icon aria-hidden="true" className="size-4" />
                  {item.label}
                </a>
              ))}
            </nav>
          </aside>

          <section className="grid gap-6">
            <div className="rounded-lg border bg-card p-5 shadow-sm">
              <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                <div className="max-w-2xl">
                  <p className="text-sm font-medium text-teal-700">
                    Task 2 readiness
                  </p>
                  <h2 className="mt-2 text-3xl font-semibold text-foreground">
                    Connect the monitored Gmail mailbox.
                  </h2>
                  <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
                    OAuth sign-in stores protected server credentials and keeps
                    browser responses limited to account connection metadata.
                  </p>
                </div>
                <ConnectionActions
                  loadState={loadState}
                  onLogout={handleLogout}
                  onRefresh={loadStatus}
                  status={status}
                />
              </div>
            </div>

            {loadState === "error" ? (
              <div className="rounded-lg border border-destructive/30 bg-card p-4 text-sm text-destructive shadow-sm">
                Connection status is unavailable. Confirm the backend is running
                and `NEXT_PUBLIC_API_BASE_URL` points to it.
              </div>
            ) : null}

            <div className="grid gap-4 md:grid-cols-3">
              {readinessChecks.map((check) => (
                <article
                  className="rounded-lg border bg-card p-4 shadow-sm"
                  key={check.label}
                >
                  <div className="flex items-center justify-between gap-3">
                    <check.icon
                      aria-hidden="true"
                      className={`size-5 ${check.tone}`}
                    />
                    <span className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
                      ready
                    </span>
                  </div>
                  <h3 className="mt-5 text-sm font-semibold text-foreground">
                    {check.label}
                  </h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {check.value}
                  </p>
                </article>
              ))}
            </div>

            <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
              <section className="rounded-lg border bg-card p-5 shadow-sm">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h2 className="text-lg font-semibold">Connection status</h2>
                    <p className="mt-1 text-sm text-muted-foreground">
                      The connected account becomes the monitored mailbox for
                      Gmail ingestion.
                    </p>
                  </div>
                  {status.connected ? (
                    <CheckCircle2
                      aria-hidden="true"
                      className="size-6 text-teal-700"
                    />
                  ) : (
                    <Mail aria-hidden="true" className="size-6 text-amber-700" />
                  )}
                </div>

                <dl className="mt-6 grid gap-4 sm:grid-cols-2">
                  <StatusItem
                    label="Signed-in email"
                    value={status.email ?? "Not signed in"}
                  />
                  <StatusItem
                    label="Monitored mailbox"
                    value={status.monitored_email ?? "Not connected"}
                  />
                  <StatusItem
                    label="Gmail watch"
                    value={watchStatusLabel(status.gmail_watch?.status)}
                  />
                  <StatusItem
                    label="Session"
                    value={status.authenticated ? "Active" : "Not active"}
                  />
                </dl>
              </section>

              <section className="rounded-lg border bg-card p-5 shadow-sm">
                <div className="flex items-center gap-3">
                  <div className="flex size-10 items-center justify-center rounded-md bg-muted">
                    <Bell aria-hidden="true" className="size-5 text-teal-700" />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold">Next Gmail step</h2>
                    <p className="text-sm text-muted-foreground">
                      Watch registration is pending.
                    </p>
                  </div>
                </div>
                <div className="mt-6 rounded-md border bg-muted p-4 text-sm text-muted-foreground">
                  After OAuth is connected, the push ingestion task can register
                  a Gmail watch for the monitored mailbox without asking the
                  browser for provider tokens.
                </div>
              </section>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}

function ConnectionActions({
  loadState,
  onLogout,
  onRefresh,
  status,
}: {
  loadState: LoadState;
  onLogout: () => void;
  onRefresh: () => void;
  status: AuthStatus;
}) {
  if (status.connected) {
    return (
      <div className="flex flex-wrap gap-3">
        <Button asChild>
          <a href="/dashboard">
            <BriefcaseBusiness aria-hidden="true" />
            Open dashboard
          </a>
        </Button>
        <Button onClick={onRefresh} type="button" variant="outline">
          <RefreshCw aria-hidden="true" />
          Refresh
        </Button>
        <Button onClick={onLogout} type="button" variant="outline">
          <LogOut aria-hidden="true" />
          Log out
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-3">
      <Button asChild>
        <a href={googleOAuthStartUrl()}>
          <Mail aria-hidden="true" />
          Sign in with Google
        </a>
      </Button>
      <Button
        disabled={loadState === "loading"}
        onClick={onRefresh}
        type="button"
        variant="outline"
      >
        <RefreshCw aria-hidden="true" />
        Refresh
      </Button>
    </div>
  );
}

function StatusItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-background p-4">
      <dt className="text-xs font-medium uppercase text-muted-foreground">{label}</dt>
      <dd className="mt-2 break-words text-sm font-semibold text-foreground">
        {value}
      </dd>
    </div>
  );
}

function watchStatusLabel(status: GmailWatchState["status"] | undefined) {
  if (status === "registered") {
    return "Registered";
  }
  if (status === "expired") {
    return "Expired";
  }
  return "Not registered";
}
