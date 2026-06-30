import { FormEvent, useEffect, useRef, useState } from "react";

import { api } from "./api";
import { clearAuthToken, clearUser, loadAuthToken, loadUser, saveAuthToken, saveUser } from "./storage";
import type { Session, SessionEventPayload, SessionMessage, User } from "./types";

type AuthMode = "signin" | "signup";

const TOP_K = 5;

function formatBytes(bytes: number) {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function statusLabel(session: Session | null) {
  if (!session) {
    return "No active PDF";
  }
  if (session.status === "ready") {
    return "Ready to chat";
  }
  if (session.status === "failed") {
    return "Needs attention";
  }
  return `Processing ${session.pipeline_status}`;
}

export default function App() {
  const [authMode, setAuthMode] = useState<AuthMode>("signin");
  const [authToken, setAuthToken] = useState<string | null>(() => loadAuthToken());
  const [user, setUser] = useState<User | null>(() => loadUser());
  const [session, setSession] = useState<Session | null>(null);
  const [question, setQuestion] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [appError, setAppError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isAuthLoading, setIsAuthLoading] = useState(false);
  const [isSessionLoading, setIsSessionLoading] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [signupValues, setSignupValues] = useState({
    email: "",
    display_name: "",
    password: "",
  });
  const [signinValues, setSigninValues] = useState({
    email: "",
    password: "",
  });
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const eventSourceRef = useRef<{ close: () => void } | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages, session?.status]);

  useEffect(() => {
    if (!authToken) {
      return;
    }

    let cancelled = false;
    setIsSessionLoading(true);
    setAppError(null);
    api.getMe(authToken)
      .then((response) => {
        if (cancelled) {
          return;
        }
        setUser(response.user);
        saveUser(response.user);
        return api.getCurrentSession(authToken)
          .then((activeSession) => {
            if (!cancelled) {
              setSession(activeSession);
            }
          })
          .catch((error: Error) => {
            if (!cancelled && error.message !== "No active session found.") {
              setAppError(error.message);
            }
            if (!cancelled && error.message === "No active session found.") {
              setSession(null);
            }
          });
      })
      .catch((error: Error) => {
        if (cancelled) {
          return;
        }
        clearAuthToken();
        clearUser();
        setAuthToken(null);
        setUser(null);
        setAuthError(error.message);
      })
      .finally(() => {
        if (!cancelled) {
          setIsSessionLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [authToken]);

  useEffect(() => {
    if (!authToken || !session || (session.status !== "ingesting" && session.status !== "failed")) {
      return;
    }

    eventSourceRef.current?.close();
    const source = api.subscribeToSessionEvents(
      authToken,
      session.session_id,
      (payload) => {
        handleSessionEvent(payload);
      },
      (message) => {
        setAppError(message);
      },
    );
    eventSourceRef.current = source;

    return () => {
      source.close();
    };
  }, [authToken, session?.session_id, session?.status]);

  function handleSessionEvent(payload: SessionEventPayload) {
    setSession((currentSession) => {
      if (!currentSession || currentSession.session_id !== payload.session_id) {
        return currentSession;
      }
      return {
        ...currentSession,
        status: payload.status,
        pipeline_status: payload.pipeline_status,
        page_count: payload.page_count,
        failure_message: payload.error_message,
      };
    });
  }

  async function handleSignUp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsAuthLoading(true);
    setAuthError(null);
    setSuccessMessage(null);
    try {
      const response = await api.register(signupValues);
      saveAuthToken(response.access_token);
      saveUser(response.user);
      setAuthToken(response.access_token);
      setUser(response.user);
      setSigninValues({ email: signupValues.email, password: "" });
      setSuccessMessage("Account created. You are now signed in on this browser.");
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Could not create your account.");
    } finally {
      setIsAuthLoading(false);
    }
  }

  async function handleSignIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
      setIsAuthLoading(true);
      setAuthError(null);
      setSuccessMessage(null);
    try {
      const response = await api.login(signinValues);
      saveAuthToken(response.access_token);
      saveUser(response.user);
      setAuthToken(response.access_token);
      setUser(response.user);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Could not sign you in.");
    } finally {
      setIsAuthLoading(false);
    }
  }

  async function handleUpload(file: File) {
    if (!authToken) {
      return;
    }
    setIsSessionLoading(true);
    setAppError(null);
    setSuccessMessage(null);
    try {
      const nextSession = await api.createSession(authToken, file);
      setSession(nextSession);
    } catch (error) {
      setAppError(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setIsSessionLoading(false);
    }
  }

  async function handleQuestionSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!authToken || !session || !question.trim()) {
      return;
    }
    setIsAsking(true);
    setAppError(null);
    try {
      const response = await api.askQuestion(authToken, session.session_id, {
        question: question.trim(),
        top_k: TOP_K,
      });
      setSession((currentSession) => {
        if (!currentSession) {
          return currentSession;
        }
        const nextMessages = [...currentSession.messages, response.user_message, response.assistant_message];
        return {
          ...currentSession,
          status: response.status as Session["status"],
          message_count: nextMessages.length,
          messages: nextMessages,
          updated_at: response.assistant_message.updated_at,
          last_activity_at: response.assistant_message.updated_at,
        };
      });
      setQuestion("");
    } catch (error) {
      setAppError(error instanceof Error ? error.message : "Could not send that question.");
    } finally {
      setIsAsking(false);
    }
  }

  async function handleEndSession() {
    if (!authToken || !session) {
      return;
    }
    setAppError(null);
    try {
      await api.endSession(authToken, session.session_id);
      setSession(null);
      setSuccessMessage("Session ended. Upload another PDF whenever you're ready.");
      eventSourceRef.current?.close();
    } catch (error) {
      setAppError(error instanceof Error ? error.message : "Could not end the session.");
    }
  }

  async function handleSignOut() {
    if (authToken) {
      try {
        await api.logout(authToken);
      } catch {
        // Local sign-out should still complete even if the token is already invalid.
      }
    }
    clearAuthToken();
    clearUser();
    setAuthToken(null);
    setUser(null);
    setSession(null);
    setQuestion("");
    setSigninValues({ email: "", password: "" });
    eventSourceRef.current?.close();
  }

  const isAuthenticated = Boolean(authToken && user);

  if (!isAuthenticated) {
    return (
      <div className="auth-shell">
        <div className="auth-backdrop" />
        <section className="auth-panel">
          <div className="auth-brand">
            <p className="eyebrow">Temporary PDF chat</p>
            <h1>Talk to one document at a time.</h1>
            <p className="subtle">
              Create an account or log in, then jump straight into an upload-first chat workspace for one live PDF.
            </p>
          </div>

          <div className="auth-card">
            <div className="auth-tabs">
              <button className={authMode === "signin" ? "active" : ""} onClick={() => setAuthMode("signin")} type="button">
                Log in
              </button>
              <button className={authMode === "signup" ? "active" : ""} onClick={() => setAuthMode("signup")} type="button">
                Sign up
              </button>
            </div>

            {authMode === "signin" ? (
              <form className="auth-form" onSubmit={handleSignIn}>
                <label>
                  Email
                  <input
                    type="email"
                    value={signinValues.email}
                    onChange={(event) => setSigninValues((current) => ({ ...current, email: event.target.value }))}
                    required
                  />
                </label>
                <label>
                  Password
                  <input
                    type="password"
                    value={signinValues.password}
                    onChange={(event) => setSigninValues((current) => ({ ...current, password: event.target.value }))}
                    required
                  />
                </label>
                <button className="primary-button" disabled={isAuthLoading} type="submit">
                  {isAuthLoading ? "Signing in..." : "Log in"}
                </button>
              </form>
            ) : (
              <form className="auth-form" onSubmit={handleSignUp}>
                <label>
                  Email
                  <input
                    type="email"
                    value={signupValues.email}
                    onChange={(event) => setSignupValues((current) => ({ ...current, email: event.target.value }))}
                    required
                  />
                </label>
                <label>
                  Display name
                  <input
                    type="text"
                    value={signupValues.display_name}
                    onChange={(event) => setSignupValues((current) => ({ ...current, display_name: event.target.value }))}
                    required
                  />
                </label>
                <label>
                  Password
                  <input
                    type="password"
                    value={signupValues.password}
                    onChange={(event) => setSignupValues((current) => ({ ...current, password: event.target.value }))}
                    required
                  />
                </label>
                <button className="primary-button" disabled={isAuthLoading} type="submit">
                  {isAuthLoading ? "Creating account..." : "Create account"}
                </button>
              </form>
            )}

            {authError ? <p className="error-banner">{authError}</p> : null}
            {successMessage ? <p className="success-banner">{successMessage}</p> : null}
          </div>
        </section>
      </div>
    );
  }

  const currentUser = user!;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-header">
          <div>
            <p className="eyebrow">pdfReader</p>
          </div>
          <button className="ghost-button" onClick={handleSignOut} type="button">
            Sign out
          </button>
        </div>

        <section className="profile-card">
          <p className="profile-name">{currentUser.display_name}</p>
          <p className="profile-status">{statusLabel(session)}</p>
        </section>

        <section className="session-card">
          <div className="session-card-header">
            <h3>Session</h3>
            {session ? (
              <button className="ghost-button danger" onClick={handleEndSession} type="button">
                End
              </button>
            ) : null}
          </div>

          {session ? (
            <>
              <dl className="meta-list">
                <div>
                  <dt>Status</dt>
                  <dd>{session.status}</dd>
                </div>
                <div>
                  <dt>Pipeline</dt>
                  <dd>{session.pipeline_status}</dd>
                </div>
                <div>
                  <dt>Pages</dt>
                  <dd>{session.page_count ?? "—"}</dd>
                </div>
                <div>
                  <dt>Size</dt>
                  <dd>{formatBytes(session.file_size_bytes)}</dd>
                </div>
              </dl>
              {session.failure_message ? <p className="error-inline">{session.failure_message}</p> : null}
            </>
          ) : (
            <p className="subtle">No active session yet. Upload one PDF to begin.</p>
          )}
        </section>
      </aside>

      <main className="chat-shell">
        <header className="chat-header">
          <div>
            <p className="eyebrow">Live backend</p>
            <h1>{session ? session.original_filename : "Upload a PDF to start"}</h1>
          </div>
          <span className={`status-pill ${session?.status ?? "idle"}`}>
            {session ? session.status : "idle"}
          </span>
        </header>

        {appError ? <div className="toast error-banner">{appError}</div> : null}
        {successMessage ? <div className="toast success-banner">{successMessage}</div> : null}

        {!session ? (
          <section className="empty-state">
            <div className="empty-card">
              <p className="eyebrow">Start here</p>
              <h2>Drop in one PDF, wait for indexing, then chat.</h2>
              <p className="subtle">
                This frontend uses the backend’s temporary-session model, so one upload becomes one active workspace.
              </p>
              <input
                accept="application/pdf"
                className="hidden-input"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) {
                    void handleUpload(file);
                    event.target.value = "";
                  }
                }}
                ref={fileInputRef}
                type="file"
              />
              <button className="primary-button wide" disabled={isSessionLoading} onClick={() => fileInputRef.current?.click()} type="button">
                {isSessionLoading ? "Uploading..." : "Upload PDF"}
              </button>
            </div>
          </section>
        ) : (
          <>
            <section className="messages-panel">
              {session.messages.length === 0 ? (
                <div className="empty-chat-state">
                  <h2>{session.status === "ready" ? "Your document is ready." : "We’re preparing your document."}</h2>
                  <p className="subtle">
                    {session.status === "ready"
                      ? "Ask a question about the PDF and the assistant will answer with chunk-level citations."
                      : `Current stage: ${session.pipeline_status}. This screen listens for live updates from the backend.`}
                  </p>
                </div>
              ) : (
                session.messages.map((message) => (
                  <MessageBubble key={message.message_id} message={message} />
                ))
              )}
              <div ref={messagesEndRef} />
            </section>

            <form className="composer" onSubmit={handleQuestionSubmit}>
              <textarea
                disabled={session.status !== "ready" || isAsking}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder={session.status === "ready" ? "Ask about the document..." : "Wait until ingestion is finished..."}
                rows={3}
                value={question}
              />
              <div className="composer-footer">
                <span className="subtle">Top {TOP_K} chunks per answer</span>
                <button className="primary-button" disabled={session.status !== "ready" || isAsking || !question.trim()} type="submit">
                  {isAsking ? "Sending..." : "Send"}
                </button>
              </div>
            </form>
          </>
        )}
      </main>
    </div>
  );
}

function MessageBubble({ message }: { message: SessionMessage }) {
  return (
    <article className={`message-bubble ${message.role}`}>
      <div className="message-role">{message.role === "user" ? "You" : "Assistant"}</div>
      <p>{message.content}</p>
      {message.answer_status && message.role === "assistant" ? (
        <div className="answer-footer">
          <span className={`answer-status ${message.answer_status}`}>{message.answer_status}</span>
          {message.citations.length > 0 ? (
            <div className="citation-row">
              {message.citations.map((citation) => (
                <span className="citation-pill" key={`${citation.chunk_id}-${citation.chunk_index}`}>
                  p. {citation.start_page_number}
                  {citation.end_page_number !== citation.start_page_number ? `-${citation.end_page_number}` : ""}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
