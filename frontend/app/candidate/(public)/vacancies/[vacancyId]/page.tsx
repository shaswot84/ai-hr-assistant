"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { BackLink } from "@/components/page-header";
import { StatusBadge } from "@/components/status";
import { DetailSkeleton } from "@/components/loading";
import { api, ApiError } from "@/lib/api";
import { getAuthToken, setAuthToken } from "@/lib/auth";
import type { ApplicationStatusView, Vacancy } from "@/lib/types";
import { useToast } from "@/components/toast";

const ALLOWED_EXTENSIONS = [".pdf", ".docx"];
const MAX_BYTES = 10 * 1024 * 1024;

interface ApplyForm {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  password: string;
}

const emptyForm: ApplyForm = { first_name: "", last_name: "", email: "", phone: "", password: "" };

/**
 * Public apply flow: first-time candidates give their details + CV (all
 * compulsory). Applying provisions their account (password chosen here) and
 * the application in one transaction, then signs them in automatically.
 */
function ApplySection({ vacancy }: { vacancy: Vacancy }) {
  const router = useRouter();
  const { addToast } = useToast();
  const [existing, setExisting] = useState<ApplicationStatusView | null | undefined>(undefined);
  const [form, setForm] = useState<ApplyForm>(emptyForm);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    // Only signed-in candidates can have "already applied" state — anonymous
    // visitors get the apply form straight away (no lookup, no sign-in prompt).
    if (!getAuthToken()) {
      Promise.resolve().then(() => setExisting(null));
      return;
    }
    api
      .myApplications()
      .then((apps) => setExisting(apps.find((a) => a.vacancy_id === vacancy.vacancy_id) ?? null))
      .catch(() => setExisting(null));
  }, [vacancy.vacancy_id]);

  function setField<K extends keyof ApplyForm>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    setError(null);
    const f = e.target.files?.[0] ?? null;
    if (!f) {
      setFile(null);
      return;
    }
    const lower = f.name.toLowerCase();
    if (!ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
      setError("Only PDF or DOCX resumes are accepted.");
      setFile(null);
      return;
    }
    if (f.size > MAX_BYTES) {
      setError("Resume too large. Max size is 10MB.");
      setFile(null);
      return;
    }
    setFile(f);
  }

  async function handleApply(e: React.FormEvent) {
    e.preventDefault();
    if (!file) {
      setError("Please upload your resume — it's required to apply.");
      return;
    }
    if (form.password.length < 8) {
      setError("Password must be at least 8 characters — you'll use it to sign in.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("first_name", form.first_name);
      formData.append("last_name", form.last_name);
      formData.append("email", form.email);
      formData.append("phone", form.phone);
      formData.append("password", form.password);

      await api.applyAsNewCandidate(vacancy.vacancy_id, formData);
      addToast("Application submitted — your account was created.", "success");

      // Sign the new candidate straight into their portal (password they just set).
      const login = await api.login(form.email, form.password);
      setAuthToken(login.access_token);
      router.push("/candidate/applications");
    } catch (err) {
      if (err instanceof ApiError && /already exists/i.test(err.detail)) {
        setError(`${err.detail} — use the "Sign in" link above to apply from your account.`);
      } else {
        setError(err instanceof ApiError ? err.detail : "Failed to submit application.");
      }
      setSubmitting(false);
    }
  }

  if (existing === undefined) return null;

  if (existing) {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-5">
        <p className="text-sm text-emerald-900">
          You&apos;ve already applied to this role — status:{" "}
          <StatusBadge status={existing.application_status} />
        </p>
      </div>
    );
  }

  if (vacancy.status !== "OPEN") {
    return (
      <div className="card p-5">
        <p className="text-sm text-zinc-500">This vacancy is no longer accepting applications.</p>
      </div>
    );
  }

  return (
    <div className="card p-5">
      <h2 className="text-sm font-semibold text-zinc-900">Apply for this role</h2>
      <p className="mt-1 text-sm text-zinc-500">
        Tell us about yourself and upload your resume. Your details create your account — you&apos;ll
        use your email and the password below to track this application.
      </p>

      <form onSubmit={handleApply} className="mt-4 space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="label">First Name *</label>
            <input
              required
              className="input"
              value={form.first_name}
              onChange={(e) => setField("first_name", e.target.value)}
              placeholder="Jane"
            />
          </div>
          <div>
            <label className="label">Last Name *</label>
            <input
              required
              className="input"
              value={form.last_name}
              onChange={(e) => setField("last_name", e.target.value)}
              placeholder="Doe"
            />
          </div>
          <div>
            <label className="label">Email *</label>
            <input
              required
              type="email"
              className="input"
              value={form.email}
              onChange={(e) => setField("email", e.target.value)}
              placeholder="jane.doe@email.com"
            />
          </div>
          <div>
            <label className="label">Phone *</label>
            <input
              required
              className="input"
              value={form.phone}
              onChange={(e) => setField("phone", e.target.value)}
              placeholder="+91 90000 00000"
            />
          </div>
          <div className="sm:col-span-2">
            <label className="label">Set a Password * (min 8 characters)</label>
            <input
              required
              type="password"
              minLength={8}
              className="input"
              value={form.password}
              onChange={(e) => setField("password", e.target.value)}
              placeholder="You'll use this to sign in and track your application"
            />
          </div>
        </div>

        <div>
          <label className="label">Resume *</label>
          <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-zinc-300 bg-zinc-50/50 px-4 py-8 text-center transition-colors hover:border-blue-400 hover:bg-blue-50/40">
            <svg className="h-7 w-7 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
              />
            </svg>
            <span className="text-sm font-medium text-zinc-700">
              {file ? file.name : "Click to choose your resume"}
            </span>
            <span className="text-xs text-zinc-400">PDF or DOCX, max 10MB — required</span>
            <input type="file" accept=".pdf,.docx" required onChange={handleFileChange} className="hidden" />
          </label>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-zinc-400">Your resume is only used to screen this application.</p>
          <button type="submit" disabled={submitting} className="btn-primary shrink-0">
            {submitting ? "Submitting…" : "Submit Application"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function VacancyDetailPage() {
  const params = useParams<{ vacancyId: string }>();
  const [vacancy, setVacancy] = useState<Vacancy | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getVacancy(params.vacancyId)
      .then(setVacancy)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Vacancy not found."));
  }, [params.vacancyId]);

  return (
    <div className="space-y-6">
      {error && <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>}
      {!error && !vacancy && <DetailSkeleton />}
      {vacancy && (
        <>
          <BackLink href="/candidate" label="All vacancies" />
          <div className="card p-6">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-xl font-semibold tracking-tight text-zinc-900">{vacancy.title}</h1>
              <StatusBadge status={vacancy.status} />
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-zinc-500">
              <span className="font-medium text-zinc-700">{vacancy.department_name ?? "—"}</span>
              <span className="text-zinc-300">·</span>
              <span>{vacancy.employment_type.replaceAll("_", " ")}</span>
            </div>
            {vacancy.description && (
              <p className="mt-4 max-w-3xl whitespace-pre-wrap text-sm leading-relaxed text-zinc-600">
                {vacancy.description}
              </p>
            )}
          </div>
          <ApplySection vacancy={vacancy} />
        </>
      )}
    </div>
  );
}
