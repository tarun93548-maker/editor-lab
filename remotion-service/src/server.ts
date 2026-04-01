import express from "express";
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition, getSilentParts, getVideoMetadata } from "@remotion/renderer";
import crypto from "crypto";
import path from "path";
import fs from "fs";
import { writeFile, unlink } from "fs/promises";
import os from "os";
import { uploadToR2 } from "./utils/r2";
import dotenv from "dotenv";

// Load .env from the remotion-service root (two levels up from src/server.ts at runtime in dist/)
dotenv.config({ path: path.resolve(__dirname, "..", ".env") });

const app = express();
app.use(express.json({ limit: "50mb" }));

const PORT = parseInt(process.env.REMOTION_PORT || "3100", 10);

// Serve temp files so OffthreadVideo can access them via http://
app.use("/temp", express.static(os.tmpdir()));

/**
 * Download a remote URL to a temp file and return the local path.
 * Uses crypto.randomUUID() for unique filenames.
 */
async function downloadToTemp(url: string, prefix: string): Promise<string> {
  const ext = path.extname(new URL(url).pathname) || ".mp4";
  const tmpPath = path.join(os.tmpdir(), `${prefix}-${crypto.randomUUID()}${ext}`);
  console.log(`[Download] ${url} -> ${tmpPath}`);
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`Failed to download ${url}: ${resp.status} ${resp.statusText}`);
  }
  const buffer = Buffer.from(await resp.arrayBuffer());
  await writeFile(tmpPath, buffer);
  return tmpPath;
}

/**
 * Convert a local temp file path to an HTTP URL served by this Express app.
 * OffthreadVideo requires http(s):// URLs — it cannot use file:// paths.
 */
function toTempUrl(localPath: string): string {
  const filename = path.basename(localPath);
  return `http://localhost:${PORT}/temp/${encodeURIComponent(filename)}`;
}

/** Remove a temp file, ignoring errors if it's already gone. */
function cleanupTemp(filePath: string) {
  unlink(filePath).catch(() => {});
}

// Bundle caching — always re-bundle to pick up composition changes
let bundled: string | null = null;

async function getBundled(): Promise<string> {
  // Always re-bundle so style/logic changes take effect without restart
  console.log("[Remotion] Bundling compositions...");
  bundled = await bundle({
    entryPoint: path.resolve(__dirname, "index.tsx"),
  });
  console.log("[Remotion] Bundle complete:", bundled);
  return bundled;
}

// Health check
app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "remotion" });
});

// Detect silence
app.post("/api/detect-silence", async (req, res) => {
  try {
    const { videoUrl, noiseThreshold = -30, minDuration = 0.5 } = req.body;

    if (!videoUrl) {
      return res.status(400).json({ error: "videoUrl is required" });
    }

    console.log(`[Silence] Detecting silence in: ${videoUrl}`);

    const localPath = await downloadToTemp(videoUrl, "silence");
    try {
      // Get video metadata for fps and duration
      const metadata = await getVideoMetadata(localPath);
      const fps = metadata.fps;
      const durationInSeconds = metadata.durationInSeconds ?? 0;
      const durationInFrames = Math.round(durationInSeconds * fps);

      const result = await getSilentParts({
        src: localPath,
        noiseThresholdInDecibels: noiseThreshold,
        minDurationInSeconds: minDuration,
      });

      // Shrink each silent part by BREATH_FRAMES on each side so cuts
      // happen slightly inside the silence, giving a natural breath.
      const BREATH_FRAMES = 2;
      const silentParts: Array<{
        startFrame: number;
        endFrame: number;
        startSec: number;
        endSec: number;
      }> = [];

      for (const part of result.silentParts) {
        const rawStart = Math.round(part.startInSeconds * fps);
        const rawEnd = Math.round(part.endInSeconds * fps);
        const paddedStart = rawStart + BREATH_FRAMES;
        const paddedEnd = rawEnd - BREATH_FRAMES;
        // Skip if the silent part is too short after padding
        if (paddedEnd <= paddedStart) continue;
        silentParts.push({
          startFrame: paddedStart,
          endFrame: paddedEnd,
          startSec: paddedStart / fps,
          endSec: paddedEnd / fps,
        });
      }

      res.json({
        silentParts,
        fps,
        durationInFrames,
      });
    } finally {
      cleanupTemp(localPath);
    }
  } catch (err: any) {
    console.error("[Silence] Error:", err);
    res.status(500).json({ error: err.message });
  }
});

// Render silence removed
app.post("/api/render-silence-removed", async (req, res) => {
  try {
    const { videoUrl, silentParts, fps, durationInFrames } = req.body;

    if (!videoUrl || !silentParts || !fps || !durationInFrames) {
      return res.status(400).json({ error: "Missing required fields" });
    }

    const localVideo = await downloadToTemp(videoUrl, "clean-src");
    try {
      const bundlePath = await getBundled();

      // Calculate output frames (total - silent frames)
      const silentFrameCount = silentParts.reduce(
        (sum: number, sp: any) => sum + (sp.endFrame - sp.startFrame),
        0
      );
      const outputFrames = durationInFrames - silentFrameCount;

      console.log(
        `[Render] Silence removal: ${durationInFrames} frames -> ${outputFrames} frames`
      );

      const videoHttpUrl = toTempUrl(localVideo);
      const inputProps = { videoUrl: videoHttpUrl, silentParts, fps, durationInFrames };

      const composition = await selectComposition({
        serveUrl: bundlePath,
        id: "SilenceRemoval",
        inputProps,
      });

      composition.durationInFrames = outputFrames;
      composition.fps = fps;

      const tmpFile = path.join(os.tmpdir(), `clean-${Date.now()}.mp4`);

      await renderMedia({
        composition,
        serveUrl: bundlePath,
        codec: "h264",
        outputLocation: tmpFile,
        inputProps,
        timeoutInMilliseconds: 120_000,
      });

      const { key, url } = await uploadToR2(tmpFile, "clean");

      // Clean up output temp file
      fs.unlinkSync(tmpFile);

      console.log(`[Render] Silence removed video uploaded: ${key}`);
      res.json({ outputUrl: url, r2Key: key });
    } finally {
      cleanupTemp(localVideo);
    }
  } catch (err: any) {
    console.error("[Render] Silence removal error:", err);
    res.status(500).json({ error: err.message });
  }
});

// Render variation
app.post("/api/render-variation", async (req, res) => {
  try {
    const {
      videoUrl,
      segments,
      captions,
      fps = 30,
      width = 1080,
      height = 1920,
    } = req.body;

    if (!videoUrl || !segments) {
      return res.status(400).json({ error: "Missing required fields" });
    }

    const localVideo = await downloadToTemp(videoUrl, "var-src");
    try {
      const bundlePath = await getBundled();

      // Calculate total frames by summing per-segment frames the same way
      // the composition does: Math.floor(duration * fps) per segment
      const totalFrames = segments.reduce(
        (sum: number, seg: any) => sum + Math.floor((seg.end - seg.start) * fps),
        0
      );

      console.log(
        `[Render] Variation: ${segments.length} segments, ${totalFrames} frames`
      );

      const videoHttpUrl = toTempUrl(localVideo);
      const inputProps = { videoUrl: videoHttpUrl, segments, captions: captions || [], fps };

      const composition = await selectComposition({
        serveUrl: bundlePath,
        id: "VariationRender",
        inputProps,
      });

      composition.durationInFrames = totalFrames;
      composition.fps = fps;
      composition.width = width;
      composition.height = height;

      const tmpFile = path.join(os.tmpdir(), `variation-${Date.now()}.mp4`);

      await renderMedia({
        composition,
        serveUrl: bundlePath,
        codec: "h264",
        outputLocation: tmpFile,
        inputProps,
        timeoutInMilliseconds: 120_000,
      });

      const { key, url } = await uploadToR2(tmpFile, "variations");

      fs.unlinkSync(tmpFile);

      console.log(`[Render] Variation uploaded: ${key}`);
      res.json({ outputUrl: url, r2Key: key });
    } finally {
      cleanupTemp(localVideo);
    }
  } catch (err: any) {
    console.error("[Render] Variation error:", err);
    res.status(500).json({ error: err.message });
  }
});

// Start server and pre-bundle
app.listen(PORT, () => {
  console.log(`[Remotion] Service running on port ${PORT}`);
  // Pre-bundle on startup
  getBundled().catch((err) => {
    console.error("[Remotion] Pre-bundle failed:", err);
  });
});
