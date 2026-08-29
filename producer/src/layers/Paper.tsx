import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { CANVAS, fonts, palette, pegboard } from "../theme";

/** Shared dot-grid layer, used by both the ground and the overlay. */
const DotGrid: React.FC<{ offset: number; opacity: number }> = ({ offset, opacity }) => (
  <div
    style={{
      position: "absolute",
      // Overscan so the drift never exposes an edge.
      inset: -pegboard.spacing * 2,
      backgroundImage: `radial-gradient(${palette.dot} ${pegboard.radius}px, transparent ${pegboard.radius}px)`,
      backgroundSize: `${pegboard.spacing}px ${pegboard.spacing}px`,
      backgroundPosition: `${offset}px ${offset * 0.6}px`,
      opacity,
    }}
  />
);

/** Drift is a pure function of the frame, so ground and overlay stay in phase. */
const driftOffset = (frame: number, drift: boolean) =>
  drift ? Math.sin(frame / 240) * 6 : 0;

/**
 * The pegboard paper ground.
 *
 * Rendered as a repeating CSS radial-gradient rather than thousands of DOM nodes
 * or an SVG pattern. Both alternatives were measured to be far slower and the
 * SVG variant caused visible flicker in headless Chromium, since the rasteriser
 * re-tiled the pattern on sub-pixel offsets between frames.
 */
export const Paper: React.FC<{
  /** Slow drift keeps the frame from feeling like a static PNG. */
  drift?: boolean;
}> = ({ drift = true }) => {
  const frame = useCurrentFrame();
  const offset = driftOffset(frame, drift);

  return (
    <AbsoluteFill style={{ backgroundColor: palette.ground }}>
      <DotGrid offset={offset} opacity={0.85} />
      {/* Paper edge shading. Keeps a pure-white frame from looking flat. */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(120% 90% at 50% 42%, transparent 45%, ${palette.paperShade} 100%)`,
        }}
      />
    </AbsoluteFill>
  );
};

/**
 * The pegboard grid, repeated *on top of* illustration plates.
 *
 * Illustrations are generated on plain paper with no grid, because a grid drawn
 * by the image model never aligned with the page's own grid — the mismatch made
 * the plate's edge visible as a seam no matter how the ground tones were matched.
 * Continuing the real grid across the plate instead makes the drawing sit on the
 * page rather than on top of it.
 *
 * Kept faint, and in phase with `Paper` because both derive their offset from
 * the same function of the frame.
 */
export const PegboardOverlay: React.FC<{ drift?: boolean; opacity?: number }> = ({
  drift = true,
  opacity = 0.5,
}) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <DotGrid offset={driftOffset(frame, drift)} opacity={opacity} />
    </AbsoluteFill>
  );
};

/**
 * Registration marks in the corners, like a print proof. Small, static, and
 * cheap — they do a lot of work selling the "technical document" identity.
 */
export const RegistrationMarks: React.FC<{ accent: string }> = ({ accent }) => {
  const size = 26;
  const inset = 46;
  const corners = [
    { top: inset, left: inset },
    { top: inset, right: inset },
    { bottom: inset, left: inset },
    { bottom: inset, right: inset },
  ];

  return (
    <>
      {corners.map((pos, i) => (
        <div key={i} style={{ position: "absolute", ...pos, width: size, height: size }}>
          <div
            style={{
              position: "absolute",
              top: size / 2,
              left: 0,
              width: size,
              height: 1,
              background: i === 0 ? accent : palette.rule,
            }}
          />
          <div
            style={{
              position: "absolute",
              left: size / 2,
              top: 0,
              width: 1,
              height: size,
              background: i === 0 ? accent : palette.rule,
            }}
          />
        </div>
      ))}
    </>
  );
};

/**
 * Horizontal progress rule along the very top of the frame. Communicates
 * position in the video without a chrome-heavy progress bar.
 */
export const ProgressRule: React.FC<{ progress: number; accent: string }> = ({
  progress,
  accent,
}) => (
  <div
    style={{
      position: "absolute",
      top: 0,
      left: 0,
      right: 0,
      height: 5,
      background: palette.groundSunk,
    }}
  >
    <div
      style={{
        height: "100%",
        width: `${Math.max(0, Math.min(1, progress)) * 100}%`,
        background: accent,
      }}
    />
  </div>
);

/**
 * A drawn hairline that animates open. Used as a structural divider between the
 * kicker and the headline, and as the `rule_wipe` transition's residue.
 */
export const DrawnRule: React.FC<{
  width: number;
  delay?: number;
  duration?: number;
  color?: string;
  thickness?: number;
}> = ({ width, delay = 0, duration = 16, color = palette.ink, thickness = 2 }) => {
  const frame = useCurrentFrame();
  const grown = interpolate(frame - delay, [0, duration], [0, width], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        width: grown,
        height: thickness,
        background: color,
        borderRadius: thickness,
      }}
    />
  );
};

export const contentWidth = CANVAS.width - CANVAS.margin * 2;

/**
 * Page footer, in the manner of a technical manual: a hairline, a sheet index,
 * and the document's subject.
 *
 * Beyond the brand fit, this solves a real compositional problem. Content-light
 * layouts (a two-item comparison, a short node chain) previously occupied only
 * the top third of a 1920px frame and left the rest empty, which read as an
 * unfinished slide. Anchoring the composition at both ends makes the negative
 * space deliberate instead of accidental.
 */
export const Footer: React.FC<{
  index: number;
  total: number;
  label?: string;
  accent: string;
  delay?: number;
}> = ({ index, total, label, accent, delay = 10 }) => {
  const frame = useCurrentFrame();
  const fade = interpolate(frame - delay, [0, 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        left: CANVAS.margin,
        right: CANVAS.margin,
        bottom: 92,
        opacity: fade * 0.95,
      }}
    >
      <div style={{ height: 1, background: palette.rule, marginBottom: 18 }} />
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span
          style={{
            fontFamily: fonts.mono,
            fontSize: 20,
            fontWeight: 500,
            letterSpacing: 2.6,
            color: palette.inkFaint,
            textTransform: "uppercase",
          }}
        >
          {label || "Editorial brief"}
        </span>
        <span
          style={{
            fontFamily: fonts.mono,
            fontSize: 20,
            fontWeight: 600,
            letterSpacing: 2.6,
            color: accent,
          }}
        >
          {String(index).padStart(2, "0")} / {String(total).padStart(2, "0")}
        </span>
      </div>
    </div>
  );
};
