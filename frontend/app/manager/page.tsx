"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { MetricCard } from "@/components/metric-card";
import { AreaChart, BarList } from "@/components/charts";
import { StatusBadge } from "@/components/status";
import { EmptyState } from "@/components/empty-state";
import { ListSkeleton, StatsSkeleton } from "@/components/loading";
import { api } from "@/lib/api";
import type { ApplicationDetail, Vacancy } from "@/lib/types";

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;

export default function ManagerDashboardPage() {
  const [vacancies, setVacancies] = useState<Vacancy[]>([]);
  const [applications, setApplications] = useState<ApplicationDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [range, setRange] = useState<7 | 30 | 90>(30);

  useEffect(() => {
    Promise.allSettled([api.listVacancies(), api.allApplications()]).then(([v, a]) => {
      if (v.status === "fulfilled") setVacancies(v.value);
      if (a.status === "fulfilled") setApplications(a.value);
      setLoading(false);
    });
  }, []);

  const stats = useMemo(() => {
    const open = vacancies.filter((v) => v.status === "OPEN").length;
    const closed = vacancies.filter((v) => v.status === "CLOSED").length;
    const shortlisted = applications.filter((a) => a.application_status === "SHORTLISTED").length;
    // Only successful screenings carry a real requirements verdict — a
    // failed evaluation (no AI provider, etc.) has nothing to count here.
    const screened = applications.filter((a) => a.evaluated && a.evaluation && !a.evaluation.failed);
    const meetingRequirements = screened.filter((a) => a.evaluation?.detail?.requirements_met !== false).length;
    const meetingRequirementsPct = screened.length
      ? Math.round((meetingRequirements / screened.length) * 100)
      : null;

    // 7-day trend window for the Applications metric delta.
    const now = new Date();

    const last7 = applications.filter((a) => {
      const d = new Date(a.applied_at);
      return now.getTime() - d.getTime() <= 7 * 86400000;
    }).length;
    const prev7 = applications.filter((a) => {
      const d = new Date(a.applied_at);
      const age = now.getTime() - d.getTime();
      return age > 7 * 86400000 && age <= 14 * 86400000;
    }).length;

    const breakdown = (
      ["APPLIED", "SHORTLISTED", "REJECTED", "WITHDRAWN"] as const
    ).map((s) => ({
      label: s.charAt(0) + s.slice(1).toLowerCase(),
      value: applications.filter((a) => a.application_status === s).length,
    }));

    return { open, closed, shortlisted, meetingRequirementsPct, last7, prev7, breakdown };
  }, [applications, vacancies]);

  // Applications per day over the selected range window.
  const days = useMemo(() => {
    const now = new Date();
    const counts = new Map<string, number>();
    for (const a of applications) {
      const key = dayKey(new Date(a.applied_at));
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    const out: Array<{ label: string; value: number }> = [];
    for (let i = range - 1; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(now.getDate() - i);
      out.push({
        label: d.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
        value: counts.get(dayKey(d)) ?? 0,
      });
    }
    return out;
  }, [applications, range]);

  const recent = useMemo(
    () =>
      [...vacancies]
        .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
        .slice(0, 5),
    [vacancies]
  );

  const delta =
    stats.last7 === 0 && stats.prev7 === 0
      ? undefined
      : {
          value:
            stats.prev7 === 0
              ? `+${stats.last7} this week`
              : `${Math.round(((stats.last7 - stats.prev7) / stats.prev7) * 100)}% vs last week`,
          direction: (
            stats.last7 > stats.prev7 ? "up" : stats.last7 < stats.prev7 ? "down" : "neutral"
          ) as "up" | "down" | "neutral",
        };

  return (
    <div className="space-y-6">
      <PageHeader
        title={`${greeting()} — here's what's happening`}
        description={`${new Date().toLocaleDateString("en-US", {
          weekday: "long",
          year: "numeric",
          month: "long",
          day: "numeric",
        })} · A live view of recruitment activity across your workspace.`}
        actions={
          <>
            <Link href="/manager/vacancies?new=1" className="btn-secondary">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Post a Vacancy
            </Link>
            <Link href="/manager/applications" className="btn-primary">
              Review Applications
            </Link>
          </>
        }
      />

      {loading ? (
        <StatsSkeleton />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Open Vacancies"
            value={stats.open}
            sub={`${stats.closed} closed · ${vacancies.length} total`}
            iconClass="bg-emerald-50 text-emerald-600"
            icon={
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.75}
                  d="M20 7h-4V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2H4a2 2 0 00-2 2v9a2 2 0 002 2h16a2 2 0 002-2V9a2 2 0 00-2-2zm-6 0h-4V5h4v2z"
                />
              </svg>
            }
          />
          <MetricCard
            label="Applications"
            value={applications.length}
            delta={delta}
            sub="Across all vacancies"
            iconClass="bg-blue-50 text-blue-600"
            icon={
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.75}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
            }
          />
          <MetricCard
            label="Shortlisted"
            value={stats.shortlisted}
            sub="Awaiting the next step"
            iconClass="bg-violet-50 text-violet-600"
            icon={
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.75}
                  d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            }
          />
          <MetricCard
            label="Meeting Requirements"
            value={stats.meetingRequirementsPct === null ? "—" : `${stats.meetingRequirementsPct}%`}
            sub={
              stats.meetingRequirementsPct === null
                ? "No screenings yet"
                : "Of AI-screened resumes"
            }
            iconClass="bg-amber-50 text-amber-600"
            icon={
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.75}
                  d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                />
              </svg>
            }
          />
        </div>
      )}

      {/* Charts */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <section className="card p-5 lg:col-span-2">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-zinc-900">Applications</h2>
              <p className="text-xs text-zinc-400">Daily submissions, last {range} days</p>
            </div>
            <div className="flex items-center gap-1 rounded-lg border border-zinc-200 bg-white p-0.5">
              {([7, 30, 90] as const).map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => setRange(r)}
                  className={`tab ${range === r ? "tab-active" : ""}`}
                  aria-pressed={range === r}
                >
                  {r}d
                </button>
              ))}
            </div>
          </div>
          {loading ? (
            <div className="h-[280px] animate-pulse rounded-lg bg-zinc-100" />
          ) : days.some((d) => d.value > 0) ? (
            <AreaChart data={days} labelFormatter={(l) => l} />
          ) : (
            <div className="flex h-[280px] items-center justify-center">
              <p className="text-sm text-zinc-400">No applications in this window — share a vacancy to get started.</p>
            </div>
          )}
        </section>

        <section className="card p-5">
          <div className="mb-4">
            <h2 className="text-sm font-semibold text-zinc-900">Pipeline status</h2>
            <p className="text-xs text-zinc-400">Applications by current state</p>
          </div>
          {loading ? (
            <div className="h-[280px] animate-pulse rounded-lg bg-zinc-100" />
          ) : applications.length === 0 ? (
            <div className="flex h-[280px] items-center justify-center">
              <p className="text-sm text-zinc-400">Nothing in the pipeline yet.</p>
            </div>
          ) : (
            <div className="pt-2">
              <BarList data={stats.breakdown} colorClass="bg-blue-500" />
            </div>
          )}
        </section>
      </div>

      {/* Recent vacancies */}
      <section className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-zinc-100 px-5 py-3.5">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900">Recent vacancies</h2>
            <p className="text-xs text-zinc-400">The five most recently posted roles</p>
          </div>
          <Link href="/manager/vacancies" className="link">
            View all
          </Link>
        </div>
        {loading ? (
          <ListSkeleton rows={3} />
        ) : recent.length === 0 ? (
          <EmptyState
            title="No vacancies yet"
            description="Post your first vacancy to start receiving applications."
            action={
              <Link href="/manager/vacancies?new=1" className="btn-primary">
                Post a Vacancy
              </Link>
            }
          />
        ) : (
          <div className="table-scroll">
            <table className="w-full">
              <thead className="bg-zinc-50">
                <tr>
                  <th className="table-th">Title</th>
                  <th className="table-th hidden sm:table-cell">Department</th>
                  <th className="table-th hidden sm:table-cell">Posted</th>
                  <th className="table-th">Status</th>
                  <th className="table-th text-right">Applications</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {recent.map((v) => {
                  const count = applications.filter((a) => a.vacancy_id === v.vacancy_id).length;
                  return (
                    <tr key={v.vacancy_id} className="table-row">
                      <td className="table-td">
                        <Link
                          href={`/manager/vacancies/${v.vacancy_id}`}
                          className="font-medium text-zinc-900 hover:text-blue-600"
                        >
                          {v.title}
                        </Link>
                      </td>
                      <td className="table-td hidden sm:table-cell text-zinc-500">
                        {v.department_name ?? "—"}
                      </td>
                      <td className="table-td hidden text-xs text-zinc-500 sm:table-cell">
                        {new Date(v.created_at).toLocaleDateString("en-US", {
                          month: "short",
                          day: "numeric",
                          year: "numeric",
                        })}
                      </td>
                      <td className="table-td">
                        <StatusBadge status={v.status} />
                      </td>
                      <td className="table-td text-right tabular-nums text-zinc-500">{count}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
