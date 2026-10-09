<script setup lang="ts">
import type { AgreementPrice } from "@papilio/api";
import NumField from "@papilio/ui/NumField.vue";
const price=defineModel<AgreementPrice>({required:true});
defineProps<{disabled?:boolean}>();
function number(key:"fixed_price_rial"|"discount_bps"|"quantum_rial",value:string):void{price.value={...price.value,[key]:value===""&&key!=="quantum_rial"?null:Number(value)};}
function mode(event:Event):void{price.value={...price.value,mode:(event.target as HTMLSelectElement).value as AgreementPrice["mode"],fixed_price_rial:null,discount_bps:null};}
</script>
<template><fieldset class="form-grid" :disabled="disabled"><legend>Agreement price</legend><label class="field"><span>Pricing method</span><select aria-label="Pricing method" :value="price.mode" @change="mode"><option value="catalog">Current catalog price</option><option value="fixed">Amount Fixed</option><option value="discount">Discount on the current catalog price</option></select></label><NumField v-if="price.mode==='fixed'" :model-value="price.fixed_price_rial===null?'':String(price.fixed_price_rial)" label="Fixed amount (rial)" @update:model-value="number('fixed_price_rial',$event)"/><NumField v-if="price.mode==='discount'" :model-value="price.discount_bps===null?'':String(price.discount_bps)" label="Discount (basis points; 100 = 1%)" @update:model-value="number('discount_bps',$event)"/><label class="field"><span>Round to the selected increment</span><select aria-label="Round to the selected increment" v-model="price.rounding"><option value="floor">Round down</option><option value="ceil">Round up</option><option value="nearest">Nearest increment, half up</option></select></label><NumField :model-value="String(price.quantum_rial)" label="Rounding increment (rial)" @update:model-value="number('quantum_rial',$event)"/></fieldset></template>
<style scoped>fieldset{border:1px solid var(--line);border-radius:12px;padding:16px}</style>
