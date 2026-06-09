"use client";

import {
  ArrowLeft,
  CheckCircle2,
  Clock3,
  Mail,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DashboardShell } from "@/components/dashboard/dashboard-shell";
import { StatusPill } from "@/components/dashboard/status-pill";
import { Button } from "@/components/ui/button";
import {
  type ApplicationDetail,
  type ApplicationStatus,
  deleteApplication,
  fetchApplicationDetail,
  primaryStatuses,
  updateApplicationStatus,
} from "@/lib/api";

type LoadState = "loading" | "ready" | "error";

export function ApplicationDetailView({
  applicationId,
}: {
  applicationId: string;
}) {
  const router = useRouter();
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [selectedStatus, setSelectedStatus] =
    useState<ApplicationStatus>("Applied");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const loadDetail = useCallback(async () => {
    setLoadState("loading");
    try {
      const nextDetail = await fetchApplicationDetail(applicationId);
      setDetail(nextDetail);
      setSelectedStatus(nextDetail.application.current_status);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }, [applicationId]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  const pageTitle = useMemo(() => {
    if (detail === null) {
      return "Application timeline";
    }
    return `${detail.application.company_name}: ${detail.application.role}`;
  }, [detail]);

  async function handleStatusSave() {
    if (detail === null) {
      return;
    }
    const previous = detail;
    setSaving(true);
    setDetail({
      ...detail,
      application: {
        ...detail.application,
        current_status: selectedStatus,
      },
    });
    try {
      await updateApplicationStatus(
        applicationId,
        selectedStatus,
        "Updated from dashboard.",
      );
      await loadDetail();
    } catch {
      setDetail(previous);
      setLoadState("error");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (detail === null || deleting) {
      return;
    }
    const confirmed = window.confirm(
      `Delete ${detail.application.company_name}: ${detail.application.role}? This removes the application and its timeline. Linked emails will move back to manual review.`,
    );
    if (!confirmed) {
      return;
    }

    setDeleting(true);
    try {
      await deleteApplication(applicationId);
      router.push("/dashboard");
      router.refresh();
    } catch {
      setLoadState("error");
      setDeleting(false);
    }
  }

  return (
    <DashboardShell
      actions={
        <div className="flex flex-wrap gap-3">
          <Button asChild variant="outline">
            <Link href="/dashboard">
              <ArrowLeft aria-hidden="true" />
              Back
            </Link>
          </Button>
          <Button onClick={loadDetail} type="button" variant="outline">
            <RefreshCw aria-hidden="true" />
            Refresh
          </Button>
          <Button
            className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
            disabled={detail === null || deleting}
            onClick={() => void handleDelete()}
            type="button"
            variant="outline"
          >
            <Trash2 aria-hidden="true" />
            {deleting ? "Deleting" : "Delete"}
          </Button>
        </div>
      }
      title={pageTitle}
    >
      <div className="grid gap-6">
        {loadState === "error" ? (
          <div className="rounded-lg border border-destructive/30 bg-card p-4 text-sm text-destructive shadow-sm">
            Application data is unavailable.
          </div>
        ) : null}

        {detail === null ? (
          <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground shadow-sm">
            Loading application timeline.
          </div>
        ) : (
          <>
            <section className="grid gap-4 lg:grid-cols-[1fr_320px]">
              <div className="rounded-lg border bg-card p-5 shadow-sm">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="text-sm font-medium text-teal-700">
                      {detail.application.company_name}
                    </p>
                    <h2 className="mt-1 text-2xl font-semibold text-foreground">
                      {detail.application.role}
                    </h2>
                  </div>
                  <StatusPill status={detail.application.current_status} />
                </div>
                <dl className="mt-6 grid gap-4 sm:grid-cols-2">
                  <InfoItem
                    label="Location"
                    value={detail.application.location ?? "Not recorded"}
                  />
                  <InfoItem
                    label="Job ID"
                    value={detail.application.job_id ?? "Not recorded"}
                  />
                  <InfoItem
                    label="Source email"
                    value={detail.application.source_email_id ?? "Not recorded"}
                  />
                  <InfoItem
                    label="Updated"
                    value={formatDateTime(detail.application.updated_at)}
                  />
                </dl>
              </div>

              <form
                className="rounded-lg border bg-card p-5 shadow-sm"
                onSubmit={(event) => {
                  event.preventDefault();
                  void handleStatusSave();
                }}
              >
                <label className="text-sm font-semibold text-foreground">
                  Current status
                </label>
                <select
                  className="mt-3 h-10 w-full rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onChange={(event) =>
                    setSelectedStatus(event.target.value as ApplicationStatus)
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
                <Button
                  className="mt-4 w-full"
                  disabled={saving}
                  type="submit"
                >
                  <Save aria-hidden="true" />
                  {saving ? "Saving" : "Save status"}
                </Button>
              </form>
            </section>

            <section className="rounded-lg border bg-card p-5 shadow-sm">
              <div className="flex items-center gap-3 border-b pb-4">
                <Clock3 aria-hidden="true" className="size-5 text-teal-700" />
                <h2 className="text-lg font-semibold text-foreground">
                  Timeline
                </h2>
              </div>

              {detail.timeline.length === 0 ? (
                <div className="py-6 text-sm text-muted-foreground">
                  No status history has been recorded.
                </div>
              ) : (
                <ol className="divide-y">
                  {detail.timeline.map((item) => (
                    <li className="grid gap-4 py-5 lg:grid-cols-[180px_1fr]" key={item.id}>
                      <div className="text-sm text-muted-foreground">
                        {formatDateTime(item.created_at)}
                      </div>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusPill status={item.new_status} />
                          <span className="inline-flex h-7 items-center gap-1 rounded-md bg-muted px-2 text-xs font-medium text-muted-foreground">
                            {item.source === "email" ? (
                              <Mail aria-hidden="true" className="size-3" />
                            ) : (
                              <CheckCircle2
                                aria-hidden="true"
                                className="size-3"
                              />
                            )}
                            {item.source}
                          </span>
                        </div>
                        <p className="mt-3 text-sm text-foreground">
                          {item.explanation ?? "Status updated."}
                        </p>
                        <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                          {item.previous_status ? (
                            <span className="rounded-md bg-muted px-2 py-1">
                              From {item.previous_status}
                            </span>
                          ) : null}
                          {item.email_id ? (
                            <span className="rounded-md bg-muted px-2 py-1">
                              Email {item.email_id}
                            </span>
                          ) : null}
                          {typeof item.confidence === "number" ? (
                            <span className="rounded-md bg-muted px-2 py-1">
                              {Math.round(item.confidence * 100)}% confidence
                            </span>
                          ) : null}
                        </div>
                        {item.evidence.length > 0 ? (
                          <div className="mt-4 grid gap-2">
                            {item.evidence.map((evidence) => (
                              <blockquote
                                className="rounded-md border bg-background p-3 text-sm text-muted-foreground"
                                key={`${item.id}-${evidence.field}-${evidence.snippet}`}
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
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </>
        )}
      </div>
    </DashboardShell>
  );
}

function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-t pt-3">
      <dt className="text-xs font-medium uppercase text-muted-foreground">{label}</dt>
      <dd className="mt-2 break-words text-sm font-semibold text-foreground">
        {value}
      </dd>
    </div>
  );
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}
