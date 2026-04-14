import uuid
from fastapi import UploadFile, HTTPException, status
from app.core.supabase import supabase_admin
from app.core.config import settings

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_DOC_TYPES   = {"application/pdf"}
MAX_FILE_SIZE_MB    = 10


async def upload_file(
    file: UploadFile,
    bucket: str,
    folder: str = "",
    allowed_types: set[str] = None,
) -> str:
    """
    Faz upload de um arquivo para o Supabase Storage.
    Retorna a URL pública do arquivo.
    """
    if allowed_types and file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Tipo de arquivo não permitido: {file.content_type}",
        )

    content = await file.read()

    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Arquivo muito grande. Máximo: {MAX_FILE_SIZE_MB}MB",
        )

    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "bin"
    file_name = f"{folder}/{uuid.uuid4()}.{ext}" if folder else f"{uuid.uuid4()}.{ext}"

    supabase_admin.storage.from_(bucket).upload(
        path=file_name,
        file=content,
        file_options={"content-type": file.content_type},
    )

    public_url = supabase_admin.storage.from_(bucket).get_public_url(file_name)
    return public_url


async def upload_photo(file: UploadFile, folder: str = "photos") -> str:
    return await upload_file(
        file,
        bucket=settings.storage_bucket_photos,
        folder=folder,
        allowed_types=ALLOWED_IMAGE_TYPES,
    )


async def upload_signature(file: UploadFile, folder: str = "signatures") -> str:
    return await upload_file(
        file,
        bucket=settings.storage_bucket_signatures,
        folder=folder,
        allowed_types=ALLOWED_IMAGE_TYPES,
    )


async def upload_document(file: UploadFile, folder: str = "docs") -> str:
    return await upload_file(
        file,
        bucket=settings.storage_bucket_documents,
        folder=folder,
        allowed_types=ALLOWED_DOC_TYPES | ALLOWED_IMAGE_TYPES,
    )


async def upload_logo(file: UploadFile) -> str:
    return await upload_file(
        file,
        bucket=settings.storage_bucket_logos,
        folder="",
        allowed_types=ALLOWED_IMAGE_TYPES,
    )


def delete_file(bucket: str, path: str) -> None:
    """Remove um arquivo do Supabase Storage pelo caminho."""
    supabase_admin.storage.from_(bucket).remove([path])
