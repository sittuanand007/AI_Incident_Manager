# AI_Incident_Manager
# AI Agent for Incident Management

This project contains an AI-powered agent designed to automate key aspects of IT incident management. It monitors an email inbox, classifies incidents by priority, assigns them to appropriate teams, 
sends acknowledgements, and creates Jira tickets for critical (P1) issues.


## Features
- **Email Monitoring:** Fetches new emails from a specified IMAP account.
- **Incident Parsing:** Extracts relevant information (subject, body) from emails.
- **Priority Classification:** Rule-based classification (P1-P4) using keywords from `config.ini`.
- **Team Assignment:** Rule-based assignment to predefined teams using keywords from `config.ini`.
- **Auto-Acknowledgement:** Sends an email notification acknowledging incident receipt and initial assessment.
- **Jira Integration:** Automatically creates Jira tickets for P1 incidents in a configured project.
- **Configurable:** Uses `.env` for secrets and `config.ini` for rules and settings.
- **Scheduled Operation:** Runs periodically to check for new incidents.
- **Logging:** Comprehensive logging to console and `incident_agent.log`.

## Project Structure
incident_management_agent/
- **agent.py** # Main agent logic and scheduler
- **config_manager.py** # Loads and provides configuration
- **email_handler.py** # Handles email interactions
- **incident_parser.py** # Parses incoming incident data
- **incident_classifier.py**# Classifies priority and assigns teams
- **jira_handler.py** # Handles Jira ticket creation
- **models.py** # Pydantic models for data structures
- **.env.example** # Example for environment variables (secrets)
- **.gitignore** # Specifies intentionally untracked files
- **config.ini** # Non-secret configurations and rules
- **requirements.txt** # Python dependencies
- **incident_agent.log** # Log file (generated on run)


## Prerequisites
- Python 3.7+
- Pip (Python package installer)
- Access to an email account (IMAP for reading, SMTP for sending)
- Access to a Jira instance (with API token permissions for creating issues)

## Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/YOUR_USERNAME/YOUR_REPOSITORY_NAME.git
    cd YOUR_REPOSITORY_NAME
    ```

2.  **Create a Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    # On Windows:
    # venv\Scripts\activate
    # On macOS/Linux:
    # source venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables:**
    Copy the example environment file and fill in your credentials:
    ```bash
    cp .env.example .env
    ```
    Now, edit the newly created `.env` file with your actual IMAP, SMTP, and Jira credentials.
    **IMPORTANT:** The `.env` file contains sensitive credentials and is ignored by Git (due to `.gitignore`). **Never commit your actual `.env` file.**

5.  **Customize Configuration:**
    Edit `config.ini` to:
    - Set your `AgentName`.
    - Adjust `CheckIntervalSeconds`.
    - Configure Jira `ProjectKey` and `P1IssueType`.
    - Define `[Teams]` with their names and associated keywords.
    - Define `[TeamEmails]` with corresponding email addresses (ensure keys are lowercase versions of team names from `[Teams]`). Set `DefaultTeamName` and its email.
    - Customize `[PriorityKeywords]` for P1-P4 classification.

## Running the Agent
Ensure your virtual environment is activated. Then, from the root project directory, run:
```bash
python agent.py
```
The agent will start, perform an initial check for incidents, and then continue checking at the interval specified in config.ini. Logs will be printed to the console and saved to incident_agent.log.
Press Ctrl+C to stop the agent gracefully.
