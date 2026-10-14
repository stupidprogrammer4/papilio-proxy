<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useAuth } from "@papilio/auth";
import Modal from "@papilio/ui/Modal.vue";
import { asciiDigits, faNumber } from "@papilio/ui";
import { item, query, request, type Page, type PaymentDestination, type SmsOriginCapabilities } from "@papilio/api";
import ReceivingAccountBindingModal from "./payments/ReceivingAccountBindingModal.vue";

const props = defineProps<{ capabilities?: SmsOriginCapabilities | null }>();
const { t } = useI18n();
const auth = useAuth();
const rows = ref<PaymentDestination[]>([]);
const selected = ref<number | null>(null);
const page = ref(1);
const pages = ref(1);
const search = ref("");
const state = ref<"loading" | "ready" | "error">("loading");
const busy = ref(false);
const error = ref("");
const notice = ref("");
const editorOpen = ref(false);
const bindingOpen = ref(false);
const bindingDestination = ref<PaymentDestination | null>(null);
const revision = ref<number | undefined>();
let version = 0;

const empty = () => ({
  title: "",
  kind: "card" as PaymentDestination["kind"],
  account: "",
  recipient: "",
  bank_name: "",
  instructions: "",
  is_active: false,
});
const form = ref(empty());

async function load(): Promise<void> {
  const stamp = ++version;
  state.value = "loading";
  error.value = "";
  try {
    const result = await request<Page<PaymentDestination>>(
      `/v1/admin/payments/destinations?${query({ page: page.value, q: search.value })}`,
    );
    if (stamp !== version) return;
    rows.value = result.data;
    pages.value = result.meta.pager?.total_pages ?? 1;
    state.value = "ready";
  } catch (cause) {
    if (stamp === version) {
      state.value = "error";
      error.value = cause instanceof Error ? cause.message : t("paymentConfig.destination.loadFailed");
    }
  }
}

function choose(row: PaymentDestination, force = false): void {
  if (busy.value && !force) return;
  editorOpen.value = true;
  selected.value = row.destination_id;
  revision.value = row.revision;
  form.value = {
    title: row.title,
    kind: row.kind,
    account: row.account,
    recipient: row.recipient,
    bank_name: row.bank_name,
    instructions: row.instructions ?? "",
    is_active: row.is_active,
  };
  notice.value = "";
}

async function save(): Promise<void> {
  if (busy.value || !auth.can("payments", selected.value === null ? "create" : "update")) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const result = await item<PaymentDestination>(
      `/v1/admin/payments/destinations${selected.value === null ? "" : `/${selected.value}`}`,
      selected.value === null ? "POST" : "PUT",
      {
        ...form.value,
        ...(selected.value !== null && revision.value !== undefined ? { expected_revision: revision.value } : {}),
        account: asciiDigits(form.value.account.trim()).toUpperCase(),
        instructions: form.value.instructions.trim() || null,
      },
    );
    choose(result, true);
    editorOpen.value = false;
    notice.value = t("paymentConfig.destination.saved");
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("paymentConfig.destination.saveFailed");
  } finally {
    busy.value = false;
  }
}

function startCreate(): void {
  if (busy.value) return;
  if (selected.value !== null) {
    selected.value = null;
    form.value = empty();
  }
  notice.value = "";
  editorOpen.value = true;
}

onMounted(load);
</script>

<template>
  <section class="card card-pad" style="margin-top: 18px">
    <h2>{{ t("paymentConfig.destination.title") }}</h2>
    <p>{{ t("paymentConfig.destination.description") }}</p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <div class="toolbar">
      <label class="field">
        <span>{{ t("paymentConfig.destination.search") }}</span>
        <input v-model="search" @keydown.enter="page = 1; load()" />
      </label>
      <button class="btn secondary" @click="page = 1; load()">{{ t("paymentConfig.search") }}</button>
      <button v-if="auth.can('payments', 'create')" class="btn" :disabled="busy" @click="startCreate">
        {{ t("paymentConfig.destination.create") }}
      </button>
    </div>
    <p v-if="state === 'loading'">{{ t("paymentConfig.loading") }}</p>
    <p v-else-if="state === 'ready' && !rows.length">{{ t("paymentConfig.destination.empty") }}</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr>
          <th>{{ t("paymentConfig.destination.label") }}</th>
          <th>{{ t("paymentConfig.destination.bank") }}</th>
          <th>{{ t("paymentConfig.status") }}</th>
          <th v-if="capabilities?.read_available">{{ t("paymentConfig.receivingAccount") }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.destination_id" tabindex="0"
            :class="{ 'selected-row': selected === row.destination_id }"
            @click="choose(row)" @keydown.enter="choose(row)">
            <td>{{ row.title }}</td><td>{{ row.bank_name }}</td>
            <td>{{ row.is_active ? t("paymentConfig.active") : t("paymentConfig.inactive") }}</td>
            <td v-if="capabilities?.read_available">
              <span>{{ row.receiving_alias_id == null ? t("paymentConfig.unbound") : t("paymentConfig.alias", { id: row.receiving_alias_id }) }}</span>
              <button v-if="capabilities.enabled && auth.can('payments', 'update')" class="btn small secondary"
                :disabled="busy" @click.stop="bindingDestination = row; bindingOpen = true">
                {{ t("paymentConfig.destination.bind") }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="pager">
      <button :disabled="page <= 1" :aria-label="t('paymentConfig.previousPage')" @click="page--; load()">‹</button>
      <span>{{ faNumber(page) }}</span>
      <button :disabled="page >= pages" :aria-label="t('paymentConfig.nextPage')" @click="page++; load()">›</button>
    </div>
    <Modal v-model="editorOpen" :title="selected === null ? t('paymentConfig.destination.createTitle') : t('paymentConfig.destination.editTitle')" :busy="busy" wide>
      <p v-if="error" class="message error" role="alert">{{ error }}</p>
      <form class="form-grid" @submit.prevent="save">
        <fieldset class="form-grid" :disabled="busy || !auth.can('payments', selected === null ? 'create' : 'update')">
          <label class="field"><span>{{ t("paymentConfig.destination.name") }}</span><input v-model="form.title" required maxlength="100" /></label>
          <label class="field"><span>{{ t("paymentConfig.destination.method") }}</span>
            <select v-model="form.kind">
              <option value="card">{{ t("paymentConfig.destination.card") }}</option>
              <option value="iban">{{ t("paymentConfig.destination.iban") }}</option>
              <option value="bank_account">{{ t("paymentConfig.destination.accountType") }}</option>
            </select>
          </label>
          <label class="field"><span>{{ t("paymentConfig.destination.accountNumber") }}</span><input v-model="form.account" dir="ltr" required maxlength="100" /></label>
          <label class="field"><span>{{ t("paymentConfig.destination.recipient") }}</span><input v-model="form.recipient" required maxlength="100" /></label>
          <label class="field"><span>{{ t("paymentConfig.destination.bankName") }}</span><input v-model="form.bank_name" required maxlength="100" /></label>
          <label class="field"><span>{{ t("paymentConfig.destination.instructions") }}</span><textarea v-model="form.instructions" maxlength="2000" /></label>
          <label class="check-row"><input v-model="form.is_active" type="checkbox" />{{ t("paymentConfig.destination.available") }}</label>
          <button class="btn">{{ t("paymentConfig.destination.save") }}</button>
        </fieldset>
      </form>
    </Modal>
    <ReceivingAccountBindingModal v-model="bindingOpen" :destination="bindingDestination" :capabilities="capabilities ?? null" @saved="load" />
  </section>
</template>
