#!/usr/bin/env python3
"""
b2_presign.py

Generate presigned GET and PUT URLs for Backblaze B2 using the S3-compatible API (boto3).

Usage:
  # simplest: rely on env vars B2_KEY, B2_SECRET
  python b2_presign.py --bucket my-bucket --key input/test_60_short.mp4

  # explicit credentials and custom endpoint
  python b2_presign.py \
    --bucket my-bucket --key input/test_60_short.mp4 \
    --access-key YOUR_KEY --secret-key YOUR_SECRET \
    --endpoint https://s3.us-west-000.backblazeb2.com --expires 3600

Output: prints JSON with get_url and put_url (put allows uploading back the output file).

Note:
- For Backblaze B2 with S3 compatibility, set the endpoint to the S3-compatible endpoint for your account/region,
  for example: https://s3.us-west-000.backblazeb2.com
- For objects >5GB use multipart uploads (not handled here). For ~1GB single PUT is fine.
"""

import os
import sys
import json
import argparse
from typing import Optional

try:
    import boto3
    from botocore.client import Config
except Exception:
    print("Missing dependency: boto3. Install with `pip install boto3`.")
    raise


def make_client(access_key: Optional[str], secret_key: Optional[str], endpoint: Optional[str], region: Optional[str]):
    kwargs = {}
    if access_key and secret_key:
        kwargs['aws_access_key_id'] = access_key
        kwargs['aws_secret_access_key'] = secret_key
    if region:
        kwargs['region_name'] = region
    elif endpoint and 'us-west-004' in endpoint:
        kwargs['region_name'] = 'us-west-004'
    if endpoint:
        # reduce signature version issues
        cfg = Config(s3={'addressing_style': 'virtual'})
        client = boto3.client('s3', endpoint_url=endpoint, config=cfg, **kwargs)
    else:
        client = boto3.client('s3', **kwargs)
    return client


def generate_presigned(bucket: str, key: str, access_key: Optional[str], secret_key: Optional[str], endpoint: Optional[str], region: Optional[str], expires: int = 3600):
    s3 = make_client(access_key, secret_key, endpoint, region)

    # presigned GET
    get_url = s3.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=expires,
    )

    # presigned PUT - don't include ContentType in params for B2 compatibility
    # B2 will accept the file without explicit Content-Type in the presigned URL
    put_url = s3.generate_presigned_url(
        ClientMethod='put_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=expires,
    )

    return {'get_url': get_url, 'put_url': put_url}


def list_objects(bucket: str, prefix: str, access_key: Optional[str] = None, secret_key: Optional[str] = None, endpoint: Optional[str] = None, region: Optional[str] = None):
    """List objects in bucket with given prefix using B2 API"""
    import requests
    # Fallback to environment variables if explicit creds/endpoints not provided
    access_key = access_key or os.environ.get('B2_KEY') or os.environ.get('AWS_ACCESS_KEY_ID')
    secret_key = secret_key or os.environ.get('B2_SECRET') or os.environ.get('AWS_SECRET_ACCESS_KEY')
    endpoint = endpoint or os.environ.get('B2_ENDPOINT')
    region = region or os.environ.get('B2_REGION')

    # B2 API endpoints
    auth_url = "https://api.backblazeb2.com/b2api/v2/b2_authorize_account"
    list_url = "https://api.backblazeb2.com/b2api/v2/b2_list_file_names"

    # Get credentials
    account_id = access_key
    application_key = secret_key

    if not account_id or not application_key:
        raise ValueError("B2_KEY and B2_SECRET required (pass as args or set B2_KEY/B2_SECRET env vars)")

    # Authorize
    auth_response = requests.get(auth_url, auth=(account_id, application_key))
    auth_response.raise_for_status()
    auth_data = auth_response.json()

    api_url = auth_data['apiUrl']
    auth_token = auth_data['authorizationToken']
    account_id = auth_data['accountId']

    # List files
    headers = {
        'Authorization': auth_token
    }

    # First, get bucket ID
    bucket_url = f"{api_url}/b2api/v2/b2_list_buckets"
    bucket_response = requests.post(bucket_url, headers=headers, json={'accountId': account_id})
    bucket_response.raise_for_status()
    bucket_data = bucket_response.json()

    bucket_id = None
    for b in bucket_data['buckets']:
        if b['bucketName'] == bucket:
            bucket_id = b['bucketId']
            break

    if not bucket_id:
        raise ValueError(f"Bucket {bucket} not found")

    # List files
    headers = {
        'Authorization': auth_token
    }

    params = {
        'bucketId': bucket_id,
        'prefix': prefix
    }

    # List files
    list_response = requests.post(f"{api_url}/b2api/v2/b2_list_file_names", headers=headers, json=params)
    list_response.raise_for_status()
    list_data = list_response.json()

    objects = []
    for file_info in list_data['files']:
        objects.append({
            'key': file_info.get('fileName', ''),
            'size': file_info.get('size', 0),
            'last_modified': file_info.get('uploadTimestamp', 0),
            'etag': file_info.get('fileId', '')
        })

    return objects


def main(argv=None):
    parser = argparse.ArgumentParser(description='Generate presigned GET and PUT URLs for Backblaze B2 (S3-compatible)')
    parser.add_argument('--bucket', required=True, help='Bucket name')
    parser.add_argument('--key', required=True, help='Object key (path)')
    parser.add_argument('--access-key', help='Backblaze (S3) access key id (or leave to use env)')
    parser.add_argument('--secret-key', help='Backblaze (S3) secret (or leave to use env)')
    parser.add_argument('--endpoint', default=os.environ.get('B2_ENDPOINT', 'https://s3.us-west-000.backblazeb2.com'), help='S3-compatible endpoint URL')
    parser.add_argument('--region', default=os.environ.get('B2_REGION', None), help='Region name (optional)')
    parser.add_argument('--expires', type=int, default=604800, help='URL expiry seconds (default: 1 week)')
    args = parser.parse_args(argv)

    access_key = args.access_key or os.environ.get('B2_KEY') or os.environ.get('AWS_ACCESS_KEY_ID')
    secret_key = args.secret_key or os.environ.get('B2_SECRET') or os.environ.get('AWS_SECRET_ACCESS_KEY')

    if not access_key or not secret_key:
        print('Warning: no explicit access key/secret provided; boto3 will try other credential providers (env, profile).')

    try:
        urls = generate_presigned(args.bucket, args.key, access_key, secret_key, args.endpoint, args.region, expires=args.expires)
    except Exception as e:
        print('Error generating presigned URLs:', e)
        return 2

    # Print the resulting URLs as JSON
    print(json.dumps(urls, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
