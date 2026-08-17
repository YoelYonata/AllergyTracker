import type { Location } from "../types";

interface Props {
  locations: Location[];
  selected: string;
  onChange: (locationId: string) => void;
}

export function LocationPicker({ locations, selected, onChange }: Props) {
  return (
    <label className="location-picker">
      <span>Location</span>
      <select value={selected} onChange={(e) => onChange(e.target.value)}>
        {locations.map((loc) => (
          <option key={loc.location_id} value={loc.location_id}>
            {loc.display_name}
          </option>
        ))}
      </select>
    </label>
  );
}
