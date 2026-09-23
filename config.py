"""Demo visibility switches. No backend integrations are enabled here."""
ENABLE_HUMAN_REVIEW = True
ENABLE_TASK_DASHBOARD = True
ENABLE_MONITORING = True

# Staging limits include failed extraction attempts; logout does not reset counters.
MAX_EXTRACTIONS_PER_SESSION = 20
MAX_ASK_REQUESTS_PER_SESSION = 30
MAX_GEMINI_CALLS_PER_SESSION = 120
