"use client";

import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status";
import { Modal } from "@/components/modal";
import { ListSkeleton } from "@/components/loading";
import { EmptyState } from "@/components/empty-state";
import { Pagination } from "@/components/pagination";
import { SortableTh, Th, toggleSort, type SortState } from "@/components/table";
import { OrgChart } from "@/components/org-chart";
import { useToast } from "@/components/toast";
import { api, ApiError } from "@/lib/api";
import type { Department, Designation, Employee, EmploymentStatus } from "@/lib/types";

const PAGE_SIZE = 10;

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

/** Full name helper used across the table and the modals. */
function fullName(e: Employee) {
  return `${e.first_name} ${e.last_name}`.trim();
}

/** Client-side sort for the employee table (name / department / joined / status). */
function sortEmployees(list: Employee[], sort: SortState): Employee[] {
  const dir = sort.dir === "asc" ? 1 : -1;
  const sorted = [...list];
  switch (sort.key) {
    case "name":
      sorted.sort((a, b) => fullName(a).localeCompare(fullName(b)) * dir);
      break;
    case "department":
      sorted.sort((a, b) => (a.department_name ?? "").localeCompare(b.department_name ?? "") * dir);
      break;
    case "joined":
      sorted.sort(
        (a, b) => (new Date(a.joining_date).getTime() - new Date(b.joining_date).getTime()) * dir
      );
      break;
    case "status":
      sorted.sort((a, b) => a.employment_status.localeCompare(b.employment_status) * dir);
      break;
  }
  return sorted;
}

// ---- employee add/edit form ---------------------------------------------

interface EmployeeForm {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  employee_code: string;
  department_id: string;
  designation_id: string;
  manager_employee_id: string;
  joining_date: string;
  password: string;
  employment_status: EmploymentStatus;
}

const emptyForm: EmployeeForm = {
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
  employee_code: "",
  department_id: "",
  designation_id: "",
  manager_employee_id: "",
  joining_date: todayIso(),
  password: "",
  employment_status: "ACTIVE",
};

function employeeToForm(e: Employee): EmployeeForm {
  return {
    first_name: e.first_name,
    last_name: e.last_name,
    email: e.email,
    phone: e.phone ?? "",
    employee_code: e.employee_code,
    department_id: e.department_id,
    designation_id: e.designation_id,
    manager_employee_id: e.manager_employee_id ?? "",
    joining_date: e.joining_date,
    password: "",
    employment_status: e.employment_status,
  };
}

/** Modal for creating (HR-provided credentials) or editing an employee. */
function EmployeeFormModal({
  isOpen,
  onClose,
  employee,
  initialManagerId,
  departments,
  designations,
  managers,
  onSubmit,
}: {
  isOpen: boolean;
  onClose: () => void;
  employee: Employee | null; // null = create mode
  initialManagerId?: string | null;
  departments: Department[];
  designations: Designation[];
  managers: Employee[];
  onSubmit: (payload: {
    form: EmployeeForm;
    employeeId: string | null;
  }) => Promise<void>;
}) {
  const [form, setForm] = useState<EmployeeForm>(() => {
    if (employee) return employeeToForm(employee);
    return {
      ...emptyForm,
      manager_employee_id: initialManagerId ?? "",
    };
  });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Designations offered depend on the chosen department.
  const deptDesignations = useMemo(
    () =>
      form.department_id
        ? designations.filter((d) => d.department_id === form.department_id)
        : designations,
    [designations, form.department_id]
  );

  function handleDepartmentChange(departmentId: string) {
    // A designation belongs to exactly one department, so clear the stale one.
    setForm((f) => ({ ...f, department_id: departmentId, designation_id: "" }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await onSubmit({ form, employeeId: employee?.employee_id ?? null });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={employee ? "Edit Employee" : "Add Employee"} size="lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">First Name *</label>
            <input
              required
              className="input"
              value={form.first_name}
              onChange={(e) => setForm({ ...form, first_name: e.target.value })}
              placeholder="Jane"
            />
          </div>
          <div>
            <label className="label">Last Name *</label>
            <input
              required
              className="input"
              value={form.last_name}
              onChange={(e) => setForm({ ...form, last_name: e.target.value })}
              placeholder="Doe"
            />
          </div>
          <div>
            <label className="label">Work Email *</label>
            <input
              required
              type="email"
              className="input"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              placeholder="jane.doe@company.com"
            />
          </div>
          <div>
            <label className="label">Employee Code *</label>
            <input
              required
              className="input"
              value={form.employee_code}
              onChange={(e) => setForm({ ...form, employee_code: e.target.value })}
              placeholder="EMP-042"
            />
          </div>
          <div>
            <label className="label">Phone</label>
            <input
              className="input"
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
              placeholder="+91 90000 00000"
            />
          </div>
          <div>
            <label className="label">Department *</label>
            <select
              required
              className="input"
              value={form.department_id}
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
              value={form.designation_id}
              onChange={(e) => setForm({ ...form, designation_id: e.target.value })}
            >
              <option value="">Select designation…</option>
              {deptDesignations.map((d) => (
                <option key={d.designation_id} value={d.designation_id}>
                  {d.title}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Manager</label>
            <select
              className="input"
              value={form.manager_employee_id}
              onChange={(e) => setForm({ ...form, manager_employee_id: e.target.value })}
            >
              <option value="">No manager</option>
              {managers.map((m) => (
                <option key={m.employee_id} value={m.employee_id}>
                  {fullName(m)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Joining Date *</label>
            <input
              required
              type="date"
              className="input"
              value={form.joining_date}
              onChange={(e) => setForm({ ...form, joining_date: e.target.value })}
            />
          </div>
          {employee ? (
            <div>
              <label className="label">Employment Status</label>
              <select
                className="input"
                value={form.employment_status}
                onChange={(e) =>
                  setForm({ ...form, employment_status: e.target.value as EmploymentStatus })
                }
              >
                <option value="ACTIVE">Active</option>
                <option value="INACTIVE">Inactive</option>
              </select>
            </div>
          ) : (
            <div>
              <label className="label">Temporary Password *</label>
              <input
                required
                type="password"
                className="input"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="Min 8 characters — give this to the employee"
              />
            </div>
          )}
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex justify-end gap-3 pt-2">
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button type="submit" disabled={submitting} className="btn-primary">
            {submitting ? "Saving…" : employee ? "Save Changes" : "Add Employee"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ---- employees tab -------------------------------------------------------

function EmployeesTab() {
  const { addToast } = useToast();
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [designations, setDesignations] = useState<Designation[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [deptFilter, setDeptFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sort, setSort] = useState<SortState>({ key: "name", dir: "asc" });
  const [page, setPage] = useState(1);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Employee | null>(null);
  const [deactivating, setDeactivating] = useState<Employee | null>(null);
  const [deactivatingBusy, setDeactivatingBusy] = useState(false);

  const refresh = useMemo(
    () => () =>
      Promise.all([
        api.listDepartments().catch(() => [] as Department[]),
        api.listDesignations().catch(() => [] as Designation[]),
        api.listEmployees().catch(() => [] as Employee[]),
      ])
        .then(([depts, desigs, emps]) => {
          setDepartments(depts);
          setDesignations(desigs);
          setEmployees(emps);
        })
        .finally(() => setLoading(false)),
    []
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  /** Save a create/update payload, then refresh the directory. */
  async function handleSubmit({
    form,
    employeeId,
  }: {
    form: EmployeeForm;
    employeeId: string | null;
  }) {
    if (employeeId) {
      await api.updateEmployee(employeeId, {
        first_name: form.first_name,
        last_name: form.last_name,
        phone: form.phone || null,
        department_id: form.department_id,
        designation_id: form.designation_id,
        manager_employee_id: form.manager_employee_id || null,
        joining_date: form.joining_date,
        employment_status: form.employment_status,
      });
      addToast("Employee updated.", "success");
    } else {
      await api.createEmployee({
        first_name: form.first_name,
        last_name: form.last_name,
        email: form.email,
        phone: form.phone || null,
        employee_code: form.employee_code,
        department_id: form.department_id,
        designation_id: form.designation_id,
        manager_employee_id: form.manager_employee_id || null,
        joining_date: form.joining_date,
        password: form.password,
      });
      addToast("Employee added — they can now sign in.", "success");
    }
    setFormOpen(false);
    await refresh();
  }

  async function handleDeactivate() {
    if (!deactivating) return;
    setDeactivatingBusy(true);
    try {
      await api.deactivateEmployee(deactivating.employee_id);
      addToast(`${fullName(deactivating)} deactivated — login revoked.`, "success");
      setDeactivating(null);
      await refresh();
    } catch (err) {
      addToast(err instanceof ApiError ? err.detail : "Failed to deactivate employee.", "error");
      setDeactivating(null);
    } finally {
      setDeactivatingBusy(false);
    }
  }

  // Client-side filtering (search + department + status), mirroring the
  // vacancies page; sorting + paging happen on the filtered list.
  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    const searched = employees.filter(
      (e) =>
        fullName(e).toLowerCase().includes(q) ||
        e.email.toLowerCase().includes(q) ||
        e.employee_code.toLowerCase().includes(q)
    );
    const byDept = deptFilter ? searched.filter((e) => e.department_id === deptFilter) : searched;
    const byStatus = statusFilter ? byDept.filter((e) => e.employment_status === statusFilter) : byDept;
    return sortEmployees(byStatus, sort);
  }, [employees, search, deptFilter, statusFilter, sort]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const curPage = Math.min(page, pageCount);
  const pageRows = filtered.slice((curPage - 1) * PAGE_SIZE, curPage * PAGE_SIZE);

  function handleSort(key: string) {
    setSort((s) => toggleSort(s, key));
    setPage(1);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        {/* Search */}
        <div className="relative flex-1">
          <svg
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            type="text"
            placeholder="Search by name, email, or code…"
            className="input pl-9"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
        </div>
        {/* Filters */}
        <select
          aria-label="Filter by department"
          className="input sm:w-48"
          value={deptFilter}
          onChange={(e) => {
            setDeptFilter(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All departments</option>
          {departments.map((d) => (
            <option key={d.department_id} value={d.department_id}>
              {d.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter by status"
          className="input sm:w-40"
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All statuses</option>
          <option value="ACTIVE">Active</option>
          <option value="INACTIVE">Inactive</option>
        </select>
        <button
          type="button"
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
          className="btn-primary shrink-0"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Add Employee
        </button>
      </div>

      {loading ? (
        <ListSkeleton rows={6} />
      ) : filtered.length === 0 ? (
        <div className="card">
          <EmptyState
            title={search || deptFilter || statusFilter ? "No matching employees" : "No employees yet"}
            description={
              search || deptFilter || statusFilter
                ? "Nothing matches your filters. Try widening the search."
                : "Add your first employee to start building the org directory."
            }
            action={
              !search && !deptFilter && !statusFilter ? (
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => {
                    setEditing(null);
                    setFormOpen(true);
                  }}
                >
                  Add Employee
                </button>
              ) : undefined
            }
          />
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="table-scroll max-h-[560px]">
            <table className="w-full">
              <thead className="bg-zinc-50">
                <tr className="group">
                  <SortableTh sortKey="name" sort={sort} onSort={handleSort}>
                    Employee
                  </SortableTh>
                  <Th className="hidden lg:table-cell">Code</Th>
                  <SortableTh sortKey="department" sort={sort} onSort={handleSort} className="hidden md:table-cell">
                    Department
                  </SortableTh>
                  <Th className="hidden lg:table-cell">Designation</Th>
                  <Th className="hidden xl:table-cell">Manager</Th>
                  <SortableTh sortKey="joined" sort={sort} onSort={handleSort} className="hidden sm:table-cell">
                    Joined
                  </SortableTh>
                  <SortableTh sortKey="status" sort={sort} onSort={handleSort}>
                    Status
                  </SortableTh>
                  <Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {pageRows.map((e) => (
                  <tr key={e.employee_id} className="table-row">
                    <td className="table-td">
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-50 text-[13px] font-semibold text-blue-600">
                          {e.first_name.charAt(0)}
                          {e.last_name.charAt(0)}
                        </div>
                        <div className="min-w-0">
                          <p className="font-medium text-zinc-900">{fullName(e)}</p>
                          <p className="truncate text-xs text-zinc-400">{e.email}</p>
                        </div>
                      </div>
                    </td>
                    <td className="table-td hidden font-mono text-xs text-zinc-500 lg:table-cell">
                      {e.employee_code}
                    </td>
                    <td className="table-td hidden text-zinc-500 md:table-cell">
                      {e.department_name ?? "—"}
                    </td>
                    <td className="table-td hidden text-zinc-500 lg:table-cell">
                      {e.designation_title ?? "—"}
                    </td>
                    <td className="table-td hidden text-zinc-500 xl:table-cell">
                      {e.manager_name ?? "—"}
                    </td>
                    <td className="table-td hidden text-xs text-zinc-500 sm:table-cell">
                      {new Date(e.joining_date).toLocaleDateString("en-US", {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}
                    </td>
                    <td className="table-td">
                      <StatusBadge status={e.employment_status} />
                    </td>
                    <td className="table-td text-right">
                      <div className="inline-flex items-center gap-3">
                        <button
                          type="button"
                          className="link"
                          onClick={() => {
                            setEditing(e);
                            setFormOpen(true);
                          }}
                        >
                          Edit
                        </button>
                        {e.employment_status === "ACTIVE" && (
                          <button
                            type="button"
                            className="link text-red-600 hover:text-red-700"
                            onClick={() => setDeactivating(e)}
                          >
                            Deactivate
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={curPage} pageSize={PAGE_SIZE} total={filtered.length} onPage={setPage} />
        </div>
      )}

      {/* Add / edit modal — conditionally mounted so each open starts fresh */}
      {formOpen && (
        <EmployeeFormModal
          isOpen
          onClose={() => setFormOpen(false)}
          employee={editing}
          departments={departments}
          designations={designations}
          managers={employees.filter(
            (e) => e.employment_status === "ACTIVE" && e.employee_id !== editing?.employee_id
          )}
          onSubmit={handleSubmit}
        />
      )}

      {/* Deactivate confirmation */}
      {deactivating && (
        <Modal isOpen onClose={() => !deactivatingBusy && setDeactivating(null)} title="Deactivate employee?" size="sm">
          <div className="space-y-4">
            <p className="text-sm leading-relaxed text-zinc-600">
              <span className="font-medium text-zinc-900">{fullName(deactivating)}</span> will be
              marked <span className="font-medium">inactive</span> and their login access will be{" "}
              <span className="font-medium">revoked immediately</span>. Their record stays in the directory.
            </p>
            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                className="btn-secondary"
                disabled={deactivatingBusy}
                onClick={() => setDeactivating(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn-primary bg-red-600 hover:bg-red-700"
                disabled={deactivatingBusy}
                onClick={handleDeactivate}
              >
                {deactivatingBusy ? "Deactivating…" : "Deactivate"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ---- org structure tab ---------------------------------------------------

/** Small modal with a single text field (create department or designation). */
function SimpleCreateModal({
  isOpen,
  onClose,
  title,
  label,
  placeholder,
  submitLabel,
  onSubmit,
}: {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  label: string;
  placeholder: string;
  submitLabel: string;
  onSubmit: (value: string) => Promise<void>;
}) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await onSubmit(value.trim());
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title} size="sm">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="label">{label}</label>
          <input
            required
            className="input"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={placeholder}
          />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex justify-end gap-3 pt-2">
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button type="submit" disabled={submitting} className="btn-primary">
            {submitting ? "Saving…" : submitLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** Modal for creating a designation: department select + title + optional level. */
function DesignationModal({
  isOpen,
  onClose,
  departments,
  onSubmit,
}: {
  isOpen: boolean;
  onClose: () => void;
  departments: Department[];
  onSubmit: (value: { departmentId: string; title: string; level: number | null }) => Promise<void>;
}) {
  const [departmentId, setDepartmentId] = useState(() => departments[0]?.department_id ?? "");
  const [title, setTitle] = useState("");
  const [level, setLevel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await onSubmit({
        departmentId,
        title: title.trim(),
        level: level ? Number(level) : null,
      });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Add Designation" size="sm">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="label">Department *</label>
          <select
            required
            className="input"
            value={departmentId}
            onChange={(e) => setDepartmentId(e.target.value)}
          >
            {departments.map((d) => (
              <option key={d.department_id} value={d.department_id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Title *</label>
          <input
            required
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Senior Engineer"
          />
        </div>
        <div>
          <label className="label">Level</label>
          <input
            type="number"
            min={1}
            className="input"
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            placeholder="Optional — e.g. 2"
          />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex justify-end gap-3 pt-2">
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button type="submit" disabled={submitting} className="btn-primary">
            {submitting ? "Saving…" : "Create Designation"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function OrgTab() {
  const { addToast } = useToast();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [designations, setDesignations] = useState<Designation[]>([]);
  const [loading, setLoading] = useState(true);
  const [deptModalOpen, setDeptModalOpen] = useState(false);
  const [desigModalOpen, setDesigModalOpen] = useState(false);

  const refresh = useMemo(
    () => () =>
      Promise.all([
        api.listDepartments().catch(() => [] as Department[]),
        api.listDesignations().catch(() => [] as Designation[]),
      ])
        .then(([depts, desigs]) => {
          setDepartments(depts);
          setDesignations(desigs);
        })
        .finally(() => setLoading(false)),
    []
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleCreateDepartment(name: string) {
    await api.createDepartment(name);
    addToast(`Department "${name}" created.`, "success");
    await refresh();
  }

  if (loading) return <ListSkeleton rows={4} />;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {/* Departments */}
      <section className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-zinc-100 px-5 py-3">
          <h2 className="text-sm font-semibold text-zinc-900">
            Departments{" "}
            <span className="ml-1 text-xs font-normal text-zinc-400">({departments.length})</span>
          </h2>
          <button type="button" className="btn-secondary px-3 py-1.5 text-xs" onClick={() => setDeptModalOpen(true)}>
            Add
          </button>
        </div>
        {departments.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-zinc-400">No departments yet.</p>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {departments.map((d) => {
              const count = designations.filter((x) => x.department_id === d.department_id).length;
              return (
                <li key={d.department_id} className="flex items-center justify-between px-5 py-3">
                  <span className="text-sm font-medium text-zinc-800">{d.name}</span>
                  <span className="text-xs text-zinc-400">
                    {count} designation{count === 1 ? "" : "s"}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* Designations */}
      <section className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-zinc-100 px-5 py-3">
          <h2 className="text-sm font-semibold text-zinc-900">
            Designations{" "}
            <span className="ml-1 text-xs font-normal text-zinc-400">({designations.length})</span>
          </h2>
          <button type="button" className="btn-secondary px-3 py-1.5 text-xs" onClick={() => setDesigModalOpen(true)}>
            Add
          </button>
        </div>
        {designations.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-zinc-400">No designations yet.</p>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {designations.map((d) => (
              <li key={d.designation_id} className="flex items-center justify-between px-5 py-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-zinc-800">{d.title}</p>
                  <p className="text-xs text-zinc-400">{d.department_name ?? "—"}</p>
                </div>
                {d.level !== null && (
                  <span className="badge bg-zinc-100 text-zinc-600">L{d.level}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {deptModalOpen && (
        <SimpleCreateModal
          isOpen
          onClose={() => setDeptModalOpen(false)}
          title="Add Department"
          label="Department Name"
          placeholder="e.g. Finance"
          submitLabel="Create Department"
          onSubmit={handleCreateDepartment}
        />
      )}
      {desigModalOpen && (
        <DesignationModal
          isOpen
          onClose={() => setDesigModalOpen(false)}
          departments={departments}
          onSubmit={async ({ departmentId, title }) => {
            await api.createDesignation({ department_id: departmentId, title });
            addToast(`Designation "${title}" created.`, "success");
            await refresh();
          }}
        />
      )}
    </div>
  );
}

// ---- org chart tab -------------------------------------------------------

function OrgChartTab() {
  const { addToast } = useToast();
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [designations, setDesignations] = useState<Designation[]>([]);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Employee | null>(null);
  const [presetManagerId, setPresetManagerId] = useState<string | null>(null);

  const refresh = useMemo(
    () => () =>
      Promise.all([
        api.listDepartments().catch(() => [] as Department[]),
        api.listDesignations().catch(() => [] as Designation[]),
        api.listEmployees().catch(() => [] as Employee[]),
      ])
        .then(([depts, desigs, emps]) => {
          setDepartments(depts);
          setDesignations(desigs);
          setEmployees(emps);
        })
        .finally(() => setLoading(false)),
    []
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleSubmit({
    form,
    employeeId,
  }: {
    form: EmployeeForm;
    employeeId: string | null;
  }) {
    if (employeeId) {
      await api.updateEmployee(employeeId, {
        first_name: form.first_name,
        last_name: form.last_name,
        phone: form.phone || null,
        department_id: form.department_id,
        designation_id: form.designation_id,
        manager_employee_id: form.manager_employee_id || null,
        joining_date: form.joining_date,
        employment_status: form.employment_status,
      });
      addToast("Employee updated.", "success");
    } else {
      await api.createEmployee({
        first_name: form.first_name,
        last_name: form.last_name,
        email: form.email,
        phone: form.phone || null,
        employee_code: form.employee_code,
        department_id: form.department_id,
        designation_id: form.designation_id,
        manager_employee_id: form.manager_employee_id || null,
        joining_date: form.joining_date,
        password: form.password,
      });
      addToast("Employee added.", "success");
    }
    setFormOpen(false);
    setEditing(null);
    setPresetManagerId(null);
    await refresh();
  }

  if (loading) return <ListSkeleton rows={6} />;

  if (employees.length === 0) {
    return (
      <div className="card">
        <EmptyState
          title="No employees yet"
          description="Add your first employee to start building and visualizing the org hierarchy."
          action={
            <button
              type="button"
              className="btn-primary"
              onClick={() => {
                setEditing(null);
                setPresetManagerId(null);
                setFormOpen(true);
              }}
            >
              Add Employee
            </button>
          }
        />
        {formOpen && (
          <EmployeeFormModal
            isOpen
            onClose={() => {
              setFormOpen(false);
              setEditing(null);
              setPresetManagerId(null);
            }}
            employee={editing}
            initialManagerId={presetManagerId}
            departments={departments}
            designations={designations}
            managers={employees.filter(
              (e) => e.employment_status === "ACTIVE" && e.employee_id !== editing?.employee_id
            )}
            onSubmit={handleSubmit}
          />
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <OrgChart
        employees={employees}
        departments={departments}
        designations={designations}
        onEditEmployee={(emp) => {
          setEditing(emp);
          setPresetManagerId(null);
          setFormOpen(true);
        }}
        onAddEmployee={(mgrId) => {
          setEditing(null);
          setPresetManagerId(mgrId || null);
          setFormOpen(true);
        }}
      />

      {formOpen && (
        <EmployeeFormModal
          isOpen
          onClose={() => {
            setFormOpen(false);
            setEditing(null);
            setPresetManagerId(null);
          }}
          employee={editing}
          initialManagerId={presetManagerId}
          departments={departments}
          designations={designations}
          managers={employees.filter(
            (e) => e.employment_status === "ACTIVE" && e.employee_id !== editing?.employee_id
          )}
          onSubmit={handleSubmit}
        />
      )}
    </div>
  );
}

// ---- page ----------------------------------------------------------------

const TABS = [
  { id: "employees", label: "Employees" },
  { id: "org", label: "Departments & Designations" },
  { id: "chart", label: "Org Chart" },
] as const;

export default function ManagerPeoplePage() {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("employees");

  return (
    <div className="space-y-6">
      <PageHeader
        title="People"
        description="Manage the org directory — employees, departments, and designations."
      />

      {/* Tabs */}
      <div className="flex gap-1 border-b border-zinc-200">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
              tab === t.id
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-zinc-500 hover:text-zinc-800"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "employees" ? <EmployeesTab /> : tab === "org" ? <OrgTab /> : <OrgChartTab />}
    </div>
  );
}
