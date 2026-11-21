document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-slider]").forEach(function (slider) {
        const viewport = slider.querySelector(".sidebar-slider-viewport");
        const track = slider.querySelector(".sidebar-slider-track");
        if (!viewport || !track) return;

        const slides = track.querySelectorAll(".sidebar-slide");
        const prevBtn = slider.querySelector("[data-prev]");
        const nextBtn = slider.querySelector("[data-next]");

        let currentIndex = 0;
        let slideInterval;

        function updateSlidePosition() {
            if (currentIndex >= slides.length) currentIndex = 0;
            if (currentIndex < 0) currentIndex = slides.length - 1;

            track.style.transform = `translateX(-${currentIndex * 100}%)`;
        }

        function nextSlide() {
            currentIndex++;
            updateSlidePosition();
        }

        function prevSlide() {
            currentIndex--;
            updateSlidePosition();
        }

        function startAutoPlay() {
            stopAutoPlay();
            if (slides.length > 1) {
                slideInterval = setInterval(nextSlide, 4000); // 4 seconds
            }
        }

        function stopAutoPlay() {
            clearInterval(slideInterval);
        }

        if (nextBtn) {
            nextBtn.addEventListener("click", () => {
                nextSlide();
                startAutoPlay();
            });
        }

        if (prevBtn) {
            prevBtn.addEventListener("click", () => {
                prevSlide();
                startAutoPlay();
            });
        }

        viewport.addEventListener("mouseenter", stopAutoPlay);
        viewport.addEventListener("mouseleave", startAutoPlay);

        startAutoPlay();
    });
});