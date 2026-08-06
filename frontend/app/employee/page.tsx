"use client";

import { PortalGuard } from "@/components/portal-guard";

export default function EmployeePage() {
  return (
    <PortalGuard allowedRoles={["EMPLOYEE"]}>
      <div className="rounded-xl border border-border bg-surface p-8 text-center">
        <h1 className="text-lg font-semibold">You&apos;re signed in</h1>
        <p className="mt-2 text-sm text-muted">
          The employee portal (HR policy chat + leave requests) is coming with the Leave
          Management module next sprint. Nothing to do here yet.
        </p>
      </div>
    </PortalGuard>
  );
}
