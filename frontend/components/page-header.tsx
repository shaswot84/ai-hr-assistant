import Link from "next/link";

/**
 * Standard page header used at the top of every portal page:
 *
 *   Page title                      [Primary action]
 *   Short description               [Secondary action]
 *
 *   meta row (badges, counts, etc.)
 *
 * The title is prominent but restrained (Linear/Vercel-style), the actions
 * sit on the right on desktop and wrap below on small screens, and the
 * description keeps the page from feeling like a stack of cards.
 */
export function PageHeader({
  title,
  description,
  meta,
  actions,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Optional trailing content under the description (e.g. a count badge). */
  meta?: React.ReactNode;
  /** Primary/secondary actions rendered on the right. */
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
      <div className="min-w-0 flex-1">
        <h1 className="text-xl font-semibold tracking-tight text-zinc-900 sm:text-[22px]">
          {title}
        </h1>
        {description && (
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-zinc-500">{description}</p>
        )}
        {meta && <div className="mt-2">{meta}</div>}
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
      )}
    </div>
  );
}

/** Breadcrumb-style "back to parent" link used at the top of detail pages. */
export function BackLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="group inline-flex items-center gap-1 text-[13px] font-medium text-zinc-500 transition-colors hover:text-zinc-900"
    >
      <svg
        className="h-3.5 w-3.5 transition-transform group-hover:-translate-x-0.5"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
      </svg>
      {label}
    </Link>
  );
}
