import type {
  AuthMeResponse,
  AuthSessionResponse,
  Session,
  SessionAskResponse,
  SessionEventPayload,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.trim() || "";

type RequestOptions = {
  method?: string;
  apiKey?: string;
  body?: BodyInit | null;
  headers?: Record<string, string>;
};

type SessionEventSubscription = {
  close: () => void;
};

async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers: {
      ...(options.apiKey ? { Authorization: `Bearer ${options.apiKey}` } : {}),
      ...options.headers,
    },
    body: options.body,
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}.`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload.detail !== undefined) {
        detail = normalizeErrorDetail(payload.detail);
      }
    } catch {
      // Ignore JSON parse failures and preserve the fallback message.
    }
    throw new Error(detail);
  }

  return (await response.json()) as T;
}

function normalizeErrorDetail(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail.map((item) => normalizeErrorDetail(item)).filter(Boolean);
    return messages.length > 0 ? messages.join(" ") : "Request failed.";
  }

  if (detail && typeof detail === "object") {
    if ("msg" in detail && typeof detail.msg === "string") {
      return detail.msg;
    }
    return JSON.stringify(detail);
  }

  return "Request failed.";
}

export const api = {
  baseUrl: API_BASE_URL,

  register(payload: { email: string; display_name: string; password: string }) {
    return apiRequest<AuthSessionResponse>("/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  login(payload: { email: string; password: string }) {
    return apiRequest<AuthSessionResponse>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  getMe(apiKey: string) {
    return apiRequest<AuthMeResponse>("/auth/me", { apiKey });
  },

  logout(apiKey: string) {
    return apiRequest<{ message: string }>("/auth/logout", {
      method: "POST",
      apiKey,
    });
  },

  getCurrentSession(apiKey: string) {
    return apiRequest<Session>("/sessions/current", { apiKey });
  },

  createSession(apiKey: string, file: File) {
    const formData = new FormData();
    formData.append("file", file);
    return apiRequest<Session>("/sessions", {
      method: "POST",
      apiKey,
      body: formData,
    });
  },

  askQuestion(apiKey: string, sessionId: string, payload: { question: string; top_k: number }) {
    return apiRequest<SessionAskResponse>(`/sessions/${sessionId}/messages`, {
      method: "POST",
      apiKey,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  endSession(apiKey: string, sessionId: string) {
    return apiRequest<{ session_id: string; status: string; message: string }>(`/sessions/${sessionId}/end`, {
      method: "POST",
      apiKey,
    });
  },

  subscribeToSessionEvents(
    apiKey: string,
    sessionId: string,
    onEvent: (payload: SessionEventPayload) => void,
    onError: (message: string) => void,
  ): SessionEventSubscription {
    const controller = new AbortController();
    void consumeSessionEvents(apiKey, sessionId, controller.signal, onEvent, onError);
    return {
      close: () => controller.abort(),
    };
  },
};

async function consumeSessionEvents(
  apiKey: string,
  sessionId: string,
  signal: AbortSignal,
  onEvent: (payload: SessionEventPayload) => void,
  onError: (message: string) => void,
) {
  try {
    const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}/events`, {
      headers: {
        Authorization: `Bearer ${apiKey}`,
        Accept: "text/event-stream",
      },
      signal,
    });

    if (!response.ok) {
      let detail = `Session event stream failed with status ${response.status}.`;
      try {
        const payload = (await response.json()) as { detail?: unknown };
        if (payload.detail !== undefined) {
          detail = normalizeErrorDetail(payload.detail);
        }
      } catch {
        // Preserve the fallback message when the response is not JSON.
      }
      throw new Error(detail);
    }

    if (!response.body) {
      throw new Error("Session event stream did not include a response body.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const segments = buffer.split("\n\n");
      buffer = segments.pop() ?? "";

      for (const segment of segments) {
        const payload = parseSseEvent(segment);
        if (payload) {
          onEvent(payload);
        }
      }
    }
  } catch (error) {
    if (signal.aborted) {
      return;
    }
    onError(error instanceof Error ? error.message : "The live status stream disconnected.");
  }
}

function parseSseEvent(chunk: string) {
  const lines = chunk.split("\n");
  let eventName = "";
  let data = "";

  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    }
    if (line.startsWith("data:")) {
      data += line.slice(5).trim();
    }
  }

  if (eventName !== "session_status" || !data) {
    return null;
  }

  return JSON.parse(data) as SessionEventPayload;
}
