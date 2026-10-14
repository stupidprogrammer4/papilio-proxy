import type { IpLimitChoice } from "@papilio/api";

export type IpAllowanceLabels = {
  none: string;
  unlimited: string;
  invalid: string;
  one: string;
  many: (count: number) => string;
};

const englishLabels: IpAllowanceLabels = {
  none: "No recorded source-IP restriction",
  unlimited: "Unlimited source IPs",
  invalid: "Invalid source-IP allowance",
  one: "1 source IP",
  many: count => `Up to ${count} source IPs`,
};

export function ipAllowanceText(policy: IpLimitChoice | null | undefined, labels = englishLabels): string {
  if (!policy) return labels.none;
  if (!policy.enabled) return labels.unlimited;
  if (!Number.isSafeInteger(policy.max_ips) || policy.max_ips <= 0) return labels.invalid;
  return policy.max_ips === 1 ? labels.one : labels.many(policy.max_ips);
}
