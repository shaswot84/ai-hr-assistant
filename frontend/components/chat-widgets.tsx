"use client";

import React from "react";

// Inline SVG Icons
function CalendarIcon({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
      />
    </svg>
  );
}

function ClockIcon({ className = "w-3 h-3" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
      />
    </svg>
  );
}

function CheckCircleIcon({ className = "w-4 h-4" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
      />
    </svg>
  );
}

function CheckIcon({ className = "w-3 h-3" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
    </svg>
  );
}

function XIcon({ className = "w-3 h-3" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  );
}

function ArrowRightIcon({ className = "w-3 h-3" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
    </svg>
  );
}

function ShieldCheckIcon({ className = "w-4 h-4" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
      />
    </svg>
  );
}

function FileTextIcon({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
      />
    </svg>
  );
}

function SparklesIcon({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"
      />
    </svg>
  );
}

export interface ChatWidgetProps {
  widget: {
    type: string;
    [key: string]: any;
  };
  onAction?: (actionText: string) => void;
  disabled?: boolean;
}

export function ChatWidgetRenderer({ widget, onAction, disabled = false }: ChatWidgetProps) {
  if (!widget || !widget.type) return null;

  switch (widget.type) {
    case "leave_balance":
      return <LeaveBalanceWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "leave_requests_list":
      return <LeaveRequestsListWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "leave_types_list":
      return <LeaveTypesWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "staged_action":
      return <StagedActionWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "action_result":
      return <ActionResultWidget widget={widget} />;
    case "single_leave_request":
      return <SingleLeaveRequestWidget widget={widget} onAction={onAction} disabled={disabled} />;
    default:
      return null;
  }
}

/**
 * 1. Leave Balance Grid / Cards
 */
function LeaveBalanceWidget({ widget, onAction, disabled }: ChatWidgetProps) {
  const balances: any[] = widget.balances || [];
  const year = widget.year;
  const employeeCode = widget.employee_code;

  if (balances.length === 0) return null;

  return (
    <div className="mt-3.5 space-y-2.5 w-full max-w-xl">
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-700">
          <CalendarIcon className="w-3.5 h-3.5 text-blue-600" />
          <span>
            {employeeCode ? `Leave Balance for ${employeeCode}` : "Your Leave Balance"}
            {year ? ` (${year})` : ""}
          </span>
        </div>
        <span className="text-[11px] text-zinc-400">
          {balances.length} categor{balances.length > 1 ? "ies" : "y"}
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        {balances.map((b) => {
          const allocated = parseFloat(b.allocated_days) || 0;
          const remaining = parseFloat(b.remaining_days) || 0;
          const pct = allocated > 0 ? Math.min(100, Math.max(0, (remaining / allocated) * 100)) : 0;
          const isUsable = remaining > 0;

          return (
            <div
              key={b.leave_type_name}
              className="group relative flex flex-col justify-between p-3.5 rounded-xl bg-white border border-zinc-200/90 shadow-sm transition-all duration-200 hover:shadow-md hover:border-blue-300"
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <h4 className="font-semibold text-sm text-zinc-900 tracking-tight">
                    {b.leave_type_name}
                  </h4>
                  <span
                    className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold tracking-wide uppercase ${
                      isUsable
                        ? "bg-emerald-50 text-emerald-700 border border-emerald-200/60"
                        : "bg-zinc-100 text-zinc-500"
                    }`}
                  >
                    {isUsable ? "Available" : "Exhausted"}
                  </span>
                </div>

                <div className="mt-2.5 flex items-baseline gap-1.5">
                  <span className="text-2xl font-bold tracking-tight text-zinc-900">
                    {remaining}
                  </span>
                  <span className="text-xs text-zinc-500">
                    / {allocated} days left
                  </span>
                </div>

                {/* Progress bar */}
                <div className="mt-2.5 w-full h-1.5 bg-zinc-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      pct > 50
                        ? "bg-blue-600"
                        : pct > 20
                        ? "bg-amber-500"
                        : "bg-rose-500"
                    }`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>

              {!employeeCode && isUsable && onAction && (
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onAction(`I would like to apply for ${b.leave_type_name}`)}
                  className="mt-3 inline-flex items-center justify-center gap-1.5 w-full py-1.5 px-2.5 text-xs font-medium text-blue-600 bg-blue-50/70 hover:bg-blue-100 border border-blue-200/60 rounded-lg transition-colors duration-150 disabled:opacity-50 cursor-pointer"
                >
                  <span>Apply for {b.leave_type_name}</span>
                  <ArrowRightIcon className="w-3 h-3 transition-transform group-hover:translate-x-0.5" />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * 2. Leave Requests History / Queue
 */
function LeaveRequestsListWidget({ widget, onAction, disabled }: ChatWidgetProps) {
  const requests: any[] = widget.requests || [];
  const isManager = Boolean(widget.is_manager);

  if (requests.length === 0) return null;

  return (
    <div className="mt-3.5 space-y-2.5 w-full max-w-xl">
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-700">
          <FileTextIcon className="w-3.5 h-3.5 text-blue-600" />
          <span>{isManager ? "Leave Requests Queue (All Employees)" : "Your Leave Requests"}</span>
        </div>
        <span className="text-[11px] text-zinc-400">
          {requests.length} request{requests.length > 1 ? "s" : ""}
        </span>
      </div>

      <div className="space-y-2">
        {requests.map((r) => {
          const isPending = r.status === "PENDING";
          const isApproved = r.status === "APPROVED";
          const isRejected = r.status === "REJECTED";

          return (
            <div
              key={r.request_number || r.leave_request_id}
              className="p-3.5 rounded-xl bg-white border border-zinc-200/90 shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-3"
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-xs font-bold text-zinc-900 bg-zinc-100 px-1.5 py-0.5 rounded">
                    {r.request_number}
                  </span>
                  <span className="font-semibold text-xs text-zinc-800">
                    {r.leave_type_name}
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                      isApproved
                        ? "bg-emerald-50 text-emerald-700 border border-emerald-200/60"
                        : isPending
                        ? "bg-amber-50 text-amber-700 border border-amber-200/60"
                        : isRejected
                        ? "bg-rose-50 text-rose-700 border border-rose-200/60"
                        : "bg-zinc-100 text-zinc-600"
                    }`}
                  >
                    {isApproved && <CheckIcon className="w-2.5 h-2.5" />}
                    {isPending && <ClockIcon className="w-2.5 h-2.5" />}
                    {isRejected && <XIcon className="w-2.5 h-2.5" />}
                    <span>{r.status}</span>
                  </span>
                </div>

                <div className="flex items-center gap-2 text-xs text-zinc-500">
                  <span>
                    {r.start_date} to {r.end_date}
                  </span>
                  <span>•</span>
                  <span className="font-medium text-zinc-700">
                    {r.total_days} {parseFloat(r.total_days) === 1 ? "day" : "days"}
                  </span>
                  {r.reason && (
                    <>
                      <span>•</span>
                      <span className="italic truncate max-w-[180px]">"{r.reason}"</span>
                    </>
                  )}
                </div>
              </div>

              {/* Action Buttons */}
              {isPending && onAction && (
                <div className="flex items-center gap-1.5 shrink-0">
                  {isManager ? (
                    <>
                      <button
                        type="button"
                        disabled={disabled}
                        onClick={() => onAction(`Approve request ${r.request_number}`)}
                        className="px-2.5 py-1 text-xs font-medium bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg transition-colors shadow-sm disabled:opacity-50 cursor-pointer"
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        disabled={disabled}
                        onClick={() => onAction(`Reject request ${r.request_number}`)}
                        className="px-2.5 py-1 text-xs font-medium bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 rounded-lg transition-colors disabled:opacity-50 cursor-pointer"
                      >
                        Reject
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => onAction(`Cancel request ${r.request_number}`)}
                      className="px-2.5 py-1 text-xs font-medium text-rose-600 bg-rose-50 hover:bg-rose-100 border border-rose-200/70 rounded-lg transition-colors disabled:opacity-50 cursor-pointer"
                    >
                      Cancel Request
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * 3. Available Leave Types
 */
function LeaveTypesWidget({ widget, onAction, disabled }: ChatWidgetProps) {
  const types: any[] = widget.types || [];
  if (types.length === 0) return null;

  return (
    <div className="mt-3.5 space-y-2.5 w-full max-w-xl">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-700 px-1">
        <SparklesIcon className="w-3.5 h-3.5 text-blue-600" />
        <span>Available Leave Types</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {types.map((t) => (
          <div
            key={t.leave_name}
            onClick={() => {
              if (onAction && !disabled) onAction(`I want to apply for ${t.leave_name}`);
            }}
            className="p-3 rounded-xl bg-white border border-zinc-200 hover:border-blue-400 hover:shadow-sm transition-all duration-150 cursor-pointer group flex flex-col justify-between"
          >
            <div>
              <div className="flex items-center justify-between">
                <span className="font-semibold text-sm text-zinc-900 group-hover:text-blue-600 transition-colors">
                  {t.leave_name}
                </span>
                <span
                  className={`text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase ${
                    t.is_paid
                      ? "bg-emerald-50 text-emerald-700"
                      : "bg-zinc-100 text-zinc-600"
                  }`}
                >
                  {t.is_paid ? "Paid" : "Unpaid"}
                </span>
              </div>
              {t.description && (
                <p className="mt-1 text-xs text-zinc-500 line-clamp-2">
                  {t.description}
                </p>
              )}
            </div>

            <div className="mt-2.5 flex items-center justify-between pt-2 border-t border-zinc-100 text-[11px] text-zinc-500">
              <span>Max {t.max_consecutive_days} consecutive days</span>
              <span className="font-medium text-blue-600 group-hover:underline inline-flex items-center gap-0.5">
                Apply <ArrowRightIcon className="w-2.5 h-2.5" />
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * 4. Staged Action Confirmation Widget
 */
function StagedActionWidget({ widget, onAction, disabled }: ChatWidgetProps) {
  const title = widget.title || "Confirm Action";
  const summary = widget.summary || "";
  const confirmText = widget.confirm_text || "Confirm";
  const cancelText = widget.cancel_text || "Cancel";
  const args = widget.args || {};
  const actionType = widget.action_type;

  return (
    <div className="mt-3.5 p-4 rounded-xl bg-blue-50/70 border border-blue-200/90 shadow-sm w-full max-w-xl">
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-blue-600 text-white flex items-center justify-center shadow-sm">
          <ShieldCheckIcon className="w-4 h-4" />
        </div>
        <div>
          <h4 className="text-xs font-bold uppercase tracking-wider text-blue-900">
            {title}
          </h4>
          <p className="text-xs text-blue-700/80">
            Please review the details below before confirming.
          </p>
        </div>
      </div>

      <div className="mt-3 p-3 bg-white border border-blue-100 rounded-lg text-xs space-y-1.5">
        {actionType === "submit_leave" && (
          <>
            <div className="flex justify-between">
              <span className="text-zinc-500">Leave Type:</span>
              <span className="font-semibold text-zinc-900">
                {args.leave_type_name}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Dates:</span>
              <span className="font-semibold text-zinc-900">
                {args.start_date} to {args.end_date}
              </span>
            </div>
            {args.reason && (
              <div className="flex justify-between">
                <span className="text-zinc-500">Reason:</span>
                <span className="font-medium italic text-zinc-800">
                  {args.reason}
                </span>
              </div>
            )}
          </>
        )}

        {actionType === "cancel_leave" && (
          <div className="flex justify-between">
            <span className="text-zinc-500">Request Number:</span>
            <span className="font-mono font-bold text-zinc-900">
              {args.request_number}
            </span>
          </div>
        )}

        {actionType === "decide_leave" && (
          <>
            <div className="flex justify-between">
              <span className="text-zinc-500">Request:</span>
              <span className="font-mono font-bold text-zinc-900">
                {args.request_number}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Decision:</span>
              <span
                className={`font-semibold ${
                  args.approve
                    ? "text-emerald-600"
                    : "text-rose-600"
                }`}
              >
                {args.approve ? "Approve" : "Reject"}
              </span>
            </div>
          </>
        )}

        {summary && !actionType && (
          <p className="font-medium text-zinc-800">{summary}</p>
        )}
      </div>

      {onAction && (
        <div className="mt-3.5 flex items-center gap-2">
          <button
            type="button"
            disabled={disabled}
            onClick={() => onAction("yes")}
            className="flex-1 inline-flex items-center justify-center gap-1.5 py-2 px-3 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors disabled:opacity-50 cursor-pointer"
          >
            <CheckIcon className="w-3.5 h-3.5" />
            <span>{confirmText}</span>
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onAction("cancel")}
            className="py-2 px-3 bg-white hover:bg-zinc-100 text-zinc-700 border border-zinc-200 rounded-lg text-xs font-medium transition-colors disabled:opacity-50 cursor-pointer"
          >
            <span>{cancelText}</span>
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * 5. Action Execution Result Widget
 */
function ActionResultWidget({ widget }: { widget: any }) {
  const result = widget.result || {};

  return (
    <div className="mt-3 p-3.5 rounded-xl bg-emerald-50/80 border border-emerald-200/90 w-full max-w-xl flex items-start gap-2.5">
      <div className="w-6 h-6 rounded-full bg-emerald-600 text-white flex items-center justify-center shrink-0 mt-0.5">
        <CheckCircleIcon className="w-4 h-4" />
      </div>
      <div className="space-y-1 text-xs">
        <div className="font-bold text-emerald-900">
          Action Completed Successfully
        </div>
        {result.request_number && (
          <div className="text-emerald-800">
            Request <span className="font-mono font-bold">{result.request_number}</span> status is now{" "}
            <span className="font-semibold">{result.status}</span>.
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * 6. Single Leave Request Detail Widget
 */
function SingleLeaveRequestWidget({ widget }: ChatWidgetProps) {
  const req = widget.request;
  if (!req) return null;

  return (
    <div className="mt-3 p-3.5 rounded-xl bg-white border border-zinc-200 w-full max-w-xl space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs font-bold text-zinc-900">
          {req.request_number}
        </span>
        <span className="px-2 py-0.5 text-[10px] font-semibold rounded-full bg-blue-50 text-blue-700 border border-blue-200">
          {req.status}
        </span>
      </div>
      <div className="text-xs text-zinc-500 space-y-1">
        <div>
          Type: <strong>{req.leave_type_name}</strong>
        </div>
        <div>
          Duration: {req.start_date} to {req.end_date} ({req.total_days} days)
        </div>
        {req.reason && <div>Reason: "{req.reason}"</div>}
      </div>
    </div>
  );
}
