"""Cloudflare R2 backup service.

Exports PostgreSQL data and uploads to R2 (S3-compatible) storage.
Supports:
- Full database backup (pg_dump)
- Selective table export (JSON)
- Automatic retention (keep last N days)
"""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import boto3
import structlog
from botocore.config import Config

logger = structlog.get_logger(__name__)


class R2BackupService:
    """Manages backups to Cloudflare R2."""

    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        endpoint_url: str,
        bucket_name: str,
    ) -> None:
        self._bucket_name = bucket_name
        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(
                retries={"max_attempts": 3, "mode": "adaptive"},
                signature_version="s3v4",
            ),
        )

    def upload_file(self, local_path: str, r2_key: str) -> bool:
        """Upload a file to R2."""
        try:
            self._s3.upload_file(local_path, self._bucket_name, r2_key)
            logger.info("r2.upload_success", key=r2_key, size=os.path.getsize(local_path))
            return True
        except Exception as e:
            logger.error("r2.upload_failed", key=r2_key, error=str(e))
            return False

    def upload_gzipped_json(self, data: list[dict], r2_key: str) -> bool:
        """Upload JSON data as gzipped file."""
        try:
            json_bytes = json.dumps(data, default=str, ensure_ascii=False).encode("utf-8")
            gzipped = gzip.compress(json_bytes)

            self._s3.put_object(
                Bucket=self._bucket_name,
                Key=r2_key,
                Body=gzipped,
                ContentEncoding="gzip",
                ContentType="application/json",
            )
            logger.info(
                "r2.upload_json_success",
                key=r2_key,
                records=len(data),
                size_gzipped=len(gzipped),
                size_original=len(json_bytes),
            )
            return True
        except Exception as e:
            logger.error("r2.upload_json_failed", key=r2_key, error=str(e))
            return False

    def list_backups(self, prefix: str = "") -> list[dict]:
        """List backups in R2."""
        try:
            response = self._s3.list_objects_v2(
                Bucket=self._bucket_name,
                Prefix=prefix,
            )
            return [
                {
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                }
                for obj in response.get("Contents", [])
            ]
        except Exception as e:
            logger.error("r2.list_failed", prefix=prefix, error=str(e))
            return []

    def delete_backup(self, r2_key: str) -> bool:
        """Delete a backup from R2."""
        try:
            self._s3.delete_object(Bucket=self._bucket_name, Key=r2_key)
            logger.info("r2.delete_success", key=r2_key)
            return True
        except Exception as e:
            logger.error("r2.delete_failed", key=r2_key, error=str(e))
            return False

    def cleanup_old_backups(self, prefix: str, keep_days: int = 30) -> int:
        """Delete backups older than keep_days."""
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
        backups = self.list_backups(prefix)
        deleted = 0

        for backup in backups:
            key = backup["key"]
            try:
                last_mod = datetime.fromisoformat(backup["last_modified"].replace("Z", "+00:00"))
                if last_mod < cutoff:
                    if self.delete_backup(key):
                        deleted += 1
            except Exception:
                continue

        if deleted > 0:
            logger.info("r2.cleanup_done", deleted=deleted, keep_days=keep_days)
        return deleted


def pg_dump_table(
    table: str,
    output_path: str,
    host: str = "localhost",
    port: int = 5432,
    user: str = "solana_intel",
    password: str = "dev_password",
    database: str = "solana_wallet_intel",
) -> bool:
    """Export a PostgreSQL table to JSON using psql."""
    try:
        env = os.environ.copy()
        env["PGPASSWORD"] = password

        cmd = [
            "psql",
            "-h", host,
            "-p", str(port),
            "-U", user,
            "-d", database,
            "-t", "-A",
            "-c", f"SELECT row_to_json(t) FROM (SELECT * FROM {table}) t",
        ]

        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            logger.error("pg_dump.failed", table=table, error=result.stderr)
            return False

        records = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        with open(output_path, "w") as f:
            json.dump(records, f, default=str, ensure_ascii=False)

        logger.info("pg_dump.success", table=table, records=len(records))
        return True

    except subprocess.TimeoutExpired:
        logger.error("pg_dump.timeout", table=table)
        return False
    except Exception as e:
        logger.error("pg_dump.error", table=table, error=str(e))
        return False
