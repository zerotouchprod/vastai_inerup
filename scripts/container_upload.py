#!/usr/bin/env python3
"""container_upload.py

Run inside the container to upload a local file to Backblaze B2 (S3-compatible) using boto3.
Reads credentials from environment: B2_KEY, B2_SECRET, B2_ENDPOINT (optional) and B2_BUCKET.

Usage:
  python3 /workspace/project/scripts/container_upload.py /workspace/final_output.mp4 noxfvr-videos output/qad.mp4

On success prints the download URL and exits 0. On failure prints diagnostics and exits non-zero.
"""
import sys
import os
import subprocess
import threading


try:
    import boto3
    from botocore.client import Config
    from botocore.exceptions import ClientError
except Exception:
    boto3 = None


class ProgressPercentage:
    """Callback for boto3 upload to print progress.

    Prints transferred bytes and percentage to stdout so container logs show upload progress.
    """

    def __init__(self, filename):
        try:
            self._size = float(os.path.getsize(filename))
        except Exception:
            self._size = None
        self._seen_so_far = 0
        self._lock = threading.Lock()

    def __call__(self, bytes_amount):
        # bytes_amount is the chunk size just transferred
        with self._lock:
            self._seen_so_far += bytes_amount
            if self._size and self._size > 0:
                pct = (self._seen_so_far / self._size) * 100
                print(
                    f"Upload progress: {self._seen_so_far}/{int(self._size)} bytes ({pct:.1f}%)",
                    flush=True,
                )
            else:
                print(
                    f"Upload progress: {self._seen_so_far} bytes transferred", flush=True
                )


def upload_via_boto(filepath, bucket, key, endpoint):
    access_key = os.environ.get("B2_KEY") or os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("B2_SECRET") or os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        print("B2 credentials not found in environment (B2_KEY/B2_SECRET).")
        return False

    if boto3 is None:
        print("boto3 not installed inside container.")
        return False

    cfg = Config(s3={"addressing_style": "virtual"})
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            endpoint_url=endpoint,
            config=cfg,
        )
        # upload_file for multipart support
        print(f"Uploading {filepath} -> s3://{bucket}/{key} using boto3...")
        file_size = os.path.getsize(filepath)
        # Zero-size files should be handled gracefully
        if file_size == 0:
            print("Warning: Zero-size file, uploading as is without multipart...")
            s3.upload_file(filepath, bucket, key)
        else:
            # Use TransferConfig for multipart uploads
            from boto3.s3.transfer import TransferConfig

            # Define the configuration for multipart uploads
            config = TransferConfig(
                multipart_threshold=1024 * 25,  # 25MB threshold for multipart uploads
                max_concurrency=10,  # Adjust based on your network and instance capacity
                multipart_chunksize=1024 * 25,  # 25MB per part
                use_threads=True,  # Enable threading
            )
            # Pass ProgressPercentage as Callback to upload progress
            s3.upload_file(
                filepath,
                bucket,
                key,
                Config=config,
                Callback=ProgressPercentage(filepath),
            )
        # Confirm the uploaded object path and print presigned GET URL
        print(f"Uploaded to s3://{bucket}/{key}")
        # Retry head_object a few times (occasionally B2 can be eventually consistent)
        import time

        head_ok = False
        for attempt in range(1, 4):
            try:
                s3.head_object(Bucket=bucket, Key=key)
                head_ok = True
                print(f"Verified via head_object on attempt {attempt}")
                break
            except Exception as e:
                print(f"Warning: head_object attempt {attempt} failed: {e}")
                time.sleep(1)

        if not head_ok:
            print("ERROR: head_object verification failed after retries")
            return False

        # Generate presigned URL and try a lightweight GET to ensure object is publicly retrievable via the URL
        url = s3.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=604800
        )
        print("Presigned GET URL:", url)

        # Try HTTP GET to verify accessibility and optionally Content-Length match
        try:
            from urllib.request import urlopen, Request

            req = Request(url, headers={"User-Agent": "vastai-uploader/1.0"})
            with urlopen(req, timeout=15) as resp:
                code = resp.getcode()
                cl = resp.getheader("Content-Length")
                print(f"Presigned URL HTTP status: {code}, Content-Length: {cl}")
                try:
                    if cl is not None:
                        cl_int = int(cl)
                        local_size = os.path.getsize(filepath)
                        if cl_int != local_size:
                            print(
                                f"Warning: uploaded object size ({cl_int}) != local file size ({local_size})"
                            )
                except Exception:
                    pass
                if code != 200:
                    print("ERROR: Presigned URL did not return 200 OK")
                    return False
        except Exception as e:
            print("Warning: presigned URL fetch failed:", e)
            # Not a hard failure: still consider upload successful if head_object passed

        print("✅ B2 upload successful and verified")
        print(url)
        return True
    except ClientError as e:
        print("boto3 ClientError:", e.response.get("Error", {}))
        return False
    except Exception as e:
        print("boto3 upload exception:", e)
        return False


def upload_via_transfersh(filepath):
    print("Falling back to transfer.sh upload...")
    try:
        res = subprocess.run(
            ["curl", "--upload-file", filepath, "https://transfer.sh/output.mp4"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if res.returncode == 0 and res.stdout.strip():
            print("✅ Uploaded to transfer.sh")
            print(res.stdout.strip())
            return True
        else:
            print("transfer.sh failed:", res.returncode, res.stdout, res.stderr)
            return False
    except Exception as e:
        print("transfer.sh exception:", e)
        return False


def main(argv=None):
    argv = argv or sys.argv[1:]
    if len(argv) < 3:
        print("Usage: container_upload.py <filepath> <bucket> <key> [endpoint]")
        return 2
    filepath, bucket, key = argv[0], argv[1], argv[2]
    endpoint = (
        argv[3]
        if len(argv) > 3
        else os.environ.get("B2_ENDPOINT", "https://s3.us-west-004.backblazeb2.com")
    )

    if not os.path.exists(filepath):
        print("File not found:", filepath)
        return 3

    ok = upload_via_boto(filepath, bucket, key, endpoint)
    if ok:
        return 0

    ok2 = upload_via_transfersh(filepath)
    if ok2:
        return 0

    print("Upload failed by both boto3 and transfer.sh")
    print("File info:", filepath, os.path.getsize(filepath))
    return 1


if __name__ == "__main__":
    sys.exit(main())
