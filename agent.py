import os
import json
import subprocess
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
        "gemini-1.5-pro-latest", model_provider="google_genai"
    )
    code_model = init_chat_model(
        "gemini-1.5-pro-latest", model_provider="google_genai"
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

1. **Summary**
2. **Core MVP Features**
3. **Key Technologies**
4. **Main Components/Pages**
5. **Essential Data Models**
"""

def save_files_to_dir(code_data, base_dir):
    for file in code_data.get("files", []):
        path = os.path.join(base_dir, file["path"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(file["content"])

def init_git_repo(base_dir):
    if not os.path.exists(os.path.join(base_dir, ".git")):
        subprocess.run(["git", "init"], cwd=base_dir, check=True)
        subprocess.run(["git", "config", "user.email", "you@example.com"], cwd=base_dir, check=True)
        subprocess.run(["git", "config", "user.name", "Your Name"], cwd=base_dir, check=True)

def commit_changes(base_dir, message="Update code"):
    subprocess.run(["git", "add", "."], cwd=base_dir, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=base_dir, check=True)

def generate_code_from_plan(plan, code_model):
    code_agent = create_react_agent(code_model, [])
    code_instruction = (
        "You are a project code generator. Please output a JSON object with a 'files' array. "
        "Each item must have 'path' and 'content'.\n"
        f"Plan:\n{plan}\n"
        "Generate all necessary application files accordingly."
    )
    response = code_agent.invoke({"messages": [HumanMessage(content=code_instruction)]})
    return response["messages"][-1].content

def validate_code(code_json, model):
    validation_agent = create_react_agent(model, [])
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
    response = validation_agent.invoke({"messages": messages})
    raw_output = response["messages"][-1].content
    try:
        print(f"Raw Output: {raw_output}")
        outs = json.loads(raw_output)
        return outs
    except json.JSONDecodeError:
        cleaned = raw_output.strip().strip("```json").strip("```").strip()
        print(f"Cleaned Output: {cleaned}")
        outs = json.loads(cleaned)
        return outs

def process_app_idea(idea: str):
    setup_env()
    planner_model, code_model = init_models()

    planner_agent = create_react_agent(planner_model, [planner_tool])
    planner_resp = planner_agent.invoke({"messages": [HumanMessage(content=idea)]})
    plan = planner_resp["messages"][-1].content
    print(f"\nProject Plan:\n{plan}\n")

    base_dir = os.path.join(os.getcwd(), "tempo")
    os.makedirs(base_dir, exist_ok=True)
    print(f"Using temp directory: {base_dir}")
    init_git_repo(base_dir)

    # First generation
    raw_code = generate_code_from_plan(plan, code_model)
    validated_code = validate_code(raw_code, code_model)
    save_files_to_dir(validated_code, base_dir)
    commit_changes(base_dir, message="Initial project setup")

    code_context = raw_code

    while True:
        user_input = input("\n🔧 Enter additional request for your project (or type 'exit'): ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("Exiting loop.")
            break

        # Invoke code agent with user update
        code_agent = create_react_agent(code_model, [])
        instruction = (
            "You are enhancing a project. The files for the project are as follows: "
            f"{code_context}\n\n" 
            "The user has the following request:\n"
            f"{user_input}\n\n"
            "Please return updated files only. Keep same format."
            "If any file needs to be deleted send in same format but keep content as 'TERMINATE'"
        )
        response = code_agent.invoke({"messages": [HumanMessage(content=instruction)]})
        new_code_json = response["messages"][-1].content
        code_context+= f"\n\nIteration for prompt: {user_input}\nCode given: {new_code_json}"
        validated_update = validate_code(new_code_json, code_model)

        save_files_to_dir(validated_update, base_dir)
        commit_changes(base_dir, message=f"Applied user request: {user_input}")

if __name__ == "__main__":
    idea = "I want to build a webapp for an e commerece site"
    process_app_idea(idea)