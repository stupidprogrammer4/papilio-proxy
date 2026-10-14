<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { item, privateFile, request, query, type Page, type PublicSubscription, type PublicProfile, type ConfigurationDownload } from "@papilio/api";
import { useI18n } from "vue-i18n";
import { useLocalizedFormats } from "../composables/useLocalizedFormats";
const route = useRoute();
const { t, locale } = useI18n();
const { date, number } = useLocalizedFormats();
const detail = ref<PublicSubscription | null>(null); const profiles = ref<PublicProfile[]>([]); const page = ref(1); const pages = ref(1);
const loading = ref(false); const busy = ref(false); const error = ref(""); const notice = ref(""); let version = 0;
const statusKeys: Record<string, string> = { customer_hold: "serviceSuspended", revoking: "revoking", exhausted: "quotaExhausted", suspended: "suspended", active: "active", pending_provision: "pendingProvision", expired: "expired", failed: "provisionFailed", cancelled: "cancelled" };
const protocols: Record<string, string> = { vless_reality: "VLESS REALITY", vless_tls: "VLESS", vmess_tls: "VMess", trojan_tls: "Trojan", shadowsocks: "Shadowsocks", hysteria2: "Hysteria2", wireguard: "WireGuard", openvpn: "OpenVPN" };
const qrUrl = ref(""); const qrTitle = ref(""); const qrBusy = ref(false); let qrVersion = 0;
function clearQr(): void { qrVersion++; if (qrUrl.value) URL.revokeObjectURL(qrUrl.value); qrUrl.value = ""; qrTitle.value = ""; qrBusy.value = false; }
async function showQr(profile?: PublicProfile): Promise<void> {
  clearQr(); const current = token(); const render = qrVersion; qrBusy.value = true; error.value = ""; notice.value = "";
  const suffix = profile ? `/profiles/${profile.profile_id}/qr?${query({ host_id: profile.host_id ?? undefined })}` : "/qr";
  try { const image = await privateFile(`/s/${encodeURIComponent(current)}${suffix}`); if (render !== qrVersion || current !== token()) return; qrUrl.value = URL.createObjectURL(image); qrTitle.value = profile ? profile.label : t("customerService.subscriptionUrl"); }
  catch (cause) { if (render === qrVersion && current === token()) error.value = cause instanceof Error ? cause.message : t("customerService.operationFailed"); }
  finally { if (render === qrVersion) qrBusy.value = false; }
}
onBeforeUnmount(() => { version++; clearQr(); });
function token(): string { return String(route.params.token ?? ""); }
async function load(): Promise<void> {
  clearQr(); const current = token(); const read = ++version; loading.value = true; error.value = "";
  try { const [summary, rows] = await Promise.all([item<PublicSubscription>(`/s/${encodeURIComponent(current)}/status`), request<Page<PublicProfile>>(`/s/${encodeURIComponent(current)}/profiles?${query({ page: page.value })}`)]); if (read !== version || current !== token()) return; detail.value = summary; profiles.value = rows.data; pages.value = rows.meta.pager?.total_pages ?? 1; document.title = `${summary.brand_title} | ${t("customerService.title")}`; }
  catch (cause) { if (read === version) error.value = cause instanceof Error ? cause.message : t("customerService.operationFailed"); }
  finally { if (read === version) loading.value = false; }
}
async function download(profile: PublicProfile): Promise<void> {
  const current = token(); busy.value = true; error.value = "";
  try { const file = await item<ConfigurationDownload>(`/s/${encodeURIComponent(current)}/profiles/${profile.profile_id}/download?${query({ host_id: profile.host_id ?? undefined })}`); if (current !== token()) return; const url = URL.createObjectURL(new Blob([file.content], { type: file.media_type })); const link = document.createElement("a"); link.href = url; link.download = file.filename; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url); notice.value = t("customerService.downloaded"); }
  catch (cause) { if (current === token()) error.value = cause instanceof Error ? cause.message : t("customerService.operationFailed"); }
  finally { if (current === token()) busy.value = false; }
}
async function copyLink(): Promise<void> {
  const current = token(); error.value = ""; notice.value = "";
  try { if (!detail.value?.feed_url) return; await navigator.clipboard.writeText(detail.value.feed_url); notice.value = t("customerService.copied"); }
  catch { error.value = t("customerService.copyFailed"); }
}
watch(() => route.params.token, () => { version++; detail.value = null; profiles.value = []; page.value = 1; busy.value = false; notice.value = ""; void load(); }, { immediate: true });
watch(locale, () => { if (detail.value) document.title = `${detail.value.brand_title} | ${t("customerService.title")}`; });
</script>
<template>
  <main class="service-page">
    <div class="page-head"><div><p class="eyebrow">{{ t("customerService.eyebrow") }}</p><h1>{{ detail?.brand_title ?? t("customerService.title") }}</h1><p class="subtitle">{{ t("customerService.privateHint") }}</p></div><button class="btn secondary" :disabled="loading || busy" @click="load">{{ t("customerService.refresh") }}</button></div>
    <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
    <p v-if="loading">{{ t("customerService.loading") }}</p>
    <section v-if="detail" class="card card-pad form-grid">
      <div class="detail-line"><span>{{ t("customerService.subscriptionId") }}</span><strong>{{ number(detail.id, 0) }}</strong></div>
      <div class="detail-line"><span>{{ t("customerService.status") }}</span><strong>{{ t(`customerService.statuses.${statusKeys[detail.status]??'unknown'}`) }}</strong></div>
      <div class="detail-line"><span>{{ t("customerService.expiry") }}</span><strong>{{ date(detail.expires_at) }}</strong></div>
      <div class="detail-line"><span>{{ t("customerService.quota") }} (GiB)</span><strong>{{ (detail.quota_bytes === null ? t("customerService.unlimited") : number(detail.quota_bytes / 1_073_741_824)) }}</strong></div>
      <div class="detail-line"><span>{{ t("customerService.usage") }} (GiB)</span><strong>{{ number(detail.used_bytes / 1_073_741_824) }}</strong></div>
      <div class="detail-line"><span>{{ t("customerService.autoRenew") }}</span><strong>{{ detail.auto_renew ? t("customerService.autoRenewEnabled") : t("customerService.disabled") }}</strong></div>
      <button v-if="detail.feed_url !== null" class="btn" @click="copyLink">{{ t("customerService.copyUrl") }}</button><button v-if="detail.feed_url && detail.qr_enabled" class="btn secondary" :disabled="qrBusy || loading" @click="showQr()">{{ t("customerService.subscriptionQr") }}</button>
      <p class="hint-box">{{ t("customerService.botHint") }}</p>
      <a v-if="detail.support_handle" class="btn secondary" :href="'https://t.me/' + detail.support_handle.replace(/^@/, '')" target="_blank" rel="noreferrer noopener">{{ t("customerService.support") }}</a>
    </section>
    <section v-if="qrBusy || qrUrl" class="card card-pad service-qr" :aria-label="t('customerService.privateQr')">
      <p v-if="qrBusy" role="status">{{ t("customerService.loadingQr") }}</p>
      <template v-if="qrUrl"><h2>{{ qrTitle }}</h2><img :src="qrUrl" :alt="t('customerService.privateQr')" /><p class="hint-box">{{ t("customerService.qrHint") }}</p><a class="btn" :href="qrUrl" download="connection-qr.png">{{ t("customerService.downloadImage") }}</a></template>
      <button class="btn secondary" @click="clearQr">{{ t("customerService.closeImage") }}</button>
    </section>
    <section v-if="detail" class="card card-pad service-profiles"><h2>{{ t("customerService.connections") }}</h2>
      <p v-if="!loading && !profiles.length && !error">{{ t("customerService.noConnections") }}</p>
      <div class="table-wrap"><table v-if="profiles.length" class="data-table"><thead><tr><th>{{ t("customerService.route") }}</th><th>{{ t("customerService.protocol") }}</th><th>{{ t("customerService.download") }}</th></tr></thead><tbody><tr v-for="profile in profiles" :key="profile.profile_id + ':' + profile.host_id"><td>{{ profile.label }}</td><td>{{ protocols[profile.protocol] ?? t('customerService.connect') }}</td><td><button class="btn small" :disabled="busy" @click="download(profile)">{{ t("customerService.downloadFile") }}</button><button v-if="detail.qr_enabled" class="btn small secondary" :disabled="qrBusy || loading" @click="showQr(profile)">{{ t("customerService.connectionQr") }}</button></td></tr></tbody></table></div>
      <div class="pager"><button :disabled="page <= 1 || loading" @click="page--; load()">‹</button><span>{{ number(page, 0) }}</span><button :disabled="page >= pages || loading" @click="page++; load()">›</button></div>
    </section>
  </main>
</template>
<style scoped>
.service-page { max-width: 920px; margin: 0 auto; padding: 24px 16px; min-inline-size: 0; }
.service-qr { margin-top: 20px; display: grid; justify-items: center; gap: 12px; }
.service-qr img { max-width: 100%; height: auto; max-height: 70vh; object-fit: contain; background: white; }
.service-profiles { margin-top: 20px; }
</style>
