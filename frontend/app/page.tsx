"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { getAuthToken } from "@/lib/auth";

const ROLE_HOME: Record<string, string> = {
  HR_ADMIN: "/manager",
  CANDIDATE: "/candidate",
  EMPLOYEE: "/employee",
};

/** Root route: dispatches to the role-appropriate portal, or /login if unauthenticated. */
export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    if (!getAuthToken()) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    api
      .me()
      .then((res) => {
        if (cancelled) return;
        router.replace(ROLE_HOME[res.user.coarse_role] ?? "/login");
      })
      .catch(() => {
        if (!cancelled) router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50">
      <p className="text-sm text-zinc-500">Loading…</p>
    </div>
  );
}
