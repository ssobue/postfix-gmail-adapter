import base64
import importlib
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def install_google_stubs() -> None:
    google_module = types.ModuleType("google")
    google_auth_module = types.ModuleType("google.auth")
    google_auth_exceptions_module = types.ModuleType("google.auth.exceptions")
    google_auth_transport_module = types.ModuleType("google.auth.transport")
    google_auth_transport_requests_module = types.ModuleType("google.auth.transport.requests")
    google_oauth2_module = types.ModuleType("google.oauth2")
    google_oauth2_credentials_module = types.ModuleType("google.oauth2.credentials")
    googleapiclient_module = types.ModuleType("googleapiclient")
    googleapiclient_discovery_module = types.ModuleType("googleapiclient.discovery")
    googleapiclient_errors_module = types.ModuleType("googleapiclient.errors")
    google_auth_oauthlib_module = types.ModuleType("google_auth_oauthlib")
    google_auth_oauthlib_flow_module = types.ModuleType("google_auth_oauthlib.flow")

    class GoogleAuthError(Exception):
        pass

    class RefreshError(Exception):
        pass

    class HttpError(Exception):
        def __init__(self, resp=None, content=None):
            super().__init__("http error")
            self.resp = resp
            self.content = content

    class Request:
        pass

    class Credentials:
        def __init__(self, valid=True, expired=False, refresh_token=None):
            self.valid = valid
            self.expired = expired
            self.refresh_token = refresh_token

        @classmethod
        def from_authorized_user_file(cls, filename, scopes=None):
            raise NotImplementedError("stubbed Credentials.from_authorized_user_file")

        def refresh(self, request):
            raise NotImplementedError("stubbed Credentials.refresh")

        def to_json(self):
            return "{}"

    class InstalledAppFlow:
        @classmethod
        def from_client_secrets_file(cls, filename, scopes):
            raise NotImplementedError("stubbed InstalledAppFlow.from_client_secrets_file")

    def build(*args, **kwargs):
        raise NotImplementedError("stubbed googleapiclient.discovery.build")

    google_auth_module.exceptions = google_auth_exceptions_module
    google_auth_exceptions_module.GoogleAuthError = GoogleAuthError
    google_auth_exceptions_module.RefreshError = RefreshError
    google_auth_transport_requests_module.Request = Request
    google_auth_transport_module.requests = google_auth_transport_requests_module
    google_oauth2_credentials_module.Credentials = Credentials
    google_oauth2_module.credentials = google_oauth2_credentials_module
    googleapiclient_discovery_module.build = build
    googleapiclient_errors_module.HttpError = HttpError
    googleapiclient_module.discovery = googleapiclient_discovery_module
    googleapiclient_module.errors = googleapiclient_errors_module
    google_auth_oauthlib_flow_module.InstalledAppFlow = InstalledAppFlow
    google_auth_oauthlib_module.flow = google_auth_oauthlib_flow_module

    google_module.auth = google_auth_module
    google_module.oauth2 = google_oauth2_module

    sys.modules["google"] = google_module
    sys.modules["google.auth"] = google_auth_module
    sys.modules["google.auth.exceptions"] = google_auth_exceptions_module
    sys.modules["google.auth.transport"] = google_auth_transport_module
    sys.modules["google.auth.transport.requests"] = google_auth_transport_requests_module
    sys.modules["google.oauth2"] = google_oauth2_module
    sys.modules["google.oauth2.credentials"] = google_oauth2_credentials_module
    sys.modules["googleapiclient"] = googleapiclient_module
    sys.modules["googleapiclient.discovery"] = googleapiclient_discovery_module
    sys.modules["googleapiclient.errors"] = googleapiclient_errors_module
    sys.modules["google_auth_oauthlib"] = google_auth_oauthlib_module
    sys.modules["google_auth_oauthlib.flow"] = google_auth_oauthlib_flow_module


try:
    postfix_to_gmail = importlib.import_module("postfix_to_gmail")
except ModuleNotFoundError:
    install_google_stubs()
    sys.modules.pop("postfix_to_gmail", None)
    postfix_to_gmail = importlib.import_module("postfix_to_gmail")


class FakeStdin:
    def __init__(self, payload: bytes):
        self.buffer = io.BytesIO(payload)


class PostfixToGmailTests(unittest.TestCase):
    def run_main(
        self,
        payload: bytes,
        service=None,
        env=None,
        build_error=None,
        init_auth=False,
    ) -> int:
        if env is None:
            env = {}

        build_patcher = (
            patch.object(postfix_to_gmail, "build_gmail_service", side_effect=build_error)
            if build_error is not None
            else patch.object(postfix_to_gmail, "build_gmail_service", return_value=service)
        )

        with patch.object(postfix_to_gmail, "configure_logging"), patch.object(
            postfix_to_gmail.socket, "setdefaulttimeout"
        ), patch.object(postfix_to_gmail.LOGGER, "info"), patch.object(
            postfix_to_gmail.LOGGER, "error"
        ), patch.object(
            postfix_to_gmail.LOGGER, "exception"
        ), patch.dict(
            postfix_to_gmail.os.environ, env, clear=True
        ), patch.object(
            postfix_to_gmail.sys, "stdin", FakeStdin(payload)
        ), patch.object(
            postfix_to_gmail, "parse_args", return_value=types.SimpleNamespace(init_auth=init_auth)
        ), patch.object(
            postfix_to_gmail, "get_google_creds", return_value=object()
        ), build_patcher:
            return postfix_to_gmail.main()

    def test_parse_labels_uses_defaults_for_blank_value(self) -> None:
        self.assertEqual(postfix_to_gmail.parse_labels(None), ["INBOX", "UNREAD"])
        self.assertEqual(postfix_to_gmail.parse_labels("   "), ["INBOX", "UNREAD"])
        self.assertEqual(
            postfix_to_gmail.parse_labels(" INBOX, UNREAD , ,STARRED "),
            ["INBOX", "UNREAD", "STARRED"],
        )

    def test_extract_message_id_normalizes_angle_brackets_and_whitespace(self) -> None:
        raw_message = (
            b"Message-ID:   <abc123@example.com>\r\n"
            b"Subject: test\r\n"
            b"\r\n"
            b"hello\r\n"
        )

        self.assertEqual(
            postfix_to_gmail.extract_message_id(raw_message),
            "<abc123@example.com>",
        )

    def test_import_message_base64url_encodes_original_bytes(self) -> None:
        service = MagicMock()
        execute_mock = service.users.return_value.messages.return_value.import_.return_value.execute
        execute_mock.return_value = {"id": "message-1", "threadId": "thread-1"}
        raw_message = b"Subject: Test\r\n\r\nhello world\r\n"

        response = postfix_to_gmail.import_message(
            service,
            "me",
            raw_message,
            ["INBOX", "UNREAD"],
        )

        expected_raw = base64.urlsafe_b64encode(raw_message).decode("ascii")
        service.users.return_value.messages.return_value.import_.assert_called_once_with(
            userId="me",
            body={"raw": expected_raw, "labelIds": ["INBOX", "UNREAD"]},
        )
        self.assertEqual(response["id"], "message-1")

    def test_get_google_creds_reads_existing_token_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "token.json"
            token_file.write_text("{}", encoding="utf-8")
            creds = MagicMock(valid=True)

            with patch.object(postfix_to_gmail, "TOKEN_FILE", token_file), patch.object(
                postfix_to_gmail.Credentials,
                "from_authorized_user_file",
                return_value=creds,
            ) as from_file_mock:
                result = postfix_to_gmail.get_google_creds(allow_interactive=False)

            from_file_mock.assert_called_once_with(str(token_file), postfix_to_gmail.SCOPES)
            self.assertIs(result, creds)

    def test_get_google_creds_refreshes_expired_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "token.json"
            token_file.write_text("{}", encoding="utf-8")
            creds = MagicMock(valid=False, expired=True, refresh_token="refresh-token")
            creds.to_json.return_value = '{"token":"refreshed"}'

            with patch.object(postfix_to_gmail, "TOKEN_FILE", token_file), patch.object(
                postfix_to_gmail.Credentials,
                "from_authorized_user_file",
                return_value=creds,
            ):
                result = postfix_to_gmail.get_google_creds(allow_interactive=False)

            creds.refresh.assert_called_once()
            self.assertEqual(token_file.read_text(encoding="utf-8"), '{"token":"refreshed"}')
            self.assertIs(result, creds)

    def test_get_google_creds_raises_when_token_missing_in_non_interactive_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "missing-token.json"

            with patch.object(postfix_to_gmail, "TOKEN_FILE", token_file):
                with self.assertRaises(RuntimeError):
                    postfix_to_gmail.get_google_creds(allow_interactive=False)

    def test_get_google_creds_runs_interactive_flow_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "token.json"
            client_secrets_file = Path(temp_dir) / "credentials.json"
            client_secrets_file.write_text('{"installed": {}}', encoding="utf-8")
            creds = MagicMock(valid=True)
            creds.to_json.return_value = '{"token":"interactive"}'

            with patch.object(postfix_to_gmail, "TOKEN_FILE", token_file), patch.object(
                postfix_to_gmail, "CREDENTIALS_FILE", client_secrets_file
            ), patch.object(
                postfix_to_gmail,
                "run_installed_app_flow",
                return_value=creds,
            ) as flow_mock:
                result = postfix_to_gmail.get_google_creds(allow_interactive=True)

            flow_mock.assert_called_once_with(client_secrets_file)
            self.assertEqual(token_file.read_text(encoding="utf-8"), '{"token":"interactive"}')
            self.assertIs(result, creds)

    def test_main_skips_import_when_duplicate_message_id_exists(self) -> None:
        service = MagicMock()
        service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "existing"}]
        }

        exit_code = self.run_main(
            b"Message-ID: <dup@example.com>\r\nSubject: Hi\r\n\r\nBody\r\n",
            service=service,
        )

        self.assertEqual(exit_code, 0)
        service.users.return_value.messages.return_value.list.assert_called_once_with(
            userId="me",
            q="rfc822msgid:<dup@example.com>",
            includeSpamTrash=True,
            maxResults=1,
        )
        service.users.return_value.messages.return_value.import_.assert_not_called()

    def test_main_imports_when_message_id_is_missing(self) -> None:
        service = MagicMock()
        service.users.return_value.messages.return_value.import_.return_value.execute.return_value = {
            "id": "new-message",
            "threadId": "thread-1",
        }
        raw_message = b"Subject: No Message ID\r\n\r\nBody\r\n"

        exit_code = self.run_main(
            raw_message,
            service=service,
            env={"GMAIL_USER": "me", "GMAIL_LABELS": "INBOX, UNREAD"},
        )

        self.assertEqual(exit_code, 0)
        service.users.return_value.messages.return_value.list.assert_not_called()
        expected_raw = base64.urlsafe_b64encode(raw_message).decode("ascii")
        service.users.return_value.messages.return_value.import_.assert_called_once_with(
            userId="me",
            body={"raw": expected_raw, "labelIds": ["INBOX", "UNREAD"]},
        )

    def test_main_returns_non_zero_when_authentication_fails(self) -> None:
        with patch.object(postfix_to_gmail, "configure_logging"), patch.object(
            postfix_to_gmail.socket, "setdefaulttimeout"
        ), patch.object(
            postfix_to_gmail, "parse_args", return_value=types.SimpleNamespace(init_auth=False)
        ), patch.object(
            postfix_to_gmail,
            "get_google_creds",
            side_effect=postfix_to_gmail.GoogleAuthError("boom"),
        ), patch.object(
            postfix_to_gmail.LOGGER, "error"
        ):
            exit_code = postfix_to_gmail.main()

        self.assertEqual(exit_code, 1)

    def test_main_returns_non_zero_when_stdin_is_empty(self) -> None:
        exit_code = self.run_main(b"")
        self.assertEqual(exit_code, 1)

    def test_main_initializes_auth_and_exits(self) -> None:
        with patch.object(postfix_to_gmail, "configure_logging"), patch.object(
            postfix_to_gmail.socket, "setdefaulttimeout"
        ), patch.object(
            postfix_to_gmail, "parse_args", return_value=types.SimpleNamespace(init_auth=True)
        ), patch.object(
            postfix_to_gmail, "get_google_creds", return_value=object()
        ), patch.object(
            postfix_to_gmail, "TOKEN_FILE", Path("/tmp/gmail-token.json")
        ), patch.object(
            postfix_to_gmail.LOGGER, "info"
        ):
            exit_code = postfix_to_gmail.main()

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
