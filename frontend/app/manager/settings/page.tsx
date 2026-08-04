"use client";

import { useEffect, useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { api } from "@/lib/api";

/**
 * Manager settings page. Currently exposes one setting: the system prompt sent
 * to the LLM when it evaluates resumes. Managers can view the current prompt,
 * edit it, save it, or reset it back to the default.
 */
export default function ManagerSettingsPage() {
  const [prompt, setPrompt] = useState<string | null>(null);
  const [isDefault, setIsDefault] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .getResumeReviewPrompt()
      .then((res) => {
        setPrompt(res.prompt);
        setIsDefault(res.is_default);
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load settings"),
      );
  }, []);

  /** Persists the edited system prompt via the API. */
  async function save() {
    if (prompt === null) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.setResumeReviewPrompt(prompt);
      setPrompt(res.prompt);
      setIsDefault(res.is_default);
      setNotice("Resume review prompt saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  /** Restores the default prompt via the API. */
  async function reset() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.resetResumeReviewPrompt();
      setPrompt(res.prompt);
      setIsDefault(res.is_default);
      setNotice("Reset to the default prompt.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset settings");
    } finally {
      setSaving(false);
    }
  }

  const inputClass =
    "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none transition-colors focus:border-border-strong";

  return (
    <PortalGuard allowedRoles={["HR_ADMIN"]}>
      <div className="animate-fade-in mx-auto max-w-2xl">
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted">
          Configure how the AI reviews resumes submitted by candidates.
        </p>

        {error && <p className="mt-6 text-sm text-danger">{error}</p>}

        {prompt === null && !error && <p className="mt-6 text-sm text-muted">Loading…</p>}

        {prompt !== null && (
          <div className="mt-6 space-y-4 rounded-xl border border-border bg-surface p-6">
            <div>
              <div className="flex items-center justify-between gap-4">
                <label className="text-xs font-medium text-muted" htmlFor="review-prompt">
                  Resume review system prompt
                </label>
                {!isDefault && (
                  <span className="rounded-full border border-border-strong px-2.5 py-0.5 text-[11px] font-medium text-muted">
                    custom
                  </span>
                )}
              </div>
              <p className="mt-1 text-xs text-muted">
                Sent to the LLM when scoring a candidate&apos;s resume against a job. Edit it to
                change how the AI evaluates candidates.
              </p>
              <textarea
                id="review-prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={10}
                className={`${inputClass} mt-3 resize-y`}
              />
            </div>

            {notice && <p className="text-sm text-foreground">{notice}</p>}

            <div className="flex gap-3">
              <button
                type="button"
                onClick={save}
                disabled={saving}
                className="rounded-full bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {saving ? "Saving…" : "Save prompt"}
              </button>
              <button
                type="button"
                onClick={reset}
                disabled={saving || isDefault}
                className="rounded-full border border-border px-5 py-2.5 text-sm font-medium transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40"
              >
                Reset to default
              </button>
            </div>
          </div>
        )}
      </div>
    </PortalGuard>
  );
}
