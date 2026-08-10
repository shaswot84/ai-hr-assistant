import { ComingSoon } from "@/components/coming-soon";

export default function EmployeeLeavePage() {
  return (
    <ComingSoon
      title="Leave Requests"
      description="Submit and track your leave requests, and check your balance — coming with the Leave module next sprint."
      icon={
        <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 16l2 2 4-4" />
        </svg>
      }
    />
  );
}
