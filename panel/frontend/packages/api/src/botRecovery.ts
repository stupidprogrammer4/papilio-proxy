/** Owner-scoped work/message metadata and explicit immutable recovery records. */
export type BotWorkState = "queued" | "running" | "done" | "failed" | "cancelled";
export type BotMessageState = "queued" | "sending" | "sent" | "retry" | "ambiguous" | "failed" | "cancelled";
export type BotRecoveryAction = "retry" | "cancel";
export type BotRecoveryKind = "work" | "messages";
export interface BotWorkInspection {
  id: string; event_id: string; bot_id: string; status: BotWorkState; revision: string;
  attempts: number; error_code: string | null; retry_at: string | null;
  lease_until: string | null; received_at: string; completed_at: string | null;
  actions: BotRecoveryAction[];
}
export interface BotMessageInspection {
  id: string; event_id: string; bot_id: string; owner_id: number; administrator: boolean;
  invoice_id: string | null; status: BotMessageState; revision: string; attempts: number;
  message_id: string | null; error_code: string | null; retry_at: string | null;
  created_at: string; lease_until: string | null; actions: BotRecoveryAction[];
}
export interface BotWorkPage { items: BotWorkInspection[]; count: number; page: number; page_size: number }
export interface BotMessagePage { items: BotMessageInspection[]; count: number; page: number; page_size: number }
export interface BotRecoveryDefinition { request_key: string; expected_revision: string; action: BotRecoveryAction; note: string }
export interface BotRecoveryAudit {
  id: string; actor_id: number; bot_id: string; request_key: string; expected_revision: string;
  action: BotRecoveryAction; note: string; previous_status: string; previous_attempts: number; created_at: string;
}
export interface BotWorkRecovery extends BotRecoveryAudit { work_id: string }
export interface BotMessageRecovery extends BotRecoveryAudit { message_id: string }
export interface BotWorkRecoveryPage { items: BotWorkRecovery[]; count: number; page: number; page_size: number }
export interface BotMessageRecoveryPage { items: BotMessageRecovery[]; count: number; page: number; page_size: number }
export interface BotWorkRecoveryResult { recovery: BotWorkRecovery; work: BotWorkInspection; created: boolean }
export interface BotMessageRecoveryResult { recovery: BotMessageRecovery; message: BotMessageInspection; created: boolean }
