<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, request, type BotShopDefinition, type BotShopSettings } from "@papilio/api";
import BotShopDefinitionEditor from "./BotShopDefinitionEditor.vue";

const props = defineProps<{ botId: string }>();
const { t } = useI18n();
const settings = ref<BotShopSettings | null>(null);
const draft = ref<BotShopDefinition | null>(null);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const lifetime = new AbortController();
const endpoint = `/v1/bots/${props.botId}/shop`;
onBeforeUnmount(() => lifetime.abort());

function copy(values: BotShopDefinition): BotShopDefinition {
  const texts = Object.fromEntries(
    Object.entries(values.texts).map(([locale, messages]) => [locale, { ...messages }]),
  ) as BotShopDefinition["texts"];
  return { ...values, texts, flows: { ...values.flows } };
}
async function perform(action: () => Promise<void>): Promise<void> {
  if (busy.value) return;
  busy.value = true; error.value = ""; notice.value = "";
  try { await action(); }
  catch (cause) { if (!lifetime.signal.aborted) error.value = cause instanceof Error ? cause.message : t("bots.failed"); }
  finally { busy.value = false; }
}
async function reload(): Promise<void> {
  await perform(async () => {
    try {
      const current = await request<BotShopSettings>(endpoint, "GET", undefined, { signal: lifetime.signal });
      settings.value = current;
      draft.value = copy(current.definition);
    } catch (cause) {
      if (!(cause instanceof ApiError) || cause.status !== 404) throw cause;
      const defaults = await request<BotShopDefinition>("/v1/bot-shop-defaults", "GET", undefined, { signal: lifetime.signal });
      settings.value = null;
      draft.value = copy(defaults);
    }
  });
}
async function save(): Promise<void> {
  const current = settings.value;
  if (!draft.value) return;
  const definition = copy(draft.value);
  await perform(async () => {
    const saved = current
      ? await request<BotShopSettings>(endpoint, "PUT", { ...definition, expected_revision: current.revision }, { signal: lifetime.signal })
      : await request<BotShopSettings>(endpoint, "POST", definition, { signal: lifetime.signal });
    settings.value = saved;
    draft.value = copy(saved.definition);
    notice.value = t("botShop.saved");
  });
}
onMounted(reload);
</script>

<template>
  <section class="card card-pad form-grid" data-testid="shop-settings">
    <h2 data-testid="shop-title">{{ t('botShop.title') }}</h2>
    <p>{{ t('botShop.help') }}</p>
    <p v-if="error" class="message error" role="alert" data-testid="shop-error">{{ error }}</p>
    <p v-if="notice" class="message" role="status">{{ notice }}</p>
    <p v-if="settings">{{ t('productCatalog.revision') }} <span data-testid="shop-revision">{{ settings.revision }}</span></p>
    <p v-else>{{ t('botShop.notCreated') }}</p>
    <button class="btn secondary" data-testid="shop-reload" :disabled="busy" @click="reload">{{ t('bots.reload') }}</button>
    <form v-if="draft" class="form-grid" @submit.prevent="save">
      <BotShopDefinitionEditor v-model="draft" :disabled="busy" />
      <button class="btn" data-testid="shop-save" :disabled="busy">{{ t(settings ? 'foundation.save' : 'botShop.create') }}</button>
    </form>
    <p class="hint-box">{{ t('botShop.scheduleHelp') }} <RouterLink to="/">{{ t('botShop.schedules') }}</RouterLink></p>
  </section>
</template>
