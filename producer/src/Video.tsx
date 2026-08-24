import React from "react";
import {
  AbsoluteFill,
  Sequence,
  Audio,
  Img,
  staticFile,
  useCurrentFrame,
  interpolate,
  spring,
} from "remotion";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadOutfit } from "@remotion/google-fonts/Outfit";
import timing from "./timing.json";

const { fontFamily: fontBody } = loadInter();
const { fontFamily: fontDisplay } = loadOutfit();

const { hookFrames, outroFrames, beats } = timing as {
  hookFrames: number;
  outroFrames: number;
  beats: Record<string, number>;
};

const bodyFrames: number = Object.values(beats).reduce(
  (a: number, b: number) => a + b,
  0
);
const totalVideoFrames: number = hookFrames + bodyFrames + outroFrames;
const beatKeys: string[] = Object.keys(beats);

// Design Tokens & Palette
const CYAN = "#00f2fe";
const BLUE = "#4facfe";
const MAGENTA = "#ff0844";
const PURPLE = "#7f00ff";
const GOLD = "#f6d365";
const DARK_BG = "#07090e";
const GLASS_BG = "rgba(15, 22, 36, 0.75)";
const WHITE = "#FFFFFF";
const LIGHT_GRAY = "#CBD5E1";
const MUTED_GRAY = "#64748B";

// Helpers
export const fadeByFraction = (
  frame: number,
  duration: number,
  inFrac = 0.08,
  outFrac = 0.9
) => {
  const inEnd = Math.max(1, duration * inFrac);
  const outStart = Math.min(duration - 1, duration * outFrac);
  const safeOutStart = Math.max(outStart, inEnd + 1);
  const inV = interpolate(frame, [0, inEnd], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const outV = interpolate(
    frame,
    [safeOutStart, Math.max(safeOutStart + 1, duration)],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  return Math.min(inV, outV);
};

// 1. Dynamic Animated Ambient Backdrop
const DynamicBackdrop: React.FC = () => {
  const frame = useCurrentFrame();

  // Floating ambient light spheres
  const orb1X = 50 + Math.sin(frame / 45) * 25;
  const orb1Y = 20 + Math.cos(frame / 60) * 15;
  const orb2X = 80 + Math.cos(frame / 50) * 20;
  const orb2Y = 70 + Math.sin(frame / 40) * 20;
  const orb3X = 20 + Math.sin(frame / 35) * 15;
  const orb3Y = 80 + Math.cos(frame / 55) * 15;

  return (
    <AbsoluteFill style={{ backgroundColor: DARK_BG, overflow: "hidden" }}>
      {/* Orb 1: Cyan Glow */}
      <div
        style={{
          position: "absolute",
          top: `${orb1Y}%`,
          left: `${orb1X}%`,
          width: 700,
          height: 700,
          borderRadius: "50%",
          background: `radial-gradient(circle, rgba(0,242,254,0.18) 0%, rgba(0,0,0,0) 70%)`,
          transform: "translate(-50%, -50%)",
          filter: "blur(60px)",
        }}
      />
      {/* Orb 2: Purple Glow */}
      <div
        style={{
          position: "absolute",
          top: `${orb2Y}%`,
          left: `${orb2X}%`,
          width: 800,
          height: 800,
          borderRadius: "50%",
          background: `radial-gradient(circle, rgba(127,0,255,0.16) 0%, rgba(0,0,0,0) 70%)`,
          transform: "translate(-50%, -50%)",
          filter: "blur(80px)",
        }}
      />
      {/* Orb 3: Magenta Accent */}
      <div
        style={{
          position: "absolute",
          top: `${orb3Y}%`,
          left: `${orb3X}%`,
          width: 600,
          height: 600,
          borderRadius: "50%",
          background: `radial-gradient(circle, rgba(255,8,68,0.12) 0%, rgba(0,0,0,0) 70%)`,
          transform: "translate(-50%, -50%)",
          filter: "blur(70px)",
        }}
      />

      {/* Cyber Grid */}
      <svg
        width="100%"
        height="100%"
        style={{ position: "absolute", opacity: 0.05 }}
      >
        <defs>
          <pattern
            id="cyber-grid"
            width="80"
            height="80"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M 80 0 L 0 0 0 80"
              fill="none"
              stroke={WHITE}
              strokeWidth="1.5"
            />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#cyber-grid)" />
      </svg>

      {/* Vignette Overlay */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(circle at 50% 50%, rgba(7,9,14,0.2) 0%, rgba(7,9,14,0.85) 100%)",
        }}
      />
    </AbsoluteFill>
  );
};

// 2. Persistent Header Bar & Video Progress Bar
const HeaderBar: React.FC<{ currentGlobalFrame: number }> = ({
  currentGlobalFrame,
}) => {
  const progressPercent = Math.min(
    100,
    Math.max(0, (currentGlobalFrame / totalVideoFrames) * 100)
  );

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 100,
        padding: "60px 50px 0 50px",
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      {/* Top Video Progress Bar */}
      <div
        style={{
          width: "100%",
          height: 6,
          backgroundColor: "rgba(255, 255, 255, 0.12)",
          borderRadius: 3,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${progressPercent}%`,
            background: `linear-gradient(90deg, ${CYAN}, ${BLUE}, ${MAGENTA})`,
            boxShadow: `0 0 12px ${CYAN}`,
            borderRadius: 3,
          }}
        />
      </div>

      {/* Header Badges */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        {/* Brand Tag */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            backgroundColor: "rgba(15, 23, 42, 0.8)",
            padding: "10px 20px",
            borderRadius: 30,
            border: "1px solid rgba(255, 255, 255, 0.15)",
            backdropFilter: "blur(12px)",
          }}
        >
          <div
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              backgroundColor: CYAN,
              boxShadow: `0 0 10px ${CYAN}`,
            }}
          />
          <span
            style={{
              fontFamily: fontDisplay,
              fontWeight: 800,
              fontSize: 20,
              letterSpacing: 2,
              color: WHITE,
            }}
          >
            AI DISPATCH
          </span>
        </div>

        {/* Category Tag */}
        <div
          style={{
            backgroundColor: "rgba(255, 8, 68, 0.15)",
            padding: "8px 18px",
            borderRadius: 30,
            border: "1px solid rgba(255, 8, 68, 0.4)",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span
            style={{
              fontFamily: fontDisplay,
              fontWeight: 700,
              fontSize: 16,
              letterSpacing: 1.5,
              color: "#FF4D6D",
            }}
          >
            ● INTELLIGENCE UPDATE
          </span>
        </div>
      </div>
    </div>
  );
};

// 3. Ken Burns Image Background Layer
const KenBurnsImage: React.FC<{ name: string; duration: number }> = ({
  name,
  duration,
}) => {
  const frame = useCurrentFrame();
  const [hasError, setHasError] = React.useState(false);

  if (hasError) return null;

  const scale = interpolate(frame, [0, duration], [1.0, 1.15], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const opacity = interpolate(frame, [0, 15], [0, 0.45], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <img
        src={staticFile(`images/${name}.png`)}
        onError={() => setHasError(true)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${scale})`,
          opacity,
          filter: "contrast(1.1) saturate(1.2)",
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "linear-gradient(180deg, rgba(7,9,14,0.85) 0%, rgba(7,9,14,0.5) 50%, rgba(7,9,14,0.9) 100%)",
        }}
      />
    </AbsoluteFill>
  );
};

// 4. Redesigned Hook Scene
const HookScene: React.FC<{ duration: number; text: string }> = ({
  duration,
  text,
}) => {
  const frame = useCurrentFrame();
  const exitOpacity = fadeByFraction(frame, duration, 0, 0.92);

  const titleScale = spring({
    frame,
    fps: 30,
    config: { damping: 11, stiffness: 120 },
    durationInFrames: Math.min(22, Math.round(duration * 0.25)),
  });

  const badgeSlide = spring({
    frame,
    fps: 30,
    config: { damping: 14 },
    durationInFrames: 18,
  });

  const words = text.split(" ");
  const third = Math.ceil(words.length / 3);
  const line1 = words.slice(0, third).join(" ");
  const line2 = words.slice(third, third * 2).join(" ");
  const line3 = words.slice(third * 2).join(" ");
  const lines = [line1, line2, line3].filter(Boolean);

  return (
    <AbsoluteFill
      style={{
        alignItems: "center",
        justifyContent: "center",
        padding: "0 60px",
        opacity: exitOpacity,
      }}
    >
      <Audio src={staticFile("audio/01_hook.mp3")} />
      <Sequence from={0} durationInFrames={Math.min(30, Math.round(duration))}>
        <Audio src={staticFile("sfx/whoosh.wav")} volume={0.6} />
      </Sequence>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          textAlign: "center",
          gap: 24,
        }}
      >
        {/* Breaking Badge */}
        <div
          style={{
            transform: `translateY(${(1 - badgeSlide) * -40}px)`,
            opacity: badgeSlide,
            backgroundColor: "rgba(0, 242, 254, 0.12)",
            border: `1.5px solid ${CYAN}`,
            borderRadius: 50,
            padding: "10px 28px",
            boxShadow: `0 0 30px rgba(0, 242, 254, 0.3)`,
          }}
        >
          <span
            style={{
              fontFamily: fontDisplay,
              fontWeight: 800,
              fontSize: 22,
              letterSpacing: 3,
              color: CYAN,
              textTransform: "uppercase",
            }}
          >
            ⚡ BREAKING STORY
          </span>
        </div>

        {/* Hook Card */}
        <div
          style={{
            transform: `scale(${titleScale})`,
            backgroundColor: GLASS_BG,
            border: "1px solid rgba(255, 255, 255, 0.15)",
            backdropFilter: "blur(24px)",
            borderRadius: 36,
            padding: "50px 40px",
            boxShadow:
              "0 30px 60px rgba(0, 0, 0, 0.7), 0 0 50px rgba(0, 242, 254, 0.12)",
          }}
        >
          {lines.map((line, i) => {
            const lineOpacity = interpolate(
              frame,
              [i * 6, i * 6 + 12],
              [0, 1],
              { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
            );
            return (
              <div
                key={i}
                style={{
                  fontFamily: fontDisplay,
                  fontWeight: 900,
                  fontSize: i === 0 ? 58 : 46,
                  lineHeight: 1.25,
                  opacity: lineOpacity,
                  background:
                    i === 0
                      ? `linear-gradient(135deg, ${WHITE} 40%, ${CYAN} 100%)`
                      : i === 1
                      ? `linear-gradient(135deg, ${WHITE} 60%, ${GOLD} 100%)`
                      : WHITE,
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  marginTop: i > 0 ? 16 : 0,
                  letterSpacing: -0.5,
                }}
              >
                {line}
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// 5. Redesigned Kinetic Text Beat (Karaoke-style word highlight)
const KineticTextBeat: React.FC<{ duration: number; text: string }> = ({
  duration,
  text,
}) => {
  const frame = useCurrentFrame();
  const opacity = fadeByFraction(frame, duration);

  const sentences = text
    .split(/(?<=[.!?])\s+/)
    .filter((s) => s.trim().length > 0);
  const framesPerSentence = Math.max(
    Math.floor(duration / Math.max(sentences.length, 1)),
    30
  );

  return (
    <AbsoluteFill
      style={{
        alignItems: "center",
        justifyContent: "center",
        padding: "0 60px",
        opacity,
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 960,
          backgroundColor: GLASS_BG,
          border: "1px solid rgba(255, 255, 255, 0.12)",
          backdropFilter: "blur(20px)",
          borderRadius: 36,
          padding: "48px 40px",
          boxShadow:
            "0 24px 60px rgba(0, 0, 0, 0.6), inset 0 1px 0 rgba(255, 255, 255, 0.15)",
          textAlign: "center",
        }}
      >
        {sentences.map((sentence, i) => {
          const sentenceStart = i * framesPerSentence;
          const sentenceEnd = sentenceStart + framesPerSentence;
          const words = sentence.split(" ");
          const highlightIndex = interpolate(
            frame,
            [sentenceStart + 4, sentenceEnd - 4],
            [0, words.length - 0.01],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
          );
          const sentenceOpacity = interpolate(
            frame,
            [
              sentenceStart,
              sentenceStart + 10,
              sentenceEnd - 10,
              sentenceEnd,
            ],
            [0, 1, 1, 0],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
          );
          const sentenceSlide = interpolate(
            frame,
            [sentenceStart, sentenceStart + 12],
            [25, 0],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
          );

          return (
            <div
              key={i}
              style={{
                opacity: sentenceOpacity,
                transform: `translateY(${sentenceSlide}px)`,
                fontFamily: fontBody,
                fontSize: 42,
                lineHeight: 1.75,
                marginBottom: i < sentences.length - 1 ? 24 : 0,
              }}
            >
              {words.map((word, wi) => {
                const isCurrent = Math.round(highlightIndex) === wi;
                const isPast = wi < Math.round(highlightIndex);

                return (
                  <span
                    key={wi}
                    style={{
                      display: "inline-block",
                      padding: "4px 8px",
                      margin: "2px 4px",
                      borderRadius: 8,
                      fontWeight: isCurrent ? 800 : isPast ? 600 : 400,
                      color: isCurrent
                        ? DARK_BG
                        : isPast
                        ? WHITE
                        : "rgba(255, 255, 255, 0.45)",
                      background: isCurrent
                        ? `linear-gradient(135deg, ${CYAN}, ${BLUE})`
                        : "transparent",
                      boxShadow: isCurrent ? `0 0 20px ${CYAN}` : "none",
                      transform: isCurrent ? "scale(1.08)" : "scale(1)",
                      transition: "transform 0.1s ease",
                    }}
                  >
                    {word}
                  </span>
                );
              })}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// 6. Redesigned Stat Reveal Beat
const StatRevealBeat: React.FC<{ duration: number; text: string }> = ({
  duration,
  text,
}) => {
  const frame = useCurrentFrame();
  const opacity = fadeByFraction(frame, duration);

  const statMatch = text.match(/(\d[\d,\.]*\s*[%kMBN]*)/i);
  const statText = statMatch ? statMatch[1] : "100%";
  const label = text.replace(statText, "").trim();

  const scale = spring({
    frame,
    fps: 30,
    config: { damping: 12, stiffness: 100 },
    durationInFrames: 20,
  });

  const counterProgress = interpolate(frame, [4, 28], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const numericPart = statText.replace(/[^0-9.,]/g, "").replace(/,/g, "");
  const numVal = parseFloat(numericPart) || 0;
  const displayNum = Math.round(numVal * counterProgress);
  const displayText =
    counterProgress >= 0.99
      ? statText
      : statText.replace(numericPart, String(displayNum));

  return (
    <AbsoluteFill
      style={{
        alignItems: "center",
        justifyContent: "center",
        padding: "0 60px",
        opacity,
      }}
    >
      <div
        style={{
          transform: `scale(${scale})`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 20,
        }}
      >
        {/* Trend Indicator Pill */}
        <div
          style={{
            backgroundColor: "rgba(0, 242, 254, 0.15)",
            border: `1px solid ${CYAN}`,
            borderRadius: 30,
            padding: "8px 24px",
            boxShadow: `0 0 25px rgba(0, 242, 254, 0.25)`,
          }}
        >
          <span
            style={{
              fontFamily: fontDisplay,
              fontWeight: 800,
              fontSize: 20,
              letterSpacing: 2,
              color: CYAN,
            }}
          >
            ▲ KEY STATISTIC
          </span>
        </div>

        {/* Glassmorphic Stat Box */}
        <div
          style={{
            backgroundColor: GLASS_BG,
            border: "1.5px solid rgba(0, 242, 254, 0.3)",
            backdropFilter: "blur(24px)",
            borderRadius: 40,
            padding: "60px 70px",
            textAlign: "center",
            boxShadow:
              "0 30px 70px rgba(0, 0, 0, 0.7), 0 0 60px rgba(0, 242, 254, 0.2)",
            minWidth: 600,
          }}
        >
          {/* Big Number */}
          <div
            style={{
              fontFamily: fontDisplay,
              fontWeight: 900,
              fontSize: 120,
              lineHeight: 1,
              background: `linear-gradient(135deg, ${CYAN} 0%, ${WHITE} 60%, ${BLUE} 100%)`,
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              filter: "drop-shadow(0 10px 20px rgba(0, 242, 254, 0.3))",
            }}
          >
            {displayText}
          </div>

          {/* Divider */}
          <div
            style={{
              width: 120,
              height: 3,
              background: `linear-gradient(90deg, transparent, ${CYAN}, transparent)`,
              margin: "24px auto",
            }}
          />

          {/* Label */}
          {label && (
            <div
              style={{
                fontFamily: fontBody,
                fontWeight: 600,
                fontSize: 30,
                color: LIGHT_GRAY,
                lineHeight: 1.4,
                maxWidth: 600,
              }}
            >
              {label}
            </div>
          )}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// 7. Redesigned Diagram Beat
const DiagramBeat: React.FC<{ duration: number; text: string }> = ({
  duration,
  text,
}) => {
  const frame = useCurrentFrame();
  const opacity = fadeByFraction(frame, duration);
  const d = duration;

  const titleOpacity = interpolate(frame, [0, d * 0.12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const leftBoxIn = spring({
    frame,
    fps: 30,
    config: { damping: 13 },
    durationInFrames: 22,
    delay: Math.round(d * 0.15),
  });

  const rightBoxIn = spring({
    frame,
    fps: 30,
    config: { damping: 13 },
    durationInFrames: 22,
    delay: Math.round(d * 0.3),
  });

  const beamProgress = interpolate(frame, [d * 0.35, d * 0.65], [0, 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const sentences = text.split(/(?<=[.!?])\s+/).filter(Boolean);
  const title = sentences[0] || "Mechanism Breakdown";
  const rest = sentences.slice(1).join(" ") || text;
  const restWords = rest.split(" ");
  const mid = Math.ceil(restWords.length / 2);
  const leftText = restWords.slice(0, mid).join(" ");
  const rightText = restWords.slice(mid).join(" ");

  return (
    <AbsoluteFill
      style={{
        alignItems: "center",
        justifyContent: "center",
        padding: "0 50px",
        opacity,
      }}
    >
      <Sequence from={Math.round(d * 0.15)} durationInFrames={20}>
        <Audio src={staticFile("sfx/pop.wav")} volume={0.5} />
      </Sequence>
      <Sequence from={Math.round(d * 0.3)} durationInFrames={20}>
        <Audio src={staticFile("sfx/pop.wav")} volume={0.5} />
      </Sequence>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          width: "100%",
          gap: 36,
        }}
      >
        {/* Title */}
        <div
          style={{
            fontFamily: fontDisplay,
            fontWeight: 800,
            fontSize: 34,
            color: WHITE,
            opacity: titleOpacity,
            textAlign: "center",
            maxWidth: 800,
            letterSpacing: -0.5,
          }}
        >
          {title}
        </div>

        {/* Flow Boxes */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 24,
            width: "100%",
            justifyContent: "center",
          }}
        >
          {/* Box 1 */}
          <div
            style={{
              transform: `scale(${leftBoxIn})`,
              width: 380,
              borderRadius: 28,
              border: `1.5px solid ${CYAN}`,
              background: "rgba(0, 242, 254, 0.08)",
              backdropFilter: "blur(20px)",
              padding: "36px 28px",
              textAlign: "center",
              boxShadow: "0 20px 40px rgba(0,0,0,0.5), 0 0 30px rgba(0,242,254,0.15)",
            }}
          >
            <div
              style={{
                fontFamily: fontDisplay,
                fontWeight: 700,
                fontSize: 22,
                color: CYAN,
                marginBottom: 10,
                letterSpacing: 1,
              }}
            >
              PHASE 01
            </div>
            <div
              style={{
                fontFamily: fontBody,
                fontWeight: 600,
                fontSize: 24,
                color: WHITE,
                lineHeight: 1.4,
              }}
            >
              {leftText || "Primary Action"}
            </div>
          </div>

          {/* Connection Beam / Arrow */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 8,
              width: 80,
            }}
          >
            <div
              style={{
                width: "100%",
                height: 4,
                backgroundColor: "rgba(255, 255, 255, 0.15)",
                borderRadius: 2,
                position: "relative",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: `${beamProgress}%`,
                  background: `linear-gradient(90deg, ${CYAN}, ${MAGENTA})`,
                  boxShadow: `0 0 10px ${CYAN}`,
                }}
              />
            </div>
            <span style={{ fontSize: 28, color: CYAN }}>➔</span>
          </div>

          {/* Box 2 */}
          <div
            style={{
              transform: `scale(${rightBoxIn})`,
              width: 380,
              borderRadius: 28,
              border: `1.5px solid ${MAGENTA}`,
              background: "rgba(255, 8, 68, 0.08)",
              backdropFilter: "blur(20px)",
              padding: "36px 28px",
              textAlign: "center",
              boxShadow: "0 20px 40px rgba(0,0,0,0.5), 0 0 30px rgba(255,8,68,0.15)",
            }}
          >
            <div
              style={{
                fontFamily: fontDisplay,
                fontWeight: 700,
                fontSize: 22,
                color: MAGENTA,
                marginBottom: 10,
                letterSpacing: 1,
              }}
            >
              PHASE 02
            </div>
            <div
              style={{
                fontFamily: fontBody,
                fontWeight: 600,
                fontSize: 24,
                color: WHITE,
                lineHeight: 1.4,
              }}
            >
              {rightText || "Result & Impact"}
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// 8. Redesigned Outro / CTA Scene
const OutroScene: React.FC<{ duration: number }> = ({ duration }) => {
  const frame = useCurrentFrame();
  const enter = interpolate(frame, [0, duration * 0.1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const pulse = 1 + Math.sin(frame / 6) * 0.05;

  return (
    <AbsoluteFill
      style={{
        alignItems: "center",
        justifyContent: "center",
        padding: "0 60px",
        opacity: enter,
      }}
    >
      <Audio src={staticFile("audio/03_cta.mp3")} />

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          textAlign: "center",
          gap: 32,
          backgroundColor: GLASS_BG,
          border: "1.5px solid rgba(0, 242, 254, 0.3)",
          backdropFilter: "blur(24px)",
          borderRadius: 40,
          padding: "60px 50px",
          boxShadow:
            "0 30px 70px rgba(0, 0, 0, 0.7), 0 0 60px rgba(0, 242, 254, 0.2)",
        }}
      >
        {/* Play Icon Badge */}
        <div style={{ transform: `scale(${pulse})` }}>
          <div
            style={{
              width: 100,
              height: 100,
              borderRadius: "50%",
              background: `linear-gradient(135deg, ${CYAN}, ${BLUE})`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow: `0 0 50px ${CYAN}`,
            }}
          >
            <span
              style={{
                fontFamily: fontDisplay,
                fontWeight: 900,
                fontSize: 50,
                color: DARK_BG,
                marginLeft: 6,
              }}
            >
              ▶
            </span>
          </div>
        </div>

        {/* CTA Title */}
        <div
          style={{
            fontFamily: fontDisplay,
            fontWeight: 900,
            fontSize: 44,
            lineHeight: 1.25,
            color: WHITE,
            maxWidth: 700,
          }}
        >
          SUBSCRIBE FOR DAILY AI & TECH DISPATCHES
        </div>

        {/* Subtitle Badge */}
        <div
          style={{
            backgroundColor: "rgba(255, 255, 255, 0.08)",
            padding: "10px 28px",
            borderRadius: 30,
            border: "1px solid rgba(255, 255, 255, 0.15)",
          }}
        >
          <span
            style={{
              fontFamily: fontBody,
              fontWeight: 600,
              fontSize: 22,
              color: CYAN,
            }}
          >
            @AI_DISPATCH_NEWS
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// 9. Main Video Composition Assembly
interface VideoProps {
  script: {
    hook: string;
    body: string;
    cta: string;
    suggested_visual_beats: Array<{
      name: string;
      narration_text: string;
      beat_type?: string;
    }>;
  };
}

export const ContentVideo: React.FC<VideoProps> = ({ script }) => {
  const frame = useCurrentFrame();

  const beatsMap: Record<
    string,
    { narration_text: string; beat_type: string }
  > = {};
  for (const b of script.suggested_visual_beats) {
    beatsMap[b.name] = {
      narration_text: b.narration_text,
      beat_type: b.beat_type || "kinetic_text",
    };
  }

  const BEAT_COMPONENTS: Record<
    string,
    React.FC<{ duration: number; text: string }>
  > = {
    kinetic_text: KineticTextBeat,
    stat_reveal: StatRevealBeat,
    diagram: DiagramBeat,
  };

  let bodyStart = 0;
  const bodyBeatEntries = beatKeys.map((key) => {
    const start = bodyStart;
    bodyStart += beats[key];
    return { key, start, duration: beats[key] };
  });

  const outroStart = hookFrames + bodyFrames;

  return (
    <AbsoluteFill>
      {/* Ambient Layer */}
      <DynamicBackdrop />

      {/* Global Persistent Header & Progress Bar */}
      <HeaderBar currentGlobalFrame={frame} />

      {/* 1. Hook Scene */}
      <Sequence from={0} durationInFrames={hookFrames}>
        <KenBurnsImage name="hook" duration={hookFrames} />
        <HookScene duration={hookFrames} text={script.hook} />
      </Sequence>

      {/* 2. Body Beats */}
      <Sequence from={hookFrames} durationInFrames={bodyFrames}>
        <Audio src={staticFile("audio/02_body.mp3")} />
        {bodyBeatEntries.map((entry) => {
          const beatData = beatsMap[entry.key];
          const BeatComp =
            BEAT_COMPONENTS[beatData?.beat_type || "kinetic_text"] ||
            KineticTextBeat;

          return (
            <Sequence
              key={entry.key}
              from={entry.start}
              durationInFrames={entry.duration}
            >
              <KenBurnsImage name={entry.key} duration={entry.duration} />
              <BeatComp
                duration={entry.duration}
                text={beatData?.narration_text || ""}
              />
            </Sequence>
          );
        })}
      </Sequence>

      {/* 3. Outro / CTA Scene */}
      <Sequence from={outroStart} durationInFrames={outroFrames}>
        <OutroScene duration={outroFrames} />
      </Sequence>
    </AbsoluteFill>
  );
};

