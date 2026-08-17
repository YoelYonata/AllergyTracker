import { useState, type FormEvent } from "react";
import { subscribe } from "../api";

interface Props {
  locationId: string;
}

type Status = { kind: "idle" } | { kind: "sending" } | { kind: "done"; message: string } | { kind: "error"; message: string };

export function SubscribeForm({ locationId }: Props) {
  const [email, setEmail] = useState("");
  const [threshold, setThreshold] = useState(3);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setStatus({ kind: "sending" });
    try {
      const res = await subscribe({ email, location: locationId, threshold });
      setStatus({ kind: "done", message: res.message });
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "Something went wrong." });
    }
  }

  return (
    <form className="subscribe-form" onSubmit={onSubmit}>
      <h2>Get alerts</h2>
      <p className="subscribe-form__hint">
        We'll email you when any watched pollen type crosses your threshold for this location.
      </p>
      <label>
        <span>Email</span>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
        />
      </label>
      <label>
        <span>Alert threshold (UPI 0-5)</span>
        <input
          type="number"
          min={0}
          max={5}
          required
          value={threshold}
          onChange={(e) => setThreshold(Number(e.target.value))}
        />
      </label>
      <button type="submit" disabled={status.kind === "sending"}>
        {status.kind === "sending" ? "Sending..." : "Subscribe"}
      </button>
      {status.kind === "done" && <p className="subscribe-form__status subscribe-form__status--ok">{status.message}</p>}
      {status.kind === "error" && <p className="subscribe-form__status subscribe-form__status--error">{status.message}</p>}
    </form>
  );
}
