/** Current Django node onboarding contracts; separate from preserved network APIs. */
export interface AgentRuntime {
  listen_address: string;
  xray_api_address: string;
  request_timeout_seconds: number;
  read_header_timeout_seconds: number;
  idle_timeout_seconds: number;
  shutdown_timeout_seconds: number;
  max_body_bytes: number;
  max_grpc_reply_bytes: number;
}
export interface CertificatePolicy {
  validity_seconds: number;
  authority_validity_seconds: number;
  backdate_seconds: number;
}
export interface ManagedNode {
  id: string;
  deployment_id: string;
  owner_id: number;
  name: string;
  endpoint_url: string;
  runtime: AgentRuntime;
  certificate_policy: CertificatePolicy;
  credentials_ready: boolean;
  certificate_expires_at: string | null;
  last_reachable: boolean | null;
  last_checked_at: string | null;
  last_error_code: string | null;
  uptime_seconds: number | null;
  last_operation_id: string | null;
}
export interface NodeOperation {
  id: string;
  node_id: string;
  kind: "issue_credentials" | "check_connection";
  status: "queued" | "running" | "succeeded" | "failed";
  attempts: number;
  error_code: string | null;
  worker_pid: number | null;
}
export interface NodeRegistration { node: ManagedNode; operation: NodeOperation }
export interface ManagedNodePage { items: ManagedNode[]; count: number; page: number; page_size: number }
