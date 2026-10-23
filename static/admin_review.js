// Navigasi keyboard halaman review: j/k pindah kartu, 1-9 pilih topik, x tidak relevan, Enter simpan.
(function () {
  "use strict";

  const cards = Array.from(document.querySelectorAll("[data-review-card]"));
  if (cards.length === 0) {
    return;
  }

  let current = -1;

  function focusCard(index) {
    if (index < 0 || index >= cards.length) {
      return;
    }
    current = index;
    cards[index].focus();
    cards[index].scrollIntoView({ block: "nearest" });
  }

  function cardOf(element) {
    return element ? element.closest("[data-review-card]") : null;
  }

  function isFormControl(element) {
    return element && /^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(element.tagName);
  }

  document.addEventListener("focusin", function (event) {
    const card = cardOf(event.target);
    const index = cards.indexOf(card);
    if (index >= 0) {
      current = index;
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.ctrlKey || event.metaKey || event.altKey) {
      return;
    }
    const card = cardOf(event.target) || cards[current];
    if (!card) {
      return;
    }

    if (event.key === "Enter") {
      if (isFormControl(event.target) && event.target.tagName === "BUTTON") {
        return;
      }
      const form = card.querySelector("form");
      if (form) {
        event.preventDefault();
        form.requestSubmit();
      }
      return;
    }

    if (isFormControl(event.target)) {
      return;
    }

    if (event.key === "j") {
      event.preventDefault();
      focusCard(current + 1);
    } else if (event.key === "k") {
      event.preventDefault();
      focusCard(current - 1);
    } else if (/^[1-9]$/.test(event.key)) {
      const select = card.querySelector("[data-topic-select]");
      const index = Number(event.key);
      if (select && index < select.options.length) {
        select.selectedIndex = index;
        event.preventDefault();
      }
    } else if (event.key === "x") {
      const checkbox = card.querySelector('input[name="tidak_relevan"]');
      if (checkbox) {
        checkbox.checked = !checkbox.checked;
        event.preventDefault();
      }
    }
  });

  const firstField = window.location.hash ? document.querySelector(window.location.hash) : null;
  focusCard(firstField ? Math.max(cards.indexOf(cardOf(firstField)), 0) : 0);
})();
