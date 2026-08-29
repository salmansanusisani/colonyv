import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { palette } from "../theme";
import type { IllustrationMotion } from "../types";

/**
 * Camera treatment for an illustration plate.
 *
 * Every transform is clamped and bounded. Unbounded interpolation over long
 * beats previously pushed scale high enough to blow out Chromium's rasteriser
 * on 1080x1920 plates, which is what produced the intermittent render crashes.
 */
const cameraFor = (
  motion: IllustrationMotion | undefined,
  frame: number,
  duration: number,
) => {
  const t = duration <= 1 ? 0 : Math.max(0, Math.min(1, frame / duration));

  switch (motion) {
    case "still":
      return { scale: 1.02, x: 0, y: 0 };
    case "drift":
      return {
        scale: 1.06,
        x: Math.sin(frame / 150) * 14,
        y: Math.cos(frame / 190) * 10,
      };
    case "pull_out":
      return { scale: interpolate(t, [0, 1], [1.14, 1.02]), x: 0, y: 0 };
    case "parallax":
      return {
        scale: 1.08,
        x: interpolate(t, [0, 1], [-18, 18]),
        y: interpolate(t, [0, 1], [8, -8]),
      };
    case "push_in":
    default:
      return { scale: interpolate(t, [0, 1], [1.02, 1.12]), x: 0, y: 0 };
  }
};

/**
 * Full-bleed illustration.
 *
 * Because the generated art carries the same paper + pegboard ground as the
 * canvas, a full-bleed plate reads as ink drawn directly on the page. No frame,
 * no border, no shadow — those would break the illusion.
 */
export const PlateFull: React.FC<{
  file: string;
  duration: number;
  motion?: IllustrationMotion;
  /** Fade the art back so overlaid type stays legible. */
  recede?: number;
  delay?: number;
}> = ({ file, duration, motion, recede = 0, delay = 0 }) => {
  const frame = useCurrentFrame();
  const cam = cameraFor(motion, frame, duration);
  const reveal = interpolate(frame - delay, [0, 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ opacity: reveal * (1 - recede) }}>
      <Img
        src={staticFile(file)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${cam.scale}) translate(${cam.x}px, ${cam.y}px)`,
        }}
      />
      {recede > 0 && (
        <AbsoluteFill style={{ background: palette.ground, opacity: recede * 0.55 }} />
      )}
    </AbsoluteFill>
  );
};

/**
 * Illustration occupying a horizontal band of the frame, with the rest left as
 * clean paper for type.
 *
 * The plate for a band layout is generated at roughly the band's own aspect
 * ratio (square for a top band, 5:4 for a foot band), so it fills the band with
 * almost no cropping and the model's composition survives. The paper ground
 * continues seamlessly past the band edge because the plate's ground has been
 * tone-matched to the canvas.
 */
export const PlateBand: React.FC<{
  file: string;
  duration: number;
  motion?: IllustrationMotion;
  region: "top" | "bottom";
  /** Fraction of frame height the art occupies. */
  extent?: number;
  delay?: number;
}> = ({ file, duration, motion, region, extent = 0.56, delay = 0 }) => {
  const frame = useCurrentFrame();
  const cam = cameraFor(motion, frame, duration);
  const reveal = interpolate(frame - delay, [0, 20], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rise = interpolate(reveal, [0, 1], [26, 0]);

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        height: `${extent * 100}%`,
        ...(region === "top" ? { top: 0 } : { bottom: 0 }),
        overflow: "hidden",
        opacity: reveal,
        transform: `translateY(${region === "top" ? -rise : rise}px)`,
      }}
    >
      <Img
        src={staticFile(file)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          objectPosition: region === "top" ? "center top" : "center bottom",
          transform: `scale(${cam.scale}) translate(${cam.x}px, ${cam.y}px)`,
        }}
      />
    </div>
  );
};

/**
 * Illustration as a contained block on one side of the frame, type on the other.
 *
 * `contain` rather than `cover` is essential here. The side column is far taller
 * than it is wide, so cover-cropping a drawing to fill it magnified a narrow
 * vertical sliver of the plate — in practice usually empty paper, leaving the
 * shot looking blank. The plate is generated at 3:4 for this layout and is shown
 * whole, vertically centred.
 */
export const PlateSide: React.FC<{
  file: string;
  duration: number;
  motion?: IllustrationMotion;
  side: "left" | "right";
  extent?: number;
  delay?: number;
}> = ({ file, duration, motion, side, extent = 0.44, delay = 0 }) => {
  const frame = useCurrentFrame();
  const cam = cameraFor(motion, frame, duration);
  const reveal = interpolate(frame - delay, [0, 20], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const slide = interpolate(reveal, [0, 1], [34, 0]);

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        bottom: 0,
        width: `${extent * 100}%`,
        ...(side === "left" ? { left: 0 } : { right: 0 }),
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        opacity: reveal,
        transform: `translateX(${side === "left" ? -slide : slide}px)`,
      }}
    >
      <Img
        src={staticFile(file)}
        style={{
          width: "104%",
          maxHeight: "84%",
          objectFit: "contain",
          transform: `scale(${cam.scale}) translate(${cam.x}px, ${cam.y}px)`,
        }}
      />
    </div>
  );
};
