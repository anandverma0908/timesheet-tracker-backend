"""
app/models — Import all ORM models here so SQLAlchemy's metadata knows about them.
This file is the single import point for Alembic and create_tables().
"""

from app.core.database import Base  # noqa: F401

from app.models.organisation import Organisation  # noqa: F401
from app.models.user         import User          # noqa: F401
from app.models.ticket       import (             # noqa: F401
    JiraTicket, Worklog, TicketComment, TicketAttachment, TicketEmbedding,
)
from app.models.wiki         import (             # noqa: F401
    WikiSpace, WikiPage, WikiVersion, WikiEmbedding,
)
from app.models.manual_entry import ManualEntry   # noqa: F401
from app.models.audit        import AuditLog, SyncLog  # noqa: F401
from app.models.sprint       import Sprint, Standup, KnowledgeGap  # noqa: F401
from app.models.epic         import Epic  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.client       import ClientBudget, BurnRateAlert  # noqa: F401
from app.models.goal         import Goal  # noqa: F401
from app.models.space_brief  import SpaceBrief   # noqa: F401
from app.models.space_member import SpaceMember  # noqa: F401
from app.models.saved_filter import SavedFilter  # noqa: F401
from app.models.board_config import BoardConfig  # noqa: F401
from app.models.release import Release  # noqa: F401
from app.models.automation import AutomationRule  # noqa: F401
from app.models.tests import TestCase, TestCycle, TestExecution  # noqa: F401
from app.models.code_review import CodeReviewSnapshot  # noqa: F401
