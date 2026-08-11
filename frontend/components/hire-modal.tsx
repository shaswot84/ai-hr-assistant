"use client";

import { useEffect, useState } from "react";
import { Modal } from "@/components/modal";
import { api, ApiError } from "@/lib/api";
import type { Department, Designation, Employee } from "@/lib/types";

/**
 * Shared hire-handoff modal: converts a shortlisted candidate into an
 * employee (employee code, department → designation, manager, joining date).
 * Used from the application detail page and the applications list.
 *
 * The parent is responsible for toasts and refreshing its data via `onHired`.
 */
export function HireModal({
  applicationId,
  candidateName,
  onClose,
  onHired,
}: {
  applicationId: string;
  candidateName: string;
  onClose: () => void;
  onHired: (employee: Employee) => void;
}) {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [designations, setDesignations] = useState<Designation[]>([]);
  const [managers, setManagers] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [employeeCode, setEmployeeCode] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [designationId, setDesignationId] = useState("");
  const [managerId, setManagerId] = useState("");
  const [joiningDate, setJoiningDate] = useState(() => new Date().toISOString().slice(0, 10));

  // Load the org pickers (departments, designations, active employees as managers).
  useEffect(() => {
    Promise.all([api.listDepartments(), api.listDesignations(), api.listEmployees()])
      .then(([depts, desigs, emps]) => {
        setDepartments(depts);
        setDesignations(desigs);
        setManagers(emps.filter((e) => e.employment_status === "ACTIVE"));
        if (depts[0]) setDepartmentId(depts[0].department_id);
      })
      .catch((err) =>
        setError(err instanceof ApiError ? err.detail : "Failed to load organization data.")
      )
      .finally(() => setLoading(false));
  }, []);

  // Designations offered depend on the chosen department.
  const deptDesignations = designations.filter((d) => d.department_id === departmentId);

  function handleDepartmentChange(id: string) {
    setDepartmentId(id);
    setDesignationId(""); // a designation belongs to exactly one department
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const employee = await api.hireCandidate(applicationId, {
        employee_code: employeeCode,
        department_id: departmentId,
        designation_id: designationId,
        manager_employee_id: managerId || null,
        joining_date: joiningDate,
      });
      onHired(employee);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to hire candidate.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal isOpen onClose={onClose} title={`Hire ${candidateName}`} size="lg">
      {loading ? (
        <p className="py-6 text-center text-sm text-zinc-400">Loading organization data…</p>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <p className="text-sm leading-relaxed text-zinc-600">
            This creates an employee record for {candidateName} on their existing account, grants
            them access to the employee portal, and automatically withdraws their other open
            applications. Their application history is kept.
          </p>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">Employee Code *</label>
              <input
                required
                className="input"
                value={employeeCode}
                onChange={(e) => setEmployeeCode(e.target.value)}
                placeholder="EMP-042"
              />
            </div>
            <div>
              <label className="label">Joining Date *</label>
              <input
                required
                type="date"
                className="input"
                value={joiningDate}
                onChange={(e) => setJoiningDate(e.target.value)}
              />
            </div>
            <div>
              <label className="label">Department *</label>
              <select
                required
                className="input"
                value={departmentId}
                onChange={(e) => handleDepartmentChange(e.target.value)}
              >
                <option value="">Select department…</option>
                {departments.map((d) => (
                  <option key={d.department_id} value={d.department_id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Designation *</label>
              <select
                required
                className="input"
                value={designationId}
                onChange={(e) => setDesignationId(e.target.value)}
              >
                <option value="">Select designation…</option>
                {deptDesignations.map((d) => (
                  <option key={d.designation_id} value={d.designation_id}>
                    {d.title}
                  </option>
                ))}
              </select>
            </div>
            <div className="col-span-2">
              <label className="label">Manager</label>
              <select
                className="input"
                value={managerId}
                onChange={(e) => setManagerId(e.target.value)}
              >
                <option value="">No manager</option>
                {managers.map((m) => (
                  <option key={m.employee_id} value={m.employee_id}>
                    {m.first_name} {m.last_name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? "Hiring…" : "Hire Candidate"}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
