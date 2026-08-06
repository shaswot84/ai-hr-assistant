"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { api } from "@/lib/api";
import type { Vacancy } from "@/lib/types";

export default function ManagerDashboardPage() {
  const [vacancies, setVacancies] = useState<Vacancy[]>([]);

  useEffect(() => {
    api.listVacancies().then(setVacancies).catch(() => setVacancies([]));
  }, []);

  const open = vacancies.filter((v) => v.status === "OPEN").length;
  const closed = vacancies.filter((v) => v.status === "CLOSED").length;

  return (
    <PortalGuard allowedRoles={["HR_ADMIN"]}>
      <div className="mb-6">
        <h1 className="text-xl font-semibold">Recruitment dashboard</h1>
        <p className="mt-1 text-sm text-muted">Post vacancies, review applications, and manage hiring.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-border bg-surface p-5">
          <p className="text-xs text-muted">Open vacancies</p>
          <p className="mt-1 text-2xl font-semibold">{open}</p>
        </div>
        <div className="rounded-xl border border-border bg-surface p-5">
          <p className="text-xs text-muted">Closed vacancies</p>
          <p className="mt-1 text-2xl font-semibold">{closed}</p>
        </div>
        <div className="rounded-xl border border-border bg-surface p-5">
          <p className="text-xs text-muted">Total vacancies</p>
          <p className="mt-1 text-2xl font-semibold">{vacancies.length}</p>
        </div>
      </div>

      <div className="mt-6 flex gap-3">
        <Link
          href="/manager/vacancies"
          className="rounded-lg border border-border bg-surface px-4 py-2 text-sm font-medium transition-colors hover:bg-surface-hover"
        >
          View all vacancies
        </Link>
        <Link
          href="/manager/vacancies/new"
          className="rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90"
        >
          Post a vacancy
        </Link>
      </div>
    </PortalGuard>
  );
}
