import json
import requests
import subprocess
import atexit
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
    check_website,
    ask_user_input_tool,
)
from prompts import (
    planner_prompt,
    code_generation_prompt,
    code_validation_prompt,
    file_structure_prompt,
    file_changes_prompt,
    html_planner_input,
    html_planner_prompt,
    html_update_planner_prompt,
    reviewer_prompt,
)
from state_manager import StateManager
from response_models import (
    FileStructureList,
    FileGenerationList,
    FileChangesList,
    ReviewerResponse,
)
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
import winsound  # remove in production
import os
from dotenv import load_dotenv
import time

load_dotenv()

deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
preview_url = os.getenv("PREVIEW_URL")

# Start uvicorn as a subprocess with no stdio
process = subprocess.Popen(
    ["uvicorn", "preview:app", "--host", "0.0.0.0", "--port", "7000"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    stdin=subprocess.DEVNULL,
)


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
    print(plan)
    if not state_manager.is_feedback_done():
        print(f"\n Initial Project Plan:\n{plan}\n")
        if not state_manager.get_html():
            planner_input = html_planner_input.format(prompt=idea)
            preview = code_model.invoke(
                html_planner_prompt.format(plan=plan, input=planner_input)
            )
            html_data = preview.content
        else:
            html_data = state_manager.get_html()

        response = requests.post(
            preview_url,
            data=html_data.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
        )
        print_info(f"You can view the preview at {preview_url}")

        while True:
            winsound.Beep(500, 500)
            plan_feedback = input("Do you have any changes? (or type 'no')\n>>>")

            # Check if all values are "no" or empty
            if plan_feedback in {"no", "n", ""}:
                print_info(
                    " No changes made to the plan. Proceeding with implementation."
                )
                state_manager.update_html(html_data)
                state_manager.update_plan(plan)
                state_manager.mark_feedback_done()
                print("Feedback marked as done. Exiting feedback loop.")
                break  # This break is inside the while True loop, so it's valid

            refined_plan_prompt = f"""
        Here is the original project plan:

        {plan}
        The user has provided the following feedback.
        {plan_feedback}
        A preview using HTML was also generate and these are the contents for reference
        {html_data}
        If the user's query is purely regarding the html and makes no actual change to the plan then give back the old plan itself

        First understand the original plan and make the changes accordingly.
        Your task is to revise the original plan by merging the user's feedback carefully:
        - Do *not* discard any original information unless the user clearly says so.
        - If the user provides a new goal, integrate it into the existing goal rather than replacing it entirely.
        - If a value is given, apply the change additively or descriptively while preserving the structure and content of the original.
        
        🧠 Always begin your answer with a <thinking> ... </thinking> section. In this section, write a detailed natural-language explanation covering:
        - What the user's feedback was,
        - What changes you made based on it,
        - And how those changes respect and enhance the original plan.

        Do not discuss sections where the user said “no changes” — only explain the parts that you actually modified.
        Your explanation should flow like human reasoning — not in list format or bullet points.
        After that, return the revised project plan in the **exact same markdown format** as the original.
        Be concise. Avoid introducing unnecessary tools or complexity unless explicitly requested.
        """
            refined_plan_response = planner_model.invoke(refined_plan_prompt)
            refined_plan = refined_plan_response.content
            print(f"\n Refined Plan:\n{refined_plan}")

            planner_input = html_planner_input.format(prompt=idea)
            planner_update_input = html_planner_input.format(prompt=plan_feedback)
            preview = code_model.invoke(
                html_update_planner_prompt.format(
                    plan=plan,
                    input=planner_input,
                    html_code=html_data,
                    refined_plan=refined_plan,
                    user_suggestion=planner_update_input,
                )
            )
            html_data = preview.content
            plan = refined_plan
            response = requests.post(
                preview_url,
                data=html_data.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
            )
            print_info(f"You can view the preview at {preview_url}")

            state_manager.update_plan(plan)
            state_manager.update_html(html_data)
            state_manager.mark_feedback_done()

    print_success(f"Preview: {preview_url}")
    html_data = state_manager.get_html()
    response = requests.post(
        preview_url,
        data=html_data.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
    )

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
                    {
                        "role": "user",
                        "content": f"Idea: {idea}\n\nPlan:\n{plan}\n\nA sample preview generated using html only for reference on how the UI for the website should look:\n{html_data}",
                    }
                ]
            }
        )
        file_paths = structure_response["structured_response"].paths
        state_manager.update_structure(file_paths)

    structure = state_manager.get_structure()
    gen_structure = state_manager.get_generated()
    file_paths = [item for item in structure if item not in gen_structure]
    print_warning(str(file_paths))
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
                            "content": f"Idea: {idea}\n\nPlan: {plan}\n\nA sample preview generated using html only for reference on how the UI for the website should look:\n{html_data}\n\n\nEntire file structure: {structure}\n\n\nFiles you need to generate: {batch}\n\nSummary of previously generated code: {summary}",
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

            print_success(response["structured_response"].reasoning)
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

    if not state_manager.is_review_done():
        reviewer_agent = create_react_agent(
            model=code_model,
            tools=[],
            prompt=reviewer_prompt,
            response_format=ReviewerResponse,
        )
        response = reviewer_agent.invoke(
            {
                "messages": [
                    {"role": "user", "content": f"This is the codebase {code_data}"}
                ]
            }
        )
        status_code = response["structured_response"].status_code
        report = response["structured_response"].report or None
        state_manager.mark_review_done()
    else:
        status_code = 0
        report = None

    while True:
        repo_name = state_manager.get_work_dir()
        server_res_obj = start_server(repo_name)
        server_res = json.dumps(server_res_obj)

        if "Failed" in server_res or "Error" in server_res or status_code == 1:
            if status_code == 1:
                print_warning(report)
                user_input = f"Here is the detailed report of the code review, please handle all of the errors detailed in this report and fix them: {report}"
                status_code = 0
            else:
                print_error(server_res)
                user_input = (
                    f"The server failed to start. Here is the error log from response.text:\n\n"
                    f"{server_res}\n\n"
                    f"Please analyze and fix the root cause in the code."
                    "Make sure that a startup.sh file is created and the outgoing port is strictly 9000 if it is exposing 2 ports than serve the build file through the backend itself and then make the backend use 9000 port"
                )
        else:
            print_warning("Checking for any errors...")
            time.sleep(30)
            link = server_res_obj["link"]
            code, check_msg = check_website(link)
            time.sleep(5)
            error_res = server_logs(repo_name)

            if "success" not in error_res[:10] or code == 1:
                print_error(
                    f"This is the server error message: \n\n{error_res}\n\nThis is server response: \n\n {check_msg}"
                )
                user_input = (
                    "\n\nThis code was run inside of a docker container, the container stopped due to some issue or something else happened"
                    f"This was the error log: {error_res}"
                    f"This was the server response: {check_msg}"
                    "Fix this error properly and any errors that might propogate due to this error too"
                )
            else:
                print_info("There are no errors server-side")
                print_success(server_res)
                winsound.Beep(500, 500)  # remove in production
                user_input = input(
                    "\n>>> Enter additional request for your project (or type 'exit'): "
                ).strip()

                error_res = server_logs(repo_name)
                if "success" not in error_res:
                    print_error(error_res)
                    user_input += (
                        "\n\nThis code was run inside of a docker container, the container stopped due to some issue or something else happened"
                        f"This was the error log: {error_res}"
                        "Fix this error properly and any errors that might propogate due to this error too"
                    )

                if user_input.lower() in {"exit", "quit"}:
                    stop_server(repo_name)
                    print("Exiting loop.")
                    break

                if user_input.lower() in {"restart"}:
                    res = start_server(repo_name)
                    print_success(res)
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
        print_success(response["structured_response"].reasoning)
        print(f"\n\nCode Changes Suggested: \n\n{code_changes_data}\n\n")

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


@atexit.register
def cleanup():
    print("Terminating Uvicorn subprocess... and exiting program")
    process.terminate()
    process.wait()
    state_manager = StateManager()
    repo_name = state_manager.get_work_dir()
    stop_server(repo_name)


idea = """
Create web application for desktop and mobile with apartment listing with transparant character that people can use free of charge. Same easy of use as websites like AirBnB. Integrate Dutch point system for every apartment listing. Dutch point system assigns point and calculates maximum rent. Build it MERN Stack
"""
process_app_idea(idea)
