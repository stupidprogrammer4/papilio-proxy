<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { item, privateFile, request, query, type Page, type PublicSubscription, type PublicProfile, type ConfigurationDownload } from "@papilio/api";
import { useI18n } from "vue-i18n";
import { useLocalizedFormats } from "../composables/useLocalizedFormats";
const route = useRoute();
const { t, locale } = useI18n();
const { date, number } = useLocalizedFormats();
type ClientPlatform = "android" | "ios" | "windows" | "macos" | "linux";
const platforms: ClientPlatform[] = ["android", "ios", "windows", "macos", "linux"];
const platform = ref<ClientPlatform>("android");
const clients: Record<ClientPlatform, { name: string; url: string; description: string }[]> = {
  android: [
    { name: "Hiddify", url: "https://github.com/hiddify/hiddify-app/releases/latest", description: "crossPlatformClient" },
    { name: "v2rayNG", url: "https://github.com/2dust/v2rayNG/releases", description: "androidClient" },
  ],
  ios: [
    { name: "Hiddify", url: "https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532", description: "crossPlatformClient" },
    { name: "Streisand", url: "https://apps.apple.com/us/app/streisand/id6450534064", description: "iosClient" },
  ],
  windows: [
    { name: "Hiddify", url: "https://github.com/hiddify/hiddify-app/releases/latest", description: "crossPlatformClient" },
    { name: "v2rayN", url: "https://github.com/2dust/v2rayN/releases", description: "desktopClient" },
  ],
  macos: [
    { name: "Hiddify", url: "https://github.com/hiddify/hiddify-app/releases/latest", description: "crossPlatformClient" },
    { name: "v2rayN", url: "https://github.com/2dust/v2rayN/releases", description: "desktopClient" },
  ],
  linux: [
    { name: "Hiddify", url: "https://github.com/hiddify/hiddify-app/releases/latest", description: "crossPlatformClient" },
    { name: "v2rayN", url: "https://github.com/2dust/v2rayN/releases", description: "desktopClient" },
  ],
};
const usagePercent = computed(() => {
  if (!detail.value?.quota_bytes || detail.value.quota_bytes <= 0) return 0;
  return Math.min(100, Math.max(0, detail.value.used_bytes / detail.value.quota_bytes * 100));
});
const detail = ref<PublicSubscription | null>(null); const profiles = ref<PublicProfile[]>([]); const page = ref(1); const pages = ref(1);
const loading = ref(false); const busy = ref(false); const error = ref(""); const notice = ref(""); let version = 0;
const statusKeys: Record<string, string> = { customer_hold: "serviceSuspended", revoking: "revoking", exhausted: "quotaExhausted", suspended: "suspended", active: "active", pending_provision: "pendingProvision", expired: "expired", failed: "provisionFailed", cancelled: "cancelled" };
const protocols: Record<string, string> = { vless_reality: "VLESS REALITY", vless_tls: "VLESS", vmess_tls: "VMess", trojan_tls: "Trojan", shadowsocks: "Shadowsocks", hysteria2: "Hysteria2", wireguard: "WireGuard", openvpn: "OpenVPN" };
const qrUrl = ref(""); const qrTitle = ref(""); const qrBusy = ref(false); let qrVersion = 0;
let themeQuery: MediaQueryList | null = null;
let previousTheme: string | undefined;
function applySystemTheme(isDark: boolean): void {
  document.documentElement.dataset.theme = isDark ? "dark" : "light";
}
function followSystemTheme(): void {
  themeQuery = matchMedia("(prefers-color-scheme: dark)");
  previousTheme = document.documentElement.dataset.theme;
  applySystemTheme(themeQuery.matches);
  themeQuery.addEventListener("change", onSystemThemeChange);
}
function onSystemThemeChange(event: MediaQueryListEvent): void {
  applySystemTheme(event.matches);
}
function clearQr(): void { qrVersion++; if (qrUrl.value) URL.revokeObjectURL(qrUrl.value); qrUrl.value = ""; qrTitle.value = ""; qrBusy.value = false; }
async function showQr(profile?: PublicProfile): Promise<void> {
  clearQr(); const current = token(); const render = qrVersion; qrBusy.value = true; error.value = ""; notice.value = "";
  const suffix = profile ? `/profiles/${profile.profile_id}/qr?${query({ host_id: profile.host_id ?? undefined })}` : "/qr";
  try { const image = await privateFile(`/s/${encodeURIComponent(current)}${suffix}`); if (render !== qrVersion || current !== token()) return; qrUrl.value = URL.createObjectURL(image); qrTitle.value = profile ? profile.label : t("customerService.subscriptionUrl"); }
  catch (cause) { if (render === qrVersion && current === token()) error.value = cause instanceof Error ? cause.message : t("customerService.operationFailed"); }
  finally { if (render === qrVersion) qrBusy.value = false; }
}
onMounted(followSystemTheme);
onBeforeUnmount(() => { version++; clearQr(); themeQuery?.removeEventListener("change", onSystemThemeChange); if (previousTheme === undefined) delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = previousTheme; });
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
    <section v-if="detail" class="service-summary card card-pad">
      <div class="usage-ring" :style="{'--usage-percent': `${usagePercent}%`}"><div><strong>{{ number(usagePercent, 0) }}%</strong><span>{{ t("customerService.used") }}</span></div></div>
      <div class="summary-facts">
      <div class="detail-line"><span>{{ t("customerService.subscriptionId") }}</span><strong>{{ number(detail.id, 0) }}</strong></div>
      <div class="detail-line"><span>{{ t("customerService.status") }}</span><strong>{{ t(`customerService.statuses.${statusKeys[detail.status]??'unknown'}`) }}</strong></div>
      <div class="detail-line"><span>{{ t("customerService.expiry") }}</span><strong>{{ date(detail.expires_at) }}</strong></div>
      <div class="detail-line"><span>{{ t("customerService.quota") }} (GiB)</span><strong>{{ (detail.quota_bytes === null ? t("customerService.unlimited") : number(detail.quota_bytes / 1_073_741_824)) }}</strong></div>
      <div class="detail-line"><span>{{ t("customerService.usage") }} (GiB)</span><strong>{{ number(detail.used_bytes / 1_073_741_824) }}</strong></div>
      <div class="detail-line"><span>{{ t("customerService.autoRenew") }}</span><strong>{{ detail.auto_renew ? t("customerService.autoRenewEnabled") : t("customerService.disabled") }}</strong></div>
      </div>
      <button v-if="detail.feed_url !== null" class="btn" @click="copyLink">{{ t("customerService.copyUrl") }}</button><button v-if="detail.feed_url && detail.qr_enabled" class="btn secondary" :disabled="qrBusy || loading" @click="showQr()">{{ t("customerService.subscriptionQr") }}</button>
      <p class="hint-box service-private-hint">{{ t("customerService.privateHint") }}</p>
      <a v-if="detail.support_handle" class="btn secondary support-action" :href="'https://t.me/' + detail.support_handle.replace(/^@/, '')" target="_blank" rel="noreferrer noopener">{{ t("customerService.support") }}</a>
    </section>
    <section v-if="detail" class="client-guide card card-pad">
      <div class="section-heading"><div><p class="eyebrow">{{ t("customerService.setupEyebrow") }}</p><h2>{{ t("customerService.appsByPlatform") }}</h2></div><p>{{ t("customerService.importHint") }}</p></div>
      <div class="platform-tabs" role="tablist" :aria-label="t('customerService.appsByPlatform')">
        <button v-for="item in platforms" :key="item" class="btn small" :class="{secondary: platform !== item}" role="tab" :aria-selected="platform === item" :tabindex="platform === item ? 0 : -1" @click="platform=item">{{ t(`customerService.platforms.${item}`) }}</button>
      </div>
      <div class="client-grid" role="tabpanel">
        <article v-for="client in clients[platform]" :key="client.name" class="client-card">
          <div><h3>{{ client.name }}</h3><p>{{ t(`customerService.clientDescriptions.${client.description}`) }}</p></div>
          <a class="btn small secondary" :href="client.url" :aria-label="`${t('customerService.getApp')} ${client.name}`" target="_blank" rel="noreferrer noopener">{{ t("customerService.getApp") }} <span aria-hidden="true">↗</span></a>
        </article>
      </div>
    </section>
    <section v-if="qrBusy || qrUrl" class="card card-pad service-qr" :aria-label="t('customerService.privateQr')">
      <p v-if="qrBusy" role="status">{{ t("customerService.loadingQr") }}</p>
      <template v-if="qrUrl"><h2>{{ qrTitle }}</h2><img :src="qrUrl" :alt="t('customerService.privateQr')" /><p class="hint-box">{{ t("customerService.qrHint") }}</p><a class="btn" :href="qrUrl" download="connection-qr.png">{{ t("customerService.downloadImage") }}</a></template>
      <button class="btn secondary" @click="clearQr">{{ t("customerService.closeImage") }}</button>
    </section>
    <section v-if="detail" class="card card-pad service-profiles"><div class="section-heading"><div><p class="eyebrow">{{ t("customerService.setupEyebrow") }}</p><h2>{{ t("customerService.connections") }}</h2></div><p>{{ t("customerService.configHint") }}</p></div>
      <p v-if="!loading && !profiles.length && !error">{{ t("customerService.noConnections") }}</p>
      <div class="table-wrap"><table v-if="profiles.length" class="data-table"><thead><tr><th>{{ t("customerService.route") }}</th><th>{{ t("customerService.protocol") }}</th><th>{{ t("customerService.download") }}</th></tr></thead><tbody><tr v-for="profile in profiles" :key="profile.profile_id + ':' + profile.host_id"><td>{{ profile.label }}</td><td>{{ protocols[profile.protocol] ?? t('customerService.connect') }}</td><td><button class="btn small" :disabled="busy" @click="download(profile)">{{ t("customerService.downloadFile") }}</button><button v-if="detail.qr_enabled" class="btn small secondary" :disabled="qrBusy || loading" @click="showQr(profile)">{{ t("customerService.connectionQr") }}</button></td></tr></tbody></table></div>
      <div class="pager"><button :disabled="page <= 1 || loading" @click="page--; load()">‹</button><span>{{ number(page, 0) }}</span><button :disabled="page >= pages || loading" @click="page++; load()">›</button></div>
    </section>
  </main>
</template>
<style scoped>
.service-page { max-width: 980px; margin: 0 auto; padding: 32px 16px 56px; min-inline-size: 0; }
.service-page .page-head { align-items: center; margin-bottom: 22px; }
.service-page .eyebrow { color: var(--muted); font-size: 11px; letter-spacing: .08em; margin: 0 0 4px; }
.service-page h2 { margin: 0; font-size: 20px; }
.service-summary { display: grid; grid-template-columns: 148px minmax(0, 1fr) auto auto; align-items: center; gap: 18px; }
.summary-facts { display: grid; gap: 6px; min-width: 0; }
.detail-line { display: flex; justify-content: space-between; gap: 16px; padding: 7px 0; border-bottom: 1px solid var(--border); }
.detail-line span, .section-heading > p, .client-card p { color: var(--muted); }
.detail-line strong { text-align: end; }
.usage-ring { --usage-percent: 0%; width: 132px; aspect-ratio: 1; display: grid; place-items: center; border-radius: 50%; background: conic-gradient(var(--accent-strong) var(--usage-percent), var(--border) 0); }
.usage-ring > div { width: 104px; aspect-ratio: 1; display: grid; align-content: center; justify-items: center; border-radius: 50%; background: var(--surface); }
.usage-ring strong { font-size: 24px; line-height: 1.2; }
.usage-ring span { color: var(--muted); font-size: 12px; }
.service-private-hint { grid-column: 1 / -1; margin: 0; }
.support-action { grid-column: 1 / -1; justify-self: start; }
.client-guide, .service-profiles, .service-qr { margin-top: 18px; }
.section-heading { display: flex; justify-content: space-between; align-items: end; gap: 20px; margin-bottom: 16px; }
.section-heading > p { max-width: 440px; margin: 0; font-size: 13px; }
.platform-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.client-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
.client-card { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 16px; border: 1px solid var(--border); border-radius: 14px; background: var(--glass); }
.client-card h3 { margin: 0; font-size: 15px; }
.client-card p { margin: 4px 0 0; font-size: 12px; }
.client-card .btn { white-space: nowrap; }
.service-qr { display: grid; justify-items: center; gap: 12px; }
.service-qr img { max-width: 100%; height: auto; max-height: 70vh; object-fit: contain; background: white; }
@media (max-width: 760px) { .service-summary { grid-template-columns: 112px minmax(0, 1fr); } .usage-ring { width: 104px; } .usage-ring > div { width: 80px; } .usage-ring strong { font-size: 19px; } .service-summary > .btn { grid-column: span 1; } .service-private-hint, .support-action { grid-column: 1 / -1; } }
@media (max-width: 480px) { .service-page { padding-top: 20px; } .service-summary { grid-template-columns: 1fr; justify-items: stretch; } .usage-ring { justify-self: center; } .service-summary > .btn { width: 100%; } .section-heading { align-items: start; flex-direction: column; gap: 6px; } .client-card { align-items: flex-start; flex-direction: column; } }
</style>
