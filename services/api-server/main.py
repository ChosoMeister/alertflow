"""
AlertFlow API Server - Main Application
"""
import logging
import os
from datetime import timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm

from auth import authenticate_user, create_access_token, get_current_user, User
from config import get_settings
from routes import routing, test_email, alerts, health, logs, integrations, providers, channels, sse, analytics, webhook
from routes import settings as settings_routes

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("API-Server")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    logger.info("AlertFlow API Server starting...")
    logger.info(f"API running on {settings.api_host}:{settings.api_port}")
    yield
    logger.info("AlertFlow API Server shutting down...")


# Create FastAPI app
app = FastAPI(
    title="AlertFlow API",
    description="Alert processing system with AI analysis and notification routing",
    version="2.1.0",
    lifespan=lifespan,
)

# CORS middleware
cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]
cors_allows_credentials = "*" not in cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_allows_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix="/api")
app.include_router(routing.router, prefix="/api")
app.include_router(routing.profiles_router, prefix="/api")
app.include_router(test_email.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(integrations.router, prefix="/api")
app.include_router(providers.router, prefix="/api")
app.include_router(channels.router, prefix="/api")
app.include_router(sse.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(webhook.router, prefix="/api")
app.include_router(settings_routes.router)  # settings has its own prefix


@app.post("/api/auth/login")
async def login(response: Response, form_data: OAuth2PasswordRequestForm = Depends()):
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

    cookie_secure = os.getenv("COOKIE_SECURE", "true").lower() in {"1", "true", "yes", "on"}
    response.set_cookie(
        key="alertflow_session",
        value=access_token,
        httponly=True,
        secure=cookie_secure,
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "username": user["username"],
            "role": user["role"]
        }
    }


@app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    """Expire the browser session cookie. Bearer clients remain stateless."""
    response.delete_cookie(
        key="alertflow_session",
        path="/",
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "true").lower() in {"1", "true", "yes", "on"},
        samesite="lax",
    )


@app.get("/api/auth/me")
async def get_current_user_info(user: User = Depends(get_current_user)):
    """Get current user information."""
    return {
        "username": user.username,
        "role": user.role
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info"
    )
