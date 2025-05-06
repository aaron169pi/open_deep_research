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
   code_model = ChatAnthropic(
      model="claude-3-7-sonnet-20250219",
      max_tokens=15000
   )
   structure_model = ChatAnthropic(
      model="claude-3-7-sonnet-20250219",
      max_tokens=8000
   )

   return planner_model, code_model, structure_model

def print_error(str):
   print('\033[91m' + str + '\033[0m')

def batch_files(file_paths, batch_size):
    for i in range(0, len(file_paths), batch_size):
        yield file_paths[i:i + batch_size]

def process_app_idea(idea: str):
   planner_model, code_model, structure_model = init_models()
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
      print(f"Structure: {structure_response['messages'][-1].content}")
      try:
         file_paths = json.loads(structure_response['messages'][-1].content)
      except Exception as e:
         try:
            raw = structure_response['messages'][-1].content
            file_paths = json.loads(raw.strip().strip("```json").strip("```").strip())
         except Exception as e:
            print_error(f"Structure parse error: {e}, raw response: {structure_response['messages'][-1].content}")
            return 1

      generated_code = []
      summary = []

      batch_agent = create_react_agent(
               model=code_model,
               tools=[],
               prompt=code_generation_prompt,
               response_format=FileResponseList
      )
      for batch in batch_files(file_paths, batch_size=4):
         response = batch_agent.invoke({
            "messages": [{"role": "user", "content": 
            f"Idea: {idea}\n\nPlan: {plan}\n\n\nEntire file structure: {file_paths}\n\n\nFiles you need to generate: {batch}\n\nSummary of previously generated code: {summary}"}]
         })
         print(f"\n\nBatch {batch}:\n\n{response['messages'][-1].content}")
         try:
            batch_code = json.loads(response['messages'][-1].content)
            generated_code.extend(batch_code)
         except Exception as e:
            try:
               raw = response['messages'][-1].content
               batch_code = json.loads(raw.strip().strip("```json").strip("```").strip())
               generated_code.extend(batch_code)
            except Exception as e:
               print_error(f"Batch parse error: {e}, response: {response['messages'][-1].content}")
         summary.append([ {key: value for key, value in item.items() if key != "content"} for item in batch_code])

      print(f"Generated Code: \n\n{generated_code}")

      # validation_agent = create_react_agent(
      #    model=code_model,
      #    tools=[],
      #    prompt=code_validation_prompt,
      #    response_format=FileResponseList
      # )
      # for i, file in enumerate(generated_code):
      #    validated_update_code = validation_agent.invoke({"messages": [{"role": "user", "content": str(file)}]})
      #    try:
      #       updated_code_data = json.loads(validated_update_code['messages'][-1].content)
      #       print(f"updated_code_data")
      #       generated_code[i]['content'] = updated_code_data
      #    except json.JSONDecodeError as e:
      #       print_error(f"JSON decoding error: {e}")
      #       updated_code_data = None
      #    except Exception as e:
      #       print_error(f"Unexpected error: {e}, code was: {validated_update_code['messages']}")
      #       updated_code_data = None


      save_files(generated_code, base_dir)
      commit_changes(base_dir, message="Initial project setup")
      state_manager.update_codebase(generated_code)

   else:
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
         print_error(f"JSON decoding error: {e}")
         updated_code_data = None
         return 1 #exits when there's a problem 
      except Exception as e:
         print_error(f"Unexpected error: {e}, code was: {validated_update_code['messages']}")
         updated_code_data = None

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
idea = "I want to build a Customer relation management app(CRM) using react for my company called 169pi"
process_app_idea(idea)