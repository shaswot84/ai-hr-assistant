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
    <div className="card flex flex-col items-center gap-3 p-12 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-100 text-blue-600">
        {icon}
      </div>
      <h1 className="text-lg font-semibold text-gray-900">{title}</h1>
      <p className="max-w-sm text-sm text-gray-500">{description}</p>
      <span className="badge bg-gray-100 text-gray-600">Coming soon</span>
    </div>
  );
}
