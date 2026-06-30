export type User = {
  user_id: string;
  email: string;
  display_name: string;
};

export type AuthRegisterResponse = {
  user: User;
  api_key: string;
  api_key_prefix: string;
};

export type AuthSessionResponse = {
  user: User;
  access_token: string;
  token_type: "bearer";
};

export type AuthMeResponse = {
  user: User;
};

export type Citation = {
  chunk_id: string;
  chunk_index: number;
  start_page_number: number;
  end_page_number: number;
};

export type SessionMessage = {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  answer_status: string | null;
  citations: Citation[];
  created_at: string;
  updated_at: string;
};

export type Session = {
  session_id: string;
  document_version_id: string;
  status: "ingesting" | "ready" | "failed";
  title: string;
  original_filename: string;
  pipeline_status: string;
  page_count: number | null;
  file_size_bytes: number;
  failure_message: string | null;
  last_activity_at: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  messages: SessionMessage[];
};

export type SearchMatch = {
  chunk_id: string;
  chunk_index: number;
  start_page_number: number;
  end_page_number: number;
  text: string;
  distance: number;
};

export type SessionAskResponse = {
  session_id: string;
  document_version_id: string;
  status: string;
  user_message: SessionMessage;
  assistant_message: SessionMessage;
  matches: SearchMatch[];
};

export type SessionEventPayload = {
  event: "session_status";
  session_id: string;
  document_version_id: string;
  status: "ingesting" | "ready" | "failed";
  pipeline_status: string;
  page_count: number | null;
  error_message: string | null;
};
