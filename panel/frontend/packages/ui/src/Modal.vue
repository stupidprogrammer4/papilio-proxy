<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, useId, watch } from "vue";
const props=withDefaults(defineProps<{modelValue:boolean;title:string;description?:string;busy?:boolean;wide?:boolean}>(),{busy:false,wide:false});
const emit=defineEmits<{"update:modelValue":[value:boolean]}>();
const dialog=ref<HTMLDialogElement|null>(null);const heading=useId(),descriptionId=useId();
watch(()=>props.modelValue,open=>{if(open&&!dialog.value?.open)dialog.value?.showModal();else if(!open&&dialog.value?.open)dialog.value.close();},{flush:"post"});
function close():void{if(!props.busy)emit("update:modelValue",false);}
function cancel(event:Event):void{event.preventDefault();close();}
onMounted(()=>{if(props.modelValue)dialog.value?.showModal();});
onBeforeUnmount(()=>dialog.value?.close());
</script>
<template>
  <dialog ref="dialog" class="modal" :class="{'modal-wide':wide}" :aria-labelledby="heading" :aria-describedby="description?descriptionId:undefined" :aria-busy="busy" @cancel="cancel" @close="emit('update:modelValue',false)">
    <header class="modal-heading"><div><p class="eyebrow">WORKSPACE ACTION</p><h2 :id="heading">{{title}}</h2><p v-if="description" :id="descriptionId" class="subtitle">{{description}}</p></div><button type="button" class="icon-button" aria-label="Close dialog" :disabled="busy" @click="close">×</button></header>
    <div class="modal-body"><slot /></div>
  </dialog>
</template>
