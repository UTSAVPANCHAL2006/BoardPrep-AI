// Data shapes returned by the backend API.

export type InterviewMode = "quick" | "full";

interface DAFProfile {
  hobbies: string[];
  optional_subject: string;
  work_experience: string[];
  education: string[];
  service_preferences: string[];
  hometown: string;
}

export interface RetrievedChunk {
  doc_type: string;
  text: string;
  preview: string;
  source_title?: string;
}

export interface CASource {
  title: string;
  daf_anchor: string;
  source: string;
  grounded: boolean;
  grounding_score: number;
}

export interface CABriefing {
  article_title: string;
  briefing_text: string;
  briefing_voice?: string;
  source?: string;
  source_url?: string;
  prelims_pointer?: string;
  mains_angle?: string;
  gs_link: string;
  interview_tip: string;
  gs_tags: string[];
  key_highlights: string[];
  key_concepts: Record<string, string>;
  audio_base64?: string;
  voice_error?: string;
  voice_language?: string;
}

export interface DAFFlag {
  field: string;
  daf_says: string;
  candidate_said: string;
  message: string;
}

interface Evaluation {
  clarity: string;
  factual_consistency: string;
  notes: string;
}

export interface UploadDAFResponse {
  session_id: string;
  daf_profile: DAFProfile;
}

export interface StartInterviewResponse {
  session_id: string;
  question: string;
  audio_base64: string;
  current_phase: string;
  articles_indexed: number;
  interview_mode: string;
  router_action: string;
  daf_focus: string;
  retrieved_chunks: RetrievedChunk[];
  ca_source?: CASource | null;
  ca_briefing?: CABriefing | null;
}

export interface RespondResponse {
  session_id: string;
  transcript: string;
  question: string;
  audio_base64: string;
  current_phase: string;
  interview_complete: boolean;
  evaluation_notes: string;
  evaluation: Evaluation | null;
  router_action: string;
  daf_flags: DAFFlag[];
  daf_focus: string;
  retrieved_chunks: RetrievedChunk[];
  ca_source?: CASource | null;
  ca_briefing?: CABriefing | null;
}

/** 0-10, or null when the phase was never reached ("not assessed"). */
export interface FeedbackScores {
  clarity: number | null;
  structure: number | null;
  daf_consistency: number | null;
  subject_depth: number | null;
  current_affairs: number | null;
  confidence: number | null;
}

/** One row per question, tied to the candidate's own words (quotes are checked by the server). */
export interface QuestionFeedback {
  turn: number;
  question: string;
  status: "answered" | "skipped" | "off_topic";
  quote: string;
  what_worked: string;
  improve: string;
  better_answer: string;
  /** How the answer was built; a tick is kept only if its evidence phrase is really in the answer. */
  checklist?: { item: string; label: string; ok: boolean; evidence: string }[];
  length?: { words: number; verdict: "too_short" | "short" | "good" | "too_long"; note: string };
}

export interface FeedbackReport {
  overall_summary: string;
  strengths: string[];
  improvements: string[];
  daf_consistency: string;
  subject_depth: string;
  current_affairs_awareness: string;
  scores?: FeedbackScores;
  phase_breakdown?: Record<string, string>;
  priority_actions?: string[];
  daf_flags?: DAFFlag[];
  question_feedback?: QuestionFeedback[];
  coverage?: { answered: number; asked: number; max_score: number };
}

export interface FeedbackReportResponse {
  session_id: string;
  report: FeedbackReport;
  daf_flags: DAFFlag[];
  interview_mode: string;
}
