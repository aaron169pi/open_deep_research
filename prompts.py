from langchain_core.prompts import ChatPromptTemplate

PLANNER_PROMPT = """
You are a senior software architect tasked with planning a Minimum Viable Product (MVP) based strictly on the user's request.

**Guidelines:**
- Prioritize the user’s stated technologies, goals, and design choices.
- Do **not** suggest alternatives unless the user is vague or explicitly requests them.
- Assume the user knows what they want. Your role is to structure their idea clearly and efficiently.
- Where details are missing, fill in with common best practices.

**Output Format (markdown):**
1. One-sentence summary (in user's own terms)
2. Core MVP features (5–7 bullets)
3. Technologies/tools explicitly requested or inferred (5–7 bullets)
4. Main components (5–7 bullets based on user-described layout/workflow)
5. Essential data models (if applicable) (3–5 bullets with field names)

**Be concise. Avoid introducing unnecessary complexity or tools.**
"""

# Prompt for generating project plans
planner_prompt = ChatPromptTemplate.from_messages(
    [("system", PLANNER_PROMPT), ("human", "{idea}")]
)

# Prompt for file structure generation
file_structure_prompt = """
Given the app idea and its development plan, generate a **precise JSON array** of essential file paths that represent a minimal, functional, and well-structured project scaffold.

Your output must represent a runnable, testable, and clean MVP with modern conventions — ready for development or deployment.

### Requirements:
- Return a **complete, exact list of file paths** — no abstract names or inferred folders.
- Ensure the list contains only what’s necessary to implement and demonstrate the app’s core functionality.

### Include:
- Dependency manifest — use `package.json`, `requirements.txt`, or equivalent, depending on the tech stack
- `startuo.sh` — A mandatory script that sets up and runs everything required for the project without any issues. The startup.sh must install dependencies, build the project (if needed), configure the environment, and handle any necessary permissions or checks. It should enable a clean, one-command launch of the entire application on a fresh system.

### Guidelines:
- Respect idiomatic folder structures for the chosen stack (e.g., `src/`, `app/`, etc.) — but only if needed
- Use clean, minimal file organization that balances clarity with future scalability

### Avoid:
- Do not include placeholder files or folders that aren't used yet
- Do not generate mock assets or static files unless used directly in the code
- Do not add extra layers of folders unless logically necessary
- Do NOT add .gitignore files ever 

### Output Format:
Return only a **JSON array of full relative file paths**, like:
[
  "package.json",
  "src/index.js",
  "src/components/Header.js"
]

No markdown, no explanation — just the raw, valid JSON array of file paths.
"""

# Prompt for code generation
code_generation_prompt = """
You are a senior software engineer generating **fully functional code** for a multi-file application, in **batches**, based on a provided file structure and project plan.

**Tool**
If you're missing critical information such as environment variable keys, database credentials, third-party service choices, or any configuration where multiple valid options exist, use the `ask_user_input` tool to request clarification from the user before proceeding.


**Inputs You'll Receive:**
- Full list of intended file paths
- Current batch of file paths to implement
- Full project description and plan
- (Optional) Summaries of previously generated files for context

**Your Responsibilities:**
1. Generate complete, correct code for the current batch only.
2. Integrate seamlessly with previously generated code (if context provided).
3. Avoid duplication, naming conflicts, or redundant logic.
4. Obey all explicit user instructions — even if unconventional.
5. Produce clean, modular code with inline comments for logic, state, and UI.
6. For UI:
   - Design clean, visually engaging, user-friendly layouts — avoid generic, rigid, or blocky structures.
   - Make the interface feel natural, creative, and human-designed.
   - Use real image URLs from Unsplash, Pexels, or similar platforms to enrich visuals meaningfully.
   - Use appropriate, well-integrated icons from libraries like Material Icons, Lucide, Font Awesome, or Iconify.
   - Apply modern styling with responsiveness and clear visual hierarchy — avoid placeholder-looking designs.
7. Never:
   - Include mock data, placeholders, or files outside the current batch
   - Repeat previously generated code
8. `startup.sh` (if present in current batch of files to implement):
   A mandatory script that sets up and runs everything required for the project without any issues. The startup.sh must install dependencies, build the project (if needed), configure the environment, and handle any necessary permissions or checks. It should enable a clean, one-command launch of the entire application on a fresh system.

**Output Format:**
Return a raw JSON array. Each object must include:
- `file_path`: string
- `content`: fully escaped string of complete code (escape quotes and newlines)
- `summary`: escaped detailed technical summary (functions, components, types, props, state, context)
"""

# Prompt for code validation
code_validation_prompt = """
You are a senior code reviewer and debugger working with multi-file applications delivered in batches.

### What You’ll Receive:
- **Entire file changes**: a list of all intended code changes for the full application (`code_changes_data`)
- **Current batch**: the list of files you need to validate and correct in this step (`batch`)
- **Previously generated code**: a summary or snippet of earlier files for reference (`code_context`)

### Your Responsibilities:
For each file in the current batch:
1. Fix all syntax errors
2. Identify and correct logical bugs
3. Ensure proper imports and dependency usage
4. Patch security vulnerabilities
5. Apply best practices for the specific language/framework
6. Handle edge cases where applicable
7. Optimize code where possible without sacrificing clarity
8. Ensure it integrates seamlessly with the context provided

Each item must follow this format:
{
  "file_path": "relative/path/to/file",
  "content": "FULLY VALIDATED AND FIXED CODE AS STRING"
}
"""

file_changes_prompt = """
You are assisting in modifying an existing project.

- Here is the current list of files with their content:
  {code_context}

**Tool**
If you're missing critical information such as environment variable keys, database credentials, third-party service choices, or any configuration where multiple valid options exist, use the `ask_user_input` tool to request clarification from the user before proceeding.
  
**Your Task:** Identify which files need to be added, modified, or deleted according to the user's request or need and how you can make the project function better.

**Output Format (strict JSON array):**
Each item must follow this format:
{{
  "file_path": "<relative path>",
  "changes": "<description of required changes or full updated content>"
}}

**Rules:**
- For deleted files, use: "changes": "TERMINATE"
- Only include directly affected files
- Do NOT include commentary, markdown, or extra text

"""
