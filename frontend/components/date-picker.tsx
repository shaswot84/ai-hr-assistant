"use client";

import { useEffect, useMemo, useRef, useState } from "react";

const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** Pads a number to 2 digits for ISO date strings (YYYY-MM-DD). */
function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** Converts a YYYY-MM-DD string to a local Date (avoiding TZ/UTC off-by-one). */
function parseIso(value: string): Date | null {
  if (!value) return null;
  const [y, m, d] = value.split("-").map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
}

/** Builds an array of Date cells for a month grid, padded to full weeks. */
function monthCells(year: number, month: number): Date[] {
  const first = new Date(year, month, 1);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const startOffset = first.getDay();
  const cells: Date[] = [];
  for (let i = 0; i < startOffset; i++) cells.push(new Date(year, month, 1 - (startOffset - i)));
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(year, month, d));
  while (cells.length % 7 !== 0) cells.push(new Date(year, month + 1, cells.length - startOffset - daysInMonth + 1));
  return cells;
}

/**
 * Custom date picker matching the app's light theme (no native browser chrome,
 * so it looks consistent across the UI). Renders a button that opens a small
 * calendar popover with month navigation.
 *
 * @param props.value ISO date string (YYYY-MM-DD) or empty.
 * @param props.onChange Callback receiving the new ISO date string, or "" when cleared.
 * @param props.className Extra classes for the trigger button.
 * @param props.placeholder Placeholder text when no date is selected.
 */
export function DatePicker({
  value,
  onChange,
  className = "",
  placeholder = "Select date",
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<Date>(() => parseIso(value) ?? new Date());
  const rootRef = useRef<HTMLDivElement>(null);

  // Close the calendar when clicking outside it.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const cells = useMemo(() => monthCells(view.getFullYear(), view.getMonth()), [view]);
  const selected = parseIso(value);

  function prevMonth() {
    setView((v) => new Date(v.getFullYear(), v.getMonth() - 1, 1));
  }
  function nextMonth() {
    setView((v) => new Date(v.getFullYear(), v.getMonth() + 1, 1));
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`flex w-full items-center justify-between gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none transition-colors focus:border-border-strong ${className}`}
      >
        <span className={value ? "text-foreground" : "text-muted"}>
          {value ? parseIso(value)?.toLocaleDateString() : placeholder}
        </span>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="h-4 w-4 text-muted"
        >
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-30 mt-2 w-72 rounded-xl border border-border bg-surface p-3 shadow-lg">
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={prevMonth}
              aria-label="Previous month"
              className="flex h-8 w-8 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-hover"
            >
              ‹
            </button>
            <p className="text-sm font-medium">
              {MONTHS[view.getMonth()]} {view.getFullYear()}
            </p>
            <button
              type="button"
              onClick={nextMonth}
              aria-label="Next month"
              className="flex h-8 w-8 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-hover"
            >
              ›
            </button>
          </div>

          <div className="mt-2 grid grid-cols-7 gap-1">
            {WEEKDAYS.map((d) => (
              <div key={d} className="py-1 text-center text-[11px] font-medium text-muted">
                {d}
              </div>
            ))}
            {cells.map((cell, i) => {
              const cellIso = iso(cell);
              const inMonth = cell.getMonth() === view.getMonth();
              const isSelected = selected && cellIso === value;
              return (
                <button
                  type="button"
                  key={i}
                  onClick={() => {
                    onChange(cellIso);
                    setOpen(false);
                  }}
                  className={`h-9 rounded-lg text-sm transition-colors ${
                    isSelected
                      ? "bg-foreground text-background"
                      : inMonth
                        ? "text-foreground hover:bg-surface-hover"
                        : "text-muted opacity-40 hover:bg-surface-hover"
                  }`}
                >
                  {cell.getDate()}
                </button>
              );
            })}
          </div>

          {value && (
            <button
              type="button"
              onClick={() => {
                onChange("");
                setOpen(false);
              }}
              className="mt-2 w-full rounded-lg py-1.5 text-xs font-medium text-muted transition-colors hover:bg-surface-hover"
            >
              Clear
            </button>
          )}
        </div>
      )}
    </div>
  );
}