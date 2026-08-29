import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { fonts, kickerStyle, palette, typeScale } from "../theme";
import type { MotionKey } from "../theme";
import { motion as motionTable } from "../theme";
import { DrawnRule } from "./Paper";

const normalise = (word: string) => word.replace(/[^\p{L}\p{N}$%.,-]/gu, "").toLowerCase();

/**
 * Build a matcher for the director's `emphasis_words`.
 *
 * Emphasis is matched on a normalised form so that "$84,000" in the plan still
 * lights up "$84,000." in the headline, and multi-word phrases are expanded into
 * their constituent tokens.
 */
const buildEmphasis = (words: string[] | undefined): Set<string> => {
  const set = new Set<string>();
  for (const phrase of words ?? []) {
    for (const token of String(phrase).split(/\s+/)) {
      const clean = normalise(token);
      if (clean.length > 1) set.add(clean);
    }
  }
  return set;
};

/**
 * The kicker: a small monospaced eyebrow label.
 *
 * The text is always authored by the Art Director for this specific story. The
 * previous system hardcoded labels like "KEY TAKEAWAY" into every scene, which
 * is exactly what made every video feel identical.
 */
export const Kicker: React.FC<{
  text: string;
  accent: string;
  delay?: number;
  motionKey?: string;
}> = ({ text, accent, delay = 0, motionKey }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = motionTable[(motionKey as MotionKey) in motionTable ? (motionKey as MotionKey) : "precise"];
  const p = Math.max(0, Math.min(1, spring({ frame: frame - delay, fps, config: cfg.spring })));

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        opacity: p,
        transform: `translateX(${interpolate(p, [0, 1], [-16, 0])}px)`,
        marginBottom: 26,
      }}
    >
      <div style={{ width: 12, height: 12, background: accent }} />
      <span style={{ ...kickerStyle, color: palette.inkSoft }}>{text}</span>
    </div>
  );
};

/**
 * Headline with staggered per-word entrance and accent emphasis.
 *
 * Words animate individually rather than the block as a whole, which reads as
 * deliberate typesetting rather than a generic fade.
 */
export const Headline: React.FC<{
  text: string;
  accent: string;
  scale?: keyof typeof typeScale;
  emphasis?: string[];
  delay?: number;
  motionKey?: string;
  align?: "left" | "center";
  maxWidth?: number;
}> = ({
  text,
  accent,
  scale = "lg",
  emphasis,
  delay = 0,
  motionKey,
  align = "left",
  maxWidth,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = motionTable[(motionKey as MotionKey) in motionTable ? (motionKey as MotionKey) : "precise"];
  const band = typeScale[scale] ?? typeScale.lg;
  const emphasised = buildEmphasis(emphasis);
  const words = String(text || "").split(/\s+/).filter(Boolean);

  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        justifyContent: align === "center" ? "center" : "flex-start",
        gap: `${Math.round(band.size * 0.12)}px ${Math.round(band.size * 0.22)}px`,
        maxWidth,
      }}
    >
      {words.map((word, i) => {
        const p = Math.max(
          0,
          Math.min(1, spring({ frame: frame - delay - i * cfg.stagger, fps, config: cfg.spring })),
        );
        const hot = emphasised.has(normalise(word));
        return (
          <span
            key={`${word}-${i}`}
            style={{
              display: "inline-block",
              fontFamily: fonts.display,
              fontSize: band.size,
              fontWeight: band.weight,
              letterSpacing: band.tracking,
              lineHeight: band.leading,
              color: hot ? accent : palette.ink,
              opacity: p,
              transform: `translateY(${interpolate(p, [0, 1], [band.size * 0.22, 0])}px)`,
            }}
          >
            {word}
          </span>
        );
      })}
    </div>
  );
};

/**
 * Kicker + rule + headline as one aligned block. This is the standard type
 * treatment reused by nearly every layout, which is what keeps typography
 * consistent while structure varies.
 */
export const CopyBlock: React.FC<{
  kicker?: string;
  headline?: string;
  accent: string;
  scale?: keyof typeof typeScale;
  emphasis?: string[];
  motionKey?: string;
  align?: "left" | "center";
  maxWidth?: number;
  delay?: number;
  rule?: boolean;
}> = ({
  kicker,
  headline,
  accent,
  scale = "lg",
  emphasis,
  motionKey,
  align = "left",
  maxWidth,
  delay = 0,
  rule = true,
}) => (
  <div
    style={{
      display: "flex",
      flexDirection: "column",
      alignItems: align === "center" ? "center" : "flex-start",
    }}
  >
    {kicker ? (
      <Kicker text={kicker} accent={accent} delay={delay} motionKey={motionKey} />
    ) : null}
    {rule && kicker ? (
      <div style={{ marginBottom: 30 }}>
        <DrawnRule width={maxWidth ?? 300} delay={delay + 3} color={palette.rule} thickness={1} />
      </div>
    ) : null}
    {headline ? (
      <Headline
        text={headline}
        accent={accent}
        scale={scale}
        emphasis={emphasis}
        delay={delay + (kicker ? 5 : 0)}
        motionKey={motionKey}
        align={align}
        maxWidth={maxWidth}
      />
    ) : null}
  </div>
);

/**
 * Pull-quote treatment. Uses a heavy left rule and optical hanging punctuation
 * rather than a decorative quote glyph.
 */
export const QuoteBlock: React.FC<{
  text: string;
  accent: string;
  scale?: keyof typeof typeScale;
  motionKey?: string;
  maxWidth?: number;
  delay?: number;
}> = ({ text, accent, scale = "md", motionKey, maxWidth, delay = 0 }) => {
  const frame = useCurrentFrame();
  const band = typeScale[scale] ?? typeScale.md;
  const grow = interpolate(frame - delay, [0, 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div style={{ display: "flex", gap: 34, maxWidth }}>
      <div
        style={{
          width: 6,
          background: accent,
          transformOrigin: "top",
          transform: `scaleY(${grow})`,
          flexShrink: 0,
        }}
      />
      <div style={{ paddingTop: 4 }}>
        <Headline
          text={`\u201C${text}\u201D`}
          accent={accent}
          scale={scale}
          delay={delay + 4}
          motionKey={motionKey}
          maxWidth={maxWidth ? maxWidth - 40 : undefined}
        />
      </div>
    </div>
  );
};
