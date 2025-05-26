# incident_classifier.py

from typing import Tuple, Optional
import logging

from models import Incident # Assuming Incident model is in models.py
from config_manager import ConfigManager # Assuming ConfigManager is in config_manager.py

logger = logging.getLogger(__name__)

class IncidentClassifier:
    """
    Classifies incidents based on priority and assigns them to the appropriate team
    using rule-based logic derived from the configuration.
    """
    def __init__(self, config: ConfigManager):
        self.config = config
        logger.debug("IncidentClassifier initialized.")
        logger.debug(f"Priority keywords loaded: {list(self.config.priority_keywords.keys())}")
        logger.debug(f"Team keywords loaded: {list(self.config.team_keywords.keys())}")
        logger.debug(f"Team emails loaded: {list(self.config.team_emails.keys())}")
        logger.debug(f"Default team configured: Name='{self.config.default_team_name}', Email='{self.config.default_team_email}'")

    def classify_incident_priority(self, incident: Incident) -> str:
        """
        Determines the priority of an incident based on keywords found in its subject or body.
        Keywords and priorities are defined in `config.ini`.
        The method checks for P1 keywords first, then P2, P3, and P4.
        Defaults to "P3" (or a configured default) if no specific keywords are matched.

        Args:
            incident: The Incident object to classify.

        Returns:
            A string representing the classified priority (e.g., "P1", "P2", "P3", "P4").
        """
        # Concatenate subject and body for a comprehensive text scan, convert to lowercase once.
        text_to_scan = (incident.subject + " " + incident.body).lower()
        
        # Iterate through priorities in a specific order (P1 is most critical)
        for p_level in ["P1", "P2", "P3", "P4"]:
            keywords_for_level = self.config.priority_keywords.get(p_level, [])
            for keyword in keywords_for_level: # These keywords are already lowercased by ConfigManager
                if keyword in text_to_scan:
                    note = f"Priority classified as {p_level} due to keyword: '{keyword}'."
                    incident.add_note(note)
                    logger.info(f"Incident {incident.id}: {note}")
                    return p_level
        
        # If no keywords matched, assign a default priority
        default_priority = "P3" # Hardcoded default, could be made configurable
        note = f"No specific priority keywords found. Defaulting priority to {default_priority}."
        incident.add_note(note)
        logger.info(f"Incident {incident.id}: {note}")
        return default_priority

    def assign_incident_to_team(self, incident: Incident) -> Tuple[str, str]:
        """
        Assigns an incident to a team based on keywords found in its subject or body.
        Team names, keywords, and email addresses are defined in `config.ini`.
        Falls back to a configured default team if no specific team keywords are matched.

        Args:
            incident: The Incident object to assign.

        Returns:
            A tuple containing:
                - team_name_display (str): The display name of the assigned team (e.g., "NetworkTeam").
                - team_email (str): The email address of the assigned team.
        """
        text_to_scan = (incident.subject + " " + incident.body).lower()
        
        # Iterate through configured teams and their keywords from [Teams] section.
        # self.config.team_keywords is like: {'NetworkTeam': ['network', ...], 'DatabaseTeam': ['db', ...]}
        # team_name_key is the key from the [Teams] section (e.g., "NetworkTeam")
        for team_name_key, keywords_for_team in self.config.team_keywords.items():
            for keyword in keywords_for_team: # These keywords are already lowercased
                if keyword in text_to_scan:
                    # Team found. Now get its email.
                    # Email lookup uses the lowercase version of team_name_key.
                    team_email = self.config.team_emails.get(team_name_key.lower())
                    
                    if not team_email:
                        note = (f"Keyword '{keyword}' matched team '{team_name_key}', "
                                f"but no email found for '{team_name_key.lower()}' in [TeamEmails] section. "
                                "Assigning to default team instead.")
                        incident.add_note(note)
                        logger.warning(f"Incident {incident.id}: {note}")
                        # Break from inner loop and let it fall to default team logic
                        break 
                    else:
                        note = f"Assigned to team '{team_name_key}' based on keyword: '{keyword}'. Email: {team_email}"
                        incident.add_note(note)
                        logger.info(f"Incident {incident.id}: {note}")
                        return team_name_key, team_email # Return the display name and email
            
            if incident.assigned_team: # If assigned in the inner loop due to missing email, fall to default
                break


        # If no specific team keywords matched or if a matched team had no email, assign to default team.
        note = (f"No specific team keywords matched or issue with matched team's email. "
                f"Assigning to default team: Name='{self.config.default_team_name}', Email='{self.config.default_team_email}'.")
        incident.add_note(note)
        logger.info(f"Incident {incident.id}: {note}")
        return self.config.default_team_name, self.config.default_team_email