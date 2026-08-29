import React from "react";
import {
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { CANVAS, fonts, kickerStyle, motion as motionTable, palette } from "../theme";

/**
 * Persistent corner watermark using the real COLONY V mark.
 *
 * The previous outro drew a text circle containing the letters "CV" and the logo
 * files in the repository were never referenced by the renderer at all. The mark
 * is now a first-class asset, copied into public/ by the producer.
 */
export const Watermark: React.FC<{ logo?: string; accent: string }> = ({ logo, accent }) => {
  const frame = useCurrentFrame();
  const fade = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        top: 62,
        left: CANVAS.margin,
        display: "flex",
        alignItems: "center",
        gap: 14,
        opacity: fade * 0.9,
      }}
    >
      {logo ? (
        <Img
          src={staticFile(logo)}
          style={{
            width: 46,
            height: 46,
            objectFit: "contain",
            // The mark is a dark sphere on transparency; on paper it reads as ink.
            filter: "grayscale(1) contrast(1.1)",
          }}
        />
      ) : (
        <div style={{ width: 12, height: 12, background: accent }} />
      )}
      <span
        style={{
          fontFamily: fonts.display,
          fontSize: 24,
          fontWeight: 800,
          letterSpacing: 5.5,
          color: palette.ink,
        }}
      >
        COLONY V
      </span>
    </div>
  );
};

/**
 * Concentric rings that pulse outward from the logo. Built from four bordered
 * divs rather than many elements or SVG filters, because heavy effects were the
 * cause of earlier headless rasteriser crashes.
 */
const Rings: React.FC<{ accent: string; delay: number; size: number }> = ({
  accent,
  delay,
  size,
}) => {
  const frame = useCurrentFrame();
  const rings = [0, 1, 2, 3];

  return (
    <>
      {rings.map((i) => {
        const t = interpolate(frame - delay - i * 12, [0, 70], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const scale = interpolate(t, [0, 1], [0.55, 1.9]);
        const opacity = interpolate(t, [0, 0.25, 1], [0, 0.4, 0]);
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              width: size,
              height: size,
              left: "50%",
              top: "50%",
              marginLeft: -size / 2,
              marginTop: -size / 2,
              borderRadius: "50%",
              border: `2px solid ${accent}`,
              opacity,
              transform: `scale(${scale})`,
            }}
          />
        );
      })}
    </>
  );
};

/**
 * The outro brand moment: logo, wordmark, CTA, and channel handle.
 *
 * The call to action text comes from the script's spoken CTA so the on-screen
 * copy matches the narration, rather than the previously hardcoded
 * "SUBSCRIBE FOR DAILY BREAKTHROUGHS" string.
 */
export const BrandOutro: React.FC<{
  headline?: string;
  ctaLabel?: string;
  handle?: string;
  logo?: string;
  accent: string;
  motionKey?: string;
}> = ({ headline, ctaLabel, handle, logo, accent, motionKey }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg =
    motionTable[(motionKey as keyof typeof motionTable) in motionTable
      ? (motionKey as keyof typeof motionTable)
      : "precise"];

  const logoP = Math.max(0, Math.min(1, spring({ frame: frame - 4, fps, config: cfg.spring })));
  const headP = Math.max(0, Math.min(1, spring({ frame: frame - 18, fps, config: cfg.spring })));
  const ctaP = Math.max(0, Math.min(1, spring({ frame: frame - 32, fps, config: cfg.spring })));
  const logoSize = 260;

  return (
    <div
      style={{
        position: "absolute",
        inset: `${CANVAS.safeTop}px ${CANVAS.margin}px ${CANVAS.safeBottom}px`,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
      }}
    >
      {/* Logo with radiating rings. */}
      <div
        style={{
          position: "relative",
          width: logoSize,
          height: logoSize,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 54,
        }}
      >
        <Rings accent={accent} delay={10} size={logoSize} />
        {logo ? (
          <Img
            src={staticFile(logo)}
            style={{
              width: logoSize,
              height: logoSize,
              objectFit: "contain",
              opacity: logoP,
              transform: `scale(${interpolate(logoP, [0, 1], [0.86, 1])})`,
            }}
          />
        ) : (
          <div
            style={{
              width: logoSize * 0.6,
              height: logoSize * 0.6,
              borderRadius: "50%",
              background: palette.ink,
              opacity: logoP,
            }}
          />
        )}
      </div>

      <div
        style={{
          fontFamily: fonts.display,
          fontSize: 40,
          fontWeight: 800,
          letterSpacing: 12,
          color: palette.ink,
          opacity: logoP,
          marginBottom: 46,
        }}
      >
        COLONY V
      </div>

      {headline ? (
        <div
          style={{
            fontFamily: fonts.display,
            fontSize: 58,
            fontWeight: 800,
            letterSpacing: -1.6,
            lineHeight: 1.1,
            color: palette.ink,
            maxWidth: 840,
            opacity: headP,
            transform: `translateY(${interpolate(headP, [0, 1], [22, 0])}px)`,
          }}
        >
          {headline}
        </div>
      ) : null}

      {/* Solid accent CTA button. The one place a filled accent block is right. */}
      <div
        style={{
          marginTop: 52,
          display: "flex",
          alignItems: "center",
          gap: 16,
          background: accent,
          padding: "22px 44px",
          opacity: ctaP,
          transform: `translateY(${interpolate(ctaP, [0, 1], [18, 0])}px)`,
        }}
      >
        {/* Simple play/subscribe glyph drawn with borders, no icon font. */}
        <div
          style={{
            width: 0,
            height: 0,
            borderTop: "11px solid transparent",
            borderBottom: "11px solid transparent",
            borderLeft: `18px solid ${palette.ground}`,
          }}
        />
        <span
          style={{
            fontFamily: fonts.display,
            fontSize: 30,
            fontWeight: 800,
            letterSpacing: 3.4,
            color: palette.ground,
            textTransform: "uppercase",
          }}
        >
          {ctaLabel || "Subscribe"}
        </span>
      </div>

      {handle ? (
        <div
          style={{
            ...kickerStyle,
            marginTop: 34,
            color: palette.inkSoft,
            opacity: ctaP,
          }}
        >
          {handle}
        </div>
      ) : null}
    </div>
  );
};
