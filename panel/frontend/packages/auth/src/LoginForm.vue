<script setup lang="ts">
import { ref } from "vue";
import { useAuth, useResellerAuth } from "./index";
const props=withDefaults(defineProps<{realm?:"admin"|"reseller"}>(),{realm:"admin"});
const emit=defineEmits<{ signedIn: [] }>();
const auth=props.realm==="reseller"?useResellerAuth():useAuth();const username=ref("");const password=ref("");const error=ref("");const busy=ref(false);
async function submit():Promise<void>{
  if(busy.value)return;busy.value=true;error.value="";
  try{await auth.login(username.value.trim(),password.value);password.value="";emit("signedIn");}
  catch(cause){error.value=cause instanceof Error?cause.message:"Sign in failed. Check your credentials and try again.";}
  finally{busy.value=false;}
}
</script>
<template>
  <form class="login-card form-grid" @submit.prevent="submit"><div><p class="eyebrow">{{realm==='reseller'?'Reseller sign in':'Admin sign in'}}</p><h2>Welcome back</h2><p>{{realm==='reseller'?'Sign in with your reseller account.':'Sign in with your staff account.'}}</p></div><label class="field"><span>Username</span><input v-model="username" autocomplete="username" required dir="ltr" :disabled="busy" /></label><label class="field"><span>Password</span><input v-model="password" type="password" autocomplete="current-password" minlength="8" maxlength="256" required :disabled="busy" /></label><p v-if="error" class="message error" role="alert">{{ error }}</p><button class="btn" :disabled="busy">{{ busy?'Signing in…':'Sign in' }}</button></form>
</template>
