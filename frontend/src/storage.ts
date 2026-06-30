import type { User } from "./types";

const API_KEY_STORAGE_KEY = "pdfreader.apiKey";
const USER_STORAGE_KEY = "pdfreader.user";

export function loadApiKey() {
  return window.localStorage.getItem(API_KEY_STORAGE_KEY);
}

export function saveApiKey(apiKey: string) {
  window.localStorage.setItem(API_KEY_STORAGE_KEY, apiKey);
}

export function clearApiKey() {
  window.localStorage.removeItem(API_KEY_STORAGE_KEY);
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
