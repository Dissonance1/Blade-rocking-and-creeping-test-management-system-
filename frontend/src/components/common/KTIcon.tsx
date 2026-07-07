import { cn } from "@/utils/cn";

export type KeenIconType = "outline" | "solid" | "duotone";

interface KTIconProps {
  iconName: string;
  iconType?: KeenIconType;
  className?: string;
}

/**
 * Renders a Keenicons glyph (the icon font vendored under src/assets/keenicons/).
 * Size/color follow the standard font-icon convention — control them via
 * Tailwind text-size and text-color utilities on className (e.g. "text-lg text-slate-500").
 */
export default function KTIcon({ iconName, iconType = "outline", className }: KTIconProps) {
  return <i className={cn(`ki-${iconType}`, `ki-${iconName}`, className)} />;
}
