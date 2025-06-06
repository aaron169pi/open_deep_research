from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
import json


app = FastAPI()

# Placeholder HTML content
placeholder = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Preparing Website</title>
  <style>
    body {
      margin: 0;
      font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
      background: linear-gradient(135deg, #667eea, #764ba2);
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100vh;
      color: white;
      text-align: center;
      animation: fadeIn 1.2s ease-in-out;
    }
    h1 {
      font-size: 2.5rem;
      background: rgba(255, 255, 255, 0.1);
      padding: 1rem 2rem;
      border-radius: 12px;
      box-shadow: 0 10px 20px rgba(0, 0, 0, 0.2);
      backdrop-filter: blur(6px);
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(30px); }
      to { opacity: 1; transform: translateY(0); }
    }
  </style>
</head>
<body>
  <h1>Your website is being prepared...</h1>
</body>
</html>
"""

# Store the uploaded content, or None if nothing posted yet
latest_html_text: str | None = None


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/data", response_class=PlainTextResponse)
async def get_latest_html():
    return latest_html_text or placeholder

@app.post("/")
async def update_html(request: Request):
    global latest_html_text
    html_text = await request.body()
    latest_html_text = html_text.decode("utf-8")
    return {"status": "HTML updated successfully"}
