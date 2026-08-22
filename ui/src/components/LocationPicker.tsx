import { useEffect, useMemo, useRef, useState } from "react";
import type { Location } from "../types";

interface Props {
  locations: Location[];
  selected: string;
  onChange: (locationId: string) => void;
}

export function LocationPicker({ locations, selected, onChange }: Props) {
  const selectedLocation = useMemo(
    () => locations.find((loc) => loc.location_id === selected) ?? null,
    [locations, selected]
  );

  const [query, setQuery] = useState(selectedLocation?.display_name ?? "");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  // Keep the input text in sync when the selection changes from outside (e.g. initial load).
  useEffect(() => {
    setQuery(selectedLocation?.display_name ?? "");
  }, [selectedLocation]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery(selectedLocation?.display_name ?? "");
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [selectedLocation]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return locations;
    return locations.filter((loc) => loc.display_name.toLowerCase().includes(q));
  }, [locations, query]);

  function selectLocation(loc: Location) {
    onChange(loc.location_id);
    setQuery(loc.display_name);
    setOpen(false);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setHighlight((h) => Math.min(h + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (results[highlight]) selectLocation(results[highlight]);
    } else if (e.key === "Escape") {
      setOpen(false);
      setQuery(selectedLocation?.display_name ?? "");
    }
  }

  return (
    <div className="location-picker" ref={containerRef}>
      <span className="location-picker__label">Location</span>
      <div className="location-picker__combobox">
        <input
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          placeholder="Search for a city..."
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setHighlight(0);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {open && (
          <ul className="location-picker__results" role="listbox">
            {results.length === 0 && <li className="location-picker__empty">No cities match.</li>}
            {results.map((loc, i) => (
              <li
                key={loc.location_id}
                role="option"
                aria-selected={loc.location_id === selected}
                className={
                  "location-picker__option" +
                  (i === highlight ? " location-picker__option--highlight" : "") +
                  (loc.location_id === selected ? " location-picker__option--selected" : "")
                }
                onMouseDown={(e) => {
                  e.preventDefault(); // keep focus/avoid the input's blur firing first
                  selectLocation(loc);
                }}
                onMouseEnter={() => setHighlight(i)}
              >
                {loc.display_name}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
