"""Storage abstraction for file uploads (avatars).

Provides a pluggable backend system:
- LocalStorage: stores files on the local filesystem (development)
- OCIStorage: Oracle Object Storage (production)

The active backend is selected via the STORAGE_BACKEND config key.
"""

import abc
import os

from flask import url_for


class StorageBackend(abc.ABC):
    """Abstract base class for file storage backends."""

    @abc.abstractmethod
    def store(self, filename: str, data: bytes, content_type: str) -> str:
        """Store file data.

        Args:
            filename: The name to store the file under.
            data: Raw file bytes.
            content_type: MIME type of the file (e.g. 'image/webp').

        Returns:
            The path or URL to access the stored file.
        """

    @abc.abstractmethod
    def delete(self, filename: str) -> bool:
        """Delete a stored file.

        Args:
            filename: The name of the file to delete.

        Returns:
            True if the file was deleted, False if it was not found.
        """

    @abc.abstractmethod
    def get_url(self, filename: str) -> str:
        """Get the public URL or path for a stored file.

        Args:
            filename: The name of the stored file.

        Returns:
            A URL string that can be used in templates to serve the file.
        """


class LocalStorage(StorageBackend):
    """Store files in static/uploads/avatars/ for development."""

    def __init__(self, upload_dir: str):
        self.upload_dir = upload_dir  # absolute path to static/uploads/avatars/

    def store(self, filename: str, data: bytes, content_type: str) -> str:
        path = os.path.join(self.upload_dir, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
        return f"static/uploads/avatars/{filename}"

    def delete(self, filename: str) -> bool:
        path = os.path.join(self.upload_dir, filename)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def get_url(self, filename: str) -> str:
        return url_for('static', filename=f'uploads/avatars/{filename}')


class OCIStorage(StorageBackend):
    """Store files in Oracle Cloud Infrastructure Object Storage."""

    def __init__(self, namespace: str, bucket: str, config_path: str):
        import oci
        self.config = oci.config.from_file(config_path)
        self.client = oci.object_storage.ObjectStorageClient(self.config)
        self.namespace = namespace
        self.bucket = bucket

    def store(self, filename: str, data: bytes, content_type: str) -> str:
        self.client.put_object(self.namespace, self.bucket, filename, data, content_type=content_type)
        return self.get_url(filename)

    def delete(self, filename: str) -> bool:
        try:
            self.client.delete_object(self.namespace, self.bucket, filename)
            return True
        except Exception:
            return False

    def get_url(self, filename: str) -> str:
        return (
            f"https://objectstorage.{self.config['region']}.oraclecloud.com"
            f"/n/{self.namespace}/b/{self.bucket}/o/{filename}"
        )


def get_storage_backend(app) -> StorageBackend:
    """Factory: return the configured storage backend.

    Reads app.config['STORAGE_BACKEND'] to determine which backend to use.
    Defaults to 'local' (LocalStorage) if not set.
    """
    backend = app.config.get('STORAGE_BACKEND', 'local')
    if backend == 'oci':
        namespace = app.config['OCI_NAMESPACE']
        bucket = app.config['OCI_BUCKET']
        config_path = app.config['OCI_CONFIG_PATH']
        return OCIStorage(namespace, bucket, config_path)
    else:
        upload_dir = os.path.join(app.static_folder, 'uploads', 'avatars')
        return LocalStorage(upload_dir)
