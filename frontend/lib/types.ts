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

export interface FeedbackSection {
  summary: string;
  issues: string[];
}

export interface ImprovedBullet {
  original: string;
  improved: string;
  reason: string;
}

export interface JobMatch {
  match_score: number;
  summary: string;
  matched_keywords: string[];
  missing_keywords: string[];
}

export interface EvaluationDetail {
  overall_score: number;
  score_justification: string;
  clarity: FeedbackSection;
  impact: FeedbackSection;
  formatting: FeedbackSection;
  missing_sections: string[];
  improved_bullets: ImprovedBullet[];
  job_match: JobMatch | null;
}

export interface Evaluation {
  score: number;
  overview: string;
  model: string | null;
  evaluated_at: string;
  detail: EvaluationDetail | null;
}

export type ApplicationStatus = "APPLIED" | "SHORTLISTED" | "REJECTED" | "WITHDRAWN";

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
