"use client";

import {
  CalendarDays,
  CheckCircle2,
  Clock,
  DatabaseZap,
  Play,
  RefreshCw,
  RotateCcw,
  TriangleAlert,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DashboardShell } from "@/components/dashboard/dashboard-shell";
import { Button } from "@/components/ui/button";
import {
  type BackfillJob,
  type BackfillStatus,
  fetchBackfillStatus,
  retryBackfill,
  startBackfill,
} from "@/lib/api";

type LoadState = "loading" | "ready" | "error";
type ActionState = "idle" | "starting" | "retrying";

export function BackfillSettings() {
  const [status, setStatus] = useState<BackfillStatus | null>(null);
  const [dateValue, setDateValue] = useState("");
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [actionState, setActionState] = useState<ActionState>("idle");
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    setLoadState("loading");
    setError(null);
    try {
      const nextStatus = await fetchBackfillStatus();
      setStatus(nextStatus);
      setDateValue((current) => current || nextStatus.default_start_date);
      setLoadState("ready");
    } catch (exc) {
      setError(errorMessage(exc));
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const job = status?.active_job ?? status?.latest_job ?? null;
  const active = status?.active_job !== null && status?.active_job !== undefined;
  const canStart = Boolean(dateValue) && !active && actionState === "idle";
  const canRetry =
    Boolean(job) &&
    job?.status !== "succeeded" &&
    actionState === "idle";

  const metrics = useMemo(
    () => [
      { label: "Fetched", value: job?.fetched_count ?? 0 },
      { label: "Saved", value: job?.saved_count ?? 0 },
      { label: "Duplicates", value: job?.duplicate_count ?? 0 },
      { label: "Processed", value: job?.processed_count ?? 0 },
      { label: "Extracted", value: job?.extracted_count ?? 0 },
      { label: "Matched", value: job?.matched_count ?? 0 },
      { label: "Review", value: job?.needs_review_count ?? 0 },
      { label: "Failed", value: job?.failed_count ?? 0 },
    ],
    [job],
  );

  async function handleStart() {
    if (!canStart) {
      return;
    }
    setActionState("starting");
    setError(null);
    try {
      const started = await startBackfill(dateValue);
      setStatus((current) => ({
        default_start_date: current?.default_start_date ?? dateValue,
        active_job: started,
        latest_job: started,
      }));
      await loadStatus();
    } catch (exc) {
      setError(errorMessage(exc));
    } finally {
      setActionState("idle");
    }
  }

  async function handleRetry() {
    if (!job || !canRetry) {
      return;
    }
    setActionState("retrying");
    setError(null);
    try {
      const retried = await retryBackfill(job.id);
      setStatus((current) => ({
        default_start_date: current?.default_start_date ?? retried.start_date,
        active_job: retried,
        latest_job: retried,
      }));
      await loadStatus();
    } catch (exc) {
      setError(errorMessage(exc));
    } finally {
      setActionState("idle");
    }
  }

  return (
    <DashboardShell
      actions={
        <Button
          disabled={loadState === "loading"}
          onClick={() => void loadStatus()}
          type="button"
          variant="outline"
        >
          <RefreshCw aria-hidden="true" />
          Refresh
        </Button>
      }
      title="Settings"
    >
      <div className="grid gap-6">
        {error ? (
          <div className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-card p-4 text-sm text-destructive shadow-sm">
            <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <span>{error}</span>
          </div>
        ) : null}

        <section className="rounded-lg border bg-card p-5 shadow-sm">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-md bg-muted">
                  <DatabaseZap aria-hidden="true" className="size-5 text-teal-700" />
                </div>
                <div className="min-w-0">
                  <h2 className="text-lg font-semibold text-foreground">
                    Historical Gmail backfill
                  </h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {job ? `Last job ${statusLabel(job)}.` : "No backfill jobs yet."}
                  </p>
                </div>
              </div>
            </div>
            <JobStatusBadge job={job} />
          </div>

          <div className="mt-6 grid gap-3 lg:grid-cols-[minmax(220px,320px)_auto_auto] lg:items-end">
            <label className="grid gap-2 text-sm font-medium text-foreground">
              <span>Start date</span>
              <span className="flex h-10 items-center gap-2 rounded-md border bg-background px-3">
                <CalendarDays
                  aria-hidden="true"
                  className="size-4 shrink-0 text-muted-foreground"
                />
                <input
                  className="min-w-0 flex-1 bg-transparent text-sm outline-none"
                  max={todayInputValue()}
                  onChange={(event) => setDateValue(event.target.value)}
                  type="date"
                  value={dateValue}
                />
              </span>
            </label>
            <Button
              disabled={!canStart}
              onClick={() => void handleStart()}
              type="button"
            >
              <Play aria-hidden="true" />
              {actionState === "starting" ? "Starting" : "Start"}
            </Button>
            <Button
              disabled={!canRetry}
              onClick={() => void handleRetry()}
              type="button"
              variant="outline"
            >
              <RotateCcw aria-hidden="true" />
              {retryLabel(job, actionState)}
            </Button>
          </div>
        </section>

        <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {metrics.map((metric) => (
            <MetricCard
              key={metric.label}
              label={metric.label}
              value={metric.value}
            />
          ))}
        </section>

        <section className="rounded-lg border bg-card p-5 shadow-sm">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-foreground">Job details</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {job ? job.gmail_query : "Waiting for the first backfill job."}
              </p>
            </div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Clock aria-hidden="true" className="size-4" />
              {job ? formatDateTime(job.updated_at) : "No updates"}
            </div>
          </div>

          {job ? (
            <dl className="mt-6 grid gap-4 md:grid-cols-3">
              <DetailItem label="Started" value={formatDateTime(job.started_at)} />
              <DetailItem label="Completed" value={formatDateTime(job.completed_at)} />
              <DetailItem label="Cursor" value={job.page_token ?? "None"} />
            </dl>
          ) : null}

          {job?.last_error ? (
            <div className="mt-5 rounded-md border border-destructive/30 bg-background p-4 text-sm text-destructive">
              {job.last_error}
            </div>
          ) : null}
        </section>
      </div>
    </DashboardShell>
  );
}

function JobStatusBadge({ job }: { job: BackfillJob | null }) {
  if (!job) {
    return (
      <span className="inline-flex h-9 w-fit items-center gap-2 rounded-md border bg-muted px-3 text-sm text-muted-foreground">
        <Clock aria-hidden="true" className="size-4" />
        Idle
      </span>
    );
  }

  const Icon = job.status === "failed" ? TriangleAlert : CheckCircle2;
  return (
    <span
      className={`inline-flex h-9 w-fit items-center gap-2 rounded-md border px-3 text-sm font-medium ${statusClass(
        job,
      )}`}
    >
      <Icon aria-hidden="true" className="size-4" />
      {statusLabel(job)}
    </span>
  );
}

function MetricCard({ label, value }: { label: string; value: number }) {
  return (
    <article className="rounded-lg border bg-card p-4 shadow-sm">
      <p className="text-2xl font-semibold text-foreground">{value}</p>
      <h2 className="mt-1 text-sm font-medium text-muted-foreground">{label}</h2>
    </article>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-background p-4">
      <dt className="text-xs font-medium uppercase text-muted-foreground">{label}</dt>
      <dd className="mt-2 break-words text-sm font-semibold text-foreground">
        {value}
      </dd>
    </div>
  );
}

function statusLabel(job: BackfillJob) {
  if (job.status === "succeeded") {
    return "Completed";
  }
  if (job.status === "failed") {
    return "Failed";
  }
  if (job.status === "running") {
    return "Running";
  }
  return "Pending";
}

function statusClass(job: BackfillJob) {
  if (job.status === "failed") {
    return "border-destructive/30 bg-destructive/10 text-destructive";
  }
  if (job.status === "succeeded") {
    return "border-teal-700/20 bg-teal-50 text-teal-800";
  }
  return "border-amber-500/30 bg-amber-50 text-amber-800";
}

function retryLabel(job: BackfillJob | null, actionState: ActionState) {
  if (actionState === "retrying") {
    return "Resuming";
  }
  if (job?.status === "failed") {
    return "Retry";
  }
  return "Resume";
}

function formatDateTime(value: string | null) {
  if (!value) {
    return "None";
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function todayInputValue() {
  return new Date().toISOString().slice(0, 10);
}

function errorMessage(exc: unknown) {
  return exc instanceof Error ? exc.message : "Request failed.";
}
