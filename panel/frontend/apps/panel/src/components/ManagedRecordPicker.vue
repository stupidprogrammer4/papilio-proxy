<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{
  title: string;
  items: { id: string; label: string }[];
  count: number;
  page: number;
  pageSize: number;
  selectedId?: string;
  busy: boolean;
}>();
const emit = defineEmits<{
  search: [value: { q: string; page: number; page_size: number }];
  select: [id: string];
}>();
const { t } = useI18n();
const search = ref("");
const pageSize = ref(props.pageSize);
function load(page: number): void {
  emit("search", { q: search.value, page, page_size: pageSize.value });
}
</script>

<template>
  <section class="form-grid">
    <h3>{{ title }}</h3>
    <form class="form-grid" @submit.prevent="load(1)">
      <label class="field"><span>{{ t('serviceSetup.search') }}</span><input v-model="search" type="search" maxlength="200" :disabled="busy" /></label>
      <label class="field"><span>{{ t('serviceSetup.pageSize') }}</span><input v-model.number="pageSize" type="number" min="1" step="1" required :disabled="busy" /></label>
      <button class="btn secondary" :disabled="busy">{{ t('serviceSetup.search') }}</button>
    </form>
    <p>{{ t('serviceSetup.total', { count }) }}</p>
    <p v-if="!items.length && !busy" data-testid="record-empty">{{ t('serviceSetup.empty') }}</p>
    <div v-for="item in items" :key="item.id">
      <button type="button" class="btn secondary" :aria-pressed="selectedId === item.id" :disabled="busy" @click="emit('select', item.id)">{{ item.label }}</button>
    </div>
    <div class="pager">
      <button type="button" :aria-label="t('serviceSetup.previous')" :disabled="busy || page <= 1" @click="load(page - 1)">‹</button>
      <span>{{ t('serviceSetup.page', { page }) }}</span>
      <button type="button" :aria-label="t('serviceSetup.next')" :disabled="busy || page * props.pageSize >= count" @click="load(page + 1)">›</button>
    </div>
  </section>
</template>
