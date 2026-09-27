"""Private Cloudflare R2 storage for derived Product Hub assets."""
from __future__ import annotations

import os
from hashlib import sha256


class R2ConfigurationError(RuntimeError):
    pass


def _env(*names: str) -> str:
    return next((os.getenv(name, "").strip() for name in names if os.getenv(name, "").strip()), "")


class R2Storage:
    def __init__(self, *, account_id: str, bucket: str, access_key_id: str, secret_access_key: str) -> None:
        if not all((account_id, bucket, access_key_id, secret_access_key)):
            raise R2ConfigurationError("R2 storage is not configured")
        import boto3
        self.bucket = bucket
        self._client = boto3.client("s3", endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com", aws_access_key_id=access_key_id, aws_secret_access_key=secret_access_key, region_name="auto")

    @classmethod
    def from_environment(cls) -> "R2Storage":
        return cls(account_id=_env("XW_R2_ACCOUNT_ID", "R2_ACCOUNT_ID", "CLOUDFLARE_ACCOUNT_ID"), bucket=_env("XW_R2_BUCKET", "R2_BUCKET", "R2_BUCKET_NAME"), access_key_id=_env("XW_R2_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"), secret_access_key=_env("XW_R2_SECRET_ACCESS_KEY", "R2_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"))

    def put_private(self, *, key: str, content: bytes, content_type: str) -> str:
        digest = sha256(content).hexdigest()
        self._client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=content_type, Metadata={"sha256": digest})
        return f"r2://{self.bucket}/{key}"
