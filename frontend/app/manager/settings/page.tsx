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
      <div className="animate-fade-in space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">AI Settings</h1>
          <p className="mt-1 text-sm text-gray-500">
            Configure the system prompt used to instruct the AI when it reviews resumes against a
            job posting.
          </p>
        </div>

        {loading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : (
          <div className="card max-w-2xl p-6">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-semibold text-gray-900">Resume-Review System Prompt</span>
              <span className={`badge ${isDefault ? "bg-gray-100 text-gray-600" : "bg-blue-100 text-blue-700"}`}>
                {isDefault ? "Default" : "Customized"}
              </span>
            </div>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={10}
              className="input"
            />
            {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
            {saved && <p className="mt-3 text-sm text-green-700">Saved.</p>}
            <div className="mt-4 flex gap-3">
              <button type="button" onClick={handleSave} disabled={saving} className="btn-primary">
                {saving ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                onClick={handleReset}
                disabled={saving || isDefault}
                className="btn-secondary"
              >
                Reset to Default
              </button>
            </div>
          </div>
        )}
      </div>
    </PortalGuard>
  );
}
