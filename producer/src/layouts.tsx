import React from "react";
import { AbsoluteFill } from "remotion";
import { CANVAS, typeScale } from "./theme";
import type { Shot } from "./types";
import {
  Footer,
  Paper,
  PegboardOverlay,
  ProgressRule,
  RegistrationMarks,
  contentWidth,
} from "./layers/Paper";
import { PlateBand, PlateFull, PlateSide } from "./layers/Plate";
import { CopyBlock, QuoteBlock } from "./layers/Copy";
import { CompareTwoUp, NodeFlow, Readout, TimelineRail } from "./layers/Data";
import { Callouts } from "./layers/Callout";
import { BrandOutro, Watermark } from "./layers/Brand";

/**
 * Layout composer.
 *
 * This is the heart of the change from the previous system. Before, six fixed
 * scene components existed and the model's only creative act was naming one of
 * them; every video therefore had the same six possible looks, with hardcoded
 * on-screen labels like "KEY TAKEAWAY".
 *
 * Now a shot is assembled from independent layers — paper, plate, copy, data,
 * diagram, callouts, brand — and the Art Director decides which layers appear,
 * where the type sits, what it says, and how the camera moves. Illustration is
 * available to every layout rather than to one, which is why art no longer gets
 * silently dropped when a shot happens to be data-led.
 */

interface ShotProps {
  shot: Shot;
  accent: string;
  duration: number;
  motionKey?: string;
  /** 0..1 position through the whole video, for the progress rule. */
  progress: number;
  logo?: string;
  brand?: { handle?: string; ctaLabel?: string };
  /** 1-based shot position and total, for the page footer. */
  index?: number;
  total?: number;
  /** Short document label shown in the footer. */
  docLabel?: string;
}

/**
 * Layouts whose content does not naturally fill a 1920px frame. These centre
 * their column so the remaining space is balanced above and below, rather than
 * collecting at the bottom and reading as an unfinished slide.
 */
const SELF_CONTAINED = new Set<Shot["layout"]>([
  "node_flow",
  "compare_two_up",
  "timeline_rail",
  "quote_block",
]);

/** One band down, used where a narrower column needs smaller type. */
const stepDown = (scale: keyof typeof typeScale): keyof typeof typeScale =>
  scale === "xl" ? "lg" : scale === "lg" ? "md" : "sm";

const anchorStyle = (anchor: Shot["text_anchor"]): React.CSSProperties => {
  if (anchor === "center") return { top: 0, bottom: 0, justifyContent: "center" };
  if (anchor === "bottom") {
    return { bottom: CANVAS.safeBottom, justifyContent: "flex-end" };
  }
  return { top: CANVAS.safeTop, justifyContent: "flex-start" };
};

const TextColumn: React.FC<{
  anchor: Shot["text_anchor"];
  align?: "left" | "center";
  width?: number;
  left?: number;
  children: React.ReactNode;
}> = ({ anchor, align = "left", width, left = CANVAS.margin, children }) => (
  <div
    style={{
      position: "absolute",
      left,
      width: width ?? contentWidth,
      display: "flex",
      flexDirection: "column",
      alignItems: align === "center" ? "center" : "flex-start",
      ...anchorStyle(anchor),
    }}
  >
    {children}
  </div>
);

export const ShotComposition: React.FC<ShotProps> = ({
  shot,
  accent,
  duration,
  motionKey,
  progress,
  logo,
  brand,
  index = 1,
  total = 1,
  docLabel,
}) => {
  const scale = shot.type_scale ?? "lg";
  const illustration = shot.illustration?.file;
  const illoMotion = shot.illustration?.motion;

  const anchor: Shot["text_anchor"] =
    SELF_CONTAINED.has(shot.layout) && !illustration ? "center" : shot.text_anchor ?? "top";

  // --- The brand outro owns the whole frame. ---
  if (shot.layout === "outro_brand") {
    return (
      <AbsoluteFill>
        <Paper />
        <RegistrationMarks accent={accent} />
        <BrandOutro
          headline={shot.headline}
          ctaLabel={brand?.ctaLabel}
          handle={brand?.handle}
          logo={logo}
          accent={accent}
          motionKey={motionKey}
        />
      </AbsoluteFill>
    );
  }

  const chrome = (
    <>
      <Paper />
      <RegistrationMarks accent={accent} />
      <ProgressRule progress={progress} accent={accent} />
      <Watermark logo={logo} accent={accent} />
    </>
  );

  // Suppress the footer wherever artwork reaches the bottom of the frame, so a
  // hairline never cuts across a drawing.
  const artOccupiesFoot =
    Boolean(illustration) &&
    (shot.layout === "data_readout" ||
      shot.layout === "quote_block" ||
      shot.layout === "illustration_full" ||
      shot.layout === "illustration_side");

  const footer = artOccupiesFoot ? null : (
    <Footer index={index} total={total} label={docLabel} accent={accent} />
  );

  const copy = (
    <CopyBlock
      kicker={shot.kicker}
      headline={shot.headline}
      accent={accent}
      scale={scale}
      emphasis={shot.emphasis_words}
      motionKey={motionKey}
      maxWidth={contentWidth}
      delay={illustration ? 8 : 2}
    />
  );

  switch (shot.layout) {
    /**
     * Full-bleed art with type overlaid. The plate recedes slightly so the
     * headline keeps contrast without needing a scrim slab over the drawing.
     */
    case "illustration_full":
      return (
        <AbsoluteFill>
          <Paper />
          {illustration ? (
            <PlateFull
              file={illustration}
              duration={duration}
              motion={illoMotion}
              recede={0.3}
            />
          ) : null}
          <PegboardOverlay />
          <RegistrationMarks accent={accent} />
          <ProgressRule progress={progress} accent={accent} />
          <Watermark logo={logo} accent={accent} />
          <TextColumn anchor={anchor}>{copy}</TextColumn>
          <Callouts annotations={shot.annotations} accent={accent} />
        </AbsoluteFill>
      );

    /**
     * Art in the upper band, type beneath. The most reliable arrangement for a
     * dense drawing, because type never sits on top of linework.
     */
    case "illustration_top":
      return (
        <AbsoluteFill>
          {chrome}
          {illustration ? (
            <PlateBand
              file={illustration}
              duration={duration}
              motion={illoMotion}
              region="top"
              extent={0.56}
            />
          ) : null}
          <PegboardOverlay />
          <TextColumn anchor="bottom">{copy}</TextColumn>
          <Callouts annotations={shot.annotations} accent={accent} />
          {footer}
        </AbsoluteFill>
      );

    /**
     * Art on the right, type on the left.
     *
     * The art column is kept under half the width and the type steps down two
     * bands, because a 50/50 split left the headline in a column so narrow that
     * short phrases broke across three lines.
     */
    case "illustration_side": {
      const artExtent = 0.44;
      const textWidth = contentWidth * 0.6;
      return (
        <AbsoluteFill>
          {chrome}
          {illustration ? (
            <PlateSide
              file={illustration}
              duration={duration}
              motion={illoMotion}
              side="right"
              extent={artExtent}
            />
          ) : null}
          <PegboardOverlay />
          <TextColumn anchor={anchor === "top" ? "center" : anchor} width={textWidth}>
            <CopyBlock
              kicker={shot.kicker}
              headline={shot.headline}
              accent={accent}
              scale={stepDown(stepDown(scale))}
              emphasis={shot.emphasis_words}
              motionKey={motionKey}
              maxWidth={textWidth}
              delay={6}
            />
          </TextColumn>
          <Callouts annotations={shot.annotations} accent={accent} />
        </AbsoluteFill>
      );
    }

    /**
     * A figure is the point. Art, when present, sits in the lower band so the
     * number dominates the upper half.
     */
    case "data_readout":
      return (
        <AbsoluteFill>
          {chrome}
          {illustration ? (
            <PlateBand
              file={illustration}
              duration={duration}
              motion={illoMotion}
              region="bottom"
              extent={0.44}
            />
          ) : null}
          <PegboardOverlay />
          <TextColumn anchor="top">
            {shot.kicker || shot.headline ? (
              <div style={{ marginBottom: 46 }}>
                <CopyBlock
                  kicker={shot.kicker}
                  headline={shot.headline}
                  accent={accent}
                  scale={stepDown(stepDown(scale))}
                  emphasis={shot.emphasis_words}
                  motionKey={motionKey}
                  maxWidth={contentWidth}
                  delay={2}
                />
              </div>
            ) : null}
            {shot.data ? (
              <Readout data={shot.data} accent={accent} delay={12} motionKey={motionKey} />
            ) : null}
          </TextColumn>
          <Callouts annotations={shot.annotations} accent={accent} />
          {footer}
        </AbsoluteFill>
      );

    case "node_flow":
      return (
        <AbsoluteFill>
          {chrome}
          <TextColumn anchor={anchor}>
            <div style={{ marginBottom: 56 }}>
              <CopyBlock
                kicker={shot.kicker}
                headline={shot.headline}
                accent={accent}
                scale={stepDown(stepDown(scale))}
                emphasis={shot.emphasis_words}
                motionKey={motionKey}
                maxWidth={contentWidth}
                delay={2}
              />
            </div>
            <NodeFlow
              nodes={shot.nodes ?? []}
              accent={accent}
              delay={16}
              motionKey={motionKey}
              width={contentWidth}
            />
          </TextColumn>
          {footer}
        </AbsoluteFill>
      );

    case "compare_two_up":
      return (
        <AbsoluteFill>
          {chrome}
          <TextColumn anchor={anchor}>
            <div style={{ marginBottom: 64 }}>
              <CopyBlock
                kicker={shot.kicker}
                headline={shot.headline}
                accent={accent}
                scale={stepDown(stepDown(scale))}
                emphasis={shot.emphasis_words}
                motionKey={motionKey}
                maxWidth={contentWidth}
                delay={2}
              />
            </div>
            <CompareTwoUp
              nodes={shot.nodes ?? []}
              accent={accent}
              delay={16}
              motionKey={motionKey}
            />
          </TextColumn>
          {footer}
        </AbsoluteFill>
      );

    case "timeline_rail":
      return (
        <AbsoluteFill>
          {chrome}
          <TextColumn anchor={anchor}>
            <div style={{ marginBottom: 54 }}>
              <CopyBlock
                kicker={shot.kicker}
                headline={shot.headline}
                accent={accent}
                scale={stepDown(stepDown(scale))}
                emphasis={shot.emphasis_words}
                motionKey={motionKey}
                maxWidth={contentWidth}
                delay={2}
              />
            </div>
            <TimelineRail
              events={shot.events ?? []}
              accent={accent}
              delay={16}
              motionKey={motionKey}
            />
          </TextColumn>
          {footer}
        </AbsoluteFill>
      );

    case "quote_block":
      return (
        <AbsoluteFill>
          {chrome}
          {illustration ? (
            <PlateBand
              file={illustration}
              duration={duration}
              motion={illoMotion}
              region="bottom"
              extent={0.38}
            />
          ) : null}
          <PegboardOverlay />
          <TextColumn anchor={anchor}>
            {shot.kicker ? (
              <div style={{ marginBottom: 32 }}>
                <CopyBlock
                  kicker={shot.kicker}
                  accent={accent}
                  motionKey={motionKey}
                  maxWidth={contentWidth}
                  rule={false}
                />
              </div>
            ) : null}
            <QuoteBlock
              text={shot.headline ?? ""}
              accent={accent}
              scale={stepDown(scale)}
              motionKey={motionKey}
              maxWidth={contentWidth}
              delay={6}
            />
          </TextColumn>
          {footer}
        </AbsoluteFill>
      );

    /**
     * Pure typographic statement. Deliberately austere: on a pegboard page a
     * large, well-set sentence with a single accent word carries a shot on its own.
     */
    case "hero_statement":
    default:
      return (
        <AbsoluteFill>
          {chrome}
          <TextColumn anchor={anchor}>
            {copy}
            {shot.data ? (
              <div style={{ marginTop: 60 }}>
                <Readout data={shot.data} accent={accent} delay={18} motionKey={motionKey} />
              </div>
            ) : null}
          </TextColumn>
          <Callouts annotations={shot.annotations} accent={accent} />
          {footer}
        </AbsoluteFill>
      );
  }
};
