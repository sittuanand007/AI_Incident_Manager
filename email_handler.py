# email_handler.py

import imaplib
import smtplib
import email # For email.message.Message and email.utils
from email.mime.text import MIMEText
from typing import List, Optional, Set
import logging

from config_manager import ConfigManager
from incident_parser import IncidentParser # Assuming IncidentParser is in incident_parser.py
from models import Incident # Assuming Incident model is in models.py

logger = logging.getLogger(__name__)

class EmailHandler:
    """
    Handles fetching new emails (potential incidents) from an IMAP server
    and sending notifications/acknowledgements via SMTP.
    """
    def __init__(self, config: ConfigManager, parser: IncidentParser):
        self.config = config
        self.parser = parser
        # This set stores unique Incident IDs (Message-ID or fallback) of emails
        # that have been fetched AND successfully parsed into an Incident object OR
        # determined to be irrelevant by the parser.
        # For a production system, this should be a persistent store (DB, file)
        # to avoid reprocessing emails if the agent restarts and IMAP 'SEEN' flags are lost/reset.
        self.processed_incident_ids: Set[str] = set()

    def _connect_imap(self) -> Optional[imaplib.IMAP4_SSL]:
        """Connects to the IMAP server and selects the inbox."""
        if not all([self.config.imap_server, self.config.imap_username, self.config.imap_password]):
            logger.error("IMAP server, username, or password not configured. Cannot fetch emails.")
            return None
        try:
            logger.debug(f"Connecting to IMAP server: {self.config.imap_server}")
            mail_server = imaplib.IMAP4_SSL(self.config.imap_server)
            mail_server.login(self.config.imap_username, self.config.imap_password)
            status, _ = mail_server.select("inbox") # Connect to the inbox.
            if status != 'OK':
                logger.error(f"Failed to select INBOX on IMAP server. Status: {status}")
                mail_server.logout()
                return None
            logger.debug("Successfully connected to IMAP and selected inbox.")
            return mail_server
        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP login/connection error: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error connecting to IMAP server: {e}", exc_info=True)
            return None

    def fetch_new_incidents_from_email(self) -> List[Incident]:
        """
        Fetches new, unread emails from the inbox, parses them into Incident objects.
        Marks successfully processed or irrelevant emails as 'Seen' on the IMAP server.
        Uses `processed_incident_ids` for deduplication based on Message-ID if available.
        """
        new_incidents: List[Incident] = []
        mail_server = self._connect_imap()
        if not mail_server:
            return new_incidents # Return empty list if connection failed

        try:
            # Search for all unseen emails.
            # Other criteria can be used, e.g., 'NEW' (unread since last select), 'SINCE "01-Jan-2023"'
            status, message_uids_bytes = mail_server.search(None, "UNSEEN")
            if status != "OK":
                logger.error(f"IMAP search for UNSEEN emails failed with status: {status}")
                return new_incidents

            email_imap_uids = message_uids_bytes[0].split() # These are UIDs or sequence numbers as bytes
            if not email_imap_uids:
                logger.info("No new unread emails found in this cycle (based on UNSEEN).")
                return new_incidents
            
            logger.info(f"Found {len(email_imap_uids)} new unread email(s) by IMAP UID based on UNSEEN search.")

            for imap_msg_uid_bytes in email_imap_uids:
                imap_msg_uid_str = imap_msg_uid_bytes.decode() # For logging and internal use
                
                # Fetch the full email (RFC822)
                # Using UID FETCH is generally more reliable with UIDs if the server supports it well.
                # If search returns sequence numbers, use those directly.
                # For simplicity, we assume search returns identifiers usable with FETCH.
                status, msg_data = mail_server.fetch(imap_msg_uid_bytes, "(RFC822)")
                
                if status == "OK":
                    raw_email_bytes = None
                    # msg_data is a list, typically with one item for the fetched email
                    for response_part in msg_data:
                        if isinstance(response_part, tuple) and response_part[0].endswith(b'(RFC822)'):
                            raw_email_bytes = response_part[1]
                            break 

                    if raw_email_bytes:
                        # Attempt to parse the email into an Incident object
                        incident = self.parser.parse_email_to_incident(
                            imap_msg_uid=imap_msg_uid_str,
                            raw_email_bytes=raw_email_bytes,
                            agent_sender_email=self.config.sender_email # To avoid self-loops
                        )
                        
                        if incident: # Successfully parsed into a potential incident
                            if incident.id in self.processed_incident_ids:
                                logger.info(f"Skipping already processed incident (ID: {incident.id}, IMAP UID: {imap_msg_uid_str}). Marking as seen.")
                            else:
                                new_incidents.append(incident)
                                self.processed_incident_ids.add(incident.id) # Add unique Incident ID
                                logger.info(f"Successfully parsed new incident (ID: {incident.id}) from IMAP UID {imap_msg_uid_str}.")
                        else: # Parser returned None (e.g., auto-reply, parsing error, or self-sent)
                            # The parser logs why it skipped. We just note it was handled.
                            logger.info(f"Parser determined email IMAP UID {imap_msg_uid_str} is not a processable incident or failed parsing.")
                            # Add a placeholder to processed_ids if Message-ID could be extracted even for non-incidents
                            # to prevent re-parsing errors. For now, we rely on parser to return Incident object.

                        # Mark email as seen on the server regardless of whether it's a valid incident or not,
                        # to prevent it from being fetched again by "UNSEEN" search.
                        # For production, consider moving processed/irrelevant emails to a specific folder.
                        mail_server.store(imap_msg_uid_bytes, '+FLAGS', '\\Seen')
                        logger.debug(f"Marked IMAP UID {imap_msg_uid_str} as \\Seen.")
                    else:
                        logger.warning(f"Could not retrieve RFC822 content for IMAP UID {imap_msg_uid_str}, though fetch status was OK.")
                else:
                    logger.error(f"Failed to fetch email content for IMAP UID {imap_msg_uid_str}. Status: {status}")
            
            # If using move+delete for processed emails:
            # if mail_server.select('inbox')[0] == 'OK': # ensure inbox is still selected
            #    mail_server.expunge()
            #    logger.info("Expunged emails marked for deletion from inbox.")

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP operation error during email fetching: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error fetching or processing emails: {e}", exc_info=True)
        finally:
            if mail_server:
                try:
                    mail_server.close()
                    mail_server.logout()
                    logger.debug("IMAP connection closed and logged out.")
                except Exception as e_close:
                    logger.error(f"Error closing/logging out IMAP connection: {e_close}")
        
        return new_incidents

    def send_acknowledgement_email(self, incident: Incident, recipient_email: Optional[str] = None):
        """Sends an acknowledgement email for a processed incident via SMTP."""
        if not all([self.config.smtp_server, self.config.sender_email, 
                    self.config.smtp_username, self.config.smtp_password]):
            logger.warning("SMTP server, sender email, or credentials not fully configured. Skipping email acknowledgement.")
            incident.add_note("Acknowledgement email skipped: SMTP not configured.")
            return

        actual_recipient = recipient_email or incident.assigned_team_email
        if not actual_recipient:
            logger.warning(f"No recipient email for acknowledgement of incident {incident.id}. Skipping.")
            incident.add_note(f"Acknowledgement email skipped: No recipient email determined.")
            return

        # Construct email subject and body
        subject = f"RE: {incident.subject} [Incident ACK - ID: {incident.id}]"
        body_content = (
            f"Hello,\n\n"
            f"This is an automated message from {self.config.agent_name}.\n"
            f"We have received your incident report titled: '{incident.subject}'.\n\n"
            f"Initial Assessment:\n"
            f"- Incident Source ID: {incident.id}\n" # This is the Message-ID or IMAP UID
            f"- Assigned Priority: {incident.priority or 'Pending Classification'}\n"
            f"- Assigned Team: {incident.assigned_team or 'Pending Assignment'}\n"
        )
        if incident.jira_ticket_key:
            jira_ticket_url = f"{self.config.jira_url.rstrip('/')}/browse/{incident.jira_ticket_key}"
            body_content += f"- Jira Ticket: {incident.jira_ticket_key} (Link: {jira_ticket_url})\n"
        
        body_content += (
            f"\nThis incident is being processed. You will receive further updates from the assigned team.\n\n"
            f"Regards,\n{self.config.agent_name}"
        )

        msg = MIMEText(body_content)
        msg['Subject'] = subject
        msg['From'] = self.config.sender_email
        msg['To'] = actual_recipient
        
        # Add In-Reply-To and References headers to thread the email correctly if it's a reply to original
        if incident.source == "email" and incident.id.startswith("<") and incident.id.endswith(">"): # Check if ID is a Message-ID
            msg['In-Reply-To'] = incident.id
            msg['References'] = incident.id
        elif incident.source == "email" and incident.raw_content: # Try to get Message-ID from raw_content
             try:
                original_email_msg = email.message_from_string(incident.raw_content)
                original_message_id = original_email_msg.get('Message-ID')
                if original_message_id:
                    msg['In-Reply-To'] = original_message_id
                    msg['References'] = original_message_id
             except Exception as e:
                logger.debug(f"Could not parse Message-ID from raw_content for incident {incident.id} for threading: {e}")


        try:
            logger.info(f"Attempting to send acknowledgement for incident {incident.id} to {actual_recipient} via {self.config.smtp_server}:{self.config.smtp_port}")
            with smtplib.SMTP(self.config.smtp_server, self.config.smtp_port) as server:
                server.ehlo() # Extended Hello
                server.starttls() # Enable TLS encryption
                server.ehlo() # Re-send EHLO after STARTTLS
                server.login(self.config.smtp_username, self.config.smtp_password)
                server.sendmail(self.config.sender_email, [actual_recipient], msg.as_string())
            logger.info(f"Acknowledgement email sent for incident {incident.id} to {actual_recipient}.")
            incident.is_acknowledged = True
            incident.add_note(f"Acknowledgement email sent to {actual_recipient}.")
        except smtplib.SMTPException as e:
            logger.error(f"SMTP Error sending acknowledgement for incident {incident.id} to {actual_recipient}: {e}", exc_info=True)
            incident.add_note(f"Failed to send acknowledgement email (SMTP Error): {e}")
        except Exception as e:
            logger.error(f"Unexpected error sending acknowledgement email for incident {incident.id}: {e}", exc_info=True)
            incident.add_note(f"Failed to send acknowledgement email (Unexpected Error): {e}")