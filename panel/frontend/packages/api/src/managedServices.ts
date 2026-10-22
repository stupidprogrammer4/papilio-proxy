/** Native Django core/service contracts. IDs are UUIDs, separate from legacy APIs. */
export interface ManagedCore {
  id: string;
  owner_id: number;
  node_id: string;
  kind: "xray";
  name: string;
  xray: { default_user_level: number };
}
export interface ManagedInbound {
  id: string;
  core_id: string;
  tag: string;
  public_host: string;
  port: number;
}
export interface ManagedService {
  id: string;
  owner_id: number;
  core_id: string;
  inbound_id: string;
  name: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  attempts: number;
  error_code: string | null;
  worker_pid: number | null;
  lease_until: string | null;
}
export interface ManagedCorePage { items: ManagedCore[]; count: number; page: number; page_size: number }
export interface ManagedInboundPage { items: ManagedInbound[]; count: number; page: number; page_size: number }
export interface ManagedServicePage { items: ManagedService[]; count: number; page: number; page_size: number }
export interface XrayCoreCreate {
  request_key: string;
  node_id: string;
  name: string;
  default_user_level: number;
}
export interface XrayInboundCreate {
  request_key: string;
  tag: string;
  public_host: string;
  port: number;
}
export interface ManagedServiceCreate {
  request_key: string;
  core_id: string;
  inbound_id: string;
  name: string;
  user_level: number | null;
  identifier: string | null;
}
