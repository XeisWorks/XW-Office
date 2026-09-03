from __future__ import annotations

import json

import httpx
import pytest

from xw_office.services.filename_generator.models import FilenameGeneratorError
from xw_office.services.filename_generator.wix_media_upload import WixMediaUploadService


class _Secrets:
    def __init__(self, api_key: str = "secret-key", site_id: str = "site-123") -> None:
        self._values = {"WIX_API_KEY": api_key, "WIX_SITE_ID": site_id}

    def get_secret(self, name: str) -> str:
        return self._values.get(name, "")


def _json_response(request: httpx.Request, payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, request=request, content=json.dumps(payload).encode())


def test_upload_creates_exact_folder_path_without_leaking_api_key(tmp_path) -> None:
    source = tmp_path / "sk-t__03__btb__teacher.mp3"
    source.write_bytes(b"audio")
    created: list[tuple[str, str]] = []
    upload_headers: dict[str, str] = {}
    list_file_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal list_file_calls
        if request.url.host == "uploads.wix.test":
            upload_headers.update(dict(request.headers))
            assert request.content == b"audio"
            return _json_response(
                request,
                {"file": {"id": "file-1", "displayName": source.name}},
            )
        if request.method == "GET" and request.url.path.endswith("/folders"):
            return _json_response(request, {"folders": []})
        if request.method == "POST" and request.url.path.endswith("/folders"):
            body = json.loads(request.content)
            created.append((body["displayName"], body["parentFolderId"]))
            return _json_response(
                request,
                {"folder": {"id": f"folder-{len(created)}", "displayName": body["displayName"]}},
            )
        if request.method == "GET" and request.url.path.endswith("/files"):
            list_file_calls += 1
            if list_file_calls == 1:
                return _json_response(request, {"files": []})
            return _json_response(
                request,
                {
                    "files": [
                        {
                            "id": "file-1",
                            "displayName": source.name,
                            "url": "wix:audio://file-1",
                            "state": "READY",
                        }
                    ]
                },
            )
        if request.method == "POST" and request.url.path.endswith("/generate-upload-url"):
            body = json.loads(request.content)
            assert body["parentFolderId"] == "folder-5"
            assert request.headers["authorization"] == "secret-key"
            assert request.headers["wix-site-id"] == "site-123"
            return _json_response(request, {"uploadUrl": "https://uploads.wix.test/file"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = WixMediaUploadService(
        _Secrets(),  # type: ignore[arg-type]
        transport=httpx.MockTransport(handler),
    )

    result = service.upload_files([source], "/MH-Tracks/sk-t/btb/uploads/batch-1")

    assert result.folder.path == "/MH-Tracks/sk-t/btb/uploads/batch-1"
    assert result.folder.folder_id == "folder-5"
    assert result.files[0].file_url == "wix:audio://file-1"
    assert created == [
        ("MH-Tracks", "media-root"),
        ("sk-t", "folder-1"),
        ("btb", "folder-2"),
        ("uploads", "folder-3"),
        ("batch-1", "folder-4"),
    ]
    assert "authorization" not in upload_headers
    assert "wix-site-id" not in upload_headers


def test_upload_blocks_existing_same_name(tmp_path) -> None:
    source = tmp_path / "sk-t__01__btb__practice.mp3"
    source.write_bytes(b"new")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/folders"):
            return _json_response(
                request,
                {"folders": [{"id": "target", "displayName": "existing"}]},
            )
        if request.url.path.endswith("/files"):
            return _json_response(request, {"files": [{"displayName": source.name}]})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = WixMediaUploadService(
        _Secrets(),  # type: ignore[arg-type]
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(FilenameGeneratorError, match="gleichnamige"):
        service.upload_files([source], "/existing")


def test_upload_requires_wix_credentials(tmp_path) -> None:
    source = tmp_path / "sk-t__01__btb__practice.mp3"
    source.write_bytes(b"audio")
    service = WixMediaUploadService(_Secrets(api_key=""))  # type: ignore[arg-type]

    with pytest.raises(FilenameGeneratorError, match="WIX_API_KEY"):
        service.upload_files([source], "/MH-Tracks/test")
