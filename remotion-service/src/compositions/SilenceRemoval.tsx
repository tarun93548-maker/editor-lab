import React from "react";
import { AbsoluteFill, OffthreadVideo, Sequence } from "remotion";

interface SilentPart {
  startFrame: number;
  endFrame: number;
  startSec: number;
  endSec: number;
}

interface SilenceRemovalProps extends Record<string, unknown> {
  videoUrl: string;
  silentParts: SilentPart[];
  fps: number;
  durationInFrames: number;
}

export const SilenceRemoval: React.FC<SilenceRemovalProps> = ({
  videoUrl,
  silentParts,
  fps,
  durationInFrames,
}) => {
  // Sort silent parts by startFrame
  const sorted = [...silentParts].sort((a, b) => a.startFrame - b.startFrame);

  // Invert silent parts to get audible segments
  const audibleSegments: { startFrame: number; endFrame: number }[] = [];
  let cursor = 0;

  for (const sp of sorted) {
    if (sp.startFrame > cursor) {
      audibleSegments.push({ startFrame: cursor, endFrame: sp.startFrame });
    }
    cursor = Math.max(cursor, sp.endFrame);
  }

  // Add trailing segment if there's content after last silence
  if (cursor < durationInFrames) {
    audibleSegments.push({ startFrame: cursor, endFrame: durationInFrames });
  }

  let currentFrame = 0;

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {audibleSegments.map((seg, i) => {
        const segDuration = seg.endFrame - seg.startFrame;
        const from = currentFrame;
        currentFrame += segDuration;
        return (
          <Sequence key={i} from={from} durationInFrames={segDuration}>
            <OffthreadVideo
              src={videoUrl}
              startFrom={seg.startFrame}
              endAt={seg.startFrame + segDuration}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
