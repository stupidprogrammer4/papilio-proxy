import { createI18n } from "vue-i18n";
import en from "./en.json";
import fa from "./fa.json";
import foundationEn from "./foundation.en.json";
import foundationFa from "./foundation.fa.json";

import nodesEn from "./nodes.en.json";
import nodesFa from "./nodes.fa.json";

import botsEn from "./bots.en.json";
import botsFa from "./bots.fa.json";
import serviceSetupEn from "./service-setup.en.json";
import serviceSetupFa from "./service-setup.fa.json";
import salesEn from "./sales.en.json";
import salesFa from "./sales.fa.json";

export const i18n = createI18n({
  legacy: false,
  locale: "en",
  fallbackLocale: "en",
  messages: { en: { ...en, foundation: foundationEn, nodes: nodesEn, bots: botsEn, serviceSetup: serviceSetupEn, sales: salesEn }, fa: { ...fa, foundation: foundationFa, nodes: nodesFa, bots: botsFa, serviceSetup: serviceSetupFa, sales: salesFa } },
});
