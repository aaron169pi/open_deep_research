import os
import subprocess


def save_files(code_data: str, base_dir: str) -> str:
    try:
        for item in code_data:
            path = os.path.join(base_dir, item["file_path"])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(item["content"])
        return "Files saved successfully."
    except Exception as e:
        print_error(f"Error saving files: {str(e)}")
        return f"Error saving files: {str(e)}"


def init_git_repo() -> str:
    base_dir = os.path.join(os.getcwd(), "tempo")
    os.makedirs(base_dir, exist_ok=True)
    try:
        if not os.path.exists(os.path.join(base_dir, ".git")):
            subprocess.run(["git", "init"], cwd=base_dir, check=True)
            subprocess.run(
                ["git", "config", "user.email", "you@example.com"],
                cwd=base_dir,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Your Name"], cwd=base_dir, check=True
            )
        return base_dir
    except subprocess.CalledProcessError as e:
        print_error(f"Error initializing Git repository: {str(e)}")
        return base_dir


def commit_changes(base_dir: str, message: str = "Update code") -> str:
    try:
        subprocess.run(["git", "add", "."], cwd=base_dir, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=base_dir, check=True)
        return "Changes committed successfully."
    except subprocess.CalledProcessError as e:
        print_error(f"Error committing changes: {str(e)}")
        return f"Error committing changes: {str(e)}"


def print_error(str):
    print("\033[91m" + str + "\033[0m")


def print_success(str):
    print("\033[92m" + str + "\033[0m")


def print_info(text):
    print("\033[94m" + text + "\033[0m")


def batch_files(file_paths, batch_size):
    for i in range(0, len(file_paths), batch_size):
        yield file_paths[i : i + batch_size]
