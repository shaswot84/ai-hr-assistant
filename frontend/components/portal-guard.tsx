"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { CoarseRole, UserContext } from "@/lib/types";
import { Header } from "@/components/header";

/**
 * Client-side auth guard that wraps a role's pages. On mount it calls the
 * `/api/auth/me` endpoint to resolve the current user; if the user's coarse
 * role is not in `allowedRoles` (or the request fails), it redirects to
 * /login. Renders the Header plus a centered main column once authorized.
 *
 * @param props.allowedRoles Roles permitted to view the wrapped children.
 * @param props.children Page content rendered inside the guard.
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

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((res) => {
        if (cancelled) return;
        // Role-based redirect: user authenticated but with the wrong role.
        if (!allowedRoles.includes(res.user.coarse_role)) {
          router.replace("/login");
          return;
        }
        setUser(res.user);
        setChecking(false);
      })
      .catch(() => {
        // Unauthenticated (or backend unreachable) → bounce to the login page.
        if (!cancelled) router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router, allowedRoles]);

  if (checking || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted">Loading…</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <Header user={user} />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">{children}</main>
    </div>
  );
}