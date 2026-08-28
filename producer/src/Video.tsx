import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import timing from "./timing.json";
import { theme } from "./theme";

const { hookFrames, outroFrames, beats } = timing as {
  hookFrames: number;
  outroFrames: number;
  beats: Record<string, number>;
};

type Beat = {
  name: string;
  narration_text: string;
  beat_type?: string;
  image_url?: string;
  asset_source_url?: string;
  asset_available?: boolean;
  image_treatment?: string;
  visual_style?: "editorial" | "image_led" | "stat_led" | "diagram" | "timeline" | "quiet";
};

interface VideoProps {
  script: {
    hook: string;
    body: string;
    cta: string;
    format?: string;
    accent_color?: string;
    suggested_visual_beats: Beat[];
  };
}

const accentFor = (text: string) => {
  const value = (text || "").toLowerCase();
  if (/nvidia|jensen|gpu|blackwell|hardware|chip/.test(value)) return "#10B981"; // Emerald
  if (/anthropic|claude|startup|model/.test(value)) return "#F59E0B"; // Amber
  if (/gemini|google|deepmind/.test(value)) return "#3B82F6"; // Royal Blue
  if (/bitcoin|crypto|ethereum|blockchain/.test(value)) return "#F97316"; // Bright Orange
  if (/openai|gpt|altman/.test(value)) return "#06B6D4"; // Cyan
  if (/warning|risk|loss|ban|crisis|hack/.test(value)) return "#EF4444"; // Red
  return "#8B5CF6"; // Vibrant Violet default
};

// --- Component 1: Multi-Property Spring Entrance (Rule 2) ---
const Entrance: React.FC<{ delay?: number; distance?: number; children: React.ReactNode; style?: React.CSSProperties }> = ({
  delay = 0,
  distance = 35,
  children,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = Math.max(0, spring({ frame: frame - delay, fps, config: theme.spring.smooth }));
  return (
    <div
      style={{
        opacity: Math.min(1, p),
        transform: `translateY(${interpolate(p, [0, 1], [distance, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px) scale(${interpolate(p, [0, 1], [0.94, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })})`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

// --- Component 2: Background Mesh (Rule 5 & 7: Never Flat) ---
const BgMesh: React.FC<{ accent: string; progress?: number; chrome?: boolean }> = ({ accent, progress = 0, chrome = false }) => {
  const frame = useCurrentFrame();
  const d1 = Math.sin(frame / 60) * 45;
  const d2 = Math.cos(frame / 75) * 40;

  return (
    <AbsoluteFill style={{ background: theme.colors.bg, overflow: "hidden" }}>
      {/* Subtle Grid Grid Pattern */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: `linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)`,
          backgroundSize: "80px 80px",
          opacity: 0.6,
        }}
      />
      {/* Drifting Radial Glowing Orbs - High Performance Pure CSS Gradients (0% Chromium Crash) */}
      <div
        style={{
          position: "absolute",
          width: 900,
          height: 900,
          borderRadius: "50%",
          top: -250,
          left: -200 + d1,
          background: `radial-gradient(circle, ${accent}2e 0%, ${accent}14 42%, transparent 70%)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 800,
          height: 800,
          borderRadius: "50%",
          bottom: -200,
          right: -200 - d2,
          background: `radial-gradient(circle, ${accent}22 0%, ${accent}0d 45%, transparent 70%)`,
        }}
      />

      {chrome && (
        <>
          <div style={{ position: "absolute", left: 60, right: 60, top: 60, height: 4, borderRadius: 4, background: "rgba(255,255,255,0.1)" }}>
            <div style={{ height: "100%", width: `${Math.max(4, progress * 100)}%`, background: accent, borderRadius: 4 }} />
          </div>
          <div style={{ position: "absolute", left: 60, top: 86, display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: accent }} />
            <span style={{ fontFamily: theme.fonts.display, fontWeight: 800, fontSize: 18, letterSpacing: 3, color: theme.colors.text }}>COLONY V</span>
          </div>
          <div style={{ position: "absolute", right: 60, top: 86, fontFamily: theme.fonts.display, fontWeight: 600, fontSize: 14, letterSpacing: 2, color: theme.colors.textMuted }}>
            AI INTELLIGENCE
          </div>
        </>
      )}
    </AbsoluteFill>
  );
};

// --- Component 3: Radial Spark / Logo Mark (Pattern 10) ---
const RadialSpark: React.FC<{ size?: number; accent: string; delay?: number }> = ({ size = 200, accent, delay = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rays = 12;
  const rot = interpolate(frame, [0, 180], [0, 90], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <div style={{ position: "relative", width: size, height: size, transform: `rotate(${rot}deg)` }}>
      {Array.from({ length: rays }).map((_, i) => {
        const p = Math.max(0, spring({ frame: frame - delay - i * 1.5, fps, config: theme.spring.snappy }));
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: "50%",
              top: "50%",
              width: size * 0.04,
              height: Math.max(0, size * 0.42 * p),
              background: accent,
              borderRadius: size,
              transformOrigin: "50% 0%",
              transform: `translateX(-50%) rotate(${(360 / rays) * i}deg) translateY(${size * 0.08}px)`,
            }}
          />
        );
      })}
    </div>
  );
};

// --- Component 4: Editorial Card with Ken Burns Zoom & Pan (Rule 6) ---
const SubjectImage: React.FC<{ name: string; duration: number; available?: boolean; accent: string }> = ({ name, duration, available = true, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!available) return null;

  const reveal = Math.max(0, Math.min(1, spring({ frame: frame - 6, fps, config: theme.spring.smooth })));
  const scale = interpolate(frame, [0, duration], [1.0, 1.08], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const pan = interpolate(frame, [0, duration], [0, -20], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const breathe = Math.sin(frame / 60) * 6;

  return (
    <div
      style={{
        position: "absolute",
        top: 280,
        right: 60,
        width: 440,
        height: 640,
        borderRadius: 28,
        overflow: "hidden",
        border: `1px solid ${theme.colors.bgCardBorder}`,
        background: theme.colors.bgCard,
        boxShadow: `0 16px 40px rgba(0,0,0,0.5)`,
        opacity: reveal,
        transform: `translateY(${(1 - reveal) * 40 + breathe}px) scale(${0.92 + reveal * 0.08})`,
      }}
    >
      <Img
        src={staticFile(`images/${name}.png`)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${scale}) translateX(${pan}px)`,
        }}
      />
      {/* Inner Vignette / Grade */}
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, transparent 60%, rgba(10,10,15,0.8) 100%)" }} />
      <div style={{ position: "absolute", bottom: 18, left: 18, right: 18, display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: accent }} />
        <span style={{ fontFamily: theme.fonts.display, fontSize: 13, fontWeight: 700, color: "#fff", letterSpacing: 1.5, textTransform: "uppercase" }}>Verified Source</span>
      </div>
    </div>
  );
};

// --- Component 5: Animated Number Counter (Pattern 9) ---
const AnimatedCounter: React.FC<{ target: number; prefix?: string; suffix?: string; accent: string; delay?: number }> = ({
  target,
  prefix = "",
  suffix = "",
  accent,
  delay = 6,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = Math.max(0, Math.min(1, spring({ frame: frame - delay, fps, config: { damping: 24, stiffness: 80 } })));
  const current = interpolate(p, [0, 1], [0, target], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const fontSize = target >= 10000 ? 84 : 110;

  return (
    <div style={{ fontFamily: theme.fonts.display, fontSize, fontWeight: 900, color: theme.colors.text, lineHeight: 1 }}>
      <span style={{ color: accent }}>{prefix}</span>
      <span>{target % 1 === 0 ? Math.round(current).toLocaleString("en-US") : current.toFixed(1)}</span>
      <span style={{ color: accent, fontSize: Math.round(fontSize * 0.65), marginLeft: 8 }}>{suffix}</span>
    </div>
  );
};

// --- Component 6: Kinetic Hook Scene ---
const HookScene: React.FC<{ text: string; duration: number; accent: string }> = ({ text, duration, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const words = text.split(" ");
  const exit = interpolate(frame, [duration - 10, duration], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: exit }}>
      <BgMesh accent={accent} chrome />
      <Audio src={staticFile("audio/01_hook.mp3")} />

      <div style={{ position: "absolute", inset: "0 60px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
        {/* Category Pill Tag */}
        <Entrance delay={0} distance={20}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 10,
              padding: "8px 18px",
              background: `${accent}22`,
              border: `1px solid ${accent}55`,
              borderRadius: 30,
              marginBottom: 36,
            }}
          >
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: accent }} />
            <span style={{ fontFamily: theme.fonts.display, fontWeight: 800, fontSize: 15, letterSpacing: 2.5, color: accent }}>BREAKING SIGNAL</span>
          </div>
        </Entrance>

        {/* Big Staggered Headline Reveal */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "14px 20px", maxWidth: 960 }}>
          {words.map((word, i) => {
            const isHero = i >= words.length - 3;
            const p = Math.max(0, Math.min(1, spring({ frame: frame - 6 - i * 2.5, fps, config: theme.spring.snappy })));
            return (
              <span
                key={i}
                style={{
                  display: "inline-block",
                  fontFamily: theme.fonts.display,
                  fontSize: 72,
                  fontWeight: 900,
                  letterSpacing: -2.5,
                  lineHeight: 1.05,
                  color: isHero ? accent : theme.colors.text,
                  opacity: p,
                  transform: `translateY(${interpolate(p, [0, 1], [30, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px) scale(${interpolate(p, [0, 1], [0.92, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })})`,
                }}
              >
                {word}
              </span>
            );
          })}
        </div>

        {/* Glowing Progress Accent Bar */}
        <div
          style={{
            marginTop: 48,
            width: interpolate(frame, [8, 36], [0, 480], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
            height: 4,
            background: `linear-gradient(90deg, ${accent}, transparent)`,
            borderRadius: 2,
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

// --- Component 7: Kinetic Editorial Scene ---
const KineticScene: React.FC<{ beat: Beat; duration: number; accent: string; index: number; total: number }> = ({
  beat,
  duration,
  accent,
  index,
  total,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const sentences = (beat.narration_text || "").split(/(?<=[.!?])\s+/).filter(Boolean).slice(0, 3);
  const active = Math.min(sentences.length - 1, Math.floor(frame / Math.max(1, duration / Math.max(1, sentences.length))));
  const hasAsset = Boolean(beat.asset_available);

  return (
    <AbsoluteFill>
      <BgMesh accent={accent} progress={(index + frame / duration) / total} chrome />
      <SubjectImage name={beat.name} duration={duration} available={hasAsset} accent={accent} />

      <div style={{ position: "absolute", left: 60, top: 280, width: hasAsset ? 480 : 960 }}>
        <Entrance delay={0} distance={15}>
          <div style={{ fontFamily: theme.fonts.display, color: accent, fontSize: 16, fontWeight: 800, letterSpacing: 2.5, marginBottom: 30, display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ width: 24, height: 2, background: accent }} />
            <span>KEY TAKEAWAY</span>
          </div>
        </Entrance>

        {sentences.map((sentence, i) => {
          const isCurrent = i === active;
          const p = Math.max(0, Math.min(1, spring({ frame: frame - i * 16, fps, config: theme.spring.smooth })));
          return (
            <div
              key={sentence}
              style={{
                fontFamily: theme.fonts.display,
                fontSize: isCurrent ? 44 : 32,
                lineHeight: 1.25,
                fontWeight: isCurrent ? 800 : 500,
                color: isCurrent ? theme.colors.text : theme.colors.textMuted,
                marginBottom: 28,
                padding: "16px 20px",
                borderRadius: 18,
                background: isCurrent ? "rgba(255,255,255,0.04)" : "transparent",
                border: isCurrent ? `1px solid ${accent}44` : "1px solid transparent",
                opacity: p,
                transform: `translateX(${interpolate(p, [0, 1], [-25, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px)`,
                transition: "all 0.2s ease",
              }}
            >
              {sentence}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// --- Component 8: Stat / Data Scene (Pattern 9) ---
const StatScene: React.FC<{ beat: Beat; duration: number; accent: string; index: number; total: number }> = ({
  beat,
  duration,
  accent,
  index,
  total,
}) => {
  const frame = useCurrentFrame();
  const match = (beat.narration_text || "").match(/(\$)?(\d+[\d,.]*)(\s*(?:million|billion|trillion|M|B|%))?/i);
  const prefix = match?.[1] || "";
  const numStr = match?.[2] ? match[2].replace(/,/g, "") : "100";
  const suffix = match?.[3] || "%";
  const numVal = parseFloat(numStr) || 100;
  const remaining = beat.narration_text ? beat.narration_text.replace(match?.[0] || "", "").trim() : "";

  return (
    <AbsoluteFill>
      <BgMesh accent={accent} progress={(index + frame / duration) / total} chrome />

      <div style={{ position: "absolute", inset: "0 60px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <Entrance delay={0} distance={15}>
          <div style={{ fontFamily: theme.fonts.display, fontSize: 16, fontWeight: 800, letterSpacing: 3, color: accent, marginBottom: 20 }}>
            CRITICAL DATA POINT
          </div>
        </Entrance>

        <Entrance delay={4} distance={30}>
          <div style={{ background: theme.colors.bgCard, padding: "36px 44px", borderRadius: 32, border: `1px solid ${accent}44`, boxShadow: `0 16px 40px rgba(0,0,0,0.5)`, marginBottom: 36 }}>
            <AnimatedCounter target={numVal} prefix={prefix} suffix={suffix} accent={accent} delay={6} />
          </div>
        </Entrance>

        <Entrance delay={14} distance={25}>
          <div style={{ fontFamily: theme.fonts.display, fontSize: 38, lineHeight: 1.35, fontWeight: 600, color: theme.colors.text, maxWidth: 900 }}>
            {remaining}
          </div>
        </Entrance>
      </div>
    </AbsoluteFill>
  );
};

// --- Component 9: Diagram / Logic Flow Scene (Pattern 10 & 13) ---
const DiagramScene: React.FC<{ beat: Beat; duration: number; accent: string; index: number; total: number }> = ({
  beat,
  duration,
  accent,
  index,
  total,
}) => {
  const frame = useCurrentFrame();
  const words = (beat.narration_text || "").split(" ");
  const mid = Math.max(1, Math.ceil(words.length / 2));
  const boxA = words.slice(0, mid).join(" ") || "System Action";
  const boxB = words.slice(mid).join(" ") || "Outcome";
  const progressLine = interpolate(frame, [18, 48], [0, 100], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill>
      <BgMesh accent={accent} progress={(index + frame / duration) / total} chrome />

      <div style={{ position: "absolute", inset: "0 60px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <Entrance delay={0} distance={15}>
          <div style={{ fontFamily: theme.fonts.display, fontSize: 16, fontWeight: 800, letterSpacing: 3, color: accent, marginBottom: 36 }}>
            SYSTEM FLOW & IMPACT
          </div>
        </Entrance>

        <div style={{ display: "flex", flexDirection: "column", gap: 24, position: "relative" }}>
          {/* Node 1 */}
          <Entrance delay={4} distance={30}>
            <div style={{ padding: "32px 36px", background: theme.colors.bgCard, borderRadius: 24, border: `1px solid rgba(255,255,255,0.08)`, display: "flex", alignItems: "center", gap: 20 }}>
              <div style={{ width: 44, height: 44, borderRadius: "50%", background: "rgba(255,255,255,0.08)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, color: theme.colors.textMuted }}>01</div>
              <div style={{ fontFamily: theme.fonts.display, fontSize: 32, fontWeight: 700, color: theme.colors.text, lineHeight: 1.3 }}>{boxA}</div>
            </div>
          </Entrance>

          {/* Connection Line */}
          <div style={{ height: 32, width: 3, background: `linear-gradient(180deg, ${accent}, transparent)`, marginLeft: 56, opacity: progressLine / 100 }} />

          {/* Node 2 */}
          <Entrance delay={20} distance={30}>
            <div style={{ padding: "32px 36px", background: theme.colors.bgCard, borderRadius: 24, border: `2px solid ${accent}`, display: "flex", alignItems: "center", gap: 20 }}>
              <div style={{ width: 44, height: 44, borderRadius: "50%", background: accent, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 900, color: "#fff" }}>02</div>
              <div style={{ fontFamily: theme.fonts.display, fontSize: 32, fontWeight: 800, color: accent, lineHeight: 1.3 }}>{boxB}</div>
            </div>
          </Entrance>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// --- Component 10: Timeline Sequence Scene ---
const TimelineScene: React.FC<{ beat: Beat; duration: number; accent: string; index: number; total: number }> = ({
  beat,
  duration,
  accent,
  index,
  total,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const events = beat.narration_text.split(/\s*\|\s*|(?<=[.!?])\s+/).filter(Boolean).slice(0, 3);
  const line = interpolate(frame, [10, duration * 0.6], [0, 100], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill>
      <BgMesh accent={accent} progress={(index + frame / duration) / total} chrome />
      <div style={{ position: "absolute", inset: "0 60px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <Entrance delay={0} distance={15}>
          <div style={{ fontFamily: theme.fonts.display, fontSize: 16, fontWeight: 800, letterSpacing: 3, color: accent, marginBottom: 40 }}>
            ROADMAP & TIMELINE
          </div>
        </Entrance>

        <div style={{ display: "flex", flexDirection: "column", gap: 32, position: "relative" }}>
          <div style={{ position: "absolute", left: 19, top: 20, bottom: 20, width: 2, background: "rgba(255,255,255,0.08)" }}>
            <div style={{ width: "100%", height: `${line}%`, background: accent }} />
          </div>

          {events.map((event, i) => {
            const p = Math.max(0, Math.min(1, spring({ frame: frame - 8 - i * 14, fps, config: theme.spring.smooth })));
            return (
              <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 28, paddingLeft: 8, opacity: p, transform: `translateY(${interpolate(p, [0, 1], [25, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px)` }}>
                <div style={{ width: 24, height: 24, borderRadius: "50%", background: i === 0 ? accent : theme.colors.bgCard, border: `2px solid ${accent}`, flexShrink: 0, marginTop: 4 }} />
                <div style={{ fontFamily: theme.fonts.display, fontSize: 32, fontWeight: 650, lineHeight: 1.35, color: theme.colors.text }}>{event}</div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// --- Component 11: Quiet High-Impact Scene ---
const QuietScene: React.FC<{ beat: Beat; duration: number; accent: string }> = ({ beat, accent }) => {
  return (
    <AbsoluteFill>
      <BgMesh accent={accent} chrome />
      <div style={{ position: "absolute", inset: "0 70px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <Entrance delay={0} distance={15}>
          <div style={{ width: 80, height: 4, background: accent, borderRadius: 2, marginBottom: 40 }} />
        </Entrance>
        <Entrance delay={4} distance={30}>
          <div style={{ fontFamily: theme.fonts.display, fontSize: 58, lineHeight: 1.2, fontWeight: 850, letterSpacing: -2, color: theme.colors.text }}>
            {beat.narration_text}
          </div>
        </Entrance>
      </div>
    </AbsoluteFill>
  );
};

// --- Component 12: Call to Action Outro Scene ---
const OutroScene: React.FC<{ text: string; duration: number; accent: string }> = ({ text, duration, accent }) => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill>
      <BgMesh accent={accent} chrome />
      <Audio src={staticFile("audio/03_cta.mp3")} />

      <div style={{ position: "absolute", inset: "0 60px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center" }}>
        {/* Animated Radial Spark Background behind Logo */}
        <div style={{ position: "absolute", top: "28%" }}>
          <RadialSpark size={260} accent={accent} delay={2} />
        </div>

        {/* Brand Logo Avatar */}
        <Entrance delay={2} distance={30}>
          <div
            style={{
              width: 120,
              height: 120,
              borderRadius: "50%",
              background: theme.colors.bgCard,
              border: `2px solid ${accent}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: theme.fonts.display,
              fontSize: 36,
              fontWeight: 900,
              color: "#fff",
              boxShadow: `0 8px 24px rgba(0,0,0,0.5)`,
              position: "relative",
              zIndex: 2,
            }}
          >
            CV
          </div>
        </Entrance>

        <Entrance delay={8} distance={25}>
          <div style={{ fontFamily: theme.fonts.display, fontSize: 50, lineHeight: 1.2, fontWeight: 850, color: theme.colors.text, maxWidth: 860, marginTop: 44 }}>
            {text}
          </div>
        </Entrance>

        {/* CTA Pill */}
        <Entrance delay={16} distance={20}>
          <div
            style={{
              marginTop: 36,
              display: "inline-flex",
              alignItems: "center",
              gap: 12,
              padding: "14px 32px",
              borderRadius: 40,
              background: accent,
              color: "#000",
              fontFamily: theme.fonts.display,
              fontSize: 18,
              fontWeight: 900,
              letterSpacing: 2,
            }}
          >
            SUBSCRIBE FOR DAILY BREAKTHROUGHS
          </div>
        </Entrance>
      </div>
    </AbsoluteFill>
  );
};

// --- Component 13: Clean Vignette Layer (Rule 5 & 7) ---
const Vignette: React.FC = () => (
  <AbsoluteFill style={{ pointerEvents: "none", background: "radial-gradient(circle at center, transparent 40%, rgba(10,10,15,0.3) 120%)" }} />
);

export const ContentVideo: React.FC<VideoProps> = ({ script }) => {
  const allText = `${script?.hook || ""} ${script?.body || ""}`;
  const accent = script?.accent_color || accentFor(allText);
  const beatKeys = Object.keys(beats || {});
  const bodyFrames = Object.values(beats || {}).reduce((sum, value) => sum + value, 0);
  const totalFrames = hookFrames + bodyFrames + outroFrames;
  let cursor = hookFrames;

  const visualBeats = script?.suggested_visual_beats || [];

  return (
    <AbsoluteFill style={{ background: theme.colors.bg }}>
      <Sequence from={0} durationInFrames={hookFrames}>
        <HookScene text={script?.hook || ""} duration={hookFrames} accent={accent} />
      </Sequence>
      {beatKeys.map((name, index) => {
        const duration = (beats && beats[name]) || 90;
        const from = cursor;
        cursor += duration;
        const beat = visualBeats.find((item) => item.name === name) || visualBeats[index] || { name, narration_text: "" };
        const type = beat.beat_type || "kinetic_text";
        const Scene =
          beat.visual_style === "timeline"
            ? TimelineScene
            : beat.visual_style === "quiet"
            ? QuietScene
            : type === "stat_reveal" || beat.visual_style === "stat_led"
            ? StatScene
            : type === "diagram" || beat.visual_style === "diagram"
            ? DiagramScene
            : KineticScene;

        return (
          <Sequence key={name} from={from} durationInFrames={duration}>
            <Audio src={staticFile(`audio/beat_${String(index + 1).padStart(2, "0")}.mp3`)} />
            <Scene beat={beat} duration={duration} accent={accent} index={index} total={beatKeys.length} />
          </Sequence>
        );
      })}
      <Sequence from={totalFrames - outroFrames} durationInFrames={outroFrames}>
        <OutroScene text={script?.cta || ""} duration={outroFrames} accent={accent} />
      </Sequence>

      {/* Topmost Cinematic Vignette Layer */}
      <Vignette />
    </AbsoluteFill>
  );
};
