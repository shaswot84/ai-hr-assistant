"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { StatsCard } from "@/components/stats-card";
import { StatusBadge } from "@/components/status";
import { ListSkeleton, StatsSkeleton } from "@/components/loading";
import { api } from "@/lib/api";
import type { Vacancy } from "@/lib/types";

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export default function ManagerDashboardPage() {
  const [vacancies, setVacancies] = useState<Vacancy[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listVacancies()
      .then(setVacancies)
      .catch(() => setVacancies([]))
      .finally(() => setLoading(false));
  }, []);

  const open = vacancies.filter((v) => v.status === "OPEN").length;
  const closed = vacancies.filter((v) => v.status === "CLOSED").length;
  const recent = [...vacancies]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">{greeting()} 👋</h1>
        <p className="mt-1 text-sm text-gray-500">
          {new Date().toLocaleDateString("en-US", {
            weekday: "long",
            year: "numeric",
            month: "long",
            day: "numeric",
          })}
        </p>
      </div>

      {loading ? (
        <StatsSkeleton />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatsCard
            title="Open Vacancies"
            value={open}
            subtitle="Currently accepting applications"
            color="green"
            icon={
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 7h-4V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2H4a2 2 0 00-2 2v9a2 2 0 002 2h16a2 2 0 002-2V9a2 2 0 00-2-2zm-6 0h-4V5h4v2z" />
              </svg>
            }
          />
          <StatsCard
            title="Closed Vacancies"
            value={closed}
            subtitle="Archived roles"
            color="amber"
            icon={
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 8h14M5 8a2 2 0 01-2-2V4a2 2 0 012-2h14a2 2 0 012 2v2a2 2 0 01-2 2M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
              </svg>
            }
          />
          <StatsCard
            title="Total Vacancies"
            value={vacancies.length}
            subtitle="All time"
            color="blue"
            icon={
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
              </svg>
            }
          />
        </div>
      )}

      {loading ? (
        <ListSkeleton rows={3} />
      ) : (
        <div className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
            <h2 className="font-semibold text-gray-900">Recent Vacancies</h2>
            <Link href="/manager/vacancies" className="text-sm text-blue-600 hover:underline">
              View all
            </Link>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-sky-50">
                <tr>
                  <th className="table-th">Title</th>
                  <th className="table-th hidden sm:table-cell">Department</th>
                  <th className="table-th hidden sm:table-cell">Posted</th>
                  <th className="table-th">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {recent.length ? (
                  recent.map((v) => (
                    <tr key={v.vacancy_id} className="transition-colors hover:bg-sky-50">
                      <td className="table-td">
                        <Link
                          href={`/manager/vacancies/${v.vacancy_id}`}
                          className="font-medium text-gray-900 hover:text-blue-600"
                        >
                          {v.title}
                        </Link>
                      </td>
                      <td className="table-td hidden sm:table-cell">{v.department_name ?? "—"}</td>
                      <td className="table-td hidden sm:table-cell text-xs text-gray-500">
                        {new Date(v.created_at).toLocaleDateString()}
                      </td>
                      <td className="table-td">
                        <StatusBadge status={v.status} />
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={4} className="table-td py-8 text-center text-gray-500">
                      No vacancies yet
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card p-6">
        <h2 className="mb-4 font-semibold text-gray-900">Quick Actions</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Link
            href="/manager/vacancies?new=1"
            className="flex flex-col items-center justify-center gap-2 rounded-xl bg-blue-50 p-4 text-sm font-medium text-blue-700 transition-colors hover:bg-blue-100"
          >
            <span className="text-2xl">📝</span>
            Post a Vacancy
          </Link>
          <Link
            href="/manager/applications"
            className="flex flex-col items-center justify-center gap-2 rounded-xl bg-purple-50 p-4 text-sm font-medium text-purple-700 transition-colors hover:bg-purple-100"
          >
            <span className="text-2xl">📋</span>
            Review Applications
          </Link>
          <Link
            href="/manager/settings"
            className="flex flex-col items-center justify-center gap-2 rounded-xl bg-amber-50 p-4 text-sm font-medium text-amber-700 transition-colors hover:bg-amber-100"
          >
            <span className="text-2xl">⚙️</span>
            AI Settings
          </Link>
        </div>
      </div>
    </div>
  );
}
