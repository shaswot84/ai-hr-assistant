export type CoarseRole = "HR_ADMIN" | "EMPLOYEE" | "CANDIDATE";

export interface UserContext {
  subject: string;
  email: string;
  display_name: string;
  coarse_role: CoarseRole;
}

export interface Vacancy {
  vacancy_id: string;
  title: string;
  department_name: string | null;
  description: string | null;
  employment_type: string;
  opening_date: string | null;
  closing_date: string | null;
  status: "DRAFT" | "OPEN" | "CLOSED";
  created_at: string;
}

export interface ScoreFactor {
  factor: string;
  score: number;
  note: string;
}

/** ATS-style screening result: does this resume match the job, and why — not a resume review. */
export interface EvaluationDetail {
  match_score: number;
  recommendation: string;
  summary: string;
  score_factors: ScoreFactor[];
  strengths: string[];
  weaknesses: string[];
  matched_keywords: string[];
  missing_keywords: string[];
}

export interface Evaluation {
  score: number;
  overview: string;
  model: string | null;
  evaluated_at: string;
  detail: EvaluationDetail | null;
}

export type ApplicationStatus = "APPLIED" | "SHORTLISTED" | "REJECTED" | "WITHDRAWN";

/** Candidate-facing view of their own application — status only, no screening result. */
export interface ApplicationStatusView {
  application_id: string;
  vacancy_id: string;
  vacancy_title: string | null;
  application_status: ApplicationStatus;
  applied_at: string;
}

/** Manager-facing view of an application, including its AI screening result. */
export interface Application {
  application_id: string;
  vacancy_id: string;
  vacancy_title: string | null;
  application_status: ApplicationStatus;
  applied_at: string;
  evaluated: boolean;
  evaluation: Evaluation | null;
}

export interface ApplicationDetail extends Application {
  candidate_name: string | null;
  candidate_email: string | null;
}
