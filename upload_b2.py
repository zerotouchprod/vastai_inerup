#!/usr/bin/env python3
"""
upload_b2.py

Upload a local file to Backblaze B2 using the S3-compatible API (boto3).

Usage:
  export B2_KEY=... B2_SECRET=... B2_ENDPOINT=https://s3.us-west-000.backblazeb2.com
  python3 upload_b2.py --file ./test_60_short.mp4 --bucket my-bucket --key input/test_60_short.mp4

The script uploads using boto3's upload_file (which uses multipart when needed) and prints a presigned GET URL.

Requirements: boto3 (already in requirements.txt)
"""

import os
import sys
import argparse
import json
import mimetypes
import time
import traceback
from typing import Optional

try:
    import boto3
    from botocore.client import Config
    from botocore.exceptions import ClientError
    from boto3.s3.transfer import TransferConfig
except Exception:
    print("Missing dependency: boto3. Install with `pip install boto3`.")
    raise

PENDING_MARKER_PATH = '/workspace/.pending_upload.json'


def make_client(access_key: Optional[str], secret_key: Optional[str], endpoint: Optional[str], region: Optional[str]):
    """Create an S3 client with conservative configuration for B2 S3 compatibility."""
    kwargs = {}
    if access_key and secret_key:
        kwargs['aws_access_key_id'] = access_key
        kwargs['aws_secret_access_key'] = secret_key
    if region:
        kwargs['region_name'] = region
    # Use signature v4 and virtual addressing style for maximum compatibility
    if endpoint:
        cfg = Config(signature_version='s3v4', s3={'addressing_style': 'virtual'})
        client = boto3.client('s3', endpoint_url=endpoint, config=cfg, **kwargs)
    else:
        cfg = Config(signature_version='s3v4', s3={'addressing_style': 'virtual'})
        client = boto3.client('s3', config=cfg, **kwargs)
    return client


def validate_credentials(s3_client, bucket: Optional[str] = None):
    """Quick check that credentials work. If bucket is provided do a head_bucket, otherwise list_buckets.
    Returns None on success, raises ClientError on failure.
    """
    try:
        if bucket:
            # head_bucket is a lightweight check (requires permission to read bucket metadata)
            s3_client.head_bucket(Bucket=bucket)
        else:
            s3_client.list_buckets()
    except ClientError as e:
        # Re-raise so caller can present helpful guidance
        raise


def _write_pending_marker(local_path, bucket, key, endpoint, attempts):
    try:
        obj = {
            'file': local_path,
            'bucket': bucket,
            'key': key,
            'endpoint': endpoint,
            'attempts': attempts,
            'timestamp': int(time.time())
        }
        with open(PENDING_MARKER_PATH, 'w') as f:
            json.dump(obj, f)
        print(f"Wrote pending upload marker {PENDING_MARKER_PATH} (attempts={attempts})")
    except Exception as e:
        print(f"Failed to write pending marker: {e}")


def _remove_pending_marker():
    try:
        if os.path.exists(PENDING_MARKER_PATH):
            os.remove(PENDING_MARKER_PATH)
            print(f"Removed pending upload marker: {PENDING_MARKER_PATH}")
    except Exception as e:
        print(f"Failed to remove pending marker: {e}")


def upload_file(local_path: str, bucket: str, key: str, access_key: Optional[str], secret_key: Optional[str], endpoint: Optional[str], region: Optional[str], expires: int = 604800, overwrite: bool = False, max_attempts: int = 3):
    s3 = make_client(access_key, secret_key, endpoint, region)

    # Validate credentials early to give clearer errors
    try:
        validate_credentials(s3, bucket=bucket)
    except ClientError as e:
        code = getattr(e, 'response', {}).get('Error', {}).get('Code')
        msg = getattr(e, 'response', {}).get('Error', {}).get('Message', str(e))
        print(f"Credential check failed: {code} - {msg}")
        if code == 'InvalidAccessKeyId':
            print(
                "The provided Access Key ID is not valid for the S3 endpoint.\n"
                "If you are using Backblaze B2, make sure you created an S3-compatible application key (S3 credentials),\n"
                "not a B2 Native Application Key. In the Backblaze web console create an 'S3 Compatible' key for your bucket\n"
                "and use its KeyID/Application Key as B2_KEY/B2_SECRET. See: https://www.backblaze.com/b2/docs/s3_compatible_api.html\n"
            )
        raise

    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Local file not found: {local_path}")

    content_type, _ = mimetypes.guess_type(local_path)
    extra_args = {}
    if content_type:
        extra_args['ContentType'] = content_type

    # If overwrite not requested, check whether the object already exists and matches size
    if not overwrite:
        try:
            head = s3.head_object(Bucket=bucket, Key=key)
            remote_size = head.get('ContentLength')
            local_size = os.path.getsize(local_path)
            if remote_size == local_size:
                print(f"Object s3://{bucket}/{key} already exists with matching size ({remote_size} bytes); skipping upload.")
                # Generate presigned GET and return
                url = s3.generate_presigned_url(
                    ClientMethod='get_object',
                    Params={'Bucket': bucket, 'Key': key},
                    ExpiresIn=expires,
                )
                # Clean any pending marker (we succeeded logically)
                _remove_pending_marker()
                return url
            else:
                print(f"Object s3://{bucket}/{key} exists but size differs (remote={remote_size} local={local_size}); will upload and overwrite.")
        except ClientError as e:
            err_code = e.response.get('Error', {}).get('Code')
            # 404 / NotFound -> object does not exist, proceed to upload
            if err_code in ('404', 'NoSuchKey', 'NotFound'):
                pass
            else:
                # For other errors, re-raise for visibility
                raise

    # Prepare multipart transfer config (tunable)
    MB = 1024 * 1024
    transfer_config = TransferConfig(
        multipart_threshold=50 * MB,
        multipart_chunksize=50 * MB,
        max_concurrency=4,
        use_threads=True
    )

    # TransferConfig exposes attributes we configured; use getattr for safety
    tc_thresh = getattr(transfer_config, 'multipart_threshold', None)
    tc_chunksize = getattr(transfer_config, 'multipart_chunksize', None)
    tc_conc = getattr(transfer_config, 'max_concurrency', None)
    print(f"Uploading {local_path} -> s3://{bucket}/{key} (endpoint={endpoint}) using multipart_threshold={tc_thresh} chunk_size={tc_chunksize} concurrency={tc_conc}")

    local_size = os.path.getsize(local_path)

    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            # Use boto3 upload_file with TransferConfig for multipart support and concurrency
            s3.upload_file(local_path, bucket, key, ExtraArgs=extra_args, Config=transfer_config)
            # On success, remove any pending marker and return presigned URL
            url = s3.generate_presigned_url(
                ClientMethod='get_object',
                Params={'Bucket': bucket, 'Key': key},
                ExpiresIn=expires,
            )
            print(f"Upload succeeded on attempt {attempt}")
            _remove_pending_marker()
            return url
        except ClientError as e:
            code = getattr(e, 'response', {}).get('Error', {}).get('Code')
            msg = getattr(e, 'response', {}).get('Error', {}).get('Message', str(e))
            print(f"Attempt {attempt}/{max_attempts} - boto3 ClientError: {code} - {msg}")
            last_exc = e
        except Exception as e:
            print(f"Attempt {attempt}/{max_attempts} - upload exception: {e}")
            traceback.print_exc()
            last_exc = e

        # If not last attempt, backoff and retry
        if attempt < max_attempts:
            backoff = 2 ** (attempt - 1)
            print(f"Retrying upload after {backoff}s backoff...")
            time.sleep(backoff)
        else:
            print("Reached max upload attempts; will record pending marker for retry on next container start")
            try:
                _write_pending_marker(local_path, bucket, key, endpoint, attempt)
            except Exception as me:
                print(f"Failed to write pending marker: {me}")

    # If we reach here, all attempts failed
    raise last_exc if last_exc is not None else RuntimeError("Unknown upload failure")


def main(argv=None):
    parser = argparse.ArgumentParser(description='Upload a file to Backblaze B2 (S3-compatible) and print a presigned GET URL')
    parser.add_argument('--file', required=True, help='Local file path to upload')
    parser.add_argument('--bucket', required=True, help='Bucket name')
    parser.add_argument('--key', required=True, help='Object key (path) in bucket')
    # Accept both legacy and explicit b2-prefixed flags; region remains optional
    parser.add_argument('--endpoint', '--b2-endpoint', dest='endpoint', default=os.environ.get('B2_ENDPOINT'), help='S3-compatible endpoint (or set B2_ENDPOINT env)')
    parser.add_argument('--region', default=os.environ.get('B2_REGION'), help='Region name (optional)')
    parser.add_argument('--access-key', '--b2-key', dest='access_key', default=os.environ.get('B2_KEY') or os.environ.get('AWS_ACCESS_KEY_ID'), help='Access key id (or set B2_KEY env)')
    parser.add_argument('--secret-key', '--b2-secret', dest='secret_key', default=os.environ.get('B2_SECRET') or os.environ.get('AWS_SECRET_ACCESS_KEY'), help='Secret key (or set B2_SECRET env)')
    parser.add_argument('--overwrite', action='store_true', help='Force upload and overwrite existing object')
    parser.add_argument('--expires', type=int, default=604800, help='Presigned GET expiry seconds (default: 1 week)')
    parser.add_argument('--max-attempts', type=int, default=3, help='Max upload attempts before writing pending marker')
    args = parser.parse_args(argv)

    try:
        url = upload_file(args.file, args.bucket, args.key, args.access_key, args.secret_key, args.endpoint, args.region, expires=args.expires, overwrite=args.overwrite, max_attempts=args.max_attempts)
    except Exception as e:
        print('Upload failed:', e)
        # write a minimal result file for downstream diagnostics
        res = {'bucket': args.bucket, 'key': args.key, 'file': args.file, 'error': str(e)}
        try:
            with open('/workspace/realesrgan_upload_result.json', 'w') as fo:
                json.dump(res, fo)
        except Exception:
            pass
        return 2

    out = {'bucket': args.bucket, 'key': args.key, 'get_url': url}
    print(json.dumps(out, indent=2))
    # write result file for downstream scripts
    try:
        with open('/workspace/realesrgan_upload_result.json', 'w') as fo:
            json.dump(out, fo)
    except Exception:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
