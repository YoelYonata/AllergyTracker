import { useEffect, useState } from "react";
import "./App.css";
import { getHistory, getLatest, getLocations } from "./api";
import { LocationPicker } from "./components/LocationPicker";
import { SubscribeForm } from "./components/SubscribeForm";
import { TodaySummary } from "./components/TodaySummary";
import { TrendChart } from "./components/TrendChart";
import type { Location, Reading } from "./types";

export default function App() {
  const [locations, setLocations] = useState<Location[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [latest, setLatest] = useState<Reading | null>(null);
  const [history, setHistory] = useState<Reading[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getLocations()
      .then((res) => {
        setLocations(res.locations);
        if (res.locations.length > 0) setSelected(res.locations[0].location_id);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load locations."));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setError(null);
    Promise.all([getLatest(selected), getHistory(selected, 14)])
      .then(([latestRes, historyRes]) => {
        setLatest(latestRes.reading);
        setHistory(historyRes.readings);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load pollen data."));
  }, [selected]);

  return (
    <div className="app">
      <header className="app__header">
        <h1>Allergy Tracker</h1>
        {locations.length > 0 && (
          <LocationPicker locations={locations} selected={selected} onChange={setSelected} />
        )}
      </header>

      {error && <div className="app__error">{error}</div>}

      {selected && (
        <>
          <TodaySummary reading={latest} />
          <TrendChart readings={history} />
          <SubscribeForm locationId={selected} />
        </>
      )}
    </div>
  );
}
