"use client";

import { PortalGuard } from "@/components/portal-guard";

/**
 * Shared shell for every /manager/* page: one auth check + one persistent
 * sidebar/topbar mount. Individual pages used to each wrap themselves in
 * PortalGuard, which remounted the whole shell (and re-ran the auth check)
 * on every navigation between manager pages — that's what caused the white
 * flash when switching sidebar tabs.
 */
export default function ManagerLayout({ children }: { children: React.ReactNode }) {
  return <PortalGuard allowedRoles={["HR_ADMIN"]}>{children}</PortalGuard>;
}
