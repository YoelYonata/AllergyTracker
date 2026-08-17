import type { PollenType } from "./types";

// Categorical slots 1-3 from the validated default palette (see the dataviz skill's
// references/palette.md) -- the only three that pass every CVD/contrast gate together
// in both light and dark, so a 4th pollen type would need its own re-validation, not
// just the next hue in the ramp.
export const POLLEN_COLORS: Record<PollenType, { light: string; dark: string }> = {
  TREE: { light: "#2a78d6", dark: "#3987e5" },
  GRASS: { light: "#eb6834", dark: "#d95926" },
  WEED: { light: "#1baf7a", dark: "#199e70" },
};

export const CHROME = {
  light: {
    surface: "#fcfcfb",
    page: "#f9f9f7",
    textPrimary: "#0b0b0b",
    textSecondary: "#52514e",
    muted: "#898781",
    gridline: "#e1e0d9",
    baseline: "#c3c2b7",
  },
  dark: {
    surface: "#1a1a19",
    page: "#0d0d0d",
    textPrimary: "#ffffff",
    textSecondary: "#c3c2b7",
    muted: "#898781",
    gridline: "#2c2c2a",
    baseline: "#383835",
  },
};

export function seriesColor(type: PollenType, isDark: boolean): string {
  return isDark ? POLLEN_COLORS[type].dark : POLLEN_COLORS[type].light;
}

export function chrome(isDark: boolean) {
  return isDark ? CHROME.dark : CHROME.light;
}
