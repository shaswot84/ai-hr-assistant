"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { CoarseRole, UserContext } from "@/lib/types";
import { Header } from "@/components/header";
import { Sidebar } from "@/components/sidebar";
import { Spinner } from "@/components/loading";

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
  const pathname = usePathname();
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
          router.replace("/signin");
          return;
        }
        setUser(res.user);
        setChecking(false);
      })
      .catch(() => {
        if (!cancelled) router.replace("/signin");
      });
    return () => {
      cancelled = true;
    };
  }, [router, allowedRoles]);

  if (checking || !user) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-zinc-50">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600 shadow-sm">
          <svg className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
            />
          </svg>
        </div>
        <Spinner size="md" />
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-zinc-50">
      <Sidebar
        role={user.coarse_role}
        user={user}
        mobileOpen={mobileNavOpen}
        onCloseMobile={() => setMobileNavOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header user={user} onMenuClick={() => setMobileNavOpen(true)} />
        <main className="flex-1 overflow-y-auto">
          <div
            key={pathname}
            className="animate-fade-in mx-auto w-full max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8"
          >
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
