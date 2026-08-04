"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ThemeToggle } from "@/components/theme-toggle";
import { api } from "@/lib/api";
import type { UserContext } from "@/lib/types";

export function Header({ user }: { user: UserContext }) {
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  async function signOut() {
    setSigningOut(true);
    try {
      await api.logout();
    } finally {
      router.push("/login");
    }
  }

  const homeHref = user.coarse_role === "HR_ADMIN" ? "/manager" : "/candidate";

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
              <Link
                href="/manager/vacancies"
                className="transition-colors hover:text-foreground"
              >
                Vacancies
              </Link>
            </nav>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden text-xs text-muted sm:block">{user.display_name}</span>
          <span className="rounded-full border border-border px-2.5 py-0.5 text-[11px] font-medium text-muted">
            {user.coarse_role}
          </span>
          <ThemeToggle />
          <button
            type="button"
            onClick={signOut}
            disabled={signingOut}
            className="rounded-full border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-surface-hover disabled:opacity-50"
          >
            {signingOut ? "…" : "Sign out"}
          </button>
        </div>
      </div>
    </header>
  );
}