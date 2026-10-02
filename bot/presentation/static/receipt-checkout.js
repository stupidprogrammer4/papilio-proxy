"use strict";
(() => {
  const form = document.getElementById("receipt-form");
  const status = document.getElementById("receipt-status");
  const copy = document.getElementById("copy-card");
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(copy.dataset.card); copy.textContent = "✅ کپی شد"; }
    catch { status.textContent = "شماره کارت را انتخاب و کپی کن."; }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = document.getElementById("receipt").files[0];
    if (!file || file.size > 2000000 || !["image/png", "image/jpeg"].includes(file.type)) {
      status.textContent = "تصویر PNG یا JPEG با حجم حداکثر ۲ مگابایت انتخاب کن."; return;
    }
    const button = form.querySelector("button"); button.disabled = true;
    status.textContent = "⏳ در حال ارسال و تأیید خودکار رسید…";
    try {
      const image = await new Promise((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(reader.result);
        reader.onerror = reject; reader.readAsDataURL(file);
      });
      const response = await fetch(location.pathname.replace(/\/$/, "") + "/receipt", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({image}), credentials: "omit",
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "پاسخ درگاه نرسید؛ دوباره پرداخت نکن.");
      status.textContent = result.paid ? "✅ تأیید شد؛ در حال بازگشت به بات…" : "⏳ رسید ثبت شد؛ تأیید خودکار در پس‌زمینه ادامه دارد. دوباره پرداخت نکن.";
      location.assign(result.callback);
    } catch (error) { status.textContent = error.message || "پاسخ قطعی نرسید؛ دوباره پرداخت نکن."; }
    finally { button.disabled = false; }
  });
})();
