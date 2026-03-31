import React from "react";
import { Composition } from "remotion";
import { SilenceRemoval } from "./compositions/SilenceRemoval";
import { VariationRender } from "./compositions/VariationRender";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="SilenceRemoval"
        component={SilenceRemoval}
        durationInFrames={1}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          videoUrl: "",
          silentParts: [],
          fps: 30,
          durationInFrames: 1,
        }}
      />
      <Composition
        id="VariationRender"
        component={VariationRender}
        durationInFrames={1}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          videoUrl: "",
          segments: [],
          captions: [],
          fps: 30,
        }}
      />
    </>
  );
};
