<script setup lang="ts">
import { computed, ref } from "vue";
import type { BotLocale, BotLocaleTextSettings, BotPresentationSettings } from "@papilio/api";

const props = defineProps<{
  modelValue: BotPresentationSettings;
  disabled?: boolean;
}>();
const emit = defineEmits<{
  "update:modelValue": [value: BotPresentationSettings];
}>();

const selectedLocale = ref<BotLocale>("fa");
const messageSearch = ref("");
const filteredMessages = computed(() => Object.keys(props.modelValue.message_catalog.fa)
  .filter((source) => source.toLocaleLowerCase().includes(messageSearch.value.toLocaleLowerCase())));

function setLocaleText<K extends keyof BotLocaleTextSettings>(
  field: K,
  value: BotLocaleTextSettings[K],
): void {
  emit("update:modelValue", {
    ...props.modelValue,
    localized_texts: {
      ...props.modelValue.localized_texts,
      [selectedLocale.value]: {
        ...props.modelValue.localized_texts[selectedLocale.value],
        [field]: value,
      },
    },
  });
}

function setVisibility(field: keyof Pick<BotPresentationSettings,
  "show_purchases" | "show_loyalty" | "show_trials" | "show_account" |
  "show_catalog" | "show_subscriptions" | "show_wallet" | "show_support">,
  value: boolean): void {
  emit("update:modelValue", { ...props.modelValue, [field]: value });
}

function setPhoto(value: string | null): void {
  emit("update:modelValue", { ...props.modelValue, welcome_photo_url: value });
}

function setMessage(source: string, value: string): void {
  emit("update:modelValue", {
    ...props.modelValue,
    message_catalog: {
      ...props.modelValue.message_catalog,
      [selectedLocale.value]: {
        ...props.modelValue.message_catalog[selectedLocale.value],
        [source]: value,
      },
    },
  });
}

const buttons = [
  ["purchases_button_label", "show_purchases", "botPresentation.purchases"],
  ["loyalty_button_label", "show_loyalty", "botPresentation.loyalty"],
  ["trial_button_label", "show_trials", "botPresentation.trials"],
  ["account_button_label", "show_account", "botPresentation.account"],
  ["catalog_button_label", "show_catalog", "botPresentation.catalog"],
  ["subscriptions_button_label", "show_subscriptions", "botPresentation.subscriptions"],
  ["wallet_button_label", "show_wallet", "botPresentation.wallet"],
  ["support_button_label", "show_support", "botPresentation.support"],
] as const;

const locales: { key: BotLocale; label: string }[] = [
  { key: "fa", label: "فارسی" },
  { key: "en", label: "English" },
  { key: "ru", label: "Русский" },
  { key: "zh", label: "中文" },
];
</script>

<template>
  <section class="form-grid" :aria-disabled="disabled">
    <h3>{{ $t("botPresentation.title") }}</h3>
    <label class="field">
      <span>{{ $t("botPresentation.locale") }}</span>
      <select v-model="selectedLocale">
        <option v-for="locale in locales" :key="locale.key" :value="locale.key">{{ locale.label }}</option>
      </select>
    </label>
    <label class="field">
      <span>{{ $t("botPresentation.welcome") }}</span>
      <textarea
        :value="modelValue.localized_texts[selectedLocale].welcome_message"
        rows="5"
        maxlength="3000"
        @input="setLocaleText('welcome_message', ($event.target as HTMLTextAreaElement).value)"
      />
    </label>
    <p class="hint-box">{{ $t("botPresentation.placeholders") }}</p>
    <label class="field">
      <span>{{ $t("botPresentation.photoUrl") }}</span>
      <input
        :value="modelValue.welcome_photo_url ?? ''"
        type="url"
        maxlength="2048"
        placeholder="https://cdn.example.com/bot.webp"
        @input="setPhoto(($event.target as HTMLInputElement).value.trim() || null)"
      />
    </label>
    <img
      v-if="modelValue.welcome_photo_url"
      class="bot-photo-preview"
      :src="modelValue.welcome_photo_url"
      :alt="$t('botPresentation.photoPreview')"
      loading="lazy"
      referrerpolicy="no-referrer"
    />
    <p class="hint-box">{{ $t("botPresentation.photoHint") }}</p>
    <div class="form-grid bot-menu-settings">
      <h4>{{ $t("botPresentation.menu") }}</h4>
      <div v-for="[labelField, visibleField, label] in buttons" :key="labelField" class="bot-menu-setting">
        <label class="field">
          <span>{{ $t(label) }}</span>
          <input
            :value="modelValue.localized_texts[selectedLocale][labelField]"
            maxlength="64"
            @input="setLocaleText(labelField, ($event.target as HTMLInputElement).value)"
          />
        </label>
        <label class="check-row">
          <input
            :checked="modelValue[visibleField]"
            type="checkbox"
            @change="setVisibility(visibleField, ($event.target as HTMLInputElement).checked)"
          />
          {{ $t("botPresentation.showButton") }}
        </label>
      </div>
    </div>
    <div class="form-grid bot-catalog-editor">
      <h4>{{ $t("botPresentation.messageCatalog") }}</h4>
      <label class="field">
        <span>{{ $t("botPresentation.searchMessages") }}</span>
        <input v-model="messageSearch" type="search" />
      </label>
      <p class="hint-box">{{ $t("botPresentation.messageCatalogHint") }}</p>
      <label v-for="source in filteredMessages" :key="source" class="field">
        <span dir="auto">{{ source }}</span>
        <textarea
          :value="modelValue.message_catalog[selectedLocale][source]"
          rows="2"
          maxlength="4000"
          dir="auto"
          @input="setMessage(source, ($event.target as HTMLTextAreaElement).value)"
        />
      </label>
    </div>
  </section>
</template>

<style scoped>
.bot-photo-preview { width: min(100%, 360px); max-height: 240px; object-fit: contain; border-radius: 12px; }
.bot-menu-settings { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
.bot-menu-setting { display: grid; gap: 8px; }
.bot-catalog-editor { max-height: 70vh; overflow: auto; }
</style>
