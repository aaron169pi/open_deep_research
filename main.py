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
    rollback_server,
    check_website,
    extract_preview_plan,
    ask_user_input_tool,
)
from prompts import (
    classifier_prompt,
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
    AppTypeResponse,
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
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    stdin=subprocess.DEVNULL,
)


def init_models():
    # planner_model = ChatDeepSeek(model="deepseek-chat", max_tokens=8000)

    classifier_model = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-preview-04-17",
        max_tokens=8000,
    )
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

    return classifier_model, planner_model, code_model, structure_model


def classify_app_type(idea: str) -> str:
    classifier_model, _, _, _ = init_models()

    classifier_agent = create_react_agent(
        model=classifier_model,
        tools=[],
        prompt=classifier_prompt,
        response_format=AppTypeResponse,
    )
    response = classifier_agent.invoke(
        {"messages": [{"role": "user", "content": idea}]}
    )
    app_type = response["structured_response"].app_type
    print_info(f"Classified app type: {app_type}")

    category_map = {
        "Modern Web App": "modern_web_app",
        "Streamlit App": "interactive_data_app",
        "Web App": "web_app_python",
    }
    return category_map.get(app_type)


def process_app_idea(idea: str, app_type: str = "auto"):
    classifier_model, planner_model, code_model, structure_model = init_models()
    state_manager = StateManager()

    if not state_manager.get_classification():
        valid_types = {"modern_web_app", "interactive_data_app", "web_app_python"}
        if app_type not in valid_types:
            print_info("🧠 Classifying app type automatically...")
            app_type = classify_app_type(idea)
            print_info(f"✅ Auto-classified as: {app_type}")
        else:
            print_info(f"✅ User selected app type: {app_type}")
        state_manager.add_classification(app_type)

    APP_TYPE_DESCRIPTIONS = {
        "modern_web_app": "A full-stack web application built with React frontend and Node.js backend, designed for complex user interactions, scalable architecture, and rich user experiences. Ideal for production-ready applications like e-commerce platforms, SaaS products, social media apps, and enterprise business applications that require advanced features like real-time updates, user authentication, and sophisticated state management.",
        "interactive_data_app": "A single-page Python application using the Streamlit framework for rapid prototyping and data-focused applications. Features built-in UI components, automatic reactivity, and seamless integration with data science libraries. Perfect for creating interactive dashboards, data visualization tools, ML model demonstrations, analytics platforms, and research tools that require quick development and easy sharing without separate frontend/backend architecture.",
        "web_app_python": "A web application with Python backend (Flask/FastAPI) and custom frontend (HTML/React), following API-first architecture with clear separation of concerns. Designed for building scalable web services, REST APIs, microservices, and custom web applications that require database integration, user management systems, authentication, and flexible frontend design options suitable for production environments.",
    }
    app_type = state_manager.get_classification()
    app_type_description = APP_TYPE_DESCRIPTIONS.get(
        app_type, "No description available."
    )
    print_info(f"✅ App Type Description:\n{app_type_description}")

    # Check if a plan already exists
    if not state_manager.get_plan():
        plan_response = planner_model.invoke(
            planner_prompt.format(
                idea=idea, app_type=app_type, app_type_description=app_type_description
            )
        )
        plan = plan_response.content
        state_manager.update_plan(plan)

    plan = state_manager.get_plan()
    print(f"\nProject Plan:\n{plan}\n")

    if app_type == "interactive_data_app":
        print_info("📊 Streamlit app detected - skipping HTML preview generation")
        state_manager.mark_feedback_done()
        # Set empty HTML data for consistency
        state_manager.update_html("<!-- Streamlit app - no HTML preview needed -->")
    else:
        if not state_manager.is_feedback_done():
            print(f"\n Initial Project Plan:\n{plan}\n")

            skip = True
            html_data = (
                "No html data is currently generated, user had some issue with the plan"
            )

            if not state_manager.get_html():
                plan_feedback = input(
                    "Do you have any changes for the plan? (or type 'no')\n>>>"
                )
                if plan_feedback in {"no", "n", ""}:
                    print_info(
                        " No changes made to the plan. Proceeding with implementation."
                    )
                    if not state_manager.get_html():
                        planner_input = html_planner_input.format(prompt=idea)
                        preview_plan = extract_preview_plan(plan)
                        preview = code_model.invoke(
                            html_planner_prompt.format(
                                plan=preview_plan, input=planner_input
                            )
                        )
                        html_data = preview.content
                        state_manager.update_html(html_data)
                        print(html_data)
                    else:
                        html_data = state_manager.get_html()

                    response = requests.post(
                        preview_url,
                        data=html_data.encode("utf-8"),
                        headers={"Content-Type": "text/plain"},
                    )
                    print_info(f"You can view the preview at {preview_url}")
                    skip = False
            else:
                skip = False

            while True:
                if not skip:
                    winsound.Beep(500, 500)

                    plan_feedback = input(
                        "Do you have any changes? (or type 'no')\n>>>"
                    )

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
            If the user's query is purely regarding makes no actual change to the plan then give back the old plan itself

            First understand the original plan and make the changes accordingly.
            Your task is to revise the original plan by merging the user's feedback carefully:
            - Do *not* discard any original information unless the user clearly says so.
            - If the user provides a new goal, integrate it into the existing goal rather than replacing it entirely.
            - If a value is given, apply the change additively or descriptively while preserving the structure and content of the original.
            - If user feedback is to add new page and update the page structure, do so without removing existing pages and their content.
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

                skip = False

                planner_input = html_planner_input.format(prompt=idea)
                planner_update_input = html_planner_input.format(prompt=plan_feedback)
                preview_plan = extract_preview_plan(plan)
                refined_preview_plan = extract_preview_plan(refined_plan)
                preview = code_model.invoke(
                    html_update_planner_prompt.format(
                        plan=preview_plan,
                        input=planner_input,
                        html_code=html_data,
                        refined_plan=refined_preview_plan,
                        user_suggestion=planner_update_input,
                    )
                )
                html_data = preview.content
                print(f"\n HTML Preview:\n{html_data}\n")
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

    html_data = state_manager.get_html()

    if app_type != "interactive_data_app":
        print_success(f"Preview: {preview_url}")
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
        if app_type == "interactive_data_app":
            print_info(
                "📊 Streamlit app detected - generating structure for Streamlit application"
            )
            structure_content = f"Idea: {idea}\n\nPlan:\n{plan}\n\nApp Type: Streamlit application - focus on Python components and data handling"
        else:
            html_data = state_manager.get_html()
            structure_content = f"Idea: {idea}\n\nPlan:\n{plan}\n\nA sample preview generated using html only for reference on how the UI for the website should look:\n{html_data}"

        structure_response = structure_agent.invoke(
            {"messages": [{"role": "user", "content": structure_content}]}
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
        for progress, batch in batch_files(file_paths, batch_size=5):

            if app_type == "interactive_data_app":
                print_info(
                    "📊 Streamlit app detected - generating code for Streamlit application"
                )
                batch_content = f"Idea: {idea}\n\nPlan: {plan}\n\nApp Type: Streamlit application\n\nEntire file structure: {structure}\n\nFiles you need to generate: {batch}\n\nSummary of previously generated code: {summary}"
            else:
                html_data = state_manager.get_html()
                batch_content = f"Idea: {idea}\n\nPlan: {plan}\n\nA sample preview generated using html only for reference on how the UI for the website should look:\n{html_data}\n\nEntire file structure: {structure}\n\nFiles you need to generate: {batch}\n\nSummary of previously generated code: {summary}"

            response = batch_agent.invoke(
                {"messages": [{"role": "user", "content": batch_content}]}
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
        if repo_name is None:
            print_warning("No changes were made in the commit")
        else:
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
                user_input = f"Here is the original plan that was used to generate this code:\n\n{plan}\n\nHere is the detailed report of the code review, please handle all of the errors detailed in this report and fix them: {report}, please make sure that the code is working properly and there are no errors ."
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
            time.sleep(60)
            link = server_res_obj["link"]
            code, check_msg = check_website(link, repo_name)
            time.sleep(5)
            code, check_msg = check_website(link, repo_name)

            if "success" not in check_msg or code == 1:
                print_error(f"This is the server error message: \n\n{check_msg}")
                user_input = (
                    "\n\nThis code was run inside of a docker container, the container stopped due to some issue or something else happened"
                    f"This was the server log: {check_msg}"
                    "Fix this error properly and any errors that might propogate due to this error too"
                )
            else:
                print_info("There are no errors server-side")
                print_success(server_res)
                winsound.Beep(500, 500)  # remove in production
                user_input = input(
                    "\n>>> Enter additional request for your project (or type 'exit'): "
                ).strip()

                code, check_msg = check_website(link, repo_name)
                if "success" not in check_msg:
                    print_error(check_msg)
                    user_input += (
                        "\n\nThis code was run inside of a docker container, the container stopped due to some issue or something else happened"
                        f"This was the error log: {check_msg}"
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

        for progress, batch in batch_files(code_changes_data, batch_size=5):
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
        if repo_name is None:
            print_warning("No changes were made in the commit")
        else:
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
Create a simple snake game that should be playable in both laptop and mobile
"""
app_type = ""  # or "modern_web_app", "interactive_data_app"
process_app_idea(idea, app_type)
