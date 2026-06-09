"use client";

import {
  Activity,
  BriefcaseBusiness,
  ClipboardCheck,
  Mail,
  Settings,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { API_BASE_URL } from "@/lib/api";

const navItems = [
  {
    label: "Overview",
    href: "/dashboard",
    icon: Activity,
    active: (pathname: string) => pathname === "/dashboard",
  },
  {
    label: "Applications",
    href: "/dashboard#applications",
    icon: BriefcaseBusiness,
    active: (pathname: string) => pathname.startsWith("/dashboard/applications"),
  },
  {
    label: "Manual review",
    href: "/dashboard/review",
    icon: ClipboardCheck,
    active: (pathname: string) => pathname === "/dashboard/review",
  },
  {
    label: "Settings",
    href: "/dashboard/settings",
    icon: Settings,
    active: (pathname: string) => pathname === "/dashboard/settings",
  },
];

export function DashboardShell({
  children,
  title,
  eyebrow = "JobTracker",
  actions,
}: {
  children: ReactNode;
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
}) {
  const pathname = usePathname();

  return (
    <main className="shell-grid min-h-screen">
      <div className="min-h-screen bg-background/90">
        <header className="border-b bg-card/95">
          <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 py-4 lg:flex-row lg:items-center lg:justify-between lg:px-8">
            <div>
              <p className="text-xs font-semibold uppercase text-teal-700">
                {eyebrow}
              </p>
              <h1 className="mt-1 text-2xl font-semibold text-foreground">
                {title}
              </h1>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              {actions}
              <Button asChild variant="outline">
                <a href={`${API_BASE_URL}/health`}>
                  <Mail aria-hidden="true" />
                  API
                </a>
              </Button>
            </div>
          </div>
        </header>

        <div className="mx-auto grid max-w-7xl gap-6 px-5 py-6 lg:grid-cols-[232px_1fr] lg:px-8">
          <aside className="h-fit rounded-lg border bg-card p-2">
            <nav aria-label="Dashboard navigation" className="grid gap-1">
              {navItems.map((item) => {
                const active = item.active(pathname);
                return (
                  <Link
                    aria-current={active ? "page" : undefined}
                    className={`flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium ${
                      active
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    }`}
                    href={item.href}
                    key={item.label}
                  >
                    <item.icon aria-hidden="true" className="size-4" />
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </aside>

          <section className="min-w-0">{children}</section>
        </div>
      </div>
    </main>
  );
}
