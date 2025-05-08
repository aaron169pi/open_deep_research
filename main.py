import os
import json
from langgraph.prebuilt import create_react_agent
from tools import save_files, init_git_repo, commit_changes, print_error, print_info, batch_files
from prompts import planner_prompt, code_generation_prompt, code_validation_prompt
from state_manager import StateManager
from pydantic import BaseModel
from typing import List
# from langchain_anthropic import ChatAnthropic
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
import re
import winsound #remove in production

# Define the structure for file responses
class FileResponse(BaseModel):
   file_path: str
   content: str

class FileResponseList(BaseModel):
   items: List[FileResponse]

class FileStructureResponse(BaseModel):
   paths: List[str]

def init_models():
   planner_model = ChatDeepSeek(
      model="deepseek-chat",
      max_tokens=8000
   )
   structure_model = ChatGoogleGenerativeAI(
      model="gemini-2.5-pro-preview-05-06",
      max_tokens=8000
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

   base_dir = os.path.join(os.getcwd(), "tempo")
   os.makedirs(base_dir, exist_ok=True)
   print(f"Using temp directory: {base_dir}")
   init_git_repo(base_dir)

   # Check if structure already exists
   if not state_manager.get_structure():
      file_structure_prompt = (
         "Based on the following app idea and plan, generate a list of file paths only (no content). "
         "Only include files you intend to create. Respond in JSON list like: [\"src/App.js\", \"src/index.js\", ...].\n\n"
         "Always create all important files such as package.json for react, requirements.txt for python, etc"
         "Do not include file paths for images, audio, etc that are static assents, only generate code file paths"
         "Do not needlessly create files, only create files if they are absolutely needed, the lesser the number of files the better"
      )
      structure_agent = create_react_agent(
         model=structure_model,
         tools=[],
         prompt=file_structure_prompt,
         response_format=FileStructureResponse
      )
      structure_response = structure_agent.invoke({
         "messages": [{"role": "user", "content": f"Idea: {idea}\n\nPlan:\n{plan}"}]
      })
      try:
         file_paths = json.loads(structure_response['messages'][-1].content)
         state_manager.update_structure(file_paths)
      except Exception as e:
         try:
            raw = structure_response['messages'][-1].content
            file_paths = json.loads(raw.strip().strip("```json").strip("```").strip())
            state_manager.update_structure(file_paths)
         except Exception as e:
            print_error(f"Structure parse error: {e}, raw response: {structure_response['messages'][-1].content}")

   structure = state_manager.get_structure()
   gen_structure = state_manager.get_generated()
   file_paths = [item for item in structure if item not in gen_structure]

   print(f"\nProject Structure:\n{structure}\n")

   # Check if codebase already exists
   if file_paths:
      generated_code = state_manager.get_codebase()
      summary = state_manager.get_summary()

      batch_agent = create_react_agent(
               model=code_model,
               tools=[],
               prompt=code_generation_prompt,
               response_format=FileResponseList
      )
      for batch in batch_files(file_paths, batch_size=4):
         response = batch_agent.invoke({
            "messages": [{"role": "user", "content": 
            f"Idea: {idea}\n\nPlan: {plan}\n\n\nEntire file structure: {structure}\n\n\nFiles you need to generate: {batch}\n\nSummary of previously generated code: {summary}"}]
         })
         print(f"\n\nBatch {batch}:\n\n{response['messages'][-1].content}")
         try:
            batch_code = json.loads(response['messages'][-1].content)
         except Exception as e:
            try:
               raw = response['messages'][-1].content
               match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
               if match:
                  array_str = match.group(0)
                  array_str = re.sub(r'```json\s*', '', array_str, flags=re.IGNORECASE)
                  array_str = re.sub(r'```', '', array_str)
                  batch_code = json.loads(array_str)
               else:
                  print_error("No JSON array found in the response.")
            except Exception as e:
               print_error(f"Batch parse error: {e}, response: \n{response['messages'][-1].content}")

         generated_code.extend(batch_code)

         save_files(generated_code, base_dir)
         state_manager.update_codebase(generated_code)

         gen_structure.extend(batch)
         state_manager.update_generated(gen_structure)

         summary.append(
            [{key: value for key, value in item.items() if key != "content"} for item in batch_code]
         )
         state_manager.update_summary(summary)

      print(f"Generated Code: \n\n{generated_code}")
      commit_changes(base_dir, message="Initial project setup")

   code_data = state_manager.get_codebase()

   while True:
      winsound.Beep(500, 500) #remove in production
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
      raw_code = response['messages'][-1].content

      print(f"Raw Code: \n\n{raw_code}\n\n")

      validation_agent = create_react_agent(
         model=code_model,
         tools=[],
         prompt=code_validation_prompt,
         response_format=FileResponseList
      )
      validated_update_code = validation_agent.invoke({"messages": [{"role": "user", "content": raw_code}]})
      try:
         updated_code_data = json.loads(validated_update_code['messages'][-1].content)
      except json.JSONDecodeError as e:
         try:
            raw = validated_update_code['messages'][-1].content
            match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
            if match:
               array_str = match.group(0)
               array_str = re.sub(r'```json\s*', '', array_str, flags=re.IGNORECASE)
               array_str = re.sub(r'```', '', array_str)
               updated_code_data = json.loads(array_str)
            else:
               print_info("No JSON array found in the response.")
         except Exception as e:
            print_error(f"Batch parse error: {e}, response: \n{validated_update_code['messages'][-1].content}")

            print_info("There was no update in the code, please check generated input")

      if updated_code_data:
         print(f"\nUpdated Validated Code:\n{updated_code_data}\n")
      
         # Update the codebase with new changes
         existing_files = {file["file_path"]: file for file in code_data}

         for file in updated_code_data:
            if file["content"] == "TERMINATE" or file["content"] == "":
               existing_files.pop(file["file_path"], None)
            else:
               existing_files[file["file_path"]] = {"file_path": file["file_path"], "content": file["content"]}

         code_data = list(existing_files.values())

         save_files(code_data, base_dir)
         commit_changes(base_dir, message=f"Applied user request: {user_input}")

         state_manager.update_codebase(code_data)


# if __name__ == "__main__":
idea = "I want to build a windows application using electron to have a record of all my financial spendings, make sure there are various ways to store all kinds of data and to have tags, also let all the data be stored as a scv file that i can export anytime i want."
process_app_idea(idea)