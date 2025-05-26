# jira_handler.py

from jira import JIRA, JIRAError # jira library for interacting with Jira
import logging
from typing import Optional

from models import Incident # Assuming Incident model is in models.py
from config_manager import ConfigManager # Assuming ConfigManager is in config_manager.py

logger = logging.getLogger(__name__)

class JiraHandler:
    """
    Handles interactions with a Jira instance, primarily for creating tickets.
    """
    def __init__(self, config: ConfigManager):
        self.config = config
        self.jira_client: Optional[JIRA] = None
        self._connect_to_jira()

    def _connect_to_jira(self):
        """
        Establishes a connection to the Jira server using credentials from config.
        Sets `self.jira_client` to the JIRA object if successful, or None otherwise.
        """
        if not all([self.config.jira_url, self.config.jira_username, self.config.jira_api_token]):
            logger.warning("Jira URL, username, or API token not fully configured. Jira integration will be disabled.")
            self.jira_client = None
            return

        try:
            logger.info(f"Attempting to connect to Jira server: {self.config.jira_url}")
            # Options for Jira connection, server URL is primary
            jira_options = {'server': self.config.jira_url.rstrip('/')} # Ensure no trailing slash

            self.jira_client = JIRA(
                options=jira_options,
                basic_auth=(self.config.jira_username, self.config.jira_api_token)
            )
            # Test connection by trying to fetch projects (a lightweight call)
            self.jira_client.projects() 
            logger.info(f"Successfully connected to Jira server: {self.config.jira_url}")
        except JIRAError as e:
            # JIRAError often contains useful status_code and text from Jira API
            logger.error(f"Jira API Error during connection: Status {e.status_code} - {e.text}", exc_info=True)
            self.jira_client = None
        except Exception as e: 
            # Catch other potential errors (e.g., network issues, invalid URL format)
            logger.error(f"An unexpected error occurred during Jira connection attempt: {e}", exc_info=True)
            self.jira_client = None

    def create_jira_ticket_for_incident(self, incident: Incident) -> Optional[str]:
        """
        Creates a Jira ticket for a given incident.
        This method is typically called for P1 incidents as per requirements.

        Args:
            incident: The Incident object for which to create a Jira ticket.

        Returns:
            The Jira ticket key (e.g., "PROJECT-123") if successful, otherwise None.
        """
        if not self.jira_client:
            message = "Jira client is not initialized or connection failed. Cannot create ticket."
            incident.add_note(message)
            logger.error(f"Incident {incident.id}: {message}")
            return None

        # This check might be redundant if agent.py already filters, but good for direct use
        if incident.priority != "P1":
            message = f"Incident priority is {incident.priority}, not P1. Jira ticket creation skipped by rule."
            incident.add_note(message)
            logger.info(f"Incident {incident.id}: {message}")
            return None

        # Prepare Jira issue fields
        summary = f"P1 Incident: {incident.subject}"
        # Jira summary fields often have a length limit (e.g., 255 chars)
        max_summary_len = 254 
        if len(summary) > max_summary_len:
            summary = summary[:max_summary_len-3] + "..." # Truncate with ellipsis
            logger.warning(f"Incident {incident.id}: Summary was truncated to {max_summary_len} characters for Jira.")

        # Construct a detailed description for the Jira ticket
        description_parts = [
            f"Automated P1 Incident Report from: {self.config.agent_name}",
            f"Source System: {incident.source}",
            f"Source Incident ID: {incident.id}", # e.g., Email Message-ID
            f"Detected Priority: {incident.priority}",
            f"Auto-Assigned Team: {incident.assigned_team or 'N/A'}",
            f"\nOriginal Subject:\n{incident.subject}",
            f"\nOriginal Body/Details:\n{'-'*20}\n{incident.body if incident.body else '(No body content provided)'}\n{'-'*20}",
            f"\nAgent Processing Notes:"
        ]
        description_parts.extend([f"- {note}" for note in incident.processing_notes])
        description = "\n".join(description_parts)

        issue_dict = {
            'project': {'key': self.config.jira_project_key},
            'summary': summary,
            'description': description,
            'issuetype': {'name': self.config.jira_p1_issue_type},
            # Optional: Add labels, components, custom fields, assignee, etc.
            # 'labels': ['auto-created', 'p1-incident', incident.assigned_team.lower() if incident.assigned_team else 'unassigned'],
            # 'components': [{'name': 'CriticalSystems'}], # Ensure component 'CriticalSystems' exists
            # Example for assignee (ensure 'jira_default_assignee' is a valid Jira username):
            # 'assignee': {'name': self.config.get('Jira', 'DefaultP1Assignee', fallback=None)},
        }
        
        # Remove None values from assignee if not set, to avoid Jira API errors
        # if 'assignee' in issue_dict and not issue_dict['assignee']['name']:
        #     del issue_dict['assignee']

        try:
            logger.info(f"Attempting to create Jira P1 ticket for incident {incident.id} in project '{self.config.jira_project_key}' with type '{self.config.jira_p1_issue_type}'.")
            new_issue = self.jira_client.create_issue(fields=issue_dict)
            
            incident.jira_ticket_key = new_issue.key # Store the created ticket key (e.g., "ITSM-123")
            message = f"Jira ticket {new_issue.key} created successfully."
            incident.add_note(message)
            logger.info(f"Incident {incident.id}: {message}")
            return new_issue.key
        except JIRAError as e:
            # JIRAError can provide detailed error messages from the Jira API
            error_message_detail = f"Jira API Error creating ticket: Status {e.status_code} - {e.text}."
            # Log the full response if available and helpful
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_json = e.response.json()
                    logger.error(f"Jira error response JSON for incident {incident.id}: {error_json}")
                    # Extract specific errors if possible
                    errors = error_json.get('errors', {})
                    error_messages_list = error_json.get('errorMessages', [])
                    if errors: error_message_detail += f" Field errors: {errors}."
                    if error_messages_list: error_message_detail += f" Server messages: {', '.join(error_messages_list)}."
                except ValueError: # If response is not JSON
                    logger.error(f"Jira response content for incident {incident.id} was not JSON: {e.response.content}")
            
            incident.add_note(error_message_detail)
            logger.error(f"Incident {incident.id}: {error_message_detail}", exc_info=True) # Log with stack trace
        except Exception as e:
            # Catch any other unexpected errors during Jira ticket creation
            error_message = f"Unexpected error creating Jira ticket: {e}"
            incident.add_note(error_message)
            logger.error(f"Incident {incident.id}: {error_message}", exc_info=True)
        
        return None # Return None if ticket creation failed