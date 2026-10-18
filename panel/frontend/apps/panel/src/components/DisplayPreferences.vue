<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { useDisplayPreferences } from "../stores/displayPreferences";

const display = useDisplayPreferences();
withDefaults(defineProps<{ compact?: boolean; showTheme?: boolean }>(), { compact: false, showTheme: true });
const { t } = useI18n();
let stopListening: (() => void) | undefined;
onMounted(() => { stopListening = display.listenForSystemTheme(); });
onBeforeUnmount(() => stopListening?.());
</script>

<template>
  <div class="display-preferences" :class="{ 'display-preferences-compact': compact }">
    <label><span>{{ t('display.language') }}</span><select v-model="display.locale" data-testid="locale-selector"><option value="en">English</option><option value="fa">فارسی</option></select></label>
    <label v-if="showTheme"><span>{{ t('display.theme') }}</span><select v-model="display.theme" data-testid="theme-selector"><option value="light">{{ t('display.light') }}</option><option value="dark">{{ t('display.dark') }}</option><option value="system">{{ t('display.system') }}</option></select></label>
    <small v-if="!display.persistent" role="status">{{ t('display.temporary') }}</small>
  </div>
</template>
