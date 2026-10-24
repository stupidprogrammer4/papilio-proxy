import type { ManagedService } from "./managedServices";

/** Owner policy and last native-account synchronization observation. */
export interface ManagedServiceSynchronization {
  service_id: string;
  enabled: boolean;
  interval_seconds: number;
  revision: string;
  generation: string;
  status: ManagedService["status"];
  attempts: string;
  error_code: string | null;
  worker_pid: number | null;
  lease_until: string | null;
  due_at: string;
  last_completed_at: string | null;
}
