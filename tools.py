import os
import re
import json
import subprocess
import uuid
import requests
import winsound
from langchain_core.tools import Tool
from dotenv import load_dotenv
from tkinter import Tk, filedialog


load_dotenv()

GITHUB_PAT = os.getenv("GITHUB_PAT")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_EMAIL = os.getenv("GITHUB_EMAIL")
API_URL = os.getenv("API_URL")


def save_files(code_data: str, base_dir: str) -> str:
    try:
        for item in code_data:
            # Remove leading slashes to ensure relative path
            rel_path = item["file_path"].lstrip("/\\")
            # Normalize and build final path
            path = os.path.normpath(os.path.join(base_dir, rel_path))

            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(item["content"])
        return "Files saved successfully."
    except Exception as e:
        print_error(f"Error saving files: {str(e)}")
        return f"Error saving files: {str(e)}"


def extract_preview_plan(text):
    # Find all matches for 'Pages' and 'Features'
    pattern = r"## (Pages|Features)(.*?)(?=\n## |\Z)"
    matches = re.findall(pattern, text, re.DOTALL)

    # Use a dictionary to store only the latest occurrence
    latest_sections = {}
    for header, content in matches:
        latest_sections[header] = content.strip()

    # Reconstruct the result in the order: Pages, then Features (if they exist)
    result = ""
    if "Pages" in latest_sections:
        result += f"## Pages\n{latest_sections['Pages']}\n\n"
    if "Features" in latest_sections:
        result += f"## Features\n{latest_sections['Features']}\n"

    return result.strip()


def check_website(link: str, dir_name: str) -> list:
    try:
        hit = requests.get(link)

        response = requests.get(f"{API_URL}/logs/{dir_name}")
        response.raise_for_status()

        logs = response.json()["stdout"]
        logs += "\n\n" + response.json()["stderr"]

        print_info(f"Status code: {hit.status_code}")

        return [
            0 if int(hit.status_code) < 300 else 1,
            f"These are the server logs: {logs}",
        ]
    except Exception as e:
        response = requests.get(f"{API_URL}/logs/{dir_name}")
        response.raise_for_status()

        logs = response.json()["stdout"]
        logs += "\n\n" + response.json()["stderr"]

        print_error(str(e))

        return [1, logs]


def start_server(dir_name: str) -> object:
    try:
        print_info(f"Attempting to start server for directory: {dir_name}")
        print_info(f"API URL: {API_URL}/execute_codebase")

        # Add timeout and better error handling
        response = requests.post(
            f"{API_URL}/execute_codebase",
            data={"dir_name": dir_name},
            timeout=30,  # Add timeout
            headers={
                "Content-Type": "application/x-www-form-urlencoded"
            },  # Explicit content type
        )

        print_info(f"Response status code: {response.status_code}")
        print_info(f"Response headers: {dict(response.headers)}")

        # Log response content for debugging
        try:
            response_json = response.json()
            print_info(f"Response JSON: {json.dumps(response_json, indent=2)}")
        except:
            print_info(f"Response text: {response.text}")

        response.raise_for_status()
        return response_json

    except requests.exceptions.Timeout:
        error_msg = f"Request timed out after 30 seconds"
        print_error(error_msg)
        return error_msg

    except requests.exceptions.ConnectionError as e:
        error_msg = f"Connection error - API server might be down: {e}"
        print_error(error_msg)
        return error_msg

    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP Error {response.status_code}: {response.text}"
        print_error(error_msg)
        return error_msg

    except requests.exceptions.RequestException as e:
        error_msg = f"Request failed: {e}"
        print_error(error_msg)
        return error_msg

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        print_error(error_msg)
        return error_msg


def select_images():
    root = Tk()
    root.withdraw()  # Hide main window
    root.call("wm", "attributes", ".", "-topmost", True)  # Bring dialog to front

    file_paths = filedialog.askopenfilenames(
        title="Select image(s) to upload",
        filetypes=[("Image files", "*.png *.jpg *.jpeg *.ico *.gif *.bmp *.webp")],
    )
    root.destroy()  # Properly close the Tk instance
    return file_paths


def upload_images():
    file_paths = select_images()
    if not file_paths:
        print_error("No images selected.")
        return

    responses = []

    for idx, path in enumerate(file_paths, start=1):
        with open(path, "rb") as f:
            files = {"file": (os.path.basename(path), f, "image/x-icon")}
            data = {"tag": f"image_{idx}"}

            response = requests.post(
                f"{API_URL}/upload_image",
                files=files,
                data=data,
                headers={"accept": "application/json"},
            )

            try:
                res_data = response.json()
            except Exception:
                res_data = response.text

            res_data["filename"] = os.path.basename(path)
            responses.append(res_data)

    return responses


def rollback_server(dir_name: str, commit_id: str) -> str:
    try:
        response = requests.post(
            f"{API_URL}/rollback_server",
            data={"dir_name": dir_name, "commit_id": commit_id},
        )
        response.raise_for_status()
        return f"Rollback successful: {response.json()}"
    except requests.exceptions.RequestException as e:
        return f"Failed to rollback server: {e}"


def stop_server(dir_name: str) -> str:
    try:
        response = requests.post(f"{API_URL}/stop_process", data={"dir_name": dir_name})
        response.raise_for_status()
        return f"Server stopped: {response.json()}"
    except requests.exceptions.RequestException as e:
        return f"Failed to stop server: {e}"


def init_git_repo() -> str:
    base_dir = os.path.join(os.getcwd(), "tempo")
    os.makedirs(base_dir, exist_ok=True)
    try:
        if not os.path.exists(os.path.join(base_dir, ".git")):
            subprocess.run(["git", "init"], cwd=base_dir, check=True)
            subprocess.run(
                ["git", "config", "user.email", GITHUB_EMAIL],
                cwd=base_dir,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", GITHUB_USERNAME],
                cwd=base_dir,
                check=True,
            )
        return base_dir
    except subprocess.CalledProcessError as e:
        print_error(f"Error initializing Git repository: {str(e)}")
        return base_dir


def rollback_codebase(base_dir: str, commit_id: str):
    try:
        subprocess.run(
            ["git", "checkout", commit_id, "--", "."], cwd=base_dir, check=True
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git checkout failed: {e}")

    # Step 2: Traverse the repository and collect file contents
    file_dicts = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            file_path = os.path.join(root, file)

            # Skip hidden files and .git directory
            if ".git" in file_path or file.startswith("."):
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                file_dicts.append(
                    {
                        "file_path": os.path.relpath(file_path, base_dir),
                        "content": content,
                    }
                )
            except Exception as e:
                print(f"Could not read file {file_path}: {e}")

    return file_dicts


def commit_changes(
    base_dir: str, message: str = "Update code", repo_name: str = ""
) -> str:
    try:
        subprocess.run(["git", "add", "."], cwd=base_dir, check=True)
        subprocess.run(["git", "commit", "-m", message[:256]], cwd=base_dir, check=True)

        # Get the latest commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=base_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        commit_id = result.stdout.strip()

        repo_name = push_to_github(base_dir, repo_name)
        return commit_id, repo_name
    except subprocess.CalledProcessError as e:
        print_error(f"Error committing changes: {str(e)}")
        return f"Error committing changes: {str(e)}", None


def process_url(url: str) -> str:
    url = url.rstrip("/")

    print_error(url)

    # Insert PAT
    parts = url.split("https://github.com/")
    final_url = f"https://{GITHUB_USERNAME}:{GITHUB_PAT}@github.com/{parts[1]}"

    return final_url


def create_github_repo(repo_prefix: str = "tempo") -> str:
    repo_name = f"{repo_prefix}-{uuid.uuid4().hex[:8]}"
    url = "https://api.github.com/user/repos"

    headers = {
        "Authorization": f"token {GITHUB_PAT}",
        "Accept": "application/vnd.github+json",
    }
    data = {"name": repo_name, "private": False, "auto_init": False}
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 201:
        print_success(f"Created GitHub repo: {repo_name}")
        return f"https://github.com/{GITHUB_USERNAME}/{repo_name}.git", repo_name
    else:
        print_error(f"GitHub API error: {response.status_code} - {response.text}")
        raise Exception(f"GitHub API error: {response.status_code} - {response.text}")


def push_to_github(base_dir: str, repo_name: str = "") -> str:
    try:
        # Check if a remote already exists
        result = subprocess.run(
            ["git", "remote"], cwd=base_dir, capture_output=True, text=True, check=True
        )
        remotes = result.stdout.strip().split()

        if remotes:
            # Remote exists — use it
            remote_name = remotes[0]
            result = subprocess.run(
                ["git", "remote", "get-url", remote_name],
                cwd=base_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            remote_url = result.stdout.strip()
            permission_url = process_url(remote_url)
            subprocess.run(
                ["git", "push", "-u", permission_url, "main"], cwd=base_dir, check=True
            )
            return repo_name
        else:
            # No remote — create GitHub repo and push
            remote_url = create_github_repo()
            permission_url = process_url(remote_url[0])
            remote_name = "origin"
            subprocess.run(
                ["git", "remote", "add", remote_name, remote_url[0]],
                cwd=base_dir,
                check=True,
            )
            subprocess.run(["git", "branch", "-M", "main"], cwd=base_dir, check=True)
            subprocess.run(
                ["git", "push", "-u", permission_url, "main"], cwd=base_dir, check=True
            )
            return remote_url[1]
    except subprocess.CalledProcessError as e:
        print_error(f"Git error: {e}")
        return None
    except Exception as e:
        print_error(str(e))
        return None


def print_error(str):
    print("\033[91m" + str + "\033[0m")


def print_success(str):
    print("\033[92m" + str + "\033[0m")


def print_info(text):
    print("\033[94m" + text + "\033[0m")


def print_warning(str):
    print("\033[93m" + str + "\033[0m")


def batch_files(file_paths, batch_size):
    batches = (len(file_paths) + batch_size - 1) // batch_size
    for i in range(0, len(file_paths), batch_size):
        yield f"{(i // batch_size) + 1}/{batches}", file_paths[i : i + batch_size]


def ask_user_input(prompt: str) -> str:
    winsound.Beep(500, 500)  # remove in production
    print("\nAgent needs your input:")
    print(f"> {prompt}")
    return input(">>> Your input: ").strip()


ask_user_input_tool = Tool(
    name="ask_user_input",
    func=ask_user_input,
    description="Ask the human for a missing detail. Takes a prompt string like 'What is the desired frontend framework?'",
)
