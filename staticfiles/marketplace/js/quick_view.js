
/* =========================================================
   THE SPOTLIGHT - PRODUCT QUICK VIEW
   File: quick_view.js

   Responsibilities:
   1. Open the Bootstrap Quick View modal.
   2. Display selected product information.
   3. Display the product image.
   4. Link to the full product detail page.
   5. Reset modal content when closed.
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {

    const quickViewModalElement = document.getElementById(
        "quickViewModal"
    );

    // Stop if the page does not contain the Quick View modal.
    if (!quickViewModalElement) {
        return;
    }

    // Bootstrap is required for the modal.
    if (!window.bootstrap) {
        console.error(
            "Bootstrap JavaScript is required for Quick View."
        );
        return;
    }

    const quickViewModal = bootstrap.Modal.getOrCreateInstance(
        quickViewModalElement
    );

    // Modal elements.
    const modalTitle = document.getElementById("quickViewTitle");
    const modalImage = document.getElementById("quickViewImage");
    const modalName = document.getElementById("quickViewName");
    const modalDescription = document.getElementById(
        "quickViewDescription"
    );
    const modalPrice = document.getElementById("quickViewPrice");
    const modalLink = document.getElementById("quickViewLink");

    // Default image when a product does not have an image.
    const placeholderImage = "/static/img/product-placeholder.png";


    /* =====================================================
       1. OPEN QUICK VIEW
       ===================================================== */

    document.addEventListener("click", function (event) {

        const quickViewButton = event.target.closest(
            ".quick-view-button"
        );

        if (!quickViewButton) {
            return;
        }

        event.preventDefault();

        // Read product information from the clicked button.
        const productName =
            quickViewButton.dataset.name || "Product";

        const productDescription =
            quickViewButton.dataset.description ||
            "No product description is available.";

        const productPrice =
            quickViewButton.dataset.price || "Price unavailable";

        const productImage =
            quickViewButton.dataset.image || placeholderImage;

        const productUrl =
            quickViewButton.dataset.url || "#";


        /* =================================================
           2. POPULATE MODAL CONTENT
           ================================================= */

        // Use textContent instead of innerHTML for safety.
        if (modalTitle) {
            modalTitle.textContent = "Product Quick View";
        }

        if (modalName) {
            modalName.textContent = productName;
        }

        if (modalDescription) {
            modalDescription.textContent = productDescription;
        }

        if (modalPrice) {
            modalPrice.textContent = productPrice;
        }

        if (modalImage) {

            modalImage.src = productImage;
            modalImage.alt = productName;

            modalImage.onerror = function () {
                this.onerror = null;
                this.src = placeholderImage;
            };

        }

        if (modalLink) {

            if (productUrl && productUrl !== "#") {
                modalLink.href = productUrl;
                modalLink.classList.remove("disabled");
                modalLink.removeAttribute("aria-disabled");
            } else {
                modalLink.href = "#";
                modalLink.classList.add("disabled");
                modalLink.setAttribute("aria-disabled", "true");
            }

        }


        /* =================================================
           3. DISPLAY MODAL
           ================================================= */

        quickViewModal.show();

    });


    /* =====================================================
       4. RESET MODAL AFTER CLOSING
       ===================================================== */

    quickViewModalElement.addEventListener(
        "hidden.bs.modal",
        function () {

            if (modalName) {
                modalName.textContent = "";
            }

            if (modalDescription) {
                modalDescription.textContent = "";
            }

            if (modalPrice) {
                modalPrice.textContent = "";
            }

            if (modalImage) {
                modalImage.removeAttribute("src");
                modalImage.alt = "";
            }

            if (modalLink) {
                modalLink.href = "#";
                modalLink.classList.add("disabled");
                modalLink.setAttribute("aria-disabled", "true");
            }

        }
    );

});
