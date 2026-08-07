"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { CoarseRole, UserContext } from "@/lib/types";
import { Header } from "@/components/header";
import { Sidebar } from "@/components/sidebar";

/**
 * Client-side auth guard + page shell (sidebar + top bar) wrapping every
 * role's pages. On mount it calls `/api/auth/me` to resolve the current
 * user; if the request fails (no token, expired token) or the role isn't
 * in `allowedRoles`, it redirects to /login.
 */
export function PortalGuard({
  allowedRoles,
  children,
}: {
  allowedRoles: CoarseRole[];
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [user, setUser] = useState<UserContext | null>(null);
  const [checking, setChecking] = useState(true);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((res) => {
        if (cancelled) return;
        if (!allowedRoles.includes(res.user.coarse_role)) {
          router.replace("/login");
          return;
        }
        setUser(res.user);
        setChecking(false);
      })
      .catch(() => {
        if (!cancelled) router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router, allowedRoles]);

  if (checking || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-sky-100">
        <p className="text-sm text-gray-500">Loading…</p>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-sky-100">
      <Sidebar
        role={user.coarse_role}
        mobileOpen={mobileNavOpen}
        onCloseMobile={() => setMobileNavOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header user={user} onMenuClick={() => setMobileNavOpen(true)} />
        <main className="flex-1 overflow-y-auto p-4 sm:p-6">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
