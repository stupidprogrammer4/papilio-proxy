"use strict";
document.getElementById("copy-subscription").addEventListener("click", async () => {
  const field = document.getElementById("subscription-link");
  const status = document.getElementById("copy-status");
  try {
    await navigator.clipboard.writeText(field.value);
    status.textContent = "✓ لینک کپی شد؛ در برنامهٔ اتصال وارد کن.";
  } catch {
    field.focus();
    field.select();
    status.textContent = "لینک انتخاب شد؛ آن را دستی کپی کن.";
  }
});
