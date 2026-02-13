"""Shared checksum utilities."""
import hashlib

_CHUNK_SIZE = 1024 * 1024  # 1 MB


def calculate_file_checksum(file_path: str) -> str:
    """Calculate SHA256 checksum of a file (synchronous)."""
    hash_sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(_CHUNK_SIZE):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()


async def calculate_file_checksum_async(file_path: str) -> str:
    """Calculate SHA256 checksum of a file (asynchronous)."""
    import aiofiles
    hash_sha256 = hashlib.sha256()
    async with aiofiles.open(file_path, 'rb') as f:
        while chunk := await f.read(_CHUNK_SIZE):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()
