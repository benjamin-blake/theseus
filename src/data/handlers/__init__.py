"""Lambda handlers for the platform agent automation.

1. scheduled_agent_handler - dispatches the scheduled agent fleet
   (.github/agents/schedule.yaml) and writes agent logs to S3
2. findings_processor_handler - turns agent findings into recommendations
   via the ops portal
"""
