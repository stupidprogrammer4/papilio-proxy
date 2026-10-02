"use strict";
const returnElement = document.getElementById("payment-return");
if (returnElement) {
  const destination = new URL(returnElement.dataset.url);
  if (destination.protocol === "https:" && destination.hostname === "t.me") {
    setTimeout(() => window.location.replace(destination.href), 1800);
  }
}
