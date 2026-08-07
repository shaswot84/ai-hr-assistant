"use client";

import { PortalGuard } from "@/components/portal-guard";

export default function EmployeePage() {
  return (
    <PortalGuard allowedRoles={["EMPLOYEE"]}>
      <div className="card animate-fade-in flex flex-col items-center gap-3 p-12 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-100 text-blue-600">
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
        </div>
        <h1 className="text-lg font-semibold text-gray-900">You&apos;re signed in</h1>
        <p className="max-w-sm text-sm text-gray-500">
          The employee portal (HR policy chat + leave requests) is coming with the Leave
          Management module next sprint. Nothing to do here yet.
        </p>
      </div>
    </PortalGuard>
  );
}
