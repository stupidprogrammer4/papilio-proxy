/** Native owner invoices, private receipt metadata and audited manual decisions. */
export interface ManualPaymentDefinition {
  recipient: string;
  destination: string;
  instructions: string;
  enabled: boolean;
  receipt_max_bytes: number;
}
export interface ManualPaymentSettings { owner_id: number; revision: string; definition: ManualPaymentDefinition }
export type ManualInvoiceState = "open" | "review" | "rejected" | "settled";
export interface ManualInvoice {
  id: string;
  owner_id: number;
  request_key: string;
  customer_id: string;
  base_amount_minor: string;
  amount_due_minor: string;
  currency: "IRR";
  unit: "rial";
  mode: "manual";
  status: ManualInvoiceState;
  revision: string;
  settings_revision: string;
  settings: ManualPaymentDefinition;
  created_at: string;
}
export interface ManualInvoicePage { items: ManualInvoice[]; count: number; page: number; page_size: number }
export interface ManualInvoiceReceipt {
  id: string;
  invoice_id: string;
  request_key: string;
  reference: string;
  note: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  created_at: string;
}
export interface ManualReceiptPage { items: ManualInvoiceReceipt[]; count: number; page: number; page_size: number }
export interface ManualPaymentDecision {
  id: string;
  invoice_id: string;
  actor_id: number;
  request_key: string;
  expected_revision: string;
  action: "approve" | "reject";
  reason: string;
  receipt_id: string | null;
  wallet_entry_id: string | null;
  created_at: string;
}
export interface ManualDecisionPage { items: ManualPaymentDecision[]; count: number; page: number; page_size: number }
export interface ManualDecisionResult { invoice: ManualInvoice; decision: ManualPaymentDecision }
