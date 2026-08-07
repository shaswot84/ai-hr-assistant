"use client";

import { useEffect, useState } from "react";
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
    <div className="card max-w-2xl p-6">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-semibold text-gray-900">Resume-Screening System Prompt</span>
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
    <div className="card max-w-2xl p-6">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-semibold text-gray-900">LLM Provider Connection</span>
        <span className={`badge ${isDefault ? "bg-gray-100 text-gray-600" : "bg-blue-100 text-blue-700"}`}>
          {isDefault ? "Default" : "Customized"}
        </span>
      </div>

      <div className="space-y-4">
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
            className="input"
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
          <p className="mt-1 text-xs text-gray-400">
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
    </div>
  );
}

export default function ManagerSettingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">AI Settings</h1>
        <p className="mt-1 text-sm text-gray-500">
          Configure the LLM provider and the system prompt used to screen resumes against a job
          posting — this controls how candidates are scored and matched, not resume-writing feedback.
        </p>
      </div>

      <LlmConnectionSettings />
      <PromptSettings />
    </div>
  );
}
