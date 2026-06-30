import type { User } from "./types";

const AUTH_TOKEN_STORAGE_KEY = "pdfreader.authToken";
const USER_STORAGE_KEY = "pdfreader.user";

export function loadAuthToken() {
  return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
}

export function saveAuthToken(authToken: string) {
  window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, authToken);
}

export function clearAuthToken() {
  window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
}

export function loadUser(): User | null {
  const raw = window.localStorage.getItem(USER_STORAGE_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as User;
  } catch {
    window.localStorage.removeItem(USER_STORAGE_KEY);
    return null;
  }
}

export function saveUser(user: User) {
  window.localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
}

export function clearUser() {
  window.localStorage.removeItem(USER_STORAGE_KEY);
}
