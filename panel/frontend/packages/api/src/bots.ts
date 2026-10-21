/** Operator-owned bot configuration and pairing; credentials are never returned. */
export interface BotRuntime {
  api_base_url: string;
  poll_timeout_seconds: number;
  http_timeout_seconds: number;
  update_limit: number;
  max_response_bytes: number;
  pairing_ttl_seconds: number;
  failure_retry_seconds: number;
}
export interface BotSchedule { enabled: boolean; interval_seconds: number }
export interface BotDefaults { runtime: BotRuntime; schedule: BotSchedule }
export interface BotDraft extends BotDefaults { label: string; token: string }
export interface ManagedBot extends BotDefaults {
  id: string;
  owner_id: number;
  label: string;
  revision: string;
  telegram_id: number | null;
  username: string | null;
  verified: boolean;
  admin_chat_id: number | null;
  last_poll_at: string | null;
  last_error_code: string | null;
  next_update_id: string;
  retry_at: string | null;
}
export interface ManagedBotPage { items: ManagedBot[]; count: number; page: number; page_size: number }
export interface BotPairingGrant { url: string; expires_at: string }
