import base64
from email import message_from_bytes

from app.integrations.gmail.service import GmailService


def test_gmail_mime_contains_recipients_subject_and_body() -> None:
    raw = GmailService._mime(["to@example.com"], "Atlas update", "Hello from Atlas", ["cc@example.com"], None)
    message = message_from_bytes(base64.urlsafe_b64decode(raw))

    assert message["To"] == "to@example.com"
    assert message["Cc"] == "cc@example.com"
    assert message["Subject"] == "Atlas update"
    assert "Hello from Atlas" in message.get_payload()


def test_gmail_message_parser_extracts_headers_and_plain_text_body() -> None:
    encoded = base64.urlsafe_b64encode(b"Travel plans").decode().rstrip("=")
    parsed = GmailService._parse_message(
        {
            "id": "gmail-message-id",
            "threadId": "thread-id",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "To", "value": "atlas@example.com"},
                    {"name": "Subject", "value": "Travel"},
                ],
                "body": {"data": encoded},
            },
        }
    )

    assert parsed.sender == "sender@example.com"
    assert parsed.subject == "Travel"
    assert parsed.body == "Travel plans"
