"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

const ROLES = [
  { value: "CANDIDATE", label: "Candidate", email: "candidate@example.com" },
  { value: "HR_ADMIN", label: "Manager", email: "manager@example.com" },
  { value: "EMPLOYEE", label: "Employee", email: "employee@example.com" },
] as const;

/**
 * Dev login page. Lets the user pick a persona (role) or type an email, then
 * calls the dev-stub auth endpoint. Replaces the Keycloak login flow during
 * local development.
 */
export default function LoginPage() {
  const router = useRouter();
  const [role, setRole] = useState<(typeof ROLES)[number]>(
    ROLES[0] as (typeof ROLES)[number],
  );
  const [email, setEmail] = useState<string>(ROLES[0].email);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  /** Logs in via the dev endpoint and routes the user to their role's portal. */
  async function login() {
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.devLogin(role.value, email, role.label);
      // Managers go to the manager portal; candidates/employees to the candidate portal.
      router.push(res.user.coarse_role === "HR_ADMIN" ? "/manager" : "/candidate");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      setSubmitting(false);
    }
  }

  // Portal destination shown next to each role option on the login card.
  const destinations: Record<string, string> = {
    CANDIDATE: "/candidate",
    HR_ADMIN: "/manager",
    EMPLOYEE: "/candidate",
  };

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center px-4">
      <div className="animate-fade-in w-full max-w-sm">
        <h1 className="text-2xl font-semibold tracking-tight">AI HR Assistant</h1>
        <p className="mt-1 text-sm text-muted">
          Sign in to continue. In development, pick a persona to simulate.
        </p>

        <div className="mt-6 space-y-2">
          {ROLES.map((r) => (
            <button
              key={r.value}
              type="button"
              onClick={() => {
                setRole(r);
                setEmail(r.email);
              }}
              className={`flex w-full items-center justify-between rounded-xl border px-4 py-3 text-left transition-colors ${
                role.value === r.value
                  ? "border-foreground bg-surface-hover"
                  : "border-border bg-surface hover:bg-surface-hover"
              }`}
            >
              <div>
                <p className="text-sm font-medium">{r.label}</p>
                <p className="text-xs text-muted">{r.email}</p>
              </div>
              <span className="text-xs text-muted">{destinations[r.value]}</span>
            </button>
          ))}
        </div>

        <div className="mt-4 space-y-2">
          <label className="block text-xs font-medium text-muted" htmlFor="login-email">
            Email
          </label>
          <input
            id="login-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none transition-colors focus:border-border-strong"
          />
        </div>

        {error && <p className="mt-3 text-sm text-danger">{error}</p>}

        <button
          type="button"
          onClick={login}
          disabled={submitting}
          className="mt-5 w-full rounded-full bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </div>
    </div>
  );
}