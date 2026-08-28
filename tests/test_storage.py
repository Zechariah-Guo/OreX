"""Unit tests for app.storage module.

Tests the StorageBackend interface, LocalStorage implementation,
OCIStorage implementation (mocked), and the get_storage_backend factory function.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.storage import LocalStorage, OCIStorage, StorageBackend, get_storage_backend


class TestLocalStorage:
    """Tests for the LocalStorage backend."""

    @pytest.fixture
    def tmp_upload_dir(self, tmp_path):
        """Create a temporary upload directory."""
        upload_dir = tmp_path / "uploads" / "avatars"
        upload_dir.mkdir(parents=True)
        return str(upload_dir)

    @pytest.fixture
    def storage(self, tmp_upload_dir):
        """Create a LocalStorage instance with a temp directory."""
        return LocalStorage(tmp_upload_dir)

    def test_is_storage_backend(self, storage):
        """LocalStorage implements the StorageBackend interface."""
        assert isinstance(storage, StorageBackend)

    def test_store_creates_file(self, storage, tmp_upload_dir):
        """store() writes file data to disk and returns the relative path."""
        data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        result = storage.store('test_user.png', data, 'image/png')

        assert result == 'static/uploads/avatars/test_user.png'
        file_path = os.path.join(tmp_upload_dir, 'test_user.png')
        assert os.path.exists(file_path)
        with open(file_path, 'rb') as f:
            assert f.read() == data

    def test_store_overwrites_existing(self, storage, tmp_upload_dir):
        """store() overwrites an existing file with the same name."""
        storage.store('user.webp', b'old data', 'image/webp')
        storage.store('user.webp', b'new data', 'image/webp')

        file_path = os.path.join(tmp_upload_dir, 'user.webp')
        with open(file_path, 'rb') as f:
            assert f.read() == b'new data'

    def test_delete_existing_file(self, storage, tmp_upload_dir):
        """delete() removes an existing file and returns True."""
        storage.store('to_delete.png', b'data', 'image/png')
        result = storage.delete('to_delete.png')

        assert result is True
        assert not os.path.exists(os.path.join(tmp_upload_dir, 'to_delete.png'))

    def test_delete_nonexistent_file(self, storage):
        """delete() returns False when the file does not exist."""
        result = storage.delete('nonexistent.png')
        assert result is False

    def test_get_url_returns_flask_static_url(self, app, storage):
        """get_url() returns a Flask static URL for the file."""
        with app.test_request_context():
            url = storage.get_url('user123.webp')
            assert 'uploads/avatars/user123.webp' in url


class TestGetStorageBackend:
    """Tests for the get_storage_backend factory function."""

    def test_default_returns_local_storage(self, app):
        """Factory returns LocalStorage when STORAGE_BACKEND is 'local'."""
        app.config['STORAGE_BACKEND'] = 'local'
        backend = get_storage_backend(app)

        assert isinstance(backend, LocalStorage)
        assert backend.upload_dir == os.path.join(app.static_folder, 'uploads', 'avatars')

    def test_unset_config_defaults_to_local(self, app):
        """Factory defaults to LocalStorage when STORAGE_BACKEND is not set."""
        app.config.pop('STORAGE_BACKEND', None)
        backend = get_storage_backend(app)

        assert isinstance(backend, LocalStorage)

    def test_oci_returns_oci_storage(self, app):
        """Factory returns OCIStorage when STORAGE_BACKEND is 'oci'."""
        app.config['STORAGE_BACKEND'] = 'oci'
        app.config['OCI_NAMESPACE'] = 'test-namespace'
        app.config['OCI_BUCKET'] = 'test-bucket'
        app.config['OCI_CONFIG_PATH'] = '~/.oci/config'

        with patch('app.storage.OCIStorage') as MockOCI:
            mock_instance = MagicMock()
            MockOCI.return_value = mock_instance
            backend = get_storage_backend(app)

            MockOCI.assert_called_once_with('test-namespace', 'test-bucket', '~/.oci/config')
            assert backend is mock_instance


class TestOCIStorage:
    """Tests for the OCIStorage backend (mocked OCI SDK)."""

    @pytest.fixture
    def mock_oci(self):
        """Mock the oci module for testing without the SDK installed."""
        mock_oci_module = MagicMock()
        mock_config = {'region': 'us-ashburn-1', 'user': 'ocid1.user.oc1..test'}
        mock_oci_module.config.from_file.return_value = mock_config
        mock_client = MagicMock()
        mock_oci_module.object_storage.ObjectStorageClient.return_value = mock_client
        return mock_oci_module, mock_config, mock_client

    @pytest.fixture
    def storage(self, mock_oci):
        """Create an OCIStorage instance with mocked OCI SDK."""
        mock_oci_module, mock_config, mock_client = mock_oci
        with patch.dict('sys.modules', {'oci': mock_oci_module,
                                         'oci.config': mock_oci_module.config,
                                         'oci.object_storage': mock_oci_module.object_storage}):
            instance = OCIStorage('test-namespace', 'test-bucket', '~/.oci/config')
        return instance

    def test_is_storage_backend(self, storage):
        """OCIStorage implements the StorageBackend interface."""
        assert isinstance(storage, StorageBackend)

    def test_init_loads_config_and_creates_client(self, mock_oci):
        """__init__ loads OCI config and creates ObjectStorageClient."""
        mock_oci_module, mock_config, mock_client = mock_oci
        with patch.dict('sys.modules', {'oci': mock_oci_module,
                                         'oci.config': mock_oci_module.config,
                                         'oci.object_storage': mock_oci_module.object_storage}):
            instance = OCIStorage('my-ns', 'my-bucket', '/path/to/config')

        mock_oci_module.config.from_file.assert_called_once_with('/path/to/config')
        mock_oci_module.object_storage.ObjectStorageClient.assert_called_once_with(mock_config)
        assert instance.namespace == 'my-ns'
        assert instance.bucket == 'my-bucket'

    def test_store_puts_object_and_returns_url(self, storage):
        """store() calls put_object and returns the public URL."""
        data = b'\x00\x01\x02\x03'
        result = storage.store('avatar.webp', data, 'image/webp')

        storage.client.put_object.assert_called_once_with(
            'test-namespace', 'test-bucket', 'avatar.webp', data,
            content_type='image/webp'
        )
        expected_url = (
            "https://objectstorage.us-ashburn-1.oraclecloud.com"
            "/n/test-namespace/b/test-bucket/o/avatar.webp"
        )
        assert result == expected_url

    def test_delete_existing_object(self, storage):
        """delete() calls delete_object and returns True on success."""
        result = storage.delete('avatar.webp')

        storage.client.delete_object.assert_called_once_with(
            'test-namespace', 'test-bucket', 'avatar.webp'
        )
        assert result is True

    def test_delete_nonexistent_object(self, storage):
        """delete() returns False when delete_object raises an exception."""
        storage.client.delete_object.side_effect = Exception("ObjectNotFound")
        result = storage.delete('missing.webp')

        assert result is False

    def test_get_url_format(self, storage):
        """get_url() returns correctly formatted OCI Object Storage URL."""
        url = storage.get_url('user123.webp')
        expected = (
            "https://objectstorage.us-ashburn-1.oraclecloud.com"
            "/n/test-namespace/b/test-bucket/o/user123.webp"
        )
        assert url == expected
