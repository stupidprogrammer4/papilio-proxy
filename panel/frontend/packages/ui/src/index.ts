const integerFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const currencyFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const dateFormat = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" });

export function faNumber(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? integerFormat.format(parsed) : "—";
}

export function toman(rial: number): string {
  return `${currencyFormat.format(rial / 10)} toman`;
}

export function faDigits(value: string): string {
  return value;
}

export function asciiDigits(value: string): string {
  return value.replace(/[۰-۹]/g, digit => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit))).replace(/[٠-٩]/g, digit => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)));
}

export function faDate(iso: string | null): string {
  if (iso === null) return "No expiry";
  return dateFormat.format(new Date(iso));
}
