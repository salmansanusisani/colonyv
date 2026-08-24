import React from "react";
import { Composition } from "remotion";
import { ContentVideo } from "./Video";
import timing from "./timing.json";

const { hookFrames, outroFrames, beats } = timing;
const bodyFrames = Object.values(beats).reduce((a: number, b: number) => a + b, 0);
const totalFrames = hookFrames + bodyFrames + outroFrames;

// Demo defaults: only reference files that always exist in public/audio/
const DEMO_PROPS = {
  script: {
    hook: "Demo hook.",
    body: "Demo body.",
    cta: "Demo CTA.",
    estimated_duration: 10,
    format: "demo",
    claims_used: [],
    suggested_visual_beats: [
      { name: "beat_01", narration_text: "Demo beat.", beat_type: "kinetic_text" },
    ],
  },
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="ContentVideo"
      component={ContentVideo as any}
      durationInFrames={totalFrames}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={DEMO_PROPS as any}
    />
  );
};
