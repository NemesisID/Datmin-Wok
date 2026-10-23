// Batasi pilihan perbandingan di klien. Server tetap memeriksa ulang.
document.querySelectorAll("form[data-banding]").forEach((form) => {
  const max = Number(form.dataset.max || 3);
  const boxes = [...form.querySelectorAll('input[name="dosen"]')];
  const counter = form.querySelector("[data-banding-hitung]");
  const button = form.querySelector('button[type="submit"]');

  function refresh() {
    const chosen = boxes.filter((box) => box.checked);
    if (chosen.length > max) {
      chosen[max].checked = false;
    }
    const selected = boxes.filter((box) => box.checked).length;
    if (counter) {
      counter.textContent = selected
        ? `${selected} dari ${max} dosen dipilih.`
        : `Belum ada dosen dipilih.`;
    }
    if (button) {
      button.disabled = selected < 2;
    }
  }

  boxes.forEach((box) => box.addEventListener("change", refresh));
  refresh();
});
