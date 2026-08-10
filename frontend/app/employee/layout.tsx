"use client";

import { PortalGuard } from "@/components/portal-guard";

/** Shared shell for every /employee/* page — see app/manager/layout.tsx for why. */
export default function EmployeeLayout({ children }: { children: React.ReactNode }) {
  return <PortalGuard allowedRoles={["EMPLOYEE"]}>{children}</PortalGuard>;
}
