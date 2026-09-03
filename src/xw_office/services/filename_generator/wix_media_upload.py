"""Direct, preview-safe uploads to a precise Wix Media Manager folder."""
from __future__ import annotations

import mimetypes
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import httpx

from xw_office.services.filename_generator.models import FilenameGeneratorError

if TYPE_CHECKING:
    from xw_office.services.secrets.service import SecretService

_API_BASE = "https://www.wixapis.com/site-media/v1"
_READY_STATES = {"OK", "READY"}
_MAX_LIST_PAGE_SIZE = 100


@dataclass(frozen=True)
class WixMediaFolder:
    folder_id: str
    display_name: str
    path: str


@dataclass(frozen=True)
class WixMediaUploadedFile:
    local_path: Path
    file_id: str
    display_name: str
    file_url: str


@dataclass(frozen=True)
class WixMediaUploadResult:
    folder: WixMediaFolder
    files: tuple[WixMediaUploadedFile, ...]
    processing_complete: bool = True


class WixMediaUploadService:
    """Upload local MP3 files using the configured Wix API key and site ID."""

    def __init__(
        self,
        secret_service: SecretService,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._secrets = secret_service
        self._transport = transport

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key() and self._site_id())

    def list_folder_files(self, target_path: str) -> tuple[WixMediaFolder, list[dict[str, Any]]]:
        """Read-only listing of an existing Wix Media folder's files, for the CMS import."""
        folder_parts = self._normalize_folder_path(target_path)
        if not self.is_configured:
            raise FilenameGeneratorError(
                "Wix ist nicht konfiguriert. Bitte WIX_API_KEY und WIX_SITE_ID in den Einstellungen prüfen."
            )
        with httpx.Client(
            base_url=_API_BASE,
            headers=self._headers(),
            timeout=httpx.Timeout(60.0, connect=20.0),
            transport=self._transport,
        ) as api_client:
            folder = self._resolve_or_create_folder(api_client, folder_parts)
            files = self._list_files(api_client, folder.folder_id)
        return folder, files

    def upload_files(
        self,
        files: Sequence[Path | str],
        target_path: str,
        *,
        progress: Callable[[int, str], None] | None = None,
    ) -> WixMediaUploadResult:
        sources = self._validate_sources(files)
        folder_parts = self._normalize_folder_path(target_path)
        if not self.is_configured:
            raise FilenameGeneratorError(
                "Wix ist nicht konfiguriert. Bitte WIX_API_KEY und WIX_SITE_ID in den Einstellungen prüfen."
            )

        with httpx.Client(
            base_url=_API_BASE,
            headers=self._headers(),
            timeout=httpx.Timeout(60.0, connect=20.0),
            transport=self._transport,
        ) as api_client:
            folder = self._resolve_or_create_folder(api_client, folder_parts)
            existing_names = {
                self._file_display_name(item).casefold()
                for item in self._list_files(api_client, folder.folder_id)
                if self._file_display_name(item)
            }
            collisions = [source.name for source in sources if source.name.casefold() in existing_names]
            if collisions:
                raise FilenameGeneratorError(
                    "Im Wix-Zielordner existieren bereits gleichnamige Dateien: "
                    + ", ".join(collisions)
                )

            uploaded: list[WixMediaUploadedFile] = []
            total = len(sources)
            for index, source in enumerate(sources, start=1):
                if progress:
                    progress(round((index - 1) * 90 / total), f"Lade {source.name} hoch …")
                try:
                    uploaded.append(self._upload_one(api_client, folder, source))
                except FilenameGeneratorError as exc:
                    partial = (
                        f" {len(uploaded)} zuvor hochgeladene Datei(en) bleiben im Batch-Ordner; "
                        "für einen neuen Versuch bitte einen neuen Batch-Pfad verwenden."
                        if uploaded
                        else ""
                    )
                    raise FilenameGeneratorError(f"{exc}{partial}") from exc

            if progress:
                progress(92, "Warte auf die Verarbeitung im Wix Media Manager …")
            ready_files, processing_complete = self._wait_until_listed(
                api_client, folder.folder_id, uploaded
            )
            if progress:
                message = (
                    f"{len(ready_files)} Datei(en) hochgeladen."
                    if processing_complete
                    else "Upload angenommen; Wix verarbeitet mindestens eine Audiodatei noch."
                )
                progress(100, message)
            return WixMediaUploadResult(
                folder=folder,
                files=tuple(ready_files),
                processing_complete=processing_complete,
            )

    def _api_key(self) -> str:
        # A separate data/media key may deliberately have narrower Wix scopes than
        # the general integration key. It stays environment-only, so it is not
        # exposed in the general settings UI.
        data_key = os.getenv("WIX_API_KEY_DATA", "").strip()
        return data_key or str(self._secrets.get_secret("WIX_API_KEY") or "").strip()

    def _site_id(self) -> str:
        return str(self._secrets.get_secret("WIX_SITE_ID") or "").strip()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._api_key(),
            "wix-site-id": self._site_id(),
            "Content-Type": "application/json",
        }

    @staticmethod
    def _validate_sources(files: Sequence[Path | str]) -> list[Path]:
        if not files:
            raise FilenameGeneratorError("Keine gültigen MP3-Dateien zum Hochladen gefunden.")
        result: list[Path] = []
        seen: set[Path] = set()
        for value in files:
            source = Path(value).expanduser().resolve()
            if source in seen:
                continue
            if not source.is_file() or source.suffix.casefold() != ".mp3":
                raise FilenameGeneratorError(f'Keine lesbare MP3-Datei: "{source.name}".')
            seen.add(source)
            result.append(source)
        return result

    @staticmethod
    def _normalize_folder_path(value: str) -> tuple[str, ...]:
        raw = str(value or "").strip().replace("\\", "/")
        parts = tuple(part.strip() for part in PurePosixPath(raw).parts if part not in {"", "/"})
        if not parts:
            raise FilenameGeneratorError("Bitte einen Wix-Zielordner angeben.")
        if any(part in {".", ".."} or len(part) > 200 for part in parts):
            raise FilenameGeneratorError("Der Wix-Zielpfad enthält ein ungültiges Segment.")
        return parts

    def _resolve_or_create_folder(
        self,
        client: httpx.Client,
        parts: tuple[str, ...],
    ) -> WixMediaFolder:
        parent_id = "media-root"
        resolved: list[str] = []
        for part in parts:
            matches = [
                folder
                for folder in self._list_folders(client, parent_id)
                if self._folder_display_name(folder).casefold() == part.casefold()
            ]
            if len(matches) > 1:
                raise FilenameGeneratorError(
                    f'Der Wix-Ordner "{part}" ist unterhalb von "/{"/".join(resolved)}" nicht eindeutig.'
                )
            if matches:
                folder_data = matches[0]
            else:
                response = client.post(
                    "/folders",
                    json={"displayName": part, "parentFolderId": parent_id},
                )
                folder_data = self._response_json(response, "Wix-Ordner anlegen").get("folder", {})
            folder_id = self._folder_id(folder_data)
            if not folder_id:
                raise FilenameGeneratorError(f'Wix lieferte für den Ordner "{part}" keine ID.')
            parent_id = folder_id
            resolved.append(self._folder_display_name(folder_data) or part)
        return WixMediaFolder(parent_id, resolved[-1], "/" + "/".join(resolved))

    def _list_folders(self, client: httpx.Client, parent_id: str) -> list[dict[str, Any]]:
        response = client.get(
            "/folders",
            params={"parentFolderId": parent_id, "paging.limit": _MAX_LIST_PAGE_SIZE},
        )
        payload = self._response_json(response, "Wix-Ordner lesen")
        return [item for item in payload.get("folders", []) if isinstance(item, dict)]

    def _list_files(self, client: httpx.Client, folder_id: str) -> list[dict[str, Any]]:
        response = client.get(
            "/files",
            params={"parentFolderId": folder_id, "paging.limit": _MAX_LIST_PAGE_SIZE},
        )
        payload = self._response_json(response, "Wix-Dateien lesen")
        return [item for item in payload.get("files", []) if isinstance(item, dict)]

    def _upload_one(
        self,
        api_client: httpx.Client,
        folder: WixMediaFolder,
        source: Path,
    ) -> WixMediaUploadedFile:
        mime_type = mimetypes.guess_type(source.name)[0] or "audio/mpeg"
        response = api_client.post(
            "/files/generate-upload-url",
            json={
                "mimeType": mime_type,
                "fileName": source.name,
                "parentFolderId": folder.folder_id,
                "private": False,
            },
        )
        payload = self._response_json(response, f"Upload-URL für {source.name} erzeugen")
        upload_url = str(payload.get("uploadUrl") or "").strip()
        if not upload_url:
            raise FilenameGeneratorError(f'Wix lieferte für "{source.name}" keine Upload-URL.')

        # The signed URL authorizes the upload itself. Never forward the Wix API key
        # to the upload host, which may differ from www.wixapis.com.
        with httpx.Client(
            timeout=httpx.Timeout(300.0, connect=30.0),
            transport=self._transport,
        ) as upload_client, source.open("rb") as file_handle:
            upload_response = upload_client.put(
                upload_url,
                headers={"Content-Type": mime_type},
                content=file_handle,
            )
        upload_payload = self._response_json(upload_response, f"{source.name} hochladen")
        file_data = upload_payload.get("file", upload_payload)
        if not isinstance(file_data, dict):
            file_data = {}
        return WixMediaUploadedFile(
            local_path=source,
            file_id=self._file_id(file_data),
            display_name=self._file_display_name(file_data) or source.name,
            file_url=self._file_url(file_data),
        )

    def _wait_until_listed(
        self,
        client: httpx.Client,
        folder_id: str,
        uploaded: list[WixMediaUploadedFile],
    ) -> tuple[list[WixMediaUploadedFile], bool]:
        expected = {item.display_name.casefold(): item for item in uploaded}
        deadline = time.monotonic() + 60.0
        while True:
            listed = self._list_files(client, folder_id)
            by_name = {
                self._file_display_name(item).casefold(): item
                for item in listed
                if self._file_display_name(item)
            }
            if all(name in by_name and self._file_is_ready(by_name[name]) for name in expected):
                return [
                    WixMediaUploadedFile(
                        local_path=item.local_path,
                        file_id=self._file_id(by_name[name]) or item.file_id,
                        display_name=self._file_display_name(by_name[name]) or item.display_name,
                        file_url=self._file_url(by_name[name]) or item.file_url,
                    )
                    for name, item in expected.items()
                ], True
            if time.monotonic() >= deadline:
                return uploaded, False
            time.sleep(2.0)

    @staticmethod
    def _folder_id(data: dict[str, Any]) -> str:
        return str(data.get("id") or data.get("folderId") or "").strip()

    @staticmethod
    def _folder_display_name(data: dict[str, Any]) -> str:
        return str(data.get("displayName") or data.get("folderName") or "").strip()

    @staticmethod
    def _file_id(data: dict[str, Any]) -> str:
        return str(data.get("id") or data.get("fileId") or "").strip()

    @staticmethod
    def _file_display_name(data: dict[str, Any]) -> str:
        return str(data.get("displayName") or data.get("originalFileName") or "").strip()

    @staticmethod
    def _file_url(data: dict[str, Any]) -> str:
        return str(data.get("url") or data.get("fileUrl") or "").strip()

    @staticmethod
    def _file_is_ready(data: dict[str, Any]) -> bool:
        state = str(data.get("state") or data.get("operationStatus") or "").strip().upper()
        return state in _READY_STATES or (not state and bool(WixMediaUploadService._file_url(data)))

    @staticmethod
    def _response_json(response: httpx.Response, operation: str) -> dict[str, Any]:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                payload = response.json()
                message = payload.get("message") or payload.get("error", {}).get("message")
            except (ValueError, AttributeError):
                message = ""
            detail = f": {message}" if message else f" (HTTP {response.status_code})"
            raise FilenameGeneratorError(operation + detail) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise FilenameGeneratorError(f"{operation}: Wix lieferte keine JSON-Antwort.") from exc
        if not isinstance(payload, dict):
            raise FilenameGeneratorError(f"{operation}: Unerwartete Wix-Antwort.")
        return payload
