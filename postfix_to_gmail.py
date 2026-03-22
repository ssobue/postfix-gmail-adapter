#!/usr/bin/env python

from __future__ import annotations

import argparse
import base64
import logging
import os
import pathlib
import socket
import sys
from email.parser import BytesHeaderParser
from pathlib import Path
from typing import Any, Optional

from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow

DEFAULT_GMAIL_USER = "me"
DEFAULT_LABELS = ("INBOX", "UNREAD")
SOCKET_TIMEOUT_SECONDS = 30

BASE_DIR = pathlib.Path(os.environ.get("BASE_DIR", "/opt/postfix-to-gmail"))
TOKEN_FILE = BASE_DIR / "token.json"
CREDENTIALS_FILE = BASE_DIR / "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.insert",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]

LOGGER = logging.getLogger("postfix_to_gmail")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import RFC 5322 messages from stdin into Gmail."
    )
    parser.add_argument(
        "--init-auth",
        action="store_true",
        help="Run the OAuth local server flow and save the token file, then exit.",
    )
    return parser.parse_args()


def parse_labels(raw_value: Optional[str]) -> list[str]:
    if raw_value is None or raw_value.strip() == "":
        return list(DEFAULT_LABELS)

    labels = [label.strip() for label in raw_value.split(",") if label.strip()]
    return labels or list(DEFAULT_LABELS)


def read_raw_message() -> bytes:
    raw_message = sys.stdin.buffer.read()
    if not raw_message:
        raise ValueError("stdin is empty")
    return raw_message


def extract_message_id(raw_message: bytes) -> Optional[str]:
    headers = BytesHeaderParser().parsebytes(raw_message)
    message_id = headers.get("Message-ID")
    if message_id is None:
        return None

    normalized = " ".join(message_id.split()).strip().strip("<>")
    if not normalized:
        return None
    return f"<{normalized}>"


def run_installed_app_flow(client_secrets_file: Path) -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), SCOPES)
    return flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=False,
        authorization_prompt_message="Open this URL in your browser:\n{url}",
        success_message="Authentication completed. You may close this window.",
    )


def get_google_creds(allow_interactive: bool) -> Credentials:
    creds: Optional[Credentials] = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not allow_interactive:
            raise RuntimeError(
                "OAuth token is missing or invalid. Run this script manually with --init-auth first."
            )
        creds = run_installed_app_flow(CREDENTIALS_FILE)

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def build_gmail_service(credentials: Credentials) -> Any:
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def message_already_exists(service: Any, user_id: str, message_id: str) -> bool:
    response = (
        service.users()
        .messages()
        .list(
            userId=user_id,
            q=f"rfc822msgid:{message_id}",
            includeSpamTrash=True,
            maxResults=1,
        )
        .execute()
    )
    return bool(response.get("messages"))


def import_message(
    service: Any,
    user_id: str,
    raw_message: bytes,
    label_ids: list[str],
) -> dict[str, Any]:
    encoded_message = base64.urlsafe_b64encode(raw_message).decode("ascii")
    body = {"raw": encoded_message, "labelIds": label_ids}
    return service.users().messages().import_(userId=user_id, body=body).execute()


def log_http_error(exc: HttpError) -> None:
    status = getattr(exc.resp, "status", "unknown")
    content = getattr(exc, "content", b"")
    details = ""
    if isinstance(content, bytes) and content:
        details = content.decode("utf-8", errors="replace")
    elif content:
        details = str(content)

    if details:
        LOGGER.error("Gmail API request failed: status=%s body=%s", status, details)
    else:
        LOGGER.error("Gmail API request failed: status=%s error=%s", status, exc)


def main() -> int:
    configure_logging()
    socket.setdefaulttimeout(SOCKET_TIMEOUT_SECONDS)

    try:
        args = parse_args()
        creds = get_google_creds(allow_interactive=args.init_auth)

        if args.init_auth:
            LOGGER.info("OAuth token initialized successfully: %s", TOKEN_FILE)
            return 0

        raw_message = read_raw_message()
        user_id = os.getenv("GMAIL_USER", DEFAULT_GMAIL_USER).strip() or DEFAULT_GMAIL_USER
        label_ids = parse_labels(os.getenv("GMAIL_LABELS"))
        service = build_gmail_service(creds)

        message_id = extract_message_id(raw_message)
        if message_id:
            LOGGER.info("Checking duplicate by Message-ID: %s", message_id)
            if message_already_exists(service, user_id, message_id):
                LOGGER.info("Duplicate message detected, skipping import: %s", message_id)
                return 0
        else:
            LOGGER.info("Message-ID not found, importing without duplicate check")

        response = import_message(service, user_id, raw_message, label_ids)
        LOGGER.info(
            "Imported message successfully: id=%s threadId=%s labels=%s",
            response.get("id", "unknown"),
            response.get("threadId", "unknown"),
            ",".join(label_ids),
        )
        return 0
    except ValueError as exc:
        LOGGER.error("Invalid input: %s", exc)
        return 1
    except (socket.timeout, TimeoutError) as exc:
        LOGGER.error("Operation timed out after %s seconds: %s", SOCKET_TIMEOUT_SECONDS, exc)
        return 1
    except HttpError as exc:
        log_http_error(exc)
        return 1
    except (GoogleAuthError, RefreshError) as exc:
        LOGGER.error("Google authentication failed: %s", exc)
        return 1
    except RuntimeError as exc:
        LOGGER.error("Configuration error: %s", exc)
        return 1
    except Exception:
        LOGGER.exception("Unexpected failure during Gmail import")
        return 1


if __name__ == "__main__":
    sys.exit(main())
