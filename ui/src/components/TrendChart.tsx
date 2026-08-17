import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PollenType, Reading } from "../types";
import { chrome, seriesColor } from "../theme";
import { useDarkMode } from "../useDarkMode";

const TYPE_ORDER: PollenType[] = ["TREE", "GRASS", "WEED"];
const TYPE_LABEL: Record<PollenType, string> = { TREE: "Tree", GRASS: "Grass", WEED: "Weed" };

interface ChartRow {
  date: string;
  TREE: number | null;
  GRASS: number | null;
  WEED: number | null;
}

function toChartRows(readings: Reading[]): ChartRow[] {
  return readings.map((r) => ({
    date: r.date,
    TREE: r.types.TREE?.upi ?? null,
    GRASS: r.types.GRASS?.upi ?? null,
    WEED: r.types.WEED?.upi ?? null,
  }));
}

interface TooltipPayloadItem {
  dataKey: PollenType;
  value: number | null;
  color: string;
}

function ChartTooltip({
  active,
  payload,
  label,
  ink,
  secondaryInk,
  surface,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
  ink: string;
  secondaryInk: string;
  surface: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div
      style={{
        background: surface,
        border: `1px solid ${secondaryInk}33`,
        borderRadius: 6,
        padding: "8px 12px",
        fontSize: 13,
        color: ink,
      }}
    >
      <div style={{ color: secondaryInk, marginBottom: 4 }}>{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: 4,
                background: p.color,
                display: "inline-block",
              }}
            />
            {TYPE_LABEL[p.dataKey]}
          </span>
          <span>{p.value ?? "--"}</span>
        </div>
      ))}
    </div>
  );
}

interface Props {
  readings: Reading[];
}

export function TrendChart({ readings }: Props) {
  const isDark = useDarkMode();
  const c = chrome(isDark);

  if (readings.length === 0) {
    return <div className="trend-chart trend-chart--empty">No history yet for this location.</div>;
  }

  const data = toChartRows(readings);

  return (
    <div className="trend-chart">
      <h2>Trend</h2>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 8, right: 24, bottom: 8, left: 0 }}>
          <CartesianGrid stroke={c.gridline} vertical={false} />
          <XAxis
            dataKey="date"
            stroke={c.baseline}
            tick={{ fill: c.muted, fontSize: 12 }}
            tickLine={false}
          />
          <YAxis
            domain={[0, 5]}
            allowDecimals={false}
            stroke={c.baseline}
            tick={{ fill: c.muted, fontSize: 12 }}
            tickLine={false}
            width={28}
          />
          <Tooltip
            content={
              <ChartTooltip ink={c.textPrimary} secondaryInk={c.textSecondary} surface={c.surface} />
            }
          />
          <Legend wrapperStyle={{ color: c.textSecondary, fontSize: 13 }} iconType="plainline" />
          {TYPE_ORDER.map((type) => (
            <Line
              key={type}
              type="monotone"
              dataKey={type}
              name={TYPE_LABEL[type]}
              stroke={seriesColor(type, isDark)}
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
