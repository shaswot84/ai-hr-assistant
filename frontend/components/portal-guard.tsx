"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { CoarseRole, UserContext } from "@/lib/types";
import { Header } from "@/components/header";

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
        if (!allowedRoles.includes(res.user.coarse_role)) {
          router.replace("/login");
          return;
        }
        setUser(res.user);
        setChecking(false);
      })
      .catch(() => {
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