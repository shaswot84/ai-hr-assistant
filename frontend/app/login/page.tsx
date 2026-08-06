"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { setAuthToken } from "@/lib/auth";

const ROLE_HOME: Record<string, string> = {
  HR_ADMIN: "/manager",
  CANDIDATE: "/candidate",
  EMPLOYEE: "/employee",
};

/** Login page: email + password, works for all three roles (role comes back from the API). */
export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await api.login(email, password);
      setAuthToken(res.access_token);
      router.push(ROLE_HOME[res.user.coarse_role] ?? "/");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not sign in. Is the backend running?");
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <h1 className="text-center text-2xl font-semibold tracking-tight">AI HR Assistant</h1>
        <p className="mt-1 text-center text-sm text-muted">Sign in with your account to continue.</p>

        <form
          onSubmit={handleSubmit}
          className="mt-6 space-y-4 rounded-xl border border-border bg-surface p-6"
        >
          <label className="block">
            <span className="text-xs font-medium text-muted">Email</span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-foreground"
              placeholder="you@example.com"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-muted">Password</span>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-foreground"
              placeholder="••••••••"
            />
          </label>

          {error && (
            <p className="text-sm text-red-600" role="alert">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <div className="mt-4 rounded-lg border border-border bg-surface p-3 text-xs text-muted">
          <p className="font-medium text-foreground">Demo accounts</p>
          <p className="mt-1">Manager: manager@example.com / manager123</p>
          <p>Candidate: candidate@example.com / candidate123</p>
        </div>
      </div>
    </div>
  );
}
