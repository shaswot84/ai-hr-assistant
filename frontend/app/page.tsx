import { redirect } from "next/navigation";

/**
 * Root route: immediately redirects visitors to the login page. The portal
 * landing pages (candidate/manager) are reached after sign-in.
 */
export default function HomePage() {
  redirect("/login");
}
