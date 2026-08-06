"use client";

import { useEffect, useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { api, ApiError } from "@/lib/api";

export default function ManagerSettingsPage() {
  const [prompt, setPrompt] = useState("");
  const [isDefault, setIsDefault] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api
      .getResumeReviewPrompt()
      .then((res) => {
        setPrompt(res.prompt);
        setIsDefault(res.is_default);
      })
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load settings."))
      .finally(() => setLoading(false));
  }, []);

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const res = await api.setResumeReviewPrompt(prompt);
      setPrompt(res.prompt);
      setIsDefault(res.is_default);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const res = await api.resetResumeReviewPrompt();
      setPrompt(res.prompt);
      setIsDefault(res.is_default);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to reset.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <PortalGuard allowedRoles={["HR_ADMIN"]}>
      <div className="mb-6">
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="mt-1 text-sm text-muted">
          Configure the system prompt used to instruct the AI when it reviews resumes against a
          job posting.
        </p>
      </div>

      {loading ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : (
        <div className="max-w-2xl space-y-4 rounded-xl border border-border bg-surface p-6">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Resume-review system prompt</span>
            <span className="text-xs text-muted">{isDefault ? "Default" : "Customized"}</span>
          </div>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={10}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-foreground"
          />
          {error && <p className="text-sm text-red-600">{error}</p>}
          {saved && <p className="text-sm text-emerald-700">Saved.</p>}
          <div className="flex gap-3">
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={handleReset}
              disabled={saving || isDefault}
              className="rounded-lg border border-border bg-surface px-4 py-2 text-sm font-medium transition-colors hover:bg-surface-hover disabled:opacity-50"
            >
              Reset to default
            </button>
          </div>
        </div>
      )}
    </PortalGuard>
  );
}
