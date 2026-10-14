import { computed, ref, watch } from "vue";
import { defineStore } from "pinia";
import { i18n } from "../i18n";

export type Locale = "en" | "fa";
export type Theme = "light" | "dark" | "system";

function savedChoice<T extends string>(key: string, choices: readonly T[], fallback: T): T {
  try {
    const value = localStorage.getItem(key);
    return choices.find(choice => choice === value) ?? fallback;
  } catch {
    return fallback;
  }
}

export const useDisplayPreferences = defineStore("display-preferences", () => {
  const locale = ref(savedChoice("papilio.locale", ["en", "fa"] as const, "en"));
  const theme = ref(savedChoice("papilio.theme", ["light", "dark", "system"] as const, "dark"));
  const systemDark = ref(matchMedia("(prefers-color-scheme: dark)").matches);
  const persistent = ref(true);
  const effectiveTheme = computed(() => theme.value === "system" ? (systemDark.value ? "dark" : "light") : theme.value);

  function saveChoices(): void {
    try {
      localStorage.setItem("papilio.locale", locale.value);
      localStorage.setItem("papilio.theme", theme.value);
      persistent.value = true;
    } catch {
      persistent.value = false;
    }
  }

  function applyDisplay(): void {
    i18n.global.locale.value = locale.value;
    document.documentElement.lang = locale.value;
    document.documentElement.dir = locale.value === "fa" ? "rtl" : "ltr";
    document.documentElement.dataset.theme = effectiveTheme.value;
    document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute(
      "content",
      effectiveTheme.value === "dark" ? "#080808" : "#f4f4f4",
    );
  }

  watch([locale, theme], saveChoices);
  watch([locale, effectiveTheme], applyDisplay, { immediate: true, flush: "sync" });

  function listenForSystemTheme(): () => void {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const changed = (event: MediaQueryListEvent): void => { systemDark.value = event.matches; };
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }

  return { locale, theme, persistent, effectiveTheme, listenForSystemTheme };
});
