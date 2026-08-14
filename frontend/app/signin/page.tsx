"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { setAuthToken } from "@/lib/auth";
import { useToast } from "@/components/toast";

const ROLE_HOME: Record<string, string> = {
  HR_ADMIN: "/manager",
  CANDIDATE: "/candidate",
  EMPLOYEE: "/employee",
};

const DEMOS: Record<string, { email: string; password: string }> = {
  manager: { email: "manager@example.com", password: "manager123" },
  employee: { email: "employee@example.com", password: "employee123" },
  candidate: { email: "candidate@example.com", password: "candidate123" },
};

const DEMO_LABELS: Record<string, string> = {
  manager: "Manager",
  employee: "Employee",
  candidate: "Candidate",
};

export default function SignInPage() {
  const router = useRouter();
  const { addToast } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [selectedDemo, setSelectedDemo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);

  function fillDemo(role: keyof typeof DEMOS) {
    setEmail(DEMOS[role].email);
    setPassword(DEMOS[role].password);
    setSelectedDemo(role);
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
    <div className="flex min-h-screen flex-col items-center justify-center bg-zinc-50 px-4 py-12">
      <Link href="/welcome" className="mb-6 flex items-center gap-2.5">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-600 shadow-sm">
          <svg className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
            />
          </svg>
        </div>
        <div className="leading-tight">
          <p className="text-[15px] font-semibold tracking-tight text-zinc-900">AI HR Assistant</p>
          <p className="text-xs text-zinc-400">HR Platform</p>
        </div>
      </Link>

      <div className="card w-full max-w-md p-8 sm:p-10">
        <h1 className="text-center text-xl font-semibold text-zinc-900">Welcome back</h1>
        <p className="mt-1 text-center text-sm text-zinc-500">
          Sign in to continue to your HR workspace.
        </p>

        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <div>
            <label className="label" htmlFor="signin-email">
              Email address
            </label>
            <input
              id="signin-email"
              ref={emailRef}
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
            <label className="label" htmlFor="signin-password">
              Password
            </label>
            <div className="relative">
              <input
                id="signin-password"
                type={showPassword ? "text" : "password"}
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input pr-11"
                placeholder="••••••••"
              />
              <button
                type="button"
                onClick={() => setShowPassword((s) => !s)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-zinc-400 transition-colors hover:text-zinc-600"
              >
                {showPassword ? (
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.75}
                      d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
                    />
                  </svg>
                ) : (
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.75}
                      d="M15 12a3 3 0 11-6 0 3 3 0 016 0zM2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                    />
                  </svg>
                )}
              </button>
            </div>
          </div>

          {error && <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>}

          <button type="submit" disabled={submitting} className="btn-primary w-full py-2.5">
            {submitting ? "Signing in…" : "Sign In"}
          </button>
        </form>

        <div className="mt-7">
          <div className="flex items-center gap-3">
            <span className="h-px flex-1 bg-zinc-200" />
            <span className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
              or use a demo account
            </span>
            <span className="h-px flex-1 bg-zinc-200" />
          </div>
          <div className="mt-4 grid grid-cols-3 gap-2">
            {(Object.keys(DEMOS) as Array<keyof typeof DEMOS>).map((role) => {
              const active = selectedDemo === role;
              return (
                <button
                  key={role}
                  type="button"
                  onClick={() => fillDemo(role)}
                  aria-pressed={active}
                  className={`flex items-center justify-center gap-1.5 rounded-md border px-2 py-2 text-xs font-medium transition-colors ${
                    active
                      ? "border-blue-500 bg-blue-50 text-blue-700"
                      : "border-zinc-200 bg-white text-zinc-600 hover:border-zinc-300 hover:text-zinc-900"
                  }`}
                >
                  {active && (
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                  {DEMO_LABELS[role]}
                </button>
              );
            })}
          </div>
          <p className="mt-2.5 text-center text-xs text-zinc-400">
            Demo accounts fill the form automatically — just press Sign In.
          </p>
          <p className="mt-1.5 text-center text-[11px] text-zinc-400">
            First time applying?{" "}
            <Link href="/candidate" className="link">
              Browse open roles
            </Link>{" "}
            — no account needed until you apply.
          </p>
        </div>
      </div>
    </div>
  );
}
