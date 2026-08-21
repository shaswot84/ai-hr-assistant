"use client";

import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status";
import { Modal } from "@/components/modal";
import { ListSkeleton } from "@/components/loading";
import { EmptyState } from "@/components/empty-state";
import { useToast } from "@/components/toast";
import { api, ApiError } from "@/lib/api";
import type {
  CompanyHoliday,
  Department,
  LeaveRequestDetail,
  LeaveType,
  TeamMemberOutOfOffice,
} from "@/lib/types";

type Tab = "requests" | "types" | "calendar" | "holidays";

function formatDate(value: string) {
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function TabSwitch({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  const tabs: { key: Tab; label: string }[] = [
    { key: "requests", label: "Requests" },
    { key: "types", label: "Leave Types" },
    { key: "calendar", label: "Team Calendar" },
    { key: "holidays", label: "Company Holidays" },
  ];
  return (
    <div className="inline-flex rounded-lg border border-zinc-200 bg-zinc-50 p-0.5">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          onClick={() => onChange(t.key)}
          className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
            tab === t.key ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-500 hover:text-zinc-700"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function RequestsTab() {
  const { addToast } = useToast();
  const [requests, setRequests] = useState<LeaveRequestDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{
    request: LeaveRequestDetail;
    action: "approve" | "reject";
  } | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useMemo(
    () => () =>
      api
        .allLeaveRequests()
        .then(setRequests)
        .catch((err) =>
          setError(err instanceof ApiError ? err.detail : "Failed to load leave requests.")
        )
        .finally(() => setLoading(false)),
    []
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function decide() {
    if (!pending) return;
    setBusy(true);
    try {
      await api.decideLeaveRequest(pending.request.leave_request_id, pending.action);
      addToast(
        pending.action === "approve"
          ? "Leave request approved successfully."
          : "Leave request rejected.",
        "success"
      );
      setPending(null);
      refresh();
    } catch (err) {
      addToast(err instanceof ApiError ? err.detail : "Failed to record decision.", "error");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>;
  if (loading) return <ListSkeleton rows={5} />;
  if (requests.length === 0)
    return (
      <div className="card">
        <EmptyState
          title="No leave requests"
          description="Requests submitted by employees will show up here for review."
        />
      </div>
    );

  return (
    <>
      <div className="card overflow-hidden">
        <div className="table-scroll">
          <table className="w-full">
            <thead className="bg-zinc-50">
              <tr>
                <th className="table-th">Employee</th>
                <th className="table-th">Type</th>
                <th className="table-th">Dates</th>
                <th className="table-th">Duration</th>
                <th className="table-th">Status</th>
                <th className="table-th text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {requests.map((r) => (
                <tr key={r.leave_request_id} className="table-row">
                  <td className="table-td">
                    <div className="flex items-center gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-zinc-100 text-[13px] font-semibold text-blue-600">
                        {(r.employee_name ?? "?").charAt(0)}
                      </div>
                      <div>
                        <p className="font-medium text-zinc-900">{r.employee_name ?? "Unknown"}</p>
                        <p className="text-xs text-zinc-400">{r.request_number}</p>
                      </div>
                    </div>
                  </td>
                  <td className="table-td text-zinc-600">{r.leave_type_name}</td>
                  <td className="table-td text-xs text-zinc-500">
                    {formatDate(r.start_date)}
                    {r.start_date !== r.end_date ? ` – ${formatDate(r.end_date)}` : ""}
                  </td>
                  <td className="table-td text-xs text-zinc-600">
                    {r.is_half_day && r.half_day_period
                      ? `0.5 day (${r.half_day_period.toLowerCase()})`
                      : `${r.total_days} day(s)`}
                  </td>
                  <td className="table-td">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="table-td text-right">
                    {r.status === "PENDING" ? (
                      <div className="flex justify-end gap-3">
                        <button
                          type="button"
                          className="link text-emerald-600 hover:text-emerald-700 font-medium"
                          onClick={() => setPending({ request: r, action: "approve" })}
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          className="link text-red-600 hover:text-red-700"
                          onClick={() => setPending({ request: r, action: "reject" })}
                        >
                          Reject
                        </button>
                      </div>
                    ) : (
                      <span className="text-zinc-300">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Modal
        isOpen={pending !== null}
        onClose={() => setPending(null)}
        title={pending?.action === "approve" ? "Approve this leave request?" : "Reject this leave request?"}
        size="sm"
      >
        <p className="text-sm leading-relaxed text-zinc-600">
          {pending?.action === "approve"
            ? `${pending.request.employee_name ?? "The employee"} will be notified and ${
                pending.request.is_half_day ? "0.5" : pending.request.total_days
              } day(s) will be deducted from their balance.`
            : `${pending?.request.employee_name ?? "The employee"} will be notified their request was rejected.`}
        </p>
        <div className="mt-6 flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={() => setPending(null)} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className={
              pending?.action === "approve"
                ? "btn-primary bg-emerald-600 hover:bg-emerald-700"
                : "btn-primary bg-red-600 hover:bg-red-700"
            }
            disabled={busy}
            onClick={decide}
          >
            {busy ? "Saving…" : pending?.action === "approve" ? "Approve" : "Reject"}
          </button>
        </div>
      </Modal>
    </>
  );
}

const emptyTypeForm = {
  leaveName: "",
  description: "",
  defaultDays: "",
  requiresApproval: true,
  isPaid: true,
  maxConsecutiveDays: "",
};

function TypesTab() {
  const { addToast } = useToast();
  const [types, setTypes] = useState<LeaveType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState(emptyTypeForm);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const refresh = useMemo(
    () => () =>
      api
        .listLeaveTypes()
        .then(setTypes)
        .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load leave types."))
        .finally(() => setLoading(false)),
    []
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      await api.createLeaveType({
        leave_name: form.leaveName,
        description: form.description || null,
        default_days: form.defaultDays,
        requires_approval: form.requiresApproval,
        is_paid: form.isPaid,
        max_consecutive_days: form.maxConsecutiveDays ? Number(form.maxConsecutiveDays) : null,
      });
      addToast("Leave type created.", "success");
      setModalOpen(false);
      setForm(emptyTypeForm);
      refresh();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.detail : "Failed to create leave type.");
    } finally {
      setSubmitting(false);
    }
  }

  if (error) return <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>;

  return (
    <>
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => {
            setForm(emptyTypeForm);
            setModalOpen(true);
          }}
          className="btn-primary"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Add Leave Type
        </button>
      </div>

      {loading ? (
        <ListSkeleton rows={4} />
      ) : types.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No leave types yet"
            description="Create a leave type (e.g. Annual, Sick) so employees can request it."
            action={
              <button type="button" className="btn-primary" onClick={() => setModalOpen(true)}>
                Add Leave Type
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
                  <th className="table-th">Name</th>
                  <th className="table-th">Default Days</th>
                  <th className="table-th">Max Consecutive</th>
                  <th className="table-th">Paid</th>
                  <th className="table-th">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {types.map((t) => (
                  <tr key={t.leave_type_id} className="table-row">
                    <td className="table-td">
                      <p className="font-medium text-zinc-900">{t.leave_name}</p>
                      {t.description && <p className="text-xs text-zinc-400">{t.description}</p>}
                    </td>
                    <td className="table-td tabular-nums text-zinc-600">{t.default_days}</td>
                    <td className="table-td text-zinc-600">{t.max_consecutive_days ?? "—"}</td>
                    <td className="table-td text-zinc-600">{t.is_paid ? "Yes" : "No"}</td>
                    <td className="table-td">
                      <StatusBadge status={t.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal isOpen={modalOpen} onClose={() => setModalOpen(false)} title="Add Leave Type" size="md">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="label">Name *</label>
            <input
              required
              className="input"
              value={form.leaveName}
              onChange={(e) => setForm({ ...form, leaveName: e.target.value })}
              placeholder="Annual Leave"
            />
          </div>
          <div>
            <label className="label">Description</label>
            <input
              className="input"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Planned time off for rest and personal use."
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">Default Days *</label>
              <input
                required
                type="number"
                min="0"
                step="0.5"
                className="input"
                value={form.defaultDays}
                onChange={(e) => setForm({ ...form, defaultDays: e.target.value })}
              />
            </div>
            <div>
              <label className="label">Max Consecutive Days</label>
              <input
                type="number"
                min="1"
                className="input"
                value={form.maxConsecutiveDays}
                onChange={(e) => setForm({ ...form, maxConsecutiveDays: e.target.value })}
                placeholder="No limit"
              />
            </div>
          </div>
          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm text-zinc-700">
              <input
                type="checkbox"
                checked={form.isPaid}
                onChange={(e) => setForm({ ...form, isPaid: e.target.checked })}
              />
              Paid leave
            </label>
            <label className="flex items-center gap-2 text-sm text-zinc-700">
              <input
                type="checkbox"
                checked={form.requiresApproval}
                onChange={(e) => setForm({ ...form, requiresApproval: e.target.checked })}
              />
              Requires approval
            </label>
          </div>

          {formError && <p className="text-sm text-red-600">{formError}</p>}

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={() => setModalOpen(false)} className="btn-secondary">
              Cancel
            </button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? "Creating…" : "Create Leave Type"}
            </button>
          </div>
        </form>
      </Modal>
    </>
  );
}

function CalendarTab() {
  const [entries, setEntries] = useState<TeamMemberOutOfOffice[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [selectedDept, setSelectedDept] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.listDepartments(), api.teamOutOfOffice()])
      .then(([depts, outEntries]) => {
        setDepartments(depts);
        setEntries(outEntries);
      })
      .catch((err) =>
        setError(err instanceof ApiError ? err.detail : "Failed to load team absence calendar.")
      )
      .finally(() => setLoading(false));
  }, []);

  const filteredEntries = useMemo(() => {
    if (!selectedDept) return entries;
    return entries.filter((e) => e.department_id === selectedDept);
  }, [entries, selectedDept]);

  if (error) return <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>;
  if (loading) return <ListSkeleton rows={4} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-zinc-900">Department Out-of-Office Schedule</h3>
          <p className="text-xs text-zinc-500">Monitor employee absence overlaps to avoid understaffing</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-xs font-medium text-zinc-600">Filter Department:</label>
          <select
            className="input text-xs py-1"
            value={selectedDept}
            onChange={(e) => setSelectedDept(e.target.value)}
          >
            <option value="">All Departments</option>
            {departments.map((d) => (
              <option key={d.department_id} value={d.department_id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {filteredEntries.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No scheduled absences"
            description="No employees in this department are scheduled to be on leave."
          />
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="table-scroll">
            <table className="w-full">
              <thead className="bg-zinc-50">
                <tr>
                  <th className="table-th">Employee</th>
                  <th className="table-th">Department</th>
                  <th className="table-th">Leave Type</th>
                  <th className="table-th">Dates</th>
                  <th className="table-th">Duration</th>
                  <th className="table-th">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {filteredEntries.map((e) => (
                  <tr key={e.leave_request_id} className="table-row">
                    <td className="table-td font-medium text-zinc-900">{e.employee_name}</td>
                    <td className="table-td text-zinc-500">{e.department_name || "General"}</td>
                    <td className="table-td text-zinc-700">{e.leave_type_name}</td>
                    <td className="table-td text-xs text-zinc-600">
                      {formatDate(e.start_date)}
                      {e.start_date !== e.end_date ? ` – ${formatDate(e.end_date)}` : ""}
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
      )}
    </div>
  );
}

const emptyHolidayForm = {
  name: "",
  holidayDate: "",
  description: "",
  isRecurringYearly: true,
};

function HolidaysTab() {
  const { addToast } = useToast();
  const [holidays, setHolidays] = useState<CompanyHoliday[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState(emptyHolidayForm);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const refresh = useMemo(
    () => () =>
      api
        .listCompanyHolidays()
        .then(setHolidays)
        .catch((err) =>
          setError(err instanceof ApiError ? err.detail : "Failed to load company holidays.")
        )
        .finally(() => setLoading(false)),
    []
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      await api.createCompanyHoliday({
        name: form.name,
        holiday_date: form.holidayDate,
        description: form.description || null,
        is_recurring_yearly: form.isRecurringYearly,
      });
      addToast("Company holiday added successfully.", "success");
      setModalOpen(false);
      setForm(emptyHolidayForm);
      refresh();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.detail : "Failed to add company holiday.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(holidayId: string) {
    if (!confirm("Are you sure you want to remove this company holiday?")) return;
    setDeletingId(holidayId);
    try {
      await api.deleteCompanyHoliday(holidayId);
      addToast("Company holiday deleted.", "success");
      refresh();
    } catch (err) {
      addToast(err instanceof ApiError ? err.detail : "Failed to delete company holiday.", "error");
    } finally {
      setDeletingId(null);
    }
  }

  if (error) return <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>;

  return (
    <>
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-zinc-900">Official Company Holiday Calendar</h3>
          <p className="text-xs text-zinc-500">
            Holidays configured here will be excluded from employee working days calculation automatically.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setForm(emptyHolidayForm);
            setModalOpen(true);
          }}
          className="btn-primary"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Add Holiday
        </button>
      </div>

      {loading ? (
        <ListSkeleton rows={4} />
      ) : holidays.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No company holidays configured"
            description="Add official holidays (e.g. New Year's Day, Labor Day) so they are automatically deducted from leave calculations."
            action={
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  setForm(emptyHolidayForm);
                  setModalOpen(true);
                }}
              >
                Add Holiday
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
                  <th className="table-th">Holiday Name</th>
                  <th className="table-th">Date</th>
                  <th className="table-th">Description</th>
                  <th className="table-th">Recurring</th>
                  <th className="table-th text-right">Action</th>
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
                        <span className="inline-flex items-center text-blue-700 bg-blue-50 px-2 py-0.5 rounded text-[11px] font-medium border border-blue-100">
                          Annual (Recurring)
                        </span>
                      ) : (
                        "One-time"
                      )}
                    </td>
                    <td className="table-td text-right">
                      <button
                        type="button"
                        disabled={deletingId === h.holiday_id}
                        onClick={() => handleDelete(h.holiday_id)}
                        className="link text-red-600 hover:text-red-700 text-xs"
                      >
                        {deletingId === h.holiday_id ? "Deleting…" : "Delete"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        title="Add Official Company Holiday"
        size="md"
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div>
            <label className="label">Holiday Name *</label>
            <input
              required
              className="input"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. New Year's Day, Independence Day"
            />
          </div>
          <div>
            <label className="label">Date *</label>
            <input
              required
              type="date"
              className="input"
              value={form.holidayDate}
              onChange={(e) => setForm({ ...form, holidayDate: e.target.value })}
            />
          </div>
          <div>
            <label className="label">Description</label>
            <input
              className="input"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="e.g. National public holiday; office closed."
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="recurring"
              checked={form.isRecurringYearly}
              onChange={(e) => setForm({ ...form, isRecurringYearly: e.target.checked })}
              className="rounded border-zinc-300 text-blue-600 focus:ring-blue-500"
            />
            <label htmlFor="recurring" className="text-sm text-zinc-700 cursor-pointer">
              Repeats annually on this date
            </label>
          </div>

          {formError && <p className="text-sm text-red-600">{formError}</p>}

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={() => setModalOpen(false)} className="btn-secondary">
              Cancel
            </button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? "Adding…" : "Add Holiday"}
            </button>
          </div>
        </form>
      </Modal>
    </>
  );
}

export default function ManagerLeavePage() {
  const [tab, setTab] = useState<Tab>("requests");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Leave Management"
        description="Review employee leave requests, configure leave types, schedule company holidays, and view team out-of-office overlaps."
        meta={<TabSwitch tab={tab} onChange={setTab} />}
      />
      {tab === "requests" && <RequestsTab />}
      {tab === "types" && <TypesTab />}
      {tab === "calendar" && <CalendarTab />}
      {tab === "holidays" && <HolidaysTab />}
    </div>
  );
}
