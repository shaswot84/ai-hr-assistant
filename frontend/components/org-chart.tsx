"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { StatusBadge } from "@/components/status";
import type { Department, Designation, Employee } from "@/lib/types";

// Harmonious palette generator for department badges and accent tags
const DEPT_COLORS: { bg: string; text: string; border: string; accent: string }[] = [
  { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200", accent: "bg-blue-600" },
  { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", accent: "bg-emerald-600" },
  { bg: "bg-purple-50", text: "text-purple-700", border: "border-purple-200", accent: "bg-purple-600" },
  { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-200", accent: "bg-amber-600" },
  { bg: "bg-rose-50", text: "text-rose-700", border: "border-rose-200", accent: "bg-rose-600" },
  { bg: "bg-indigo-50", text: "text-indigo-700", border: "border-indigo-200", accent: "bg-indigo-600" },
  { bg: "bg-cyan-50", text: "text-cyan-700", border: "border-cyan-200", accent: "bg-cyan-600" },
  { bg: "bg-teal-50", text: "text-teal-700", border: "border-teal-200", accent: "bg-teal-600" },
];

function getDeptColor(deptName: string | null) {
  if (!deptName) return { bg: "bg-zinc-100", text: "text-zinc-700", border: "border-zinc-200", accent: "bg-zinc-500" };
  let hash = 0;
  for (let i = 0; i < deptName.length; i++) {
    hash = (hash << 5) - hash + deptName.charCodeAt(i);
    hash |= 0;
  }
  const idx = Math.abs(hash) % DEPT_COLORS.length;
  return DEPT_COLORS[idx];
}

function fullName(e: Employee) {
  return `${e.first_name} ${e.last_name}`.trim();
}

function initials(e: Employee) {
  const f = e.first_name?.charAt(0) || "";
  const l = e.last_name?.charAt(0) || "";
  return (f + l).toUpperCase() || "?";
}

export interface TreeNode {
  employee: Employee;
  reports: TreeNode[];
  directReportCount: number;
  totalDescendantCount: number;
  depth: number;
}

export interface OrgChartProps {
  employees: Employee[];
  departments: Department[];
  designations: Designation[];
  onEditEmployee?: (employee: Employee) => void;
  onAddEmployee?: (managerId?: string) => void;
}

export function OrgChart({
  employees,
  departments,
  designations: _designations,
  onEditEmployee,
  onAddEmployee,
}: OrgChartProps) {
  // View states
  const [viewMode, setViewMode] = useState<"tree" | "compact">("tree");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedDeptId, setSelectedDeptId] = useState<string>("ALL");
  const [showActiveOnly, setShowActiveOnly] = useState(false);
  const [focusedRootId, setFocusedRootId] = useState<string | null>(null);

  // Expanded / Collapsed state: Record<employeeId, boolean> (true = collapsed)
  const [collapsedMap, setCollapsedMap] = useState<Record<string, boolean>>({});

  // Inspected employee for Slide-over Drawer
  const [inspectedEmployee, setInspectedEmployee] = useState<Employee | null>(null);

  // Zoom & Pan canvas transform
  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const startPanRef = useRef({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement>(null);
  const chartWrapperRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Filter employees according to active-only setting
  const activeFilteredEmployees = useMemo(() => {
    if (!showActiveOnly) return employees;
    return employees.filter((e) => e.employment_status === "ACTIVE");
  }, [employees, showActiveOnly]);

  const employeeMap = useMemo(() => {
    return new Map<string, Employee>(employees.map((e) => [e.employee_id, e]));
  }, [employees]);

  // Build the hierarchical tree structure
  const { fullTreeRoots, allNodesMap, maxDepth, totalManagers } = useMemo(() => {
    const byId = new Map<string, Employee>(activeFilteredEmployees.map((e) => [e.employee_id, e]));
    const childrenMap = new Map<string, Employee[]>();
    const roots: Employee[] = [];

    // Identify direct children and root candidates
    for (const emp of activeFilteredEmployees) {
      if (emp.manager_employee_id && byId.has(emp.manager_employee_id) && emp.manager_employee_id !== emp.employee_id) {
        const list = childrenMap.get(emp.manager_employee_id) ?? [];
        list.push(emp);
        childrenMap.set(emp.manager_employee_id, list);
      } else {
        roots.push(emp);
      }
    }

    const nodesMap = new Map<string, TreeNode>();
    let calculatedMaxDepth = 0;
    let managerCount = 0;

    // Recursive helper to construct TreeNode hierarchy with cycle protection
    function buildNode(emp: Employee, depth: number, visited: Set<string>): TreeNode {
      visited.add(emp.employee_id);
      if (depth > calculatedMaxDepth) calculatedMaxDepth = depth;

      const directChildren = (childrenMap.get(emp.employee_id) ?? []).filter((child) => !visited.has(child.employee_id));
      if (directChildren.length > 0) managerCount++;

      const childNodes: TreeNode[] = directChildren.map((child) =>
        buildNode(child, depth + 1, new Set(visited))
      );

      const totalDescendants = childNodes.reduce(
        (sum, child) => sum + 1 + child.totalDescendantCount,
        0
      );

      const node: TreeNode = {
        employee: emp,
        reports: childNodes,
        directReportCount: childNodes.length,
        totalDescendantCount: totalDescendants,
        depth,
      };

      nodesMap.set(emp.employee_id, node);
      return node;
    }

    const builtRoots = roots.map((r) => buildNode(r, 1, new Set<string>()));

    return {
      fullTreeRoots: builtRoots,
      allNodesMap: nodesMap,
      maxDepth: calculatedMaxDepth,
      totalManagers: managerCount,
    };
  }, [activeFilteredEmployees]);

  // Determine active visible roots based on focusedRootId drilldown
  const visibleRoots = useMemo(() => {
    if (!focusedRootId) return fullTreeRoots;
    const target = allNodesMap.get(focusedRootId);
    return target ? [target] : fullTreeRoots;
  }, [focusedRootId, fullTreeRoots, allNodesMap]);

  // Search matching logic
  const searchResults = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return new Set<string>();

    const matches = new Set<string>();
    for (const emp of activeFilteredEmployees) {
      const matchName = fullName(emp).toLowerCase().includes(query);
      const matchEmail = emp.email?.toLowerCase().includes(query);
      const matchCode = emp.employee_code?.toLowerCase().includes(query);
      const matchTitle = emp.designation_title?.toLowerCase().includes(query);
      const matchDept = emp.department_name?.toLowerCase().includes(query);

      if (matchName || matchEmail || matchCode || matchTitle || matchDept) {
        matches.add(emp.employee_id);
      }
    }
    return matches;
  }, [searchQuery, activeFilteredEmployees]);

  // Auto-expand ancestors when search changes
  useEffect(() => {
    if (searchResults.size === 0) return;

    setCollapsedMap((prev) => {
      const next = { ...prev };
      for (const matchedId of searchResults) {
        let cur: Employee | undefined = employeeMap.get(matchedId);
        while (cur && cur.manager_employee_id) {
          const managerId = cur.manager_employee_id;
          next[managerId] = false; // ensure expanded
          cur = employeeMap.get(managerId);
        }
      }
      return next;
    });
  }, [searchResults, employeeMap]);

  // Compute breadcrumb path when in focused subtree view
  const focusBreadcrumb = useMemo(() => {
    if (!focusedRootId) return [];
    const trail: Employee[] = [];
    let curId: string | null = focusedRootId;
    const guard = new Set<string>();

    while (curId && employeeMap.has(curId) && !guard.has(curId)) {
      guard.add(curId);
      const emp: Employee | undefined = employeeMap.get(curId);
      if (!emp) break;
      trail.unshift(emp);
      curId = emp.manager_employee_id;
    }
    return trail;
  }, [focusedRootId, employeeMap]);

  // Expand / Collapse Helpers
  const toggleCollapse = useCallback((employeeId: string) => {
    setCollapsedMap((prev) => ({
      ...prev,
      [employeeId]: !prev[employeeId],
    }));
  }, []);

  const expandAll = useCallback(() => {
    setCollapsedMap({});
  }, []);

  const collapseAll = useCallback(() => {
    const next: Record<string, boolean> = {};
    for (const empId of allNodesMap.keys()) {
      const node = allNodesMap.get(empId);
      if (node && node.directReportCount > 0) {
        next[empId] = true;
      }
    }
    setCollapsedMap(next);
  }, [allNodesMap]);

  // Zoom Controls
  const handleZoomIn = () => setScale((s) => Math.min(1.8, Number((s + 0.15).toFixed(2))));
  const handleZoomOut = () => setScale((s) => Math.max(0.4, Number((s - 0.15).toFixed(2))));
  const handleResetZoom = () => {
    setScale(1);
    setPan({ x: 0, y: 0 });
  };

  const handleFitView = () => {
    setScale(0.85);
    setPan({ x: 0, y: 0 });
  };

  // Pan Canvas Handlers
  const handlePointerDown = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest("button, a, input, select, .no-pan")) {
      return;
    }
    setIsPanning(true);
    startPanRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!isPanning) return;
    setPan({
      x: e.clientX - startPanRef.current.x,
      y: e.clientY - startPanRef.current.y,
    });
  };

  const handlePointerUp = () => {
    setIsPanning(false);
  };

  // Wheel Zoom support (with Ctrl/Cmd or standard pinch)
  const handleWheel = (e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.08 : 0.92;
      setScale((s) => Math.min(1.8, Math.max(0.4, Number((s * zoomFactor).toFixed(2)))));
    }
  };

  const toggleFullscreen = () => {
    if (!chartWrapperRef.current) return;
    if (!document.fullscreenElement) {
      chartWrapperRef.current.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => {});
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => {});
    }
  };

  useEffect(() => {
    const handleFsChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", handleFsChange);
    return () => document.removeEventListener("fullscreenchange", handleFsChange);
  }, []);

  return (
    <div className="space-y-4" ref={chartWrapperRef}>
      {/* 1. Header Toolbar & Statistics Bar */}
      <div className="flex flex-col gap-3 rounded-lg border border-zinc-200 bg-white p-4 shadow-xs">
        {/* Top bar: Controls, Search, Dept Filter, View Switcher */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* Search Box */}
          <div className="relative min-w-[240px] flex-1 sm:max-w-xs">
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
              placeholder="Search people in tree…"
              className="input pl-9 pr-8"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600"
                aria-label="Clear search"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
              </button>
            )}
          </div>

          {/* Department Filter */}
          <div className="flex items-center gap-2">
            <select
              aria-label="Filter by department in org tree"
              className="input sm:w-44 text-xs font-medium"
              value={selectedDeptId}
              onChange={(e) => setSelectedDeptId(e.target.value)}
            >
              <option value="ALL">All Departments</option>
              {departments.map((d) => (
                <option key={d.department_id} value={d.department_id}>
                  {d.name}
                </option>
              ))}
            </select>

            <button
              type="button"
              onClick={() => setShowActiveOnly((prev) => !prev)}
              className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors ${
                showActiveOnly
                  ? "border-blue-600 bg-blue-50 text-blue-700"
                  : "border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50"
              }`}
              title="Toggle active employees only"
            >
              <span className={`h-2 w-2 rounded-full ${showActiveOnly ? "bg-blue-600" : "bg-zinc-300"}`} />
              Active Only
            </button>
          </div>

          {/* Expand / Collapse & View Mode Toggle */}
          <div className="flex items-center gap-1.5 border-l border-zinc-200 pl-3">
            <button
              type="button"
              onClick={expandAll}
              className="btn-secondary px-2.5 py-1.5 text-xs"
              title="Expand all tree branches"
            >
              <svg className="h-3.5 w-3.5 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 13l-7 7-7-7m14-8l-7 7-7-7" />
              </svg>
              Expand All
            </button>

            <button
              type="button"
              onClick={collapseAll}
              className="btn-secondary px-2.5 py-1.5 text-xs"
              title="Collapse all subtrees"
            >
              <svg className="h-3.5 w-3.5 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 11l7-7 7 7M5 19l7-7 7 7" />
              </svg>
              Collapse
            </button>

            {/* View Switcher: Tree vs Compact */}
            <div className="ml-1 inline-flex rounded-md border border-zinc-200 bg-zinc-50 p-0.5">
              <button
                type="button"
                onClick={() => setViewMode("tree")}
                className={`flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                  viewMode === "tree" ? "bg-white text-blue-700 shadow-xs" : "text-zinc-600 hover:text-zinc-900"
                }`}
                title="Top-down visual tree chart"
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16m-7 6h7" />
                </svg>
                Visual Tree
              </button>
              <button
                type="button"
                onClick={() => setViewMode("compact")}
                className={`flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                  viewMode === "compact" ? "bg-white text-blue-700 shadow-xs" : "text-zinc-600 hover:text-zinc-900"
                }`}
                title="Compact hierarchical list view"
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                </svg>
                Hierarchy List
              </button>
            </div>
          </div>
        </div>

        {/* Subtree Focus Breadcrumbs if Drilled In */}
        {focusedRootId && focusBreadcrumb.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 rounded-md bg-blue-50/70 px-3 py-2 text-xs text-blue-900">
            <span className="font-semibold text-blue-800">Focused Subtree:</span>
            <button
              type="button"
              onClick={() => setFocusedRootId(null)}
              className="inline-flex items-center font-medium text-blue-700 underline hover:text-blue-900"
            >
              Full Organization
            </button>
            {focusBreadcrumb.map((emp, i) => {
              const isLast = i === focusBreadcrumb.length - 1;
              return (
                <div key={emp.employee_id} className="inline-flex items-center gap-1.5">
                  <span className="text-blue-300">/</span>
                  {isLast ? (
                    <span className="font-semibold text-blue-950">{fullName(emp)}</span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setFocusedRootId(emp.employee_id)}
                      className="font-medium text-blue-700 hover:underline"
                    >
                      {fullName(emp)}
                    </button>
                  )}
                </div>
              );
            })}
            <button
              type="button"
              onClick={() => setFocusedRootId(null)}
              className="ml-auto rounded-xs bg-blue-200/60 px-2 py-0.5 text-[11px] font-semibold text-blue-800 hover:bg-blue-300/60"
            >
              Reset to Full Org
            </button>
          </div>
        )}

        {/* Metrics Strip */}
        <div className="flex flex-wrap items-center gap-4 border-t border-zinc-100 pt-2.5 text-xs text-zinc-500">
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-600" />
            <span>
              Total Headcount: <strong className="font-semibold text-zinc-900">{activeFilteredEmployees.length}</strong>
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-600" />
            <span>
              People Managers: <strong className="font-semibold text-zinc-900">{totalManagers}</strong>
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-purple-600" />
            <span>
              Departments: <strong className="font-semibold text-zinc-900">{departments.length}</strong>
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-600" />
            <span>
              Max Org Depth: <strong className="font-semibold text-zinc-900">{maxDepth} Levels</strong>
            </span>
          </div>
          {searchQuery && (
            <div className="ml-auto font-medium text-blue-600">
              Found {searchResults.size} match{searchResults.size === 1 ? "" : "es"}
            </div>
          )}
        </div>
      </div>

      {/* 2. Main Org Canvas Area */}
      <div
        className={`relative overflow-hidden rounded-lg border border-zinc-200 bg-zinc-50/80 select-none ${
          isFullscreen ? "fixed inset-0 z-50 h-screen w-screen rounded-none bg-zinc-100" : "h-[680px] w-full"
        }`}
        ref={containerRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
        onWheel={handleWheel}
        style={{ cursor: isPanning ? "grabbing" : "grab" }}
      >
        {/* Floating Canvas Controls Overlay */}
        <div className="absolute right-4 top-4 z-20 flex flex-col gap-1.5 rounded-lg border border-zinc-200/80 bg-white/95 p-1 shadow-sm backdrop-blur-xs">
          <button
            type="button"
            onClick={handleZoomIn}
            className="flex h-7 w-7 items-center justify-center rounded-md text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
            title="Zoom In (or Ctrl + Wheel Up)"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
          </button>
          <button
            type="button"
            onClick={handleZoomOut}
            className="flex h-7 w-7 items-center justify-center rounded-md text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
            title="Zoom Out (or Ctrl + Wheel Down)"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 12H4" />
            </svg>
          </button>
          <div className="my-0.5 h-px bg-zinc-200" />
          <button
            type="button"
            onClick={handleResetZoom}
            className="flex h-7 w-7 items-center justify-center rounded-md text-[11px] font-semibold text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
            title="Reset Zoom to 100%"
          >
            1:1
          </button>
          <button
            type="button"
            onClick={handleFitView}
            className="flex h-7 w-7 items-center justify-center rounded-md text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
            title="Fit to screen view"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
            </svg>
          </button>
          <button
            type="button"
            onClick={toggleFullscreen}
            className="flex h-7 w-7 items-center justify-center rounded-md text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
            title={isFullscreen ? "Exit Fullscreen" : "Fullscreen View"}
          >
            {isFullscreen ? (
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4h6m-6 0v6m16-6h-6m6 0v6M4 20h6m-6 0v-6m16 6h-6m6 0v-6" />
              </svg>
            )}
          </button>
        </div>

        {/* Visual Canvas Content */}
        {viewMode === "tree" ? (
          <div
            className="absolute inset-0 origin-top-left transition-transform duration-75"
            style={{
              transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`,
              transformOrigin: "center top",
            }}
          >
            <div className="flex min-w-max justify-center p-12">
              <div className="flex flex-wrap items-start justify-center gap-16">
                {visibleRoots.map((rootNode) => (
                  <VisualTreeNode
                    key={rootNode.employee.employee_id}
                    node={rootNode}
                    collapsedMap={collapsedMap}
                    onToggleCollapse={toggleCollapse}
                    onSelectEmployee={(emp) => setInspectedEmployee(emp)}
                    onFocusSubtree={(empId) => setFocusedRootId(empId)}
                    selectedDeptId={selectedDeptId}
                    searchResults={searchResults}
                  />
                ))}
              </div>
            </div>
          </div>
        ) : (
          /* Compact Hierarchy View */
          <div className="h-full overflow-y-auto p-6">
            <div className="mx-auto max-w-4xl space-y-2">
              {visibleRoots.map((rootNode) => (
                <CompactTreeNode
                  key={rootNode.employee.employee_id}
                  node={rootNode}
                  collapsedMap={collapsedMap}
                  onToggleCollapse={toggleCollapse}
                  onSelectEmployee={(emp) => setInspectedEmployee(emp)}
                  onFocusSubtree={(empId) => setFocusedRootId(empId)}
                  selectedDeptId={selectedDeptId}
                  searchResults={searchResults}
                  level={0}
                />
              ))}
            </div>
          </div>
        )}

        {/* Canvas Navigation Hint */}
        <div className="pointer-events-none absolute bottom-3 left-4 z-10 flex items-center gap-2 rounded-full border border-zinc-200 bg-white/90 px-3 py-1 text-[11px] text-zinc-500 shadow-xs backdrop-blur-xs">
          <span>Drag canvas to pan</span>
          <span className="text-zinc-300">•</span>
          <span>Ctrl + Scroll to zoom</span>
          <span className="text-zinc-300">•</span>
          <span>Click card for details</span>
        </div>
      </div>

      {/* 3. Slide-Over Employee Detail Drawer */}
      {inspectedEmployee && (
        <EmployeeDetailDrawer
          employee={inspectedEmployee}
          employeeMap={employeeMap}
          allNodesMap={allNodesMap}
          onClose={() => setInspectedEmployee(null)}
          onEditEmployee={() => {
            if (onEditEmployee) {
              onEditEmployee(inspectedEmployee);
            }
          }}
          onSelectEmployee={(emp) => setInspectedEmployee(emp)}
          onFocusSubtree={(empId) => {
            setFocusedRootId(empId);
            setInspectedEmployee(null);
          }}
          onAddDirectReport={() => {
            if (onAddEmployee) {
              onAddEmployee(inspectedEmployee.employee_id);
            }
          }}
        />
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Visual Tree Node Component (Branching Top-Down Layout with Connectors)
// --------------------------------------------------------------------------

interface VisualTreeNodeProps {
  node: TreeNode;
  collapsedMap: Record<string, boolean>;
  onToggleCollapse: (empId: string) => void;
  onSelectEmployee: (emp: Employee) => void;
  onFocusSubtree: (empId: string) => void;
  selectedDeptId: string;
  searchResults: Set<string>;
}

function VisualTreeNode({
  node,
  collapsedMap,
  onToggleCollapse,
  onSelectEmployee,
  onFocusSubtree,
  selectedDeptId,
  searchResults,
}: VisualTreeNodeProps) {
  const isCollapsed = Boolean(collapsedMap[node.employee.employee_id]);
  const hasReports = node.reports.length > 0;
  const isMatchingSearch = searchResults.has(node.employee.employee_id);
  const isDeptMatch = selectedDeptId === "ALL" || node.employee.department_id === selectedDeptId;
  const deptTheme = getDeptColor(node.employee.department_name);

  return (
    <div className="flex flex-col items-center">
      {/* Node Card Box */}
      <div
        className={`relative z-10 w-64 rounded-xl border bg-white p-3.5 shadow-xs transition-all duration-150 ${
          isMatchingSearch
            ? "border-blue-500 ring-4 ring-blue-500/20 shadow-md scale-102"
            : !isDeptMatch
            ? "opacity-45 border-zinc-200"
            : "border-zinc-200/90 hover:border-blue-400 hover:shadow-md"
        }`}
      >
        {/* Department Color Accent Line */}
        <div className={`absolute left-0 top-3 bottom-3 w-1 rounded-r ${deptTheme.accent}`} />

        {/* Top Card Row: Avatar, Name, Status */}
        <div
          className="flex cursor-pointer items-start gap-3 pl-1.5"
          onClick={() => onSelectEmployee(node.employee)}
        >
          <div
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full font-semibold text-xs border ${deptTheme.bg} ${deptTheme.text} ${deptTheme.border}`}
          >
            {initials(node.employee)}
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-1">
              <p className="truncate text-sm font-semibold text-zinc-900 group-hover:text-blue-600">
                {fullName(node.employee)}
              </p>
              <span
                className={`inline-block h-2 w-2 shrink-0 rounded-full ${
                  node.employee.employment_status === "ACTIVE" ? "bg-emerald-500" : "bg-zinc-300"
                }`}
                title={node.employee.employment_status}
              />
            </div>
            <p className="truncate text-xs font-medium text-zinc-600">
              {node.employee.designation_title || "Team Member"}
            </p>
          </div>
        </div>

        {/* Card Middle Row: Department Badge & Employee Code */}
        <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-zinc-100 pt-2 pl-1.5 text-[11px]">
          <span className={`inline-flex items-center rounded-sm px-1.5 py-0.5 font-medium border ${deptTheme.bg} ${deptTheme.text} ${deptTheme.border}`}>
            {node.employee.department_name || "General"}
          </span>
          <span className="font-mono text-[10px] text-zinc-400">
            {node.employee.employee_code}
          </span>
        </div>

        {/* Card Footer Actions: Quick Focus + Collapse / Direct Reports Count */}
        <div className="mt-2 flex items-center justify-between border-t border-zinc-100/80 pt-2 pl-1.5 text-[11px]">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onFocusSubtree(node.employee.employee_id);
            }}
            className="inline-flex items-center gap-1 text-zinc-400 hover:text-blue-600 font-medium"
            title="Focus this manager's team as root"
          >
            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
            Team
          </button>

          {hasReports && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onToggleCollapse(node.employee.employee_id);
              }}
              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold transition-colors ${
                isCollapsed
                  ? "bg-blue-600 text-white hover:bg-blue-700 shadow-xs"
                  : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200"
              }`}
              title={isCollapsed ? "Expand direct reports" : "Collapse direct reports"}
            >
              <span>{isCollapsed ? "+" : "−"}</span>
              <span>{node.directReportCount}</span>
              <span className="text-[10px] font-normal opacity-85">reports</span>
            </button>
          )}
        </div>

        {/* Stem Connector: Vertical stub leaving bottom of card */}
        {hasReports && !isCollapsed && (
          <div className="absolute -bottom-6 left-1/2 h-6 w-0.5 -translate-x-1/2 bg-zinc-300" />
        )}
      </div>

      {/* Children Subtrees with Connector Lines */}
      {hasReports && !isCollapsed && (
        <div className="relative mt-6 flex items-start justify-center pt-6">
          {/* Horizontal crossbar connecting all child branch lines */}
          {node.reports.length > 1 && (
            <div className="absolute top-0 left-0 right-0 h-0.5 bg-zinc-300" />
          )}

          <div className="flex items-start justify-center gap-10">
            {node.reports.map((childNode) => (
              <div key={childNode.employee.employee_id} className="relative flex flex-col items-center">
                {/* Vertical line dropping down from crossbar to child card top */}
                <div className="absolute -top-6 left-1/2 h-6 w-0.5 -translate-x-1/2 bg-zinc-300" />

                <VisualTreeNode
                  node={childNode}
                  collapsedMap={collapsedMap}
                  onToggleCollapse={onToggleCollapse}
                  onSelectEmployee={onSelectEmployee}
                  onFocusSubtree={onFocusSubtree}
                  selectedDeptId={selectedDeptId}
                  searchResults={searchResults}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Compact Indented Hierarchy View Component
// --------------------------------------------------------------------------

interface CompactTreeNodeProps {
  node: TreeNode;
  collapsedMap: Record<string, boolean>;
  onToggleCollapse: (empId: string) => void;
  onSelectEmployee: (emp: Employee) => void;
  onFocusSubtree: (empId: string) => void;
  selectedDeptId: string;
  searchResults: Set<string>;
  level: number;
}

function CompactTreeNode({
  node,
  collapsedMap,
  onToggleCollapse,
  onSelectEmployee,
  onFocusSubtree,
  selectedDeptId,
  searchResults,
  level,
}: CompactTreeNodeProps) {
  const isCollapsed = Boolean(collapsedMap[node.employee.employee_id]);
  const hasReports = node.reports.length > 0;
  const isMatchingSearch = searchResults.has(node.employee.employee_id);
  const isDeptMatch = selectedDeptId === "ALL" || node.employee.department_id === selectedDeptId;
  const deptTheme = getDeptColor(node.employee.department_name);

  return (
    <div className="space-y-1">
      <div
        className={`group flex items-center justify-between rounded-lg border bg-white px-3.5 py-2.5 transition-all ${
          isMatchingSearch
            ? "border-blue-500 bg-blue-50/40 ring-2 ring-blue-500/20"
            : !isDeptMatch
            ? "opacity-50 border-zinc-200"
            : "border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50/60"
        }`}
        style={{ marginLeft: `${level * 24}px` }}
      >
        {/* Left: Expand Toggle + Avatar + Name + Title */}
        <div className="flex items-center gap-3 min-w-0">
          {hasReports ? (
            <button
              type="button"
              onClick={() => onToggleCollapse(node.employee.employee_id)}
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-zinc-200 bg-zinc-50 text-xs font-semibold text-zinc-700 hover:bg-zinc-100"
            >
              {isCollapsed ? "+" : "−"}
            </button>
          ) : (
            <span className="h-6 w-6 shrink-0 flex items-center justify-center text-zinc-300">
              •
            </span>
          )}

          <div
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-semibold text-xs border ${deptTheme.bg} ${deptTheme.text} ${deptTheme.border}`}
          >
            {initials(node.employee)}
          </div>

          <div
            className="min-w-0 cursor-pointer"
            onClick={() => onSelectEmployee(node.employee)}
          >
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-semibold text-zinc-900 group-hover:text-blue-600">
                {fullName(node.employee)}
              </span>
              <span className="font-mono text-[11px] text-zinc-400">
                {node.employee.employee_code}
              </span>
            </div>
            <p className="truncate text-xs text-zinc-500">
              {node.employee.designation_title || "Team Member"}
              {node.employee.department_name ? ` · ${node.employee.department_name}` : ""}
            </p>
          </div>
        </div>

        {/* Right: Badges & Actions */}
        <div className="flex items-center gap-3 shrink-0">
          {hasReports && (
            <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-600">
              {node.directReportCount} reports ({node.totalDescendantCount} total)
            </span>
          )}
          <StatusBadge status={node.employee.employment_status} />
          <button
            type="button"
            onClick={() => onFocusSubtree(node.employee.employee_id)}
            className="rounded px-2 py-1 text-xs font-medium text-zinc-500 hover:bg-zinc-100 hover:text-blue-600"
            title="Focus sub-team"
          >
            Focus
          </button>
          <button
            type="button"
            onClick={() => onSelectEmployee(node.employee)}
            className="rounded px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50"
          >
            Details
          </button>
        </div>
      </div>

      {/* Children */}
      {hasReports && !isCollapsed && (
        <div className="space-y-1">
          {node.reports.map((child) => (
            <CompactTreeNode
              key={child.employee.employee_id}
              node={child}
              collapsedMap={collapsedMap}
              onToggleCollapse={onToggleCollapse}
              onSelectEmployee={onSelectEmployee}
              onFocusSubtree={onFocusSubtree}
              selectedDeptId={selectedDeptId}
              searchResults={searchResults}
              level={level + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Slide-Over Employee Detail Drawer
// --------------------------------------------------------------------------

interface EmployeeDetailDrawerProps {
  employee: Employee;
  employeeMap: Map<string, Employee>;
  allNodesMap: Map<string, TreeNode>;
  onClose: () => void;
  onEditEmployee: () => void;
  onSelectEmployee: (emp: Employee) => void;
  onFocusSubtree: (empId: string) => void;
  onAddDirectReport: () => void;
}

function EmployeeDetailDrawer({
  employee,
  employeeMap,
  allNodesMap,
  onClose,
  onEditEmployee,
  onSelectEmployee,
  onFocusSubtree,
  onAddDirectReport: _onAddDirectReport,
}: EmployeeDetailDrawerProps) {
  const node = allNodesMap.get(employee.employee_id);
  const deptTheme = getDeptColor(employee.department_name);

  // Compute reporting chain up to top executive
  const reportingChain = useMemo(() => {
    const chain: Employee[] = [];
    let curId: string | null = employee.manager_employee_id;
    const guard = new Set<string>();

    while (curId && employeeMap.has(curId) && !guard.has(curId)) {
      guard.add(curId);
      const m: Employee | undefined = employeeMap.get(curId);
      if (!m) break;
      chain.unshift(m);
      curId = m.manager_employee_id;
    }
    return chain;
  }, [employee, employeeMap]);

  // Direct reports list
  const directReports = useMemo(() => {
    if (!node) return [];
    return node.reports.map((r) => r.employee);
  }, [node]);

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-zinc-950/30 backdrop-blur-[2px] transition-opacity"
        onClick={onClose}
      />

      <div className="fixed inset-y-0 right-0 flex max-w-full pl-10">
        <div className="relative w-screen max-w-md bg-white shadow-2xl flex flex-col">
          {/* Drawer Header */}
          <div className="flex items-center justify-between border-b border-zinc-200 px-6 py-4">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-zinc-900">Employee Details</span>
              <span className="font-mono text-xs text-zinc-400">({employee.employee_code})</span>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600"
              aria-label="Close panel"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Drawer Body */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {/* Main Profile Info Card */}
            <div className="flex items-start gap-4 rounded-xl border border-zinc-200 bg-zinc-50/50 p-4">
              <div
                className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full font-bold text-base border ${deptTheme.bg} ${deptTheme.text} ${deptTheme.border}`}
              >
                {initials(employee)}
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="truncate text-base font-bold text-zinc-900">{fullName(employee)}</h3>
                <p className="text-xs font-medium text-zinc-600">
                  {employee.designation_title || "No designation assigned"}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <span className={`inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium border ${deptTheme.bg} ${deptTheme.text} ${deptTheme.border}`}>
                    {employee.department_name || "No department"}
                  </span>
                  <StatusBadge status={employee.employment_status} />
                </div>
              </div>
            </div>

            {/* Contact & Employment Facts */}
            <div className="space-y-3">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                Contact & Records
              </h4>
              <div className="rounded-lg border border-zinc-200 divide-y divide-zinc-100 text-xs">
                <div className="flex justify-between px-3.5 py-2.5">
                  <span className="text-zinc-500">Work Email</span>
                  <span className="font-medium text-zinc-900">{employee.email}</span>
                </div>
                <div className="flex justify-between px-3.5 py-2.5">
                  <span className="text-zinc-500">Phone</span>
                  <span className="font-medium text-zinc-900">{employee.phone || "—"}</span>
                </div>
                <div className="flex justify-between px-3.5 py-2.5">
                  <span className="text-zinc-500">Joining Date</span>
                  <span className="font-medium text-zinc-900">
                    {new Date(employee.joining_date).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                    })}
                  </span>
                </div>
                <div className="flex justify-between px-3.5 py-2.5">
                  <span className="text-zinc-500">Direct Manager</span>
                  <span className="font-medium text-zinc-900">
                    {employee.manager_name || "None (Top Level)"}
                  </span>
                </div>
              </div>
            </div>

            {/* Reporting Chain (Breadcrumbs up to Root) */}
            <div className="space-y-3">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                Reporting Line (Upward)
              </h4>
              {reportingChain.length === 0 ? (
                <p className="text-xs text-zinc-500 italic bg-zinc-50 p-3 rounded-lg border border-zinc-200">
                  This employee has no manager (Root / Executive node).
                </p>
              ) : (
                <div className="space-y-1.5 rounded-lg border border-zinc-200 p-3 bg-zinc-50/50">
                  {reportingChain.map((mgr, index) => (
                    <div key={mgr.employee_id} className="flex items-center gap-2 text-xs">
                      <span className="text-zinc-400 font-mono text-[10px] w-4">{index + 1}.</span>
                      <button
                        type="button"
                        onClick={() => onSelectEmployee(mgr)}
                        className="font-medium text-blue-600 hover:underline truncate"
                      >
                        {fullName(mgr)}
                      </button>
                      <span className="text-zinc-400 truncate">({mgr.designation_title || "Lead"})</span>
                    </div>
                  ))}
                  <div className="flex items-center gap-2 text-xs pt-1 border-t border-zinc-200 font-semibold text-zinc-900">
                    <span className="text-blue-600 font-mono text-[10px] w-4">↳</span>
                    <span>{fullName(employee)} (Current)</span>
                  </div>
                </div>
              )}
            </div>

            {/* Direct Reports List */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                  Direct Reports ({directReports.length})
                </h4>
                {node && node.totalDescendantCount > directReports.length && (
                  <span className="text-[11px] text-zinc-500">
                    {node.totalDescendantCount} total in subtree
                  </span>
                )}
              </div>

              {directReports.length === 0 ? (
                <p className="text-xs text-zinc-500 italic bg-zinc-50 p-3 rounded-lg border border-zinc-200">
                  No direct reports assigned to this employee.
                </p>
              ) : (
                <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200 overflow-hidden">
                  {directReports.map((report) => (
                    <li
                      key={report.employee_id}
                      className="flex items-center justify-between p-2.5 hover:bg-zinc-50 transition-colors"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-50 text-[11px] font-semibold text-blue-600">
                          {initials(report)}
                        </div>
                        <div className="min-w-0">
                          <button
                            type="button"
                            onClick={() => onSelectEmployee(report)}
                            className="text-xs font-semibold text-zinc-900 hover:text-blue-600 truncate block text-left"
                          >
                            {fullName(report)}
                          </button>
                          <p className="text-[11px] text-zinc-400 truncate">
                            {report.designation_title || "Team Member"}
                          </p>
                        </div>
                      </div>
                      <StatusBadge status={report.employment_status} />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {/* Drawer Footer Actions */}
          <div className="border-t border-zinc-200 bg-zinc-50 px-6 py-4 flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => onFocusSubtree(employee.employee_id)}
              className="btn-secondary text-xs flex-1"
            >
              <svg className="h-4 w-4 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              Focus Team
            </button>

            <button
              type="button"
              onClick={onEditEmployee}
              className="btn-primary text-xs flex-1"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
              Edit Record
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
