import json
from langgraph.prebuilt import create_react_agent
from tools import (
    save_files,
    init_git_repo,
    commit_changes,
    print_error,
    print_success,
    print_warning,
    print_info,
    batch_files,
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
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
import winsound  # remove in production


def init_models():
    # planner_model = ChatDeepSeek(model="deepseek-chat", max_tokens=8000)
    planner_model = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-preview-04-17",
        max_tokens=8000,
    )
    structure_model = ChatGoogleGenerativeAI(
        model="gemini-2.5-pro-preview-05-06",
        max_tokens=10000,
    )
    code_model = ChatGoogleGenerativeAI(
        model="gemini-2.5-pro-preview-05-06",
        max_tokens=25000,
    )

    return planner_model, code_model, structure_model


def process_app_idea(idea: str):
    planner_model, code_model, structure_model = init_models()
    state_manager = StateManager()

    # Check if a plan already exists
    if not state_manager.get_plan():
        plan_response = planner_model.invoke(planner_prompt.format(idea=idea))
        plan = plan_response.content
        state_manager.update_plan(plan)

    plan = state_manager.get_plan()
    print(f"\nProject Plan:\n{plan}\n")

    # Initialisation of directory
    base_dir = init_git_repo()
    print(f"Using temp directory: {base_dir}")

    # Check if structure already exists
    if not state_manager.get_structure():
        structure_agent = create_react_agent(
            model=structure_model,
            tools=[],
            prompt=file_structure_prompt,
            response_format=FileStructureList,
        )
        structure_response = structure_agent.invoke(
            {
                "messages": [
                    {"role": "user", "content": f"Idea: {idea}\n\nPlan:\n{plan}"}
                ]
            }
        )
        file_paths = structure_response["structured_response"].paths
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
        commit_changes(base_dir, message="Initial project setup")

    code_data = state_manager.get_codebase()

    while True:
        winsound.Beep(500, 500)  # remove in production
        user_input = input(
            "\n>>> Enter additional request for your project (or type 'exit'): "
        ).strip()
        if user_input.lower() in {"exit", "quit"}:
            print("Exiting loop.")
            break

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

                state_manager.add_user_request(user_input)
                state_manager.update_codebase(code_data)
            else:
                print_info(
                    "There was no update in this batch, please check generated input"
                )

        commit_changes(base_dir, message=f"Applied user request: {user_input[:200]}")


idea = (
    "create a MERN stack app for playing tick tac toe and saving the score with names"
)
process_app_idea(idea)
