export interface WorkerObservation {
  role: string;
  queue: string;
  worker_host: string;
  worker_pid: number;
  observed_at: string;
}

export interface SystemStatus {
  version: string;
  brand_title: string;
  environment: string;
  instance: string;
  database: boolean;
  cache: boolean;
  workers_ready: boolean;
  workers: WorkerObservation[];
  available_modules: string[];
}

export interface DiagnosticOperation {
  id: string;
  kind: "io" | "cpu";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  attempts: number;
  created_at: string;
  updated_at: string;
  result: { worker_pid: number; worker_host: string; database_ok: boolean | null; cache_ok: boolean | null; digest: string | null } | null;
  error_code: string | null;
  status_url: string;
}

export interface ManagedSchedule {
  key: "io-heartbeat" | "cpu-heartbeat" | "outbox";
  enabled: boolean;
  interval_seconds: number;
  changed_at: string;
}
