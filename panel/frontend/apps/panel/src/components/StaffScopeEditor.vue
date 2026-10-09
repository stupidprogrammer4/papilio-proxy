<script setup lang="ts">
import { computed } from "vue";
import { useAuth } from "@papilio/auth";
import type { StaffScopeCatalog } from "@papilio/api";
const props = defineProps<{ catalog: StaffScopeCatalog | null; disabled?: boolean; allowOwner?: boolean; grants?: string[]; ownerLabel?: string }>();
const model = defineModel<string[]>({ required: true });
const auth = useAuth();
const areas: Record<string, string> = { resellers: "Resellers", team: "Reseller team", wallet: "Wallet", staff: "Staff", customers: "Customers", catalog: "Plans", payments: "Payments", subscriptions: "Subscriptions", network: "Network", settings: "Settings", support: "Support", notifications: "Notifications" };
const levels: Record<string, string> = { read: "View", create: "Create", update: "Update", delete: "Delete", manage: "Actions", "*": "All operations" };
const choices = computed(() => props.catalog?.areas.flatMap(area => props.catalog!.levels.map(level => ({ value: `${area}:${level}`, label: `${areas[area] ?? area} · ${levels[level] ?? level}` }))) ?? []);
function mayGrant(value: string): boolean {
  const grants = props.grants ?? auth.session?.scopes ?? [];
  return grants.includes("*") || grants.includes(value) || grants.includes(`${value.split(":")[0]}:*`);
}
function toggle(value: string, event: Event): void {
  if (props.disabled || !mayGrant(value)) return;
  model.value = (event.target as HTMLInputElement).checked ? [...model.value, value] : model.value.filter(scope => scope !== value);
}
</script>
<template>
  <fieldset :disabled="disabled" class="scope-grid"><legend>Allowed permissions</legend>
    <label v-if="allowOwner !== false && ((grants ?? auth.session?.scopes)?.includes('*') || model.includes('*'))" class="scope-choice"><input type="checkbox" :checked="model.includes('*')" :disabled="!mayGrant('*')" @change="toggle('*', $event)" /> {{ ownerLabel ?? 'Full system access' }}</label>
    <label v-for="choice in choices" :key="choice.value" class="scope-choice"><input type="checkbox" :checked="model.includes(choice.value)" :disabled="!mayGrant(choice.value)" @change="toggle(choice.value, $event)" /> {{ choice.label }}</label>
  </fieldset>
</template>
<style scoped>
.scope-grid { border: 1px solid var(--line, #ddd); border-radius: 12px; padding: 12px; display:grid; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); gap:8px; }
.scope-choice { display:flex; align-items:center; gap:8px; font-size:13px; }
.scope-choice input { width:auto; min-height:0; }
</style>
