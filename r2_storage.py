import os
import uuid
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig


def _get_client():
    """Return a boto3 S3 client configured for Cloudflare R2."""
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ.get("R2_ACCESS_KEY_ID", ""),
        aws_secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY", ""),
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )


def _bucket():
    return os.environ.get("R2_BUCKET", "editor-lab")


def upload_file(local_path: str, prefix: str = "uploads") -> dict:
    """Upload a local file to R2. Returns {"key": str, "url": str}."""
    ext = Path(local_path).suffix.lower()
    key = f"{prefix}/{uuid.uuid4().hex}{ext}"
    content_type = "video/mp4" if ext == ".mp4" else "application/octet-stream"

    client = _get_client()
    client.upload_file(
        local_path, _bucket(), key,
        ExtraArgs={"ContentType": content_type},
    )
    return {"key": key, "url": get_public_url(key)}


def upload_bytes(data: bytes, key: str, content_type: str = "application/octet-stream") -> dict:
    """Upload raw bytes to R2."""
    client = _get_client()
    client.put_object(Bucket=_bucket(), Key=key, Body=data, ContentType=content_type)
    return {"key": key, "url": get_public_url(key)}


def get_public_url(key: str) -> str:
    """Return public URL if R2_PUBLIC_URL is set, else a presigned URL."""
    public_url = os.environ.get("R2_PUBLIC_URL", "")
    if public_url:
        return f"{public_url.rstrip('/')}/{key}"
    return get_presigned_url(key)


def get_presigned_url(key: str, expires: int = 3600) -> str:
    """Generate a presigned GET URL."""
    client = _get_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=expires,
    )


def download_file(key: str, local_path: str):
    """Download an object from R2 to a local path."""
    client = _get_client()
    client.download_file(_bucket(), key, local_path)


def delete_file(key: str):
    """Delete an object from R2."""
    client = _get_client()
    client.delete_object(Bucket=_bucket(), Key=key)
