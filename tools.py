import os
import subprocess
# from langchain_core.tools import tool

# @tool
def save_files(code_data: str, base_dir: str) -> str:
    """
    Save files from a JSON object to the specified directory.
    """
    try:
        for item in code_data:
            path = os.path.join(base_dir, item['file_path'])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(item['content'])
        return "Files saved successfully."
    except Exception as e:
        return f"Error saving files: {str(e)}"

# @tool
def init_git_repo(base_dir: str) -> str:
    """
    Initialize a Git repository in the specified directory.
    """
    try:
        if not os.path.exists(os.path.join(base_dir, ".git")):
            subprocess.run(["git", "init"], cwd=base_dir, check=True)
            subprocess.run(["git", "config", "user.email", "you@example.com"], cwd=base_dir, check=True)
            subprocess.run(["git", "config", "user.name", "Your Name"], cwd=base_dir, check=True)
        return "Git repository initialized."
    except subprocess.CalledProcessError as e:
        return f"Error initializing Git repository: {str(e)}"

# @tool
def commit_changes(base_dir: str, message: str = "Update code") -> str:
    """
    Commit changes in the Git repository with the provided message.
    """
    try:
        subprocess.run(["git", "add", "."], cwd=base_dir, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=base_dir, check=True)
        return "Changes committed successfully."
    except subprocess.CalledProcessError as e:
        return f"Error committing changes: {str(e)}"