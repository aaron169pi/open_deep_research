import os
import json
import docker  # pip install docker
from google import genai
from google.genai import types

# Configure Gemini client
GEMINI_MODEL = "gemini-1.5-pro"
GEMINI_API_KEY = "AIzaSyCNUfDMpVGjvAV4YVMK0pCVnvXWcyVwW9Q"

client = genai.Client(api_key=GEMINI_API_KEY)

# Static prompt template
PROMPT_TEMPLATE = """
You are a project code generator. Please output a JSON object with a "files" array. Each item in this array should be an object containing:
- "path": the file's relative path (e.g., "src/App.js", "public/index.html", "app/main.py", "styles/style.css", "Dockerfile", "pom.xml")
- "content": the complete content of the file as a string

Guidelines:
1. The project can be of any type or language (e.g., Python, React, Streamlit, Java, HTML/CSS, etc.).
2. The project must be **complete, functional, and immediately runnable**.
   - Every file must contain **full, working code** — no placeholders, stubs, or incomplete logic.
   - No "TODO" comments or partial implementations.
3. Include **all required files** for a self-contained project:
   - Application source code
   - Dependency declarations (e.g., "requirements.txt", "package.json", "pom.xml")
   - Static assets (if applicable)
   - Entry points and routing (if applicable)
4. Always include a **Dockerfile** to run the project in a **safe, isolated, and reproducible environment**.
   - The Dockerfile must install all dependencies, copy necessary files, run the application, and
     **EXPOSE the correct port** used by the app (e.g., 8501 for Streamlit, 3000 for React, 8000 for FastAPI).
5. **All required dependencies must be explicitly listed** (e.g., in "requirements.txt", "package.json", etc.), so the application runs without any missing modules or packages.
6. Use the correct directory structure in all file paths (e.g., "src/", "app/", "public/").
7. Ensure every "content" field is a **fully valid and idiomatic implementation** for its file type and framework.
8. The output JSON must be syntactically valid, properly escaped, and ready for use in automation.

Expected output format:
{
  "files": [
    {
      "path": "app/main.py",
      "content": "# Complete, working Python code here..."
    },
    {
      "path": "requirements.txt",
      "content": "streamlit==1.33.0\\nnumpy==1.24.2"
    },
    {
      "path": "Dockerfile",
      "content": "FROM python:3.10\\nWORKDIR /app\\nCOPY . .\\nRUN pip install -r requirements.txt\\nEXPOSE 8501\\nCMD [\\"streamlit\\", \\"run\\", \\"app/main.py\\"]"
    }
  ]
}
"""

def generate_codebase(user_prompt: str) -> dict:
    """
    Call the Gemini API to generate a JSON listing of files.
    """
    full_prompt = PROMPT_TEMPLATE + "\n\n" + user_prompt
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=full_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    print("==================================\n\n\n",  response.text, "\n\n\n==================================\n\n\n")
    return json.loads(response.text)

def write_files(build_dir: str, files: list[dict]):
    """
    Write each file in the JSON spec to disk under build_dir.
    """
    for file in files:
        path = os.path.join(build_dir, file["path"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(file["content"])

def build_image(build_dir: str, tag: str):
    """
    Build a Docker image from build_dir, returns the image object.
    """
    print("Building Docker image...")
    client = docker.from_env()
    image, logs = client.images.build(path=build_dir, tag=tag)
    for chunk in logs:
        if 'stream' in chunk:
            print(chunk['stream'], end="")
    return image

def get_exposed_ports(image_tag):
    client = docker.from_env()
    image = client.images.get(image_tag)
    exposed_ports = image.attrs['Config'].get('ExposedPorts', {})
    return list(exposed_ports.keys())


def run_container(image_tag):
    """
    Run the specified Docker image, mapping one of its exposed ports to host port 5000.
    """
    print("Running container...")
    client = docker.from_env()
    exposed_ports = get_exposed_ports(image_tag)

    if not exposed_ports:
        raise ValueError(f"No exposed ports found in image '{image_tag}'.")

    # Select the first exposed port
    container_port = exposed_ports[0]

    # Map the selected container port to host port 5000
    ports = {container_port: 5000}

    container = client.containers.run(
        image_tag,
        detach=True,
        ports=ports
    )

    print(f"Container is running. Access the application at http://localhost:5000")

    # for line in container.logs(stream=True):
    #     print(line.decode(), end="")

    # exit_code = container.wait()["StatusCode"]
    # print(f"Container exited with {exit_code}")
    # return exit_code

def orchestrate(prompt: str, image_tag="generated_app:latest"):
    # 1. Generate code spec
    spec = generate_codebase(prompt)
    # 2. Prepare build context
    build_dir = os.getcwd()
    try:
        write_files(build_dir, spec["files"])
        # 3. Build Docker image
        build_image(build_dir, image_tag)
        # 4. Run container
        run_container(image_tag)
    finally:
        # shutil.rmtree(build_dir)
        print('Temporary files have been deleted')

if __name__ == "__main__":
    user_prompt = (
        "Create a website for me to have stats for cricket"
        "Make sure it is a good website with great UI and i can easily use it"
        "Also be sure to include css to style the website in a wonderful manner"
        "build using react please and make sure the ui is vibrant"
        # "Create a streamlit app that is very diverse and has all types of conversions. "
        # "Include distance, weight, sound, volume, money, bmi and other conversions. "
        # "Make sure that it is a menu based systems. "
        # "Only one selection should be displayed at a time. "
        # "A minimum of 10 different menu selections for various quantities should be present. "
    )
    orchestrate(user_prompt)