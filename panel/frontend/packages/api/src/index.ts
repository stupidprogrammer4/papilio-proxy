export * from "./ipPolicies";
export * from "./system";
import type { PurchasedIpPolicyRead, EffectiveIpPolicyRead, PlanIpPolicyRead, IpLimitCapacityRead, IpPolicyTransitionOptions } from "./ipPolicies";
export * from "./smsOrigins";

export interface PageMeta {
  pager?: {
    total_items: number;
    total_pages: number;
    has_prev: boolean;
    has_next: boolean;
  };
}

export interface Page<T> { data: T[]; meta: PageMeta }
export interface Plan { effective_ip_policy?: PlanIpPolicyRead; quota_policy: QuotaPolicy | null; fulfillment: FulfillmentPolicy | null; ip_limit: IpLimitChoice | null; group_id: number | null; id: number; code: string; title: string; quota_bytes: number|null; duration_days: number|null; price_rial: number; sort_order: number; is_active: boolean }
export interface Customer { services_enabled: boolean; renewals_enabled: boolean; service_hold_pending: boolean; service_hold_clock: "continue" | "pause" | null; id: number; display_name: string; telegram_id: number | null; is_active: boolean }
export interface Topup { id: number; revision:number; customer_id: number; amount_rial: number; requested_amount_rial?:number|null; payment_identifier_mode?:PaymentIdentifierMode; payment_identifier_code4?:string|null; status: string; bank_reference: string | null; approved_by_staff_id: number | null; approved_by_device_id?: number | null; approved_by_sms_id?: number | null }
export interface Subscription { purchased_ip_policy?: PurchasedIpPolicyRead|null; effective_ip_policy?: EffectiveIpPolicyRead; commerce?: CustomerPriceQuote|null; entitlement_kind: "paid"|"trial"; suspended_at: string | null; suspension_clock: "continue" | "pause" | null; suspension_reason: string | null; suspended_by_staff_id: number | null; suspended_by_reseller_account_id: number | null; used_bytes: number; provisioning_managed: boolean; activated_at: string | null; group_id: number | null; id: number; customer_id: number; plan_id: number; quota_bytes: number|null; price_rial: number; duration_days: number|null; expires_at: string|null; status: string; auto_renew: boolean; renewal_count: number; failure_reason: string | null }
export interface WalletBalance { customer_id: number; balance_rial: number }
export type CheckoutTransientConflictMode = "retry_until_expiry"|"require_confirmation";
export interface PurchaseCheckoutPolicy { transient_conflict_action?:CheckoutTransientConflictMode; enabled:boolean; admission_mode:"require_ready_bundle"|"allow_manual_profiles"; default_expiry_seconds:number }
export interface CheckoutOffer { effective_ip_policy?: PlanIpPolicyRead|null; customer_id:number;plan_id:number;price_rial:number;offer_sha256:string;plan_title:string;quota_bytes:number|null;duration_days:number|null;membership_count:number;delivery_mode:"configured_bundle"|"manual_profiles";captured_at:string;default_expiry_seconds?:number }
export interface CheckoutIntent { id:number;customer_id:number;plan_id:number;revision:number;state:"awaiting_funding"|"ready"|"action_required"|"purchased"|"cancelled"|"expired";funding_mode:"wallet_only"|"approved_topup";delivery_mode:"configured_bundle"|"manual_profiles";price_rial:number;offer_sha256:string;auto_renew:boolean;expires_at:string;changed_offer_action:"require_confirmation"|"cancel";topup_id:number|null;subscription_id:number|null;reason_code:string|null }
export interface CheckoutCreate { request_key:string;plan_id:number;funding_mode:CheckoutIntent["funding_mode"];expected_offer_sha256:string;expected_price_rial:number;auto_renew:boolean;expiry_seconds:number;changed_offer_action:CheckoutIntent["changed_offer_action"];topup_amount_rial:number|null;destination_id:number|null }
export interface CheckoutRetire { request_key:string }
export interface CheckoutRetirement { request_key:string;status:"retired"|"purchased";intent:CheckoutIntent|null }
export interface CheckoutCancel { request_key:string;expected_revision:number }
export interface CheckoutReconfirm extends CheckoutCancel { expected_offer_sha256:string;expected_price_rial:number }
export interface SmsEvent { device_id?: number | null; id: number; event_id: string; sender: string; amount_rial: number | null; bank_reference: string | null; sent_at: string; parser_revision_id?:number|null; parser_definition_sha256?:string|null; receiving_realm_id?:number|null; receiving_alias_id?:number|null; captured_destination_id?:number|null; captured_destination_revision?:number|null; direction?:"credit"|"debit"|"unknown"|null; parse_reason_code?:string|null; origin_reason_code?:string|null; declared_notification_sha256?:string|null; balance_rial?:number|null; origin_kind?:"direct_sms"|"forwarded"|"imported"|"manual"|null; original_sender?:string|null; original_provider_timestamp_ms?:number|null; canonicalization_revision?:1|null; canonical_message_digest?:string|null; origin_identity_sha256?:string|null }
export type NodeAdapterKind = "xray"|"sing_box"|"openvpn"|"wireguard"|"hysteria";
export type NodeCapabilityReason = "adapter_unavailable"|"counter_adapter_unavailable"|"strict_enforcement_unavailable"|"runtime_ip_adapter_unavailable"|"device_admission_unavailable"|"engine_completion_unavailable"|"protocol_matrix_not_reported"|"binary_reference_unverified"|"core_binary_unavailable"|"capability_binary_unavailable"|"capability_binary_invalid"|"capability_binary_capacity"|"capability_probe_timeout"|"capability_binary_changed"|"capability_output_capacity"|"capability_probe_unavailable"|"capability_version_unavailable"|"sing_box_v2ray_api_build_unavailable";
export type NodeCapabilityScope = "local_immutable_document_validation"|"fresh_authorized_immutable_bundle_lifecycle"|"live_exact_installed_membership_only"|"merged_xray_scoped_cumulative_counters"|"whole_merged_core_stop_with_poll_overrun"|"no_strict_quota_or_expiry_guarantee"|"source_ip_not_device_identity"|"no_device_count_guarantee"|"unresolved_grants_preserved"|"export_or_binary_version_is_not_protocol_acceptance";
export interface NodeOperationCapability { implemented:boolean;compatibility:"reference_match"|"unverified"|"unavailable";scope:NodeCapabilityScope;reason_code:NodeCapabilityReason|null }
export interface NodeAdapterCapability { kind:NodeAdapterKind;adapter_revision:1;executable:{available:boolean;version:string|null;sha256:string|null;v2ray_api_build_tag:boolean;reason_code:NodeCapabilityReason|null};validation:NodeOperationCapability;installation:NodeOperationCapability;installed_membership:NodeOperationCapability;counters:NodeOperationCapability;polled_stop:NodeOperationCapability;strict_quota_expiry:NodeOperationCapability;ip_admission:NodeOperationCapability;device_admission:NodeOperationCapability;final_counters:NodeOperationCapability;protocol_matrix:NodeOperationCapability }
export interface NodeCapabilityObservation { observation_id:number;node_id:number;node_code:string;report_id:string;report_sha256:string;observed_at:string;received_at:string;evidence_kind:"authenticated_node_self_report";report:{schema_revision:1;observed_at:string;adapters:NodeAdapterCapability[]} }
export interface NodeCapabilityLatest { node_id:number;status:"absent"|"fresh"|"stale"|"future";observation:NodeCapabilityObservation|null }
export interface NodeEndpoint { id: number; code: string; label: string; public_host: string; public_port: number; protocol: string; is_enabled: boolean }
export interface RegisteredNode { node: NodeEndpoint; agent_key: string }
export interface NodeQuality { node_id: number; code: string; label: string; protocol: string; client_network: string; sample_count: number; successful_count: number; average_latency_ms: number | null; score: number | null }
export interface Session { username: string; scopes: string[]; csrf_token: string }

const messages: Record<string, string> = {
  topup_revision_conflict: "This top-up changed. Reload the current version before reviewing it.",
  sms_origins_unavailable: "SMS parsing and origin management is unavailable under the current operational policy.",
  sms_origin_admission_unavailable: "SMS policy admission is unavailable. Your draft is retained.",
  sms_parser_revision_conflict: "This parser profile changed. Check its current revision; your draft is retained.",
  sms_receiving_realm_revision_conflict: "This receiving account changed. Check its current revision; your draft is retained.",
  sms_parser_profile_capacity: "The configured parser profile capacity has been reached.",
  sms_receiving_realm_capacity: "The configured receiving account capacity has been reached.",
  sms_parser_profile_not_found: "This parser profile was not found.",
  sms_parser_revision_not_found: "This parser revision was not found.",
  sms_receiving_realm_not_found: "This receiving account was not found.",
  sms_review_revision_conflict: "The SMS source or receiving account changed. Reload the recorded decision and review its current revisions; your approval draft is retained.",
  sms_candidate_capacity: "Matching payments exceed the configured review capacity. Refine the receiving-account association before continuing.",
  payment_destination_revision_conflict: "This payment destination changed. Check its current revision; your draft is retained.",
  capability_observations_disabled: "Node capability reporting is disabled in the application policy.",
  capability_observations_unconfigured: "Node capability reporting has not been configured.",
  checkout_attempt_retired: "This purchase request was cancelled. Review the current offer before starting a new checkout.",
  checkout_offer_busy: "The connection inventory is being updated. Refresh the offer and retry; no new purchase was made.",
  checkout_disabled: "Automated checkout is unavailable under the current policy.",
  checkout_offer_changed: "The plan or price changed. Review the current offer before confirming.",
  checkout_bundle_required: "This plan needs a configured delivery bundle.",
  checkout_bundle_unavailable: "The plan's connection options are unavailable. No purchase was made.",
  checkout_revision_conflict: "This checkout changed. Refresh its status; your draft is retained.",
  checkout_request_conflict: "This request key already belongs to different checkout details.",
  checkout_reseller_funding_unsupported: "Use your reseller's purchase workflow for this account.",
  runtime_disabled: "Runtime control is disabled in application settings.",
  runtime_start_disabled: "Starting cores is disabled in application settings.",
  runtime_revision_conflict: "The runtime control revision changed. Your draft is retained; refresh and review the current state.",
  runtime_command_busy: "A runtime command is already pending for this core. Review its result before submitting another.",
  runtime_snapshot_stale: "Configuration or customer eligibility changed. Capture a current revision before applying it.",
  runtime_revision_required: "Select an immutable runtime revision for this action.",
  runtime_revision_not_found: "The selected revision is unavailable for this core.",
  runtime_request_conflict: "This request key was already used with different command data.",
  tier_capacity:"Tier count exceeds configured capacity.",tier_revision_conflict:"This tier changed. Your draft is retained; review the current record.",loyalty_revision_conflict:"Loyalty rules changed. Refresh the revision before retrying.",loyalty_unavailable:"Loyalty is not configured.",loyalty_capacity:"Loyalty rules exceed operational capacity.",
  sms_devices_disabled: "SMS device enrollment is disabled by operational settings.",
  sms_device_sender_capacity: "Sender count exceeds configured capacity.",
  sms_device_expired: "Choose a future expiry for an enabled device.",
  sms_device_expiry_capacity: "Expiry exceeds the configured maximum key validity.",
  sms_device_not_found: "This SMS device was not found.",
  sms_device_revision_conflict: "The device changed. Refresh its record; your draft is retained.",
  trial_disabled:"Trials are disabled.", trial_capacity:"Trial policy exceeds operational capacity.", trial_claim_limit:"This account has reached its trial claim limit.", trial_paid_customer:"This offer requires no previous paid purchase.", trial_active_exists:"An active trial subscription already exists.", trial_cooldown:"The trial cooldown has not ended.", trial_not_renewable:"Trial subscriptions cannot renew automatically.",
  automation_revision_conflict: "The schedule changed. Review the current revision before retrying.",
  automation_policy_capacity: "Policy exceeds operational capacity.",
  automation_recheck_mode: "The recheck method for this operation cannot be replaced.",
  customer_access_changed: "Customer access changed. Refresh the record.",
  customer_access_key_reused: "This key was already used for a different change.",
  customer_hold_clock_changed: "The active suspension clock policy cannot change. Suspension history is retained.",
  customer_services_disabled: "Customer service access is paused or node revocation is incomplete.",
  customer_hold_policy_missing: "Suspension information is incomplete. Review customer access settings.",
  subscription_already_activated: "This service was activated. Initial-purchase refunds are unavailable.",
  subscription_control_key_reused: "This operation key was already used with different data.",
  subscription_suspend_unavailable: "Only active subscriptions can be suspended.",
  subscription_resume_unavailable: "Resume is available after all nodes confirm revocation.",
  subscription_resume_consumed: "Remaining time or quota is insufficient to resume.",
  subscription_suspension_changed: "The suspension reason or policy changed. Refresh the record.",
  staff_last_owner: "The final active account with full access cannot be disabled.",
  staff_access_changed: "Staff access changed. Refresh the account.",
  staff_delegation_denied: "You cannot grant permissions beyond your own access or modify a higher-privilege account.",
  notification_not_found: "This notification is unavailable in this account.",
  notification_disabled: "Notification creation is unavailable under the current policy.",
  notification_message_length: "The notification exceeds the allowed length.",
  notification_event_reused: "This request key was already used for another message.",
  notification_changed: "The notification changed. Refresh while retaining your draft.",
  notification_recovery_unavailable: "Recovery is unavailable in the current state.",
  notification_policy_capacity: "Notification policy exceeds operational capacity.",
  notification_customer_unavailable: "The notification customer was not found.",
  support_ticket_not_found: "This ticket was not found in this account.",
  support_ticket_changed: "The ticket changed. Refresh while retaining your draft.",
  support_request_reused: "This request key was already used with different data.",
  support_policy_capacity: "Support policy exceeds capacity. An administrator must update it.",
  support_new_disabled: "New tickets are currently disabled.",
  support_reply_disabled: "Replies are currently disabled.",
  support_state_denied: "The selected status change is unavailable under the current policy.",
  support_message_length: "The message exceeds the support policy's length limit.",
  support_open_capacity: "The account has reached its open-ticket limit.",
  support_thread_capacity: "This ticket has reached its message limit.",
  support_ticket_closed: "The ticket is closed. Reopen it with the required permission first.",
  support_context_unavailable: "The related subscription or payment is unavailable in this account.",
  staff_role_not_found: "The selected role no longer exists.",
  staff_role_changed: "The role changed. Refresh the record; your draft is retained.",
  staff_role_membership_changed: "Role assignments changed. Refresh the record; your selection is retained.",
  staff_role_member_capacity: "The role member capacity is reached. Remove memberships or adjust capacity.",
  staff_role_capacity: "This account's role count exceeds configured capacity.",
  staff_role_inactive: "Inactive role assignment is unavailable under the current policy.",
  staff_grant_capacity: "Permission count exceeds configured capacity.",
  usage_grant_capacity: "Quota policy exceeds operational capacity.",
  usage_final_report_required: "The node must report final usage before revocation.",
  provision_retirement_conflict: "Period completion conflicts with the previous state.",
  qr_disabled: "QR codes are currently disabled.",
  qr_render_capacity: "The connection does not fit in a QR code. Use its link or file.",
  qr_policy_capacity: "QR size exceeds capacity. Reduce the size or disable image delivery.",
  subscription_unavailable: "The link is invalid or this route is unavailable.",
  provision_configuration_changed: "The configuration changed. Apply its current revision to the node.",
  configuration_revision_conflict: "Another operator changed the configuration. Refresh the record.",
  provision_retry_unavailable: "This request cannot be retried in its current state.",
  fulfillment_capacity: "Delivery policy exceeds configured capacity.",
  profile_allocation_capacity: "Profile check capacity is insufficient.",
  wireguard_pool_exhausted: "No free address remains in the WireGuard subnet.",
  inbound_port_conflict: "The selected port conflicts with another configuration on this node.",
  preferences_revision_conflict: "Another operator changed the settings. Refresh the record.",
  openvpn_disabled: "OpenVPN draft creation is disabled by operational policy.",
  openvpn_capacity: "OpenVPN settings exceed operational capacity.",
  openvpn_management_conflict: "Another configuration owns this management socket. Select a separate path.",
  openvpn_management_missing: "Management socket reservation is missing. Review migration and configuration state.",
  openvpn_identity_changed: "Create a new configuration to change certificate identity or move it.",
  openvpn_certificate_unavailable: "The OpenVPN certificate is invalid. Review configuration and certificate authority validity.",
  core_export_global_conflict: "Shared DNS, routing or other settings differ. Align the JSON documents or choose independent files.",
  core_export_outbound_conflict: "An outbound tag has conflicting definitions. Align the documents or choose independent files.",
  core_export_inbound_tag_conflict: "Inbound tags must be unique across the core.",
  core_export_outbound_tag_required: "Combined output requires named outbound tags. Set tags or choose independent files.",
  core_export_merge_unsupported: "This core supports independent configuration files; combined JSON is unavailable.",
  core_export_invalid_json: "A document cannot be combined. Review its inbounds and outbounds or use independent files.",
  core_export_disabled: "Core exports are disabled in application settings.",
  core_export_empty: "Add a configuration to this core before exporting.",
  core_export_capacity: "The export exceeds the configured configuration or profile capacity.",
  core_export_output_capacity: "The export exceeds the configured output byte capacity.",
  core_export_stale: "Configurations changed during export. Generate the export again.",
  core_protocol_mismatch: "The core and protocol are incompatible or belong to different nodes.",
  host_sni_mismatch: "The server name does not match the configuration.",
  plan_group_disabled: "The plan's delivery group is inactive.",
  ip_policy_capacity: "Policy exceeds configured capacity.",
  ip_ban_capacity: "Ban duration exceeds configured capacity.",
  node_subscription_unassigned: "This subscription is not assigned to the requesting node.",
  configuration_no_clients: "A Shadowsocks export requires at least one valid user.",
  configuration_export_capacity: "Profile count exceeds export capacity.",
  configuration_protocol_mismatch: "Configuration protocol must match the node.",
  wireguard_address_required: "A dedicated client address is required.",
  wireguard_address_invalid: "The client address must identify one host within the node subnet.",
  subscription_not_provisionable: "This subscription cannot be provisioned.",
  customer_unauthorized: "Your account session is invalid. Get a new sign-in link from the bot.",
  customer_csrf_denied: "The account request is invalid. Refresh the page.",
  payment_destination_required: "Select a payment destination.",
  payment_destination_unavailable: "The payment destination is unavailable. Select another destination.",
  topup_amount_policy: "The top-up amount is outside the allowed range.",
  topup_request_reused: "This request was already submitted with different data.",
  payment_identifier_disabled: "Payment identifiers are unavailable. Ask support to review the payment settings.",
  payment_identifier_capacity: "The payment identifier policy exceeds this runtime’s capacity.",
  payment_identifier_candidate_capacity: "The configured payment identifier range exceeds the allocation capacity.",
  payment_identifier_exhausted: "No unique payment identifier is available. Keep this request and ask support to review it.",
  payment_identifier_binding_changed: "The receiving account changed. Refresh the payment destination before creating a request.",
  payment_identifier_receiving_realm_required: "This payment identifier needs a configured receiving account.",
  receipt_image_invalid: "The receipt image is invalid or exceeds the limit.",
  receipt_busy: "Receipt processing is busy. Try again later.",
  receipt_capacity: "This payment has reached its receipt limit.",
  receipt_upload_unavailable: "Receipt uploads are disabled or the image exceeds capacity.",
  admin_unauthorized: "Your session ended. Sign in again.",
  admin_csrf_denied: "The request is invalid. Refresh and try again.",
  admin_scope_denied: "You do not have permission for this operation.",
  purchase_price_changed: "The plan price changed. Review the new price before confirming purchase.",
  reseller_unauthorized: "Your reseller session is invalid. Sign in again.",
  reseller_csrf_denied: "The reseller request is invalid. Refresh the page.",
  reseller_scope_denied: "You do not have reseller permission for this operation.",
  reseller_delegation_denied: "You cannot delegate permissions beyond your own access.",
  reseller_not_found: "This record was not found in the selected reseller account.",
  reseller_policy_capacity: "Reseller policy exceeds operational capacity. Reduce the values.",
  reseller_disabled: "Reseller services are currently disabled.",
  reseller_customer_capacity: "Reseller customer capacity is reached.",
  reseller_account_capacity: "Reseller team account capacity is reached.",
  reseller_session_capacity: "Session capacity is reached. Review the session policy.",
  reseller_plan_capacity: "Plan agreement capacity is reached.",
  reseller_account_revision_changed: "The account changed. Refresh while retaining your draft.",
  reseller_revision_changed: "The record changed. Refresh while retaining your draft.",
  reseller_plan_revision_changed: "The agreement changed. Review its current price and revision.",
  reseller_last_owner: "The final active reseller owner must remain available.",
  reseller_owner_required: "Reseller policy requires an active account with full access.",
  reseller_customer_creation_disabled: "Customer creation is disabled for this reseller.",
  reseller_customer_access_denied: "Custom initial customer access is unavailable under reseller policy.",
  reseller_customer_purchase_disabled: "Direct purchases are unavailable for this account. Contact the reseller.",
  reseller_customer_renewal_denied: "This account cannot change renewal funded by the reseller wallet.",
  reseller_plan_unavailable: "The plan has no active reseller agreement.",
  reseller_sales_disabled: "Sales are currently paused for this reseller.",
  reseller_payer_required: "Select the paying wallet.",
  reseller_payer_denied: "The selected wallet is unavailable under reseller policy.",
  reseller_customer_not_owned: "The selected customer belongs to another reseller.",
  payer_inactive: "The paying account is inactive.",
  wallet_insufficient: "Insufficient wallet balance.",
  topup_reviewed: "This request was already reviewed.",
  plan_code_exists: "The plan code is already in use.",
  subscription_not_pending: "This subscription is not awaiting provisioning.",
};

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message);
  }
}

export type ApiErrorTranslator = (code: string, status: number) => string | undefined;
let errorTranslator: ApiErrorTranslator | undefined;
export function setApiErrorTranslator(translator: ApiErrorTranslator): void {
  errorTranslator = translator;
}

function errorMessage(body: unknown, status: number): ApiError {
  const envelope = body && typeof body === "object" ? body as Record<string, unknown> : {};
  const value = envelope.error && typeof envelope.error === "object" ? envelope.error as Record<string, unknown> : envelope;
  if (typeof value.message_code !== "string" && status < 500) {
    const detail = typeof value.detail === "string" ? value.detail : Object.values(value)
      .flatMap(field => Array.isArray(field) ? field.filter((message): message is string => typeof message === "string") : []);
    const message = typeof detail === "string" ? detail : detail.join(" ");
    if (message) return new ApiError(status, typeof value.code === "string" ? value.code : "validation_error", message);
  }
  const code = typeof value.message_code === "string" ? value.message_code : "request_failed";
  return new ApiError(status, code, errorTranslator?.(code, status) ?? messages[code] ?? (status === 429 ? "Too many requests. Try again later." : status === 413 ? "The request exceeds the allowed size." : status >= 500 ? "Server error. Try again." : "The request could not be completed. Check your input."));
}

let csrf = "";
let customerCsrf = "";
let resellerCsrf = "";
export function setResellerCsrf(value: string): void { resellerCsrf = value }
export function setCustomerCsrf(value: string): void { customerCsrf = value }
export function setCsrf(value: string): void { csrf = value }

export interface RequestOptions { signal?: AbortSignal }

export type SmsApprovalMode = "manual" | "unique_sms";
export interface SmsDevice { id: number; label: string; senders: string[]; is_active: boolean; revision: number; expires_at: string; approval_mode: string; destination_id: number | null; parser_profile_id?:number|null; settlement_identity_mode?:import("./smsOrigins").SmsIdentityMode; connection_state:"unknown"|"recent"|"stale"|"disabled"|"expired"; status_received_at:string|null; pending_event_count:number|null; permission_granted:boolean|null; delivery_state:string|null; last_acknowledged_event_id:string|null; last_error_code:string|null }
export interface SmsDeviceWrite { label: string; senders: string[]; is_active: boolean; expires_at: string; approval_mode: SmsApprovalMode; destination_id: number | null; expected_revision?: number; parser_profile_id?:number|null; settlement_identity_mode?:import("./smsOrigins").SmsIdentityMode }
export interface SmsDeviceEnrollment { device: SmsDevice; api_key: string }

export async function request<T>(path: string, method = "GET", body?: unknown, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined && !(body instanceof FormData)) headers["Content-Type"] = "application/json";
  const writeToken = path.startsWith("/v1/reseller/") ? resellerCsrf : path.startsWith("/v1/customer") ? customerCsrf : csrf;
  if (writeToken) headers["X-CSRF-Token"] = writeToken;
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { method, credentials: "include", headers, signal: options.signal, body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body) });
  } catch (cause) {
    if (options.signal?.aborted || cause instanceof Error && cause.name === "AbortError") throw cause;
    throw new ApiError(0, "network", "Could not connect to the server. Try again.");
  }
  if (response.status === 204) return undefined as T;
  const content = await response.json().catch((cause: unknown) => {
    if (options.signal?.aborted || cause instanceof Error && cause.name === "AbortError") throw cause;
    return null;
  }) as unknown;
  if (!response.ok) throw errorMessage(content, response.status);
  return content as T;
}

export async function item<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const result = await request<{ data: T }>(path, method, body);
  return result.data;
}

export function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== "") search.set(key, String(value));
  return search.toString();
}

export interface ConfigurationDraft { revision: number; core_id: number; listen_port: number; port_network: "tcp" | "udp" | "dual"; id: number; node_id: number; label: string; protocol: string; application_status: "draft" }
export interface ClientProfile { id: number; configuration_id: number; subscription_id: number; client_address: string | null }
export interface ConfigurationDownload { filename: string; content: string; media_type: string }

export type OpenVpnKeyType = "ec_p256" | "rsa_2048" | "rsa_3072" | "rsa_4096";
export type OpenVpnCipher = "AES-256-GCM" | "AES-128-GCM" | "CHACHA20-POLY1305";
export type OpenVpnTopology = { mode: "tun"; network: string } | { mode: "tap"; network: string; bridge_address: string; pool_start: string; pool_end: string };
export interface OpenVpnOptions { protocol: "openvpn"; listen_address: string; ca_name: string; server_name: string; transport: "udp" | "tcp"; topology: OpenVpnTopology; routes: string[]; dns: string[]; redirect_gateway: boolean; client_to_client: boolean; data_ciphers: OpenVpnCipher[]; tls_min_version: "1.2" | "1.3"; tls_crypt: boolean; key_type: OpenVpnKeyType; ca_validity_days: number; server_validity_days: number; client_validity_days: number; crl_validity_seconds: number; keepalive_seconds: number; restart_seconds: number; max_clients: number; management_socket: string; verbosity: number }
export interface OpenVpnCapacity { enabled: boolean; max_ca_validity_days: number; max_server_validity_days: number; max_client_validity_days: number; max_crl_validity_seconds: number; max_clients: number; max_routes: number; max_dns_servers: number; max_keepalive_seconds: number; max_restart_seconds: number; allowed_key_types: OpenVpnKeyType[] }
export type ConfigurationOptions = OpenVpnOptions | { protocol: "vless_reality"; listen_address: string; server_name: string; target_port: number } | { protocol: "vless_tls" | "vmess_tls" | "trojan_tls"; listen_address: string; server_name: string; certificate_path: string; private_key_path: string; transport: "tcp" | "ws" | "grpc"; transport_path: string | null } | { protocol: "hysteria2"; listen_address: string; server_name: string; certificate_path: string; private_key_path: string } | { protocol: "shadowsocks"; listen_address: string } | { protocol: "wireguard"; server_address: string; client_subnet: string; allowed_ips: string[]; dns: string[] };
export interface ConfigurationDetail extends ConfigurationDraft { options: ConfigurationOptions }

export interface SchedulePolicy { mode: "cron"|"interval"; interval_seconds: number|null; enabled: boolean; cron: string|null; timezone: string|null; batch_size: number; recheck_seconds: number | null }
export interface AutomationSchedule extends SchedulePolicy { capacity_valid: boolean; key: string; scope: string; revision: number; applied_revision: number | null; registered_at: string | null }
export interface AutomationRevision { revision: number; values: SchedulePolicy; reason: string; staff_id: number; created_at: string }
export interface PaymentReview { topup_id: number; customer_id: number; customer_name: string; amount_rial: number; topup_status: string; status: string; candidate_count: number; competing_topup_count: number; checked_at: string }
export interface NodeHealthCheck {node_id:number;status:string;checked_at:string}
export interface NodeHealth { node_id: number; code: string; label: string; protocol: string; is_enabled: boolean; status: string; sample_count: number; successful_count: number; average_latency_ms: number | null; last_sample_at: string | null; checked_at: string }
export interface SubscriptionAttention { subscription_id: number; customer_id: number; customer_name: string; subscription_status: string; status: string; expires_at: string|null; auto_renew: boolean; payer_customer_id: number|null; renewal_available: boolean|null; renewal_price_rial: number|null; wallet_balance_rial: number; checked_at: string }
export interface WalletEntry { id: number; customer_id: number; amount_rial: number; balance_after_rial: number; reference: string; reason: string; created_at: string }
export interface IpLimitPolicy { subscription_id: number; enabled: boolean; max_ips: number; lease_seconds: number; ban_seconds: number; mode: "reject_new" | "replace_oldest" }
export interface IpLimitDetail { transition_options?: IpPolicyTransitionOptions; purchased_ip_policy?: PurchasedIpPolicyRead|null; effective_ip_policy?: EffectiveIpPolicyRead; subscription_id: number; policy: IpLimitPolicy | null; defaults: { mode: IpLimitPolicy["mode"]; max_ips: number; lease_seconds: number; ban_seconds: number; max_ips_ceiling: number; max_lease_seconds: number; max_ban_seconds: number } }
export interface IpSession { id: number; subscription_id: number; source_ip: string; last_node_id: number; first_seen_at: string; last_seen_at: string; expires_at: string; blocked_until: string | null; block_reason: string | null; blocked_by_staff_id: number | null }

export interface RuntimeObservationFields {automation_paused:boolean;last_observed_at:string|null}
export interface CoreRuntimeSummary extends RuntimeObservationFields {revision:number;desired_revision_id:number|null;applied_revision_id:number|null;validated_revision_id:number|null;observed_status:"unknown"|"running"|"stopped"}
export interface CoreInstance { runtime:CoreRuntimeSummary|null;id: number; node_id: number; code: string; label: string; kind: "xray" | "sing_box" | "wireguard" | "openvpn" | "hysteria"; supported_protocols: string[]; application_status: "draft"|"applied" }
export interface Host { id: number; configuration_id: number; label: string; address: string; port: number; is_enabled: boolean }
export interface HostGroup { id: number; code: string; title: string; is_enabled: boolean }
export interface HostMembership { id: number; group_id: number; host_id: number; label: string | null; address: string | null; port: number | null; server_name: string | null; is_enabled: boolean; sort_order: number }
export interface GroupHost { host: Host; membership: HostMembership }
export type BotLocale = "fa" | "en" | "ru" | "zh";
export interface BotLocaleTextSettings { welcome_message:string;purchases_button_label:string;loyalty_button_label:string;trial_button_label:string;account_button_label:string;catalog_button_label:string;subscriptions_button_label:string;wallet_button_label:string;support_button_label:string }
export interface BotPresentationSettings { catalog_version:3;welcome_photo_url:string|null;show_purchases:boolean;show_loyalty:boolean;show_trials:boolean;show_account:boolean;show_catalog:boolean;show_subscriptions:boolean;show_wallet:boolean;show_support:boolean;localized_texts:Record<BotLocale,BotLocaleTextSettings>;message_catalog:Record<BotLocale,Record<string,string>> }
export interface BusinessPreferences { purchase_checkout?:PurchaseCheckoutPolicy|null; subscription_alerts?:SubscriptionAlertPolicy|null; reseller_defaults?: ResellerDefaults|null; qr_codes?: QrPolicy|null; trials?: TrialPolicy|null; notifications?: NotificationPolicy|null; support?: SupportPolicy|null; customer_creation_access: CustomerAccessState; receipts: ReceiptPolicy; checkout: CheckoutPolicy; quota_policy: QuotaPolicy; customer_link_rotation: boolean; fulfillment: FulfillmentPolicy; bot_presentation:BotPresentationSettings; brand_title: string; payment_instructions: string | null; support_handle: string | null; topup_options_rial: number[]; max_plan_duration_days: number; payment_stale_hours: number; node_health_stale_seconds: number; subscription_expiry_warning_hours: number; provisioning_attention_minutes: number; ip_defaults: { enabled: boolean; mode: "reject_new" | "replace_oldest"; max_ips: number; lease_seconds: number; ban_seconds: number } }
export interface PreferencesCapabilities { supported_notification_kinds:NotificationKind[]; checkout_transient_conflict_modes:CheckoutTransientConflictMode[]; payment_identifiers?:PaymentIdentifierCapabilities }
export interface PreferencesSnapshot { capabilities?:PreferencesCapabilities; revision: number; values: BusinessPreferences }
export interface PreferencesRevision { revision: number; values: BusinessPreferences; changed_by_staff_id: number; created_at: string | null }

export interface FulfillmentPolicy { renewal_trigger: "expiry" | "quota" | "either"; automatic: boolean; activation: "all" | "any" | "quorum"; minimum_successes: number; expiry_start: "purchase" | "activation"; failure_action: "hold" | "refund_wallet"; max_attempts: number; claim_seconds: number; retry_seconds: number; deadline_minutes: number; renewal_quota: "reset" | "carry_unused"; renewal_price: "purchased" | "current_plan" }
export type IpLimitChoice = Omit<IpLimitPolicy, "subscription_id">;
export interface PlanPolicyDefaults { ip_limit_capacity?: IpLimitCapacityRead; quota_policy: QuotaPolicy; fulfillment: FulfillmentPolicy; ip_limit: IpLimitChoice }
export interface ProvisionRequest { completion: "refund" | "expire" | "quota" | "suspend" | "cancel"; id: number; subscription_id: number; generation: number; state: string; reason_code: string | null; checked_at: string | null; activated_at: string | null; deadline_at: string; retry_reason: string | null; cancellation_reason: string | null; cancelled_by_staff_id: number | null; policy: FulfillmentPolicy }
export interface ProvisionTask { configuration_revision: number; id: number; request_id: number; configuration_id: number; profile_id: number; node_id: number; action: "apply" | "revoke"; state: string; attempts: number; claim_until: string | null; acknowledged_at: string | null; error_code: string | null; available_at: string }

export interface PublicSubscription { qr_enabled: boolean; feed_url: string | null; id: number; status: string; quota_bytes: number|null; used_bytes: number; expires_at: string|null; auto_renew: boolean; brand_title: string; support_handle: string | null }
export interface QrPolicy { enabled: boolean; error_correction: "L"|"M"|"Q"|"H"; box_size: number; border_modules: number }
export interface PublicProfile { profile_id: number; host_id: number | null; label: string; protocol: string }

export interface QuotaPolicy { mode: "reported" | "reserved"; grant_bytes: number; grant_seconds: number; report_max_age_seconds: number; report_future_seconds: number }
export interface UsageSummary { upload_bytes: number; download_bytes: number; total_bytes: number; sample_count: number }
export interface UsageGrant { id: number; subscription_id: number; profile_id: number; node_id: number; generation: number; configuration_revision: number; mode: "reported" | "reserved"; allocated_bytes: number; upload_bytes: number; download_bytes: number; sequence: number; is_closed: boolean; sampled_at: string | null; valid_until: string }
export interface UsageEvent { id: number; grant_id: number; subscription_id: number; node_id: number; generation: number; sequence: number; upload_bytes: number; download_bytes: number; delta_upload_bytes: number; delta_download_bytes: number; delta_bytes: number; final: boolean; sampled_at: string }

export interface CustomerSession { customer_id: number; display_name: string; csrf_token: string }
export type PaymentIdentifierMode="exact_requested"|"rial_suffix4";
export interface PaymentIdentifierPolicy { mode:PaymentIdentifierMode; max_adjustment_rial:number; amount_step_rial:number }
export interface PaymentIdentifierCapacity { max_adjustment_rial:number; max_candidate_amounts:number; max_active_codes:number }
export interface PaymentIdentifierCapabilities { capacity:PaymentIdentifierCapacity|null; supported_modes:PaymentIdentifierMode[]; suffix_digits:number; suffix_modulus:number }
export interface CheckoutPolicy { payment_identifier?:PaymentIdentifierPolicy|null; destination_mode: "required" | "optional" | "legacy"; allowed_methods: ("card" | "iban" | "bank_account")[]; minimum_topup_rial: number; maximum_topup_rial: number }
export interface PaymentInstruction { destination_id: number; title: string; kind: "card" | "iban" | "bank_account"; account: string; recipient: string; bank_name: string; instructions: string | null }
export interface TopupPaymentInstruction extends PaymentInstruction { topup_id:number; requested_amount_rial:number; payable_amount_rial:number; payment_identifier_mode:PaymentIdentifierMode; payment_identifier_code4:string|null }
export interface PaymentDestination extends PaymentInstruction { is_active: boolean; receiving_alias_id?:number|null; revision?:number }
export interface ReceiptFieldEvidence { line_indexes: number[]; text: string; confidence_milli: number; region: [number, number][] }
export interface ReceiptExtractionFields { amount_raw: string | null; amount_rial: number | null; currency: "rial" | "toman" | null; destination_kind: "card" | "iban" | "account" | null; visible_destination: string | null; destination_masked: string | null; bank_namespace: string | null; bank_reference: string | null; occurred_at_raw: string | null; occurred_at_utc: string | null; calendar: "jalali" | "gregorian" | null; timezone: string | null; transaction_status_claim: string | null; field_evidence: Record<string, ReceiptFieldEvidence>; warnings: string[]; reason_codes: string[] }
export interface PaymentReceipt { id: number; topup_id: number; media_type: string; size_bytes: number; created_at: string; ocr_status: "not_requested" | "pending" | "complete" | "failed"; extraction: ReceiptExtractionFields | null }
export interface ReceiptCorrectionFields { amount_rial: number | null; currency: "rial" | "toman" | null; destination_kind: "card" | "iban" | "account" | null; visible_destination: string | null; bank_namespace: string | null; bank_reference: string | null; occurred_at_utc: string | null; transaction_status_claim: string | null }
export interface ReceiptAnnotation { id: number; receipt_id: number; revision: number; staff_id: number; created_at: string; fields: ReceiptCorrectionFields; reason: string }
export interface ReceiptAnnotationWrite { expected_revision: number; fields: ReceiptCorrectionFields; reason: string }
export interface AccountPreferences { receipts: ReceiptPolicy; brand_title: string; payment_instructions: string | null; support_handle: string | null; topup_options_rial: number[]; checkout: CheckoutPolicy }
export interface AccountDelivery { entitlement_kind: "paid"|"trial"; subscription_id: number; status: string; auto_renew: boolean; feed_url: string | null; portal_url: string | null; can_rotate_link: boolean }

export async function privateFile(path: string): Promise<Blob> {
  let response: Response;
  try { response = await fetch(`/api${path}`, { credentials: "include" }); }
  catch { throw new ApiError(0,"network","Could not connect to the server."); }
  if (!response.ok) throw errorMessage(await response.json().catch(() => null), response.status);
  return response.blob();
}

export interface ReceiptPolicy { enabled: boolean; max_per_topup: number; allowed_formats: ("JPEG"|"PNG"|"WEBP")[] }

export interface Staff { id: number; username: string; is_active: boolean }
export interface StaffAccess extends Staff { scopes: string[]; role_ids: number[]; effective_scopes: string[] }
export interface StaffScopeCatalog { areas: string[]; levels: string[] }

export interface SubscriptionControlRecord { id: number; subscription_id: number; staff_id: number | null; actor_account_id: number | null; created_at: string; action: "suspend" | "resume"; reason: string; clock: "continue" | "pause" | null }

export interface CustomerAccessState { is_active: boolean; services_enabled: boolean; renewals_enabled: boolean }
export interface CustomerAccessChange { id: number; customer_id: number; staff_id: number | null; reseller_id: number | null; actor_account_id: number | null; created_at: string; previous: CustomerAccessState; values: CustomerAccessState; reason: string; clock: "continue" | "pause" | null }

export interface StaffRole { id: number; code: string; title: string; is_active: boolean; scopes: string[]; revision: number }
export interface StaffRoleRevision { id: number; revision: number; title: string; is_active: boolean; scopes: string[]; staff_id: number; reason: string; created_at: string }
export interface StaffRoleChange { id: number; target_staff_id: number; actor_staff_id: number; previous_role_ids: number[]; role_ids: number[]; reason: string; created_at: string }

export type SupportStatus = "open" | "waiting_customer" | "closed";
export interface SupportPolicy { new_tickets_enabled: boolean; customer_replies_enabled: boolean; staff_replies_enabled: boolean; staff_reply_status: SupportStatus; customer_closure_enabled: boolean; customer_reopen_enabled: boolean; closed_reply_mode: "reject" | "reopen"; max_open_tickets: number; max_messages_per_ticket: number; max_message_chars: number }
export interface SupportAvailability extends SupportPolicy { capacity_valid: boolean }
export interface SupportTicket { id: number; created_at: string; updated_at: string; customer_id: number; subject: string; status: SupportStatus; revision: number; subscription_id: number|null; topup_id: number|null }
export interface SupportMessage { id: number; created_at: string; revision: number; body: string; author_kind: "staff"|"customer"; staff_id?: number|null; customer_id?: number|null }
export interface SupportHistory { id: number; created_at: string; revision: number; previous_status: SupportStatus; status: SupportStatus; reason: string; author_kind: "staff"|"customer"; staff_id?: number|null; customer_id?: number|null }

export type CoreNotificationKind = "manual"|"support_reply"|"payment_approved"|"expiry_soon"|"renewal_unfunded"|"provisioning_failed"|"subscription_active";
export type CommerceNotificationKind = "tier_changed"|"discount_applied"|"volume_low"|"renewal_available";
export type CheckoutNotificationKind = "checkout_action_required"|"checkout_cancelled"|"checkout_expired";
export type NotificationKind = CoreNotificationKind | CommerceNotificationKind | CheckoutNotificationKind;
export type NotificationStatus = "skipped"|"pending"|"processing"|"delivered"|"retry"|"ambiguous"|"failed"|"cancelled";
export interface NotificationTemplate {enabled:boolean;title:string;body:string}
export interface NotificationPolicy {enabled:boolean;channel_mode:"inbox"|"telegram"|"both";delivery_enabled:boolean;ambiguous_mode:"hold"|"retry";backoff_mode:"fixed"|"exponential";retry_seconds:number;max_retry_seconds:number;max_attempts:number;lease_seconds:number;max_message_chars:number;templates:Record<CoreNotificationKind,NotificationTemplate>&Partial<Record<CommerceNotificationKind|CheckoutNotificationKind,NotificationTemplate>>}
export interface NotificationAvailability extends NotificationPolicy {supported_kinds?:NotificationKind[];capacity_valid:boolean;outbound_available:boolean}
export interface NotificationRecord {subscription_context?:SubscriptionNoticeContext|null;created_by_staff_id?:number|null;id:number;created_at:string;kind:NotificationKind;record_id:number|null;title:string;body:string;is_read:boolean;customer_id?:number;inbox_visible?:boolean;status?:NotificationStatus;revision?:number;attempts?:number;retry_budget_used?:number;next_attempt_at?:string|null;telegram_message_id?:number|null;error_code?:string|null}
export interface NotificationAttempt {id:number;created_at:string;attempt:number;outcome:string;error_code:string|null;finished_at:string|null}
export interface NotificationRecovery {id:number;created_at:string;revision:number;staff_id:number;action:"retry"|"cancel";previous_status:NotificationStatus;reason:string}

export interface TrialPolicy { enabled: boolean; plan_id: number|null; eligibility: "no_paid_purchase"|"any_customer"; concurrent_mode: "reject_active"|"allow_multiple"; max_claims_per_customer: number; cooldown_seconds: number; quota_bytes: number; duration_days: number }
export interface TrialAvailability { policy: TrialPolicy; capacity_valid: boolean; eligible: boolean; reason: string|null; claims: number; next_claim_at: string|null }

export interface ResellerSession { reseller_id: number; account_id: number; title: string; username: string; scopes: string[]; csrf_token: string }
export interface ResellerAccess { login_enabled: boolean; sales_enabled: boolean; renewals_enabled: boolean }
export interface ResellerPolicy {
  require_active_owner: boolean; customer_creation_enabled: boolean; customer_access_override_enabled: boolean;
  new_customer_access: CustomerAccessState; customer_capacity: number; account_capacity: number; plan_capacity: number;
  max_sessions_per_account: number; session_limit_mode: "reject_new"|"replace_oldest";
  payer_mode: "reseller_wallet"|"customer_wallet"|"either"; customer_self_purchase: boolean;
  renewal_price_mode: "purchase_snapshot"|"current_agreement";
  renewal_availability_mode: "purchase_snapshot"|"current_agreement";
  customer_can_disable_reseller_renewal: boolean;
}
export interface ResellerDefaults { access: ResellerAccess; policy: ResellerPolicy; owner_access: { scopes: string[] }; owner_is_active: boolean; wallet_customer_access: CustomerAccessState }
export interface Reseller extends ResellerAccess { id: number; code: string; title: string; revision: number; wallet_customer_id: number; policy: ResellerPolicy }
export interface ResellerAccount { id: number; reseller_id: number; username: string; revision: number; is_active: boolean; scopes: string[] }
export interface CreatedReseller { reseller: Reseller; owner: ResellerAccount }
export interface ResellerChange extends ResellerAccess { id: number; reseller_id: number; staff_id: number; revision: number; title: string; policy: ResellerPolicy; reason: string; created_at: string }
export interface ResellerAccountChange { id: number; reseller_id: number; account_id: number; staff_id: number|null; actor_account_id: number|null; action: "create"|"access"|"password"; revision: number; is_active: boolean; scopes: string[]; reason: string; created_at: string }
export interface AgreementPrice { mode: "catalog"|"fixed"|"discount"; fixed_price_rial: number|null; discount_bps: number|null; rounding: "floor"|"ceil"|"nearest"; quantum_rial: number }
export interface ResellerPlan { id: number; reseller_id: number; plan_id: number; revision: number; enabled: boolean; price: AgreementPrice; code: string; title: string; quota_bytes: number|null; duration_days: number|null; plan_active: boolean; catalog_price_rial: number; price_rial: number }
export interface ResellerPlanChange { id: number; agreement_id: number; staff_id: number; revision: number; enabled: boolean; price: AgreementPrice; reason: string; created_at: string }

export interface ResellerBillingSnapshot { agreement_revision: number; price: AgreementPrice; payer_mode: "reseller_wallet"|"customer_wallet"; renewal_price_mode: "purchase_snapshot"|"current_agreement"; renewal_availability_mode: "purchase_snapshot"|"current_agreement" }
export interface BilledSubscription extends Subscription { payer_customer_id: number; reseller_id: number|null; reseller_agreement_id: number|null; reseller_billing: ResellerBillingSnapshot|null }

export interface ServerJsonDocument { mode: "managed" | "experimental"; source: string }
export interface ServerJsonState { configuration_id: number; revision: number; core_kind: string; supported: boolean; capacity: { enabled: boolean; max_document_bytes: number; max_depth: number } | null; document: ServerJsonDocument | null }
export interface ServerJsonRevision { id: number; revision: number; staff_id: number; reason: string; created_at: string; document: ServerJsonDocument | null }
export interface PlanConfiguration {node_id:number;node_label:string;configuration_id:number;label:string;protocol:string;host_id:number;group_id:number;is_enabled:boolean}
export interface CustomerConfiguration {profile_id:number;subscription_id:number;customer_id:number;plan_id:number;plan_title:string;configuration_id:number;configuration_label:string;node_id:number;node_label:string;protocol:string;status:string;desired_revision:number;applied_revision:number|null;quota_bytes:number|null;used_bytes:number;expires_at:string|null;auto_renew:boolean}


export interface CustomerTier { id:number;code:string;title:string;minimum_bytes:number;discount_bps:number;is_enabled:boolean;revision:number }
export interface LoyaltyPolicy { enabled:boolean;tier_basis:"net_purchases"|"lifetime_purchases";unlimited_credit_mode:"exclude"|"equivalent";unlimited_equivalent_bytes:number;unlimited_plan_bytes:Record<string,number>;first_purchase_basis:"net_purchases"|"lifetime_purchases";first_purchase_discount_bps:number;combination_mode:"best"|"additive"|"sequential";maximum_discount_bps:number;minimum_qualifying_rial:number;renewal_tier_discount:boolean;notify_tier_changes:boolean;notify_discounts:boolean }
export interface LoyaltyPolicyRead {revision:number;values:LoyaltyPolicy}
export interface CustomerLoyalty {customer_id:number;purchased_bytes:number;purchase_count:number;lifetime_purchase_count:number;tier:CustomerTier|null;next_tier:CustomerTier|null}
export interface CustomerPriceQuote {customer_id:number;plan_id:number;base_price_rial:number;price_rial:number;discount_rial:number;renewal_price_rial:number;tier_code:string|null;tier_discount_bps:number;first_purchase_discount_bps:number;policy_revision:number}

export interface CoreConfigurationRevision { configuration_id: number; revision: number }
export interface CoreArtifact { filename: string; media_type: string; content: string; sha256: string; configurations: CoreConfigurationRevision[] }
export interface CoreExport { core_id: number; node_id: number; kind: CoreInstance["kind"]; mode: "merged" | "isolated"; application_status: "not_applied"; artifacts: CoreArtifact[] }

export type RuntimeAction = "validate" | "apply" | "restart" | "stop" | "rollback" | "reconcile";
export interface RuntimeUsageCapability {mode:"disabled"|"observe"|"polled_stop";configured_port:number|null;available:boolean;reason_code:string|null;protected_ports:number[]}
export interface CoreRuntimeState extends CoreRuntimeSummary { id:number|null;core_id:number;enabled:boolean;allow_start:boolean;start_blocked_reason?:string|null;allowed_actions:RuntimeAction[];observed_process_epoch?:string|null;usage?:RuntimeUsageCapability }
export interface CoreRuntimeRevision { usage_sha256?:string|null;membership_sha256:string|null;created_by_staff_id:number|null;id:number;core_id:number;mode:"merged"|"isolated";bundle_sha256:string;artifact_count:number;created_at:string }
export interface CoreRuntimeCommand { purpose:"operator"|"provisioning";reconcile_mode:"observe"|"restore"|null;created_by_staff_id:number|null;id:number;core_id:number;node_id:number;action:RuntimeAction;revision_id:number|null;state:"queued"|"leased"|"succeeded"|"failed";request_key:string;reason:string;error_code:string|null;claim_until:string|null;created_at:string }

export interface LowQuotaThreshold {code:string;mode:'any'|'all';remaining_percent_bps:number|null;remaining_bytes:number|null}
export interface SubscriptionAlertPolicy {enabled:boolean;low_quota:LowQuotaThreshold[];expiry_hours:number[];renewal_opportunity:boolean}
export interface CustomerRenewalEligibility {subscription_id:number;renewal_generation:number;checked_at:string;auto_renew:boolean;quote_available:boolean;eligible:boolean;reason_code:string|null;renewal_due:boolean;auto_renew_authorized:boolean;wallet_funded:boolean|null;payer_kind:'self'|'other'|'none';wallet_balance_rial:number|null;renewal_price_rial:number|null;wallet_shortfall_rial:number|null}
export interface SubscriptionNoticeContext {subscription_id:number;generation:number;threshold_code:string;quota_bytes:number|null;used_bytes:number;remaining_bytes:number|null;expires_at:string|null;renewal_price_rial:number|null;captured_at:string}
