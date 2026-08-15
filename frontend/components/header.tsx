"use client";

import Link from "next/link";
import type { UserContext } from "@/lib/types";
import { useSidebar } from "./sidebar-provider";

const ROLE_LABEL: Record<UserContext["coarse_role"], string> = {
  HR_ADMIN: "Manager",
  EMPLOYEE: "Employee",
  CANDIDATE: "Candidate",
};

/** Slim top bar: mobile menu trigger + app mark + contextual label.
 * The user's identity and sign-out live in the sidebar's user area — not
 * duplicated up here. */
export function Header({
  user,
  onMenuClick,
}: {
  user: UserContext;
  onMenuClick: () => void;
}) {
  const homeHref =
    user.coarse_role === "HR_ADMIN"
      ? "/manager"
      : user.coarse_role === "CANDIDATE"
        ? "/candidate"
        : "/employee/chatbot";

  const { collapsed, toggle } = useSidebar();

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-zinc-200 bg-white/85 px-4 backdrop-blur sm:px-6">
      {/* Desktop: collapse/expand the sidebar (like ChatGPT's toggle). */}
      <button
        type="button"
        onClick={toggle}
        className="hidden rounded-md p-2 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 md:inline-flex"
        aria-label={collapsed ? "Open sidebar" : "Close sidebar"}
        title={collapsed ? "Open sidebar" : "Close sidebar"}
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          {collapsed ? (
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M4 4h16a1 1 0 011 1v14a1 1 0 01-1 1H4a1 1 0 01-1-1V5a1 1 0 011-1zM9 4v16m5-7l-2 2 2 2"
            />
          ) : (
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M4 4h16a1 1 0 011 1v14a1 1 0 01-1 1H4a1 1 0 01-1-1V5a1 1 0 011-1zM9 4v16m4-7l2 2-2 2"
            />
          )}
        </svg>
      </button>

      <button
        type="button"
        onClick={onMenuClick}
        className="rounded-md p-2 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 md:hidden"
        aria-label="Open menu"
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      <Link href={homeHref} className="text-sm font-semibold tracking-tight md:hidden">
        AI HR Assistant
      </Link>

      {/* Desktop: quiet contextual label — the sidebar carries the real navigation. */}
      <p className="hidden text-[13px] font-medium text-zinc-400 md:block">
        {ROLE_LABEL[user.coarse_role]} workspace
      </p>
    </header>
  );
}
