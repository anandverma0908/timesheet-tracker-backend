"""
app/api/router.py — Aggregates all sub-routers into a single APIRouter.

Import this in app/main.py and include it once.
"""

from fastapi import APIRouter

from app.api.routes.auth          import router as auth_router
from app.api.routes.users         import router as users_router
from app.api.routes.tickets       import router as tickets_router
from app.api.routes.wiki          import router as wiki_router
from app.api.routes.search        import router as search_router
from app.api.routes.nova          import router as nova_router
from app.api.routes.sprints       import router as sprints_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.clients       import router as clients_router
from app.api.routes.analytics     import router as analytics_router
from app.api.routes.spaces        import router as spaces_router
from app.api.routes.summary       import router as summary_router
from app.api.routes.goals         import router as goals_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(tickets_router)
api_router.include_router(wiki_router)
api_router.include_router(search_router)
api_router.include_router(nova_router)
api_router.include_router(sprints_router)
api_router.include_router(notifications_router)
api_router.include_router(clients_router)
api_router.include_router(analytics_router)
api_router.include_router(spaces_router)
api_router.include_router(summary_router)
api_router.include_router(goals_router)
