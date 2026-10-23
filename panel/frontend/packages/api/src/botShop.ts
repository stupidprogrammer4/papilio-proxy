/** Shared per-bot shop policy; revision values use exact decimal strings. */
export type ShopLocale = "en" | "fa";
export interface BotShopDefinition {
  public_origin: string;
  enabled: boolean;
  delivery_enabled: boolean;
  locale: ShopLocale;
  page_size: number;
  retry_seconds: number;
  lease_seconds: number;
  max_attempts: number;
  confirmation_ttl_seconds: number;
  ambiguous_delivery: "hold" | "retry";
  texts: Record<ShopLocale, Record<string, string>>;
}
export interface BotShopSettings {
  bot_id: string;
  owner_id: number;
  revision: string;
  definition: BotShopDefinition;
}
