"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { MetricCard } from "@/components/metric-card";
import { Modal } from "@/components/modal";
import { ListSkeleton } from "@/components/loading";
import { EmptyState } from "@/components/empty-state";
import { Pagination } from "@/components/pagination";
import { SortableTh, Th, toggleSort, type SortState } from "@/components/table";
import { useToast } from "@/components/toast";
import { api, ApiError } from "@/lib/api";
import type { AuditFilterOptions, AuditLogEntry, AuditLogsResponse } from "@/lib/types";

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

type DateFilterPreset = "ALL" | "TODAY" | "7D" | "30D" | "CUSTOM";

function formatRelativeTime(dateStr: string): string {
  const now = new Date();
  const date = new Date(dateStr);
  const diffSec = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}h ago`;
  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function formatExactTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
}

function actionTone(action: string): { bg: string; text: string; ring: string; icon: string } {
  const upper = action.toUpperCase();
  if (upper.includes("LOW_CONFIDENCE") || upper.includes("NO_INFO")) {
    return {
      bg: "bg-amber-50",
      text: "text-amber-700",
      ring: "ring-amber-600/20",
      icon: "M12 9v2m0 4h.01M5 19h14a2 2 0 001.66-3.32l-7-11.66a2 2 0 00-3.32 0l-7 11.66A2 2 0 005 19z",
    };
  }
  if (
    upper.includes("CREATE") ||
    upper.includes("HIRE") ||
    upper.includes("APPROVE") ||
    upper.includes("SHORTLIST") ||
    upper.includes("REOPEN")
  ) {
    return {
      bg: "bg-emerald-50",
      text: "text-emerald-700",
      ring: "ring-emerald-600/20",
      icon: "M12 6v6m0 0v6m0-6h6m-6 0H6",
    };
  }
  if (
    upper.includes("REJECT") ||
    upper.includes("DELETE") ||
    upper.includes("CLOSE") ||
    upper.includes("DEACTIVATE") ||
    upper.includes("WITHDRAW") ||
    upper.includes("CANCEL")
  ) {
    return {
      bg: "bg-red-50",
      text: "text-red-700",
      ring: "ring-red-600/20",
      icon: "M6 18L18 6M6 6l12 12",
    };
  }
  if (upper.includes("UPDATE") || upper.includes("EDIT") || upper.includes("MODIFY")) {
    return {
      bg: "bg-blue-50",
      text: "text-blue-700",
      ring: "ring-blue-600/20",
      icon: "M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z",
    };
  }
  if (upper.includes("LOGIN") || upper.includes("AUTH")) {
    return {
      bg: "bg-purple-50",
      text: "text-purple-700",
      ring: "ring-purple-600/20",
      icon: "M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z",
    };
  }
  if (upper.includes("REQUEST")) {
    return {
      bg: "bg-amber-50",
      text: "text-amber-700",
      ring: "ring-amber-600/20",
      icon: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z",
    };
  }
  return {
    bg: "bg-zinc-100",
    text: "text-zinc-700",
    ring: "ring-zinc-500/20",
    icon: "M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  };
}

function roleBadgeTone(role: string | null): string {
  if (role === "HR_ADMIN") return "bg-purple-50 text-purple-700 ring-purple-600/20";
  if (role === "EMPLOYEE") return "bg-blue-50 text-blue-700 ring-blue-600/20";
  if (role === "CANDIDATE") return "bg-amber-50 text-amber-700 ring-amber-600/20";
  return "bg-zinc-100 text-zinc-600 ring-zinc-500/20";
}

function targetShortcutLink(targetType: string | null, targetId: string | null): string | null {
  if (!targetType || !targetId) return null;
  const t = targetType.toLowerCase();
  if (t === "vacancy") return `/manager/vacancies/${targetId}`;
  if (t === "application") return `/manager/applications/${targetId}`;
  if (t === "employee") return `/manager/people`;
  if (t === "leaverequest" || t === "leave_request") return `/manager/leave`;
  if (t === "department" || t === "designation") return `/manager/people`;
  return null;
}

/** Audit actions the chat layer writes for failed knowledge turns. */
const BAD_ANSWER_ACTIONS = new Set(["LOW_CONFIDENCE_ANSWER", "NO_INFO_ANSWER"]);

/** Payload shape written by the chat layer for failed-answer audit rows. */
interface BadAnswerPayload {
  question?: unknown;
  answer?: unknown;
  confidence?: unknown;
  actor_role?: unknown;
  citation_count?: unknown;
  reason?: unknown;
  retrieved_context?: unknown;
}

function isBadAnswerEntry(entry: AuditLogEntry): boolean {
  return BAD_ANSWER_ACTIONS.has(entry.action);
}

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** The question/answer payload of a failed-answer entry, if present. */
function badAnswerPayload(entry: AuditLogEntry): BadAnswerPayload | null {
  if (!isBadAnswerEntry(entry) || !entry.new_state) return null;
  const state = entry.new_state as BadAnswerPayload;
  return typeof state.question === "string" ? state : null;
}

function formatJsonValue(val: unknown): string {
  if (val === null || val === undefined) return "—";
  if (typeof val === "object") return JSON.stringify(val);
  return String(val);
}

interface DiffRow {
  key: string;
  oldVal: unknown;
  newVal: unknown;
  status: "added" | "modified" | "removed" | "unchanged";
}

function computeDiff(
  prev: Record<string, unknown> | null,
  next: Record<string, unknown> | null
): DiffRow[] {
  const p = prev || {};
  const n = next || {};
  const allKeys = Array.from(new Set([...Object.keys(p), ...Object.keys(n)])).sort();

  return allKeys.map((key) => {
    const hasOld = key in p;
    const hasNew = key in n;
    const oldVal = p[key];
    const newVal = n[key];

    let status: DiffRow["status"] = "unchanged";
    if (!hasOld && hasNew) status = "added";
    else if (hasOld && !hasNew) status = "removed";
    else if (JSON.stringify(oldVal) !== JSON.stringify(newVal)) status = "modified";

    return { key, oldVal: hasOld ? oldVal : undefined, newVal: hasNew ? newVal : undefined, status };
  });
}

/** Component for Deep Inspection Drawer / Modal */
function AuditInspectionModal({
  entry,
  isOpen,
  onClose,
}: {
  entry: AuditLogEntry | null;
  isOpen: boolean;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"qa" | "diff" | "raw">("diff");
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [lastEntryId, setLastEntryId] = useState<string | null>(null);
  const { addToast } = useToast();

  // Reset to the default tab per inspected entry (adjusting state during
  // render, per React's "you might not need an effect"): low-confidence
  // answer entries open on their Question & Answer panel, everything else
  // on the Visual Diff.
  const entryId = entry?.audit_id ?? null;
  if (entryId !== lastEntryId) {
    setLastEntryId(entryId);
    setTab(entry && badAnswerPayload(entry) ? "qa" : "diff");
  }

  if (!entry) return null;

  const diffs = computeDiff(entry.previous_state, entry.new_state);
  const hasState = !!entry.previous_state || !!entry.new_state;
  const tone = actionTone(entry.action);
  const shortcut = targetShortcutLink(entry.target_type, entry.target_id);
  const qa = badAnswerPayload(entry);

  function copyText(text: string, label: string) {
    navigator.clipboard.writeText(text);
    setCopiedKey(label);
    addToast(`Copied ${label} to clipboard`, "success");
    setTimeout(() => setCopiedKey(null), 2000);
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Audit Event Details" size="xl">
      <div className="space-y-6">
        {/* Top Header Card */}
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-zinc-200 bg-zinc-50/50 p-4">
          <div className="flex items-center gap-3">
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ring-1 ring-inset ${tone.bg} ${tone.ring}`}>
              <svg className={`h-5 w-5 ${tone.text}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={tone.icon} />
              </svg>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[15px] font-semibold text-zinc-900">{entry.action}</span>
                <span
                  className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
                    entry.authorization_result === "ALLOW"
                      ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20"
                      : "bg-red-50 text-red-700 ring-red-600/20"
                  }`}
                >
                  {entry.authorization_result}
                </span>
              </div>
              <p className="text-xs text-zinc-500">
                {formatExactTime(entry.created_at)} ({formatRelativeTime(entry.created_at)})
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => copyText(JSON.stringify(entry, null, 2), "Full Event JSON")}
              className="btn-secondary text-xs"
            >
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                />
              </svg>
              {copiedKey === "Full Event JSON" ? "Copied!" : "Copy JSON"}
            </button>
          </div>
        </div>

        {/* Metadata Grid */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* Actor Info */}
          <div className="rounded-lg border border-zinc-200 p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">Actor Identity</p>
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white">
                {(entry.actor_name || entry.actor_email || "S").charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate text-sm font-medium text-zinc-900">
                    {entry.actor_name || "System Actor"}
                  </p>
                  {entry.actor_role && (
                    <span className={`inline-flex rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${roleBadgeTone(entry.actor_role)}`}>
                      {entry.actor_role}
                    </span>
                  )}
                </div>
                {entry.actor_email && <p className="truncate text-xs text-zinc-500">{entry.actor_email}</p>}
                {entry.actor_user_id && (
                  <div className="mt-1 flex items-center gap-1.5">
                    <span className="font-mono text-[11px] text-zinc-400">ID: {entry.actor_user_id.slice(0, 8)}…</span>
                    <button
                      type="button"
                      onClick={() => copyText(entry.actor_user_id!, "Actor ID")}
                      className="text-zinc-400 hover:text-zinc-700"
                      title="Copy actor user ID"
                    >
                      <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Target Info */}
          <div className="rounded-lg border border-zinc-200 p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">Target Entity</p>
            {entry.target_type || entry.target_id ? (
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="inline-flex rounded-md bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-800 ring-1 ring-inset ring-zinc-500/10">
                    {entry.target_type || "Generic Target"}
                  </span>
                  {shortcut && (
                    <Link
                      href={shortcut}
                      className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:underline"
                    >
                      Open Target
                      <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                      </svg>
                    </Link>
                  )}
                </div>
                {entry.target_id && (
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-zinc-600">{entry.target_id}</span>
                    <button
                      type="button"
                      onClick={() => copyText(entry.target_id!, "Target ID")}
                      className="text-zinc-400 hover:text-zinc-700"
                      title="Copy target ID"
                    >
                      <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs text-zinc-400">No entity target specified for this action.</p>
            )}
          </div>
        </div>

        {/* Technical IDs */}
        <div className="grid grid-cols-1 gap-2 rounded-lg bg-zinc-50 p-3 font-mono text-xs text-zinc-600 sm:grid-cols-2">
          <div className="flex items-center justify-between gap-2 overflow-hidden">
            <span className="shrink-0 text-zinc-400">Audit ID:</span>
            <span className="truncate">{entry.audit_id}</span>
            <button
              type="button"
              onClick={() => copyText(entry.audit_id, "Audit ID")}
              className="shrink-0 text-zinc-400 hover:text-zinc-700"
            >
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </button>
          </div>
          {entry.request_id && (
            <div className="flex items-center justify-between gap-2 overflow-hidden">
              <span className="shrink-0 text-zinc-400">Request ID:</span>
              <span className="truncate">{entry.request_id}</span>
              <button
                type="button"
                onClick={() => copyText(entry.request_id!, "Request ID")}
                className="shrink-0 text-zinc-400 hover:text-zinc-700"
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              </button>
            </div>
          )}
        </div>

        {/* State Changes / Payloads */}
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-zinc-900">State Changes &amp; Payload</h3>
            {hasState && (
              <div className="inline-flex rounded-lg border border-zinc-200 bg-zinc-50 p-0.5 text-xs">
                {qa && (
                  <button
                    type="button"
                    onClick={() => setTab("qa")}
                    className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
                      tab === "qa" ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-500 hover:text-zinc-900"
                    }`}
                  >
                    Question &amp; Answer
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setTab("diff")}
                  className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
                    tab === "diff" ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-500 hover:text-zinc-900"
                  }`}
                >
                  Visual Diff
                </button>
                <button
                  type="button"
                  onClick={() => setTab("raw")}
                  className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
                    tab === "raw" ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-500 hover:text-zinc-900"
                  }`}
                >
                  Raw JSON
                </button>
              </div>
            )}
          </div>

          {!hasState ? (
            <div className="rounded-lg border border-dashed border-zinc-200 p-6 text-center text-xs text-zinc-400">
              No previous or new state payloads were recorded for this audit entry.
            </div>
          ) : tab === "qa" && qa ? (
            <div className="space-y-3">
              <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-4">
                <div className="mb-1.5 flex items-center justify-between">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-700">
                    User Question
                  </p>
                  <button
                    type="button"
                    onClick={() => copyText(asText(qa.question), "Question")}
                    className="text-[11px] text-blue-600 hover:underline"
                  >
                    Copy
                  </button>
                </div>
                <p className="whitespace-pre-wrap text-sm text-zinc-900">{asText(qa.question)}</p>
              </div>

              <div className="rounded-lg border border-zinc-200 bg-white p-4">
                <div className="mb-1.5 flex items-center justify-between">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                    {entry.action === "NO_INFO_ANSWER"
                      ? "Assistant Reply (declared \u201cno information\u201d despite passing the confidence gate)"
                      : "Assistant Reply (low-confidence refusal)"}
                  </p>
                  <button
                    type="button"
                    onClick={() => copyText(asText(qa.answer), "Answer")}
                    className="text-[11px] text-blue-600 hover:underline"
                  >
                    Copy
                  </button>
                </div>
                <p className="whitespace-pre-wrap text-sm text-zinc-800">{asText(qa.answer)}</p>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {qa.confidence !== undefined && (
                  <span className="inline-flex items-center rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700 ring-1 ring-inset ring-amber-600/20">
                    Confidence: {String(qa.confidence)}
                  </span>
                )}
                {typeof qa.citation_count === "number" && (
                  <span className="inline-flex items-center rounded-md bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-700 ring-1 ring-inset ring-zinc-500/10">
                    Citations served: {qa.citation_count}
                  </span>
                )}
                {typeof qa.reason === "string" && qa.reason && (
                  <span className="inline-flex items-center rounded-md bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-700 ring-1 ring-inset ring-zinc-500/10">
                    Reason: {qa.reason}
                  </span>
                )}
                {typeof qa.actor_role === "string" && qa.actor_role && (
                  <span className={`inline-flex rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${roleBadgeTone(qa.actor_role)}`}>
                    {qa.actor_role}
                  </span>
                )}
                {typeof qa.actor_role !== "string" && (
                  <span className="inline-flex items-center rounded-md bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-600 ring-1 ring-inset ring-zinc-500/10">
                    Anonymous visitor
                  </span>
                )}
              </div>

              {typeof qa.retrieved_context === "string" && qa.retrieved_context && (
                <details className="rounded-lg border border-zinc-200 bg-zinc-50/50 p-3">
                  <summary className="cursor-pointer select-none text-xs font-semibold text-zinc-600">
                    Retrieved knowledge-base context (preview)
                  </summary>
                  <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-zinc-600">
                    {qa.retrieved_context}
                  </pre>
                </details>
              )}
            </div>
          ) : tab === "diff" ? (
            <div className="overflow-hidden rounded-lg border border-zinc-200">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-zinc-200 bg-zinc-50 text-[11px] font-semibold text-zinc-500">
                  <tr>
                    <th className="px-3 py-2">Field</th>
                    <th className="px-3 py-2">Previous Value</th>
                    <th className="px-3 py-2">New Value</th>
                    <th className="px-3 py-2 text-right">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 font-mono">
                  {diffs.map((d) => (
                    <tr
                      key={d.key}
                      className={
                        d.status === "added"
                          ? "bg-emerald-50/40"
                          : d.status === "removed"
                          ? "bg-red-50/40"
                          : d.status === "modified"
                          ? "bg-blue-50/40"
                          : ""
                      }
                    >
                      <td className="px-3 py-2.5 font-semibold text-zinc-900">{d.key}</td>
                      <td className="max-w-[180px] truncate px-3 py-2.5 text-zinc-500">
                        {d.oldVal !== undefined ? (
                          <span className={d.status === "modified" || d.status === "removed" ? "line-through text-red-600/80" : ""}>
                            {formatJsonValue(d.oldVal)}
                          </span>
                        ) : (
                          <span className="text-zinc-300">—</span>
                        )}
                      </td>
                      <td className="max-w-[180px] truncate px-3 py-2.5 text-zinc-800">
                        {d.newVal !== undefined ? (
                          <span className={d.status === "added" || d.status === "modified" ? "font-medium text-emerald-700" : ""}>
                            {formatJsonValue(d.newVal)}
                          </span>
                        ) : (
                          <span className="text-zinc-300">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right font-sans">
                        <span
                          className={`inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                            d.status === "added"
                              ? "bg-emerald-100 text-emerald-800"
                              : d.status === "removed"
                              ? "bg-red-100 text-red-800"
                              : d.status === "modified"
                              ? "bg-blue-100 text-blue-800"
                              : "bg-zinc-100 text-zinc-600"
                          }`}
                        >
                          {d.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div className="overflow-hidden rounded-lg border border-zinc-200">
                <div className="flex items-center justify-between border-b border-zinc-200 bg-zinc-50 px-3 py-1.5">
                  <span className="text-[11px] font-semibold text-zinc-500">previous_state</span>
                  {entry.previous_state && (
                    <button
                      type="button"
                      onClick={() => copyText(JSON.stringify(entry.previous_state, null, 2), "Previous State")}
                      className="text-[11px] text-blue-600 hover:underline"
                    >
                      Copy
                    </button>
                  )}
                </div>
                <pre className="max-h-60 overflow-y-auto bg-zinc-950 p-3 font-mono text-xs text-zinc-100">
                  {entry.previous_state ? JSON.stringify(entry.previous_state, null, 2) : "null"}
                </pre>
              </div>

              <div className="overflow-hidden rounded-lg border border-zinc-200">
                <div className="flex items-center justify-between border-b border-zinc-200 bg-zinc-50 px-3 py-1.5">
                  <span className="text-[11px] font-semibold text-zinc-500">new_state</span>
                  {entry.new_state && (
                    <button
                      type="button"
                      onClick={() => copyText(JSON.stringify(entry.new_state, null, 2), "New State")}
                      className="text-[11px] text-blue-600 hover:underline"
                    >
                      Copy
                    </button>
                  )}
                </div>
                <pre className="max-h-60 overflow-y-auto bg-zinc-950 p-3 font-mono text-xs text-zinc-100">
                  {entry.new_state ? JSON.stringify(entry.new_state, null, 2) : "null"}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

export default function AuditLogViewerPage() {
  const [data, setData] = useState<AuditLogsResponse | null>(null);
  const [filters, setFilters] = useState<AuditFilterOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);

  // Filter States
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [search, setSearch] = useState("");
  const [actionFilter, setActionFilter] = useState("ALL");
  const [targetTypeFilter, setTargetTypeFilter] = useState("ALL");
  const [authResultFilter, setAuthResultFilter] = useState("ALL");
  const [datePreset, setDatePreset] = useState<DateFilterPreset>("ALL");
  const [customStartDate, setCustomStartDate] = useState("");
  const [customEndDate, setCustomEndDate] = useState("");

  // Sort State (client-side sort for current page rows)
  const [sort, setSort] = useState<SortState>({ key: "created_at", dir: "desc" });

  // Inspection Modal
  const [selectedEntry, setSelectedEntry] = useState<AuditLogEntry | null>(null);

  const { addToast } = useToast();

  // Compute ISO dates based on preset
  const { computedStartDate, computedEndDate } = useMemo(() => {
    if (datePreset === "CUSTOM") {
      return {
        computedStartDate: customStartDate ? new Date(customStartDate).toISOString() : undefined,
        computedEndDate: customEndDate ? new Date(customEndDate).toISOString() : undefined,
      };
    }
    if (datePreset === "TODAY") {
      const start = new Date();
      start.setHours(0, 0, 0, 0);
      return { computedStartDate: start.toISOString(), computedEndDate: undefined };
    }
    if (datePreset === "7D") {
      const start = new Date();
      start.setDate(start.getDate() - 7);
      return { computedStartDate: start.toISOString(), computedEndDate: undefined };
    }
    if (datePreset === "30D") {
      const start = new Date();
      start.setDate(start.getDate() - 30);
      return { computedStartDate: start.toISOString(), computedEndDate: undefined };
    }
    return { computedStartDate: undefined, computedEndDate: undefined };
  }, [datePreset, customStartDate, customEndDate]);

  const loadData = useCallback(
    async (isBackground = false) => {
      if (!isBackground) setLoading(true);
      else setRefreshing(true);

      try {
        const [logsRes, filtersRes] = await Promise.all([
          api.listAuditLogs({
            page,
            page_size: pageSize,
            search: search.trim() || undefined,
            action: actionFilter !== "ALL" ? actionFilter : undefined,
            target_type: targetTypeFilter !== "ALL" ? targetTypeFilter : undefined,
            authorization_result: authResultFilter !== "ALL" ? authResultFilter : undefined,
            start_date: computedStartDate,
            end_date: computedEndDate,
          }),
          api.getAuditFilterOptions(),
        ]);
        setData(logsRes);
        setFilters(filtersRes);
      } catch (err) {
        if (!isBackground) {
          addToast(err instanceof ApiError ? err.detail : "Failed to load audit logs", "error");
        }
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [page, pageSize, search, actionFilter, targetTypeFilter, authResultFilter, computedStartDate, computedEndDate, addToast]
  );

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Auto-refresh interval
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      loadData(true);
    }, 10000);
    return () => clearInterval(interval);
  }, [autoRefresh, loadData]);

  // Client-sorted rows
  const sortedRows = useMemo(() => {
    if (!data?.items) return [];
    const dir = sort.dir === "asc" ? 1 : -1;
    const list = [...data.items];

    switch (sort.key) {
      case "created_at":
        list.sort((a, b) => (new Date(a.created_at).getTime() - new Date(b.created_at).getTime()) * dir);
        break;
      case "action":
        list.sort((a, b) => a.action.localeCompare(b.action) * dir);
        break;
      case "actor":
        list.sort((a, b) => (a.actor_name || "").localeCompare(b.actor_name || "") * dir);
        break;
      case "target":
        list.sort((a, b) => (a.target_type || "").localeCompare(b.target_type || "") * dir);
        break;
      case "result":
        list.sort((a, b) => a.authorization_result.localeCompare(b.authorization_result) * dir);
        break;
    }
    return list;
  }, [data?.items, sort]);

  function handleSort(key: string) {
    setSort((current) => toggleSort(current, key));
  }

  function resetFilters() {
    setSearch("");
    setActionFilter("ALL");
    setTargetTypeFilter("ALL");
    setAuthResultFilter("ALL");
    setDatePreset("ALL");
    setCustomStartDate("");
    setCustomEndDate("");
    setPage(1);
  }

  const hasActiveFilters =
    search.trim() !== "" ||
    actionFilter !== "ALL" ||
    targetTypeFilter !== "ALL" ||
    authResultFilter !== "ALL" ||
    datePreset !== "ALL";

  function exportAsJson() {
    if (!data?.items.length) {
      addToast("No records to export", "error");
      return;
    }
    const jsonStr = JSON.stringify(data.items, null, 2);
    const blob = new Blob([jsonStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit_logs_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    addToast("Exported audit logs as JSON", "success");
  }

  function exportAsCsv() {
    if (!data?.items.length) {
      addToast("No records to export", "error");
      return;
    }
    const headers = [
      "Audit ID",
      "Timestamp",
      "Action",
      "Authorization",
      "Actor Name",
      "Actor Email",
      "Actor Role",
      "Target Type",
      "Target ID",
      "Request ID",
    ];

    const rows = data.items.map((i) => [
      `"${i.audit_id}"`,
      `"${i.created_at}"`,
      `"${i.action}"`,
      `"${i.authorization_result}"`,
      `"${i.actor_name || ""}"`,
      `"${i.actor_email || ""}"`,
      `"${i.actor_role || ""}"`,
      `"${i.target_type || ""}"`,
      `"${i.target_id || ""}"`,
      `"${i.request_id || ""}"`,
    ]);

    const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit_logs_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    addToast("Exported audit logs as CSV", "success");
  }

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <PageHeader
        title="Audit Log Viewer"
        description="Immutable system trail of all mutating business actions, authentication events, and administrative actions."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setAutoRefresh((v) => !v)}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                autoRefresh
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : "border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50"
              }`}
              title="Toggle automatic live polling every 10s"
            >
              <span className={`h-2 w-2 rounded-full ${autoRefresh ? "animate-pulse bg-emerald-500" : "bg-zinc-300"}`} />
              {autoRefresh ? "Live (10s)" : "Auto-refresh"}
            </button>

            <button
              type="button"
              onClick={() => loadData(true)}
              disabled={refreshing}
              className="btn-secondary text-xs"
              title="Refresh logs now"
            >
              <svg
                className={`h-3.5 w-3.5 ${refreshing ? "animate-spin text-blue-600" : ""}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              Refresh
            </button>

            <div className="flex items-center rounded-lg border border-zinc-200 bg-white shadow-sm">
              <button
                type="button"
                onClick={exportAsCsv}
                className="px-2.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
                title="Download CSV"
              >
                CSV
              </button>
              <div className="h-4 w-px bg-zinc-200" />
              <button
                type="button"
                onClick={exportAsJson}
                className="px-2.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
                title="Download JSON"
              >
                JSON
              </button>
            </div>
          </div>
        }
      />

      {/* Metrics Row */}
      {filters && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard
            label="Total Events"
            value={filters.total_count}
            sub="Append-only recorded history"
            iconClass="bg-blue-50 text-blue-600"
            icon={
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            }
          />
          <MetricCard
            label="Recorded Today"
            value={filters.today_count}
            sub="Events in current 24-hour cycle"
            iconClass="bg-emerald-50 text-emerald-600"
            icon={
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            }
          />
          <MetricCard
            label="Active Actors"
            value={filters.unique_actors_count}
            sub="Unique users triggering actions"
            iconClass="bg-purple-50 text-purple-600"
            icon={
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            }
          />
          <MetricCard
            label="Action Types"
            value={filters.actions.length}
            sub={`${filters.target_types.length} target categories tracked`}
            iconClass="bg-amber-50 text-amber-600"
            icon={
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
            }
          />
        </div>
      )}

      {/* Filter & Search Toolbar */}
      <div className="card space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-3">
          {/* Search bar */}
          <div className="relative min-w-[240px] flex-1">
            <svg
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              placeholder="Search by action, actor, target ID, payload data…"
              className="input pl-9 text-xs"
            />
            {search && (
              <button
                type="button"
                onClick={() => {
                  setSearch("");
                  setPage(1);
                }}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600"
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>

          {/* Action Filter */}
          <div className="w-48">
            <select
              value={actionFilter}
              onChange={(e) => {
                setActionFilter(e.target.value);
                setPage(1);
              }}
              className="input text-xs"
            >
              <option value="ALL">All Actions</option>
              {filters?.actions.map((act) => (
                <option key={act} value={act}>
                  {act}
                </option>
              ))}
            </select>
          </div>

          {/* Target Type Filter */}
          <div className="w-40">
            <select
              value={targetTypeFilter}
              onChange={(e) => {
                setTargetTypeFilter(e.target.value);
                setPage(1);
              }}
              className="input text-xs"
            >
              <option value="ALL">All Targets</option>
              {filters?.target_types.map((tgt) => (
                <option key={tgt} value={tgt}>
                  {tgt}
                </option>
              ))}
            </select>
          </div>

          {/* Authorization Result Filter */}
          <div className="w-36">
            <select
              value={authResultFilter}
              onChange={(e) => {
                setAuthResultFilter(e.target.value);
                setPage(1);
              }}
              className="input text-xs"
            >
              <option value="ALL">All Results</option>
              <option value="ALLOW">ALLOW</option>
              <option value="DENY">DENY</option>
            </select>
          </div>
        </div>

        {/* Date presets & Custom Range */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 pt-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs font-medium text-zinc-500">Date:</span>
            {(["ALL", "TODAY", "7D", "30D", "CUSTOM"] as const).map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => {
                  setDatePreset(preset);
                  setPage(1);
                }}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  datePreset === preset
                    ? "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/20"
                    : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200"
                }`}
              >
                {preset === "ALL"
                  ? "All Time"
                  : preset === "TODAY"
                  ? "Today"
                  : preset === "7D"
                  ? "Last 7 Days"
                  : preset === "30D"
                  ? "Last 30 Days"
                  : "Custom Range"}
              </button>
            ))}

            {datePreset === "CUSTOM" && (
              <div className="ml-2 flex items-center gap-2">
                <input
                  type="date"
                  value={customStartDate}
                  onChange={(e) => setCustomStartDate(e.target.value)}
                  className="input py-1 text-xs"
                />
                <span className="text-xs text-zinc-400">to</span>
                <input
                  type="date"
                  value={customEndDate}
                  onChange={(e) => setCustomEndDate(e.target.value)}
                  className="input py-1 text-xs"
                />
              </div>
            )}
          </div>

          {hasActiveFilters && (
            <button
              type="button"
              onClick={resetFilters}
              className="text-xs font-medium text-zinc-500 hover:text-red-600"
            >
              Reset all filters
            </button>
          )}
        </div>
      </div>

      {/* Main Table */}
      <div className="card overflow-hidden">
        {loading ? (
          <ListSkeleton rows={8} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title="No audit log records found"
            description={
              hasActiveFilters
                ? "No audit records match the selected filter criteria. Try adjusting your search query or filters."
                : "No audit events recorded yet. Actions across the portal will be recorded here automatically."
            }
            action={
              hasActiveFilters ? (
                <button type="button" onClick={resetFilters} className="btn-secondary text-xs">
                  Clear Filters
                </button>
              ) : undefined
            }
          />
        ) : (
          <>
            <div className="table-scroll max-h-[640px]">
              <table className="w-full">
                <thead className="bg-zinc-50">
                  <tr className="group">
                    <SortableTh sortKey="created_at" sort={sort} onSort={handleSort}>
                      Timestamp
                    </SortableTh>
                    <SortableTh sortKey="actor" sort={sort} onSort={handleSort}>
                      Actor
                    </SortableTh>
                    <SortableTh sortKey="action" sort={sort} onSort={handleSort}>
                      Action
                    </SortableTh>
                    <SortableTh sortKey="target" sort={sort} onSort={handleSort} className="hidden md:table-cell">
                      Target Entity
                    </SortableTh>
                    <SortableTh sortKey="result" sort={sort} onSort={handleSort} className="hidden sm:table-cell">
                      Auth Result
                    </SortableTh>
                    <Th className="hidden lg:table-cell">Payload Diff Preview</Th>
                    <Th align="right">Details</Th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {sortedRows.map((entry) => {
                    const tone = actionTone(entry.action);
                    const diffs = computeDiff(entry.previous_state, entry.new_state);
                    const changedFields = diffs.filter((d) => d.status !== "unchanged");
                    const qa = badAnswerPayload(entry);

                    return (
                      <tr key={entry.audit_id} className="table-row">
                        {/* Timestamp */}
                        <td className="table-td whitespace-nowrap">
                          <div>
                            <p className="font-medium text-zinc-900">{formatRelativeTime(entry.created_at)}</p>
                            <p className="text-[11px] text-zinc-400">{formatExactTime(entry.created_at)}</p>
                          </div>
                        </td>

                        {/* Actor */}
                        <td className="table-td">
                          <div className="flex items-center gap-2.5">
                            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-xs font-semibold text-zinc-600">
                              {(entry.actor_name || entry.actor_email || "S").charAt(0).toUpperCase()}
                            </div>
                            <div className="min-w-0">
                              <p className="truncate font-medium text-zinc-900">
                                {entry.actor_name || "System Actor"}
                              </p>
                              <div className="flex items-center gap-1.5">
                                {entry.actor_role && (
                                  <span className={`inline-flex rounded px-1 text-[10px] font-medium ring-1 ring-inset ${roleBadgeTone(entry.actor_role)}`}>
                                    {entry.actor_role}
                                  </span>
                                )}
                                {entry.actor_email && (
                                  <span className="truncate text-[11px] text-zinc-400">{entry.actor_email}</span>
                                )}
                              </div>
                            </div>
                          </div>
                        </td>

                        {/* Action */}
                        <td className="table-td">
                          <span
                            className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${tone.bg} ${tone.text} ${tone.ring}`}
                          >
                            <svg className="h-3 w-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={tone.icon} />
                            </svg>
                            {entry.action}
                          </span>
                        </td>

                        {/* Target Entity */}
                        <td className="table-td hidden md:table-cell">
                          {entry.target_type ? (
                            <div className="min-w-0">
                              <span className="inline-flex rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] font-medium text-zinc-700">
                                {entry.target_type}
                              </span>
                              {entry.target_id && (
                                <p className="truncate font-mono text-[11px] text-zinc-400">
                                  {entry.target_id.slice(0, 13)}…
                                </p>
                              )}
                            </div>
                          ) : (
                            <span className="text-xs text-zinc-400">—</span>
                          )}
                        </td>

                        {/* Authorization Result */}
                        <td className="table-td hidden sm:table-cell">
                          <span
                            className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${
                              entry.authorization_result === "ALLOW"
                                ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20"
                                : "bg-red-50 text-red-700 ring-red-600/20"
                            }`}
                          >
                            {entry.authorization_result === "ALLOW" ? (
                              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                              </svg>
                            ) : (
                              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            )}
                            {entry.authorization_result}
                          </span>
                        </td>

                        {/* Payload Preview */}
                        <td className="table-td hidden lg:table-cell">
                          {qa ? (
                            <span className="block max-w-[280px] truncate text-[11px] italic text-zinc-500" title={asText(qa.question)}>
                              &ldquo;{asText(qa.question)}&rdquo;
                            </span>
                          ) : changedFields.length > 0 ? (
                            <div className="flex flex-wrap items-center gap-1">
                              {changedFields.slice(0, 2).map((f) => (
                                <span
                                  key={f.key}
                                  className="inline-flex rounded bg-zinc-50 px-1.5 py-0.5 text-[10px] font-mono text-zinc-600 ring-1 ring-inset ring-zinc-200"
                                >
                                  {f.key}
                                </span>
                              ))}
                              {changedFields.length > 2 && (
                                <span className="text-[10px] text-zinc-400">+{changedFields.length - 2} more</span>
                              )}
                            </div>
                          ) : entry.new_state ? (
                            <span className="text-[11px] text-zinc-400">Recorded snapshot</span>
                          ) : (
                            <span className="text-[11px] text-zinc-400">No payload</span>
                          )}
                        </td>

                        {/* Actions */}
                        <td className="table-td text-right">
                          <button
                            type="button"
                            onClick={() => setSelectedEntry(entry)}
                            className="inline-flex items-center gap-1 rounded-md border border-zinc-200 bg-white px-2.5 py-1 text-xs font-medium text-zinc-700 shadow-sm transition-colors hover:bg-zinc-50 hover:text-zinc-900"
                          >
                            <svg className="h-3.5 w-3.5 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                            </svg>
                            Inspect
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 p-4">
              <div className="flex items-center gap-2">
                <span className="text-xs text-zinc-500">Rows per page:</span>
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value));
                    setPage(1);
                  }}
                  className="rounded border border-zinc-200 bg-white px-2 py-1 text-xs text-zinc-700"
                >
                  {PAGE_SIZE_OPTIONS.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <span className="text-xs text-zinc-400">
                  Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, data.total)} of {data.total}
                </span>
              </div>

              <Pagination page={page} total={data.total} pageSize={pageSize} onPage={setPage} />
            </div>
          </>
        )}
      </div>

      {/* Deep Inspection Modal */}
      <AuditInspectionModal
        entry={selectedEntry}
        isOpen={!!selectedEntry}
        onClose={() => setSelectedEntry(null)}
      />
    </div>
  );
}
