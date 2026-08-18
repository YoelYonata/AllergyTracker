import type { SVGProps } from "react";
import type { PollenType } from "./types";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function base({ size = 20, ...props }: IconProps) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    ...props,
  };
}

export function TreeIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 3 16 9 13.3 9 17.5 15 6.5 15 10.7 9 8 9Z" />
      <path d="M12 15V21" />
    </svg>
  );
}

export function GrassIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M8 21c0-6 1-10 1-10" />
      <path d="M12 21V7" />
      <path d="M16 21c0-6-1-10-1-10" />
    </svg>
  );
}

export function WeedIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 21V9" />
      <path d="M12 13.5c-2-.75-3-2.5-3-2.5" />
      <path d="M12 15.5c2-.75 3-2.5 3-2.5" />
      <circle cx="12" cy="6" r="2.5" />
    </svg>
  );
}

// Brand mark -- a pollen grain, distinct from the three allergen icons above.
export function LogoIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="3.5" fill="currentColor" stroke="none" />
      <path d="M12 2.5v3M12 18.5v3M21.5 12h-3M5.5 12h-3M18.01 5.99l-2.12 2.12M8.11 15.89l-2.12 2.12M18.01 18.01l-2.12-2.12M8.11 8.11 5.99 5.99" />
    </svg>
  );
}

export const POLLEN_ICONS: Record<PollenType, (props: IconProps) => React.JSX.Element> = {
  TREE: TreeIcon,
  GRASS: GrassIcon,
  WEED: WeedIcon,
};
