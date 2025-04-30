import os
import json
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

# Load and validate environment variables
def setup_env():
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError("GOOGLE_API_KEY not set in .env file")
    return api_key

# Initialize chat models
def init_models():
    planner_model = init_chat_model(
        "gemini-2.5-pro-exp-03-25", model_provider="google_genai"
    )
    code_model = init_chat_model(
        "gemini-2.5-pro-exp-03-25", model_provider="google_genai"
    )
    return planner_model, code_model

# Tool: generate project plan
@tool
def planner_tool(idea: str) -> str:
    """
    Generate a concise, MVP-focused project plan for a given idea.
    """
    return f"""
You are a software planner. Based on this idea: \"{idea}\", create an MVP-focused plan:

1. **Summary**: A one-sentence description of the application
2. **Core MVP Features** (5 max)
3. **Key Technologies** (frontend, backend, database)
4. **Main Components/Pages** (5 max)
5. **Essential Data Models** (3 max)
"""

# Main processing function
def process_app_idea(idea: str):
    # Setup environment and models
    setup_env()
    planner_model, code_model = init_models()

    # Planner agent
    planner_agent = create_react_agent(planner_model, [planner_tool])
    planner_resp = planner_agent.invoke({"messages": [HumanMessage(content=idea)]})
    plan = planner_resp["messages"][-1].content

    print(f"Plan: \n\n{plan}\n\n")

    # Code generation agent (direct instruction)
    code_agent = create_react_agent(code_model, [])
    code_instruction = (
        "You are a project code generator. Please output a JSON object with a 'files' array. "
        "Each item must have 'path' and 'content'.\n"
        f"Plan:\n{plan}\n"
        "Generate all necessary application files accordingly."
    )
    code_resp = code_agent.invoke({"messages": [HumanMessage(content=code_instruction)]})
    code_json = code_resp["messages"][-1].content

    print(f"Code json: \n\n{code_json}\n\n")

    # Content validation agent
    validation_agent = create_react_agent(code_model, [])

    messages = [
        HumanMessage(content="""
You are a senior software engineer.

Here is a codebase in the format:
{
  "files": [
    { "path": "filename", "content": "file content" }
  ]
}

Tasks:
- Validate all files for syntax errors, missing imports, and internal dependency issues.
- Fix any bugs or mistakes found.
- Do not invent extra files or restructure — stick to the given format.
- Return the fixed result as valid JSON in the same structure.
"""),
        HumanMessage(content=code_json)
    ]

    validation_resp = validation_agent.invoke({"messages": messages})
    raw_output = validation_resp["messages"][-1].content

    print(f"Raw output: \n\n{raw_output}\n\n")

    # Clean up if it’s wrapped in a code block
    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        cleaned = raw_output.strip().strip("```json").strip("```").strip()
        return json.loads(cleaned)


if __name__ == "__main__":
    idea = "I want to build a webapp chatbot using OpenAI API"
    result = process_app_idea(idea)
    print(json.dumps(result, indent=2))
