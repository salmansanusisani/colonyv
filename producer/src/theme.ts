import { Easing } from "remotion";

/**
 * COLONY V visual system.
 *
 * The channel reads as a precision technical manual: warm paper ground, a faint
 * pegboard perforation grid, drafted near-black linework, and exactly one accent
 * colour that carries meaning rather than decoration.
 *
 * Ground and ink are fixed brand constants. Only the accent varies per episode,
 * and the Art Director chooses it from the story's outcome — which is why the
 * accent is addressed by role (`verified` / `alert` / `neutral` / `topic`) rather
 * than by hue anywhere in the render tree.
 */

export const CANVAS = {
  width: 1080,
  height: 1920,
  fps: 30,
  /** Side margin. Everything typographic aligns to this column. */
  margin: 88,
  /** Vertical safe area kept clear of platform UI. */
  safeTop: 150,
  safeBottom: 260,
} as const;

export const palette = {
  ground: "#F6F5F1",
  groundAlt: "#EFEEE8",
  groundSunk: "#E7E5DC",
  /** Pegboard perforation dots. */
  dot: "#D3D1C7",
  /** Hairline rules and leader lines. */
  rule: "#C6C4B9",
  ink: "#14150F",
  inkSoft: "#57574E",
  inkFaint: "#8C8B80",
  paperShade: "rgba(20, 21, 15, 0.06)",
} as const;

/** Semantic accents. These are the only hues the system may introduce. */
export const semantic = {
  verified: "#1F9D55",
  alert: "#D14343",
  neutral: palette.ink,
} as const;

export type StateKey = "neutral" | "good" | "bad";

/** Resolve a node/annotation state to a colour, given the episode accent. */
export const stateColor = (state: StateKey | undefined, accent: string): string => {
  if (state === "good") return semantic.verified;
  if (state === "bad") return semantic.alert;
  return accent;
};

export const fonts = {
  display: `Archivo, "Helvetica Neue", "Liberation Sans", Arimo, system-ui, sans-serif`,
  mono: `"IBM Plex Mono", "DejaVu Sans Mono", "Fira Code", ui-monospace, monospace`,
} as const;

/** Headline size bands, chosen so 8 words always fit the 904px text column. */
export const typeScale = {
  xl: { size: 104, tracking: -3.4, leading: 0.98, weight: 800 },
  lg: { size: 78, tracking: -2.4, leading: 1.04, weight: 800 },
  md: { size: 60, tracking: -1.6, leading: 1.1, weight: 700 },
  sm: { size: 46, tracking: -1, leading: 1.16, weight: 700 },
} as const;

export type TypeScaleKey = keyof typeof typeScale;

export const kickerStyle = {
  fontFamily: fonts.mono,
  fontSize: 22,
  fontWeight: 600,
  letterSpacing: 4.2,
  textTransform: "uppercase" as const,
};

/**
 * Motion language. `precise` is the house default: fast settle, almost no
 * overshoot, so the frame feels drafted rather than bouncy. Springs are
 * intentionally well damped because underdamped springs combined with large
 * type caused visible sub-pixel shimmer in earlier renders.
 */
export const motion = {
  precise: {
    spring: { damping: 26, stiffness: 130, mass: 0.9 },
    stagger: 2.5,
    enterFrames: 14,
  },
  energetic: {
    spring: { damping: 15, stiffness: 190, mass: 0.7 },
    stagger: 1.8,
    enterFrames: 10,
  },
  calm: {
    spring: { damping: 32, stiffness: 74, mass: 1.1 },
    stagger: 4,
    enterFrames: 20,
  },
  urgent: {
    spring: { damping: 19, stiffness: 235, mass: 0.65 },
    stagger: 1.4,
    enterFrames: 8,
  },
} as const;

export type MotionKey = keyof typeof motion;

export const motionFor = (key: string | undefined): (typeof motion)[MotionKey] =>
  motion[(key as MotionKey) in motion ? (key as MotionKey) : "precise"];

export const ease = {
  out: Easing.bezier(0.16, 1, 0.3, 1),
  inOut: Easing.bezier(0.65, 0, 0.35, 1),
  in: Easing.bezier(0.7, 0, 0.84, 0),
} as const;

/** Pegboard geometry. Must match the illustration prompt's described ground. */
export const pegboard = {
  spacing: 34,
  radius: 1.6,
} as const;

export const theme = {
  CANVAS,
  palette,
  semantic,
  fonts,
  typeScale,
  motion,
  ease,
  pegboard,
} as const;
