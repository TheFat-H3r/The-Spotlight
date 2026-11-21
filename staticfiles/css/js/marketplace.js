document.addEventListener("DOMContentLoaded", function () {
    const viewport = document.getElementById("adSliderViewport");
    const track = document.getElementById("adSliderTrack");
    if (!viewport || !track) return;

    const slides = track.querySelectorAll(".ad-slide");
    const prevBtn = document.getElementById("adPrev");
    const nextBtn = document.getElementById("adNext");

    let currentIndex = 0;
    let slideInterval;

    function getVisibleColumns() {
        return window.innerWidth <= 576 ? 1 : 2;
    }

    function updateSlidePosition() {
        const visibleCols = getVisibleColumns();
        const maxIndex = Math.max(0, slides.length - visibleCols);

        // Wrap around when reaching the end
        if (currentIndex > maxIndex) currentIndex = 0;
        if (currentIndex < 0) currentIndex = maxIndex;

        const stepPercent = 100 / visibleCols;
        track.style.transform = `translateX(-${currentIndex * stepPercent}%)`;
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
        // Only animate if there are more ads than visible columns
        if (slides.length > getVisibleColumns()) {
            slideInterval = setInterval(nextSlide, 4000); // 4 seconds
        }
    }

    function stopAutoPlay() {
        clearInterval(slideInterval);
    }

    // Button listeners
    if (nextBtn) {
        nextBtn.addEventListener("click", () => {
            nextSlide();
            startAutoPlay(); // Reset timer on manual click
        });
    }

    if (prevBtn) {
        prevBtn.addEventListener("click", () => {
            prevSlide();
            startAutoPlay();
        });
    }

    // Pause on hover so users can read/click links easily
    viewport.addEventListener("mouseenter", stopAutoPlay);
    viewport.addEventListener("mouseleave", startAutoPlay);

    // Recalculate on window resize
    window.addEventListener("resize", () => {
        updateSlidePosition();
        startAutoPlay();
    });

    startAutoPlay();
});