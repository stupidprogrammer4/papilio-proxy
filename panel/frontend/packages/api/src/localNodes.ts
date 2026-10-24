import type { AgentRuntime, CertificatePolicy } from "./nodes";

export interface LocalNodeDefinition {
  node: { name: string; endpoint_url: string; runtime: AgentRuntime; certificate_policy: CertificatePolicy };
  core_name: string;
  inbound_tag: string;
  public_host: string;
  public_port: number;
  default_user_level: number;
  bind_address: string;
  bind_port: number;
}
export interface LocalDeliveryPolicy { enabled: boolean; retry_interval_seconds: number; max_attempts: number }
export interface LocalNodeDefaults { available: boolean; definition: LocalNodeDefinition; delivery: LocalDeliveryPolicy }
export interface LocalNodeOperation {
  id: string; request_key: string; status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  attempts: string; error_code: string | null; worker_pid: number | null;
  due_at: string; lease_until: string | null; completed_at: string | null; timeout_seconds: number;
}
export interface LocalNodeRead {
  node_id: string; core_id: string; inbound_id: string;
  definition: LocalNodeDefinition;
  delivery: LocalDeliveryPolicy & { revision: string };
  operation: LocalNodeOperation;
}
