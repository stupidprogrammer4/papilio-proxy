import type { ConfigurationOptions } from "@papilio/api";

export interface EditableConfiguration { label: string; options: ConfigurationOptions }
export interface JsonEditorRequest { id: number; action: "print" | "parse" | "document"; value?: EditableConfiguration; text?: string; optionKeys?: string[] }
export interface JsonEditorReply { id: number; success: boolean; text?: string; value?: EditableConfiguration; message?: string }
const scope = self as unknown as { onmessage: (event: MessageEvent<JsonEditorRequest>) => void; postMessage: (value: JsonEditorReply) => void };
scope.onmessage = ({ data }) => {
  try {
    if (data.action === "print") {
      scope.postMessage({ id: data.id, success: true, text: JSON.stringify(data.value, null, 2) });
      return;
    }
    const value: unknown = JSON.parse(data.text ?? "");
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("ریشهٔ JSON باید یک شیء باشد.");
    if (data.action === "document") { scope.postMessage({ id: data.id, success: true, text: JSON.stringify(value, null, 2) }); return; }
    const record = value as Record<string, unknown>;
    if (Object.keys(record).some(key => !["label", "options"].includes(key))) throw new Error("فقط Label label و Settings options قابل ویرایش‌اند.");
    if (typeof record.label !== "string" || !record.options || typeof record.options !== "object" || Array.isArray(record.options)) throw new Error("Label label و شیء options لازم‌اند.");
    if (Object.keys(record.options).some(key => !data.optionKeys?.includes(key))) throw new Error("تنظیم ناشناخته در options وجود دارد؛ Name فیلدها را بررسی کنید.");
    const result = record as unknown as EditableConfiguration;
    scope.postMessage({ id: data.id, success: true, value: result, text: JSON.stringify(result, null, 2) });
  } catch (error) {
    scope.postMessage({ id: data.id, success: false, message: error instanceof SyntaxError ? "JSON معتبر نیست؛ نشانه‌ها و ویرگول‌ها را بررسی کنید." : error instanceof Error ? error.message : "JSON بررسی نشد." });
  }
};
