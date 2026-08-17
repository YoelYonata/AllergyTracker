import type { PollenType, Reading } from "../types";
import { seriesColor } from "../theme";
import { useDarkMode } from "../useDarkMode";

const TYPE_ORDER: PollenType[] = ["TREE", "GRASS", "WEED"];

interface Props {
  reading: Reading | null;
}

export function TodaySummary({ reading }: Props) {
  const isDark = useDarkMode();

  if (!reading) {
    return (
      <div className="today-summary today-summary--empty">
        No reading yet for this location. The ingestion job runs every few hours -- check back
        shortly.
      </div>
    );
  }

  return (
    <div className="today-summary">
      <div className="today-summary__header">
        <h2>Today's pollen</h2>
        <span className="today-summary__date">{reading.date}</span>
      </div>
      <div className="today-summary__cards">
        {TYPE_ORDER.map((type) => {
          const t = reading.types[type];
          return (
            <div
              key={type}
              className="today-summary__card"
              style={{ borderInlineStartColor: seriesColor(type, isDark) }}
            >
              <div className="today-summary__card-label">{t?.display_name ?? type}</div>
              <div className="today-summary__card-value">
                {t?.upi ?? "--"}
                <span className="today-summary__card-scale">/5</span>
              </div>
              <div className="today-summary__card-category">
                {t?.upi == null ? "No coverage" : t.category ?? "--"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
