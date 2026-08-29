import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { fonts, kickerStyle, motion as motionTable, palette, stateColor } from "../theme";
import type { MotionKey } from "../theme";
import type { DataReadout as DataSpec } from "../types";

const cfgFor = (key?: string) =>
  motionTable[(key as MotionKey) in motionTable ? (key as MotionKey) : "precise"];

/**
 * Split a director-supplied figure into an animatable number and its literal
 * formatting, preserving thousands separators and decimal places exactly as
 * spoken.
 *
 * The previous implementation regex-scanned the whole narration for any digit
 * run, which happily animated years ("2026") and phone-number-like fragments as
 * if they were the story's key statistic. Figures now come from the plan, where
 * the Art Director has already committed to what the number means.
 */
const parseFigure = (raw: string | undefined) => {
  const text = String(raw ?? "").trim();
  const match = text.match(/^([^\d-]*)(-?[\d][\d,\s]*(?:\.\d+)?)(.*)$/);
  if (!match) return null;

  const digits = match[2].replace(/[\s,]/g, "");
  const value = Number.parseFloat(digits);
  if (!Number.isFinite(value)) return null;

  const decimals = digits.includes(".") ? digits.split(".")[1].length : 0;
  const grouped = /[,\s]/.test(match[2]);

  return {
    leading: match[1] ?? "",
    value,
    trailing: match[3] ?? "",
    decimals,
    grouped,
  };
};

const formatValue = (
  current: number,
  decimals: number,
  grouped: boolean,
): string => {
  if (decimals > 0) {
    return current.toLocaleString("en-US", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
      useGrouping: grouped,
    });
  }
  return Math.round(current).toLocaleString("en-US", { useGrouping: grouped });
};

/**
 * Animated numeric readout. Counts up once, settles, and never overshoots the
 * target — an overshooting counter reads as a bug on a factual statistic.
 */
export const Readout: React.FC<{
  data: DataSpec;
  accent: string;
  delay?: number;
  motionKey?: string;
}> = ({ data, accent, delay = 6, motionKey }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const figure = parseFigure(data.value);

  // Over-damped so a factual figure never wobbles, but stiff enough to reach
  // its target in well under a second. A count-up that is still climbing when
  // the narrator has moved on shows the viewer a number that is simply wrong.
  const raw = spring({
    frame: frame - delay,
    fps,
    config: { damping: 200, stiffness: 150, mass: 0.7 },
    durationInFrames: 20,
  });
  // Snap the tail so the final glyphs settle on the exact value.
  const p = raw > 0.999 ? 1 : Math.max(0, Math.min(1, raw));

  const display = figure
    ? formatValue(figure.value * p, figure.decimals, figure.grouped)
    : String(data.value ?? "");

  const prefix = data.prefix || figure?.leading || "";
  const suffix = data.suffix || figure?.trailing || "";

  // Long figures need a smaller face to stay on one line inside the margin.
  const glyphs = (prefix + display + suffix).length;
  const size = glyphs > 12 ? 150 : glyphs > 8 ? 190 : 236;

  const enter = Math.max(0, Math.min(1, spring({ frame: frame - delay, fps, config: cfgFor(motionKey).spring })));

  return (
    <div style={{ opacity: enter, transform: `translateY(${interpolate(enter, [0, 1], [22, 0])}px)` }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          fontFamily: fonts.display,
          fontWeight: 800,
          color: palette.ink,
          lineHeight: 0.92,
          letterSpacing: -size * 0.045,
        }}
      >
        {prefix ? (
          <span style={{ fontSize: size * 0.52, color: accent, marginRight: size * 0.03 }}>
            {prefix}
          </span>
        ) : null}
        <span
          style={{
            fontSize: size,
            // Tabular figures stop the layout jittering as digits change width.
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {display}
        </span>
        {suffix ? (
          <span style={{ fontSize: size * 0.4, color: accent, marginLeft: size * 0.05 }}>
            {suffix}
          </span>
        ) : null}
      </div>

      {data.label ? (
        <div
          style={{
            ...kickerStyle,
            color: palette.inkSoft,
            marginTop: 22,
            letterSpacing: 3.2,
            opacity: interpolate(frame - delay - 10, [0, 12], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          {data.label}
        </div>
      ) : null}

      {data.trend ? <TrendMark trend={data.trend} accent={accent} delay={delay + 16} /> : null}
    </div>
  );
};

const TrendMark: React.FC<{ trend: "up" | "down" | "flat"; accent: string; delay: number }> = ({
  trend,
  accent,
  delay,
}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame - delay, [0, 14], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rotation = trend === "up" ? -45 : trend === "down" ? 45 : 0;

  return (
    <div style={{ marginTop: 28, display: "flex", alignItems: "center", gap: 16, opacity: p }}>
      <div style={{ width: interpolate(p, [0, 1], [0, 92]), height: 3, background: accent }} />
      <div
        style={{
          width: 20,
          height: 20,
          borderTop: `3px solid ${accent}`,
          borderRight: `3px solid ${accent}`,
          transform: `rotate(${rotation}deg) scale(${p})`,
        }}
      />
    </div>
  );
};

/**
 * A vertical chain of director-authored nodes with a drawn connector.
 *
 * The old DiagramScene split the narration string in half by word count and put
 * each half in a box, which produced meaningless pairs like "Berkeley launched a
 * new" -> "two-semester AI degree program". Nodes are now explicit plan data, so
 * a diagram only appears when there is a real relationship to draw.
 */
export const NodeFlow: React.FC<{
  nodes: { label?: string; detail?: string; state?: "neutral" | "good" | "bad" }[];
  accent: string;
  delay?: number;
  motionKey?: string;
  width?: number;
}> = ({ nodes, accent, delay = 0, motionKey, width }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = cfgFor(motionKey);
  const step = 13;

  return (
    <div style={{ display: "flex", flexDirection: "column", width }}>
      {nodes.map((node, i) => {
        const at = delay + i * step;
        const p = Math.max(0, Math.min(1, spring({ frame: frame - at, fps, config: cfg.spring })));
        const color = stateColor(node.state, accent);
        const emphasised = node.state === "good" || node.state === "bad";

        // Connector grows between the previous node and this one.
        const linkP =
          i === 0
            ? 0
            : interpolate(frame - (at - step * 0.45), [0, 12], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              });

        return (
          <React.Fragment key={`${node.label}-${i}`}>
            {i > 0 ? (
              <div style={{ height: 46, marginLeft: 27, display: "flex", alignItems: "flex-start" }}>
                <div style={{ width: 2, height: 46 * linkP, background: palette.rule }} />
              </div>
            ) : null}

            <div
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 24,
                opacity: p,
                transform: `translateX(${interpolate(p, [0, 1], [-22, 0])}px)`,
              }}
            >
              {/* Index chip. Filled when the node carries a semantic state. */}
              <div
                style={{
                  width: 56,
                  height: 56,
                  flexShrink: 0,
                  border: `2px solid ${color}`,
                  background: emphasised ? color : "transparent",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: fonts.mono,
                  fontSize: 22,
                  fontWeight: 600,
                  color: emphasised ? palette.ground : color,
                }}
              >
                {String(i + 1).padStart(2, "0")}
              </div>

              <div style={{ paddingTop: 2 }}>
                <div
                  style={{
                    fontFamily: fonts.display,
                    fontSize: 44,
                    fontWeight: 700,
                    letterSpacing: -1.1,
                    lineHeight: 1.14,
                    color: palette.ink,
                  }}
                >
                  {node.label}
                </div>
                {node.detail ? (
                  <div
                    style={{
                      fontFamily: fonts.mono,
                      fontSize: 24,
                      fontWeight: 500,
                      color: palette.inkFaint,
                      marginTop: 10,
                      letterSpacing: 0.4,
                    }}
                  >
                    {node.detail}
                  </div>
                ) : null}
              </div>
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
};

/**
 * Two panels set against each other, divided by a drawn rule. Used when the
 * story is genuinely a comparison.
 */
export const CompareTwoUp: React.FC<{
  nodes: { label?: string; detail?: string; state?: "neutral" | "good" | "bad" }[];
  accent: string;
  delay?: number;
  motionKey?: string;
}> = ({ nodes, accent, delay = 0, motionKey }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = cfgFor(motionKey);
  const pair = nodes.slice(0, 2);
  const divider = interpolate(frame - delay - 6, [0, 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div style={{ position: "relative", display: "flex", flexDirection: "column", gap: 74 }}>
      {pair.map((node, i) => {
        const p = Math.max(
          0,
          Math.min(1, spring({ frame: frame - delay - i * 14, fps, config: cfg.spring })),
        );
        const color = stateColor(node.state, accent);

        return (
          <React.Fragment key={`${node.label}-${i}`}>
            {i === 1 ? (
              <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
                <div style={{ height: 2, width: `${divider * 100}%`, background: palette.rule }} />
                <span
                  style={{
                    ...kickerStyle,
                    fontSize: 18,
                    color: palette.inkFaint,
                    opacity: divider,
                    whiteSpace: "nowrap",
                  }}
                >
                  versus
                </span>
              </div>
            ) : null}

            <div
              style={{
                opacity: p,
                transform: `translateY(${interpolate(p, [0, 1], [26, 0])}px)`,
              }}
            >
              <div
                style={{
                  fontFamily: fonts.display,
                  fontSize: 76,
                  fontWeight: 800,
                  letterSpacing: -2.2,
                  lineHeight: 1.06,
                  color: node.state && node.state !== "neutral" ? color : palette.ink,
                }}
              >
                {node.label}
              </div>
              {node.detail ? (
                <div
                  style={{
                    fontFamily: fonts.mono,
                    fontSize: 30,
                    color: palette.inkSoft,
                    marginTop: 16,
                    letterSpacing: 0.4,
                  }}
                >
                  {node.detail}
                </div>
              ) : null}
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
};

/**
 * Timeline rail. The vertical rule draws itself, then markers land on it in
 * sequence.
 */
export const TimelineRail: React.FC<{
  events: { label?: string; marker?: string; state?: "neutral" | "good" | "bad" }[];
  accent: string;
  delay?: number;
  motionKey?: string;
}> = ({ events, accent, delay = 0, motionKey }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = cfgFor(motionKey);
  const step = 15;
  const railP = interpolate(frame - delay, [0, events.length * step + 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div style={{ position: "relative", paddingLeft: 54 }}>
      {/* The rail itself. */}
      <div
        style={{
          position: "absolute",
          left: 15,
          top: 12,
          bottom: 12,
          width: 2,
          background: palette.rule,
        }}
      >
        <div style={{ width: "100%", height: `${railP * 100}%`, background: accent }} />
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 46 }}>
        {events.map((event, i) => {
          const at = delay + i * step;
          const p = Math.max(0, Math.min(1, spring({ frame: frame - at, fps, config: cfg.spring })));
          const color = stateColor(event.state, accent);

          return (
            <div
              key={`${event.label}-${i}`}
              style={{
                position: "relative",
                opacity: p,
                transform: `translateX(${interpolate(p, [0, 1], [20, 0])}px)`,
              }}
            >
              {/* Marker dot, centred on the rail. */}
              <div
                style={{
                  position: "absolute",
                  left: -54 + 16 - 11,
                  top: 12,
                  width: 22,
                  height: 22,
                  borderRadius: "50%",
                  background: palette.ground,
                  border: `3px solid ${color}`,
                  transform: `scale(${p})`,
                }}
              />
              {event.marker ? (
                <div
                  style={{
                    fontFamily: fonts.mono,
                    fontSize: 22,
                    fontWeight: 600,
                    letterSpacing: 2.4,
                    color,
                    marginBottom: 8,
                    textTransform: "uppercase",
                  }}
                >
                  {event.marker}
                </div>
              ) : null}
              <div
                style={{
                  fontFamily: fonts.display,
                  fontSize: 44,
                  fontWeight: 700,
                  letterSpacing: -1.1,
                  lineHeight: 1.14,
                  color: palette.ink,
                }}
              >
                {event.label}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
