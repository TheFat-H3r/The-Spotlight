document.addEventListener("DOMContentLoaded", function () {
    const accordion = document.getElementById("spotlightFaqAccordion");
    if (!accordion) return;

    const triggers = accordion.querySelectorAll(".faq-trigger");

    triggers.forEach((trigger) => {
        trigger.addEventListener("click", function () {
            const item = trigger.closest(".faq-item");
            if (!item) return;

            const isCurrentlyOpen = item.classList.contains("is-open");

            // Optional: close other items so only one is expanded at a time
            accordion.querySelectorAll(".faq-item.is-open").forEach((openItem) => {
                if (openItem !== item) {
                    openItem.classList.remove("is-open");
                    const openBtn = openItem.querySelector(".faq-trigger");
                    if (openBtn) {
                        openBtn.setAttribute("aria-expanded", "false");
                    }
                }
            });

            item.classList.toggle("is-open", !isCurrentlyOpen);
            trigger.setAttribute("aria-expanded", String(!isCurrentlyOpen));
        });
    });
});