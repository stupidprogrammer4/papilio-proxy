<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from "vue";
const props=withDefaults(defineProps<{modelValue:boolean;title:string;description?:string;eyebrow?:string;closeLabel?:string;busy?:boolean;wide?:boolean}>(),{busy:false,wide:false});
const emit=defineEmits<{"update:modelValue":[value:boolean]}>();
const locale=ref(document.documentElement.lang);
let localeObserver:MutationObserver|undefined;
const eyebrow=computed(()=>props.eyebrow??(locale.value==="fa"?"عملیات فضای کار":"WORKSPACE ACTION"));
const closeLabel=computed(()=>props.closeLabel??(locale.value==="fa"?"بستن پنجره":"Close dialog"));
const dialog=ref<HTMLDialogElement|null>(null);const heading=useId(),descriptionId=useId();
watch(()=>props.modelValue,open=>{if(open&&!dialog.value?.open)dialog.value?.showModal();else if(!open&&dialog.value?.open)dialog.value.close();},{flush:"post"});
function close():void{if(!props.busy)emit("update:modelValue",false);}
function cancel(event:Event):void{event.preventDefault();close();}
onMounted(()=>{if(props.modelValue)dialog.value?.showModal();localeObserver=new MutationObserver(()=>{locale.value=document.documentElement.lang;});localeObserver.observe(document.documentElement,{attributes:true,attributeFilter:["lang"]});});
onBeforeUnmount(()=>{localeObserver?.disconnect();dialog.value?.close();});
</script>
<template>
  <dialog ref="dialog" class="modal" :class="{'modal-wide':wide}" :aria-labelledby="heading" :aria-describedby="description?descriptionId:undefined" :aria-busy="busy" @cancel="cancel" @close="emit('update:modelValue',false)">
    <header class="modal-heading"><div><p class="eyebrow">{{eyebrow}}</p><h2 :id="heading">{{title}}</h2><p v-if="description" :id="descriptionId" class="subtitle">{{description}}</p></div><button type="button" class="icon-button" :aria-label="closeLabel" :disabled="busy" @click="close">×</button></header>
    <div class="modal-body"><slot /></div>
  </dialog>
</template>
