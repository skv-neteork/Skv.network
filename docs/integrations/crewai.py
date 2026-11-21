"""SKV + CrewAI.

Replace YOUR_SKV_KEY with the key from https://skv.network/profile,
or export SKV_API_KEY. Do not commit the key.

Docs: https://docs.crewai.com/en/mcp/overview
Install: uv add mcp
"""

import os

from crewai import Agent, Crew, Task
from crewai.mcp import MCPServerHTTP


token = os.environ.get("SKV_API_KEY", "YOUR_SKV_KEY")

skv = MCPServerHTTP(
    url="https://skv.network/mcp",
    headers={"Authorization": f"Bearer {token}"},
    streamable=True,
    cache_tools_list=True,
)

researcher = Agent(
    role="Researcher with long-term memory",
    goal="Answer with facts recalled from SKV when they exist",
    backstory="Uses SKV so decisions survive a new chat",
    mcps=[skv],
)

task = Task(
    description=(
        "If the user has already said yes to the SKV constitution, follow "
        "identify → step_zero → turn. Recall any saved project deadline."
    ),
    expected_output="An answer that cites SKV memory event ids when memory is used",
    agent=researcher,
)

crew = Crew(agents=[researcher], tasks=[task])

if __name__ == "__main__":
    print(crew.kickoff())

# A bare HTTPS string also works (mcps=["https://skv.network/mcp/k/YOUR_SKV_KEY/"])
# but a header is preferable so the key is not copied into logs of the URL.
