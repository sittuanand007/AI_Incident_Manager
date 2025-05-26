# incident_parser.py

import email
from email.header import decode_header
from email.utils import parseaddr
import re
from typing import Optional
import logging

from models import Incident # Assuming models.py defines the Incident Pydantic model

logger = logging.getLogger(__name__)

class IncidentParser:
    """
    Parses incoming raw data (e.g., email content) into a structured Incident object.
    """

    def _decode_header_value(self, header_value: Optional[str]) -> str:
        """Decodes email header values (e.g., Subject, From) if they are encoded."""
        if header_value is None:
            return ""
        decoded_parts = []
        try:
            for part, charset in decode_header(header_value):
                if isinstance(part, bytes):
                    # If charset is None, try common encodings or fall back to utf-8
                    decoded_parts.append(part.decode(charset or "utf-8", errors="replace"))
                else:
                    decoded_parts.append(part) # Already a string
        except Exception as e:
            logger.warning(f"Could not fully decode header part: {header_value}. Error: {e}")
            return header_value # Return original if decoding fails badly
        return "".join(decoded_parts)

    def _get_email_body(self, msg: email.message.Message) -> str:
        """
        Extracts and decodes the text body from an email.message.Message object.
        Prioritizes 'text/plain' over 'text/html'.
        """
        body = ""
        if msg.is_multipart():
            plain_text_parts = []
            html_text_parts = [] # Collect HTML parts in case plain text is not available
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # Skip attachments
                if "attachment" in content_disposition.lower():
                    continue

                charset = part.get_content_charset() or "utf-8" # Default to utf-8 if not specified
                payload = part.get_payload(decode=True) # Decode from base64 or quoted-printable

                try:
                    text_content = payload.decode(charset, errors="replace") # Replace undecodable chars
                    if content_type == "text/plain":
                        plain_text_parts.append(text_content)
                    elif content_type == "text/html":
                        html_text_parts.append(text_content)
                except Exception as e:
                    logger.warning(f"Could not decode email part with charset {charset}: {e}. Content-Type: {content_type}")
            
            if plain_text_parts:
                body = "\n".join(plain_text_parts)
            elif html_text_parts: # Fallback to HTML if no plain text
                logger.debug("No text/plain part found, using text/html part.")
                html_body = "\n".join(html_text_parts)
                # Basic HTML to text conversion: remove style, script, and all other tags.
                # For robust HTML parsing, consider libraries like BeautifulSoup.
                body = re.sub(r'<style[^>]*>.*?</style>', '', html_body, flags=re.DOTALL | re.IGNORECASE)
                body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.DOTALL | re.IGNORECASE)
                body = re.sub(r'<[^>]+>', ' ', body) # Replace tags with a space
                body = re.sub(r'\s+', ' ', body).strip() # Normalize whitespace
        else: # Not multipart (plain text or HTML email)
            charset = msg.get_content_charset() or "utf-8"
            payload = msg.get_payload(decode=True)
            try:
                body = payload.decode(charset, errors="replace")
                if msg.get_content_type() == "text/html": # If it's HTML, strip tags
                    body = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL | re.IGNORECASE)
                    body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.DOTALL | re.IGNORECASE)
                    body = re.sub(r'<[^>]+>', ' ', body)
                    body = re.sub(r'\s+', ' ', body).strip()
            except Exception as e:
                logger.warning(f"Could not decode non-multipart email body with charset {charset}: {e}")
        
        return body.strip()

    def parse_email_to_incident(
        self, 
        imap_msg_uid: str, 
        raw_email_bytes: bytes, 
        agent_sender_email: Optional[str] = None
    ) -> Optional[Incident]:
        """
        Parses raw email bytes (fetched via IMAP) into a structured Incident object.
        Returns None if parsing fails or the email is deemed irrelevant (e.g., auto-reply, sent by agent itself).

        Args:
            imap_msg_uid: The UID of the message from the IMAP server (for logging/tracing).
            raw_email_bytes: The raw byte content of the email.
            agent_sender_email: The email address of the agent itself, to avoid self-processing loops.
        """
        try:
            msg = email.message_from_bytes(raw_email_bytes)

            subject = self._decode_header_value(msg.get("Subject", "(No Subject)"))
            from_header_decoded = self._decode_header_value(msg.get("From", ""))
            # parseaddr returns (Real Name, email_address)
            sender_email_address = parseaddr(from_header_decoded)[1].lower()

            # --- Filter out irrelevant emails ---
            lower_subject = subject.lower()
            common_auto_reply_phrases = [
                "auto-reply", "out of office", "automatic reply", 
                "undeliverable", "delivery status notification", "non-remise"
            ]
            if any(phrase in lower_subject for phrase in common_auto_reply_phrases):
                logger.info(f"Skipping email UID {imap_msg_uid} (auto-reply/OOO/DSN based on subject): '{subject}'")
                return None

            # Check for X-Auto-Response-Suppress header (used by Exchange etc. to prevent auto-replies)
            if msg.get("X-Auto-Response-Suppress") and "All" in msg.get("X-Auto-Response-Suppress", ""):
                logger.info(f"Skipping email UID {imap_msg_uid} (X-Auto-Response-Suppress header found): '{subject}'")
                return None
            
            # Check for Auto-Submitted header (RFC 3834) - common for automated messages
            auto_submitted_header = msg.get("Auto-Submitted", "").lower()
            if auto_submitted_header and auto_submitted_header != "no": # "no" means it's not auto-submitted
                logger.info(f"Skipping email UID {imap_msg_uid} (Auto-Submitted: {auto_submitted_header}): '{subject}'")
                return None

            if agent_sender_email and sender_email_address == agent_sender_email.lower():
                logger.info(f"Skipping email UID {imap_msg_uid} as it was sent by the agent itself ({agent_sender_email}). Subject: '{subject}'")
                return None
            # --- End of filters ---

            body_text = self._get_email_body(msg)
            
            # Use Message-ID as the primary unique ID if available; it's generally more globally unique.
            # Fall back to IMAP UID if Message-ID is not present.
            message_id_header = self._decode_header_value(msg.get("Message-ID"))
            incident_id = message_id_header.strip("<>") if message_id_header else f"imap-uid-{imap_msg_uid}"
            
            logger.debug(f"Successfully parsed email. UID: {imap_msg_uid}, Incident ID: {incident_id}, Subject: '{subject}'")

            return Incident(
                id=incident_id,
                source="email",
                subject=subject.strip(),
                body=body_text,
                raw_content=raw_email_bytes.decode('utf-8', errors='ignore') # Store for audit/debugging
            )
        except Exception as e:
            logger.error(f"Fatal error parsing email UID {imap_msg_uid}: {e}", exc_info=True)
            return None

    # Future extensibility:
    # def parse_api_payload_to_incident(self, payload: dict) -> Optional[Incident]:
    #     """Parses a JSON payload from a monitoring API into an Incident object."""
    #     # Implementation would depend on the API's payload structure
    #     pass