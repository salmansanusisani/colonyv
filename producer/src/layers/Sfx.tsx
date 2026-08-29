import React from "react";
import { Audio, Sequence, staticFile } from "remotion";
import type { Shot } from "../types";

/**
 * Sound design layer.
 *
 * Cues are derived, not authored. The Art Director already decides a
 * `motion_language` for the episode — precise, energetic, calm or urgent — which
 * is exactly the signal sound design needs, so no extra model call or new
 * failure mode is introduced to get it.
 *
 * The important property is that cue timings are computed from the *same* delay
 * values the visual layers animate on, rather than being hand-tuned numbers kept
 * in sync by hope. If a layout's reveal delay changes, its sound moves with it.
 *
 * Everything is mixed well under the narration. Sound here is punctuation; if a
 * viewer notices it as a separate element, it is too loud.
 */

type CueName = "tick" | "swoosh" | "riser" | "stamp" | "chime";

interface Cue {
  name: CueName;
  /** Frame within the shot, relative to the shot's own start. */
  at: number;
  volume: number;
}

/** Per-episode character. Density scales how much incidental ticking happens. */
interface SoundCharacter {
  gain: number;
  density: number;
  /** Use the riser on the hook. */
  riser: boolean;
}

const CHARACTER: Record<string, SoundCharacter> = {
  precise: { gain: 1.0, density: 1.0, riser: false },
  energetic: { gain: 1.15, density: 1.35, riser: true },
  calm: { gain: 0.72, density: 0.55, riser: false },
  urgent: { gain: 1.2, density: 1.15, riser: true },
};

const characterFor = (motionKey?: string): SoundCharacter =>
  CHARACTER[motionKey ?? "precise"] ?? CHARACTER.precise;

/** Base levels per cue, before episode gain. Deliberately conservative. */
const BASE_VOLUME: Record<CueName, number> = {
  tick: 0.13,
  swoosh: 0.15,
  riser: 0.17,
  stamp: 0.2,
  chime: 0.18,
};

/**
 * These mirror the `delay` props passed to the layers in layouts.tsx. Kept
 * together here, and named, so the coupling is visible rather than accidental.
 */
const DELAY = {
  copyWithArt: 8,
  copyPlain: 2,
  plate: 0,
  data: 12,
  diagram: 16,
  /** Per-item stagger inside NodeFlow / CompareTwoUp / TimelineRail. */
  itemStagger: 7,
  /** Per-word stagger inside a headline. */
  wordStagger: 2.5,
} as const;

const isMovingTransition = (kind?: string) =>
  kind === "slide" || kind === "dot_wipe" || kind === "rule_wipe";

/**
 * Build the cue list for one shot.
 *
 * Exported so it can be reasoned about and tested independently of rendering.
 */
export const sfxCuesFor = (
  shot: Shot,
  duration: number,
  motionKey: string | undefined,
  isFirst: boolean,
): Cue[] => {
  const character = characterFor(motionKey);
  const cues: Cue[] = [];
  const push = (name: CueName, at: number, scale = 1) => {
    if (at < 0 || at >= duration) return;
    cues.push({ name, at: Math.round(at), volume: BASE_VOLUME[name] * character.gain * scale });
  };

  const hasArt = Boolean(shot.illustration?.file);

  // --- Entry ---------------------------------------------------------------
  if (isFirst && character.riser) {
    // The riser leads slightly so its peak lands on the first headline word.
    push("riser", Math.max(0, DELAY.copyPlain - 12));
  }
  if (isMovingTransition(shot.transition_in)) {
    push("swoosh", 0);
  }

  // --- Artwork arriving ----------------------------------------------------
  if (hasArt) {
    push("swoosh", DELAY.plate, 0.75);
  }

  // --- Copy ----------------------------------------------------------------
  const copyAt = hasArt ? DELAY.copyWithArt : DELAY.copyPlain;
  if (shot.kicker) {
    push("tick", copyAt, 0.85);
  }
  // One tick for the emphasised word rather than one per word, which at 30fps
  // turns into a machine-gun rattle.
  const emphasis = shot.emphasis_words ?? [];
  if (emphasis.length > 0 && character.density >= 1) {
    const words = (shot.headline ?? "").split(/\s+/);
    const index = words.findIndex((w) =>
      emphasis.some((e) => w.toLowerCase().includes(e.toLowerCase())),
    );
    if (index > 0) {
      push("tick", copyAt + 6 + index * DELAY.wordStagger, 0.7);
    }
  }

  // --- Layout-specific ------------------------------------------------------
  switch (shot.layout) {
    case "data_readout": {
      // The stamp lands when the counter settles, not when it starts: the spring
      // in Readout is configured to reach its target in 20 frames.
      push("stamp", DELAY.data + 20);
      break;
    }
    case "node_flow":
    case "compare_two_up": {
      const nodes = shot.nodes ?? [];
      nodes.forEach((node, i) => {
        push("tick", DELAY.diagram + i * DELAY.itemStagger, 0.8);
        // A resolved end-state earns a stamp; this is the audible half of the
        // semantic accent.
        if (node.state === "good" || node.state === "bad") {
          push("stamp", DELAY.diagram + i * DELAY.itemStagger + 4, 0.5);
        }
      });
      break;
    }
    case "timeline_rail": {
      (shot.events ?? []).forEach((_, i) => {
        push("tick", DELAY.diagram + i * DELAY.itemStagger, 0.8);
      });
      break;
    }
    case "quote_block": {
      push("tick", copyAt, 0.6);
      break;
    }
    case "outro_brand": {
      push("chime", 6);
      break;
    }
    default:
      break;
  }

  // Annotations point at things; each gets a light tick as its leader draws.
  (shot.annotations ?? []).forEach((_, i) => {
    if (character.density < 1 && i > 0) return;
    push("tick", DELAY.diagram + 10 + i * DELAY.itemStagger, 0.55);
  });

  // Guard against cues stacking on the same frame, which sums amplitude and
  // reads as a click rather than as two sounds.
  const seen = new Set<string>();
  const deduped = cues.filter((cue) => {
    const key = `${cue.name}@${cue.at}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  // Hard cap per shot. Protects both the mix and the render: sound is
  // punctuation, and a shot needing more than this many cues is being over-scored.
  const MAX_CUES = 9;
  return deduped.sort((a, b) => a.at - b.at).slice(0, MAX_CUES);
};

/**
 * Length of each cue in frames at 30fps, rounded up from the synthesised WAV.
 *
 * Each cue's Sequence is bounded to its own length. Letting a cue's Sequence run
 * to the end of the shot instead — which is the obvious thing to write — makes
 * Remotion allocate and mix a full-length track per cue. With roughly thirty
 * cues in a video that stalled the audio stage indefinitely.
 */
const CUE_FRAMES: Record<CueName, number> = {
  tick: 3,
  swoosh: 11,
  riser: 27,
  stamp: 9,
  chime: 23,
};

export const Sfx: React.FC<{
  shot: Shot;
  duration: number;
  motionKey?: string;
  isFirst?: boolean;
  /** Global mute, used by the still-frame smoke test. */
  enabled?: boolean;
}> = ({ shot, duration, motionKey, isFirst = false, enabled = true }) => {
  if (!enabled) return null;
  const cues = sfxCuesFor(shot, duration, motionKey, isFirst);

  return (
    <>
      {cues.map((cue, i) => (
        <Sequence
          key={`${cue.name}-${cue.at}-${i}`}
          from={cue.at}
          durationInFrames={Math.max(1, Math.min(CUE_FRAMES[cue.name], duration - cue.at))}
          name={`sfx:${cue.name}`}
          layout="none"
        >
          <Audio src={staticFile(`sfx/${cue.name}.wav`)} volume={cue.volume} />
        </Sequence>
      ))}
    </>
  );
};
