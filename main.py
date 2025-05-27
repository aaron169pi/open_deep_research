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
    if not state_manager.is_feedback_done():
        print(f"\n Initial Project Plan:\n{plan}\n")
        while True:
            plan_feedback = {}
            plan_feedback["goal"] = input(" Change goal? (or type 'no'): ").strip()
            plan_feedback["pages"] = input(" Change pages? (or type 'no'): ").strip()
            plan_feedback["features"] = input(" Change features? (or type 'no'): ").strip()
            plan_feedback["typography"] = input("Change typography (fonts)? (or type 'no'): ").strip()
            plan_feedback["colors"] = input("Change colors (hex)? (or type 'no'): ").strip()
            
            # Check if all values are "no" or empty
            if all(val.lower() in {"no", ""} for val in plan_feedback.values()):
                print_info(" No changes made to the plan. Proceeding with implementation.")
                state_manager.mark_feedback_done()
                print("Feedback marked as done. Exiting feedback loop.")
                break  # This break is inside the while True loop, so it's valid
            
            # Process the feedback and update the plan
            feedback_json = json.dumps(plan_feedback, indent=2)
            print(f"\n User Feedback:\n{feedback_json}\n")
            
            refined_plan_prompt = f"""
        Here is the original project plan:

        {plan}
        The user has requested the following changes in JSON format:
        {feedback_json}

        First understand the original plan and make the changes accordingly.
        Your task is to revise the original plan by merging the user's feedback carefully:
        - Do *not* discard any original information unless the user clearly says so.
        - If the user provides a new goal, integrate it into the existing goal rather than replacing it entirely.
        - If a value is given, apply the change additively or descriptively while preserving the structure and content of the original.
        
        Return the updated project plan in the exact same markdown format.
        ***Be concise. Avoid introducing unnecessary complexity or tools.
        """
            refined_plan_response = planner_model.invoke(refined_plan_prompt)
            refined_plan = refined_plan_response.content
            print(f"\n Refined Plan:\n{refined_plan}")
            state_manager.update_plan(refined_plan)
            state_manager.add_user_request({
                "user_input": feedback_json,
                "type": "plan_refinement"
            })
            plan = refined_plan
            state_manager.mark_feedback_done()


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

            # if user_input.lower() in {"logs"}:
            #     res = server_logs(repo_name)
            #     if "success" in res:
            #         print_info("There are no errors server-side")
            #         print_warning(f"Trace: {res}")
            #         continue
            #     else:
            #         print_error(res)
            #         user_input = input("\n>>> Would you like to fix this error(y/n)?")
            #         if user_input in {"y", "yes"}:
            #             user_input = (
            #                 "This code was run inside of a docker container, the container stopped due to some issue or something else happened"
            #                 f"This was the error log: {res}"
            #                 "Fix this error properly and any errors that might propogate due to this error too"
            #             )
            #         else:
            #             user_input = ""
            #             continue

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

            res = server_logs(repo_name)
            if "success" in res:
                pass
            else:
                print_error(res)
                user_input += (
                    "\n\nThis code was run inside of a docker container, the container stopped due to some issue or something else happened"
                    f"This was the error log: {res}"
                    "Fix this error properly and any errors that might propogate due to this error too"
                )

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


try:
    idea = """
Design a one-page responsive website for a graphic design studio called hueneu. The layout should be inspired by Studio Morii's website—clean, minimal, scroll-based, and experience-led—but the tone, visuals, and experience must feel deeply personal and reflective of hueneu's identity.
✦ What hueneu is all about:
Name meaning: "Hue" = creative color bursts, "Neu" = grounding neutrality
Personality: Quiet but bold. Calm, mysterious, and a little playful. A studio that surprises with unexpected design moments ("Who Knew?")
Design style: Story-first, intentional, balanced, sometimes nostalgic, always evocative
Voice: Warm, poetic, subtly humorous. Think soft sophistication—not cold minimalism
✦ Structure & Content:
1. Hero Section
Animated hueneu logo reveal (just like Instagram's first post)
Tagline: "Where stories find their aesthetic."
Subtext: "Designs that whisper loud stories."
Smooth scroll-down indicator, playful but minimal
2. The hueneu Story
Short section about what hueneu means
Emphasize the balance of color and calm
Bring in the "Who Knew?" moment with a fun visual pop-out or scroll-triggered element
3. What We Do
5-6 core offerings presented with icons or line visuals:
Branding
Packaging
Social Media
Stationery
Coffee Table Books
Creative Projects
Each with a playful, single-line microcopy (e.g., "Packaging, but make it poetic")
5. Why hueneu?
Emotional brand pitch in poetic copy:
"We don't just design—we decode stories."
"Designs that speak quietly but stay with you."
Highlight calm, mystery, and balance.
6. Let's Work Together
A contact form that feels like a note or letter
Playful CTA button copy (e.g., "Let's design your story")
Add Instagram: @hueneu_
Optional: Embed a link to the services deck or a cute visual of the "Who Knew?" segment
✦ Visual & Interaction Style:
Color palette: Muted neutrals with occasional vibrant pops (inspired by brand's "Hue + Neu" concept)
Typography: Modern, elegant sans-serif with hints of personality—balance clarity and surprise
Layout: Scroll-based storytelling. Minimal, but not cold.
Effects: Subtle animations, hover reveals, scroll-triggered movement—especially for "Who Knew?"
Mood: Cozy. Intimate. Intriguing. Experimental in a soft-spoken way.
"""
    process_app_idea(idea)

finally:
    state_manager = StateManager()
    repo_name = state_manager.get_work_dir()
    stop_server(repo_name)
    print_error("Exited forcefully")
