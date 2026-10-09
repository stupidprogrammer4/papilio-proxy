import type { IpLimitChoice } from "./index";

export interface PurchasedIpPolicyRead {
  policy: IpLimitChoice;
  source: "plan_override" | "purchase_defaults";
  plan_id: number | null;
  captured_at: string;
}

export interface EffectiveIpPolicyRead {
  policy: IpLimitChoice | null;
  source: "subscription_override" | "purchased_snapshot" | "legacy_unrestricted";
  scope: "subscription";
  enforcement: "api_admission_only";
  core_enforcement_verified: false;
  transition?: IpPolicyTransitionRead | null;
}

export interface IpPolicyTransitionRead {
  status: "draining" | "blocked";
  target_policy: IpLimitChoice;
  mode: "drain_leases" | "require_closed_receipts";
  retry_at: string | null;
  reason: "ip_policy_draining" | "legacy_lease_history_unknown" | "closed_receipts_unavailable";
}

export interface IpPolicyTransitionOptions {
  default_mode: IpPolicyTransitionRead["mode"];
  choices: { mode: IpPolicyTransitionRead["mode"]; available: boolean; reason: "closed_receipts_unavailable" | null }[];
}

export interface PlanIpPolicyRead {
  policy: IpLimitChoice;
  source: "plan_override" | "current_defaults";
  scope: "subscription";
  enforcement: "api_admission_only";
  core_enforcement_verified: false;
}

export interface IpLimitCapacityRead {
  max_ips_ceiling: number;
  max_lease_seconds: number;
  max_ban_seconds: number;
}
