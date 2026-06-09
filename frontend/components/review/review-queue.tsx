"use client";

import {
  BriefcaseBusiness,
  CheckCircle2,
  ClipboardCheck,
  Mail,
  RefreshCw,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DashboardShell } from "@/components/dashboard/dashboard-shell";
import { StatusPill } from "@/components/dashboard/status-pill";
import { Button } from "@/components/ui/button";
import {
  type ApplicationStatus,
  type ReviewQueueItem,
  createApplicationFromReview,
  dismissReviewEmail,
  fetchReviewQueue,
  mapReviewEmail,
  primaryStatuses,
} from "@/lib/api";

type LoadState = "loading" | "ready" | "error";

export function ReviewQueue() {
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [busyEmailId, setBusyEmailId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [selectedStatuses, setSelectedStatuses] = useState<
    Record<string, ApplicationStatus>
  >({});

  const loadQueue = useCallback(async () => {
    setLoadState("loading");
    try {
      const nextItems = await fetchReviewQueue();
      setItems(nextItems);
      setSelectedStatuses((current) => {
        const next = { ...current };
        for (const item of nextItems) {
          next[item.email_id] =
            next[item.email_id] ??
            item.extraction?.statusSignal ??
            "Applied";
        }
        return next;
      });
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  const queueCount = items.length;
  const pageTitle = useMemo(
    () => `Manual review (${queueCount})`,
    [queueCount],
  );

  async function resolveItem(
    emailId: string,
    action: () => Promise<unknown>,
  ) {
    setBusyEmailId(emailId);
    setActionError(null);
    const previous = items;
    setItems((current) => current.filter((item) => item.email_id !== emailId));
    try {
      await action();
      await loadQueue();
    } catch (exc) {
      setItems(previous);
      setActionError(errorMessage(exc));
    } finally {
      setBusyEmailId(null);
    }
  }

  return (
    <DashboardShell
      actions={
        <Button onClick={loadQueue} type="button" variant="outline">
          <RefreshCw aria-hidden="true" />
          Refresh
        </Button>
      }
      title={pageTitle}
    >
      <div className="grid gap-6">
        {loadState === "error" ? (
          <div className="rounded-lg border border-destructive/30 bg-card p-4 text-sm text-destructive shadow-sm">
            Review data is unavailable.
          </div>
        ) : null}

        {actionError ? (
          <div className="rounded-lg border border-destructive/30 bg-card p-4 text-sm text-destructive shadow-sm">
            {actionError}
          </div>
        ) : null}

        {loadState === "loading" ? (
          <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground shadow-sm">
            Loading review queue.
          </div>
        ) : null}

        {loadState !== "loading" && items.length === 0 ? (
          <div className="rounded-lg border bg-card p-6 shadow-sm">
            <div className="flex items-center gap-3">
              <CheckCircle2 aria-hidden="true" className="size-5 text-teal-700" />
              <p className="text-sm font-medium text-foreground">
                No emails awaiting review.
              </p>
            </div>
          </div>
        ) : null}

        {items.map((item) => {
          const selectedStatus =
            selectedStatuses[item.email_id] ??
            item.extraction?.statusSignal ??
            "Applied";
          const confidence = item.matching_result?.confidence;

          return (
            <article
              className="rounded-lg border bg-card p-5 shadow-sm"
              key={item.email_id}
            >
              <div className="grid gap-5 xl:grid-cols-[1fr_320px]">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex size-9 items-center justify-center rounded-md bg-muted">
                      <Mail aria-hidden="true" className="size-4 text-teal-700" />
                    </span>
                    <StatusPill status={selectedStatus} />
                    {typeof confidence === "number" ? (
                      <span className="inline-flex h-7 items-center rounded-md bg-muted px-2 text-xs font-medium text-muted-foreground">
                        {Math.round(confidence * 100)}% confidence
                      </span>
                    ) : null}
                  </div>
                  <h2 className="mt-4 text-xl font-semibold text-foreground">
                    {item.subject ?? "Untitled email"}
                  </h2>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {[item.sender, item.received_at ? formatDate(item.received_at) : null]
                      .filter(Boolean)
                      .join(" / ")}
                  </p>
                  {item.review_reason ? (
                    <p className="mt-4 rounded-md border bg-background p-3 text-sm text-foreground">
                      {item.review_reason}
                    </p>
                  ) : null}

                  <dl className="mt-5 grid gap-3 sm:grid-cols-2">
                    <ReviewFact
                      label="Company"
                      value={item.extraction?.company ?? "Unknown"}
                    />
                    <ReviewFact
                      label="Role"
                      value={item.extraction?.role ?? "Unknown"}
                    />
                    <ReviewFact
                      label="Job ID"
                      value={item.extraction?.jobId ?? "Unknown"}
                    />
                    <ReviewFact
                      label="Sender domain"
                      value={item.extraction?.senderDomain ?? "Unknown"}
                    />
                  </dl>

                  {item.extraction?.evidence.length ? (
                    <div className="mt-5 grid gap-2">
                      {item.extraction.evidence.map((evidence) => (
                        <blockquote
                          className="rounded-md border bg-background p-3 text-sm text-muted-foreground"
                          key={`${item.email_id}-${evidence.field}-${evidence.snippet}`}
                        >
                          <span className="font-medium text-foreground">
                            {evidence.field}:
                          </span>{" "}
                          {evidence.snippet}
                        </blockquote>
                      ))}
                    </div>
                  ) : null}
                </div>

                <aside className="grid h-fit gap-4 border-t pt-4 xl:border-l xl:border-t-0 xl:pl-5 xl:pt-0">
                  <label className="grid gap-2 text-sm font-semibold text-foreground">
                    Status
                    <select
                      className="h-10 rounded-md border bg-card px-3 text-sm font-normal outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onChange={(event) =>
                        setSelectedStatuses((current) => ({
                          ...current,
                          [item.email_id]: event.target
                            .value as ApplicationStatus,
                        }))
                      }
                      value={selectedStatus}
                    >
                      {[...primaryStatuses, "Other" as ApplicationStatus].map(
                        (status) => (
                          <option key={status} value={status}>
                            {status === "Offer" ? "Offers" : status}
                          </option>
                        ),
                      )}
                    </select>
                  </label>

                  <div className="grid gap-2">
                    <Button
                      disabled={busyEmailId === item.email_id}
                      onClick={() =>
                        void resolveItem(item.email_id, () =>
                          createApplicationFromReview(
                            item.email_id,
                            selectedStatus,
                          ),
                        )
                      }
                      type="button"
                    >
                      <BriefcaseBusiness aria-hidden="true" />
                      New application
                    </Button>
                    <Button
                      disabled={busyEmailId === item.email_id}
                      onClick={() =>
                        void resolveItem(item.email_id, () =>
                          dismissReviewEmail(
                            item.email_id,
                            "Dismissed from manual review.",
                          ),
                        )
                      }
                      type="button"
                      variant="outline"
                    >
                      <Trash2 aria-hidden="true" />
                      Dismiss
                    </Button>
                  </div>
                </aside>
              </div>

              <div className="mt-5 border-t pt-4">
                <div className="flex items-center gap-2">
                  <ClipboardCheck
                    aria-hidden="true"
                    className="size-4 text-teal-700"
                  />
                  <h3 className="text-sm font-semibold text-foreground">
                    Candidate applications
                  </h3>
                </div>

                {item.candidates.length === 0 ? (
                  <p className="mt-3 text-sm text-muted-foreground">
                    No existing candidates found.
                  </p>
                ) : (
                  <div className="mt-3 divide-y border-y">
                    {item.candidates.map((candidate) => (
                      <div
                        className="grid gap-3 p-3 lg:grid-cols-[1fr_auto]"
                        key={candidate.id}
                      >
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <Link
                              className="text-sm font-semibold text-foreground hover:text-teal-700"
                              href={`/dashboard/applications/${candidate.id}`}
                            >
                              {candidate.company_name}: {candidate.role}
                            </Link>
                            <StatusPill status={candidate.current_status} />
                          </div>
                          <p className="mt-2 text-sm text-muted-foreground">
                            {[candidate.location, candidate.job_id]
                              .filter(Boolean)
                              .join(" / ") || "No location or job ID"}
                          </p>
                        </div>
                        <Button
                          disabled={busyEmailId === item.email_id}
                          onClick={() =>
                            void resolveItem(item.email_id, () =>
                              mapReviewEmail(
                                item.email_id,
                                candidate.id,
                                selectedStatus,
                              ),
                            )
                          }
                          type="button"
                          variant="outline"
                        >
                          <CheckCircle2 aria-hidden="true" />
                          Map
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </DashboardShell>
  );
}

function ReviewFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-t pt-3">
      <dt className="text-xs font-medium uppercase text-muted-foreground">{label}</dt>
      <dd className="mt-1 break-words text-sm font-semibold text-foreground">
        {value}
      </dd>
    </div>
  );
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function errorMessage(exc: unknown) {
  return exc instanceof Error ? exc.message : "Review action failed.";
}
