"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { DetailSkeleton } from "@/components/loading";
import { useToast } from "@/components/toast";
import { api, ApiError } from "@/lib/api";

function PromptSettings() {
  const { addToast } = useToast();
  const [prompt, setPrompt] = useState("");
  const [isDefault, setIsDefault] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    try {
      const res = await api.setResumeReviewPrompt(prompt);
      setPrompt(res.prompt);
      setIsDefault(res.is_default);
      addToast("Settings saved.", "success");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    setSaving(true);
    setError(null);
    try {
      const res = await api.resetResumeReviewPrompt();
      setPrompt(res.prompt);
      setIsDefault(res.is_default);
      addToast("Reset to default prompt.", "success");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to reset.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <DetailSkeleton />;

  return (
    <section className="card flex h-full flex-col p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-zinc-900">Resume-Screening System Prompt</h2>
          <p className="text-xs text-zinc-400">Controls how candidates are scored and matched</p>
        </div>
        <span className={`badge ${isDefault ? "bg-zinc-100 text-zinc-600 ring-1 ring-inset ring-zinc-500/20" : "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/20"}`}>
          {isDefault ? "Default" : "Customized"}
        </span>
      </div>
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={14}
        className="input flex-1 font-mono text-[13px] leading-relaxed"
      />
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
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
    </section>
  );
}

function LlmConnectionSettings() {
  const { addToast } = useToast();
  const [apiBase, setApiBase] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiKeySet, setApiKeySet] = useState(false);
  const [isDefault, setIsDefault] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function applyConfig(res: { api_base: string; model: string; api_key_set: boolean; is_default: boolean }) {
    setApiBase(res.api_base);
    setModel(res.model);
    setApiKeySet(res.api_key_set);
    setIsDefault(res.is_default);
  }

  useEffect(() => {
    api
      .getLlmConfig()
      .then(applyConfig)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load settings."))
      .finally(() => setLoading(false));
  }, []);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const res = await api.setLlmConfig({ api_base: apiBase, model, api_key: apiKey || undefined });
      applyConfig(res);
      setApiKey("");
      addToast("LLM settings saved.", "success");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    setSaving(true);
    setError(null);
    try {
      const res = await api.resetLlmConfig();
      applyConfig(res);
      setApiKey("");
      addToast("LLM settings reset to default.", "success");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to reset.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <DetailSkeleton />;

  return (
    <section className="card flex h-full flex-col p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-zinc-900">LLM Provider Connection</h2>
          <p className="text-xs text-zinc-400">The model used for resume screening</p>
        </div>
        <span className={`badge ${isDefault ? "bg-zinc-100 text-zinc-600 ring-1 ring-inset ring-zinc-500/20" : "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/20"}`}>
          {isDefault ? "Default" : "Customized"}
        </span>
      </div>

      <div className="flex-1 space-y-4">
        <div>
          <label className="label">API Route</label>
          <input
            type="text"
            value={apiBase}
            onChange={(e) => setApiBase(e.target.value)}
            placeholder="https://ollama.com"
            className="input"
          />
        </div>
        <div>
          <label className="label">Model</label>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="gpt-oss:120b-cloud"
            className="input font-mono"
          />
        </div>
        <div>
          <label className="label">API Key</label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={apiKeySet ? "•••••••••••••• (set — leave blank to keep)" : "Not set"}
            className="input"
            autoComplete="off"
          />
          <p className="mt-1 text-xs text-zinc-400">
            Write-only — never displayed once saved. Leave blank to keep the current key.
          </p>
        </div>
      </div>

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
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
    </section>
  );
}

export default function ManagerSettingsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="AI Settings"
        description="Configure the LLM provider and the system prompt used to screen resumes against a job posting — this controls how candidates are scored and matched."
      />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <LlmConnectionSettings />
        <PromptSettings />
      </div>
    </div>
  );
}
