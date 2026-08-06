"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { clearAuthToken } from "@/lib/auth";
import type { UserContext } from "@/lib/types";

const ROLE_LABEL: Record<UserContext["coarse_role"], string> = {
  HR_ADMIN: "Manager",
  EMPLOYEE: "Employee",
  CANDIDATE: "Candidate",
};

/** Top navigation bar rendered inside every role-guarded portal page. */
export function Header({ user }: { user: UserContext }) {
  const router = useRouter();

  function signOut() {
    clearAuthToken();
    router.push("/login");
  }

  const homeHref =
    user.coarse_role === "HR_ADMIN"
      ? "/manager"
      : user.coarse_role === "CANDIDATE"
        ? "/candidate"
        : "/employee";

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-background/80 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3">
        <div className="flex items-center gap-4">
          <Link href={homeHref} className="text-sm font-semibold tracking-tight">
            AI HR Assistant
          </Link>
          {user.coarse_role === "HR_ADMIN" && (
            <nav className="hidden items-center gap-4 text-sm text-muted sm:flex">
              <Link href="/manager" className="transition-colors hover:text-foreground">
                Dashboard
              </Link>
              <Link href="/manager/vacancies" className="transition-colors hover:text-foreground">
                Vacancies
              </Link>
              <Link href="/manager/settings" className="transition-colors hover:text-foreground">
                Settings
              </Link>
            </nav>
          )}
          {user.coarse_role === "CANDIDATE" && (
            <nav className="hidden items-center gap-4 text-sm text-muted sm:flex">
              <Link href="/candidate" className="transition-colors hover:text-foreground">
                Vacancies
              </Link>
              <Link
                href="/candidate/applications"
                className="transition-colors hover:text-foreground"
              >
                My Applications
              </Link>
            </nav>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden text-xs text-muted sm:block">{user.display_name}</span>
          <span className="rounded-full border border-border px-2.5 py-0.5 text-[11px] font-medium text-muted">
            {ROLE_LABEL[user.coarse_role]}
          </span>
          <button
            type="button"
            onClick={signOut}
            className="rounded-full border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-surface-hover"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
