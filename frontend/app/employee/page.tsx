import { redirect } from "next/navigation";

/** Bare /employee has no dashboard of its own — land on the first real tab. */
export default function EmployeeRootPage() {
  redirect("/employee/chatbot");
}
