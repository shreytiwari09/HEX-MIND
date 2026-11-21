from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.a2a.client import CrewServiceProcess, a2a_http_client
from app.agents import store as persona_store
from app.api import (
    a2a,
    apps,
    assignments,
    audit,
    budgets,
    catalog,
    connections,
    conversations,
    experiments,
    handoff,
    health,
    metrics,
    missions,
    personas,
    plugins,
    projects,
    provenance,
    providers,
    research,
    runs,
    scoping,
    skills,
    stream,
    tasks,
    traces,
    variants,
)
from app.auth import require_token
from app.catalog.service import CatalogService
from app.chat.service import ChatService
from app.config import Settings, get_settings
from app.context.manager import ContextManager
from app.db.session import create_engine, create_sessionmaker
from app.events.hub import EventHub
from app.memory.store import Memory, OllamaEmbedding
from app.missions.cleanup import clean_finished_worktrees
from app.missions.recovery import pause_interrupted_missions
from app.orchestration.background import BackgroundTasks
from app.orchestration.services import Services
from app.preview.app_runner import AppRunner
from app.providers.factory import build_providers
from app.providers.secrets import make_key_store
from app.telemetry.tracing import setup_tracing


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_tracing(settings)
    engine = create_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)
    keystore = make_key_store(settings.key_store)
    model_catalog = CatalogService(settings.data_dir / "catalog")
    providers_router, adapters = build_providers(settings, sessionmaker, keystore, model_catalog)
    memory = None
    if settings.memory_enabled:
        memory = Memory(
            settings.data_dir / "chroma",
            OllamaEmbedding(settings.ollama_url, settings.embedding_model),
        )
    services = Services(
        settings=settings,
        sessionmaker=sessionmaker,
        providers=providers_router,
        context=ContextManager(settings.context_budget_tokens),
        background=BackgroundTasks(),
        memory=memory,
        a2a_http=a2a_http_client(settings),
        keystore=keystore,
        catalog=model_catalog,
    )
    crew_service = CrewServiceProcess(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with sessionmaker() as session:
            await persona_store.refresh(session)  # the user's edited and custom personas
        await pause_interrupted_missions(services)  # a mission cannot run without its runner
        services.background.spawn(clean_finished_worktrees(services), name="worktree-cleanup")
        if settings.catalog_auto_refresh:
            services.background.spawn(model_catalog.refresh_if_stale(), name="catalog-refresh")
        if settings.crew_service_autostart:
            await crew_service.start(services.a2a_http)
        yield
        await app.state.apps.stop_all()  # an app never outlives the backend
        await services.background.cancel_all()
        await app.state.event_hub.stop()
        crew_service.stop()
        await services.a2a_http.aclose()
        for adapter in adapters:
            await adapter.aclose()
        await engine.dispose()

    app = FastAPI(title="H.E.X Mind Backend", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.services = services
    app.state.provider_router = services.providers
    services.apps = AppRunner(settings.sandbox_images)  # apps the user runs (D71)
    app.state.apps = services.apps
    app.state.chat = ChatService(services, app.state.apps)
    app.state.event_hub = EventHub(settings.database_url)

    @app.exception_handler(RequestValidationError)
    async def validation_failed(_: Request, exc: RequestValidationError) -> JSONResponse:
        """FastAPI's default answer repeats the request body in each error's `input`. A body can
        carry an API key, so only where and why a field is wrong is sent back."""
        errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    for module in (
        health,
        projects,
        handoff,
        runs,
        providers,
        conversations,
        tasks,
        a2a,
        missions,
        connections,
        personas,
        assignments,
        budgets,
        catalog,
        scoping,
        skills,
        plugins,
        variants,
        audit,
        traces,
        provenance,
        metrics,
        experiments,
        research,
        apps,
    ):
        app.include_router(module.router, prefix="/api", dependencies=[Depends(require_token)])
    app.include_router(missions.needs_router, prefix="/api", dependencies=[Depends(require_token)])
    app.include_router(
        connections.types_router, prefix="/api", dependencies=[Depends(require_token)]
    )
    app.include_router(stream.router)  # authenticates by its first frame, not a header
    return app
