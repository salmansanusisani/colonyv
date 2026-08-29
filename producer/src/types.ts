/**
 * TypeScript mirror of contracts/visual_plan.schema.json.
 *
 * Everything here is optional-by-default on purpose: the plan is authored by a
 * language model and sanitised in Python, but the renderer must still degrade
 * gracefully rather than crash a 30-minute render on one missing field.
 */

export type StateKey = "neutral" | "good" | "bad";

export type Layout =
  | "hero_statement"
  | "illustration_full"
  | "illustration_top"
  | "illustration_side"
  | "data_readout"
  | "node_flow"
  | "timeline_rail"
  | "compare_two_up"
  | "quote_block"
  | "outro_brand";

export type TransitionKey = "cut" | "dot_wipe" | "rule_wipe" | "slide" | "fade";

export type IllustrationMotion = "still" | "drift" | "push_in" | "pull_out" | "parallax";

export interface Palette {
  ground?: string;
  ink?: string;
  accent?: string;
  accent_role?: "verified" | "alert" | "neutral" | "topic";
  accent_rationale?: string;
}

export interface Illustration {
  prompt?: string;
  priority?: number;
  motion?: IllustrationMotion;
  /** Filled in by producer/illustrate.py once the art actually exists. */
  file?: string;
}

export interface DataReadout {
  value?: string;
  prefix?: string;
  suffix?: string;
  label?: string;
  trend?: "up" | "down" | "flat";
}

export interface NodeItem {
  label?: string;
  detail?: string;
  state?: StateKey;
}

export interface EventItem {
  label?: string;
  marker?: string;
  state?: StateKey;
}

export interface Annotation {
  text?: string;
  at?:
    | "top_left"
    | "top_right"
    | "mid_left"
    | "mid_right"
    | "bottom_left"
    | "bottom_right";
  state?: StateKey;
}

export interface Shot {
  beat_name: string;
  layout: Layout;
  headline?: string;
  kicker?: string;
  emphasis_words?: string[];
  type_scale?: "xl" | "lg" | "md" | "sm";
  text_anchor?: "top" | "center" | "bottom";
  illustration?: Illustration;
  data?: DataReadout;
  nodes?: NodeItem[];
  events?: EventItem[];
  annotations?: Annotation[];
  transition_in?: TransitionKey;
}

export interface VisualPlan {
  concept?: string;
  palette?: Palette;
  illustration_style?: string;
  motion_language?: string;
  shots?: Shot[];
}

export interface Timing {
  hookFrames: number;
  outroFrames: number;
  /** Ordered map of beat name to duration in frames. */
  beats: Record<string, number>;
}

export interface Script {
  hook?: string;
  body?: string;
  cta?: string;
  format?: string;
  suggested_visual_beats?: { name: string; narration_text?: string }[];
}

export interface VideoProps {
  /** Sound design on/off. Only disabled by the render smoke test. */
  sfx?: boolean;
  script?: Script;
  timing?: Timing;
  visualPlan?: VisualPlan;
  /** Brand assets resolved to public/ paths by the producer. */
  brand?: {
    logo?: string;
    wordmark?: string;
    handle?: string;
    ctaLabel?: string;
  };
  /**
   * Remotion constrains composition props to Record<string, unknown>. The index
   * signature satisfies that constraint while the named fields above stay typed.
   */
  [key: string]: unknown;
}

/** The two synthetic beat names the plan uses for hook and outro. */
export const HOOK_BEAT = "__hook__";
export const OUTRO_BEAT = "__outro__";
