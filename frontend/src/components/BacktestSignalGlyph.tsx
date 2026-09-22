export type BacktestSignalVersion = "1.0" | "2.0";

export type DivergenceGlyphKind =
  | "happy"
  | "sad"
  | "thin-up"
  | "thin-down"
  | "wide-up"
  | "wide-down"
  | "triangle-up"
  | "triangle-down";

export const divergenceGlyphKind = (
  code: string,
  version: BacktestSignalVersion,
): DivergenceGlyphKind | null => {
  if (code.endsWith("_BOTTOM_FACE")) return "happy";
  if (code.endsWith("_TOP_FACE")) return "sad";
  if (code.endsWith("_BOTTOM_ARROW_3")) return "wide-up";
  if (code.endsWith("_TOP_ARROW_3")) return "wide-down";
  if (code.endsWith("_BOTTOM_ARROW_2")) return version === "1.0" ? "thin-up" : "triangle-up";
  if (code.endsWith("_TOP_ARROW_2")) return version === "1.0" ? "thin-down" : "triangle-down";
  return null;
};

export function DivergenceIcon({
  kind,
  version,
  size = 22,
  color: colorOverride,
}: {
  kind: DivergenceGlyphKind;
  version: BacktestSignalVersion;
  size?: number;
  color?: string;
}) {
  const color = colorOverride ?? (version === "1.0" ? "#33b1ff" : "#be95ff");
  if (kind === "happy" || kind === "sad") {
    const filled = version === "2.0";
    const featureColor = filled ? "#161b22" : color;
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="9" fill={filled ? color : "#161b22"} stroke={color} strokeWidth="2" />
        <circle cx="9" cy="10" r="1.25" fill={featureColor} />
        <circle cx="15" cy="10" r="1.25" fill={featureColor} />
        <path
          d={kind === "happy" ? "M7.5 14c1.2 2 2.7 3 4.5 3s3.3-1 4.5-3" : "M7.5 17c1.2-2 2.7-3 4.5-3s3.3 1 4.5 3"}
          stroke={featureColor}
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  if (kind === "thin-up" || kind === "thin-down") {
    const up = kind === "thin-up";
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d={up ? "M12 21V4M5 11l7-7 7 7" : "M12 3v17M5 13l7 7 7-7"}
          stroke={color}
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (kind === "wide-up" || kind === "wide-down") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill={color} aria-hidden="true">
        <path d={kind === "wide-up" ? "M12 2 22 12h-6v10H8V12H2L12 2Z" : "M8 2h8v10h6L12 22 2 12h6V2Z"} />
      </svg>
    );
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={color} aria-hidden="true">
      <path d={kind === "triangle-up" ? "M12 3 22 20H2L12 3Z" : "M2 4h20L12 21 2 4Z"} />
    </svg>
  );
}
