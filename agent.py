# Main orchestration logic

# agent.py

import time
import schedule # For scheduling periodic tasks
import logging # For comprehensive logging
import sys # For sys.exit

# Import custom modules
from config_manager import ConfigManager
from email_handler import EmailHandler
from incident_parser import IncidentParser
from incident_classifier import IncidentClassifier
from jira_handler import JiraHandler
from models import Incident # Pydantic model for Incident

# --- Global Logging Configuration ---
# This configures the root logger. All module loggers will inherit this.
# Adjust level for more/less verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL)
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(name)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler("incident_agent.log", mode='a'), # Append to log file
        logging.StreamHandler(sys.stdout) # Log to console
    ]
)
# Get a logger for this specific module (agent.py)
logger = logging.getLogger(__name__)


class IncidentManagementAgent:
    """
    The main AI agent class that orchestrates the incident management process.
    It fetches incidents, classifies them, assigns them, acknowledges, and creates Jira tickets.
    """
    def __init__(self):
        logger.info("--- Initializing Incident Management Agent ---")
        try:
            # Initialize core components
            self.config = ConfigManager() # Load configurations first
            logger.info(f"Agent Name: {self.config.agent_name}")
            logger.info(f"Configuration loaded. Check interval: {self.config.check_interval_seconds}s.")
            
            # Log key configurations (be careful with logging sensitive info, even if usernames are "public")
            logger.info(f"IMAP: Server='{self.config.imap_server}', User='{self.config.imap_username is not None}'")
            logger.info(f"SMTP: Server='{self.config.smtp_server}', User='{self.config.smtp_username is not None}', Sender='{self.config.sender_email}'")
            logger.info(f"Jira: URL='{self.config.jira_url}', User='{self.config.jira_username is not None}', Project='{self.config.jira_project_key}'")

            self.parser = IncidentParser()
            self.email_handler = EmailHandler(self.config, self.parser)
            self.classifier = IncidentClassifier(self.config)
            self.jira_handler = JiraHandler(self.config) # Jira connection is attempted during its __init__
            
            logger.info("--- All agent components initialized successfully ---")
        except FileNotFoundError as e:
            logger.critical(f"CRITICAL ERROR: Configuration file (e.g., config.ini) not found. {e}. Agent cannot start.")
            # For critical startup errors, re-raising helps stop the script immediately.
            raise
        except Exception as e:
            logger.critical(f"CRITICAL ERROR during agent initialization: {e}", exc_info=True)
            raise

    def _process_single_incident(self, incident: Incident):
        """
        Private method to handle the lifecycle of a single incident.
        Includes classification, assignment, acknowledgement, and P1 Jira ticket creation.
        """
        logger.info(f"--- Starting processing for Incident ID: {incident.id}, Subject: '{incident.subject}' ---")
        incident.add_note(f"Agent '{self.config.agent_name}' received and started processing.")

        # 1. Classify Priority
        incident.priority = self.classifier.classify_incident_priority(incident)
        # Detailed logging for classification happens within the classifier method.

        # 2. Assign Team
        team_name_display, team_email_address = self.classifier.assign_incident_to_team(incident)
        incident.assigned_team = team_name_display
        incident.assigned_team_email = team_email_address
        # Detailed logging for assignment happens within the classifier method.

        # 3. "Auto-Attend" - Send Acknowledgement Email
        # The acknowledgement is typically sent to the assigned team, or could be to original reporter if parsed.
        # For this setup, we'll acknowledge the assigned team.
        if incident.assigned_team_email:
            self.email_handler.send_acknowledgement_email(incident, recipient_email=incident.assigned_team_email)
        else:
            logger.warning(f"Incident {incident.id}: No team email available for acknowledgement (Assigned Team: {incident.assigned_team}).")
            incident.add_note("Acknowledgement email skipped: No assigned team email was determined.")
        # Logging for email sending (success/failure) happens within the email_handler method.

        # 4. Create Jira Ticket for P1 issues
        if incident.priority == "P1":
            logger.info(f"Incident {incident.id} is P1. Attempting to create Jira ticket.")
            if self.jira_handler.jira_client: # Check if Jira client is available (connection successful)
                ticket_key = self.jira_handler.create_jira_ticket_for_incident(incident)
                if ticket_key:
                    # The jira_handler updates incident.jira_ticket_key and logs success.
                    # If acknowledgement email was already sent, it won't have the Jira key.
                    # Consider sending a second notification or updating the ack email logic if Jira key is critical for initial ack.
                    logger.info(f"Incident {incident.id}: P1 Jira ticket {ticket_key} successfully created.")
                else:
                    logger.error(f"Incident {incident.id}: Failed to create Jira ticket for P1 (see JiraHandler logs for details).")
            else:
                message = "Jira client is not available (e.g., connection failed or not configured). Cannot create P1 ticket."
                logger.error(f"Incident {incident.id}: {message}")
                incident.add_note(f"Jira ticket creation skipped: {message}")
        # No verbose logging for non-P1s not getting a ticket, as that's expected.

        logger.info(
            f"--- Finished processing Incident ID: {incident.id}. "
            f"Final State: Priority='{incident.priority}', Team='{incident.assigned_team}', "
            f"JiraKey='{incident.jira_ticket_key}', AckSent='{incident.is_acknowledged}' ---"
        )
        logger.debug(f"Incident {incident.id} final processing notes: {incident.processing_notes}")

    def run_incident_check_cycle(self):
        """
        Executes one full cycle of checking for new incidents and processing them.
        This method is designed to be called periodically by the scheduler.
        """
        logger.info(f"[{self.config.agent_name}] === Starting new incident check cycle ===")
        try:
            # Step 1: Fetch new raw incidents (currently from email)
            # The email_handler will parse them into Incident objects if they are valid.
            newly_fetched_incidents: List[Incident] = self.email_handler.fetch_new_incidents_from_email()
            
            if not newly_fetched_incidents:
                # This is a normal occurrence, so INFO level is appropriate.
                logger.info(f"[{self.config.agent_name}] No new incidents found in this check cycle.")
            else:
                logger.info(f"[{self.config.agent_name}] Fetched {len(newly_fetched_incidents)} new potential incident(s) to process.")
                for incident_obj in newly_fetched_incidents:
                    try:
                        self._process_single_incident(incident_obj)
                    except Exception as e:
                        # Log error specific to processing this single incident but allow the agent to continue with others.
                        logger.error(
                            f"[{self.config.agent_name}] Unhandled error while processing incident ID {incident_obj.id}: {e}", 
                            exc_info=True # Include stack trace for this error
                        )
                        # Optionally, add a failure note to the incident object itself if it's recoverable or for audit.
                        incident_obj.add_note(f"CRITICAL AGENT ERROR during processing: {e}")
            
            logger.info(f"[{self.config.agent_name}] === Finished incident check cycle ===")

        except Exception as e:
            # This catches broader errors, e.g., if email_handler.fetch_new_incidents itself fails catastrophically.
            logger.error(
                f"[{self.config.agent_name}] Critical error occurred during the main check cycle operation: {e}", 
                exc_info=True
            )

    def start_agent(self):
        """
        Starts the agent's main operational loop.
        It performs an initial check cycle and then schedules periodic checks.
        """
        logger.info(f"--- Incident Management Agent '{self.config.agent_name}' is starting up... ---")
        logger.info(f"Will check for new incidents every {self.config.check_interval_seconds} seconds.")

        # Perform an initial check cycle immediately upon startup.
        logger.info(f"[{self.config.agent_name}] Performing initial incident check cycle on startup...")
        self.run_incident_check_cycle() 
        
        # Schedule the periodic execution of the check cycle.
        schedule.every(self.config.check_interval_seconds).seconds.do(self.run_incident_check_cycle)

        logger.info(f"[{self.config.agent_name}] Scheduler started. Agent is now running. Press Ctrl+C to stop.")
        try:
            while True:
                schedule.run_pending() # Execute any pending scheduled jobs
                time.sleep(1) # Sleep for a short duration to avoid busy-waiting and be responsive to Ctrl+C
        except KeyboardInterrupt:
            logger.info(f"[{self.config.agent_name}] Shutdown signal (KeyboardInterrupt) received. Stopping agent...")
        except Exception as e:
            # Catch any unexpected critical exceptions in the main scheduling loop.
            logger.critical(
                f"[{self.config.agent_name}] Agent encountered a critical unhandled exception in the main scheduling loop: {e}", 
                exc_info=True
            )
        finally:
            logger.info(f"--- {self.config.agent_name} Incident Management Agent is shutting down. ---")

# --- Main Execution Block ---
if __name__ == "__main__":
    # This block executes if the script is run directly (e.g., `python agent.py`).
    agent_instance = None
    try:
        agent_instance = IncidentManagementAgent() # Instantiate the agent
        agent_instance.start_agent() # Start its operation
    except FileNotFoundError:
        # This specific error from ConfigManager (config.ini not found) is critical for startup.
        # Logging might not be fully set up if ConfigManager fails early, so print as well.
        print(f"FATAL: Agent cannot start. Configuration file ('config.ini') likely missing. Check logs for details.")
        # Logger should have already caught this in ConfigManager or Agent __init__.
    except Exception as e:
        # Catch any other critical exceptions during agent instantiation or before start_agent() begins its loop.
        print(f"FATAL: Agent failed to initialize or start due to an unhandled critical error: {e}")
        # If logger is available (i.e., basicConfig worked), use it.
        logger.critical(f"Agent failed to initialize or start: {e}", exc_info=True)
    
    # The `finally` block within `start_agent()` handles normal shutdown logging.
    # If startup fails catastrophically, the script will exit.