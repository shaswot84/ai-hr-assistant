"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { DetailSkeleton } from "@/components/loading";
import { useToast } from "@/components/toast";
import { api, ApiError } from "@/lib/api";

interface PromptResult {
  prompt: string;
  is_default: boolean;
}

function PromptSettings({
  title,
  description,
  rows = 14,
  get,
  set,
  reset,
}: {
  title: string;
  description: string;
  rows?: number;
  get: () => Promise<PromptResult>;
  set: (prompt: string) => Promise<PromptResult>;
  reset: () => Promise<PromptResult>;
}) {
  const { addToast } = useToast();
  const [prompt, setPrompt] = useState("");
  const [isDefault, setIsDefault] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get()
      .then((res) => {
        setPrompt(res.prompt);
        setIsDefault(res.is_default);
      })
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load settings."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const res = await set(prompt);
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
      const res = await reset();
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
          <h2 className="text-sm font-semibold text-zinc-900">{title}</h2>
          <p className="text-xs text-zinc-400">{description}</p>
        </div>
        <span className={`badge ${isDefault ? "bg-zinc-100 text-zinc-600 ring-1 ring-inset ring-zinc-500/20" : "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/20"}`}>
          {isDefault ? "Default" : "Customized"}
        </span>
      </div>
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={rows}
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
  const [showApiKey, setShowApiKey] = useState(false);
  const [isDefault, setIsDefault] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function applyConfig(res: { api_base: string; model: string; api_key: string; is_default: boolean }) {
    setApiBase(res.api_base);
    setModel(res.model);
    setApiKey(res.api_key);
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
      const res = await api.setLlmConfig({ api_base: apiBase, model, api_key: apiKey });
      applyConfig(res);
      addToast("LLM settings saved — takes effect on the next resume evaluation.", "success");
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
          <div className="relative">
            <input
              type={showApiKey ? "text" : "password"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Not set"
              className="input pr-11 font-mono"
              autoComplete="off"
            />
            <button
              type="button"
              onClick={() => setShowApiKey((s) => !s)}
              aria-label={showApiKey ? "Hide API key" : "Show API key"}
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-zinc-400 transition-colors hover:text-zinc-600"
            >
              {showApiKey ? (
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
          <p className="mt-1 text-xs text-zinc-400">
            Stored directly in the server&apos;s .env file — hidden by default since it&apos;s a secret.
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
        description="Configure the LLM provider and the system prompts used to screen resumes and generate scoring keywords."
      />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <LlmConnectionSettings />
        <PromptSettings
          title="Resume-Screening System Prompt"
          description="Controls how candidates are scored and matched"
          get={api.getResumeReviewPrompt}
          set={api.setResumeReviewPrompt}
          reset={api.resetResumeReviewPrompt}
        />
        <PromptSettings
          title="Keyword-Suggestion System Prompt"
          description="Controls the keywords/tiers suggested by 'Generate Weighted Keywords' when posting a vacancy"
          get={api.getKeywordSuggestionPrompt}
          set={api.setKeywordSuggestionPrompt}
          reset={api.resetKeywordSuggestionPrompt}
        />
      </div>
    </div>
  );
}
