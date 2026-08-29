import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { CANVAS, palette, pegboard } from "../theme";
import type { TransitionKey } from "../types";

/**
 * Shot entrance transitions.
 *
 * Each transition is a short overlay or transform applied at the head of a shot.
 * They are intentionally cheap: full-frame blurs or filters between scenes were
 * the main source of dropped frames and rasteriser crashes in the previous
 * system, so nothing here uses `filter`, `backdrop-filter` or box-shadow.
 */
export const Transition: React.FC<{
  kind?: TransitionKey;
  accent: string;
  frames?: number;
  children: React.ReactNode;
}> = ({ kind = "rule_wipe", accent, frames = 16, children }) => {
  const frame = useCurrentFrame();
  const t = interpolate(frame, [0, frames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  if (kind === "cut") {
    return <>{children}</>;
  }

  if (kind === "fade") {
    return <AbsoluteFill style={{ opacity: t }}>{children}</AbsoluteFill>;
  }

  if (kind === "slide") {
    return (
      <AbsoluteFill
        style={{
          opacity: Math.min(1, t * 2),
          transform: `translateY(${interpolate(t, [0, 1], [46, 0])}px)`,
        }}
      >
        {children}
      </AbsoluteFill>
    );
  }

  if (kind === "dot_wipe") {
    // The pegboard ground sweeps down over the incoming shot, so the transition
    // is made of the same material as the page.
    return (
      <AbsoluteFill>
        {children}
        <AbsoluteFill
          style={{
            transform: `translateY(${-t * CANVAS.height}px)`,
            backgroundColor: palette.ground,
            backgroundImage: `radial-gradient(${palette.dot} ${pegboard.radius}px, transparent ${pegboard.radius}px)`,
            backgroundSize: `${pegboard.spacing}px ${pegboard.spacing}px`,
          }}
        />
      </AbsoluteFill>
    );
  }

  // rule_wipe: a hairline sweeps across and the shot resolves behind it.
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: Math.min(1, t * 1.6) }}>{children}</AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: `${t * 100}%`,
          height: 3,
          background: accent,
          opacity: t < 0.98 ? 1 : 0,
        }}
      />
    </AbsoluteFill>
  );
};
