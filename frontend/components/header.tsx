"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { clearAuthToken } from "@/lib/auth";
import type { UserContext } from "@/lib/types";

const ROLE_LABEL: Record<UserContext["coarse_role"], string> = {
  HR_ADMIN: "Manager",
  EMPLOYEE: "Employee",
  CANDIDATE: "Candidate",
};

/** Slim top bar: mobile menu trigger + app mark + user avatar dropdown. */
export function Header({
  user,
  onMenuClick,
}: {
  user: UserContext;
  onMenuClick: () => void;
}) {
  const router = useRouter();
  const [dropdownOpen, setDropdownOpen] = useState(false);

  function signOut() {
    clearAuthToken();
    router.push("/login");
  }

  const homeHref =
    user.coarse_role === "HR_ADMIN"
      ? "/manager"
      : user.coarse_role === "CANDIDATE"
        ? "/candidate"
        : "/employee/chatbot";

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-zinc-200 bg-white/85 px-4 backdrop-blur sm:px-6">
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

      <div className="ml-auto flex items-center gap-2">
        <div className="relative">
          <button
            type="button"
            onClick={() => setDropdownOpen((o) => !o)}
            className={`flex items-center gap-2 rounded-md p-1.5 transition-colors hover:bg-zinc-100 ${
              dropdownOpen ? "bg-zinc-100" : ""
            }`}
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white">
              {user.display_name.charAt(0).toUpperCase()}
            </div>
            <div className="hidden text-left sm:block">
              <p className="text-sm font-medium leading-tight text-zinc-900">{user.display_name}</p>
              <p className="text-xs leading-tight text-zinc-400">{ROLE_LABEL[user.coarse_role]}</p>
            </div>
            <svg
              className={`hidden h-4 w-4 text-zinc-400 transition-transform sm:block ${
                dropdownOpen ? "rotate-180" : ""
              }`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {dropdownOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setDropdownOpen(false)} />
              <div className="animate-scale-in absolute right-0 top-full z-20 mt-2 w-56 overflow-hidden rounded-lg border border-zinc-200 bg-white py-1 shadow-lg">
                <div className="border-b border-zinc-100 px-3.5 py-2.5">
                  <p className="truncate text-sm font-medium text-zinc-900">{user.display_name}</p>
                  <p className="truncate text-xs text-zinc-400">{user.email}</p>
                </div>
                <div className="py-1">
                  <div className="px-3.5 py-1.5">
                    <p className="text-[11px] uppercase tracking-wider text-zinc-400">Role</p>
                    <p className="text-sm text-zinc-700">{ROLE_LABEL[user.coarse_role]}</p>
                  </div>
                </div>
                <div className="border-t border-zinc-100 py-1">
                  <button
                    type="button"
                    onClick={signOut}
                    className="menu-item menu-item-danger"
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={1.5}
                        d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
                      />
                    </svg>
                    Sign Out
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
