import os
import json
from langgraph.prebuilt import create_react_agent
from tools import save_files, init_git_repo, commit_changes
from prompts import planner_prompt, code_generation_prompt, code_validation_prompt
from state_manager import StateManager
from pydantic import BaseModel
from typing import List
from langchain_anthropic import ChatAnthropic
from langchain_deepseek import ChatDeepSeek

# Define the structure for file responses
class FileResponse(BaseModel):
   file_path: str
   content: str

class FileResponseList(BaseModel):
   items: List[FileResponse]

def init_models():
   planner_model = ChatDeepSeek(
      model="deepseek-chat",
      max_tokens=8000
   )
   code_model = ChatAnthropic(
      model="claude-3-7-sonnet-20250219",
      max_tokens=15000
   )
   return planner_model, code_model

def process_app_idea(idea: str):
   planner_model, code_model = init_models()
   state_manager = StateManager()

   # Check if a plan already exists
   if not state_manager.get_plan():
      plan_response = planner_model.invoke(planner_prompt.format(idea=idea))
      plan = plan_response.content
      state_manager.update_plan(plan)
   else:
      plan = state_manager.get_plan()

   print(f"\nProject Plan:\n{plan}\n")

   base_dir = os.path.join(os.getcwd(), "tempo")
   os.makedirs(base_dir, exist_ok=True)
   print(f"Using temp directory: {base_dir}")
   init_git_repo(base_dir)

   # Check if codebase already exists
   if not state_manager.get_codebase():
      code_agent = create_react_agent(
         model=code_model, 
         tools=[], 
         prompt=code_generation_prompt,
         response_format=FileResponseList
      )
      response = code_agent.invoke({"messages": [{"role": "user", "content": f"user idea:\n {idea}\n\n plan: \n{plan}"}]})
      raw_code = response['messages'][1].content

      print(f"Raw Code: \n\n{raw_code}\n\n")

      validation_agent = create_react_agent(
         model=code_model,
         tools=[],
         prompt=code_validation_prompt,
         response_format=FileResponseList
      )
      validated_code = validation_agent.invoke({"messages": [{"role": "user", "content": raw_code}]})
      code_data = json.loads(validated_code['messages'][1].content)

      print(f"Code Data: \n\n{code_data}\n\n")

      save_files(code_data, base_dir)
      commit_changes(base_dir, message="Initial project setup")

      state_manager.update_codebase(code_data)
   else:
      code_data = state_manager.get_codebase()

   while True:
      user_input = input("\n>>> Enter additional request for your project (or type 'exit'): ").strip()
      if user_input.lower() in {"exit", "quit"}:
         print("Exiting loop.")
         break

      state_manager.add_user_request(user_input)

      # Prepare context for the agent
      code_context = json.dumps(code_data)
      instruction = (
         "You are enhancing a project. The files for the project are as follows: "
         f"{code_context}\n\n"
         "The user will have a request to change the project in a certain way"
         "Please return updated files only. Keep same format."
         "If any file needs to be deleted send in same format but keep content as 'TERMINATE'"
      )

      code_agent = create_react_agent(
         model=code_model,
         tools=[],
         prompt=instruction,
         response_format=FileResponseList
      )
      response = code_agent.invoke({"messages": [{"role": "user", "content": user_input}]})
      raw_code = response['messages'][1].content

      print(f"Raw Code: \n\n{raw_code}\n\n")

      validation_agent = create_react_agent(
         model=code_model,
         tools=[],
         prompt=code_validation_prompt,
         response_format=FileResponseList
      )
      validated_update_code = validation_agent.invoke({"messages": [{"role": "user", "content": raw_code}]})
      updated_code_data = json.loads(validated_update_code['messages'][1].content)

      # Update the codebase with new changes
      existing_files = {file["file_path"]: file for file in code_data}

      for file in updated_code_data:
         if file["content"] == "TERMINATE" or file["content"] == "":
            existing_files.pop(file["file_path"], None)
         else:
            existing_files[file["file_path"]] = {"file_path": file["file_path"], "content": file["content"]}

      code_data = list(existing_files.values())

      print(f"Current Code: {code_data}")
      
      save_files(code_data, base_dir)
      commit_changes(base_dir, message=f"Applied user request: {user_input}")

      state_manager.update_codebase(code_data)


# if __name__ == "__main__":
idea = "I want to build a streamlit app for unit conversions, ONLY STREAMLIT"
process_app_idea(idea)