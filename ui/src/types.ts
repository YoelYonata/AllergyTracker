export type PollenType = "GRASS" | "TREE" | "WEED";

export interface Location {
  location_id: string;
  display_name: string;
}

export interface PollenTypeReading {
  upi: number | null;
  category: string | null;
  in_season: boolean | null;
  display_name: string;
}

export interface Reading {
  date: string;
  location_id: string;
  region_code?: string;
  fetched_at: string;
  max_upi: number | null;
  types: Partial<Record<PollenType, PollenTypeReading>>;
}

export interface LatestResponse {
  location: Location;
  reading: Reading | null;
}

export interface HistoryResponse {
  location: Location;
  days: number;
  from: string;
  to: string;
  readings: Reading[];
}

export interface SubscribePayload {
  email: string;
  location: string;
}

export interface ApiErrorBody {
  error: string;
}
