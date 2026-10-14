import { useI18n } from "vue-i18n";
import { faDate, toman as englishToman } from "@papilio/ui";

const persianNumber = new Intl.NumberFormat("fa-IR-u-nu-arabext", { maximumFractionDigits: 1 });
const persianDate = new Intl.DateTimeFormat("fa-IR-u-ca-persian-nu-arabext", { dateStyle: "medium", timeStyle: "short" });

export function useLocalizedFormats() {
  const { locale } = useI18n();

  function toman(amountRial: number): string {
    if (locale.value !== "fa") return englishToman(amountRial);
    return `${persianNumber.format(amountRial / 10)} تومان`;
  }

  function number(value: number, maximumFractionDigits = 3): string {
    const numberingSystem = locale.value === "fa" ? "arabext" : "latn";
    return new Intl.NumberFormat(`${locale.value}-u-nu-${numberingSystem}`, { maximumFractionDigits }).format(value);
  }

  function date(value: string | null): string {
    if (locale.value !== "fa") return faDate(value);
    if (value === null) return "بدون انقضا";
    const parsed = new Date(value);
    return Number.isFinite(parsed.getTime()) ? persianDate.format(parsed) : "زمان نامعتبر";
  }

  return { date, number, toman };
}
