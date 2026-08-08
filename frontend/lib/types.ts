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

/** Identity/contact info the AI extracted directly from the resume text (best-effort). */
export interface CandidateProfile {
  name: string;
  email: string;
  phone: string;
  location: string;
  headline: string;
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
  candidate_profile: CandidateProfile | null;
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

/** The AI provider connection used for resume screening — manager-editable, API key is write-only. */
export interface LlmConfig {
  api_base: string;
  model: string;
  api_key_set: boolean;
  is_default: boolean;
}

export type KnowledgeDocumentStatus =
  | "PENDING"
  | "PROCESSING"
  | "INDEXED"
  | "FAILED"
  | "DELETED";

export interface KnowledgeDocumentSummary {
  document_id: string;
  title: string;
  document_type: string;
  category: string;
  description: string | null;
  status: KnowledgeDocumentStatus;
  versions: number;
  current_chunks: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface KnowledgeJob {
  ingestion_job_id: string;
  document_version_id: string;
  status: KnowledgeDocumentStatus;
  failure_reason: string | null;
  error_message: string | null;
  parser_version: string | null;
  chunking_strategy: string | null;
  embedding_model: string | null;
  embedding_version: string | null;
  pipeline_version: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

export interface KnowledgeVersion {
  document_version_id: string;
  version_number: number;
  object_key: string;
  original_filename: string;
  checksum: string;
  is_current: boolean;
  previous_version_id: string | null;
  change_summary: string | null;
  status: KnowledgeDocumentStatus;
  uploaded_at: string | null;
  ingestion_jobs: KnowledgeJob[];
}

export interface KnowledgeDocumentDetail {
  document_id: string;
  title: string;
  document_type: string;
  category: string;
  description: string | null;
  status: KnowledgeDocumentStatus;
  current_chunks: number;
  created_at: string | null;
  updated_at: string | null;
  versions: KnowledgeVersion[];
}

export interface KnowledgeUploadResult {
  status: "PENDING" | "SKIPPED_DUPLICATE";
  document_id: string;
  document_version_id?: string;
  ingestion_job_id?: string;
  version_number: number;
  checksum: string;
  object_key?: string;
}

export interface KnowledgeDeleteResult {
  document_id: string;
  status: string;
  deleted_at: string | null;
  versions_removed: number;
  removed: number;
  failed: number;
}

export interface KnowledgeClearResult {
  deleted_documents: number;
  removed_objects: number;
  removed: number;
  failed: number;
}

export interface KnowledgeProvenance {
  parser_version: string | null;
  chunking_strategy: string | null;
  embedding_model: string | null;
  pipeline_version: string | null;
}

export interface KnowledgeCitation {
  chunk_id: string;
  document_id: string;
  document_version_id: string;
  version_number: number;
  document_title: string;
  category: string;
  page: number | null;
  section_title: string | null;
}

export interface KnowledgeChunk {
  chunk_id: string;
  document_title: string;
  category: string;
  section_title: string | null;
  page: number | null;
  text: string;
  parent_context: string | null;
  retrieval_score: number;
  reranker_score: number | null;
  confidence: number;
  provenance: KnowledgeProvenance | null;
  version_number: number;
}

export interface KnowledgeSearchResult {
  query: string;
  answer: string | null;
  grounded_context: string;
  confidence: number;
  low_confidence: boolean;
  citations: KnowledgeCitation[];
  chunks: KnowledgeChunk[];
}
