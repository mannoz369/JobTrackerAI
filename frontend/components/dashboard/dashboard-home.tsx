"use client";

import {
  BriefcaseBusiness,
  ClipboardCheck,
  RefreshCw,
  Search,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DashboardShell } from "@/components/dashboard/dashboard-shell";
import { StatusPill } from "@/components/dashboard/status-pill";
import { Button } from "@/components/ui/button";
import {
  type ApplicationStatus,
  type ApplicationsOverview,
  type CompanyApplicationGroup,
  fetchApplicationsOverview,
  fetchCompanyGroups,
  primaryStatuses,
} from "@/lib/api";

type LoadState = "loading" | "ready" | "error";
type StatusFilter = ApplicationStatus | "All";

export function DashboardHome() {
  const [overview, setOverview] = useState<ApplicationsOverview | null>(null);
  const [groups, setGroups] = useState<CompanyApplicationGroup[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("All");
  const [query, setQuery] = useState("");

  const loadDashboard = useCallback(async () => {
    setLoadState("loading");
    try {
      const [nextOverview, nextGroups] = await Promise.all([
        fetchApplicationsOverview(),
        fetchCompanyGroups(),
      ]);
      setOverview(nextOverview);
      setGroups(nextGroups);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

  const filteredGroups = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return groups
      .map((group) => ({
        ...group,
        applications: group.applications.filter((application) => {
          const matchesStatus =
            statusFilter === "All" ||
            application.current_status === statusFilter;
          const matchesQuery =
            !normalizedQuery ||
            `${application.company_name} ${application.role} ${
              application.location ?? ""
            } ${application.job_id ?? ""}`
              .toLowerCase()
              .includes(normalizedQuery);
          return matchesStatus && matchesQuery;
        }),
      }))
      .filter((group) => group.applications.length > 0);
  }, [groups, query, statusFilter]);

  return (
    <DashboardShell
      actions={
        <Button onClick={loadDashboard} type="button" variant="outline">
          <RefreshCw aria-hidden="true" />
          Refresh
        </Button>
      }
      title="Application dashboard"
    >
      <div className="grid gap-6">
        {loadState === "error" ? (
          <div className="rounded-lg border border-destructive/30 bg-card p-4 text-sm text-destructive shadow-sm">
            Dashboard data is unavailable. Check the backend session and API
            server.
          </div>
        ) : null}

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            icon={BriefcaseBusiness}
            label="Tracked"
            value={overview?.total ?? 0}
          />
          <MetricCard
            icon={ClipboardCheck}
            label="Needs review"
            value={overview?.review_queue_count ?? 0}
          />
          {(overview?.status_counts ?? primaryStatuses.map((status) => ({
            status,
            count: 0,
          })))
            .filter((item) => item.status !== "Other")
            .slice(0, 2)
            .map((item) => (
              <MetricCard
                icon={BriefcaseBusiness}
                key={item.status}
                label={item.status === "Offer" ? "Offers" : item.status}
                status={item.status}
                value={item.count}
              />
            ))}
        </section>

        <section className="rounded-lg border bg-card p-4 shadow-sm">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex flex-wrap gap-2">
              <FilterButton
                active={statusFilter === "All"}
                label="All"
                onClick={() => setStatusFilter("All")}
              />
              {(overview?.status_counts ?? primaryStatuses.map((status) => ({
                status,
                count: 0,
              }))).map((item) => (
                <FilterButton
                  active={statusFilter === item.status}
                  key={item.status}
                  label={`${item.status === "Offer" ? "Offers" : item.status} ${
                    item.count
                  }`}
                  onClick={() => setStatusFilter(item.status)}
                />
              ))}
            </div>
            <label className="flex h-10 min-w-0 items-center gap-2 rounded-md border bg-background px-3 text-sm text-muted-foreground xl:w-80">
              <Search aria-hidden="true" className="size-4 shrink-0" />
              <input
                className="min-w-0 flex-1 bg-transparent text-foreground outline-none placeholder:text-muted-foreground"
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter companies, roles, IDs"
                type="search"
                value={query}
              />
            </label>
          </div>
        </section>

        <section className="grid gap-4" id="applications">
          {loadState === "loading" ? (
            <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground shadow-sm">
              Loading pipeline data.
            </div>
          ) : null}

          {loadState !== "loading" && filteredGroups.length === 0 ? (
            <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground shadow-sm">
              No applications match the current filters.
            </div>
          ) : null}

          {filteredGroups.map((group) => (
            <article
              className="rounded-lg border bg-card p-4 shadow-sm"
              key={group.company_id ?? group.company_name}
            >
              <div className="flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-foreground">
                    {group.company_name}
                  </h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {group.application_count} tracked{" "}
                    {group.application_count === 1 ? "application" : "applications"}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {group.status_counts
                    .filter((item) => item.count > 0)
                    .map((item) => (
                      <span
                        className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground"
                        key={item.status}
                      >
                        {item.status === "Offer" ? "Offers" : item.status}:{" "}
                        {item.count}
                      </span>
                    ))}
                </div>
              </div>

              <div className="divide-y">
                {group.applications.map((application) => (
                  <Link
                    className="grid gap-3 py-4 transition-colors hover:bg-muted/60 sm:grid-cols-[1fr_auto] sm:px-2"
                    href={`/dashboard/applications/${application.id}`}
                    key={application.id}
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-sm font-semibold text-foreground">
                          {application.role}
                        </h3>
                        <StatusPill status={application.current_status} />
                      </div>
                      <p className="mt-2 text-sm text-muted-foreground">
                        {[application.location, application.job_id]
                          .filter(Boolean)
                          .join(" / ") || "No location or job ID"}
                      </p>
                    </div>
                    <div className="text-sm text-muted-foreground sm:text-right">
                      Updated {formatDate(application.updated_at)}
                    </div>
                  </Link>
                ))}
              </div>
            </article>
          ))}
        </section>
      </div>
    </DashboardShell>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
  status,
}: {
  icon: typeof BriefcaseBusiness;
  label: string;
  value: number;
  status?: ApplicationStatus;
}) {
  return (
    <article className="rounded-lg border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <Icon aria-hidden="true" className="size-5 text-teal-700" />
        {status ? <StatusPill status={status} /> : null}
      </div>
      <p className="mt-5 text-3xl font-semibold text-foreground">{value}</p>
      <h2 className="mt-1 text-sm font-medium text-muted-foreground">{label}</h2>
    </article>
  );
}

function FilterButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`h-9 rounded-md border px-3 text-sm font-medium transition-colors ${
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "bg-background text-muted-foreground hover:bg-muted hover:text-foreground"
      }`}
      onClick={onClick}
      type="button"
    >
      {label}
    </button>
  );
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}
