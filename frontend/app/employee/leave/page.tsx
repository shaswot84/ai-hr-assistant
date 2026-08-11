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
import type { LeaveBalance, LeaveRequest, LeaveType } from "@/lib/types";

const emptyForm = { leaveTypeId: "", startDate: "", endDate: "", reason: "" };

function formatDate(value: string) {
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
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
      {/* Rendered fresh each time the modal opens, so its form state starts
          clean without syncing via an effect. */}
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
  const [form, setForm] = useState({ ...emptyForm, leaveTypeId: leaveTypes[0]?.leave_type_id ?? "" });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.requestLeave({
        leave_type_id: form.leaveTypeId,
        start_date: form.startDate,
        end_date: form.endDate,
        reason: form.reason || null,
      });
      addToast("Leave request submitted.", "success");
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
                {t.leave_name}
              </option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Start Date *</label>
            <input
              required
              type="date"
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
              className="input"
              value={form.endDate}
              onChange={(e) => setForm({ ...form, endDate: e.target.value })}
            />
          </div>
        </div>
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

export default function EmployeeLeavePage() {
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
        description="Check your balance and submit or track leave requests."
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
                      {formatDate(r.start_date)} – {formatDate(r.end_date)}
                    </td>
                    <td className="table-td tabular-nums text-zinc-600">{r.total_days}</td>
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

      <RequestLeaveModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        leaveTypes={leaveTypes}
        onCreated={refresh}
      />
    </div>
  );
}
