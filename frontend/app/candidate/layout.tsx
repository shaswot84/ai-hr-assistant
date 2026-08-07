"use client";

import { PortalGuard } from "@/components/portal-guard";

/** Shared shell for every /candidate/* page — see app/manager/layout.tsx for why. */
export default function CandidateLayout({ children }: { children: React.ReactNode }) {
  return <PortalGuard allowedRoles={["CANDIDATE"]}>{children}</PortalGuard>;
}
