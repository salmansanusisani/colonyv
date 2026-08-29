import React from "react";
import { Composition } from "remotion";
import type { CalculateMetadataFunction } from "remotion";
import { CANVAS } from "./theme";
import { ContentVideo, totalFramesFor } from "./Video";
import type { VideoProps } from "./types";

/**
 * Composition registration.
 *
 * Duration is derived from the incoming props via `calculateMetadata` rather than
 * from a build-time `import timing from "./timing.json"`.
 *
 * The previous approach had three concrete problems:
 *   1. Remotion resolved the duration when the bundle was built, so the producer
 *      had to overwrite src/timing.json immediately before every render.
 *   2. Two renders running at once raced on that shared file and could each
 *      receive the other's duration.
 *   3. Remotion Studio always showed whichever run happened to write the file
 *      last, making the preview useless for debugging timing.
 *
 * Reading from props removes the shared mutable file from the render path
 * entirely.
 */

const DEMO_PROPS: VideoProps = {
  script: {
    hook: "An eighty four thousand dollar degree in two semesters.",
    body: "Demo body.",
    cta: "Subscribe for more.",
    suggested_visual_beats: [{ name: "beat_01_demo", narration_text: "Demo beat narration." }],
  },
  timing: {
    hookFrames: 90,
    outroFrames: 90,
    beats: { beat_01_demo: 120 },
  },
  visualPlan: {
    concept: "Preview composition",
    palette: { accent_role: "alert" },
    motion_language: "precise",
    shots: [
      {
        beat_name: "__hook__",
        layout: "hero_statement",
        kicker: "Preview",
        headline: "An $84,000 degree in two semesters",
        emphasis_words: ["$84,000"],
        type_scale: "xl",
        text_anchor: "center",
        transition_in: "cut",
      },
      {
        beat_name: "beat_01_demo",
        layout: "data_readout",
        kicker: "Tuition premium",
        headline: "The cost of accelerated credentials",
        type_scale: "md",
        data: { value: "84,000", prefix: "$", label: "Two-semester tuition" },
        transition_in: "rule_wipe",
      },
      {
        beat_name: "__outro__",
        layout: "outro_brand",
        headline: "Subscribe for deep tech briefings",
        transition_in: "fade",
      },
    ],
  },
  brand: { logo: "brand/logo_mark.png", handle: "@colonyv", ctaLabel: "Subscribe" },
};

/**
 * Duration is a pure function of the measured narration timing, so the composition
 * length always matches the audio the producer actually generated.
 */
const calculateMetadata: CalculateMetadataFunction<VideoProps> = ({ props }) => ({
  durationInFrames: Math.max(
    1,
    totalFramesFor(props.timing, props.visualPlan, props.script),
  ),
});

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="ContentVideo"
      component={ContentVideo}
      fps={CANVAS.fps}
      width={CANVAS.width}
      height={CANVAS.height}
      defaultProps={DEMO_PROPS}
      calculateMetadata={calculateMetadata}
    />
  );
};
