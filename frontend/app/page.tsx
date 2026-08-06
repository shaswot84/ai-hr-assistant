"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { getAuthToken } from "@/lib/auth";

/**
 * Root route: role-aware dispatcher. If the user has no stored JWT, go to the
 * login page. Otherwise resolve the coarse role from `/api/auth/me` and route
 * to the matching portal (manager vs candidate/employee).
 */
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
        router.replace(res.user.coarse_role === "HR_ADMIN" ? "/manager" : "/candidate");
      })
      .catch(() => {
        if (!cancelled) router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-sm text-muted">Loading…</p>
    </div>
  );
}