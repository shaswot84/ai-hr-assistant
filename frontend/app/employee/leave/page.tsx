"use client";

import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status";
import { MetricCard } from "@/components/metric-card";
import { Modal } from "@/components/modal";
import { ListSkeleton, StatsSkeleton } from "@/components/loading";
import { EmptyState } from "@/components/empty-state";
import { useToast } from "@/components/toast";
import { api, ApiError } from "@/lib/api";
import type {
  CompanyHoliday,
  LeaveBalance,
  LeaveRequest,
  LeaveType,
  TeamMemberOutOfOffice,
  WorkingDaysCalculation,
} from "@/lib/types";

type EmployeeTab = "my_requests" | "team_calendar" | "holidays";

const emptyForm = {
  leaveTypeId: "",
  startDate: "",
  endDate: "",
  isHalfDay: false,
  halfDayPeriod: "MORNING" as "MORNING" | "AFTERNOON",
  reason: "",
};

function formatDate(value: string) {
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function todayISO() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function BalanceGrid({ balances, loading }: { balances: LeaveBalance[]; loading: boolean }) {
  if (loading) return <StatsSkeleton items={balances.length || 4} />;
  if (balances.length === 0) return null;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {balances.map((b) => (
        <MetricCard
          key={b.leave_type_id}
          label={b.leave_type_name}
          value={b.remaining_days}
          sub={`of ${b.allocated_days} allocated · ${b.used_days} used`}
        />
      ))}
    </div>
  );
}

function RequestLeaveModal({
  isOpen,
  onClose,
  leaveTypes,
  onCreated,
}: {
  isOpen: boolean;
  onClose: () => void;
  leaveTypes: LeaveType[];
  onCreated: () => void;
}) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Request Leave" size="md">
      {isOpen && <RequestLeaveForm leaveTypes={leaveTypes} onClose={onClose} onCreated={onCreated} />}
    </Modal>
  );
}

function RequestLeaveForm({
  leaveTypes,
  onClose,
  onCreated,
}: {
  leaveTypes: LeaveType[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const { addToast } = useToast();
  const [form, setForm] = useState({
    ...emptyForm,
    leaveTypeId: leaveTypes[0]?.leave_type_id ?? "",
  });
  const [calculation, setCalculation] = useState<WorkingDaysCalculation | null>(null);
  const [calcLoading, setCalcLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Live working days calculation
  useEffect(() => {
    if (!form.startDate || (!form.isHalfDay && !form.endDate)) {
      setCalculation(null);
      return;
    }
    const end = form.isHalfDay ? form.startDate : form.endDate;
    if (end < form.startDate) {
      setCalculation(null);
      return;
    }

    setCalcLoading(true);
    api
      .calculateWorkingDays({
        start_date: form.startDate,
        end_date: end,
        is_half_day: form.isHalfDay,
        half_day_period: form.isHalfDay ? form.halfDayPeriod : undefined,
      })
      .then((res) => {
        setCalculation(res);
        setError(null);
      })
      .catch((err) => {
        setCalculation(null);
        if (err instanceof ApiError) setError(err.detail);
      })
      .finally(() => setCalcLoading(false));
  }, [form.startDate, form.endDate, form.isHalfDay, form.halfDayPeriod]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.requestLeave({
        leave_type_id: form.leaveTypeId,
        start_date: form.startDate,
        end_date: form.isHalfDay ? form.startDate : form.endDate,
        is_half_day: form.isHalfDay,
        half_day_period: form.isHalfDay ? form.halfDayPeriod : null,
        reason: form.reason || null,
      });
      addToast("Leave request submitted successfully.", "success");
      onClose();
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to submit leave request.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="label">Leave Type *</label>
        <select
          required
          className="input"
          value={form.leaveTypeId}
          onChange={(e) => setForm({ ...form, leaveTypeId: e.target.value })}
        >
          {leaveTypes.map((t) => (
            <option key={t.leave_type_id} value={t.leave_type_id}>
              {t.leave_name} {!t.is_paid ? "(Unpaid)" : ""}
            </option>
          ))}
        </select>
      </div>

      {/* Half Day Option */}
      <div className="flex items-center justify-between rounded-lg border border-zinc-200 bg-zinc-50 p-3">
        <div>
          <span className="text-sm font-medium text-zinc-900">Half-Day Leave</span>
          <p className="text-xs text-zinc-500">Deduct 0.5 days for morning or afternoon absence</p>
        </div>
        <label className="relative inline-flex cursor-pointer items-center">
          <input
            type="checkbox"
            className="sr-only peer"
            checked={form.isHalfDay}
            onChange={(e) => {
              const checked = e.target.checked;
              setForm({
                ...form,
                isHalfDay: checked,
                endDate: checked ? form.startDate : form.endDate,
              });
            }}
          />
          <div className="w-11 h-6 bg-zinc-300 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-zinc-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
        </label>
      </div>

      {form.isHalfDay ? (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Date *</label>
            <input
              required
              type="date"
              min={todayISO()}
              className="input"
              value={form.startDate}
              onChange={(e) =>
                setForm({ ...form, startDate: e.target.value, endDate: e.target.value })
              }
            />
          </div>
          <div>
            <label className="label">Period *</label>
            <select
              className="input"
              value={form.halfDayPeriod}
              onChange={(e) =>
                setForm({
                  ...form,
                  halfDayPeriod: e.target.value as "MORNING" | "AFTERNOON",
                })
              }
            >
              <option value="MORNING">Morning (First Half)</option>
              <option value="AFTERNOON">Afternoon (Second Half)</option>
            </select>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Start Date *</label>
            <input
              required
              type="date"
              min={todayISO()}
              className="input"
              value={form.startDate}
              onChange={(e) => setForm({ ...form, startDate: e.target.value })}
            />
          </div>
          <div>
            <label className="label">End Date *</label>
            <input
              required
              type="date"
              min={form.startDate || todayISO()}
              className="input"
              value={form.endDate}
              onChange={(e) => setForm({ ...form, endDate: e.target.value })}
            />
          </div>
        </div>
      )}

      {/* Live Working Days Calculation Preview */}
      {calcLoading ? (
        <div className="text-xs text-zinc-500 animate-pulse">Calculating working days…</div>
      ) : calculation ? (
        <div className="rounded-md border border-emerald-200 bg-emerald-50/70 p-3 text-xs text-emerald-900 space-y-1">
          <div className="flex items-center justify-between font-semibold">
            <span>Working Days Deducted:</span>
            <span className="text-sm font-bold text-emerald-800">
              {calculation.total_working_days} {Number(calculation.total_working_days) === 1 ? "day" : "days"}
            </span>
          </div>
          <div className="text-zinc-600 flex gap-3 text-[11px] pt-1">
            <span>📅 {calculation.calendar_days} calendar days</span>
            {calculation.weekend_days > 0 && <span>🏖️ {calculation.weekend_days} weekend days excluded</span>}
            {calculation.holiday_days > 0 && <span>🎉 {calculation.holiday_days} public holiday excluded</span>}
          </div>
          {calculation.holidays_in_range?.length > 0 && (
            <div className="text-[11px] text-zinc-500 pt-1">
              Official Holidays in Range: {calculation.holidays_in_range.map((h) => h.name).join(", ")}
            </div>
          )}
        </div>
      ) : null}

      <div>
        <label className="label">Reason</label>
        <textarea
          className="input"
          rows={3}
          value={form.reason}
          onChange={(e) => setForm({ ...form, reason: e.target.value })}
          placeholder="Optional context for your manager…"
        />
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="flex justify-end gap-3 pt-2">
        <button type="button" onClick={onClose} className="btn-secondary">
          Cancel
        </button>
        <button type="submit" disabled={submitting} className="btn-primary">
          {submitting ? "Submitting…" : "Submit Request"}
        </button>
      </div>
    </form>
  );
}

function CancelButton({ request, onCancelled }: { request: LeaveRequest; onCancelled: () => void }) {
  const { addToast } = useToast();
  const [busy, setBusy] = useState(false);

  async function handleCancel() {
    setBusy(true);
    try {
      await api.cancelLeaveRequest(request.leave_request_id);
      addToast("Leave request cancelled.", "success");
      onCancelled();
    } catch (err) {
      addToast(err instanceof ApiError ? err.detail : "Failed to cancel request.", "error");
    } finally {
      setBusy(false);
    }
  }

  if (request.status !== "PENDING") return <span className="text-zinc-300">—</span>;

  return (
    <button type="button" disabled={busy} onClick={handleCancel} className="link text-red-600 hover:text-red-700">
      {busy ? "Cancelling…" : "Cancel"}
    </button>
  );
}

function TeamCalendarTab() {
  const [entries, setEntries] = useState<TeamMemberOutOfOffice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .teamOutOfOffice()
      .then(setEntries)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load team calendar."))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>;
  if (loading) return <ListSkeleton rows={4} />;

  if (entries.length === 0) {
    return (
      <div className="card">
        <EmptyState
          title="Everyone is in the office"
          description="No upcoming scheduled absences or out-of-office leaves in your team."
        />
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="p-4 border-b border-zinc-100 bg-zinc-50/60 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-zinc-900">Upcoming Team Out-of-Office</h3>
          <p className="text-xs text-zinc-500">Upcoming scheduled absences to help coordinate staffing</p>
        </div>
        <span className="text-xs font-medium bg-blue-50 text-blue-700 px-2.5 py-1 rounded-full border border-blue-100">
          {entries.length} scheduled
        </span>
      </div>
      <div className="table-scroll">
        <table className="w-full">
          <thead className="bg-zinc-50">
            <tr>
              <th className="table-th">Colleague</th>
              <th className="table-th">Department</th>
              <th className="table-th">Leave Type</th>
              <th className="table-th">Dates</th>
              <th className="table-th">Duration</th>
              <th className="table-th">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {entries.map((e) => (
              <tr key={e.leave_request_id} className="table-row">
                <td className="table-td font-medium text-zinc-900">{e.employee_name}</td>
                <td className="table-td text-zinc-500">{e.department_name || "General"}</td>
                <td className="table-td text-zinc-700">{e.leave_type_name}</td>
                <td className="table-td text-xs text-zinc-600">
                  {formatDate(e.start_date)} {e.start_date !== e.end_date ? `– ${formatDate(e.end_date)}` : ""}
                </td>
                <td className="table-td text-xs text-zinc-600">
                  {e.is_half_day && e.half_day_period
                    ? `0.5 day (${e.half_day_period.toLowerCase()})`
                    : `${e.total_days} day(s)`}
                </td>
                <td className="table-td">
                  <StatusBadge status={e.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HolidaysTab() {
  const [holidays, setHolidays] = useState<CompanyHoliday[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listCompanyHolidays()
      .then(setHolidays)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load company holidays."))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>;
  if (loading) return <ListSkeleton rows={4} />;

  if (holidays.length === 0) {
    return (
      <div className="card">
        <EmptyState
          title="No company holidays listed"
          description="Official office closures and public holidays will be listed here."
        />
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="p-4 border-b border-zinc-100 bg-zinc-50/60">
        <h3 className="text-sm font-semibold text-zinc-900">Official Company Holidays</h3>
        <p className="text-xs text-zinc-500">Official closures are automatically deducted from leave requests</p>
      </div>
      <div className="table-scroll">
        <table className="w-full">
          <thead className="bg-zinc-50">
            <tr>
              <th className="table-th">Holiday</th>
              <th className="table-th">Date</th>
              <th className="table-th">Description</th>
              <th className="table-th">Recurring</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {holidays.map((h) => (
              <tr key={h.holiday_id} className="table-row">
                <td className="table-td font-medium text-zinc-900">{h.name}</td>
                <td className="table-td text-xs text-zinc-700">{formatDate(h.holiday_date)}</td>
                <td className="table-td text-xs text-zinc-500">{h.description || "—"}</td>
                <td className="table-td text-xs text-zinc-500">
                  {h.is_recurring_yearly ? (
                    <span className="inline-flex items-center text-blue-700 bg-blue-50 px-2 py-0.5 rounded text-[11px] font-medium">
                      Every year
                    </span>
                  ) : (
                    "One-time"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function EmployeeLeavePage() {
  const [tab, setTab] = useState<EmployeeTab>("my_requests");
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([]);
  const [balances, setBalances] = useState<LeaveBalance[]>([]);
  const [requests, setRequests] = useState<LeaveRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const refresh = useMemo(
    () => () =>
      Promise.all([api.listLeaveTypes(), api.myLeaveBalance(), api.myLeaveRequests()])
        .then(([types, bal, reqs]) => {
          setLeaveTypes(types);
          setBalances(bal);
          setRequests(reqs);
        })
        .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load leave data."))
        .finally(() => setLoading(false)),
    []
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (error) return <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Leave"
        description="Check your balance, submit requests, and check team out-of-office schedules."
        actions={
          <button
            type="button"
            disabled={loading || leaveTypes.length === 0}
            onClick={() => setModalOpen(true)}
            className="btn-primary"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Request Leave
          </button>
        }
      />

      <BalanceGrid balances={balances} loading={loading} />

      {/* Tabs */}
      <div className="flex border-b border-zinc-200 space-x-6">
        <button
          type="button"
          onClick={() => setTab("my_requests")}
          className={`pb-3 text-sm font-medium transition-colors border-b-2 ${
            tab === "my_requests"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-zinc-500 hover:text-zinc-700"
          }`}
        >
          My Requests ({requests.length})
        </button>
        <button
          type="button"
          onClick={() => setTab("team_calendar")}
          className={`pb-3 text-sm font-medium transition-colors border-b-2 ${
            tab === "team_calendar"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-zinc-500 hover:text-zinc-700"
          }`}
        >
          Team Out-of-Office
        </button>
        <button
          type="button"
          onClick={() => setTab("holidays")}
          className={`pb-3 text-sm font-medium transition-colors border-b-2 ${
            tab === "holidays"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-zinc-500 hover:text-zinc-700"
          }`}
        >
          Company Holidays
        </button>
      </div>

      {tab === "my_requests" && (
        <>
          {loading ? (
            <ListSkeleton rows={4} />
          ) : requests.length === 0 ? (
            <div className="card">
              <EmptyState
                title="No leave requests yet"
                description="Requests you submit will show up here so you can track their status."
                action={
                  <button type="button" className="btn-primary" onClick={() => setModalOpen(true)}>
                    Request Leave
                  </button>
                }
              />
            </div>
          ) : (
            <div className="card overflow-hidden">
              <div className="table-scroll">
                <table className="w-full">
                  <thead className="bg-zinc-50">
                    <tr>
                      <th className="table-th">Reference</th>
                      <th className="table-th">Type</th>
                      <th className="table-th">Dates</th>
                      <th className="table-th">Days</th>
                      <th className="table-th">Status</th>
                      <th className="table-th text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100">
                    {requests.map((r) => (
                      <tr key={r.leave_request_id} className="table-row">
                        <td className="table-td font-medium text-zinc-900">{r.request_number}</td>
                        <td className="table-td text-zinc-600">{r.leave_type_name}</td>
                        <td className="table-td text-xs text-zinc-500">
                          {formatDate(r.start_date)}
                          {r.start_date !== r.end_date ? ` – ${formatDate(r.end_date)}` : ""}
                        </td>
                        <td className="table-td tabular-nums text-zinc-600">
                          {r.is_half_day && r.half_day_period
                            ? `0.5 (${r.half_day_period.toLowerCase()})`
                            : r.total_days}
                        </td>
                        <td className="table-td">
                          <StatusBadge status={r.status} />
                        </td>
                        <td className="table-td text-right">
                          <CancelButton request={r} onCancelled={refresh} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {tab === "team_calendar" && <TeamCalendarTab />}
      {tab === "holidays" && <HolidaysTab />}

      <RequestLeaveModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        leaveTypes={leaveTypes}
        onCreated={refresh}
      />
    </div>
  );
}
