import { Easing } from "remotion";

export const theme = {
  colors: {
    bg: "#0A0A0F",
    bgCard: "#12121A",
    bgCardBorder: "rgba(255, 255, 255, 0.08)",
    primary: "#7C3AED", // Vibrant purple hero
    accent: "#22D3EE",  // Cyan highlight
    text: "#F4F4F5",
    textMuted: "#A1A1AA",
    glow: "rgba(124, 58, 237, 0.4)",
  },
  fonts: {
    display: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    mono: "monospace",
  },
  ease: {
    out: Easing.bezier(0.16, 1, 0.3, 1),
    inOut: Easing.bezier(0.83, 0, 0.17, 1),
    in: Easing.bezier(0.7, 0, 0.84, 0),
  },
  spring: {
    snappy: { damping: 14, stiffness: 160, mass: 0.6 },
    smooth: { damping: 20, stiffness: 90, mass: 1 },
    bouncy: { damping: 11, stiffness: 170, mass: 0.7 },
  },
} as const;
