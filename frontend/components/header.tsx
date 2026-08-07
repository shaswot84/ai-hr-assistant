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

/** Top bar: mobile menu trigger + user avatar dropdown, rendered above every portal page. */
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
    <header className="z-30 flex h-16 shrink-0 items-center justify-between border-b border-sky-200 bg-white px-4 sm:px-6">
      <button
        type="button"
        onClick={onMenuClick}
        className="rounded-lg p-2 text-gray-500 hover:bg-sky-100 md:hidden"
        aria-label="Open menu"
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      <Link href={homeHref} className="text-sm font-semibold tracking-tight md:hidden">
        AI HR Assistant
      </Link>

      <div className="ml-auto flex items-center gap-2">
        <div className="relative">
          <button
            type="button"
            onClick={() => setDropdownOpen((o) => !o)}
            className="flex items-center gap-2 rounded-lg p-1.5 transition-colors hover:bg-sky-100"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white">
              {user.display_name.charAt(0).toUpperCase()}
            </div>
            <div className="hidden text-left sm:block">
              <p className="text-sm font-medium leading-tight text-gray-900">{user.display_name}</p>
              <p className="text-xs leading-tight text-gray-500">{ROLE_LABEL[user.coarse_role]}</p>
            </div>
            <svg className="hidden h-4 w-4 text-gray-400 sm:block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {dropdownOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setDropdownOpen(false)} />
              <div className="animate-fade-in absolute right-0 top-full z-20 mt-2 w-48 rounded-xl border border-sky-200 bg-white py-1 shadow-lg">
                <div className="border-b border-gray-100 px-4 py-2.5">
                  <p className="text-sm font-medium text-gray-900">{user.display_name}</p>
                  <p className="text-xs text-gray-500">{user.email}</p>
                </div>
                <button
                  type="button"
                  onClick={signOut}
                  className="flex w-full items-center gap-2 px-4 py-2 text-sm text-red-600 transition-colors hover:bg-red-50"
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                  </svg>
                  Sign Out
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
