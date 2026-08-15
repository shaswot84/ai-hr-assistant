"use client";

import { createContext, useContext, useEffect, useState } from "react";

const STORAGE_KEY = "aha.sidebar.collapsed";

interface SidebarContextValue {
  collapsed: boolean;
  toggle: () => void;
}

const SidebarContext = createContext<SidebarContextValue | null>(null);

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    // localStorage unavailable (private mode etc.) — default to open
    return false;
  }
}

/**
 * Tracks whether the app-wide navigation sidebar is collapsed (like ChatGPT's
 * "close sidebar" toggle). The choice is persisted so it survives navigation
 * and reloads, and is shared across every portal shell in the same browser.
 *
 * The persisted value is applied on a microtask rather than synchronously in
 * the effect so the first render never differs from the server render
 * (avoids hydration mismatches) and matches the codebase's existing pattern.
 */
export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const value = readCollapsed();
    queueMicrotask(() => setCollapsed(value));
  }, []);

  const toggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        // ignore persistence failures; the in-memory state still works
      }
      return next;
    });
  };

  return <SidebarContext.Provider value={{ collapsed, toggle }}>{children}</SidebarContext.Provider>;
}

export function useSidebar(): SidebarContextValue {
  const ctx = useContext(SidebarContext);
  if (!ctx) throw new Error("useSidebar must be used within a SidebarProvider");
  return ctx;
}
