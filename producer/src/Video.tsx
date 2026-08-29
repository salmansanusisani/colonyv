import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import { loadFont as loadDisplay } from "@remotion/google-fonts/Archivo";
import { loadFont as loadMono } from "@remotion/google-fonts/IBMPlexMono";
import { palette, semantic } from "./theme";
import { HOOK_BEAT, OUTRO_BEAT } from "./types";
import type { Shot, Timing, VideoProps, VisualPlan } from "./types";
import { ShotComposition } from "./layouts";
import { Transition } from "./layers/Transition";
import { Sfx } from "./layers/Sfx";

// Fonts are loaded at module scope so Remotion registers the pending handles
// before the first frame is rasterised. Without this the first shots render in
// the fallback face and the video visibly re-flows.
//
// Weights and subsets are pinned deliberately. Loading the full families issued
// ~186 font requests per Chromium tab, which slowed every render and made the
// job depend on outbound network access at render time.
loadDisplay("normal", {
  weights: ["700", "800"],
  subsets: ["latin"],
  ignoreTooManyRequestsWarning: true,
});
loadMono("normal", {
  weights: ["500", "600"],
  subsets: ["latin"],
  ignoreTooManyRequestsWarning: true,
});

const DEFAULT_TIMING: Timing = { hookFrames: 60, outroFrames: 60, beats: {} };

/**
 * Resolve the accent colour.
 *
 * Semantic roles own their hue so the channel keeps a consistent visual grammar:
 * green always means confirmed, red always means failure. `topic` lets the
 * director introduce a subject-specific hue, and `neutral` stays monochrome.
 *
 * This replaces the previous approach, which regex-matched keywords in the
 * narration ("nvidia" -> emerald, "bitcoin" -> orange). That was a lookup table
 * masquerading as a decision and meant the colour carried no information.
 */
const resolveAccent = (plan: VisualPlan | undefined): string => {
  const p = plan?.palette;
  if (!p) return semantic.neutral;
  switch (p.accent_role) {
    case "verified":
      return semantic.verified;
    case "alert":
      return semantic.alert;
    case "neutral":
      return semantic.neutral;
    case "topic":
    default:
      return p.accent && /^#[0-9a-fA-F]{6}$/.test(p.accent) ? p.accent : semantic.neutral;
  }
};

/**
 * Build the render timeline.
 *
 * Audio and visuals are bound by the same ordered list, so a shot can never
 * drift away from its narration. The previous implementation indexed audio by
 * position (`beat_01.mp3`) while matching scenes by name, which desynchronised
 * whenever the two orderings disagreed.
 */
interface TimelineEntry {
  key: string;
  from: number;
  duration: number;
  shot: Shot;
  audio: string;
}

const buildTimeline = (
  timing: Timing,
  plan: VisualPlan | undefined,
  script: VideoProps["script"],
): { entries: TimelineEntry[]; total: number } => {
  const beatNames = Object.keys(timing.beats ?? {});
  const shots = plan?.shots ?? [];

  const shotFor = (name: string, fallbackIndex: number): Shot => {
    const exact = shots.find((s) => s.beat_name === name);
    if (exact) return exact;
    const positional = shots[fallbackIndex];
    if (positional) return positional;
    return { beat_name: name, layout: "hero_statement" };
  };

  const entries: TimelineEntry[] = [];
  let cursor = 0;

  // Hook.
  const hookShot = shotFor(HOOK_BEAT, 0);
  entries.push({
    key: HOOK_BEAT,
    from: cursor,
    duration: timing.hookFrames,
    audio: "audio/01_hook.mp3",
    shot: {
      ...hookShot,
      headline: hookShot.headline || script?.hook || "",
    },
  });
  cursor += timing.hookFrames;

  // Body beats, in the exact order the producer measured audio for.
  beatNames.forEach((name, i) => {
    const duration = timing.beats[name] ?? 90;
    const shot = shotFor(name, i + 1);
    const narration = script?.suggested_visual_beats?.find((b) => b.name === name)?.narration_text;
    entries.push({
      key: name,
      from: cursor,
      duration,
      audio: `audio/beat_${String(i + 1).padStart(2, "0")}.mp3`,
      shot: {
        ...shot,
        // Fall back to narration only if the director gave no on-screen copy.
        headline: shot.headline || narration || "",
      },
    });
    cursor += duration;
  });

  // Outro.
  const outroShot = shotFor(OUTRO_BEAT, beatNames.length + 1);
  entries.push({
    key: OUTRO_BEAT,
    from: cursor,
    duration: timing.outroFrames,
    audio: "audio/03_cta.mp3",
    shot: {
      ...outroShot,
      layout: "outro_brand",
      headline: outroShot.headline || script?.cta || "",
    },
  });
  cursor += timing.outroFrames;

  return { entries, total: cursor };
};

export const ContentVideo: React.FC<VideoProps> = ({
  script,
  timing,
  visualPlan,
  brand,
  sfx,
}) => {
  const runTiming: Timing = {
    hookFrames: timing?.hookFrames ?? DEFAULT_TIMING.hookFrames,
    outroFrames: timing?.outroFrames ?? DEFAULT_TIMING.outroFrames,
    beats: timing?.beats ?? DEFAULT_TIMING.beats,
  };

  const accent = resolveAccent(visualPlan);
  const motionKey = visualPlan?.motion_language ?? "precise";
  const { entries, total } = buildTimeline(runTiming, visualPlan, script);

  // The footer labels the document. The script's format string ("stat-heavy
  // explainer") is the most useful short descriptor the pipeline already has.
  const docLabel = script?.format || "Editorial brief";
  // Body shots only; the hook and outro are not numbered sheets.
  const sheetTotal = Math.max(1, entries.length - 2);

  return (
    <AbsoluteFill style={{ backgroundColor: palette.ground }}>
      {entries.map((entry, i) => (
        <Sequence
          key={entry.key}
          from={entry.from}
          durationInFrames={entry.duration}
          // Named layers make the Remotion Studio timeline readable, which
          // matters when debugging a mis-timed shot.
          name={`${entry.shot.layout} · ${entry.key}`}
        >
          <Audio src={staticFile(entry.audio)} />
          <Sfx
            shot={entry.shot}
            duration={entry.duration}
            motionKey={motionKey}
            isFirst={i === 0}
            enabled={sfx !== false}
          />
          <Transition
            kind={entry.shot.transition_in}
            accent={accent}
            frames={Math.min(16, Math.max(6, Math.round(entry.duration * 0.12)))}
          >
            <ShotComposition
              shot={entry.shot}
              accent={accent}
              duration={entry.duration}
              motionKey={motionKey}
              progress={total > 0 ? (entry.from + entry.duration / 2) / total : 0}
              logo={brand?.logo}
              brand={brand}
              index={Math.max(1, Math.min(sheetTotal, i))}
              total={sheetTotal}
              docLabel={docLabel}
            />
          </Transition>
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

/** Exported so Root.tsx can derive composition duration from the same logic. */
export const totalFramesFor = (
  timing: Timing | undefined,
  plan?: VisualPlan,
  script?: VideoProps["script"],
): number => {
  if (!timing) return 180;
  return buildTimeline(timing, plan, script).total;
};
