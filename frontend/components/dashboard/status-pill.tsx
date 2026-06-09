import type { ApplicationStatus } from "@/lib/api";

const statusClasses: Record<ApplicationStatus, string> = {
  Applied: "border-teal-200 bg-teal-50 text-teal-800",
  Reviewing: "border-sky-200 bg-sky-50 text-sky-800",
  Assessment: "border-amber-200 bg-amber-50 text-amber-800",
  Interview: "border-indigo-200 bg-indigo-50 text-indigo-800",
  Offer: "border-emerald-200 bg-emerald-50 text-emerald-800",
  Rejected: "border-rose-200 bg-rose-50 text-rose-800",
  Other: "border-slate-200 bg-slate-50 text-slate-700",
};

export function StatusPill({ status }: { status: ApplicationStatus }) {
  return (
    <span
      className={`inline-flex h-7 items-center rounded-md border px-2.5 text-xs font-semibold ${statusClasses[status]}`}
    >
      {status === "Offer" ? "Offers" : status}
    </span>
  );
}
