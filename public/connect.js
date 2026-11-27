for (const button of document.querySelectorAll("[data-copy]")) {
  button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.copy);
    const status = button.closest("section").querySelector("[data-copy-status]");
    try {
      await navigator.clipboard.writeText(target.value ?? target.textContent.trim());
      status.textContent = "Copied.";
    } catch {
      if (target.select) target.select();
      else {
        const range = document.createRange();
        range.selectNodeContents(target);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      }
      status.textContent = "Copy the selected text.";
    }
  });
}
