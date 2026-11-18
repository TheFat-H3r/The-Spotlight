
/* =========================================================
   THE SPOTLIGHT - MARKETPLACE
   Main JavaScript
   Responsibilities:
   1. Scroll reveal animations
   2. Staggered card animations
   3. Sticky header transition
   4. Back to top button
   5. Advertisement carousel pause controls
   6. Smooth anchor navigation
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {

    /* =====================================================
       1. ACCESSIBILITY: REDUCED MOTION
       ===================================================== */

    const prefersReducedMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)"
    ).matches;


    /* =====================================================
       2. SCROLL REVEAL ANIMATIONS
       ===================================================== */

    const revealSections = document.querySelectorAll(
        ".reveal-section"
    );

    // Add animation classes to cards inside reveal sections.
    revealSections.forEach(function (section) {

        const animatedElements = section.querySelectorAll(
            ".market-card, .vendor-card, .review-card, " +
            ".portfolio-card, .announcement-card"
        );

        animatedElements.forEach(function (element) {
            element.classList.add("reveal-item");
        });

    });

    if (prefersReducedMotion || !("IntersectionObserver" in window)) {

        // Display everything if animations are disabled
        // or IntersectionObserver is unavailable.
        revealSections.forEach(function (section) {
            section.classList.add("is-visible");
        });

    } else {

        const revealObserver = new IntersectionObserver(
            function (entries, observer) {

                entries.forEach(function (entry) {

                    if (entry.isIntersecting) {

                        entry.target.classList.add("is-visible");

                        // Stop observing once the section appears.
                        observer.unobserve(entry.target);

                    }

                });

            },
            {
                threshold: 0.12,
                rootMargin: "0px 0px -40px 0px"
            }
        );

        revealSections.forEach(function (section) {
            revealObserver.observe(section);
        });

    }


    /* =====================================================
       3. STICKY HEADER SCROLL TRANSITION
       ===================================================== */

    const siteHeader = document.querySelector(".site-header");

    function updateHeader() {

        if (!siteHeader) {
            return;
        }

        if (window.scrollY > 30) {
            siteHeader.classList.add("scrolled");
        } else {
            siteHeader.classList.remove("scrolled");
        }

    }

    window.addEventListener("scroll", updateHeader, {
        passive: true
    });

    updateHeader();


    /* =====================================================
       4. BACK TO TOP BUTTON
       ===================================================== */

    const backToTopButton = document.getElementById("backToTop");

    if (backToTopButton) {

        function updateBackToTop() {

            if (window.scrollY > 400) {
                backToTopButton.classList.add("visible");
            } else {
                backToTopButton.classList.remove("visible");
            }

        }

        window.addEventListener("scroll", updateBackToTop, {
            passive: true
        });

        backToTopButton.addEventListener("click", function () {

            window.scrollTo({
                top: 0,
                behavior: prefersReducedMotion ? "instant" : "smooth"
            });

        });

        updateBackToTop();

    }


    /* =====================================================
       5. ADVERTISEMENT CAROUSEL
       Pause when hovered or focused.
       ===================================================== */

    const advertisementCarousel = document.getElementById(
        "advertisementCarousel"
    );

    if (advertisementCarousel && window.bootstrap) {

        const carousel = bootstrap.Carousel.getOrCreateInstance(
            advertisementCarousel
        );

        advertisementCarousel.addEventListener("mouseenter", function () {
            carousel.pause();
        });

        advertisementCarousel.addEventListener("mouseleave", function () {
            carousel.cycle();
        });

        advertisementCarousel.addEventListener("focusin", function () {
            carousel.pause();
        });

        advertisementCarousel.addEventListener("focusout", function (event) {

            // Resume only when keyboard focus leaves the carousel.
            if (!advertisementCarousel.contains(event.relatedTarget)) {
                carousel.cycle();
            }

        });

    }


    /* =====================================================
       6. SMOOTH ANCHOR NAVIGATION
       ===================================================== */

    const internalLinks = document.querySelectorAll(
        'a[href^="#"]'
    );

    internalLinks.forEach(function (link) {

        link.addEventListener("click", function (event) {

            const targetId = link.getAttribute("href");

            // Ignore empty anchors.
            if (!targetId || targetId === "#") {
                return;
            }

            const targetElement = document.querySelector(targetId);

            if (!targetElement) {
                return;
            }

            event.preventDefault();

            targetElement.scrollIntoView({
                behavior: prefersReducedMotion ? "instant" : "smooth",
                block: "start"
            });

        });

    });


    /* =====================================================
       7. LAZY IMAGE LOADING SUPPORT
       ===================================================== */

    const marketplaceImages = document.querySelectorAll(
        ".market-card img, .vendor-card img, " +
        ".portfolio-card img, .review-card img"
    );

    marketplaceImages.forEach(function (image) {

        if (!image.hasAttribute("loading")) {
            image.setAttribute("loading", "lazy");
        }

        if (!image.hasAttribute("decoding")) {
            image.setAttribute("decoding", "async");
        }

    });


    /* =====================================================
       8. PREVENT EMPTY PLACEHOLDER LINKS
       ===================================================== */

    const placeholderLinks = document.querySelectorAll(
        'a[href="#"]'
    );

    placeholderLinks.forEach(function (link) {

        link.addEventListener("click", function (event) {

            event.preventDefault();

        });

    });


    /* =====================================================
       9. MARKETPLACE INITIALIZATION
       ===================================================== */

    document.documentElement.classList.add(
        "marketplace-js-ready"
    );

    console.log("Spotlight Marketplace initialized successfully.");

});
