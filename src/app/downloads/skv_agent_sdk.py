"""
SKV Agent SDK v4.0
One-line integration for AI agents.
Copy this file, set your email, and you're connected.
"""

import requests
import json
from typing import Optional, Dict, List

class SKVAgent:
    """AI Agent connected to SKV Network with memory, cubes, and constitution."""
    
    def __init__(self, user_id: str, token: str = None, project: str = "default", base_url: str = "https://skv.network"):
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.user_id = user_id
        self.project = project
        self.base_url = base_url
        self.constitution = None
        self.memory = None
        
    def connect(self) -> Dict:
        """Connect to SKV and load constitution + memory."""
        # 1. Discovery
        r = requests.get(f"{self.base_url}/.well-known/skv", headers=self.headers, timeout=10)
        self.constitution = r.json()
        
        # 2. Load memory
        r = requests.get(f"{self.base_url}/api/v4/users/{self.user_id}/projects/{self.project}/context", timeout=10)
        self.memory = r.json()
        
        return {
            "constitution_cubes": self.constitution["constitution"]["priority_1_cubes"],
            "memory_sessions": self.memory.get("sessions_count", 0),
            "status": "connected"
        }
    
    def search(self, query: str) -> Dict:
        """Search SKV knowledge base via neural graph."""
        r = requests.post(f"{self.base_url}/api/consult", 
            json={"query": query, "user_id": self.user_id, "project": self.project},
            timeout=30)
        return r.json()
    
    def remember(self, query: str, response: str) -> Dict:
        """Save to persistent memory."""
        r = requests.post(f"{self.base_url}/api/v4/sessions",
            json={"user_id": self.user_id, "project": self.project, "query": query, "response": response},
            timeout=10)
        return r.json()
    
    def create_cube(self, title: str, rules: List[str], trigger_intent: List[str], rationale: str = "") -> Dict:
        """Create an experience cube."""
        r = requests.post(f"{self.base_url}/api/v1/entries",
            json={"title": title, "type": "experience", "rules": rules, 
                  "trigger_intent": trigger_intent, "rationale": rationale},
            timeout=10)
        return r.json()
    
    def health(self) -> Dict:
        """Check SKV system health."""
        r = requests.get(f"{self.base_url}/api/v4/graph/health", timeout=10)
        return r.json()


# ===== USAGE EXAMPLE =====
if __name__ == "__main__":
    # One line to connect
    agent = SKVAgent(user_id="your@email.com", project="my-project")
    
    # Load constitution + memory
    status = agent.connect()
    print(f"Connected: {status}")
    
    # Search knowledge
    result = agent.search("How to deploy Docker?")
    print(f"Answer: {result['answer'][:200]}")
    
    # Save to memory
    agent.remember("Docker deploy", "Use docker-compose up -d")
    
    # Create experience cube
    agent.create_cube(
        title="Docker Deployment Pattern",
        rules=["MUST use docker-compose", "MUST test locally first"],
        trigger_intent=["docker", "deploy", "compose"],
        rationale="Standardized deployment process"
    )
    
    print("Done! Check https://skv.network for your cubes and memory.")
