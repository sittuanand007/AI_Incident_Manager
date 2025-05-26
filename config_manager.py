# config_manager.py

import configparser
import os
from dotenv import load_dotenv
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    Manages loading and accessing configuration from .env (for secrets)
    and config.ini (for general settings and rules).
    """
    def __init__(self, ini_file_path: str = 'config.ini', env_file_path: Optional[str] = None):
        # Determine .env file path (useful for tests or different environments)
        # If env_file_path is not provided, it defaults to '.env' in the current directory
        dotenv_path = env_file_path if env_file_path else os.path.join(os.path.dirname(__file__), '.env')
        if not os.path.exists(dotenv_path):
            logger.warning(f".env file not found at {dotenv_path}. Secrets might not be loaded if not set in environment.")
        load_dotenv(dotenv_path=dotenv_path) # Load environment variables

        self.config = configparser.ConfigParser(interpolation=None) # Disable interpolation
        if not os.path.exists(ini_file_path):
            logger.error(f"Configuration file {ini_file_path} not found.")
            raise FileNotFoundError(f"Configuration file {ini_file_path} not found.")
        self.config.read(ini_file_path)
        logger.info(f"Successfully loaded configuration from {ini_file_path}")

        # --- General Settings ---
        self.agent_name: str = self.config.get('General', 'AgentName', fallback='IncidentAgent')
        self.check_interval_seconds: int = self.config.getint('General', 'CheckIntervalSeconds', fallback=60)

        # --- Email Credentials (from .env) ---
        self.imap_server: Optional[str] = os.getenv('IMAP_SERVER')
        self.imap_username: Optional[str] = os.getenv('IMAP_USERNAME')
        self.imap_password: Optional[str] = os.getenv('IMAP_PASSWORD')
        self.smtp_server: Optional[str] = os.getenv('SMTP_SERVER')
        self.smtp_port: int = int(os.getenv('SMTP_PORT', 587))
        self.smtp_username: Optional[str] = os.getenv('SMTP_USERNAME')
        self.smtp_password: Optional[str] = os.getenv('SMTP_PASSWORD')
        self.sender_email: Optional[str] = os.getenv('SENDER_EMAIL')

        # --- Jira Credentials (from .env and config.ini) ---
        self.jira_url: Optional[str] = os.getenv('JIRA_URL')
        self.jira_username: Optional[str] = os.getenv('JIRA_USERNAME')
        self.jira_api_token: Optional[str] = os.getenv('JIRA_API_TOKEN')
        self.jira_project_key: str = self.config.get('Jira', 'ProjectKey', fallback='ITSM')
        self.jira_p1_issue_type: str = self.config.get('Jira', 'P1IssueType', fallback='Incident')

        # --- Team Mapping Rules (from config.ini) ---
        # self.team_keywords stores: {'NetworkTeam': ['network', 'firewall', ...], ...}
        # Keys are the team names as defined in [Teams] section (e.g., NetworkTeam)
        # Values are lists of lowercased keywords.
        self.team_keywords: Dict[str, List[str]] = self._load_keywords_from_section('Teams')
        
        # self.team_emails stores: {'networkteam': 'network-team@example.com', ...}
        # Keys are lowercased versions of team names from [Teams] section.
        self.team_emails: Dict[str, str] = {
            k.lower(): v for k, v in self.config.items('TeamEmails') if k.lower() != 'defaultteamname'
        }

        # Default team configuration
        self.default_team_name: str = self.config.get('TeamEmails', 'DefaultTeamName', fallback='DefaultTeam')
        # The key for the default team's email in [TeamEmails] section is its name in lowercase.
        self.default_team_email: str = self.team_emails.get(
            self.default_team_name.lower(), # Lookup using lowercase name
            'support@example.com' # Fallback if default team email not found
        )
        if not self.team_emails.get(self.default_team_name.lower()):
            logger.warning(f"Default team email for '{self.default_team_name}' (key: '{self.default_team_name.lower()}') not found in [TeamEmails]. Using fallback 'support@example.com'.")


        # --- Priority Classification Rules (from config.ini) ---
        # self.priority_keywords stores: {'P1': ['critical', ...], 'P2': ['high', ...], ...}
        # Values are lists of lowercased keywords.
        self.priority_keywords: Dict[str, List[str]] = {
            p_level: self._parse_keywords_string(self.config.get('PriorityKeywords', p_level, fallback=''))
            for p_level in ["P1", "P2", "P3", "P4"] # Ensure specific order for processing later
        }
        
        self._validate_essential_configs()

    def _parse_keywords_string(self, keyword_string: str) -> List[str]:
        """Helper to parse a comma-separated string of keywords into a list of lowercased strings."""
        return [kw.strip().lower() for kw in keyword_string.split(',') if kw.strip()]

    def _load_keywords_from_section(self, section_name: str) -> Dict[str, List[str]]:
        """
        Helper to load sections where keys are item names (e.g., Team Names)
        and values are comma-separated lists of keywords.
        Keywords are lowercased. Keys (team names) are preserved as in config.ini.
        Example: {'NetworkTeam': ['network', 'firewall'], ...}
        """
        data_dict = {}
        if self.config.has_section(section_name):
            for item_key, keywords_str in self.config.items(section_name):
                data_dict[item_key] = self._parse_keywords_string(keywords_str)
        else:
            logger.warning(f"Configuration section [{section_name}] not found in {self.config.read_file}.")
        return data_dict
        
    def _validate_essential_configs(self):
        """Validates that essential configurations are present."""
        essential_env_vars = {
            "IMAP Server": self.imap_server, "IMAP Username": self.imap_username, "IMAP Password": self.imap_password,
            "SMTP Server": self.smtp_server, "SMTP Port": self.smtp_port, "SMTP Username": self.smtp_username,
            "SMTP Password": self.smtp_password, "Sender Email": self.sender_email,
            "Jira URL": self.jira_url, "Jira Username": self.jira_username, "Jira API Token": self.jira_api_token,
        }
        for name, var in essential_env_vars.items():
            if not var:
                logger.warning(f"Essential environment variable for '{name}' is not set. Functionality relying on it may fail.")

        if not self.jira_project_key:
            logger.warning("Jira ProjectKey is not set in config.ini. Jira integration may fail.")
        if not self.team_keywords:
            logger.warning("No team keywords defined in [Teams] section of config.ini. Team assignment might always go to default.")
        if not self.priority_keywords.get("P1") and not self.priority_keywords.get("P2"): # Example check
            logger.warning("No P1 or P2 priority keywords defined in [PriorityKeywords] section. Priority classification might be ineffective.")