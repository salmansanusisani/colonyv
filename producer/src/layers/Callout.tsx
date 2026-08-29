import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { CANVAS, fonts, palette, stateColor } from "../theme";
import type { Annotation } from "../types";

const POSITIONS: Record<
  NonNullable<Annotation["at"]>,
  { top?: number; bottom?: number; left?: number; right?: number; dir: 1 | -1 }
> = {
  top_left: { top: 430, left: CANVAS.margin, dir: 1 },
  top_right: { top: 430, right: CANVAS.margin, dir: -1 },
  mid_left: { top: 900, left: CANVAS.margin, dir: 1 },
  mid_right: { top: 900, right: CANVAS.margin, dir: -1 },
  bottom_left: { bottom: 470, left: CANVAS.margin, dir: 1 },
  bottom_right: { bottom: 470, right: CANVAS.margin, dir: -1 },
};

/**
 * A callout note with a drawn leader line, in the manner of an annotated
 * technical drawing. Points into the illustration to name the thing that matters.
 *
 * The leader draws first, then a dot lands, then the label types in — the same
 * order a draughtsperson would work.
 */
export const Callout: React.FC<{
  annotation: Annotation;
  accent: string;
  delay?: number;
}> = ({ annotation, accent, delay = 0 }) => {
  const frame = useCurrentFrame();
  const pos = POSITIONS[annotation.at ?? "mid_right"] ?? POSITIONS.mid_right;
  const color = stateColor(annotation.state, accent);

  const leader = interpolate(frame - delay, [0, 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const label = interpolate(frame - delay - 8, [0, 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const leaderLength = 86;

  return (
    <div
      style={{
        position: "absolute",
        top: pos.top,
        bottom: pos.bottom,
        left: pos.left,
        right: pos.right,
        display: "flex",
        flexDirection: pos.dir === 1 ? "row" : "row-reverse",
        alignItems: "center",
        gap: 0,
      }}
    >
      {/* Terminal dot on the subject. */}
      <div
        style={{
          width: 11,
          height: 11,
          borderRadius: "50%",
          background: color,
          transform: `scale(${leader})`,
          flexShrink: 0,
        }}
      />
      {/* Leader line. */}
      <div
        style={{
          width: leaderLength * leader,
          height: 1.5,
          background: color,
          flexShrink: 0,
        }}
      />
      {/* Label sits on a paper chip so it stays legible over artwork. */}
      <div
        style={{
          opacity: label,
          transform: `translateX(${interpolate(label, [0, 1], [pos.dir * -10, 0])}px)`,
          background: palette.ground,
          borderBottom: `2px solid ${color}`,
          padding: "8px 14px 7px",
          whiteSpace: "nowrap",
        }}
      >
        <span
          style={{
            fontFamily: fonts.mono,
            fontSize: 24,
            fontWeight: 600,
            letterSpacing: 0.6,
            color: palette.ink,
          }}
        >
          {annotation.text}
        </span>
      </div>
    </div>
  );
};

export const Callouts: React.FC<{
  annotations?: Annotation[];
  accent: string;
  delay?: number;
}> = ({ annotations, accent, delay = 22 }) => {
  if (!annotations?.length) return null;
  return (
    <>
      {annotations.map((annotation, i) => (
        <Callout
          key={`${annotation.text}-${i}`}
          annotation={annotation}
          accent={accent}
          delay={delay + i * 10}
        />
      ))}
    </>
  );
};
