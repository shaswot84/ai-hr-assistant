"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { setAuthToken } from "@/lib/auth";
import { useToast } from "@/components/toast";

const ROLE_HOME: Record<string, string> = {
  HR_ADMIN: "/manager",
  CANDIDATE: "/candidate",
  EMPLOYEE: "/employee",
};

const FEATURES = [
  "Post vacancies and manage the pipeline",
  "AI-scored resumes matched to the job",
  "One-click shortlist or reject, with email",
  "A role-aware portal for every hire",
];

const DEMOS: Record<string, { email: string; password: string }> = {
  manager: { email: "manager@example.com", password: "manager123" },
  candidate: { email: "candidate@example.com", password: "candidate123" },
};

export default function LoginPage() {
  const router = useRouter();
  const { addToast } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function fillDemo(role: keyof typeof DEMOS) {
    setEmail(DEMOS[role].email);
    setPassword(DEMOS[role].password);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await api.login(email, password);
      setAuthToken(res.access_token);
      addToast(`Logged in successfully as ${res.user.display_name}.`, "success");
      router.push(ROLE_HOME[res.user.coarse_role] ?? "/");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not sign in. Is the backend running?");
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen bg-white">
      {/* Left brand panel */}
      <div className="hidden w-1/2 flex-col justify-between bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800 p-12 text-white lg:flex">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/20">
            <svg className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </div>
          <span className="text-xl font-bold">AI HR Assistant</span>
        </div>

        <div>
          <h2 className="mb-4 text-4xl font-bold leading-tight">
            Hiring,
            <br />
            without the busywork.
          </h2>
          <p className="mb-8 text-lg text-blue-200">
            Post a role, let AI score every resume against it, and decide — all from one
            dashboard.
          </p>
          <div className="space-y-3">
            {FEATURES.map((f) => (
              <div key={f} className="flex items-center gap-2 text-blue-100">
                <svg className="h-5 w-5 shrink-0 text-blue-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                {f}
              </div>
            ))}
          </div>
        </div>

        <p className="text-sm text-blue-300">© 2026 AI HR Assistant</p>
      </div>

      {/* Right form panel */}
      <div className="flex flex-1 flex-col">
        <div className="flex items-center gap-2 p-6 lg:hidden">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-600">
            <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </div>
          <span className="font-bold text-gray-900">AI HR Assistant</span>
        </div>

        <div className="flex flex-1 items-center justify-center p-8">
          <div className="w-full max-w-sm">
            <h1 className="mb-1 text-2xl font-bold text-gray-900">Sign in</h1>
            <p className="mb-8 text-sm text-gray-500">Welcome back — pick up where you left off.</p>

            <div className="mb-6 rounded-xl border border-blue-100 bg-blue-50 p-4">
              <p className="mb-2 text-xs font-semibold text-blue-700">Try a demo account</p>
              <div className="flex gap-2">
                {(Object.keys(DEMOS) as Array<keyof typeof DEMOS>).map((role) => (
                  <button
                    key={role}
                    type="button"
                    onClick={() => fillDemo(role)}
                    className="flex-1 rounded-lg border border-blue-200 bg-white px-2 py-1.5 text-xs capitalize text-gray-700 transition-all hover:border-blue-600 hover:bg-blue-600 hover:text-white"
                  >
                    {role}
                  </button>
                ))}
              </div>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="label">Email address</label>
                <input
                  type="email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="input"
                  placeholder="you@example.com"
                />
              </div>

              <div>
                <label className="label">Password</label>
                <input
                  type="password"
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input"
                  placeholder="••••••••"
                />
              </div>

              {error && (
                <p className="text-sm text-red-600" role="alert">
                  {error}
                </p>
              )}

              <button type="submit" disabled={submitting} className="btn-primary w-full py-2.5">
                {submitting ? "Signing in…" : "Sign in"}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
