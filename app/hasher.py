"""파일 무결성 검증 및 SHA-256 해시 계산 모듈."""

import hashlib
from pathlib import Path

def calculate_file_hash(file_path: Path, chunk_size: int = 65536) -> str:
    """주어진 파일의 SHA-256 해시값을 계산하여 16진수 문자열로 반환한다."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()
