"""S3 Multipart Upload Service using boto3.

Provides high-performance direct uploads to MinIO/S3 by generating
presigned URLs for parallel part uploads.
"""
import boto3
from botocore.config import Config
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, urlunparse
from app.config import get_settings

settings = get_settings()


class S3MultipartService:
    """Service for S3 Multipart Upload operations."""

    def __init__(self):
        # Internal client for S3 operations
        endpoint_url = f"http{'s' if settings.MINIO_SECURE else ''}://{settings.MINIO_ENDPOINT}"

        self.s3_client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            config=Config(signature_version='s3v4'),
            region_name='us-east-1'  # MinIO requires a region
        )

        # Presigned URL client - use internal endpoint for signature generation
        # URLs will be transformed to use nginx proxy to avoid CORS
        self.presigned_client = boto3.client(
            's3',
            endpoint_url=endpoint_url,  # Use internal endpoint
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            config=Config(signature_version='s3v4'),
            region_name='us-east-1'
        )

        self.bucket = settings.MINIO_BUCKET

        # Nginx proxy endpoint for browser uploads (avoids CORS)
        # Uses /storage/ path prefix which nginx proxies to MinIO
        self.nginx_proxy_endpoint = settings.MINIO_PUBLIC_ENDPOINT or settings.MINIO_ENDPOINT

    def _transform_url_for_nginx_proxy(self, url: str) -> str:
        """
        Transform presigned URL to use nginx /storage/ proxy.

        This avoids CORS preflight requests since the browser sees
        the same origin (nginx) for both API and storage requests.
        """
        parsed = urlparse(url)
        # Replace host with nginx endpoint and add /storage prefix to path
        new_netloc = self.nginx_proxy_endpoint
        new_path = f"/storage{parsed.path}"
        return urlunparse((
            'http',  # scheme
            new_netloc,  # netloc (host:port)
            new_path,  # path with /storage prefix
            parsed.params,
            parsed.query,  # query string with S3 signature
            parsed.fragment
        ))

    def create_multipart_upload(
        self,
        object_key: str,
        content_type: Optional[str] = None
    ) -> str:
        """
        Start a multipart upload and return the upload_id.

        Args:
            object_key: Object key (path) in the bucket
            content_type: MIME type of the file

        Returns:
            upload_id: S3 multipart upload ID
        """
        params = {
            'Bucket': self.bucket,
            'Key': object_key
        }
        if content_type:
            params['ContentType'] = content_type

        response = self.s3_client.create_multipart_upload(**params)
        return response['UploadId']

    def generate_part_presigned_urls(
        self,
        object_key: str,
        upload_id: str,
        file_size: int,
        part_size: int = 10 * 1024 * 1024  # 10MB default
    ) -> List[Dict[str, Any]]:
        """
        Generate presigned URLs for each part of a multipart upload.

        Args:
            object_key: Object key in the bucket
            upload_id: S3 multipart upload ID
            file_size: Total file size in bytes
            part_size: Size of each part in bytes

        Returns:
            List of part info with presigned URLs
        """
        parts = []
        part_number = 1
        offset = 0

        while offset < file_size:
            end = min(offset + part_size, file_size) - 1

            # Generate presigned URL for this part
            url = self.presigned_client.generate_presigned_url(
                'upload_part',
                Params={
                    'Bucket': self.bucket,
                    'Key': object_key,
                    'UploadId': upload_id,
                    'PartNumber': part_number
                },
                ExpiresIn=3600  # 1 hour
            )

            # Transform URL to use nginx proxy (avoids CORS preflight)
            proxy_url = self._transform_url_for_nginx_proxy(url)

            parts.append({
                'part_number': part_number,
                'presigned_url': proxy_url,
                'start': offset,
                'end': end,
                'size': end - offset + 1
            })

            offset += part_size
            part_number += 1

        return parts

    def complete_multipart_upload(
        self,
        object_key: str,
        upload_id: str,
        parts: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Complete a multipart upload.

        Args:
            object_key: Object key in the bucket
            upload_id: S3 multipart upload ID
            parts: List of completed parts with part_number and etag

        Returns:
            S3 completion response
        """
        # Sort parts by part number
        sorted_parts = sorted(parts, key=lambda x: x['part_number'])

        response = self.s3_client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=object_key,
            UploadId=upload_id,
            MultipartUpload={
                'Parts': [
                    {
                        'PartNumber': p['part_number'],
                        'ETag': p['etag']
                    }
                    for p in sorted_parts
                ]
            }
        )
        return response

    def abort_multipart_upload(self, object_key: str, upload_id: str) -> None:
        """
        Abort/cancel a multipart upload.

        Args:
            object_key: Object key in the bucket
            upload_id: S3 multipart upload ID
        """
        self.s3_client.abort_multipart_upload(
            Bucket=self.bucket,
            Key=object_key,
            UploadId=upload_id
        )

    def generate_simple_presigned_url(
        self,
        object_key: str,
        content_type: Optional[str] = None,
        expires: int = 3600
    ) -> str:
        """
        Generate a simple presigned PUT URL for small files.

        For files under the part size threshold, a single PUT is more efficient.

        Args:
            object_key: Object key in the bucket
            content_type: MIME type of the file
            expires: URL expiration time in seconds

        Returns:
            Presigned URL for PUT request
        """
        params = {
            'Bucket': self.bucket,
            'Key': object_key
        }
        if content_type:
            params['ContentType'] = content_type

        return self.presigned_client.generate_presigned_url(
            'put_object',
            Params=params,
            ExpiresIn=expires
        )


# Global service instance
_s3_multipart_service = None


def get_s3_multipart_service() -> S3MultipartService:
    """Get or create the S3 multipart service instance."""
    global _s3_multipart_service
    if _s3_multipart_service is None:
        _s3_multipart_service = S3MultipartService()
    return _s3_multipart_service
