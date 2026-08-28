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
} from "remotion";
import timing from "./timing.json";

const {hookFrames, outroFrames, beats} = timing as {
  hookFrames: number;
  outroFrames: number;
  beats: Record<string, number>;
};

const INK = "#0a0a0b";
const PAPER = "#f8f8f6";
const MUTED = "#68686d";
const LINE = "rgba(10,10,11,.12)";

type Beat = {
  name: string;
  narration_text: string;
  beat_type?: string;
  image_url?: string;
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
    suggested_visual_beats: Beat[];
  };
}

const accentFor = (text: string) => {
  const value = text.toLowerCase();
  if (/nvidia|jensen|gpu|blackwell/.test(value)) return "#76b900";
  if (/anthropic|claude/.test(value)) return "#d97757";
  if (/gemini|google/.test(value)) return "#4285f4";
  if (/bitcoin|crypto|ethereum/.test(value)) return "#f7931a";
  if (/openai|gpt/.test(value)) return "#10a37f";
  if (/warning|risk|loss|ban|crisis/.test(value)) return "#e5484d";
  return "#246bfd";
};

const enter = (frame: number, delay = 0, distance = 32) => {
  const value = spring({frame: frame - delay, fps: 30, config: {damping: 16, stiffness: 120, mass: 0.6}});
  return {opacity: value, transform: `translateY(${(1 - value) * distance}px) scale(${0.96 + (value * 0.04)})`};
};

const SceneBackground: React.FC<{accent: string; progress?: number; variant?: string; chrome?: boolean}> = ({accent, progress = 0, variant = "editorial", chrome = false}) => {
  const frame = useCurrentFrame();
  const x = Math.sin(frame / 60) * 40;
  const y = Math.cos(frame / 70) * 35;
  return (
    <AbsoluteFill style={{background: variant === "quiet" ? "#ffffff" : PAPER, overflow: "hidden"}}>
      {(variant === "editorial" || variant === "diagram") && <div style={{position: "absolute", inset: 0, backgroundImage: `linear-gradient(${LINE} 1px, transparent 1px), linear-gradient(90deg, ${LINE} 1px, transparent 1px)`, backgroundSize: variant === "diagram" ? "72px 72px" : "96px 96px", opacity: variant === "diagram" ? .22 : .13}} />}
      
      {/* Drifting gradient mesh (Rule 5 & 7) */}
      {(variant === "editorial" || variant === "image_led") && (
        <>
          <div style={{position: "absolute", width: 900, height: 900, left: -200 + x, top: -200 + y, borderRadius: "50%", background: accent, opacity: .05, filter: "blur(80px)"}} />
          <div style={{position: "absolute", width: 900, height: 900, right: -200 - x, bottom: -200 - y, borderRadius: "50%", background: accent, opacity: .06, filter: "blur(90px)"}} />
        </>
      )}
      {chrome && <>
        <div style={{position: "absolute", left: 58, right: 58, top: 54, height: 4, borderRadius: 4, background: "rgba(10,10,11,.08)"}}><div style={{height: "100%", width: `${Math.max(2, progress * 100)}%`, background: accent, borderRadius: 4}} /></div>
        <div style={{position: "absolute", left: 58, top: 84, fontFamily: "Arial, sans-serif", fontWeight: 800, fontSize: 20, letterSpacing: 4, color: INK}}>COLONY V</div>
        <div style={{position: "absolute", right: 58, top: 84, fontFamily: "Arial, sans-serif", fontSize: 16, color: MUTED}}>INTELLIGENCE BRIEF</div>
      </>}
    </AbsoluteFill>
  );
};

const SubjectImage: React.FC<{name: string; duration: number; side?: "left" | "right"; available?: boolean; treatment?: string}> = ({name, duration, side = "right", available = true, treatment = "editorial_frame"}) => {
  if (!available) return null;
  const frame = useCurrentFrame();
  const reveal = spring({frame: frame - 8, fps: 30, config: {damping: 20, stiffness: 90}});
  
  // Subtle drift (Rule 7: idle elements breathe)
  const xDrift = Math.sin(frame / 120) * 10;
  const yDrift = Math.cos(frame / 100) * 5;
  
  // Proper Ken Burns (Rule 6)
  const scale = interpolate(frame, [0, duration], [1.0, 1.08], {extrapolateRight: "clamp", extrapolateLeft: "clamp"});

  return (
    <div style={{position: "absolute", top: treatment === "logo_mark" ? 420 : 250, [side]: treatment === "logo_mark" ? 70 : -70, width: treatment === "logo_mark" ? 420 : 660, height: treatment === "logo_mark" ? 260 : 1100, overflow: "hidden", borderRadius: treatment === "logo_mark" ? 0 : 44, background: treatment === "logo_mark" ? "transparent" : "#fff", opacity: reveal, transform: `translateX(${(1 - reveal) * (side === "right" ? 70 : -70)}px) translateY(${yDrift}px)`}}>
      <Img src={staticFile(`images/${name}.png`)} style={{width: "100%", height: "100%", objectFit: treatment === "logo_mark" ? "contain" : "cover", transform: treatment === "logo_mark" ? `scale(${.9 + reveal * .1})` : `scale(${scale}) translateX(${xDrift}px)`, filter: "saturate(.95) contrast(1.05)"}} />
      {treatment !== "logo_mark" && <div style={{position: "absolute", inset: 0, background: side === "right" ? "linear-gradient(90deg, #f8f8f6 0%, transparent 38%)" : "linear-gradient(270deg, #f8f8f6 0%, transparent 38%)"}} />}
    </div>
  );
};

const HookScene: React.FC<{text: string; duration: number; accent: string}> = ({text, duration, accent}) => {
  const frame = useCurrentFrame();
  const words = text.split(" ");
  const focusIndex = Math.max(0, words.length - 2);
  const exit = interpolate(frame, [duration - 10, duration], [1, 0], {extrapolateLeft: "clamp"});
  return (
    <AbsoluteFill style={{padding: "0 64px", opacity: exit}}>
      <SceneBackground accent={accent} variant="editorial" chrome />
      <Audio src={staticFile("audio/01_hook.mp3")} />
      <Sequence from={0} durationInFrames={Math.min(24, duration)}><Audio src={staticFile("sfx/whoosh.wav")} volume={.28} /></Sequence>
      <div style={{position: "absolute", left: 64, top: 310, ...enter(frame, 2)}}>
        <div style={{display: "inline-flex", alignItems: "center", gap: 10, fontFamily: "Arial, sans-serif", fontWeight: 700, fontSize: 18, color: accent, letterSpacing: 2}}><span style={{width: 28, height: 3, background: accent}} />BREAKING SIGNAL</div>
      </div>
      <div style={{position: "absolute", left: 64, right: 64, top: 445, fontFamily: "Arial, sans-serif", fontSize: 76, lineHeight: 1.04, fontWeight: 900, letterSpacing: -3, color: INK}}>
        {words.map((word, index) => <span key={`${word}-${index}`} style={{display: "inline-block", marginRight: 18, color: index >= focusIndex ? accent : INK, ...enter(frame, 7 + index * 2, 42)}}>{word}</span>)}
      </div>
      <div style={{position: "absolute", left: 64, bottom: 200, width: interpolate(frame, [10, 34], [0, 620], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}), height: 2, background: accent}} />
    </AbsoluteFill>
  );
};

const KineticScene: React.FC<{beat: Beat; duration: number; accent: string; index: number; total: number}> = ({beat, duration, accent, index, total}) => {
  const frame = useCurrentFrame();
  const sentences = beat.narration_text.split(/(?<=[.!?])\s+/).filter(Boolean).slice(0, 3);
  const active = Math.min(sentences.length - 1, Math.floor(frame / Math.max(1, duration / Math.max(1, sentences.length))));
  return (
    <AbsoluteFill>
      <SceneBackground accent={accent} variant={beat.visual_style === "image_led" ? "image_led" : beat.visual_style === "quiet" ? "quiet" : "editorial"} progress={(index + frame / duration) / total} />
      <SubjectImage name={beat.name} duration={duration} treatment={beat.image_treatment} available={Boolean(beat.asset_available)} />
      <Sequence from={3} durationInFrames={18}><Audio src={staticFile("sfx/pop.wav")} volume={.22} /></Sequence>
      <div style={{position: "absolute", left: 64, top: 300, width: 700}}>
        <div style={{fontFamily: "Arial, sans-serif", color: accent, fontSize: 17, fontWeight: 800, letterSpacing: 2, marginBottom: 34, ...enter(frame, 0)}}>WHAT IT MEANS</div>
        {sentences.map((sentence, i) => {
          // Staggered choregraphy (Rule 3)
          const visible = spring({frame: frame - i * 18, fps: 30, config: {damping: 16, stiffness: 120}});
          const exit = interpolate(frame, [duration - 10, duration], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
          return <div key={sentence} style={{fontFamily: "Arial, sans-serif", fontSize: i === active ? 47 : 34, lineHeight: 1.2, fontWeight: i === active ? 800 : 600, color: i === active ? INK : "rgba(10,10,11,.28)", marginBottom: 34, opacity: visible * exit, transform: `translateX(${(1-visible) * -28}px)`, transition: "none"}}><span style={{color: i === active ? accent : "transparent", marginRight: 14}}>—</span>{sentence}</div>;
        })}
      </div>
    </AbsoluteFill>
  );
};

const StatScene: React.FC<{beat: Beat; duration: number; accent: string; index: number; total: number}> = ({beat, duration, accent, index, total}) => {
  const frame = useCurrentFrame();
  const match = beat.narration_text.match(/(?:\$)?\d[\d,.]*(?:\s?(?:million|billion|trillion|M|B))?(?:\s+dollars?)?(?:%|\b)/i);
  const stat = match?.[0] || "KEY";
  const remaining = beat.narration_text.replace(stat, "").trim();
  const reveal = spring({frame: frame - 10, fps: 30, config: {damping: 13, stiffness: 100}});
  return (
    <AbsoluteFill>
      <SceneBackground accent={accent} variant="quiet" progress={(index + frame / duration) / total} />
      <Sequence from={8} durationInFrames={20}><Audio src={staticFile("sfx/ding.wav")} volume={.25} /></Sequence>
      <div style={{position: "absolute", inset: "300px 64px 220px", display: "flex", flexDirection: "column", justifyContent: "center"}}>
        <div style={{fontFamily: "Arial, sans-serif", fontSize: 18, fontWeight: 800, letterSpacing: 3, color: accent, ...enter(frame, 2)}}>THE NUMBER TO KNOW</div>
        <div style={{fontFamily: "Arial, sans-serif", fontSize: 190, lineHeight: 1, fontWeight: 900, letterSpacing: -9, color: INK, transform: `scale(${.88 + reveal * .12})`, transformOrigin: "left center", opacity: reveal, margin: "44px 0 38px"}}>{stat}</div>
        <div style={{width: interpolate(frame, [13, 38], [0, 760], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}), height: 8, background: accent, marginBottom: 42}} />
        <div style={{fontFamily: "Arial, sans-serif", fontSize: 40, lineHeight: 1.3, fontWeight: 650, maxWidth: 850, color: INK, ...enter(frame, 26)}}>{remaining}</div>
      </div>
    </AbsoluteFill>
  );
};

const DiagramScene: React.FC<{beat: Beat; duration: number; accent: string; index: number; total: number}> = ({beat, duration, accent, index, total}) => {
  const frame = useCurrentFrame();
  const words = beat.narration_text.split(" ");
  const middle = Math.ceil(words.length / 2);
  const boxes = [words.slice(0, middle).join(" "), words.slice(middle).join(" ")];
  const path = interpolate(frame, [20, 50], [0, 100], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill>
      <SceneBackground accent={accent} variant="diagram" progress={(index + frame / duration) / total} />
      <Sequence from={18} durationInFrames={18}><Audio src={staticFile("sfx/whoosh.wav")} volume={.2} /></Sequence>
      <div style={{position: "absolute", left: 64, top: 270, fontFamily: "Arial, sans-serif", fontSize: 17, fontWeight: 800, letterSpacing: 3, color: accent, ...enter(frame, 0)}}>HOW IT CONNECTS</div>
      <div style={{position: "absolute", left: 64, right: 64, top: 470, display: "flex", alignItems: "center", gap: 24}}>
        {boxes.map((box, i) => <React.Fragment key={i}>
          <div style={{flex: 1, minHeight: 430, padding: 38, display: "flex", flexDirection: "column", justifyContent: "space-between", border: `2px solid ${i === 0 ? INK : accent}`, background: "rgba(255,255,255,.74)", borderRadius: 28, ...enter(frame, i * 18 + 4, 50)}}>
            <div style={{fontFamily: "Arial, sans-serif", fontSize: 16, fontWeight: 800, color: i === 0 ? MUTED : accent, letterSpacing: 2}}>STEP 0{i + 1}</div>
            <div style={{fontFamily: "Arial, sans-serif", fontSize: 33, lineHeight: 1.24, fontWeight: 750, color: INK}}>{box}</div>
          </div>
          {i === 0 && <div style={{width: 90}}><div style={{height: 4, width: `${path}%`, background: accent}} /><div style={{textAlign: "right", color: accent, fontSize: 32}}>›</div></div>}
        </React.Fragment>)}
      </div>
    </AbsoluteFill>
  );
};

const TimelineScene: React.FC<{beat: Beat; duration: number; accent: string; index: number; total: number}> = ({beat, duration, accent, index, total}) => {
  const frame = useCurrentFrame();
  const events = beat.narration_text.split(/\s*\|\s*|(?<=[.!?])\s+/).filter(Boolean).slice(0, 3);
  const line = interpolate(frame, [12, duration * .55], [0, 100], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill>
      <SceneBackground accent={accent} variant="editorial" progress={(index + frame / duration) / total} />
      <div style={{position: "absolute", left: 64, top: 300, fontFamily: "Arial, sans-serif", fontSize: 17, fontWeight: 800, letterSpacing: 3, color: accent, ...enter(frame, 0)}}>THE SEQUENCE</div>
      <div style={{position: "absolute", left: 94, right: 94, top: 620, height: 4, background: "rgba(10,10,11,.12)"}}><div style={{height: "100%", width: `${line}%`, background: accent}} /></div>
      <div style={{position: "absolute", left: 64, right: 64, top: 565, display: "grid", gridTemplateColumns: `repeat(${Math.max(1, events.length)}, minmax(0, 1fr))`, gap: 32}}>
        {events.map((event, i) => {
          const point = spring({frame: frame - 18 - i * 18, fps: 30, config: {damping: 16, stiffness: 100}});
          return <div key={event} style={{minWidth: 0, transform: `translateY(${(1 - point) * 34}px)`, opacity: point}}><div style={{width: 24, height: 24, margin: "0 auto", borderRadius: "50%", background: i === events.length - 1 ? accent : INK, border: `6px solid ${PAPER}`, boxShadow: `0 0 0 2px ${i === events.length - 1 ? accent : INK}`}} /><div style={{marginTop: 34, padding: "0 8px", textAlign: "center", fontFamily: "Arial, sans-serif", fontSize: 25, lineHeight: 1.25, fontWeight: 700, color: INK}}>{event}</div></div>;
        })}
      </div>
    </AbsoluteFill>
  );
};

const QuietScene: React.FC<{beat: Beat; duration: number; accent: string; index: number; total: number}> = ({beat, duration, accent}) => {
  const frame = useCurrentFrame();
  const words = beat.narration_text.split(" ");
  return (
    <AbsoluteFill>
      <SceneBackground accent={accent} variant="quiet" />
      <Sequence from={4} durationInFrames={18}><Audio src={staticFile("sfx/ding.wav")} volume={.12} /></Sequence>
      <div style={{position: "absolute", inset: "260px 76px", display: "flex", flexDirection: "column", justifyContent: "center"}}>
        <div style={{width: interpolate(frame, [4, 28], [0, 110], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}), height: 5, background: accent, marginBottom: 46}} />
        <div style={{fontFamily: "Arial, sans-serif", fontSize: 66, lineHeight: 1.1, fontWeight: 850, letterSpacing: -2.5, color: INK}}>{words.map((word, i) => <span key={`${word}-${i}`} style={{display: "inline-block", marginRight: 16, ...enter(frame, 8 + i * 2, 28)}}>{word}</span>)}</div>
        <div style={{fontFamily: "Arial, sans-serif", marginTop: 48, fontSize: 16, fontWeight: 800, letterSpacing: 3, color: accent, ...enter(frame, 28)}}>THE TAKEAWAY</div>
      </div>
    </AbsoluteFill>
  );
};

const OutroScene: React.FC<{text: string; duration: number; accent: string}> = ({text, duration, accent}) => {
  const frame = useCurrentFrame();
  const logo = spring({frame: frame - 4, fps: 30, config: {damping: 15, stiffness: 100}});
  return (
    <AbsoluteFill>
      <SceneBackground accent={accent} variant="quiet" chrome />
      <Audio src={staticFile("audio/03_cta.mp3")} />
      <Sequence from={3} durationInFrames={20}><Audio src={staticFile("sfx/ding.wav")} volume={.22} /></Sequence>
      <div style={{position: "absolute", inset: 64, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center"}}>
        <div style={{width: 116, height: 116, borderRadius: "50%", background: INK, color: PAPER, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "Arial, sans-serif", fontSize: 32, fontWeight: 900, transform: `scale(${logo})`}}>CV</div>
        <div style={{fontFamily: "Arial, sans-serif", fontSize: 54, lineHeight: 1.12, fontWeight: 850, color: INK, maxWidth: 820, marginTop: 48, ...enter(frame, 15)}}>{text}</div>
        <div style={{fontFamily: "Arial, sans-serif", fontSize: 19, fontWeight: 800, color: accent, letterSpacing: 3, marginTop: 38, ...enter(frame, 25)}}>FOLLOW THE SIGNAL</div>
      </div>
    </AbsoluteFill>
  );
};

const Vignette: React.FC = () => (
  <AbsoluteFill style={{pointerEvents: "none", background: "radial-gradient(circle at center, transparent 30%, rgba(0,0,0,0.3) 150%)"}} />
);

const Grain: React.FC = () => {
  const frame = useCurrentFrame();
  const seed = (frame % 4) * 50;
  return (
    <AbsoluteFill style={{pointerEvents: "none", opacity: 0.28, backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='1.2' numOctaves='3' stitchTiles='stitch' seed='${seed}'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")`}} />
  );
};

export const ContentVideo: React.FC<VideoProps> = ({script}) => {
  const allText = `${script.hook} ${script.body}`;
  const accent = accentFor(allText);
  const beatKeys = Object.keys(beats);
  const bodyFrames = Object.values(beats).reduce((sum, value) => sum + value, 0);
  const totalFrames = hookFrames + bodyFrames + outroFrames;
  let cursor = hookFrames;

  return (
    <AbsoluteFill style={{background: PAPER}}>
      <Sequence from={0} durationInFrames={hookFrames}><HookScene text={script.hook} duration={hookFrames} accent={accent} /></Sequence>
      {beatKeys.map((name, index) => {
        const duration = beats[name];
        const from = cursor;
        cursor += duration;
        const beat = script.suggested_visual_beats.find((item) => item.name === name) || script.suggested_visual_beats[index] || {name, narration_text: ""};
        const type = beat.beat_type || "kinetic_text";
        const Scene = beat.visual_style === "timeline" ? TimelineScene : beat.visual_style === "quiet" ? QuietScene : type === "stat_reveal" ? StatScene : type === "diagram" ? DiagramScene : KineticScene;
        return (
          <Sequence key={name} from={from} durationInFrames={duration}>
            <Audio src={staticFile(`audio/beat_${String(index + 1).padStart(2, "0")}.mp3`)} />
            <Scene beat={beat} duration={duration} accent={accent} index={index} total={beatKeys.length} />
          </Sequence>
        );
      })}
      <Sequence from={totalFrames - outroFrames} durationInFrames={outroFrames}><OutroScene text={script.cta} duration={outroFrames} accent={accent} /></Sequence>
      
      {/* 5-layer stack rule: Grade + Grain + Vignette on top */}
      <div style={{position: "absolute", inset: 0, pointerEvents: "none", mixBlendMode: "overlay", opacity: 0.15, background: "linear-gradient(45deg, #101014 0%, transparent 100%)"}} />
      <Grain />
      <Vignette />
    </AbsoluteFill>
  );
};
