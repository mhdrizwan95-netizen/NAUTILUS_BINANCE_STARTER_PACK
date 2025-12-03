import os
import sys

def fix_ops_api():
    """Overwrites ops/ops_api.py with a robust FastAPI application."""
    content = r'''"""Ops API for serving Command Center and handling governance."""

import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

APP = FastAPI(title="Nautilus Ops", version="0.1.0")

# CORS
APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@APP.get("/health")
@APP.get("/readyz")
@APP.get("/livez")
async def health_check():
    return {"status": "ok", "service": "ops"}

# Resilient Static File Serving
# We check multiple candidate locations for the frontend build.
CANDIDATE_PATHS = [
    "/app/frontend/build",
    "/app/frontend/dist",
    os.path.join(os.path.dirname(__file__), "static_ui"),
    "static_ui",
]

static_dir = None
for path in CANDIDATE_PATHS:
    if os.path.exists(path) and os.path.isdir(path):
        static_dir = path
        break

if static_dir:
    print(f"INFO: Serving static UI from {static_dir}")
    APP.mount("/", StaticFiles(directory=static_dir, html=True), name="static_ui")
else:
    print("WARNING: No static UI directory found. Serving maintenance page.")
    
    @APP.get("/")
    async def root():
        return HTMLResponse("""
        <html>
            <head><title>Nautilus Maintenance</title></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                <h1>Nautilus Ops Service</h1>
                <p>The Command Center UI is currently unavailable.</p>
                <p><em>Frontend build not found in candidate paths.</em></p>
            </body>
        </html>
        """)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(APP, host="0.0.0.0", port=8002)
'''
    os.makedirs("ops", exist_ok=True)
    with open("ops/ops_api.py", "w") as f:
        f.write(content)
    print("✅ Overwrote ops/ops_api.py")

def fix_docker_compose():
    """Updates docker-compose.yml to mount the frontend build directory."""
    file_path = "docker-compose.yml"
    if not os.path.exists(file_path):
        print(f"❌ {file_path} not found.")
        return

    with open(file_path, "r") as f:
        lines = f.readlines()

    new_lines = []
    in_ops = False
    in_volumes = False
    volume_added = False
    
    # Simple state machine to find ops service and its volumes
    for line in lines:
        stripped = line.strip()
        
        # Detect start of ops service
        if stripped == "ops:":
            in_ops = True
            in_volumes = False # Reset volumes state
        elif in_ops and stripped.startswith("services:") or (line.startswith("  ") and not line.startswith("    ") and stripped != "ops:"):
            # Exiting ops service block (next service or top level key)
            in_ops = False
            in_volumes = False

        # Detect volumes block within ops
        if in_ops and stripped == "volumes:":
            in_volumes = True
            new_lines.append(line)
            continue

        # Add the volume if we are in the volumes block and haven't added it yet
        if in_volumes and not volume_added:
            # Check if we are still in the volumes list (indented)
            if line.startswith("    -"):
                # Check if already present
                if "./frontend/build:/app/frontend/build:ro" in line:
                    volume_added = True
            else:
                # End of volumes list, insert ours before this line
                new_lines.append("    - ./frontend/build:/app/frontend/build:ro\n")
                volume_added = True
                in_volumes = False # Done with volumes

        new_lines.append(line)

    # If we finished the file and were in volumes but didn't add (EOF case)
    if in_volumes and not volume_added:
        new_lines.append("    - ./frontend/build:/app/frontend/build:ro\n")

    with open(file_path, "w") as f:
        f.writelines(new_lines)
    print("✅ Updated docker-compose.yml with frontend volume mount")

def fix_frontend_config():
    """Ensures websocket.ts uses token authentication."""
    file_path = "frontend/src/lib/websocket.ts"
    if not os.path.exists(file_path):
        print(f"⚠️ {file_path} not found. Skipping.")
        return

    with open(file_path, "r") as f:
        content = f.read()

    # Replace session with token
    if "session=" in content:
        new_content = content.replace("session=", "token=")
        with open(file_path, "w") as f:
            f.write(new_content)
        print("✅ Patched frontend/src/lib/websocket.ts (session -> token)")
    else:
        print("ℹ️ frontend/src/lib/websocket.ts already correct or pattern not found.")

def main():
    print("🔧 STARTING OPS SERVICE REPAIR...")
    fix_ops_api()
    fix_docker_compose()
    fix_frontend_config()
    print("🚀 REPAIR SCRIPT COMPLETE.")
    print("\nNEXT STEPS:")
    print("1. Run: cd frontend && npm install && npm run build (Locally)")
    print("2. Upload 'frontend/build' to 'lenser:/home/mrzlen/NAUTILUS_BINANCE_STARTER_PACK/frontend/build'")
    print("3. Run: docker compose up -d --build ops")

if __name__ == "__main__":
    main()
