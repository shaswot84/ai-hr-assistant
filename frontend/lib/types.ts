/**
 * Coarse Keycloak role assigned to a user. Manager/recruiter authority is
 * derived server-side; only these three roles reach the frontend.
 */
export type CoarseRole = "HR_ADMIN" | "EMPLOYEE" | "CANDIDATE";

/** Identity + coarse role of the signed-in user, returned by the auth endpoints. */
export interface UserContext {
  subject: string;
  email: string;
  display_name: string;
  coarse_role: CoarseRole;
}

/** A job posting; shown to candidates (OPEN only) and managed by HR_ADMINs. */
export interface Vacancy {
  vacancy_id: string;
  title: string;
  department_name: string | null;
  description: string | null;
  employment_type: string;
  opening_date: string | null;
  closing_date: string | null;
  status: string;
  created_at: string;
}

/** Advisory AI result for a resume; stored separately from authoritative application state. */
export interface Evaluation {
  score: number;
  overview: string;
  model: string | null;
  evaluated_at: string;
}

/** A candidate's application to a vacancy, including the AI evaluation if present. */
export interface Application {
  application_id: string;
  vacancy_id: string;
  vacancy_title: string | null;
  application_status: string;
  applied_at: string;
  evaluated: boolean;
  evaluation: Evaluation | null;
}

/** Application plus candidate identity; used on manager-facing detail pages. */
export interface ApplicationDetail extends Application {
  candidate_name: string | null;
  candidate_email: string | null;
}
