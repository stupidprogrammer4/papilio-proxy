<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from "vue";
import { useRoute,useRouter } from "vue-router";
import { useAuth,useResellerAuth } from "@papilio/auth";
import Icon from "@papilio/ui/Icon.vue";
import { useI18n } from "vue-i18n";
import DisplayPreferences from "./components/DisplayPreferences.vue";
import { useBranding } from "./stores/branding";
const { t } = useI18n();
const navigationMessages: Record<string, string> = { "Telegram bots": "bots.title", "Managed services": "serviceSetup.title", "Customer wallets": "sales.title", "Service products": "productCatalog.title", "Manual payments": "invoices.title" };
const navLabel = (label: string): string => t(navigationMessages[label] ?? `navigation.${label}`);
const route=useRoute(),router=useRouter(),auth=useAuth(),reseller=useResellerAuth(),branding=useBranding();
const menuOpen=ref(false),signOutError=ref(""),signingOut=ref(false);
const navigationToggle=ref<HTMLButtonElement|null>(null),sidebar=ref<HTMLElement|null>(null);
const mobileNavigation=ref(false),navigationId=useId();
let savedOverflow:string|null=null;
function syncViewport():void{
 mobileNavigation.value=Boolean(navigationToggle.value&&getComputedStyle(navigationToggle.value).display!=="none");
 if(!mobileNavigation.value)menuOpen.value=false;
}
function drawerKey(event:KeyboardEvent):void{
 if(!menuOpen.value||!mobileNavigation.value)return;
 if(event.key==="Escape"){event.preventDefault();menuOpen.value=false;return;}
 if(event.key!=="Tab")return;
 const controls=sidebar.value?.querySelectorAll<HTMLElement>('a[href],button:not([disabled])');
 if(!controls?.length)return;
 const first=controls.item(0),last=controls.item(controls.length-1);
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
 else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
}
watch(navigationToggle,syncViewport,{flush:"post"});
watch([menuOpen,mobileNavigation],async([open,mobile],[wasOpen])=>{
 if(open&&mobile){
  if(savedOverflow===null){savedOverflow=document.body.style.overflow;document.body.style.overflow="hidden";}
  await nextTick();sidebar.value?.querySelector<HTMLElement>('button:not([disabled]),a[href]')?.focus();
 }else{
  if(savedOverflow!==null){document.body.style.overflow=savedOverflow;savedOverflow=null;}
  if(wasOpen&&mobile){await nextTick();navigationToggle.value?.focus();}
 }
});
onMounted(()=>{syncViewport();window.addEventListener("resize",syncViewport,{passive:true});document.addEventListener("keydown",drawerKey);});
onBeforeUnmount(()=>{window.removeEventListener("resize",syncViewport);document.removeEventListener("keydown",drawerKey);if(savedOverflow!==null)document.body.style.overflow=savedOverflow;});
const dealer=computed(()=>Boolean(route.meta.reseller));
const identity=computed(()=>dealer.value?reseller.session:auth.session);
const navigation=computed(()=>dealer.value?[
 {path:"/reseller",label:"Overview",icon:"grid",scope:"",group:"Workspace"},
 {path:"/reseller/customers",label:"Customers",icon:"users",scope:"customers",group:"Workspace"},
 {path:"/reseller/subscriptions",label:"Subscriptions",icon:"link",scope:"subscriptions",group:"Workspace"},
 {path:"/reseller/plans",label:"Plan catalog",icon:"box",scope:"catalog",group:"Workspace"},
 {path:"/reseller/team",label:"Team",icon:"shield",scope:"team",group:"Administration"},
].filter(link=>!link.scope||reseller.can(link.scope)):[
 {path:"/",label:"Overview",icon:"grid",scope:"",group:"Workspace"},
 {path:"/customers",label:"Customers",icon:"users",scope:"customers",group:"Workspace"},
 {path:"/services",label:"Managed services",icon:"link",scope:"services",group:"Workspace"},
 {path:"/sales",label:"Customer wallets",icon:"wallet",scope:"sales",group:"Finance"},
 {path:"/invoices",label:"Manual payments",icon:"wallet",scope:"invoices",group:"Finance"},
 {path:"/products",label:"Service products",icon:"box",scope:"products",group:"Workspace"},
 {path:"/plans",label:"Plans & bundles",icon:"box",scope:"catalog",group:"Workspace"},
 {path:"/subscriptions",label:"Subscriptions",icon:"link",scope:"subscriptions",group:"Workspace"},
 {path:"/loyalty",label:"Loyalty & discounts",icon:"users",scope:"catalog",group:"Finance"},
 {path:"/payments",label:"Payments",icon:"wallet",scope:"payments",group:"Finance"},
 {path:"/bots",label:"Telegram bots",icon:"bell",scope:"bots",group:"Operations"},
 {path:"/nodes",label:"Nodes",icon:"server",scope:"nodes",group:"Infrastructure"},
 {path:"/network",label:"Nodes",icon:"server",scope:"network",group:"Infrastructure"},
 {path:"/configurations",label:"Configurations",icon:"layers",scope:"network",group:"Infrastructure"},
 {path:"/connection-lab",label:"Connection lab",icon:"bolt",scope:"network",group:"Infrastructure"},
 {path:"/host-groups",label:"Delivery groups",icon:"box",scope:"network",group:"Infrastructure"},
 {path:"/automation",label:"Automation",icon:"bolt",scope:"",group:"Operations",visible:["payments","network","subscriptions"].some(scope=>auth.can(scope))},
 {path:"/notifications",label:"Notifications",icon:"bell",scope:"notifications",group:"Operations"},
 {path:"/support",label:"Support inbox",icon:"help",scope:"support",group:"Operations"},
 {path:"/resellers",label:"Resellers",icon:"users",scope:"resellers",group:"Administration"},
 {path:"/roles",label:"Roles",icon:"shield",scope:"staff",group:"Administration"},
 {path:"/staff",label:"Team & access",icon:"users",scope:"staff",group:"Administration"},
 {path:"/settings",label:"Settings",icon:"settings",scope:"settings",group:"Administration"},
].filter(link=>link.visible!==false&&(!link.scope||auth.can(link.scope))));
const groups=computed(()=>[...new Set(navigation.value.map(link=>link.group))]);
const bareWorkspace = computed(() => route.path === "/login" || route.path === "/reseller/login" || Boolean(route.meta.public || route.meta.customer));
const current=computed(()=>navigation.value.find(link=>link.path===route.path)||navigation.value.filter(link=>link.path!=="/").find(link=>route.path.startsWith(link.path)));
watch(()=>auth.session,session=>{if(session)void branding.refresh();else branding.clear();},{immediate:true});
watch(()=>route.path,()=>{menuOpen.value=false;},{immediate:true});
watch([()=>branding.title,()=>route.path,()=>t("navigation.Account")],()=>{document.title=`${navLabel(current.value?.label??"Account")} · ${branding.title||"Papilio"}`;},{immediate:true});
watch(()=>reseller.session,session=>{if(dealer.value&&reseller.checked&&!session&&!reseller.error&&route.path!=="/reseller/login")void router.push("/reseller/login");});
async function signOut():Promise<void>{if(signingOut.value)return;signingOut.value=true;signOutError.value="";try{if(dealer.value)await reseller.logout();else await auth.logout();await router.push(dealer.value?"/reseller/login":"/login");}catch(cause){signOutError.value=cause instanceof Error?cause.message:"Could not sign out. Try again.";}finally{signingOut.value=false;}}
</script>
<template>
 <DisplayPreferences v-if="bareWorkspace" :show-theme="!route.path.startsWith('/service/')" />
 <RouterView v-if="bareWorkspace" />
 <div v-else class="layout">
  <button v-if="menuOpen" type="button" class="navigation-backdrop" :aria-label="navLabel('Close navigation')" @click="menuOpen=false" />
  <aside ref="sidebar" :id="navigationId" class="sidebar" :class="{'sidebar-open':menuOpen}" :inert="mobileNavigation&&!menuOpen" :aria-hidden="mobileNavigation&&!menuOpen?true:undefined" :role="mobileNavigation&&menuOpen?'dialog':undefined" :aria-modal="mobileNavigation&&menuOpen?true:undefined" aria-label="Workspace navigation">
   <button type="button" class="icon-button drawer-close" :aria-label="navLabel('Close navigation')" @click="menuOpen=false">×</button>
   <RouterLink :to="dealer?'/reseller':'/'" class="brand"><img class="brand-logo papilio-logo papilio-logo-dark" src="/papilio-logo-dark.png" width="636" height="256" alt="Papilio" /><img class="brand-logo papilio-logo papilio-logo-light" src="/papilio-logo-light.png" width="636" height="256" alt="Papilio" /><small>{{branding.title||navLabel('SUBSCRIPTION WORKSPACE')}}</small></RouterLink>
   <nav><section v-for="group in groups" :key="group" class="navigation-group"><p class="sidebar-caption">{{navLabel(group)}}</p><RouterLink v-for="link in navigation.filter(item=>item.group===group)" :key="link.path" :to="link.path" class="nav-link" :class="{active:current?.path===link.path}"><Icon :name="link.icon" /><span>{{navLabel(link.label)}}</span><span v-if="current?.path===link.path" class="active-dot" /></RouterLink></section></nav>
   <div class="sidebar-bottom"><div class="workspace-symbol"><img src="/papilio-mark.svg" alt="" width="22" height="22" /></div><div><strong>{{navLabel('Control plane')}}</strong><small>{{navLabel('Private workspace')}}</small></div><Icon name="shield" :size="18" /></div>
  </aside>
  <div class="workspace" :inert="mobileNavigation&&menuOpen"><header class="topbar"><div class="topbar-location"><button ref="navigationToggle" class="icon-button mobile-menu" type="button" :aria-label="navLabel(menuOpen?'Close navigation':'Open navigation')" :aria-controls="navigationId" :aria-expanded="menuOpen" @click="menuOpen=!menuOpen"><Icon name="menu" /></button><span class="breadcrumb">{{navLabel('Workspace')}} <span>/</span> <strong>{{navLabel(current?.label||'Details')}}</strong></span></div><div class="operator"><DisplayPreferences compact /><span class="workspace-pill">{{navLabel('Control panel')}}</span><span class="avatar">{{identity?.username.slice(0,1).toUpperCase()}}</span><span>{{identity?.username}}</span><button type="button" class="icon-button" :aria-label="navLabel('Sign out')" :aria-busy="signingOut" :disabled="signingOut" @click="signOut"><Icon name="logout" :size="18" /></button></div></header>
   <main><p v-if="signOutError" class="message error" role="alert">{{signOutError}}</p><p v-if="dealer&&reseller.error" class="message error" role="alert">{{reseller.error}} <button class="btn small secondary" @click="reseller.restore">Retry</button></p><p v-if="!dealer&&branding.error" class="message error" role="alert">{{branding.error}} <button class="btn small secondary" @click="branding.refresh">Retry</button></p><RouterView :key="route.path" /></main>
  </div>
 </div>
</template>
