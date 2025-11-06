# from pydantic_settings import BaseSettings, SettingsConfigDict
# from pydantic import AnyHttpUrl, Field
# from typing import List, Optional


# class Settings(BaseSettings):
#     model_config = SettingsConfigDict(
#         env_file=".env",
#         env_file_encoding="utf-8",
#         extra="ignore",  # 알 수 없는 키 무시(선택)
#     )

#     AGENT_MODEL: str = Field(default="gpt-4o-2024-08-06")

#     APP_ENV: str = "local"
#     APP_NAME: str = "VoicePhish Sim"
#     API_PREFIX: str = "/api"

#     CORS_ORIGINS: List[AnyHttpUrl] = []

#     # 1) 있으면 이 값을 **최우선 사용**
#     DATABASE_URL: Optional[str] = None

#     # 2) 없으면 아래 값으로 DSN 조합
#     POSTGRES_HOST: str = "localhost"
#     POSTGRES_PORT: int = 5432
#     POSTGRES_DB: str = "voicephish"
#     POSTGRES_USER: str = "vpuser"
#     POSTGRES_PASSWORD: str = "0320"
#     SYNC_ECHO: bool = False

#     # Keys
#     OPENAI_API_KEY: str | None = None
#     GOOGLE_API_KEY: str | None = None  # 피해자를 Gemini로 전환할 때 필요

#     # 역할별 모델명
#     ATTACKER_MODEL: str = "gpt-4.1-mini"
#     VICTIM_MODEL: str = "gpt-4.1-mini"
#     ADMIN_MODEL: str = "gpt-4.1-mini"

#     # 피해자 프로바이더 선택: "openai" | "gemini"
#     VICTIM_PROVIDER: str = "openai"

#     # 턴 제한
#     MAX_OFFENDER_TURNS: int = 10
#     MAX_VICTIM_TURNS: int = 10
#     # ... 기존 ...
#     # MCP
#     USE_MCP: bool = True
#     MCP_TRANSPORT: str = "http"  # "http" | "ws"
#     MCP_HTTP_URL: str = "http://localhost:5173/mcp/simulator.run"
#     MCP_WS_URL: str = "ws://localhost:5173/mcp"
#     MAX_AGENT_ITER: int = 5
#     MCP_WEBSOCKET_URL: str = "ws://localhost:8000/mcp/ws"

#     # LLM(Local/OpenAI)
#     ATTACKER_PROVIDER: str = "openai"  # "openai" | "local"
#     VICTIM_PROVIDER: str = "openai"  # "openai" | "gemini" | "local"
#     LOCAL_BASE_URL: str | None = None
#     LOCAL_API_KEY: str = "not-needed"

#     # Web search
#     ENABLE_WEB_SEARCH: bool = True
#     WEBCTX_PROVIDER: str = "tavily"  # "tavily" | "none"
#     TAVILY_API_KEY: str | None = None

#     # LangSmith / LangChain tracing
#     LANGCHAIN_TRACING_V2: bool = True
#     LANGCHAIN_API_KEY: str | None = None
#     LANGCHAIN_PROJECT: str = "voice-phishing-sim"

#     @property
#     def sync_dsn(self) -> str:
#         if self.DATABASE_URL:  # ← .env에 있으면 그걸 사용
#             return self.DATABASE_URL
#         return (
#             f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
#             f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}")

#     @property
#     def sqlalchemy_url(self) -> str:
#         return self.sync_dsn

#     @property
#     def OPENAI_MODEL(self) -> str:
#         # 기존 코드가 settings.OPENAI_MODEL을 찾을 때 ADMIN_MODEL을 돌려줌
#         return self.ADMIN_MODEL


# settings = Settings()  # type: ignore


from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, Field
from typing import List, Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 알 수 없는 키 무시
    )

    # ── App ─────────────────────────────────────────
    APP_ENV: str = "local"
    APP_NAME: str = "VoicePhish Sim"
    API_PREFIX: str = "/api"
    CORS_ORIGINS: List[AnyHttpUrl] = []

    # ── Database ────────────────────────────────────
    # 1) 있으면 이 값을 **최우선 사용**
    DATABASE_URL: Optional[str] = None
    # 2) 없으면 아래 값으로 DSN 조합
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "voicephish"
    POSTGRES_USER: str = "vpuser"
    POSTGRES_PASSWORD: str = "0320"
    SYNC_ECHO: bool = False

    # ── Keys ────────────────────────────────────────
    OPENAI_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None  # (필수) Gemini 사용

    # ── 모델 기본값 (모두 Gemini 계열로 기본 설정) ─────────────
    AGENT_MODEL: str = Field(default="gemini-1.5-pro")
    ATTACKER_MODEL: str = "gemini-2.5-flash-lite"
    VICTIM_MODEL: str = "gemini-2.5-flash-lite"
    ADMIN_MODEL: str = "gemini-1.5-pro"

    # (선택) 임시 강제 전환 플래그. 지금은 전부 Gemini라 사용 안 함.
    FORCE_GEMINI: int | bool = 1

    # ── 턴 제한 ─────────────────────────────────────
    MAX_OFFENDER_TURNS: int = 10
    MAX_VICTIM_TURNS: int = 10

    # ── MCP ────────────────────────────────────────
    USE_MCP: bool = True
    MCP_TRANSPORT: str = "http"  # "http" | "ws"
    MCP_HTTP_URL: str = "http://localhost:5173/mcp/simulator.run"
    MCP_WS_URL: str = "ws://localhost:5173/mcp"
    MAX_AGENT_ITER: int = 5
    MCP_WEBSOCKET_URL: str = "ws://localhost:8000/mcp/ws"

    # ── LLM(Local/OpenAI) ──────────────────────────
    # 현재는 전부 Gemini이므로 provider는 사용하지 않지만, 추후 확장 대비로 남김
    AGENT_PROVIDER: str = "gemini"
    ATTACKER_PROVIDER: str = "gemini"
    VICTIM_PROVIDER: str = "gemini"
    ADMIN_PROVIDER: str = "gemini"
    LOCAL_BASE_URL: str | None = None
    LOCAL_API_KEY: str = "not-needed"

    # ── Web search ─────────────────────────────────
    ENABLE_WEB_SEARCH: bool = True
    WEBCTX_PROVIDER: str = "tavily"  # "tavily" | "none"
    TAVILY_API_KEY: str | None = None

    # ── LangSmith / LangChain tracing ──────────────
    LANGCHAIN_TRACING_V2: bool = True
    LANGCHAIN_API_KEY: str | None = None
    LANGCHAIN_PROJECT: str = "voice-phishing-sim"

    @property
    def sync_dsn(self) -> str:
        if self.DATABASE_URL:  # ← .env에 있으면 그걸 사용
            return self.DATABASE_URL
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sqlalchemy_url(self) -> str:
        return self.sync_dsn

    @property
    def OPENAI_MODEL(self) -> str:
        # 레거시 코드 호환: OPENAI_MODEL을 찾으면 ADMIN_MODEL 반환
        return self.ADMIN_MODEL


settings = Settings()  # type: ignore
