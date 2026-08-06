"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { setAuthToken } from "@/lib/auth";

/**
 * Login page: collects email + password and exchanges them for a JWT access
 * token via the backend. On success the token is stored and the user is routed
 * to the role-aware landing page.
 */
export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  /** Submits the credentials; on success stores the token and redirects home. */
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await api.login(email, password);
      setAuthToken(res.access_token);
      router.push("/");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("Could not sign in. Is the backend running?");
      }
      setSubmitting(false);
    }
  }

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center px-4">
      <div className="animate-fade-in w-full max-w-sm">
        <h1 className="text-center text-2xl font-semibold tracking-tight">
          AI HR Assistant
        </h1>
        <p className="mt-1 text-center text-sm text-muted">
          Sign in with your account to continue.
        </p>

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
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition-colors focus:border-foreground"
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
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition-colors focus:border-foreground"
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
      </div>
    </div>
  );
}