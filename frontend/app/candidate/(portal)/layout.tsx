"use client";

import { PortalGuard } from "@/components/portal-guard";

/** Guarded shell for the authenticated candidate portal (applications, chatbot). */
export default function CandidatePortalLayout({ children }: { children: React.ReactNode }) {
  return <PortalGuard allowedRoles={["CANDIDATE"]}>{children}</PortalGuard>;
}
