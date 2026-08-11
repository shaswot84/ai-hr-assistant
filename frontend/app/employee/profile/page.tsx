"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status";
import { DetailSkeleton } from "@/components/loading";
import { api, ApiError } from "@/lib/api";
import type { Employee } from "@/lib/types";

/** A labeled value row in the profile card. */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wider text-zinc-400">{label}</dt>
      <dd className="mt-1 text-sm text-zinc-800">{children}</dd>
    </div>
  );
}

export default function EmployeeProfilePage() {
  const [profile, setProfile] = useState<Employee | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .myProfile()
      .then(setProfile)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load profile."));
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        title="My Profile"
        description="Your details as stored in the HR directory."
      />

      {error && <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>}
      {!error && !profile && <DetailSkeleton />}

      {profile && (
        <div className="grid gap-6 lg:grid-cols-3">
          {/* Identity card */}
          <section className="card p-6">
            <div className="flex items-center gap-4">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-blue-600 text-lg font-semibold text-white">
                {profile.first_name.charAt(0)}
                {profile.last_name.charAt(0)}
              </div>
              <div className="min-w-0">
                <h2 className="truncate text-lg font-semibold tracking-tight text-zinc-900">
                  {profile.first_name} {profile.last_name}
                </h2>
                <p className="truncate text-sm text-zinc-500">{profile.email}</p>
              </div>
            </div>
            <div className="mt-4 flex items-center gap-2">
              <StatusBadge status={profile.employment_status} />
              <span className="font-mono text-xs text-zinc-400">{profile.employee_code}</span>
            </div>
            {profile.phone && (
              <p className="mt-4 text-sm text-zinc-600">
                <span className="font-medium text-zinc-800">Phone:</span> {profile.phone}
              </p>
            )}
          </section>

          {/* Organization details */}
          <section className="card p-6 lg:col-span-2">
            <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-400">
              Organization
            </h2>
            <dl className="grid grid-cols-1 gap-5 sm:grid-cols-2">
              <Field label="Department">{profile.department_name ?? "—"}</Field>
              <Field label="Designation">{profile.designation_title ?? "—"}</Field>
              <Field label="Manager">
                {profile.manager_name ? (
                  <span className="inline-flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-zinc-100 text-[11px] font-semibold text-zinc-600">
                      {profile.manager_name.charAt(0)}
                    </span>
                    {profile.manager_name}
                  </span>
                ) : (
                  "—"
                )}
              </Field>
              <Field label="Joining Date">
                {new Date(profile.joining_date).toLocaleDateString("en-US", {
                  month: "long",
                  day: "numeric",
                  year: "numeric",
                })}
              </Field>
            </dl>
          </section>
        </div>
      )}
    </div>
  );
}
