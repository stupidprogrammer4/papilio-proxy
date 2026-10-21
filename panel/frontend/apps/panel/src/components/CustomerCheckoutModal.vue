<script setup lang="ts">
import { v4 as newRequestKey } from "uuid";
import PlanIpAllowance from "./PlanIpAllowance.vue";
import { computed, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import Modal from "@papilio/ui/Modal.vue";
import NumField from "@papilio/ui/NumField.vue";
import { ApiError, item, request, query, type AccountDelivery, type AccountPreferences, type CheckoutCreate, type CheckoutRetirement, type CheckoutCancel, type CheckoutReconfirm, type CheckoutIntent, type CheckoutOffer, type Page, type PaymentDestination, type Plan, type Subscription } from "@papilio/api";
import { asciiDigits, faDate, toman } from "@papilio/ui";
import TopupEvidence from "./TopupEvidence.vue";
const { t } = useI18n();
const props=defineProps<{open:boolean;plan:Plan|null;checkoutId:number|null;preferences:AccountPreferences|null}>();
const emit=defineEmits<{close:[];saved:[value:CheckoutIntent]}>();
type CheckoutProgressRead=
 |{kind:"subscription";value:Subscription|null}
 |{kind:"delivery";value:AccountDelivery|null};
const offer=ref<CheckoutOffer|null>(null),intent=ref<CheckoutIntent|null>(null);
const progressSubscription=ref<Subscription|null>(null),progressDelivery=ref<AccountDelivery|null>(null);
const busy=ref(false),error=ref(""),readState=ref<"loading"|"ready"|"error">("loading");
const funding=ref<"wallet_only"|"approved_topup">("wallet_only"),amount=ref(""),autoRenew=ref(false),changeAction=ref<"require_confirmation"|"cancel">("require_confirmation");
const destinations=ref<PaymentDestination[]>([]),destination=ref<PaymentDestination|null>(null),destinationQuery=ref(""),page=ref(1),pages=ref(1),destinationState=ref<"idle"|"loading"|"ready"|"error">("idle");
const createUncertain=ref(false),actionUncertain=ref(false),retirementPending=ref(false);
const retirementMessage=ref("");
const createAttempt=ref<CheckoutCreate|null>(null),actionAttempt=ref<{action:"reconfirm";body:CheckoutReconfirm}|{action:"cancel";body:CheckoutCancel}|null>(null);
let version=0,destinationVersion=0;
const unresolved=computed(()=>Boolean(createAttempt.value&&!intent.value));
const terminal=computed(()=>intent.value&&["purchased","cancelled","expired"].includes(intent.value.state));
const labels:Record<CheckoutIntent["state"],string>={awaiting_funding:t("checkoutModal.states.awaitingFunding"),ready:t("checkoutModal.states.ready"),action_required:t("checkoutModal.states.actionRequired"),purchased:t("checkoutModal.states.purchased"),cancelled:t("checkoutModal.states.cancelled"),expired:t("checkoutModal.states.expired")};
const reasonMessage=computed(()=>{const row=intent.value;if(!row?.reason_code||row.state==="cancelled"||row.state==="expired")return null;if(row.reason_code==="checkout_offer_busy")return row.state==="action_required"?t("checkoutModal.reasons.offerBusyNeedsReview"):t("checkoutModal.reasons.offerBusyQueued");if(row.reason_code==="checkout_offer_changed")return t("checkoutModal.reasons.offerChanged");if(row.reason_code==="wallet_insufficient")return t("checkoutModal.reasons.walletInsufficient");if(row.reason_code==="checkout_topup_rejected")return t("checkoutModal.reasons.topupRejected");return t("checkoutModal.reasons.attention");});
const fundingProgress=computed(()=>{const row=intent.value;if(!row)return t("checkoutModal.progress.loading");if(row.state==="awaiting_funding")return t("checkoutModal.states.awaitingFunding");if(row.state==="ready"||row.state==="purchased")return t("checkoutModal.progress.funded");if(row.state==="action_required")return t("checkoutModal.states.actionRequired");return t("checkoutModal.progress.notFunded");});
const deliveryProgress=computed(()=>{const status=progressDelivery.value?.status??progressSubscription.value?.status;if(!status)return t("checkoutModal.progress.serviceUnavailable");const labels:Record<string,string>={customer_hold:"customerHold",active:"active",pending_provision:"pendingProvision",revoking:"revoking",expired:"expired",exhausted:"exhausted",suspended:"suspended",failed:"failed",cancelled:"cancelled"};const label=labels[status];return label?t(`customerPortal.statuses.${label}`):t("checkoutModal.progress.serviceUnavailable");});
function fail(cause:unknown):void{error.value=cause instanceof Error?cause.message:t("checkoutModal.requestRetained");}
function retain(row:CheckoutIntent):void{intent.value=row;emit("saved",row);}
async function loadOffer(planId:number):Promise<CheckoutOffer>{return item<CheckoutOffer>(`/v1/customer/checkouts/offers/${planId}`);}
async function refresh():Promise<void>{
 const stamp=++version;busy.value=true;error.value="";readState.value="loading";
 try{
  const id=intent.value?.id??props.checkoutId;
  if(id!==null){
   const row=await item<CheckoutIntent>(`/v1/customer/checkouts/${id}`);
   if(stamp!==version)return;
   intent.value=row;progressSubscription.value=null;progressDelivery.value=null;
   if(row.subscription_id!==null){
    const subscriptionPath=`/v1/customer/subscriptions/${row.subscription_id}`;
    const reads:Array<Promise<CheckoutProgressRead>>=[
     item<Subscription>(subscriptionPath).then(
      value=>({kind:"subscription",value}),
      ()=>({kind:"subscription",value:null}),
     ),
     item<AccountDelivery>(`${subscriptionPath}/delivery`).then(
      value=>({kind:"delivery",value}),
      ()=>({kind:"delivery",value:null}),
     ),
    ];
    const outcomes=await Promise.all(reads);
    if(stamp!==version)return;
    outcomes.forEach(outcome=>{
     if(outcome.kind==="subscription"){
      progressSubscription.value=outcome.value;
      return;
     }
     progressDelivery.value=outcome.value;
    });
   }
   if(row.state==="action_required"){
    const current=await loadOffer(row.plan_id);
    if(stamp!==version)return;
    offer.value=current;
   }
  }else if(props.plan){
   const current=await loadOffer(props.plan.id);
   if(stamp!==version)return;
   offer.value=current;
  }
  if(stamp===version)readState.value="ready";
 }catch(cause){
  if(stamp===version){readState.value="error";fail(cause);}
 }finally{
  if(stamp===version)busy.value=false;
 }
}
async function loadDestinations():Promise<void>{const stamp=++destinationVersion;destinationState.value="loading";try{const result=await request<Page<PaymentDestination>>(`/v1/customer/payment-destinations?${query({page:page.value,q:destinationQuery.value})}`);if(stamp!==destinationVersion)return;destinations.value=result.data;pages.value=result.meta.pager?.total_pages??1;destinationState.value="ready";}catch(cause){if(stamp===destinationVersion){destinationState.value="error";fail(cause);}}}
async function create():Promise<void>{if(!offer.value||retirementPending.value)return;const stamp=version;error.value="";retirementMessage.value="";try{if(!createAttempt.value){if(!Number.isSafeInteger(offer.value.default_expiry_seconds)||Number(offer.value.default_expiry_seconds)<=0)throw new Error(t("checkoutModal.errors.lifetimeUnavailable"));let rial:number|null=null;if(funding.value==="approved_topup"){if(!props.preferences)throw new Error(t("checkoutModal.errors.paymentSettingsUnavailable"));const normalized=asciiDigits(amount.value);if(!/^\d+(?:\.\d)?$/.test(normalized))throw new Error(t("checkoutModal.errors.enterAmount"));rial=Math.round(Number(normalized)*10);if(!Number.isSafeInteger(rial)||rial<=0)throw new Error(t("checkoutModal.errors.invalidAmount"));if(props.preferences?.checkout.destination_mode==="required"&&!destination.value)throw new Error(t("checkoutModal.errors.selectDestination"));}createAttempt.value={request_key:newRequestKey(),plan_id:offer.value.plan_id,funding_mode:funding.value,expected_offer_sha256:offer.value.offer_sha256,expected_price_rial:offer.value.price_rial,auto_renew:autoRenew.value,expiry_seconds:Number(offer.value.default_expiry_seconds),changed_offer_action:changeAction.value,topup_amount_rial:rial,destination_id:funding.value==="approved_topup"&&props.preferences?.checkout.destination_mode!=="legacy"?destination.value?.destination_id??null:null};}busy.value=true;const row=await item<CheckoutIntent>("/v1/customer/checkouts","POST",createAttempt.value);if(stamp!==version)return;retain(row);createAttempt.value=null;createUncertain.value=false;}catch(cause){if(stamp!==version)return;if(createAttempt.value){if(cause instanceof ApiError&&cause.status>=400&&cause.status<500&&!createUncertain.value)createAttempt.value=null;else createUncertain.value=true;}fail(cause);}finally{if(stamp===version)busy.value=false;}}
async function retire():Promise<void>{
 if(!createAttempt.value||intent.value)return;
 const stamp=version,key=createAttempt.value.request_key;
 retirementPending.value=true;busy.value=true;error.value="";
 try{
  const result=await item<CheckoutRetirement>("/v1/customer/checkouts/retire","POST",{request_key:key});
  if(stamp!==version)return;
  const invalidPurchase=result.status==="purchased"&&(!result.intent||result.intent.state!=="purchased"||result.intent.subscription_id==null);
  const invalidRetirement=result.status==="retired"&&result.intent!==null&&(result.intent.subscription_id!=null||!["cancelled","expired"].includes(result.intent.state));
  if(result.request_key!==key||!["retired","purchased"].includes(result.status)||invalidPurchase||invalidRetirement)throw new Error(t("checkoutModal.errors.cancellationUnconfirmed"));
  if(result.intent)retain(result.intent);
  createAttempt.value=null;createUncertain.value=false;retirementPending.value=false;
  retirementMessage.value=result.status==="purchased"?t("checkoutModal.retirementAlreadyPurchased"):t("checkoutModal.retirementCancelled");
 }catch(cause){if(stamp===version)fail(cause);}
 finally{if(stamp===version)busy.value=false;}
}
async function perform(action:"cancel"|"reconfirm"):Promise<void>{if(!intent.value)return;const stamp=version;error.value="";if(actionAttempt.value&&actionAttempt.value.action!==action){error.value=t("checkoutModal.errors.retryRetained");return;}if(!actionAttempt.value){if(action==="reconfirm"&&!offer.value)return;const base={request_key:newRequestKey(),expected_revision:intent.value.revision};actionAttempt.value=action==="reconfirm"?{action,body:{...base,expected_price_rial:offer.value!.price_rial,expected_offer_sha256:offer.value!.offer_sha256}}:{action,body:base};}busy.value=true;try{const row=await item<CheckoutIntent>(`/v1/customer/checkouts/${intent.value.id}/${action}`,"POST",actionAttempt.value.body);if(stamp!==version)return;retain(row);actionAttempt.value=null;actionUncertain.value=false;}catch(cause){if(stamp!==version)return;if(cause instanceof ApiError&&cause.status>=400&&cause.status<500&&!actionUncertain.value)actionAttempt.value=null;else actionUncertain.value=true;fail(cause);}finally{if(stamp===version)busy.value=false;}}
watch(()=>[props.open,props.plan?.id,props.checkoutId] as const,([open,planId,id],old)=>{if(!open)return;if(intent.value?.id===id&&id!==null)return;if(old&&old[0]&&planId===old[1]&&id===old[2])return;version++;destinationVersion++;offer.value=null;intent.value=null;createAttempt.value=null;actionAttempt.value=null;createUncertain.value=actionUncertain.value=retirementPending.value=false;retirementMessage.value="";funding.value="wallet_only";amount.value="";autoRenew.value=false;changeAction.value="require_confirmation";destination.value=null;destinations.value=[];destinationState.value="idle";page.value=pages.value=1;void refresh();},{immediate:true});
watch(funding,mode=>{if(mode==="approved_topup"&&props.preferences?.checkout.destination_mode!=="legacy"&&destinationState.value==="idle")void loadDestinations();});
onUnmounted(()=>{version++;destinationVersion++;});
</script>
<template><Modal :model-value="open" :title="t('checkoutModal.title')" :busy="busy||unresolved||Boolean(actionAttempt)" wide @update:model-value="value=>{if(!value)emit('close');}"><p v-if="error" class="message error" role="alert">{{error}}</p><p v-if="retirementMessage" class="hint-box" role="status">{{retirementMessage}}</p><button type="button" class="btn secondary" :disabled="busy||unresolved" @click="refresh">{{t("checkoutModal.refresh")}}</button><p v-if="readState==='loading'">{{t("checkoutModal.loading")}}</p><template v-if="intent"><h3>{{t("checkoutModal.checkout")}} #{{intent.id}}</h3><p role="status">{{labels[intent.state]}}</p><p>{{t("checkoutModal.plan")}} #{{intent.plan_id}} · {{t("checkoutModal.price")}} {{toman(intent.price_rial)}} · {{t("checkoutModal.expires")}} {{faDate(intent.expires_at)}}</p><ol class="purchase-progress" :aria-label="t('checkoutModal.progress.label')"><li data-stage="request"><strong>{{t("checkoutModal.progress.request")}}</strong><span>{{labels[intent.state]}}</span></li><li data-stage="funding"><strong>{{t("checkoutModal.progress.funding")}}</strong><span>{{fundingProgress}}</span></li><li data-stage="delivery"><strong>{{t("checkoutModal.progress.delivery")}}</strong><span>{{deliveryProgress}}</span></li></ol><p v-if="reasonMessage" class="hint-box">{{reasonMessage}}</p><p v-if="intent.delivery_mode==='manual_profiles'">{{t("checkoutModal.manualAssignment")}}</p><p v-if="intent.state==='cancelled'||intent.state==='expired'">{{t("checkoutModal.walletRetained")}}</p><p v-if="intent.state==='awaiting_funding'">{{t("checkoutModal.paymentApproval")}}</p><p v-if="intent.topup_id!==null">{{t("checkoutModal.separateCharges")}}</p><TopupEvidence v-if="intent.topup_id!==null" :topup-id="intent.topup_id" audience="customer" :pending="intent.state==='awaiting_funding'" :can-upload="preferences?.receipts.enabled??false" /><RouterLink v-if="intent.subscription_id!==null" class="btn" :to="{path:'/account',query:{subscription_id:intent.subscription_id}}" @click="emit('close')">{{t("checkoutModal.viewService")}}</RouterLink><section v-if="intent.state==='action_required'&&offer" class="hint-box"><h3>{{t("checkoutModal.reviewOffer")}}</h3><p>{{offer.plan_title}} · {{toman(offer.price_rial)}} · {{offer.membership_count}} {{t("checkoutModal.connectionOptions")}}</p><p>{{offer.quota_bytes===null?t('checkoutModal.unlimitedData'):`${offer.quota_bytes/1024**3} GiB`}} · {{offer.duration_days===null?t('checkoutModal.noExpiry'):`${offer.duration_days} days`}}</p><p>{{offer.delivery_mode==='manual_profiles'?t('checkoutModal.manualAssignment'):t('checkoutModal.configuredBundle')}}</p><button class="btn" :disabled="busy||Boolean(actionAttempt&&actionAttempt.action!=='reconfirm')" @click="perform('reconfirm')">{{actionAttempt?.action==='reconfirm'?t('checkoutModal.retryConfirmation'):t('checkoutModal.confirmUpdatedOffer')}}</button></section><section v-if="actionAttempt && (intent.state!=='action_required'||actionAttempt.action==='cancel')" class="hint-box" role="status"><p>{{t("checkoutModal.unresolvedAction")}}</p><button class="btn" :disabled="busy" @click="perform(actionAttempt.action)">{{actionAttempt.action==='reconfirm'?t('checkoutModal.retryConfirmation'):t('checkoutModal.retryRetainedCancellation')}}</button></section><button v-if="!terminal" class="btn secondary" :disabled="busy||Boolean(actionAttempt&&actionAttempt.action!=='cancel')" @click="perform('cancel')">{{actionAttempt?.action==='cancel'?t('checkoutModal.retryCancellation'):t('checkoutModal.cancelCheckout')}}</button></template><form v-else-if="offer" class="form-grid" @submit.prevent="create"><h3>{{offer.plan_title}}</h3><PlanIpAllowance :policy="offer.effective_ip_policy"/><p><strong>{{toman(offer.price_rial)}}</strong> · {{offer.quota_bytes===null?t('checkoutModal.unlimitedData'):`${offer.quota_bytes/1024**3} GiB`}} · {{offer.duration_days===null?t('checkoutModal.noExpiry'):`${offer.duration_days} days`}}</p><p>{{offer.membership_count}} {{t("checkoutModal.connectionOptions")}} · {{offer.delivery_mode==='manual_profiles'?t('checkoutModal.manualAssignmentShort'):t('checkoutModal.configuredBundle')}}</p><p v-if="unresolved" role="status">{{t("checkoutModal.unresolvedCreate")}}</p><section v-if="unresolved" class="hint-box"><p v-if="retirementPending">{{t("checkoutModal.cancellationUnresolved")}}</p><button type="button" class="btn secondary" :disabled="busy" @click="retire">{{retirementPending?t('checkoutModal.retryCancellation'):t('checkoutModal.cancelUnresolved')}}</button></section><fieldset class="form-grid" :disabled="busy||unresolved"><label class="field"><span>{{t("checkoutModal.funding")}}</span><select v-model="funding"><option value="wallet_only">{{t("checkoutModal.walletFunding")}}</option><option value="approved_topup">{{t("checkoutModal.topupFunding")}}</option></select></label><template v-if="funding==='approved_topup'"><p>{{preferences?.payment_instructions}}</p><NumField v-model="amount" :decimal="true" :label="t('checkoutModal.requestedTopup')" /><p>{{t("checkoutModal.exactPaymentInstructions")}}</p><p v-if="preferences">{{t("checkoutModal.allowedPayment")}}: {{toman(preferences.checkout.minimum_topup_rial)}} to {{toman(preferences.checkout.maximum_topup_rial)}}</p><section v-if="preferences?.checkout.destination_mode!=='legacy'"><h4>{{t("checkoutModal.destination")}}</h4><p v-if="destination">{{t("checkoutModal.selected")}}: {{destination.title}} · {{destination.recipient}}</p><div class="toolbar"><label class="field"><span>{{t("checkoutModal.findDestination")}}</span><input v-model="destinationQuery" @keydown.enter.prevent="page=1;loadDestinations()" /></label><button type="button" class="btn secondary" @click="page=1;loadDestinations()">{{t("checkoutModal.searchDestinations")}}</button></div><p v-if="destinationState==='loading'">{{t("checkoutModal.loadingDestinations")}}</p><p v-if="destinationState==='error'">{{t("checkoutModal.destinationsError")}}</p><p v-if="destinationState==='ready'&&!destinations.length">{{t("checkoutModal.noDestinations")}}</p><button v-for="row in destinations" :key="row.destination_id" type="button" class="btn secondary" :aria-pressed="destination?.destination_id===row.destination_id" @click="destination=row">{{row.title}} · {{row.bank_name}}</button><button v-if="preferences?.checkout.destination_mode==='optional'" type="button" class="btn secondary" @click="destination=null">{{t("checkoutModal.noDestination")}}</button><div class="pager"><button type="button" :disabled="page<=1" @click="page--;loadDestinations()">{{t("checkoutModal.previousDestinations")}}</button><span>{{page}}</span><button type="button" :disabled="page>=pages" @click="page++;loadDestinations()">{{t("checkoutModal.nextDestinations")}}</button></div></section></template><label class="check-row"><input v-model="autoRenew" type="checkbox" />{{t("checkoutModal.autoRenew")}}</label><label class="field"><span>{{t("checkoutModal.changedOffer")}}</span><select v-model="changeAction"><option value="require_confirmation">{{t("checkoutModal.reviewUpdatedOffer")}}</option><option value="cancel">{{t("checkoutModal.cancelAndKeepWallet")}}</option></select></label></fieldset><button class="btn" :disabled="busy||retirementPending||!offer.default_expiry_seconds">{{unresolved?t('checkoutModal.retrySame'):t('checkoutModal.confirmCheckout')}}</button></form></Modal></template>
<style scoped>fieldset{border:0;margin:0;padding:0;min-inline-size:0}.purchase-progress{display:grid;gap:.65rem;padding-inline-start:1.5rem}.purchase-progress li{padding-inline-start:.25rem}.purchase-progress strong,.purchase-progress span{display:block}.purchase-progress span{color:var(--muted,#667085)}</style>
