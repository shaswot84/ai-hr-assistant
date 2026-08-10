"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearAuthToken } from "@/lib/auth";
import type { CoarseRole, UserContext } from "@/lib/types";

interface NavItem {
  label: string;
  href: string;
  icon: React.ReactNode;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const STROKE = { fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" } as const;

function icon(...paths: string[]) {
  return (
    <svg {...STROKE}>
      {paths.map((d, i) => (
        <path key={i} strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d={d} />
      ))}
    </svg>
  );
}

const NAV: Record<CoarseRole, NavGroup[]> = {
  HR_ADMIN: [
    {
      label: "Workspace",
      items: [
        {
          label: "Overview",
          href: "/manager",
          icon: icon(
            "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"
          ),
        },
        {
          label: "Vacancies",
          href: "/manager/vacancies",
          icon: icon(
            "M20 7h-4V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2H4a2 2 0 00-2 2v9a2 2 0 002 2h16a2 2 0 002-2V9a2 2 0 00-2-2zm-6 0h-4V5h4v2z"
          ),
        },
        {
          label: "Applications",
          href: "/manager/applications",
          icon: icon(
            "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          ),
        },
        {
          label: "People",
          href: "/manager/people",
          icon: icon(
            "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
          ),
        },
        {
          label: "Leave",
          href: "/manager/leave",
          icon: icon(
            "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
            "M9 16l2 2 4-4"
          ),
        },
      ],
    },
    {
      label: "Knowledge",
      items: [
        {
          label: "HR Chatbot",
          href: "/manager/chatbot",
          icon: icon(
            "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.86 9.86 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
          ),
        },
        {
          label: "Documents",
          href: "/manager/ingestion",
          icon: icon(
            "M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M12 12v9m0-9l-3 3m3-3l3 3"
          ),
        },
      ],
    },
    {
      label: "System",
      items: [
        {
          label: "Settings",
          href: "/manager/settings",
          icon: icon(
            "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z",
            "M15 12a3 3 0 11-6 0 3 3 0 016 0z"
          ),
        },
      ],
    },
  ],
  CANDIDATE: [
    {
      label: "Workspace",
      items: [
        {
          label: "Vacancies",
          href: "/candidate",
          icon: icon(
            "M20 7h-4V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2H4a2 2 0 00-2 2v9a2 2 0 002 2h16a2 2 0 002-2V9a2 2 0 00-2-2zm-6 0h-4V5h4v2z"
          ),
        },
        {
          label: "My Applications",
          href: "/candidate/applications",
          icon: icon(
            "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          ),
        },
      ],
    },
    {
      label: "AI",
      items: [
        {
          label: "HR Chatbot",
          href: "/candidate/chatbot",
          icon: icon(
            "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.86 9.86 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
          ),
        },
      ],
    },
  ],
  EMPLOYEE: [
    {
      label: "AI",
      items: [
        {
          label: "HR Chatbot",
          href: "/employee/chatbot",
          icon: icon(
            "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.86 9.86 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
          ),
        },
      ],
    },
    {
      label: "Me",
      items: [
        {
          label: "Leave Requests",
          href: "/employee/leave",
          icon: icon(
            "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
            "M9 16l2 2 4-4"
          ),
        },
      ],
    },
  ],
};

/**
 * Return the href of the single nav item that best matches `pathname` — the
 * longest href that is either an exact match or a path prefix. Picking the
 * longest match ensures only the most specific tab lights up.
 */
function activeHref(items: NavItem[], pathname: string): string | null {
  let best: string | null = null;
  for (const item of items) {
    const matches = pathname === item.href || pathname.startsWith(`${item.href}/`);
    if (matches && (best === null || item.href.length > best.length)) {
      best = item.href;
    }
  }
  return best;
}

function UserArea({ user }: { user: UserContext }) {
  const router = useRouter();

  function signOut() {
    clearAuthToken();
    router.push("/login");
  }

  return (
    <div className="group flex items-center gap-2.5 rounded-md px-2.5 py-2 transition-colors hover:bg-zinc-100">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[13px] font-semibold text-white">
        {user.display_name.charAt(0).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1 leading-tight">
        <p className="truncate text-[13px] font-medium text-zinc-800">{user.display_name}</p>
        <p className="truncate text-[11px] text-zinc-400">{user.email}</p>
      </div>
      <button
        type="button"
        onClick={signOut}
        aria-label="Sign out"
        title="Sign out"
        className="rounded-md p-1.5 text-zinc-400 opacity-0 transition-all hover:bg-white hover:text-red-600 group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.75}
            d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
          />
        </svg>
      </button>
    </div>
  );
}

function SidebarContent({
  role,
  user,
  onNavigate,
}: {
  role: CoarseRole;
  user: UserContext;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const groups = NAV[role];
  const allItems = groups.flatMap((g) => g.items);
  const active = activeHref(allItems, pathname);

  return (
    <div className="flex h-full flex-col">
      {/* Brand */}
      <div className="flex items-center gap-2.5 px-5 pb-4 pt-5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-600 shadow-sm">
          <svg className="h-[18px] w-[18px] text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
            />
          </svg>
        </div>
        <div className="leading-tight">
          <p className="text-[14px] font-semibold tracking-tight text-zinc-900">AI HR Assistant</p>
          <p className="text-[11px] text-zinc-400">HR Platform</p>
        </div>
      </div>

      {/* Navigation groups */}
      <nav className="flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        {groups.map((group) => (
          <div key={group.label}>
            <p className="nav-group-label">{group.label}</p>
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const isActive = item.href === active;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={onNavigate}
                    className={`nav-item ${isActive ? "nav-item-active" : ""}`}
                  >
                    {item.icon}
                    <span className="truncate">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* User / workspace area */}
      <div className="border-t border-zinc-200 p-3">
        <UserArea user={user} />
      </div>
    </div>
  );
}

export function Sidebar({
  role,
  user,
  mobileOpen,
  onCloseMobile,
}: {
  role: CoarseRole;
  user: UserContext;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}) {
  return (
    <>
      <aside className="hidden h-full w-60 shrink-0 flex-col border-r border-zinc-200 bg-white md:flex">
        <SidebarContent role={role} user={user} />
      </aside>

      {mobileOpen && (
        <>
          <div className="fixed inset-0 z-40 bg-zinc-950/40 backdrop-blur-[2px] md:hidden" onClick={onCloseMobile} />
          <aside className="fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-zinc-200 bg-white md:hidden">
            <SidebarContent role={role} user={user} onNavigate={onCloseMobile} />
          </aside>
        </>
      )}
    </>
  );
}
