# models.py

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict

class Incident(BaseModel):
    """
    Represents an incident being processed by the agent.
    Uses Pydantic for data validation and clear structure.
    """
    id: str = Field(..., description="Unique ID for the incident, e.g., email Message-ID or an internal ID")
    source: str = Field(..., description="Source of the incident, e.g., 'email', 'monitoring_tool_api'")
    subject: str = Field(..., description="Subject line of the incident")
    body: str = Field(..., description="Main content/body of the incident report")
    raw_content: str = Field(..., description="Full raw content, e.g., full email bytes as string, for auditing or re-parsing")

    # Fields to be populated by the agent during processing
    priority: Optional[str] = Field(None, description="Assigned priority, e.g., 'P1', 'P2', 'P3', 'P4'")
    assigned_team: Optional[str] = Field(None, description="Name of the team assigned to this incident")
    assigned_team_email: Optional[EmailStr] = Field(None, description="Email address of the assigned team")
    is_acknowledged: bool = Field(False, description="Flag indicating if an acknowledgement has been sent")
    jira_ticket_key: Optional[str] = Field(None, description="Jira ticket key if a ticket was created (e.g., 'ITSM-123')")
    processing_notes: List[str] = Field(default_factory=list, description="Log of actions and decisions made by the agent for this incident")

    def add_note(self, note: str):
        """Helper method to add a processing note to the incident."""
        self.processing_notes.append(note)

    class Config:
        # Allows Pydantic to work well with ORMs or other data sources if needed later
        orm_mode = True