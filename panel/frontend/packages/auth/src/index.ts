import { defineStore } from "pinia";
import { ref } from "vue";
import { request, setCsrf, type Session } from "@papilio/api";

export const useAuth = defineStore("auth", () => {
  const session = ref<Session | null>(null);
  const checked = ref(false);
  async function restore(): Promise<void> {
    try {
      session.value = await request<Session>("/v1/admin/auth/me");
      setCsrf(session.value.csrf_token);
    } catch {
      session.value = null;
      setCsrf("");
    } finally {
      checked.value = true;
    }
  }
  async function login(username: string, password: string): Promise<void> {
    const csrf = await request<{ csrf_token: string }>("/v1/admin/auth/csrf");
    setCsrf(csrf.csrf_token);
    session.value = await request<Session>("/v1/admin/auth/login", "POST", { username, password });
    setCsrf(session.value.csrf_token);
    checked.value = true;
  }
  async function logout(): Promise<void> {
    await request<void>("/v1/admin/auth/logout", "POST");
    session.value = null;
    setCsrf("");
  }
  function can(scope: string, level = "read"): boolean {
    const grants = session.value?.scopes ?? [];
    return grants.includes("*") || grants.includes(`${scope}:*`) || grants.includes(`${scope}:${level}`);
  }
  return { session, checked, restore, login, logout, can };
});


import { ApiError, setCustomerCsrf, type CustomerSession } from "@papilio/api";
export const useCustomerAuth = defineStore("customer-auth", () => {
  const session = ref<CustomerSession | null>(null); const checked = ref(false); const error = ref("");
  async function restore(): Promise<void> {
    error.value = "";
    try { session.value = await request<CustomerSession>("/v1/customer/auth/me"); setCustomerCsrf(session.value.csrf_token); }
    catch (cause) { session.value = null; setCustomerCsrf(""); if (!(cause instanceof ApiError && cause.status === 401)) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
    finally { checked.value = true; }
  }
  async function exchange(token: string): Promise<void> {
    session.value = await request<CustomerSession>("/v1/customer/auth/exchange", "POST", { token });
    setCustomerCsrf(session.value.csrf_token); checked.value = true; error.value = "";
  }
  async function logout(): Promise<void> { await request<void>("/v1/customer/auth/logout", "POST"); session.value = null; setCustomerCsrf(""); }
  return { session, checked, error, restore, exchange, logout };
});

import { setResellerCsrf, type ResellerSession } from "@papilio/api";
export const useResellerAuth = defineStore("reseller-auth", () => {
  const session = ref<ResellerSession|null>(null);
  const checked = ref(false);
  const error = ref("");
  async function restore(): Promise<void> {
    error.value = "";
    try { session.value = await request<ResellerSession>("/v1/reseller/auth/me"); setResellerCsrf(session.value.csrf_token); }
    catch (cause) {
      session.value = null; setResellerCsrf("");
      if (!(cause instanceof ApiError && cause.status === 401)) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again.";
    } finally { checked.value = true; }
  }
  async function login(username: string, password: string): Promise<void> {
    session.value = await request<ResellerSession>("/v1/reseller/auth/login", "POST", { username, password });
    setResellerCsrf(session.value.csrf_token); checked.value = true; error.value = "";
  }
  async function logout(): Promise<void> {
    await request<void>("/v1/reseller/auth/logout", "POST"); session.value = null; setResellerCsrf("");
  }
  function can(area: string, level = "read"): boolean {
    const scopes = session.value?.scopes ?? [];
    return scopes.includes("*") || scopes.includes(`${area}:${level}`);
  }
  return { session, checked, error, restore, login, logout, can };
});
