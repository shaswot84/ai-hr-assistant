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
  status: string;
  created_at: string;
}

export interface Evaluation {
  score: number;
  overview: string;
  model: string | null;
  evaluated_at: string;
}

export interface Application {
  application_id: string;
  vacancy_id: string;
  vacancy_title: string | null;
  application_status: string;
  applied_at: string;
  evaluated: boolean;
  evaluation: Evaluation | null;
}

export interface ApplicationDetail extends Application {
  candidate_name: string | null;
  candidate_email: string | null;
}
