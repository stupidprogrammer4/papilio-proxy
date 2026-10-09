<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { item, privateFile, request, query, type Page, type PublicSubscription, type PublicProfile, type ConfigurationDownload } from "@papilio/api";
import { faDate, faNumber } from "@papilio/ui";
const route = useRoute();
const detail = ref<PublicSubscription | null>(null); const profiles = ref<PublicProfile[]>([]); const page = ref(1); const pages = ref(1);
const loading = ref(false); const busy = ref(false); const error = ref(""); const notice = ref(""); let version = 0;
const labels: Record<string, string> = { customer_hold: "Service access suspended", revoking: "Revoking", exhausted: "Quota exhausted", suspended: "Suspended", active: "Active", pending_provision: "Pending provisioning", expired: "Expired", failed: "Provisioning failed", cancelled: "Cancelled" };
const protocols: Record<string, string> = { vless_reality: "VLESS REALITY", vless_tls: "VLESS", vmess_tls: "VMess", trojan_tls: "Trojan", shadowsocks: "Shadowsocks", hysteria2: "Hysteria2", wireguard: "WireGuard", openvpn: "OpenVPN" };
const qrUrl = ref(""); const qrTitle = ref(""); const qrBusy = ref(false); let qrVersion = 0;
function clearQr(): void { qrVersion++; if (qrUrl.value) URL.revokeObjectURL(qrUrl.value); qrUrl.value = ""; qrTitle.value = ""; qrBusy.value = false; }
async function showQr(profile?: PublicProfile): Promise<void> {
  clearQr(); const current = token(); const render = qrVersion; qrBusy.value = true; error.value = ""; notice.value = "";
  const suffix = profile ? `/profiles/${profile.profile_id}/qr?${query({ host_id: profile.host_id ?? undefined })}` : "/qr";
  try { const image = await privateFile(`/s/${encodeURIComponent(current)}${suffix}`); if (render !== qrVersion || current !== token()) return; qrUrl.value = URL.createObjectURL(image); qrTitle.value = profile ? profile.label : "Subscription URL"; }
  catch (cause) { if (render === qrVersion && current === token()) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (render === qrVersion) qrBusy.value = false; }
}
onBeforeUnmount(() => { version++; clearQr(); });
function token(): string { return String(route.params.token ?? ""); }
async function load(): Promise<void> {
  clearQr(); const current = token(); const read = ++version; loading.value = true; error.value = "";
  try { const [summary, rows] = await Promise.all([item<PublicSubscription>(`/s/${encodeURIComponent(current)}/status`), request<Page<PublicProfile>>(`/s/${encodeURIComponent(current)}/profiles?${query({ page: page.value })}`)]); if (read !== version || current !== token()) return; detail.value = summary; profiles.value = rows.data; pages.value = rows.meta.pager?.total_pages ?? 1; document.title = `${summary.brand_title} | My service`; }
  catch (cause) { if (read === version) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (read === version) loading.value = false; }
}
async function download(profile: PublicProfile): Promise<void> {
  const current = token(); busy.value = true; error.value = "";
  try { const file = await item<ConfigurationDownload>(`/s/${encodeURIComponent(current)}/profiles/${profile.profile_id}/download?${query({ host_id: profile.host_id ?? undefined })}`); if (current !== token()) return; const url = URL.createObjectURL(new Blob([file.content], { type: file.media_type })); const link = document.createElement("a"); link.href = url; link.download = file.filename; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url); notice.value = "Connection file downloaded."; }
  catch (cause) { if (current === token()) error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  finally { if (current === token()) busy.value = false; }
}
async function copyLink(): Promise<void> {
  const current = token(); error.value = ""; notice.value = "";
  try { if (!detail.value?.feed_url) return; await navigator.clipboard.writeText(detail.value.feed_url); notice.value = "Subscription URL copied."; }
  catch { error.value = "Could not copy the URL. Check your browser clipboard permission."; }
}
watch(() => route.params.token, () => { version++; detail.value = null; profiles.value = []; page.value = 1; busy.value = false; notice.value = ""; void load(); }, { immediate: true });
</script>
<template>
  <main class="service-page">
    <div class="page-head"><div><p class="eyebrow">YOUR PRIVATE SERVICE</p><h1>{{ detail?.brand_title ?? 'Service details' }}</h1><p class="subtitle">This page and its URL are private. Keep them to yourself.</p></div><button class="btn secondary" :disabled="loading || busy" @click="load">Refresh</button></div>
    <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message" role="status">{{ notice }}</p>
    <p v-if="loading">Loading service…</p>
    <section v-if="detail" class="card card-pad form-grid">
      <div class="detail-line"><span>Subscription ID</span><strong>{{ faNumber(detail.id) }}</strong></div>
      <div class="detail-line"><span>Status</span><strong>{{ labels[detail.status] ?? 'Needs review' }}</strong></div>
      <div class="detail-line"><span>Expiry</span><strong>{{ faDate(detail.expires_at) }}</strong></div>
      <div class="detail-line"><span>Quota Period (GiB)</span><strong>{{ (detail.quota_bytes === null ? "Unlimited" : faNumber(detail.quota_bytes / 1_073_741_824)) }}</strong></div>
      <div class="detail-line"><span>Reported usage (GiB)</span><strong>{{ faNumber(detail.used_bytes / 1_073_741_824) }}</strong></div>
      <div class="detail-line"><span>Renewal Automatic</span><strong>{{ detail.auto_renew ? 'Enabled when wallet funds are sufficient' : 'Disabled' }}</strong></div>
      <button v-if="detail.feed_url !== null" class="btn" @click="copyLink">Copy subscription URL</button><button v-if="detail.feed_url && detail.qr_enabled" class="btn secondary" :disabled="qrBusy || loading" @click="showQr()">Subscription QR code</button>
      <p class="hint-box">Use this service in the bot to purchase, top up your wallet or change renewal settings.</p>
      <a v-if="detail.support_handle" class="btn secondary" :href="'https://t.me/' + detail.support_handle.replace(/^@/, '')" target="_blank" rel="noreferrer noopener">Support</a>
    </section>
    <section v-if="qrBusy || qrUrl" class="card card-pad service-qr" aria-label="Private QR code">
      <p v-if="qrBusy" role="status">Loading QR code…</p>
      <template v-if="qrUrl"><h2>{{ qrTitle }}</h2><img :src="qrUrl" alt="Private connection QR code" /><p class="hint-box">Scan this image in your VPN client. Do not share it with others.</p><a class="btn" :href="qrUrl" download="connection-qr.png">Download image</a></template>
      <button class="btn secondary" @click="clearQr">Close image</button>
    </section>
    <section v-if="detail" class="card card-pad service-profiles"><h2>Available connections</h2>
      <p v-if="!loading && !profiles.length && !error">No connection is available for download yet.</p>
      <div class="table-wrap"><table v-if="profiles.length" class="data-table"><thead><tr><th>Route</th><th>Protocol</th><th>Download</th></tr></thead><tbody><tr v-for="profile in profiles" :key="profile.profile_id + ':' + profile.host_id"><td>{{ profile.label }}</td><td>{{ protocols[profile.protocol] ?? 'Connect' }}</td><td><button class="btn small" :disabled="busy" @click="download(profile)">Download file</button><button v-if="detail.qr_enabled" class="btn small secondary" :disabled="qrBusy || loading" @click="showQr(profile)">Connection QR code</button></td></tr></tbody></table></div>
      <div class="pager"><button :disabled="page <= 1 || loading" @click="page--; load()">‹</button><span>{{ faNumber(page) }}</span><button :disabled="page >= pages || loading" @click="page++; load()">›</button></div>
    </section>
  </main>
</template>
<style scoped>
.service-page { max-width: 920px; margin: 0 auto; padding: 24px 16px; min-inline-size: 0; }
.service-qr { margin-top: 20px; display: grid; justify-items: center; gap: 12px; }
.service-qr img { max-width: 100%; height: auto; max-height: 70vh; object-fit: contain; background: white; }
.service-profiles { margin-top: 20px; }
</style>
