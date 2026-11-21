
/* =========================================================
   THE SPOTLIGHT - MARKETPLACE FILTERS
   File: filters.js

   Responsibilities:
   1. Validate filter inputs.
   2. Handle vendor type and category selections.
   3. Validate maximum price.
   4. Submit filters using GET parameters.
   5. Provide submission feedback.
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {

    const filterForms = document.querySelectorAll(
        ".filter-panel form"
    );

    filterForms.forEach(function (filterForm) {

        const vendorType = filterForm.querySelector(
            '[name="vendor_type"]'
        );

        const category = filterForm.querySelector(
            '[name="category"]'
        );

        const maxPrice = filterForm.querySelector(
            '[name="max_price"]'
        );

        const location = filterForm.querySelector(
            '[name="location"]'
        );

        const submitButton = filterForm.querySelector(
            'button[type="submit"]'
        );


        /* =================================================
           1. MAXIMUM PRICE VALIDATION
           ================================================= */

        if (maxPrice) {

            maxPrice.addEventListener("input", function () {

                const price = Number(this.value);

                if (this.value !== "" && (
                    !Number.isFinite(price) || price < 0
                )) {
                    this.setCustomValidity(
                        "Enter a valid non-negative price."
                    );
                } else {
                    this.setCustomValidity("");
                }

            });

        }


        /* =================================================
           2. FORM SUBMISSION
           ================================================= */

        filterForm.addEventListener("submit", function (event) {

            // Validate the form before submitting.
            if (!filterForm.checkValidity()) {

                event.preventDefault();

                filterForm.reportValidity();

                return;
            }

            // Ensure maximum price is a valid number.
            if (maxPrice && maxPrice.value.trim() !== "") {

                const price = Number(maxPrice.value);

                if (!Number.isFinite(price) || price < 0) {

                    event.preventDefault();

                    maxPrice.setCustomValidity(
                        "Enter a valid non-negative price."
                    );

                    maxPrice.reportValidity();

                    return;
                }

            }

            // Display loading feedback.
            if (submitButton) {

                submitButton.disabled = true;

                submitButton.textContent = "Applying filters...";

                submitButton.setAttribute(
                    "aria-busy",
                    "true"
                );

            }

            // Allow the browser to submit the GET form.
            // Django will process the filter parameters.

        });


        /* =================================================
           3. FILTER INPUT ACCESSIBILITY
           ================================================= */

        [vendorType, category, maxPrice, location].forEach(
            function (input) {

                if (!input) {
                    return;
                }

                input.addEventListener("change", function () {

                    this.classList.remove("is-invalid");

                });

            }
        );

    });


    /* =====================================================
       4. CLEAR FILTERS
       ===================================================== */

    const clearFilterLinks = document.querySelectorAll(
        '.filter-panel a[href]'
    );

    clearFilterLinks.forEach(function (link) {

        link.addEventListener("click", function () {

            // The link navigates to the unfiltered marketplace.
            // No manual form reset is needed.

        });

    });


    console.log("Spotlight marketplace filters initialized.");

});
