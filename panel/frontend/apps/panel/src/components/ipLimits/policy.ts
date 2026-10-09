import type { IpLimitChoice } from "@papilio/api";

export function ipAllowanceText(policy: IpLimitChoice | null | undefined): string {
  if (!policy) return "No recorded source-IP restriction";
  if (!policy.enabled) return "Unlimited source IPs";
  if (!Number.isSafeInteger(policy.max_ips) || policy.max_ips <= 0) return "Invalid source-IP allowance";
  return policy.max_ips === 1 ? "1 source IP" : `Up to ${policy.max_ips} source IPs`;
}
