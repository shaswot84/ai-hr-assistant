/** A placeholder for a not-yet-built portal section (e.g. chatbot, leave management). */
export function ComingSoon({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="card flex flex-col items-center justify-center gap-2 px-6 py-20 text-center">
      <div className="mb-2 flex h-11 w-11 items-center justify-center rounded-lg border border-zinc-200 bg-zinc-50 text-zinc-400">
        {icon}
      </div>
      <h1 className="text-base font-semibold text-zinc-900">{title}</h1>
      <p className="max-w-md text-sm leading-relaxed text-zinc-500">{description}</p>
      <span className="badge mt-3 bg-zinc-100 text-zinc-500 ring-1 ring-inset ring-zinc-500/20">
        Coming soon
      </span>
    </div>
  );
}
