/** Native product revisions and accepted wallet-to-service purchase contracts. */
export interface ServiceProductDefinition {
  name: string;
  core_id: string;
  inbound_id: string;
  currency: "IRR";
  price_minor: string;
  user_level: number | null;
  is_active: boolean;
}
export interface ServiceProductOffer { id: string; product_id: string; revision: string; definition: ServiceProductDefinition; user_level: number }
export interface ServiceProduct { id: string; owner_id: number; offer: ServiceProductOffer }
export interface ServiceProductPage { items: ServiceProduct[]; count: number; page: number; page_size: number }
export interface PurchaseTerms {
  product_id: string;
  offer_id: string;
  offer_revision: string;
  product_name: string;
  price_minor: string;
  currency: "IRR";
  unit: "rial";
  core_id: string;
  inbound_id: string;
  user_level: number;
}
export interface ServiceOrder {
  id: string;
  owner_id: number;
  customer_id: string;
  terms: PurchaseTerms;
  service_name: string;
  status: "pending" | "purchased";
  service_id: string | null;
  wallet_entry_id: string | null;
  created_at: string;
}
export interface ServiceOrderPage { items: ServiceOrder[]; count: number; page: number; page_size: number }
export interface ServicePurchase {
  request_key: string;
  customer_id: string;
  product_id: string;
  expected_revision: string;
  service_name: string;
}
