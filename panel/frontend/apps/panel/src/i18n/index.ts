import { createI18n } from "vue-i18n";
import en from "./en.json";
import fa from "./fa.json";
import foundationEn from "./foundation.en.json";
import foundationFa from "./foundation.fa.json";

import nodesEn from "./nodes.en.json";
import nodesFa from "./nodes.fa.json";

import botsEn from "./bots.en.json";
import botsFa from "./bots.fa.json";
import botShopEn from "./bot-shop.en.json";
import botShopFa from "./bot-shop.fa.json";
import serviceSetupEn from "./service-setup.en.json";
import serviceSetupFa from "./service-setup.fa.json";
import salesEn from "./sales.en.json";
import salesFa from "./sales.fa.json";
import productCatalogEn from "./product-catalog.en.json";
import productCatalogFa from "./product-catalog.fa.json";
import serviceOrdersEn from "./service-orders.en.json";
import serviceOrdersFa from "./service-orders.fa.json";

import invoicesEn from "./manual-payments.en.json";
import invoicesFa from "./manual-payments.fa.json";

export const i18n = createI18n({
  legacy: false,
  locale: "en",
  fallbackLocale: "en",
  messages: { en: { ...en, foundation: foundationEn, nodes: nodesEn, bots: botsEn, botShop: botShopEn, serviceSetup: serviceSetupEn, sales: salesEn, productCatalog: productCatalogEn, serviceOrders: serviceOrdersEn, invoices: invoicesEn }, fa: { ...fa, foundation: foundationFa, nodes: nodesFa, bots: botsFa, botShop: botShopFa, serviceSetup: serviceSetupFa, sales: salesFa, productCatalog: productCatalogFa, serviceOrders: serviceOrdersFa, invoices: invoicesFa } },
});
