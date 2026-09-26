"""Send final pipeline output to the n8n task workflow on demand."""
import os
from pathlib import Path

import requests
from dotenv import dotenv_values


N8N_WEBHOOK_URL = (
    os.environ.get("N8N_WEBHOOK_URL")
    or dotenv_values(Path(__file__).resolve().parents[1] / ".env").get("N8N_WEBHOOK_URL")
    or "http://localhost:5678/webhook/task-input"
)


def send_to_n8n(final_json):
    """POST the unchanged final JSON once; propagate request errors to the UI."""
    response = requests.post(N8N_WEBHOOK_URL, json=final_json, timeout=30,
                             allow_redirects=False)
    response.raise_for_status()
    return response
