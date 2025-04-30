import asyncio
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from datetime import datetime, timedelta
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import BaseModel

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://srharshitcode.github.io"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://jprjnqyjicyvgftkkrou.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpwcmpucXlqaWN5dmdmdGtrcm91Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDYwMjYxNzIsImV4cCI6MjA2MTYwMjE3Mn0.CK0sgXbWD2unY-dggd7mwT0DRHKZoyCnfzqxVgaB2O0")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Store active WebSocket connections
connected_clients = {}

# Create a scheduler for periodic cleanup
scheduler = AsyncIOScheduler()

async def cleanup_old_data():
    """Delete users and messages older than 30 minutes"""
    try:
        thirty_minutes_ago = datetime.utcnow() - timedelta(minutes=30)
        # Delete inactive users
        supabase.table("users").delete().lt("last_active", thirty_minutes_ago.isoformat()).execute()
        # Delete old messages
        supabase.table("messages").delete().lt("timestamp", thirty_minutes_ago.isoformat()).execute()
        print("Cleaned up old data")
    except Exception as e:
        print(f"Error during cleanup: {e}")

@app.on_event("startup")
async def startup_event():
    # Schedule cleanup every 5 minutes
    scheduler.add_job(cleanup_old_data, "interval", minutes=5)
    scheduler.start()

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    connected_clients[user_id] = websocket
    try:
        # Update user's last_active timestamp
        supabase.table("users").update({"last_active": datetime.utcnow().isoformat()}).eq("user_id", user_id).execute()
        # Get username for notifications
        user_data = supabase.table("users").select("username").eq("user_id", user_id).execute()
        username = user_data.data[0]["username"] if user_data.data else "Unknown"
        # Notify others of user joining
        for client_ws in connected_clients.values():
            await client_ws.send_text(f"{username} has joined the chat")
        while True:
            data = await websocket.receive_text()
            # Save message to Supabase
            message_data = {
                "user_id": user_id,
                "message": data,
                "timestamp": datetime.utcnow().isoformat()
            }
            supabase.table("messages").insert(message_data).execute()
            # Broadcast message with username
            for client_id, client_ws in connected_clients.items():
                await client_ws.send_text(f"{username}: {data}")
    except WebSocketDisconnect:
        del connected_clients[user_id]
        # Get username for notifications
        user_data = supabase.table("users").select("username").eq("user_id", user_id).execute()
        username = user_data.data[0]["username"] if user_data.data else "Unknown"
        # Notify others of user leaving
        for client_ws in connected_clients.values():
            await client_ws.send_text(f"{username} has left the chat")
    except Exception as e:
        print(f"Error: {e}")

class UserCreate(BaseModel):
    username: str

@app.post("/create_user")
async def create_user(user: UserCreate):
    user_id = str(uuid.uuid4())
    user_data = {
        "user_id": user_id,
        "username": user.username,
        "last_active": datetime.utcnow().isoformat()
    }
    supabase.table("users").insert(user_data).execute()
    return {"user_id": user_id, "username": user.username}

@app.get("/")
async def get():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
        <head>
            <title>Chat App Backend</title>
        </head>
        <body>
            <h1>WebSocket Chat Backend</h1>
            <p>Connect to the frontend hosted on GitHub Pages.</p>
        </body>
    </html>
    """)
