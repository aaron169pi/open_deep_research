import os
import json
from langgraph.prebuilt import create_react_agent
from tools import (
    save_files,
    init_git_repo,
    commit_changes,
    rollback_codebase,
    print_error,
    print_success,
    print_warning,
    print_info,
    batch_files,
    start_server,
    stop_server,
    server_logs,
    rollback_server,
    ask_user_input_tool,
)
from prompts import (
    planner_prompt,
    code_generation_prompt,
    code_validation_prompt,
    file_structure_prompt,
    file_changes_prompt,
)
from state_manager import StateManager
from response_models import FileStructureList, FileGenerationList, FileChangesList
import winsound  # remove in production
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()


def init_models():
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

    model = client.models
    planner_model = "gemini-2.5-flash-preview-04-17"
    coder_model = "gemini-2.5-pro-preview-05-06"

    return model, planner_model, coder_model


def thinking_config(response_schema, thinking_budget=1024):
    generation_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_schema,
        thinking_config=types.ThinkingConfig(
            include_thoughts=True, thinking_budget=thinking_budget
        ),
    )
    return generation_config

def unwrap_thinking(response):
    thought, res = "", ""
    for part in response.candidates[0].content.parts:
        if not part.text:
            continue
        if part.thought:
            thought += part.text + "\n\n"
        else:
            res += part.text
    return thought, json.loads(res)

def prompt_input(system_instruction, user_input):
    system = {
        "role": "user",
        "parts": [{
            "text": system_instruction
        }]
    }
    user = {
        "role": "user",
        "parts": [{
            "text": user_input
        }]
    }

    return [system, user]

plan_schema = {
    "type": "object",
    "properties": {"plan": {"type": "string"}},
    "required": ["plan"],
}

structure_schema = {
    "type": "object",
    "properties": {
        "file_structure": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": ["file_structure"]
}

def process_app_idea(idea: str):
    model, planner_model, coder_model = init_models()
    state_manager = StateManager()

    # Check if a plan already exists
    if not state_manager.get_plan():
        plan_response = model.generate_content(
            model=planner_model,
            contents=planner_prompt.format(idea=idea),
            config=thinking_config(plan_schema),
        )
        thought, response = unwrap_thinking(plan_response)
        print_success(f"\nThinking: \n{thought}")
        state_manager.update_plan(response['plan'])

    plan = state_manager.get_plan()
    print(f"\nProject Plan:\n{plan}\n")

    # Initialisation of directory
    base_dir = init_git_repo()
    print(f"Using temp directory: {base_dir}")

    # Check if structure already exists
    if not state_manager.get_structure():
        structre_response = model.generate_content(
            model=coder_model,
            contents=prompt_input(file_structure_prompt, f"Idea: {idea}\n\nPlan:\n{plan}"),
            config=thinking_config(structure_schema),
        )
        thought, response = unwrap_thinking(structre_response)
        print_success(f"\nThinking: \n{thought}")
        file_paths = response["file_structure"]
        state_manager.update_structure(file_paths)

    structure = state_manager.get_structure()
    gen_structure = state_manager.get_generated()
    file_paths = [item for item in structure if item not in gen_structure]
    print(f"\nProject Structure: \n{structure}\n")

    # Check if codebase already exists
    if file_paths:
        generated_code = state_manager.get_codebase()
        summary = state_manager.get_summary()

        batch_agent = create_react_agent(
            model=code_model,
            tools=[ask_user_input_tool],
            prompt=code_generation_prompt,
            response_format=FileGenerationList,
        )
        for progress, batch in batch_files(file_paths, batch_size=4):
            response = batch_agent.invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Idea: {idea}\n\nPlan: {plan}\n\n\nEntire file structure: {structure}\n\n\nFiles you need to generate: {batch}\n\nSummary of previously generated code: {summary}",
                        }
                    ]
                }
            )
            batch_code = []
            for file_response in response["structured_response"].items:
                file_dict = {
                    "file_path": file_response.file_path,
                    "content": file_response.content,
                    "summary": file_response.summary,
                }
                batch_code.append(file_dict)
            print(f"\n\nBatch({progress}) {batch}:\n\n{batch_code}")

            generated_code.extend(batch_code)

            save_files(generated_code, base_dir)
            state_manager.update_codebase(generated_code)

            gen_structure.extend(batch)
            state_manager.update_generated(gen_structure)

            summary.append(
                [
                    {key: value for key, value in item.items() if key != "content"}
                    for item in batch_code
                ]
            )
            state_manager.update_summary(summary)

        print(f"Generated Code: \n\n{generated_code}")
        commit_id, repo_name = commit_changes(base_dir, message="Initial project setup")
        state_manager.add_work_dir(repo_name)
        state_manager.add_user_request(
            {"user_input": "Initial project setup", "commit_id": commit_id}
        )

    code_data = state_manager.get_codebase()
    user_input = "start"

    while True:
        repo_name = state_manager.get_work_dir()

        if user_input.lower() not in {"logs"}:
            res = start_server(repo_name)
        else:
            res = ""

        if "Failed" in res or "Error" in res:
            print_error(res)
            user_input = (
                f"The server failed to start. Here is the error log from response.text:\n\n"
                f"{res}\n\n"
                f"Please analyze and fix the root cause in the code."
                "Make sure that a startup.sh file is created and the outgoing port is strictly 9000 if it is exposing 2 ports than serve the build file through the backend itself and then make the backend use 9000 port"
            )
        else:
            print_success(res)
            winsound.Beep(500, 500)  # remove in production
            user_input = input(
                "\n>>> Enter additional request for your project (or type 'exit'): "
            ).strip()

            if user_input.lower() in {"exit", "quit"}:
                stop_server(repo_name)
                print("Exiting loop.")
                break

            if user_input.lower() in {"restart"}:
                res = start_server(repo_name)
                print_success(res)
                user_input = ""
                continue

            if user_input.lower() in {"logs"}:
                res = server_logs(repo_name)
                if "success" in res:
                    print_info("There are no errors server-side")
                    print_warning(f"Trace: {res}")
                    continue
                else:
                    print_error(res)
                    user_input = input("\n>>> Would you like to fix this error(y/n)?")
                    if user_input in {"y", "yes"}:
                        user_input = (
                            "This code was run inside of a docker container, the container stopped due to some issue or something else happened"
                            f"This was the error log: {res}"
                            "Fix this error properly and any errors that might propogate due to this error too"
                        )
                    else:
                        user_input = ""
                        continue

            if user_input.lower() in {"rollback"}:
                user_reqs = state_manager.get_user_requests()

                print("\n")
                for i, req in enumerate(user_reqs):
                    print(f"[{i+1}] {req['commit_id']}   {req['user_input']}")

                selection = int(input(">> Input the number for rollback: "))
                id = user_reqs[selection - 1]["commit_id"]
                code_base = rollback_codebase(base_dir, id)
                rollback_server(repo_name, id)
                state_manager.update_codebase(code_base)
                code_data = state_manager.get_codebase()
                user_input = ""
                continue

            if not user_input:
                continue

        # Prepare context for the agent
        code_context = json.dumps(code_data)

        code_agent = create_react_agent(
            model=code_model,
            tools=[ask_user_input_tool],
            prompt=file_changes_prompt.format(code_context=code_context),
            response_format=FileChangesList,
        )
        response = code_agent.invoke(
            {"messages": [{"role": "user", "content": user_input}]}
        )
        code_changes_data = []
        for file_response in response["structured_response"].items:
            file_dict = {
                "file_path": file_response.file_path,
                "changes": file_response.changes,
            }
            code_changes_data.append(file_dict)
        print(f"Code Changes Suggested: \n\n{code_changes_data}\n\n")

        for progress, batch in batch_files(code_changes_data, batch_size=4):
            validation_agent = create_react_agent(
                model=code_model,
                tools=[],
                prompt=code_validation_prompt,
                response_format=FileGenerationList,
            )
            validated_code_response = validation_agent.invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Entire file changes: {str(code_changes_data)}\n\n\nFiles you need to generate: {batch}\n\nPreviously generated code: {code_context}",
                        }
                    ]
                }
            )
            updated_code_data = []
            for file_response in validated_code_response["structured_response"].items:
                file_dict = {
                    "file_path": file_response.file_path,
                    "content": file_response.content,
                    "summary": file_response.summary,
                }
                updated_code_data.append(file_dict)

            if updated_code_data:
                print(f"\nUpdated Validated Code({progress}): \n{updated_code_data}\n")

                # Update the codebase with new changes
                existing_files = {file["file_path"]: file for file in code_data}

                for file in updated_code_data:
                    if file["content"] == "TERMINATE" or file["content"] == "":
                        existing_files.pop(file["file_path"], None)
                    else:
                        existing_files[file["file_path"]] = {
                            "file_path": file["file_path"],
                            "content": file["content"],
                            "summary": file["content"] or "",
                        }

                code_data = list(existing_files.values())
                code_context = json.dumps(code_data)

                save_files(code_data, base_dir)

                state_manager.update_codebase(code_data)
            else:
                print_info(
                    "There was no update in this batch, please check generated input"
                )

        commit_id, repo_name = commit_changes(
            base_dir, message=f"Applied user request: {user_input[:200]}"
        )
        state_manager.add_user_request(
            {"user_input": user_input, "commit_id": commit_id}
        )


try:
    idea = "Create a website to play games, keep it in a cyberpunk theme, make sure the UI is really good and there a minimum of 5 games to play, make it a multipage application"
    process_app_idea(idea)

finally:
    state_manager = StateManager()
    repo_name = state_manager.get_work_dir()
    stop_server(repo_name)
    print_error("Exited forcefully")
