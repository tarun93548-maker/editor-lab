import { S3Client, PutObjectCommand, GetObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { readFileSync } from "fs";
import { v4 as uuidv4 } from "uuid";

// Env vars are read at call time (after dotenv.config() in server.ts), not at import time.

let _client: S3Client | null = null;

function getClient(): S3Client {
  if (_client) return _client;
  const accountId = process.env.R2_ACCOUNT_ID || "";
  if (!accountId) {
    throw new Error("R2_ACCOUNT_ID is not set — check remotion-service/.env");
  }
  _client = new S3Client({
    endpoint: `https://${accountId}.r2.cloudflarestorage.com`,
    region: "auto",
    credentials: {
      accessKeyId: process.env.R2_ACCESS_KEY_ID || "",
      secretAccessKey: process.env.R2_SECRET_ACCESS_KEY || "",
    },
  });
  return _client;
}

export async function uploadToR2(
  localPath: string,
  prefix: string = "renders"
): Promise<{ key: string; url: string }> {
  const bucket = process.env.R2_BUCKET || "editor-lab";
  const key = `${prefix}/${uuidv4()}.mp4`;
  const body = readFileSync(localPath);

  await getClient().send(
    new PutObjectCommand({
      Bucket: bucket,
      Key: key,
      Body: body,
      ContentType: "video/mp4",
    })
  );

  const publicUrl = process.env.R2_PUBLIC_URL || "";
  let url: string;
  if (publicUrl) {
    url = `${publicUrl.replace(/\/$/, "")}/${key}`;
  } else {
    url = await getSignedUrl(
      getClient(),
      new GetObjectCommand({ Bucket: bucket, Key: key }),
      { expiresIn: 3600 }
    );
  }

  return { key, url };
}
