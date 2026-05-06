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
from app.api.routes.filters       import router as filters_router
from app.api.routes.releases      import router as releases_router
from app.api.routes.automations   import router as automations_router
from app.api.routes.custom_fields import router as custom_fields_router
from app.api.routes.tests         import router as tests_router
from app.api.routes.code_review    import router as code_review_router
from app.api.routes.manual_entries import router as manual_entries_router
from app.api.routes.decisions      import router as decisions_router
from app.api.routes.processes      import router as processes_router
from app.api.routes.integrations   import router as integrations_router
from app.api.routes.audit          import router as audit_router
from app.api.routes.chat           import router as chat_router
from app.api.routes.forms          import router as forms_router
from app.api.routes.guest          import router as guest_router
from app.api.routes.webhooks       import router as webhooks_router

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
api_router.include_router(filters_router)
api_router.include_router(releases_router)
api_router.include_router(automations_router)
api_router.include_router(custom_fields_router)
api_router.include_router(tests_router)
api_router.include_router(code_review_router)
api_router.include_router(manual_entries_router)
api_router.include_router(decisions_router)
api_router.include_router(processes_router)
api_router.include_router(integrations_router)
api_router.include_router(audit_router)
api_router.include_router(chat_router)
api_router.include_router(forms_router)
api_router.include_router(guest_router)
api_router.include_router(webhooks_router)
