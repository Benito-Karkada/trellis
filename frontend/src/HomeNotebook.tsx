import { useState } from "react";
import { ArrowLeft, ArrowRight } from "lucide-react";
import UpcomingPanel from "./UpcomingPanel";
import type { useUpcoming } from "./useUpcoming";

/** Spiral-notebook carousel: slide 1 is the Upcoming list, slide 2 is an empty square for now (the course-map picture goes there later). */
export default function HomeNotebook({
  upcoming,
  onOpen,
  onManageDeadlines,
}: {
  upcoming: ReturnType<typeof useUpcoming>;
  onOpen: (lesson: number, activity: number | null) => void;
  onManageDeadlines?: () => void;
}) {
  const [slide, setSlide] = useState(0);
  return (
    <div className="ch-nb">
      <div className="ch-nb-rings" aria-hidden="true">
        {Array.from({ length: 13 }, (_, i) => (
          <span key={i} />
        ))}
      </div>
      <div
        className="ch-nb-card"
        role="region"
        aria-roledescription="carousel"
        aria-label="Upcoming assignments and course map"
      >
        <div className="ch-nb-viewport">
          <div
            className="ch-nb-track"
            style={{ transform: `translateX(-${slide * 50}%)` }}
          >
            <div
              className="ch-nb-slide ch-nb-slide-upcoming"
              role="group"
              aria-roledescription="slide"
              aria-label="1 of 2: Upcoming"
              tabIndex={slide === 0 ? 0 : -1}
              aria-hidden={slide !== 0}
              inert={slide !== 0}
            >
              <UpcomingPanel
                items={upcoming.items}
                onToggle={upcoming.toggle}
                pending={upcoming.pending}
                loading={upcoming.loading}
                error={upcoming.error}
                onRetry={upcoming.refresh}
                onOpen={onOpen}
                onManageDeadlines={onManageDeadlines}
              />
            </div>
            <div
              className="ch-nb-slide ch-nb-slide-map"
              role="group"
              aria-roledescription="slide"
              aria-label="2 of 2: Course map"
              aria-hidden={slide !== 1}
              inert={slide !== 1}
            >
              {/* Placeholder. Replace this square with the picture (an <img> or an inline SVG) when it is ready. */}
              <div className="ch-nb-placeholder" aria-hidden="true" />
            </div>
          </div>
        </div>
        <div className="ch-nb-controls">
          <button
            type="button"
            className="ch-nb-arrow"
            aria-label="Previous slide"
            disabled={slide === 0}
            onClick={() => setSlide(0)}
          >
            <ArrowLeft size={18} />
          </button>
          <div className="ch-nb-dots">
            {["Show upcoming", "Show course map"].map((label, i) => (
              <button
                key={label}
                type="button"
                className="ch-nb-dot"
                aria-label={label}
                aria-current={slide === i ? "true" : undefined}
                onClick={() => setSlide(i)}
              />
            ))}
          </div>
          <button
            type="button"
            className="ch-nb-arrow"
            aria-label="Next slide"
            disabled={slide === 1}
            onClick={() => setSlide(1)}
          >
            <ArrowRight size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
