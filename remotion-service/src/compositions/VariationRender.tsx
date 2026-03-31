import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

interface Segment {
  start: number;
  end: number;
}

interface Caption {
  text: string;
  start: number;
  end: number;
}

interface VariationRenderProps extends Record<string, unknown> {
  videoUrl: string;
  segments: Segment[];
  captions: Caption[];
  fps: number;
}

const CaptionOverlay: React.FC<{
  captions: Caption[];
  fps: number;
}> = ({ captions, fps }) => {
  const frame = useCurrentFrame();
  const { height } = useVideoConfig();
  const currentTimeSec = frame / fps;

  const activeCaption = captions.find(
    (cap) => currentTimeSec >= cap.start && currentTimeSec < cap.end
  );

  if (!activeCaption) return null;

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-start",
        alignItems: "center",
        paddingTop: height * 0.62,
      }}
    >
      <div
        style={{
          fontFamily: "Georgia, serif",
          fontSize: 38,
          fontWeight: 400,
          color: "white",
          textShadow: "-1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000",
          textAlign: "center",
          maxWidth: "80%",
          lineHeight: 1.3,
        }}
      >
        {activeCaption.text}
      </div>
    </AbsoluteFill>
  );
};

export const VariationRender: React.FC<VariationRenderProps> = ({
  videoUrl,
  segments,
  captions,
  fps,
}) => {
  let currentFrame = 0;

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {segments.map((seg, i) => {
        const segDurationFrames = Math.floor((seg.end - seg.start) * fps);
        const sourceStartFrame = Math.floor(seg.start * fps);
        const from = currentFrame;
        currentFrame += segDurationFrames;
        return (
          <Sequence key={i} from={from} durationInFrames={segDurationFrames}>
            <OffthreadVideo
              src={videoUrl}
              startFrom={sourceStartFrame}
              endAt={sourceStartFrame + segDurationFrames}
            />
          </Sequence>
        );
      })}
      <CaptionOverlay captions={captions} fps={fps} />
    </AbsoluteFill>
  );
};
