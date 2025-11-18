# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from app.core.config import settings
from app.db.session import engine
from app.db.base import Base

# 기존 라우터들
from app.routers import health, offenders, victims, conversations, admin_cases
from app.routers import conversations_read, simulator as simulator_router
from app.routers import agent as agent_router
from app.routers.personalized import router as personalized_router
from app.routers import react_agent_stream_router
# React Agent 라우터만 추가
from app.routers import react_agent_router
from app.routers import tts_router

#langsmith
import os
from langsmith import Client

# DB 테이블 생성
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=f"{settings.APP_NAME} - React Agent Enhanced",
    version="2.0.0",
    description="보이스피싱 시뮬레이션 플랫폼 with Intelligent React Agent",
    docs_url="/docs",
    openapi_url="/openapi.json",
    redoc_url="/redoc",
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 기존 API 라우터들
app.include_router(health, prefix=settings.API_PREFIX)
app.include_router(offenders, prefix=settings.API_PREFIX)
app.include_router(victims, prefix=settings.API_PREFIX)
app.include_router(conversations, prefix=settings.API_PREFIX)
app.include_router(admin_cases, prefix=settings.API_PREFIX)
app.include_router(personalized_router, prefix="/api")

# 기존 모듈 라우터들
app.include_router(conversations_read.router, prefix=settings.API_PREFIX)
app.include_router(simulator_router.router, prefix=settings.API_PREFIX)
app.include_router(agent_router.router, prefix=settings.API_PREFIX)

# React Agent 시스템 (MCP는 여기서 동적 호출)
app.include_router(react_agent_router.router, prefix=settings.API_PREFIX)

app.include_router(react_agent_stream_router.router, prefix=settings.API_PREFIX)
app.include_router(tts_router.router, prefix=settings.API_PREFIX)




@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "env": settings.APP_ENV,
        "version": "2.0.0",
        "features": {
            "react_agent": True,
            "dynamic_mcp": True,  # 필요시에만 MCP 호출
            "intelligent_simulation": True
        },
        "endpoints": {
            "docs": "/docs",
            "react_agent": f"{settings.API_PREFIX}/react-agent",
            "simulation": f"{settings.API_PREFIX}/react-agent/simulation",
            "tts": f"{settings.API_PREFIX}/tts/synthesize"
        }
    }


@app.get("/health/detailed")
async def detailed_health():
    """상세 헬스체크"""
    try:
        from app.db.session import SessionLocal
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    try:
        from google.cloud import texttospeech
        tts_client = texttospeech.TextToSpeechClient()
        # 간단한 테스트 호출
        voices = tts_client.list_voices()
        tts_status = "healthy"
    except Exception as e:
        tts_status = f"unhealthy: {str(e)}"

    return {
        "status": "healthy",
        "database": db_status,
        "react_agent": "ready",
        "mcp_integration": "on-demand",  # 필요시에만
        "google_tts": tts_status,
        "llm_providers": {
            "attacker_chat": "ready",
            "victim_chat": "ready",
            "agent_chat": "ready"
        }
    }


# 시작 시 로그
@app.on_event("startup")
async def startup_event():
    print(f"🚀 {settings.APP_NAME} v2.0 - React Agent Enhanced")
    print(f"🤖 React Agent: Ready")
    print(f"🔗 MCP: On-demand (호출시에만 시작)")
    print(f"🎵 Google TTS: Ready")
    print(f"📚 API Docs: http://localhost:{8000}/docs")


if __name__ == "__main__":
    import uvicorn
    port = getattr(settings, 'PORT', 8000) or 8000
    uvicorn.run("app.main:app",
                host="0.0.0.0",
                port=port,
                reload=settings.APP_ENV == "development")

# # app/main.py
# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles
# from pathlib import Path

# from app.core.config import settings
# from app.db.session import engine
# from app.db.base import Base

# # 기존 라우터들
# from app.routers import health, offenders, victims, conversations, admin_cases
# from app.routers import conversations_read, simulator as simulator_router
# from app.routers import agent as agent_router
# from app.routers.personalized import router as personalized_router

# # React Agent 라우터만 추가
# from app.routers import react_agent_router

# # DB 테이블 생성
# Base.metadata.create_all(bind=engine)

# app = FastAPI(
#     title=f"{settings.APP_NAME} - React Agent Enhanced",
#     version="2.0.0",
#     description="보이스피싱 시뮬레이션 플랫폼 with Intelligent React Agent",
#     docs_url="/docs",
#     openapi_url="/openapi.json",
#     redoc_url="/redoc",
# )

# # CORS 설정
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # 정적 파일 서빙
# BASE_DIR = Path(__file__).resolve().parent
# STATIC_DIR = BASE_DIR / "static"
# if STATIC_DIR.exists():
#     app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# # 기존 API 라우터들
# app.include_router(health, prefix=settings.API_PREFIX)
# app.include_router(offenders, prefix=settings.API_PREFIX)
# app.include_router(victims, prefix=settings.API_PREFIX)
# app.include_router(conversations, prefix=settings.API_PREFIX)
# app.include_router(admin_cases, prefix=settings.API_PREFIX)
# app.include_router(personalized_router, prefix="/api")

# # 기존 모듈 라우터들
# app.include_router(conversations_read.router, prefix=settings.API_PREFIX)
# app.include_router(simulator_router.router, prefix=settings.API_PREFIX)
# app.include_router(agent_router.router, prefix=settings.API_PREFIX)

# # React Agent 시스템 (MCP는 여기서 동적 호출)
# app.include_router(react_agent_router.router, prefix=settings.API_PREFIX)


# @app.get("/")
# async def root():
#     return {
#         "name": settings.APP_NAME,
#         "env": settings.APP_ENV,
#         "version": "2.0.0",
#         "features": {
#             "react_agent": True,
#             "dynamic_mcp": True,  # 필요시에만 MCP 호출
#             "intelligent_simulation": True
#         },
#         "endpoints": {
#             "docs": "/docs",
#             "react_agent": f"{settings.API_PREFIX}/react-agent",
#             "simulation": f"{settings.API_PREFIX}/react-agent/simulation"
#         }
#     }


# @app.get("/health/detailed")
# async def detailed_health():
#     """상세 헬스체크"""
#     try:
#         from app.db.session import SessionLocal
#         db = SessionLocal()
#         db.execute("SELECT 1")
#         db.close()
#         db_status = "healthy"
#     except Exception as e:
#         db_status = f"unhealthy: {str(e)}"

#     return {
#         "status": "healthy",
#         "database": db_status,
#         "react_agent": "ready",
#         "mcp_integration": "on-demand",  # 필요시에만
#         "llm_providers": {
#             "attacker_chat": "ready",
#             "victim_chat": "ready",
#             "agent_chat": "ready"
#         }
#     }


# # 시작 시 로그
# @app.on_event("startup")
# async def startup_event():
#     print(f"🚀 {settings.APP_NAME} v2.0 - React Agent Enhanced")
#     print(f"🤖 React Agent: Ready")
#     print(f"🔗 MCP: On-demand (호출시에만 시작)")
#     print(f"📚 API Docs: http://localhost:{8000}/docs")


# if __name__ == "__main__":
#     import uvicorn
#     port = getattr(settings, 'PORT', 8000) or 8000
#     uvicorn.run("app.main:app",
#                 host="0.0.0.0",
#                 port=port,
#                 reload=settings.APP_ENV == "development")
