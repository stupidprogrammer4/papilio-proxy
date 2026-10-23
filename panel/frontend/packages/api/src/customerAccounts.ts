/** Native customer/wallet contracts; monetary strings preserve signed BIGINT exactly. */
export interface CustomerAccount { id: string; owner_id: number; name: string }
export interface CustomerAccountPage { items: CustomerAccount[]; count: number; page: number; page_size: number }
export interface CustomerWallet {
  id: string;
  customer_id: string;
  currency: "IRR";
  unit: "rial";
  balance_minor: string;
  credit_limit_minor: string;
  revision: string;
}
export interface WalletJournalEntry {
  id: string;
  wallet_id: string;
  actor_id: number;
  request_key: string;
  kind: "credit" | "debit";
  amount_minor: string;
  reason: string;
  balance_before_minor: string;
  balance_after_minor: string;
  currency: "IRR";
  unit: "rial";
  created_at: string;
}
export interface WalletJournalPage { items: WalletJournalEntry[]; count: number; page: number; page_size: number }
export interface WalletJournalPost { request_key: string; kind: "credit" | "debit"; amount_minor: string; reason: string }
