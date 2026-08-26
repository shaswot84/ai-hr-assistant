"use client";

import React, { useState, useMemo } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { getAuthToken, setAuthToken } from "@/lib/auth";
import { GenUIIframeWidget } from "@/components/genui-iframe-widget";

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

function ChevronLeftIcon({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
    </svg>
  );
}

function ChevronRightIcon({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
    </svg>
  );
}

function ChevronDownIcon({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
    </svg>
  );
}

function UserIcon({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
      />
    </svg>
  );
}

function UsersIcon({ className = "w-4 h-4" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"
      />
    </svg>
  );
}

function HierarchyIcon({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M7 11.5V14m0-2.5v-6a1.5 1.5 0 113 0m-3 6a1.5 1.5 0 00-3 0v2a7.5 7.5 0 0015 0v-5a1.5 1.5 0 00-3 0m-6-3V11m0-5.5v-1a1.5 1.5 0 013 0v1m0 0V11m0-5.5a1.5 1.5 0 013 0v3m0 0V11"
      />
    </svg>
  );
}

function BuildingOfficeIcon({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"
      />
    </svg>
  );
}

function SearchIcon({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
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
    case "all_employee_balances":
      return <AllEmployeeBalancesWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "leave_requests_list":
      return <LeaveRequestsListWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "leave_types_list":
      return <LeaveTypesWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "leave_date_picker":
      return <LeaveDatePickerWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "staged_action":
      return <StagedActionWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "action_result":
      return <ActionResultWidget widget={widget} />;
    case "single_leave_request":
      return <SingleLeaveRequestWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "vacancies_list":
      return <VacanciesListWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "vacancy_detail":
      return <VacancyDetailWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "apply_vacancy":
      return <ApplyVacancyWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "applications_list":
      return <ApplicationsListWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "company_holidays":
      return <CompanyHolidaysWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "team_out_of_office":
      return <TeamOutOfOfficeWidget widget={widget} onAction={onAction} disabled={disabled} />;
    case "genui_iframe":
    case "knowledge_genui":
    case "ag_ui_widget":
      return <GenUIIframeWidget widget={widget as any} onAction={onAction} disabled={disabled} />;
    default:
      return null;
  }
}

/**
 * 1. Interactive Calendar Date Picker Widget
 */
function LeaveDatePickerWidget({ widget, onAction, disabled }: ChatWidgetProps) {
  const leaveTypeName = widget.leave_type_name;
  const initialMinDate = widget.min_date || new Date().toISOString().split("T")[0];

  const [currentMonthDate, setCurrentMonthDate] = useState(() => {
    if (widget.start_date) {
      const [y, m] = widget.start_date.split("-").map(Number);
      return new Date(y, m - 1, 1);
    }
    const [y, m] = initialMinDate.split("-").map(Number);
    return new Date(y, m - 1, 1);
  });

  const [selectedStart, setSelectedStart] = useState<string | null>(widget.start_date || null);
  const [selectedEnd, setSelectedEnd] = useState<string | null>(widget.end_date || null);
  const [isHalfDay, setIsHalfDay] = useState<boolean>(Boolean(widget.is_half_day));
  const [halfDayPeriod, setHalfDayPeriod] = useState<"MORNING" | "AFTERNOON">(
    widget.half_day_period || "MORNING"
  );
  const [reason, setReason] = useState<string>("");

  const year = currentMonthDate.getFullYear();
  const month = currentMonthDate.getMonth();

  const monthNames = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
  ];
  const daysOfWeek = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

  const firstDayOfWeek = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const prevMonth = () => {
    setCurrentMonthDate(new Date(year, month - 1, 1));
  };

  const nextMonth = () => {
    setCurrentMonthDate(new Date(year, month + 1, 1));
  };

  const toIso = (y: number, m: number, d: number) => {
    const mm = String(m + 1).padStart(2, "0");
    const dd = String(d).padStart(2, "0");
    return `${y}-${mm}-${dd}`;
  };

  const formatDisplayDate = (iso: string) => {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };

  const calculateDays = (start: string, end: string) => {
    if (isHalfDay) return 0.5;
    const s = new Date(start);
    const e = new Date(end);
    const diff = Math.round((e.getTime() - s.getTime()) / (1000 * 3600 * 24)) + 1;
    return diff > 0 ? diff : 1;
  };

  const handleDateClick = (iso: string) => {
    if (disabled || iso < initialMinDate) return;

    if (isHalfDay) {
      setSelectedStart(iso);
      setSelectedEnd(iso);
      return;
    }

    if (!selectedStart || (selectedStart && selectedEnd)) {
      setSelectedStart(iso);
      setSelectedEnd(null);
    } else if (selectedStart && !selectedEnd) {
      if (iso < selectedStart) {
        setSelectedStart(iso);
        setSelectedEnd(null);
      } else {
        setSelectedEnd(iso);
      }
    }
  };

  const applyPreset = (preset: "tomorrow" | "next_monday" | "3_days" | "1_week") => {
    if (disabled) return;
    const base = new Date(initialMinDate);
    
    if (preset === "tomorrow") {
      const target = new Date(base);
      target.setDate(base.getDate() + 1);
      const iso = target.toISOString().split("T")[0];
      setSelectedStart(iso);
      setSelectedEnd(iso);
      setCurrentMonthDate(new Date(target.getFullYear(), target.getMonth(), 1));
    } else if (preset === "next_monday") {
      const target = new Date(base);
      const day = target.getDay();
      const daysUntilNextMonday = ((1 + 7 - day) % 7) || 7;
      target.setDate(target.getDate() + daysUntilNextMonday);
      const iso = target.toISOString().split("T")[0];
      setSelectedStart(iso);
      setSelectedEnd(iso);
      setCurrentMonthDate(new Date(target.getFullYear(), target.getMonth(), 1));
    } else if (preset === "3_days") {
      setIsHalfDay(false);
      const s = new Date(base);
      s.setDate(base.getDate() + 1);
      const e = new Date(s);
      e.setDate(s.getDate() + 2);
      setSelectedStart(s.toISOString().split("T")[0]);
      setSelectedEnd(e.toISOString().split("T")[0]);
      setCurrentMonthDate(new Date(s.getFullYear(), s.getMonth(), 1));
    } else if (preset === "1_week") {
      setIsHalfDay(false);
      const s = new Date(base);
      s.setDate(base.getDate() + 1);
      const e = new Date(s);
      e.setDate(s.getDate() + 6);
      setSelectedStart(s.toISOString().split("T")[0]);
      setSelectedEnd(e.toISOString().split("T")[0]);
      setCurrentMonthDate(new Date(s.getFullYear(), s.getMonth(), 1));
    }
  };

  const handleContinue = () => {
    if (!selectedStart || !onAction || disabled) return;
    let messageText = "";
    const effectiveEnd = selectedEnd || selectedStart;

    if (isHalfDay) {
      messageText = `for half-day on ${selectedStart} (${halfDayPeriod.toLowerCase()})`;
    } else {
      messageText = `from ${selectedStart} to ${effectiveEnd}`;
    }

    if (reason.trim()) {
      messageText += ` for ${reason.trim()}`;
    }

    onAction(messageText);
  };

  const totalDays = selectedStart ? calculateDays(selectedStart, selectedEnd || selectedStart) : 0;

  return (
    <div className="mt-3.5 p-4 rounded-xl bg-white border border-blue-200/90 shadow-sm w-full max-w-xl space-y-3.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-bold text-zinc-900">
          <CalendarIcon className="w-4 h-4 text-blue-600" />
          <span>Select Dates {leaveTypeName ? `for ${leaveTypeName}` : ""}</span>
        </div>
        <span className="text-[11px] text-zinc-500 font-medium">
          {selectedStart && (selectedEnd || selectedStart)
            ? `${totalDays} ${totalDays === 1 ? "day" : "days"} selected`
            : "Click date on calendar"}
        </span>
      </div>

      {/* Half Day Switch & Quick Presets */}
      <div className="flex items-center justify-between gap-2 p-2 bg-zinc-50 rounded-lg border border-zinc-200/70">
        <label className="flex items-center gap-2 text-xs font-medium text-zinc-700 cursor-pointer">
          <input
            type="checkbox"
            checked={isHalfDay}
            disabled={disabled}
            onChange={(e) => {
              const checked = e.target.checked;
              setIsHalfDay(checked);
              if (checked && selectedStart) {
                setSelectedEnd(selectedStart);
              }
            }}
            className="rounded border-zinc-300 text-blue-600 focus:ring-blue-500"
          />
          <span>Half-Day (0.5 day)</span>
        </label>
        {isHalfDay ? (
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={disabled}
              onClick={() => setHalfDayPeriod("MORNING")}
              className={`px-2 py-0.5 text-[11px] font-medium rounded ${
                halfDayPeriod === "MORNING"
                  ? "bg-blue-600 text-white"
                  : "bg-white text-zinc-600 border border-zinc-200"
              }`}
            >
              Morning
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={() => setHalfDayPeriod("AFTERNOON")}
              className={`px-2 py-0.5 text-[11px] font-medium rounded ${
                halfDayPeriod === "AFTERNOON"
                  ? "bg-blue-600 text-white"
                  : "bg-white text-zinc-600 border border-zinc-200"
              }`}
            >
              Afternoon
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-1">
            <button
              type="button"
              disabled={disabled}
              onClick={() => applyPreset("tomorrow")}
              className="px-2 py-0.5 text-[11px] font-medium rounded bg-white hover:bg-blue-50 text-zinc-700 hover:text-blue-700 border border-zinc-200 transition-colors disabled:opacity-50 cursor-pointer"
            >
              Tomorrow
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={() => applyPreset("next_monday")}
              className="px-2 py-0.5 text-[11px] font-medium rounded bg-white hover:bg-blue-50 text-zinc-700 hover:text-blue-700 border border-zinc-200 transition-colors disabled:opacity-50 cursor-pointer"
            >
              Next Mon
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={() => applyPreset("3_days")}
              className="px-2 py-0.5 text-[11px] font-medium rounded bg-white hover:bg-blue-50 text-zinc-700 hover:text-blue-700 border border-zinc-200 transition-colors disabled:opacity-50 cursor-pointer"
            >
              3 Days
            </button>
          </div>
        )}
      </div>

      {/* Month Navigation */}
      <div className="p-3 bg-zinc-50/70 border border-zinc-200/80 rounded-xl space-y-2.5">
        <div className="flex items-center justify-between px-1">
          <span className="text-xs font-bold text-zinc-800">
            {monthNames[month]} {year}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={disabled}
              onClick={prevMonth}
              className="p-1 rounded-md text-zinc-600 hover:bg-zinc-200 transition-colors disabled:opacity-50 cursor-pointer"
              aria-label="Previous month"
            >
              <ChevronLeftIcon className="w-4 h-4" />
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={nextMonth}
              className="p-1 rounded-md text-zinc-600 hover:bg-zinc-200 transition-colors disabled:opacity-50 cursor-pointer"
              aria-label="Next month"
            >
              <ChevronRightIcon className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Calendar Grid */}
        <div className="grid grid-cols-7 gap-1 text-center text-xs">
          {daysOfWeek.map((d) => (
            <div key={d} className="py-1 text-[11px] font-semibold text-zinc-400 uppercase">
              {d}
            </div>
          ))}

          {Array.from({ length: firstDayOfWeek }).map((_, i) => (
            <div key={`empty-${i}`} className="h-8" />
          ))}

          {Array.from({ length: daysInMonth }).map((_, i) => {
            const dayNum = i + 1;
            const iso = toIso(year, month, dayNum);
            const isPast = iso < initialMinDate;
            const isStart = iso === selectedStart;
            const isEnd = iso === selectedEnd;
            const isInRange = Boolean(
              !isHalfDay && selectedStart && selectedEnd && iso > selectedStart && iso < selectedEnd
            );

            let cellClass = "h-8 w-full flex items-center justify-center text-xs rounded-lg transition-all ";

            if (isStart || isEnd) {
              cellClass += "bg-blue-600 text-white font-bold shadow-sm ";
            } else if (isInRange) {
              cellClass += "bg-blue-100 text-blue-900 font-semibold rounded-none ";
            } else if (isPast) {
              cellClass += "text-zinc-300 cursor-not-allowed ";
            } else {
              cellClass += "text-zinc-700 hover:bg-blue-50 hover:text-blue-600 cursor-pointer ";
            }

            return (
              <button
                key={iso}
                type="button"
                disabled={isPast || disabled}
                onClick={() => handleDateClick(iso)}
                className={cellClass}
              >
                {dayNum}
              </button>
            );
          })}
        </div>
      </div>

      {/* Date Summary and Reason Input */}
      <div className="space-y-2 pt-1 border-t border-zinc-100">
        <div className="flex items-center justify-between text-xs">
          <span className="text-zinc-500 font-medium">Selected:</span>
          <span className="font-semibold text-zinc-900">
            {selectedStart ? (
              isHalfDay ? (
                `${formatDisplayDate(selectedStart)} (0.5 day - ${halfDayPeriod.toLowerCase()})`
              ) : (
                <>
                  {formatDisplayDate(selectedStart)}
                  {selectedEnd && selectedEnd !== selectedStart
                    ? ` → ${formatDisplayDate(selectedEnd)}`
                    : ""}
                </>
              )
            ) : (
              <span className="italic text-zinc-400">None selected</span>
            )}
          </span>
        </div>

        <div>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason for leave (optional, e.g. Personal appointment)"
            disabled={disabled}
            className="w-full text-xs px-3 py-1.5 rounded-lg border border-zinc-200 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 text-zinc-800 placeholder:text-zinc-400 bg-white"
          />
        </div>
      </div>

      {/* Action Submit Button */}
      {onAction && (
        <button
          type="button"
          disabled={!selectedStart || disabled}
          onClick={handleContinue}
          className="w-full inline-flex items-center justify-center gap-1.5 py-2 px-3 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors disabled:opacity-50 cursor-pointer"
        >
          <span>Continue ({totalDays} {totalDays === 1 ? "day" : "days"})</span>
          <ArrowRightIcon className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}

/**
 * Company Holidays Widget
 */
function CompanyHolidaysWidget({ widget }: ChatWidgetProps) {
  const holidays = widget.holidays || [];
  return (
    <div className="mt-3.5 p-4 rounded-xl bg-white border border-indigo-200 shadow-sm w-full max-w-xl space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-bold text-zinc-900">
          <CalendarIcon className="w-4 h-4 text-indigo-600" />
          <span>Official Company Holidays ({holidays.length})</span>
        </div>
      </div>
      {holidays.length === 0 ? (
        <p className="text-xs text-zinc-500">No company holidays scheduled.</p>
      ) : (
        <div className="divide-y divide-zinc-100 border border-zinc-100 rounded-lg overflow-hidden">
          {holidays.map((h: any, idx: number) => (
            <div key={idx} className="p-2.5 flex items-center justify-between text-xs hover:bg-zinc-50/50">
              <div>
                <p className="font-semibold text-zinc-900">{h.name}</p>
                {h.description && <p className="text-[11px] text-zinc-500">{h.description}</p>}
              </div>
              <div className="text-right">
                <span className="font-medium text-zinc-700">{h.date || h.holiday_date}</span>
                {h.is_recurring_yearly && (
                  <span className="block text-[10px] text-indigo-600 font-medium">Annual</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Team Out of Office Widget
 */
function TeamOutOfOfficeWidget({ widget }: ChatWidgetProps) {
  const entries = widget.entries || [];
  return (
    <div className="mt-3.5 p-4 rounded-xl bg-white border border-amber-200 shadow-sm w-full max-w-xl space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-bold text-zinc-900">
          <ClockIcon className="w-4 h-4 text-amber-600" />
          <span>Team Out-of-Office ({entries.length} absent)</span>
        </div>
      </div>
      {entries.length === 0 ? (
        <p className="text-xs text-zinc-500">No team members are currently scheduled out of office.</p>
      ) : (
        <div className="divide-y divide-zinc-100 border border-zinc-100 rounded-lg overflow-hidden">
          {entries.map((e: any, idx: number) => (
            <div key={idx} className="p-2.5 flex items-center justify-between text-xs hover:bg-zinc-50/50">
              <div>
                <p className="font-semibold text-zinc-900">{e.employee_name}</p>
                <p className="text-[11px] text-zinc-500">
                  {e.department_name || "Team"} · {e.leave_type_name}
                </p>
              </div>
              <div className="text-right">
                <span className="font-medium text-zinc-700">
                  {e.start_date} {e.start_date !== e.end_date ? `– ${e.end_date}` : ""}
                </span>
                <span className="block text-[10px] text-amber-700 font-medium">
                  {e.is_half_day && e.half_day_period
                    ? `0.5 day (${e.half_day_period.toLowerCase()})`
                    : `${e.total_days} day(s)`}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * 2. Single Employee Leave Balance Grid / Cards
 */
function LeaveBalanceWidget({ widget, onAction, disabled }: ChatWidgetProps) {
  const balances: any[] = widget.balances || [];
  const year = widget.year;
  const employeeCode = widget.employee_code;
  const employeeName = widget.employee_name;

  if (balances.length === 0) return null;

  return (
    <div className="mt-3.5 space-y-2.5 w-full max-w-xl">
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-700">
          <CalendarIcon className="w-3.5 h-3.5 text-blue-600" />
          <span>
            {employeeName
              ? `Leave Balance for ${employeeName}${employeeCode ? ` (${employeeCode})` : ""}`
              : employeeCode
              ? `Leave Balance for ${employeeCode}`
              : "Your Leave Balance"}
            {year ? ` (${year})` : ""}
          </span>
        </div>
        <span className="text-[11px] text-zinc-400">
          {balances.length} categor{balances.length > 1 ? "ies" : "y"}
        </span>
      </div>

      {employeeCode && onAction && (
        <div className="flex items-center justify-between p-2.5 bg-blue-50/80 border border-blue-200/80 rounded-xl text-xs">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold text-[10px]">
              <UserIcon className="w-3.5 h-3.5" />
            </div>
            <div>
              <span className="font-bold text-blue-950">
                {employeeName ? `${employeeName} (${employeeCode})` : `Employee ${employeeCode}`}
              </span>
              <span className="text-blue-700 block text-[11px]">Manager Quota Inspection</span>
            </div>
          </div>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onAction(`Show leave requests for ${employeeCode}`)}
            className="px-2.5 py-1 bg-white hover:bg-blue-100 text-blue-700 border border-blue-200 rounded-lg font-medium text-[11px] transition-colors cursor-pointer"
          >
            View Requests
          </button>
        </div>
      )}

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
 * 3. All Employees Organization Hierarchy & Balances Widget
 */
interface HierarchyNode {
  employee: any;
  children: HierarchyNode[];
}

function AllEmployeeBalancesWidget({ widget, onAction, disabled }: ChatWidgetProps) {
  const employees: any[] = widget.employees || [];
  const year = widget.year || new Date().getFullYear();
  const [viewMode, setViewMode] = useState<"hierarchy" | "department" | "list">("hierarchy");
  const [searchQuery, setSearchQuery] = useState("");
  const [collapsedNodes, setCollapsedNodes] = useState<Record<string, boolean>>({});

  if (employees.length === 0) return null;

  const toggleCollapse = (id: string) => {
    setCollapsedNodes((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  // Build hierarchy tree
  const { rootNodes, departmentGroups } = useMemo(() => {
    const idMap: Record<string, HierarchyNode> = {};
    employees.forEach((emp) => {
      idMap[emp.employee_id] = { employee: emp, children: [] };
    });

    const roots: HierarchyNode[] = [];
    employees.forEach((emp) => {
      const node = idMap[emp.employee_id];
      if (emp.manager_employee_id && idMap[emp.manager_employee_id]) {
        idMap[emp.manager_employee_id].children.push(node);
      } else {
        roots.push(node);
      }
    });

    // Group by department
    const deptMap: Record<string, any[]> = {};
    employees.forEach((emp) => {
      const deptName = emp.department_name || "General & Operations";
      if (!deptMap[deptName]) deptMap[deptName] = [];
      deptMap[deptName].push(emp);
    });

    return { rootNodes: roots, departmentGroups: deptMap };
  }, [employees]);

  // Filtered employees for list / search
  const filtered = employees.filter((emp) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    const nameMatch = (emp.employee_name || "").toLowerCase().includes(q);
    const codeMatch = (emp.employee_code || "").toLowerCase().includes(q);
    const emailMatch = (emp.employee_email || "").toLowerCase().includes(q);
    const deptMatch = (emp.department_name || "").toLowerCase().includes(q);
    const desigMatch = (emp.designation_title || "").toLowerCase().includes(q);
    return nameMatch || codeMatch || emailMatch || deptMatch || desigMatch;
  });

  return (
    <div className="mt-3.5 space-y-3 w-full max-w-xl">
      {/* Header & View Switcher */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 px-1">
        <div className="flex items-center gap-1.5 text-xs font-bold text-zinc-800">
          <UsersIcon className="w-4 h-4 text-blue-600" />
          <span>Organization Leave & Team Overview ({year})</span>
        </div>

        <div className="flex items-center gap-1 bg-zinc-100 p-0.5 rounded-lg text-xs self-start sm:self-auto">
          <button
            type="button"
            onClick={() => setViewMode("hierarchy")}
            className={`px-2 py-1 rounded-md font-medium transition-all inline-flex items-center gap-1 cursor-pointer ${
              viewMode === "hierarchy"
                ? "bg-white text-blue-700 shadow-xs font-semibold"
                : "text-zinc-600 hover:text-zinc-900"
            }`}
          >
            <HierarchyIcon className="w-3 h-3" />
            <span>Org Tree</span>
          </button>
          <button
            type="button"
            onClick={() => setViewMode("department")}
            className={`px-2 py-1 rounded-md font-medium transition-all inline-flex items-center gap-1 cursor-pointer ${
              viewMode === "department"
                ? "bg-white text-blue-700 shadow-xs font-semibold"
                : "text-zinc-600 hover:text-zinc-900"
            }`}
          >
            <BuildingOfficeIcon className="w-3 h-3" />
            <span>Departments</span>
          </button>
          <button
            type="button"
            onClick={() => setViewMode("list")}
            className={`px-2 py-1 rounded-md font-medium transition-all inline-flex items-center gap-1 cursor-pointer ${
              viewMode === "list"
                ? "bg-white text-blue-700 shadow-xs font-semibold"
                : "text-zinc-600 hover:text-zinc-900"
            }`}
          >
            <FileTextIcon className="w-3 h-3" />
            <span>List</span>
          </button>
        </div>
      </div>

      {/* Search Filter */}
      {employees.length > 2 && (
        <div className="relative">
          <SearchIcon className="w-3.5 h-3.5 absolute left-3 top-2.5 text-zinc-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by employee, code, role, or department..."
            className="w-full text-xs pl-8 pr-3 py-1.5 rounded-lg border border-zinc-200 bg-white placeholder:text-zinc-400 focus:outline-none focus:ring-1 focus:ring-blue-500 shadow-xs"
          />
        </div>
      )}

      {/* 1. HIERARCHY / ORG CHART VIEW */}
      {viewMode === "hierarchy" && (
        <div className="p-3 bg-zinc-50/70 border border-zinc-200/90 rounded-xl space-y-2.5">
          <div className="flex items-center justify-between text-[11px] text-zinc-500 font-medium pb-1 border-b border-zinc-200/60">
            <span>Reporting Hierarchy ({rootNodes.length} top-level nodes)</span>
            <span className="text-[10px] text-zinc-400">Click arrow to toggle direct reports</span>
          </div>

          <div className="space-y-2">
            {rootNodes.map((node) => (
              <OrgTreeNode
                key={node.employee.employee_id}
                node={node}
                level={0}
                collapsedNodes={collapsedNodes}
                toggleCollapse={toggleCollapse}
                onAction={onAction}
                disabled={disabled}
                searchQuery={searchQuery}
              />
            ))}
          </div>
        </div>
      )}

      {/* 2. DEPARTMENT GROUPED VIEW */}
      {viewMode === "department" && (
        <div className="space-y-3">
          {Object.entries(departmentGroups).map(([deptName, deptEmployees]) => {
            const deptFiltered = deptEmployees.filter((emp) => {
              if (!searchQuery.trim()) return true;
              const q = searchQuery.toLowerCase();
              return (
                (emp.employee_name || "").toLowerCase().includes(q) ||
                (emp.employee_code || "").toLowerCase().includes(q) ||
                (emp.designation_title || "").toLowerCase().includes(q)
              );
            });

            if (deptFiltered.length === 0) return null;

            return (
              <div
                key={deptName}
                className="p-3.5 rounded-xl bg-white border border-zinc-200/90 shadow-sm space-y-2.5"
              >
                <div className="flex items-center justify-between pb-2 border-b border-zinc-100">
                  <div className="flex items-center gap-1.5 font-bold text-xs text-zinc-900">
                    <BuildingOfficeIcon className="w-3.5 h-3.5 text-blue-600" />
                    <span>{deptName}</span>
                  </div>
                  <span className="text-[10px] font-semibold px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full">
                    {deptFiltered.length} member{deptFiltered.length > 1 ? "s" : ""}
                  </span>
                </div>

                <div className="space-y-2">
                  {deptFiltered.map((emp) => (
                    <EmployeeMiniCard
                      key={emp.employee_id}
                      emp={emp}
                      onAction={onAction}
                      disabled={disabled}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 3. DIRECTORY LIST VIEW */}
      {viewMode === "list" && (
        <div className="space-y-2.5">
          {filtered.length === 0 ? (
            <div className="p-4 text-center text-xs text-zinc-400 bg-zinc-50 rounded-xl border border-zinc-200/60">
              No employees matching "{searchQuery}".
            </div>
          ) : (
            filtered.map((emp) => (
              <div
                key={emp.employee_id || emp.employee_code}
                className="p-3.5 rounded-xl bg-white border border-zinc-200/90 shadow-sm space-y-3"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold text-xs">
                      {emp.employee_name
                        ? emp.employee_name
                            .split(" ")
                            .map((n: string) => n[0])
                            .join("")
                            .slice(0, 2)
                            .toUpperCase()
                        : "EM"}
                    </div>
                    <div>
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="font-bold text-xs text-zinc-900">
                          {emp.employee_name}
                        </span>
                        <span className="font-mono text-[10px] font-semibold bg-zinc-100 text-zinc-600 px-1.5 py-0.5 rounded">
                          {emp.employee_code}
                        </span>
                        {emp.designation_title && (
                          <span className="text-[10px] text-zinc-500 font-medium">
                            • {emp.designation_title}
                          </span>
                        )}
                        {emp.department_name && (
                          <span className="text-[10px] text-blue-600 bg-blue-50 px-1.5 py-0.2 rounded font-medium">
                            {emp.department_name}
                          </span>
                        )}
                      </div>
                      {emp.employee_email && (
                        <span className="text-[11px] text-zinc-400 block truncate max-w-[200px]">
                          {emp.employee_email}
                        </span>
                      )}
                    </div>
                  </div>

                  {onAction && (
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => onAction(`Show leave requests for ${emp.employee_code}`)}
                      className="px-2.5 py-1 text-[11px] font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200/80 rounded-lg transition-colors cursor-pointer"
                    >
                      View Requests
                    </button>
                  )}
                </div>

                {/* Balances List */}
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-1 border-t border-zinc-100">
                  {(emp.balances || []).map((b: any) => {
                    const allocated = parseFloat(b.allocated_days) || 0;
                    const remaining = parseFloat(b.remaining_days) || 0;
                    const pct = allocated > 0 ? Math.min(100, Math.max(0, (remaining / allocated) * 100)) : 0;

                    return (
                      <div
                        key={b.leave_type_name}
                        className="p-2 rounded-lg bg-zinc-50/80 border border-zinc-100 space-y-1"
                      >
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="font-semibold text-zinc-700 truncate">
                            {b.leave_type_name}
                          </span>
                        </div>
                        <div className="flex items-baseline gap-1">
                          <span className="font-bold text-xs text-zinc-900">
                            {remaining}
                          </span>
                          <span className="text-[10px] text-zinc-400">
                            / {allocated}d
                          </span>
                        </div>
                        <div className="w-full h-1 bg-zinc-200/80 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${
                              pct > 50 ? "bg-blue-600" : pct > 20 ? "bg-amber-500" : "bg-rose-500"
                            }`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Org Tree Node Recursive Component
 */
function OrgTreeNode({
  node,
  level,
  collapsedNodes,
  toggleCollapse,
  onAction,
  disabled,
  searchQuery,
}: {
  node: HierarchyNode;
  level: number;
  collapsedNodes: Record<string, boolean>;
  toggleCollapse: (id: string) => void;
  onAction?: (actionText: string) => void;
  disabled?: boolean;
  searchQuery: string;
}) {
  const emp = node.employee;
  const hasChildren = node.children.length > 0;
  const isCollapsed = Boolean(collapsedNodes[emp.employee_id]);

  const initials = emp.employee_name
    ? emp.employee_name
        .split(" ")
        .map((n: string) => n[0])
        .join("")
        .slice(0, 2)
        .toUpperCase()
    : "EM";

  const totalRemaining = (emp.balances || []).reduce(
    (acc: number, b: any) => acc + (parseFloat(b.remaining_days) || 0),
    0
  );

  return (
    <div className="space-y-1.5">
      <div
        className={`p-2.5 rounded-xl bg-white border shadow-xs flex items-center justify-between gap-2 transition-all ${
          level === 0
            ? "border-blue-300 ring-1 ring-blue-400/20"
            : "border-zinc-200/90"
        }`}
        style={{ marginLeft: `${level * 16}px` }}
      >
        <div className="flex items-center gap-2 min-w-0">
          {hasChildren && (
            <button
              type="button"
              onClick={() => toggleCollapse(emp.employee_id)}
              className="p-1 text-zinc-500 hover:bg-zinc-100 rounded-md transition-colors cursor-pointer shrink-0"
              aria-label={isCollapsed ? "Expand node" : "Collapse node"}
            >
              {isCollapsed ? (
                <ChevronRightIcon className="w-3.5 h-3.5 text-blue-600" />
              ) : (
                <ChevronDownIcon className="w-3.5 h-3.5 text-blue-600" />
              )}
            </button>
          )}

          <div className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold text-[10px] shrink-0">
            {initials}
          </div>

          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="font-bold text-xs text-zinc-900 truncate">
                {emp.employee_name}
              </span>
              <span className="font-mono text-[10px] font-semibold bg-zinc-100 text-zinc-600 px-1 py-0.2 rounded">
                {emp.employee_code}
              </span>
              {hasChildren && (
                <span className="text-[10px] bg-amber-50 text-amber-800 border border-amber-200/60 px-1.5 py-0.2 rounded-full font-medium">
                  {node.children.length} direct report{node.children.length > 1 ? "s" : ""}
                </span>
              )}
            </div>
            <div className="text-[10px] text-zinc-500 flex items-center gap-1 truncate">
              <span>{emp.designation_title || "Team Member"}</span>
              {emp.department_name && (
                <>
                  <span>•</span>
                  <span className="text-blue-600 font-medium">{emp.department_name}</span>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <div className="text-right hidden sm:block">
            <span className="text-[10px] text-zinc-400 block">Total Left</span>
            <span className="text-xs font-bold text-zinc-900">{totalRemaining}d</span>
          </div>

          {onAction && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => onAction(`Show leave requests for ${emp.employee_code}`)}
              className="px-2 py-1 text-[10px] font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-md transition-colors cursor-pointer"
            >
              Requests
            </button>
          )}
        </div>
      </div>

      {/* Render children if not collapsed */}
      {hasChildren && !isCollapsed && (
        <div className="space-y-1.5 pl-2 border-l-2 border-blue-100 ml-4">
          {node.children.map((child) => (
            <OrgTreeNode
              key={child.employee.employee_id}
              node={child}
              level={level + 1}
              collapsedNodes={collapsedNodes}
              toggleCollapse={toggleCollapse}
              onAction={onAction}
              disabled={disabled}
              searchQuery={searchQuery}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Department Mini Card for Department View
 */
function EmployeeMiniCard({
  emp,
  onAction,
  disabled,
}: {
  emp: any;
  onAction?: (actionText: string) => void;
  disabled?: boolean;
}) {
  const initials = emp.employee_name
    ? emp.employee_name
        .split(" ")
        .map((n: string) => n[0])
        .join("")
        .slice(0, 2)
        .toUpperCase()
    : "EM";

  return (
    <div className="p-2.5 rounded-lg bg-zinc-50 border border-zinc-100 flex items-center justify-between gap-2">
      <div className="flex items-center gap-2 min-w-0">
        <div className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold text-[10px] shrink-0">
          {initials}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 truncate">
            <span className="font-bold text-xs text-zinc-900">{emp.employee_name}</span>
            <span className="font-mono text-[10px] text-zinc-500 font-medium">
              ({emp.employee_code})
            </span>
          </div>
          <div className="text-[10px] text-zinc-400 truncate">
            {emp.designation_title || "Member"} • {emp.employee_email}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        <div className="flex items-center gap-1 text-[10px]">
          {(emp.balances || []).slice(0, 2).map((b: any) => (
            <span
              key={b.leave_type_name}
              className="bg-white border border-zinc-200 px-1.5 py-0.5 rounded font-medium text-zinc-700"
            >
              {b.leave_type_name.split(" ")[0]}: {b.remaining_days}d
            </span>
          ))}
        </div>

        {onAction && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onAction(`Show leave requests for ${emp.employee_code}`)}
            className="px-2 py-0.5 text-[10px] font-medium text-blue-700 bg-white hover:bg-blue-50 border border-blue-200 rounded transition-colors cursor-pointer"
          >
            Requests
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * 4. Leave Requests History / Manager Pipeline Queue
 */
function LeaveRequestsListWidget({ widget, onAction, disabled }: ChatWidgetProps) {
  const requests: any[] = widget.requests || [];
  const isManager = Boolean(widget.is_manager);

  const [statusFilter, setStatusFilter] = useState<"ALL" | "PENDING" | "APPROVED" | "REJECTED">("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");

  if (requests.length === 0) return null;

  const pendingCount = requests.filter((r) => r.status === "PENDING").length;
  const approvedCount = requests.filter((r) => r.status === "APPROVED").length;
  const rejectedCount = requests.filter((r) => r.status === "REJECTED").length;

  const filtered = requests.filter((r) => {
    if (statusFilter !== "ALL" && r.status !== statusFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const numMatch = (r.request_number || "").toLowerCase().includes(q);
      const typeMatch = (r.leave_type_name || "").toLowerCase().includes(q);
      const nameMatch = (r.employee_name || "").toLowerCase().includes(q);
      const codeMatch = (r.employee_code || "").toLowerCase().includes(q);
      return numMatch || typeMatch || nameMatch || codeMatch;
    }
    return true;
  });

  return (
    <div className="mt-3.5 space-y-3 w-full max-w-xl">
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-1.5 text-xs font-bold text-zinc-800">
          <FileTextIcon className="w-4 h-4 text-blue-600" />
          <span>{isManager ? "Team Leave Requests Pipeline" : "Your Leave Requests"}</span>
        </div>
        <span className="text-[11px] text-zinc-400 font-medium">
          {requests.length} total
        </span>
      </div>

      {/* Filter Tabs & Search Bar */}
      <div className="space-y-2">
        <div className="flex items-center gap-1 overflow-x-auto pb-1 text-xs">
          <button
            type="button"
            onClick={() => setStatusFilter("ALL")}
            className={`px-2.5 py-1 rounded-lg font-medium transition-colors cursor-pointer ${
              statusFilter === "ALL"
                ? "bg-zinc-800 text-white"
                : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200"
            }`}
          >
            All ({requests.length})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("PENDING")}
            className={`px-2.5 py-1 rounded-lg font-medium transition-colors cursor-pointer flex items-center gap-1 ${
              statusFilter === "PENDING"
                ? "bg-amber-600 text-white"
                : "bg-amber-50 text-amber-800 hover:bg-amber-100 border border-amber-200/60"
            }`}
          >
            <ClockIcon className="w-3 h-3" />
            Pending ({pendingCount})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("APPROVED")}
            className={`px-2.5 py-1 rounded-lg font-medium transition-colors cursor-pointer flex items-center gap-1 ${
              statusFilter === "APPROVED"
                ? "bg-emerald-600 text-white"
                : "bg-emerald-50 text-emerald-800 hover:bg-emerald-100 border border-emerald-200/60"
            }`}
          >
            <CheckIcon className="w-3 h-3" />
            Approved ({approvedCount})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("REJECTED")}
            className={`px-2.5 py-1 rounded-lg font-medium transition-colors cursor-pointer flex items-center gap-1 ${
              statusFilter === "REJECTED"
                ? "bg-rose-600 text-white"
                : "bg-rose-50 text-rose-800 hover:bg-rose-100 border border-rose-200/60"
            }`}
          >
            <XIcon className="w-3 h-3" />
            Rejected ({rejectedCount})
          </button>
        </div>

        {requests.length > 2 && (
          <div className="relative">
            <SearchIcon className="w-3.5 h-3.5 absolute left-3 top-2.5 text-zinc-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by employee, request #, or leave type..."
              className="w-full text-xs pl-8 pr-3 py-1.5 rounded-lg border border-zinc-200 bg-white placeholder:text-zinc-400 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
        )}
      </div>

      {/* Requests List */}
      <div className="space-y-2">
        {filtered.length === 0 ? (
          <div className="p-4 text-center text-xs text-zinc-400 bg-zinc-50 rounded-xl border border-zinc-200/60">
            No requests matching the selected filter.
          </div>
        ) : (
          filtered.map((r) => {
            const isPending = r.status === "PENDING";
            const isApproved = r.status === "APPROVED";
            const isRejected = r.status === "REJECTED";

            return (
              <div
                key={r.request_number || r.leave_request_id}
                className={`p-3.5 rounded-xl bg-white border shadow-sm transition-all duration-150 flex flex-col gap-2.5 ${
                  isPending && isManager
                    ? "border-amber-300 ring-1 ring-amber-400/20"
                    : "border-zinc-200/90"
                }`}
              >
                {/* Employee Header */}
                {isManager && (r.employee_name || r.employee_code) && (
                  <div className="flex items-center justify-between pb-2 border-b border-zinc-100">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold text-[10px]">
                        {r.employee_name
                          ? r.employee_name
                              .split(" ")
                              .map((n: string) => n[0])
                              .join("")
                              .slice(0, 2)
                          : "EM"}
                      </div>
                      <div>
                        <span className="font-bold text-xs text-zinc-900">
                          {r.employee_name || "Employee"}
                        </span>
                        {r.employee_code && (
                          <span className="ml-1.5 text-[11px] font-mono text-zinc-500">
                            ({r.employee_code})
                          </span>
                        )}
                      </div>
                    </div>
                    {r.employee_email && (
                      <span className="text-[11px] text-zinc-400 truncate max-w-[160px]">
                        {r.employee_email}
                      </span>
                    )}
                  </div>
                )}

                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
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
                    <div className="flex items-center gap-1.5 shrink-0 self-end sm:self-center">
                      {isManager ? (
                        <>
                          <button
                            type="button"
                            disabled={disabled}
                            onClick={() => onAction(`Approve request ${r.request_number}`)}
                            className="px-3 py-1.5 text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg transition-colors shadow-sm disabled:opacity-50 cursor-pointer inline-flex items-center gap-1"
                          >
                            <CheckIcon className="w-3 h-3" />
                            <span>Approve</span>
                          </button>
                          <button
                            type="button"
                            disabled={disabled}
                            onClick={() => onAction(`Reject request ${r.request_number}`)}
                            className="px-3 py-1.5 text-xs font-medium bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 rounded-lg transition-colors disabled:opacity-50 cursor-pointer inline-flex items-center gap-1"
                          >
                            <XIcon className="w-3 h-3" />
                            <span>Reject</span>
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
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

/**
 * 5. Available Leave Types
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
 * 6. Staged Action Confirmation Widget (Employee & Manager Staging)
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

      <div className="mt-3 p-3.5 bg-white border border-blue-100 rounded-xl text-xs space-y-2">
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
          <div className="space-y-2">
            {args.employee_name && (
              <div className="flex items-center justify-between pb-2 border-b border-zinc-100">
                <span className="text-zinc-500">Requesting Employee:</span>
                <span className="font-bold text-zinc-900">
                  {args.employee_name} {args.employee_code ? `(${args.employee_code})` : ""}
                </span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-zinc-500">Request Number:</span>
              <span className="font-mono font-bold text-zinc-900">
                {args.request_number}
              </span>
            </div>
            {args.start_date && (
              <div className="flex justify-between">
                <span className="text-zinc-500">Duration:</span>
                <span className="font-semibold text-zinc-800">
                  {args.start_date} to {args.end_date} ({args.total_days} days)
                </span>
              </div>
            )}
            {args.reason && (
              <div className="flex justify-between">
                <span className="text-zinc-500">Employee Reason:</span>
                <span className="italic text-zinc-800">"{args.reason}"</span>
              </div>
            )}
            <div className="flex justify-between items-center pt-1 border-t border-zinc-100">
              <span className="text-zinc-500">Decision Outcome:</span>
              <span
                className={`inline-flex items-center gap-1 font-bold text-xs px-2 py-0.5 rounded-full ${
                  args.approve
                    ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                    : "bg-rose-50 text-rose-700 border border-rose-200"
                }`}
              >
                {args.approve ? <CheckIcon className="w-3 h-3" /> : <XIcon className="w-3 h-3" />}
                {args.approve ? "APPROVE REQUEST" : "REJECT REQUEST"}
              </span>
            </div>
          </div>
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
            className={`flex-1 inline-flex items-center justify-center gap-1.5 py-2 px-3 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors disabled:opacity-50 cursor-pointer ${
              actionType === "decide_leave" && !args.approve
                ? "bg-rose-600 hover:bg-rose-700 active:bg-rose-800"
                : actionType === "decide_leave" && args.approve
                ? "bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800"
                : "bg-blue-600 hover:bg-blue-700 active:bg-blue-800"
            }`}
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
 * 7. Action Execution Result Widget
 */
function ActionResultWidget({ widget }: { widget: any }) {
  const result = widget.result || {};
  const isApproved = result.status === "APPROVED";
  const isRejected = result.status === "REJECTED";
  const isCancelled = result.status === "CANCELLED";

  return (
    <div
      className={`mt-3 p-3.5 rounded-xl border w-full max-w-xl flex items-start gap-2.5 ${
        isRejected
          ? "bg-rose-50/80 border-rose-200/90 text-rose-900"
          : isCancelled
          ? "bg-zinc-50 border-zinc-200 text-zinc-800"
          : "bg-emerald-50/80 border-emerald-200/90 text-emerald-900"
      }`}
    >
      <div
        className={`w-6 h-6 rounded-full text-white flex items-center justify-center shrink-0 mt-0.5 ${
          isRejected ? "bg-rose-600" : isCancelled ? "bg-zinc-600" : "bg-emerald-600"
        }`}
      >
        {isRejected ? <XIcon className="w-3.5 h-3.5" /> : <CheckCircleIcon className="w-4 h-4" />}
      </div>
      <div className="space-y-1 text-xs">
        <div className="font-bold">
          Action Completed: {result.status || "SUCCESS"}
        </div>
        {result.request_number && (
          <div>
            Request <span className="font-mono font-bold">{result.request_number}</span>{" "}
            {result.employee_name ? `for ${result.employee_name} ` : ""}is now{" "}
            <span className="font-semibold uppercase">{result.status}</span>.
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * 8. Single Leave Request Detail Widget
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

/**
 * 9. Vacancies List Widget
 */
function VacanciesListWidget({ widget, onAction, disabled }: ChatWidgetProps) {
  const pathname = usePathname();
  const vacancies = widget.vacancies || [];
  const [userRole, setUserRole] = useState<string | null>(null);

  React.useEffect(() => {
    if (getAuthToken()) {
      api
        .me()
        .then((res) => setUserRole(res.user.coarse_role))
        .catch(() => {});
    }
  }, []);

  const isEmployeeOrManager =
    pathname?.startsWith("/employee") ||
    pathname?.startsWith("/manager") ||
    userRole === "EMPLOYEE" ||
    userRole === "HR_ADMIN" ||
    widget.can_apply === false;

  const canApply = !isEmployeeOrManager;

  if (vacancies.length === 0) return null;

  return (
    <div className="mt-3 w-full max-w-2xl space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-zinc-700 uppercase tracking-wider">
          Available Positions ({vacancies.length})
        </span>
      </div>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {vacancies.map((v: any) => {
          const itemCanApply = canApply && v.can_apply !== false;
          return (
            <div
              key={v.vacancy_id}
              className="flex flex-col justify-between rounded-xl border border-zinc-200 bg-white p-3.5 shadow-sm transition-all hover:border-blue-300 hover:shadow"
            >
              <div>
                <div className="flex items-start justify-between gap-1.5">
                  <h4 className="text-sm font-semibold text-zinc-900 leading-tight">
                    {v.title}
                  </h4>
                  <span className="shrink-0 rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-700">
                    {(v.employment_type || "").replaceAll("_", " ")}
                  </span>
                </div>
                {v.department_name && (
                  <p className="mt-1 text-xs text-zinc-500 font-medium">
                    {v.department_name}
                  </p>
                )}
                {v.description && (
                  <p className="mt-2 line-clamp-2 text-xs text-zinc-600 leading-relaxed">
                    {v.description}
                  </p>
                )}
                {v.closing_date && (
                  <p className="mt-2 text-[11px] text-zinc-400">
                    Closes: {v.closing_date}
                  </p>
                )}
              </div>
              <div className="mt-3 flex items-center gap-2 border-t border-zinc-100 pt-2.5">
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onAction?.(`Tell me about the ${v.title} vacancy`)}
                  className={`rounded-lg border border-zinc-200 bg-zinc-50 px-2.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 hover:text-zinc-900 transition-colors ${
                    itemCanApply ? "flex-1" : "w-full"
                  }`}
                >
                  Details
                </button>
                {itemCanApply && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onAction?.(`I want to apply for ${v.title}`)}
                    className="flex-1 rounded-lg bg-blue-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-blue-700 shadow-sm transition-colors"
                  >
                    Apply in Chat
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * 10. Vacancy Detail Widget
 */
function VacancyDetailWidget({ widget, onAction, disabled }: ChatWidgetProps) {
  const pathname = usePathname();
  const vacancy = widget.vacancy;
  const [userRole, setUserRole] = useState<string | null>(null);

  React.useEffect(() => {
    if (getAuthToken()) {
      api
        .me()
        .then((res) => setUserRole(res.user.coarse_role))
        .catch(() => {});
    }
  }, []);

  if (!vacancy) return null;

  const isEmployeeOrManager =
    pathname?.startsWith("/employee") ||
    pathname?.startsWith("/manager") ||
    userRole === "EMPLOYEE" ||
    userRole === "HR_ADMIN" ||
    widget.can_apply === false ||
    vacancy.can_apply === false;

  const canApply = !isEmployeeOrManager;

  return (
    <div className="mt-3 w-full max-w-xl rounded-xl border border-zinc-200 bg-white p-4 shadow-sm space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-base font-semibold text-zinc-900 leading-tight">
            {vacancy.title}
          </h3>
          <p className="text-xs text-zinc-500 font-medium mt-0.5">
            {vacancy.department_name ? `${vacancy.department_name} · ` : ""}
            {(vacancy.employment_type || "").replaceAll("_", " ")}
          </p>
        </div>
        <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700 border border-emerald-200">
          {vacancy.status || "OPEN"}
        </span>
      </div>

      {vacancy.description && (
        <p className="text-xs text-zinc-600 whitespace-pre-wrap leading-relaxed border-t border-zinc-100 pt-2.5">
          {vacancy.description}
        </p>
      )}

      {vacancy.closing_date && (
        <p className="text-xs text-zinc-500">
          <strong>Closing Date:</strong> {vacancy.closing_date}
        </p>
      )}

      {canApply ? (
        <div className="pt-2 flex justify-end">
          <button
            type="button"
            disabled={disabled}
            onClick={() => onAction?.(`I want to apply for ${vacancy.title}`)}
            className="rounded-lg bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700 shadow-sm transition-colors"
          >
            Apply for this Role
          </button>
        </div>
      ) : (
        <div className="rounded-lg border border-zinc-100 bg-zinc-50/80 p-2.5 text-[11px] text-zinc-500">
          Internal position notice · For internal transfers or inquiries, please contact HR or your manager.
        </div>
      )}
    </div>
  );
}

/**
 * 11. Apply Vacancy Widget (In-Chat Resume Upload & Candidate Setup)
 */
function ApplyVacancyWidget({ widget, onAction, disabled }: ChatWidgetProps) {
  const pathname = usePathname();
  const vacancyId = widget.vacancy_id;
  const vacancyTitle = widget.vacancy_title || "Position";

  const [isLoggedIn, setIsLoggedIn] = useState<boolean>(() => !!getAuthToken());
  const [userRole, setUserRole] = useState<string | null>(null);
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    phone: "",
    password: "",
  });
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [appId, setAppId] = useState<string | null>(null);

  React.useEffect(() => {
    if (getAuthToken()) {
      api
        .me()
        .then((res) => {
          setUserRole(res.user.coarse_role);
          if (res.user.coarse_role === "CANDIDATE") {
            setIsLoggedIn(true);
          }
        })
        .catch(() => {});
    }
  }, []);

  const isEmployeeOrManager =
    pathname?.startsWith("/employee") ||
    pathname?.startsWith("/manager") ||
    userRole === "EMPLOYEE" ||
    userRole === "HR_ADMIN";

  const allowedExts = [".pdf", ".docx"];
  const maxBytes = 10 * 1024 * 1024;

  function setField(field: string, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    setError(null);
    const f = e.target.files?.[0];
    if (!f) return;
    const lower = f.name.toLowerCase();
    if (!allowedExts.some((ext) => lower.endsWith(ext))) {
      setError("Only PDF or DOCX resume files are accepted.");
      return;
    }
    if (f.size > maxBytes) {
      setError("Resume file exceeds 10MB limit.");
      return;
    }
    setFile(f);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !vacancyId) {
      setError("Please select a resume file.");
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      if (isLoggedIn) {
        // Authenticated candidate flow
        const res = await api.apply(vacancyId, file);
        setSubmitted(true);
        setAppId(res.application_id);
      } else {
        // Visitor setup -> evolve to registered candidate flow
        if (form.password.length < 8) {
          setError("Password must be at least 8 characters.");
          setSubmitting(false);
          return;
        }

        const formData = new FormData();
        formData.append("file", file);
        formData.append("first_name", form.first_name.trim());
        formData.append("last_name", form.last_name.trim());
        formData.append("email", form.email.trim());
        if (form.phone.trim()) {
          formData.append("phone", form.phone.trim());
        }
        formData.append("password", form.password);

        const res = await api.applyAsNewCandidate(vacancyId, formData);

        // Auto sign-in with newly created credentials
        try {
          const loginRes = await api.login(form.email.trim(), form.password);
          setAuthToken(loginRes.access_token);
          setIsLoggedIn(true);
        } catch {
          // Token setup fallback
        }

        setSubmitted(true);
        setAppId(res.application_id);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          setError("Your session has expired or you are not authenticated. Please sign in.");
        } else if (err.status === 403) {
          setError("Only candidate accounts can submit job applications. For internal transfers, please contact HR.");
        } else {
          setError(err.detail);
        }
      } else {
        setError("Failed to submit application. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (isEmployeeOrManager) {
    return (
      <div className="mt-3 w-full max-w-xl rounded-xl border border-amber-200 bg-amber-50/80 p-4 shadow-sm space-y-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-amber-600 text-white shadow-xs">
            <UserIcon className="h-4 w-4" />
          </div>
          <div>
            <h4 className="text-sm font-bold text-amber-900">
              Internal Employee Notice
            </h4>
            <p className="text-xs text-amber-700">
              Role: <strong>{vacancyTitle}</strong>
            </p>
          </div>
        </div>
        <p className="text-xs text-amber-800 leading-relaxed">
          Job applications submitted through this chatbot flow are for external candidates. As an active employee, if you are interested in internal transfer or career mobility opportunities for this position, please reach out to HR or your manager.
        </p>
      </div>
    );
  }

  if (submitted) {
    return (
      <div className="mt-3 w-full max-w-xl rounded-xl border border-emerald-200 bg-emerald-50/70 p-4 shadow-sm space-y-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-600 text-white shadow-xs">
            <CheckIcon className="h-4 w-4" />
          </div>
          <div>
            <h4 className="text-sm font-bold text-emerald-900">
              Application Submitted & Candidate Account Active!
            </h4>
            <p className="text-xs text-emerald-700">
              Role: <strong>{vacancyTitle}</strong>
              {appId ? ` · Ref: ${appId.slice(0, 8)}` : ""}
            </p>
          </div>
        </div>

        <p className="text-xs text-emerald-800 leading-relaxed">
          Your credentials have been set up and your resume is now queued for AI screening.
          You can track your progress right here in chat or visit your candidate portal anytime.
        </p>

        <div className="pt-1 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={disabled}
            onClick={() => onAction?.("What is the status of my applications?")}
            className="rounded-lg bg-emerald-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700 shadow-xs transition-colors"
          >
            Check Application Status in Chat
          </button>
          <Link
            href="/candidate/applications"
            className="rounded-lg border border-emerald-300 bg-white px-3.5 py-1.5 text-xs font-semibold text-emerald-800 hover:bg-emerald-50 transition-colors"
          >
            Open Candidate Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-3 w-full max-w-xl rounded-xl border border-zinc-200 bg-white p-4 sm:p-5 shadow-sm space-y-4">
      <div className="flex items-start justify-between gap-2 border-b border-zinc-100 pb-3">
        <div>
          <span className="text-[11px] font-bold text-blue-600 uppercase tracking-wider">
            {isLoggedIn ? "Apply via Chat" : "Apply & Create Candidate Account"}
          </span>
          <h3 className="text-base font-bold text-zinc-900">
            {vacancyTitle}
          </h3>
          {widget.department_name && (
            <p className="text-xs text-zinc-500 font-medium">
              {widget.department_name}
            </p>
          )}
        </div>
        <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-700 border border-blue-100">
          Open Role
        </span>
      </div>

      <div className="rounded-lg border border-blue-100 bg-blue-50/60 p-2.5 text-xs text-blue-900 space-y-1">
        <div className="flex items-center gap-1.5 font-semibold text-blue-800">
          <SparklesIcon className="h-3.5 w-3.5 text-blue-600" />
          ATS-Friendly Resume Screening
        </div>
        <p className="text-[11px] text-blue-700 leading-normal">
          Upload a single-column, text-based PDF or DOCX resume for optimal screening analysis.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-3.5">
        {/* Candidate credentials setup for non-logged-in visitors */}
        {!isLoggedIn && (
          <div className="space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/60 p-3.5">
            <div className="text-xs font-semibold text-zinc-700">
              Candidate Profile & Login Credentials
            </div>

            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              <div>
                <label className="block text-[11px] font-medium text-zinc-600 mb-1">
                  First Name *
                </label>
                <input
                  required
                  type="text"
                  placeholder="Jane"
                  value={form.first_name}
                  onChange={(e) => setField("first_name", e.target.value)}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-2.5 py-1.5 text-xs text-zinc-800 focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-[11px] font-medium text-zinc-600 mb-1">
                  Last Name *
                </label>
                <input
                  required
                  type="text"
                  placeholder="Doe"
                  value={form.last_name}
                  onChange={(e) => setField("last_name", e.target.value)}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-2.5 py-1.5 text-xs text-zinc-800 focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              <div>
                <label className="block text-[11px] font-medium text-zinc-600 mb-1">
                  Email Address *
                </label>
                <input
                  required
                  type="email"
                  placeholder="jane.doe@example.com"
                  value={form.email}
                  onChange={(e) => setField("email", e.target.value)}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-2.5 py-1.5 text-xs text-zinc-800 focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-[11px] font-medium text-zinc-600 mb-1">
                  Phone Number
                </label>
                <input
                  type="tel"
                  placeholder="+1 555 0199"
                  value={form.phone}
                  onChange={(e) => setField("phone", e.target.value)}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-2.5 py-1.5 text-xs text-zinc-800 focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="block text-[11px] font-medium text-zinc-600 mb-1">
                Password * (min 8 chars — used to track your applications)
              </label>
              <input
                required
                type="password"
                minLength={8}
                placeholder="Choose a secure password"
                value={form.password}
                onChange={(e) => setField("password", e.target.value)}
                className="w-full rounded-lg border border-zinc-300 bg-white px-2.5 py-1.5 text-xs text-zinc-800 focus:border-blue-500 focus:outline-none"
              />
            </div>
          </div>
        )}

        {/* Resume Dropzone */}
        <div>
          <label className="block text-[11px] font-medium text-zinc-700 mb-1">
            Resume / CV *
          </label>
          <label className="flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-lg border-2 border-dashed border-zinc-300 bg-zinc-50/50 p-4 text-center transition-colors hover:border-blue-400 hover:bg-blue-50/30">
            <FileTextIcon className="h-6 w-6 text-blue-500" />
            <span className="text-xs font-medium text-zinc-800">
              {file ? file.name : "Click to select your resume (PDF or DOCX)"}
            </span>
            <span className="text-[10px] text-zinc-400">PDF or DOCX, max 10MB</span>
            <input
              type="file"
              accept=".pdf,.docx"
              disabled={disabled || submitting}
              onChange={handleFile}
              className="hidden"
            />
          </label>
        </div>

        {error && (
          <div className="rounded-md border border-rose-200 bg-rose-50 p-2 text-xs font-medium text-rose-700">
            {error}
          </div>
        )}

        <div className="flex items-center justify-between gap-2 pt-1 border-t border-zinc-100">
          <p className="text-[11px] text-zinc-400">
            {isLoggedIn ? "Applied with your candidate account" : "Creates your login & submits application"}
          </p>
          <button
            type="submit"
            disabled={!file || submitting || disabled}
            className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50 transition-colors shrink-0"
          >
            {submitting
              ? "Submitting Application…"
              : isLoggedIn
              ? "Submit Application"
              : "Register & Submit Application"}
          </button>
        </div>
      </form>
    </div>
  );
}

/**
 * 12. Applications List Widget
 */
function ApplicationsListWidget({ widget, onAction, disabled }: ChatWidgetProps) {
  const applications = widget.applications || [];
  if (applications.length === 0) return null;

  return (
    <div className="mt-3 w-full max-w-xl space-y-2.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-zinc-700 uppercase tracking-wider">
          Your Applications ({applications.length})
        </span>
      </div>
      <div className="space-y-2">
        {applications.map((app: any) => {
          const status = app.application_status || "APPLIED";
          const isShortlisted = status === "SHORTLISTED";
          const isRejected = status === "REJECTED";
          const isWithdrawn = status === "WITHDRAWN";
          const canWithdraw = (status === "APPLIED" || status === "SHORTLISTED") && !!onAction;

          return (
            <div
              key={app.application_id}
              className="flex items-center justify-between gap-3 rounded-xl border border-zinc-200 bg-white p-3.5 shadow-sm transition-all hover:border-zinc-300"
            >
              <div className="space-y-0.5">
                <div className="flex items-center gap-2">
                  <h4 className="text-sm font-semibold text-zinc-900">
                    {app.vacancy_title}
                  </h4>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-semibold border ${
                      isShortlisted
                        ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                        : isRejected
                        ? "bg-rose-50 text-rose-700 border-rose-200"
                        : isWithdrawn
                        ? "bg-zinc-100 text-zinc-600 border-zinc-200"
                        : "bg-blue-50 text-blue-700 border-blue-200"
                    }`}
                  >
                    {status}
                  </span>
                </div>
                <p className="text-xs text-zinc-500">
                  {app.department_name ? `${app.department_name} · ` : ""}
                  Applied: {app.applied_at ? new Date(app.applied_at).toLocaleDateString() : "Recently"}
                </p>
              </div>

              {canWithdraw && (
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onAction?.(`Withdraw my application for ${app.vacancy_title}`)}
                  className="shrink-0 rounded-lg border border-red-200 bg-red-50/50 px-2.5 py-1 text-xs font-medium text-red-600 transition hover:bg-red-100/70 hover:border-red-300 disabled:opacity-50"
                >
                  Withdraw
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
