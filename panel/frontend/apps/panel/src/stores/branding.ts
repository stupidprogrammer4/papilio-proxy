import { defineStore } from "pinia";
import { ref } from "vue";
import { request } from "@papilio/api";
export const useBranding = defineStore("branding", () => {
  const title = ref(""); const error = ref("");
  async function refresh(): Promise<void> {
    try { const result = await request<{ brand_title: string }>("/v1/system/status"); title.value = result.brand_title; error.value = ""; }
    catch (cause) { error.value = cause instanceof Error ? cause.message : "The operation failed. Please try again."; }
  }
  function clear(): void { title.value = ""; error.value = ""; }
  return { title, error, refresh, clear };
});
