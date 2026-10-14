<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useAuth } from "@papilio/auth";
import type { StaffScopeCatalog } from "@papilio/api";
const { t } = useI18n();
const props = defineProps<{ catalog: StaffScopeCatalog | null; disabled?: boolean; allowOwner?: boolean; grants?: string[]; ownerLabel?: string }>();
const model = defineModel<string[]>({ required: true });
const auth = useAuth();
const areaKeys: Record<string, string> = { resellers: "staffScope.resellers", team: "staffScope.team", wallet: "staffScope.wallet", staff: "staffScope.staff", customers: "staffScope.customers", catalog: "staffScope.plans", payments: "staffScope.payments", subscriptions: "staffScope.subscriptions", network: "staffScope.network", settings: "staffScope.settings", support: "staffScope.support", notifications: "staffScope.notifications" };
const levelKeys: Record<string, string> = { read: "staffScope.view", create: "staffScope.create", update: "staffScope.update", delete: "staffScope.delete", manage: "staffScope.actions", "*": "staffScope.all" };
const choices = computed(() => props.catalog?.areas.flatMap(area => props.catalog!.levels.map(level => ({ value: area + ":" + level, label: (areaKeys[area] ? t(areaKeys[area]) : area) + " · " + (levelKeys[level] ? t(levelKeys[level]) : level) }))) ?? []);
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
  <fieldset :disabled="disabled" class="scope-grid"><legend>{{t("staffScope.allowedPermissions")}}</legend>
    <label v-if="allowOwner !== false && ((grants ?? auth.session?.scopes)?.includes('*') || model.includes('*'))" class="scope-choice"><input type="checkbox" :checked="model.includes('*')" :disabled="!mayGrant('*')" @change="toggle('*', $event)" /> {{ ownerLabel ?? t("staffScope.fullSystemAccess") }}</label>
    <label v-for="choice in choices" :key="choice.value" class="scope-choice"><input type="checkbox" :checked="model.includes(choice.value)" :disabled="!mayGrant(choice.value)" @change="toggle(choice.value, $event)" /> {{ choice.label }}</label>
  </fieldset>
</template>
<style scoped>
.scope-grid { border: 1px solid var(--line, #ddd); border-radius: 12px; padding: 12px; display:grid; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); gap:8px; }
.scope-choice { display:flex; align-items:center; gap:8px; font-size:13px; }
.scope-choice input { width:auto; min-height:0; }
</style>
