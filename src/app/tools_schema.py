"""OpenAI-compatible function calling schema for SKV agents."""
SKV_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "skv_search_cubes",
            "description": "Search for relevant SKV cubes by query. Returns matching cubes with rules and trigger intents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query in natural language"},
                    "limit": {"type": "integer", "default": 5, "description": "Max results to return"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "skv_get_cube",
            "description": "Retrieve full cube by its ID. Returns complete rules, rationale, examples.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cube_id": {"type": "string", "description": "Cube ID from search results"}
                },
                "required": ["cube_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "skv_create_file",
            "description": "Create a file on SKV server. Returns download URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "File name without extension"},
                    "content": {"type": "string", "description": "File content (HTML, JSON, CSV, etc.)"},
                    "type": {"type": "string", "enum": ["html", "txt", "json", "csv", "md", "svg"]}
                },
                "required": ["filename", "content", "type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "skv_export_cube",
            "description": "Export cube in specified format.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cube_id": {"type": "string"},
                    "format": {"type": "string", "enum": ["json", "md", "pdf", "pptx"]}
                },
                "required": ["cube_id", "format"]
            }
        }
    }
]
