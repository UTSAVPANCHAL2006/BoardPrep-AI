export type InterviewMode = "quick" | "full";

export interface DAFProfile {
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

export interface EnrichedArticle {
  title: string;
  source: string;
  published_at: string;
  url?: string;
  daf_anchor: string;
  key_highlights: string[];
  detailed_insights: string;
  key_concepts: Record<string, string>;
  gs_tags: string[];
  is_prelims_relevant: boolean;
}

export interface DailyCAResponse {
  articles: EnrichedArticle[];
  personalized: boolean;
  edition_date: string;
  is_live: boolean;
  is_fallback?: boolean;
  is_preparing?: boolean;
  article_count: number;
  voices_ready?: number;
  voices_total?: number;
}

export interface DAFFlag {
  field: string;
  daf_says: string;
  candidate_said: string;
  message: string;
}

export interface Evaluation {
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

export interface FeedbackScores {
  clarity: number;
  structure: number;
  daf_consistency: number;
  subject_depth: number;
  current_affairs: number;
  confidence: number;
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
}

export interface FeedbackReportResponse {
  session_id: string;
  report: FeedbackReport;
  daf_flags: DAFFlag[];
  interview_mode: string;
}
