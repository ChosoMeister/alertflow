"""
Sentinel-AI-Core API Server - Main Application
"""
import logging
import os
from datetime import timedelta
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm

from auth import authenticate_user, create_access_token, get_current_user, User
from config import get_settings
from routes import routing, test_email, alerts, health, logs, integrations, providers, channels
from routes import settings as settings_routes

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("API-Server")

settings = get_settings()

# Create FastAPI app
app = FastAPI(
    title="Sentinel-AI-Core API",
    description="Alert processing system with AI analysis and notification routing",
    version="2.0.0",
)

# CORS middleware
cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix="/api")
app.include_router(routing.router, prefix="/api")
app.include_router(test_email.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(integrations.router, prefix="/api")
app.include_router(providers.router, prefix="/api")
app.include_router(channels.router, prefix="/api")
app.include_router(settings_routes.router)  # settings has its own prefix


@app.post("/api/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticate user and return JWT token."""
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(
        data={"sub": user["username"], "role": user["role"]},
        expires_delta=timedelta(minutes=settings.jwt_expire_minutes)
    )
    
    logger.info(f"User logged in: {user['username']}")
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "username": user["username"],
            "role": user["role"]
        }
    }


@app.get("/api/auth/me")
async def get_current_user_info(user: User = Depends(get_current_user)):
    """Get current user information."""
    return {
        "username": user.username,
        "role": user.role
    }


@app.on_event("startup")
async def startup_event():
    logger.info("Sentinel-AI-Core API Server starting...")
    logger.info(f"API running on {settings.api_host}:{settings.api_port}")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Sentinel-AI-Core API Server shutting down...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info"
    )
