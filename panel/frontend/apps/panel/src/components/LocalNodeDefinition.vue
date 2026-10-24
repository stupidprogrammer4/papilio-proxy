<script setup lang="ts">
import { useI18n } from "vue-i18n";
import type { LocalNodeDefinition } from "@papilio/api";
const selected = defineModel<LocalNodeDefinition>({ required: true });
const { t } = useI18n();
const runtimeFields = ["request_timeout_seconds", "read_header_timeout_seconds", "idle_timeout_seconds", "shutdown_timeout_seconds", "max_body_bytes", "max_grpc_reply_bytes"] as const;
const certificateFields = ["validity_seconds", "authority_validity_seconds", "backdate_seconds"] as const;
</script>
<template>
  <details>
    <summary data-testid="local-definition-advanced">{{ t('localNode.advanced') }}</summary>
    <div class="form-grid">
      <p>{{ t('localNode.initialHelp') }}</p>
      <label class="field"><span>{{ t('nodes.name') }}</span><input v-model="selected.node.name" data-testid="local-node-name" required maxlength="80" /></label>
      <label class="field"><span>{{ t('localNode.coreName') }}</span><input v-model="selected.core_name" required maxlength="80" /></label>
      <label class="field"><span>{{ t('localNode.inboundTag') }}</span><input v-model="selected.inbound_tag" required maxlength="80" dir="ltr" /></label>
      <label class="field"><span>{{ t('localNode.publicHost') }}</span><input v-model="selected.public_host" required maxlength="255" dir="ltr" /></label>
      <label class="field"><span>{{ t('localNode.publicPort') }}</span><input v-model.number="selected.public_port" required type="number" min="1" max="65535" step="1" /></label>
      <label class="field"><span>{{ t('localNode.userLevel') }}</span><input v-model.number="selected.default_user_level" required type="number" min="0" max="4294967295" step="1" /></label>
      <p class="hint-box">{{ t('localNode.coordinatedHelp') }}</p>
      <label class="field"><span>{{ t('localNode.bindAddress') }}</span><input v-model="selected.bind_address" required dir="ltr" /></label>
      <label class="field"><span>{{ t('localNode.bindPort') }}</span><input v-model.number="selected.bind_port" required type="number" min="1" max="65535" step="1" /></label>
      <label class="field"><span>{{ t('nodes.endpoint') }}</span><input v-model="selected.node.endpoint_url" required type="url" maxlength="500" dir="ltr" /></label>
      <label v-for="field in (['listen_address', 'xray_api_address'] as const)" :key="field" class="field"><span>{{ t(`nodes.fields.${field}`) }}</span><input v-model="selected.node.runtime[field]" required dir="ltr" /></label>
      <label v-for="field in runtimeFields" :key="field" class="field"><span>{{ t(`nodes.fields.${field}`) }}</span><input v-model.number="selected.node.runtime[field]" :data-testid="`local-${field}`" type="number" min="1" :max="field === 'max_body_bytes' ? Number.MAX_SAFE_INTEGER : 2147483647" step="1" required /></label>
      <label v-for="field in certificateFields" :key="field" class="field"><span>{{ t(`nodes.fields.${field}`) }}</span><input v-model.number="selected.node.certificate_policy[field]" type="number" :min="field === 'backdate_seconds' ? 0 : 1" max="2147483647" step="1" required /></label>
    </div>
  </details>
</template>
