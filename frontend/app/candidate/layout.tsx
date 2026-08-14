"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { getAuthToken } from "@/lib/auth";
import type { UserContext } from "@/lib/types";
import { Header } from "@/components/header";
import { Sidebar } from "@/components/sidebar";
import { Spinner } from "@/components/loading";

function isPublicPath(pathname: string): boolean {
  return pathname === "/candidate" || pathname.startsWith("/candidate/vacancies/");
}

/**
 * Shell for the whole /candidate/* tree. Unlike ManagerLayout/EmployeeLayout
 * (a plain PortalGuard wrap — every page under them requires an account),
 * part of this tree is open to anonymous visitors: first-time candidates
 * browse and apply for roles before they have one. So this layout resolves
 * the session itself (if any) once, then picks a shell per page:
 *  - a signed-in candidate gets the same persistent sidebar/topbar (with a
 *    working sign out) on every /candidate/* page, vacancy browsing included
 *  - an anonymous visitor gets the slim public careers header, but only on
 *    the routes that don't require an account (browsing + applying);
 *    anything else (My Applications, the chatbot) redirects to /signin
 */
export default function CandidateLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<UserContext | null>(null);
  const [checking, setChecking] = useState(true);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const token = getAuthToken();
    if (!token) {
      Promise.resolve().then(() => {
        if (!cancelled) setChecking(false);
      });
      return () => {
        cancelled = true;
      };
    }
    api
      .me()
      .then((res) => {
        if (cancelled) return;
        if (res.user.coarse_role === "CANDIDATE") setUser(res.user);
        setChecking(false);
      })
      .catch(() => {
        if (!cancelled) setChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const publicRoute = isPublicPath(pathname);

  useEffect(() => {
    if (!checking && !user && !publicRoute) router.replace("/signin");
  }, [checking, user, publicRoute, router]);

  if (checking || (!publicRoute && !user)) {
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

  if (user) {
    return (
      <div className="flex h-screen overflow-hidden bg-zinc-50">
        <Sidebar
          role="CANDIDATE"
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

  return (
    <div className="flex min-h-screen flex-col bg-zinc-50">
      <header className="border-b border-zinc-200 bg-white">
        <div className="mx-auto flex w-full max-w-4xl items-center justify-between px-4 py-4 sm:px-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-600 shadow-sm">
              <svg className="h-[18px] w-[18px] text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
                />
              </svg>
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight text-zinc-900">Summit Technologies</p>
              <p className="text-[11px] text-zinc-400">Careers</p>
            </div>
          </div>
          <Link href="/signin" className="link text-sm">
            Sign in
          </Link>
        </div>
      </header>
      <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-6 sm:px-6 lg:py-8">{children}</main>
    </div>
  );
}
