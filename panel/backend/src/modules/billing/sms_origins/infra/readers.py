from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType
from sqlalchemy import func, select
from sqlmodel import col

from src.modules.billing.sms_origins.domain.facts import ParserProfileFacts
from src.modules.billing.sms_origins.infra.tables import (
    SmsParserProfileTable,
    SmsParserRevisionTable,
)


class SmsParserProfileReader:
    """Declared profile + current immutable revision metadata read model."""

    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    def statement(self):
        profile, revision = SmsParserProfileTable, SmsParserRevisionTable
        return select(
            col(profile.id),
            col(profile.title),
            col(profile.is_active),
            col(profile.revision),
            col(revision.id).label("current_parser_revision_id"),
            col(profile.created_at),
        ).join(
            revision,
            (col(revision.profile_id) == col(profile.id))
            & (col(revision.revision) == col(profile.revision)),
        )

    async def get(self, id: int) -> ParserProfileFacts | None:
        result = await self.uow.execute(
            self.statement().where(col(SmsParserProfileTable.id) == id)
        )
        row = result.one_or_none()
        return ParserProfileFacts(**row._mapping) if row is not None else None

    async def page(
        self, q: str | None, offset: int, limit: int
    ) -> PagedType[ParserProfileFacts]:
        query = self.statement().order_by(col(SmsParserProfileTable.id).desc())
        if q is not None:
            query = query.where(
                col(SmsParserProfileTable.title).contains(q, autoescape=True)
            )
        total = await self.uow.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
        rows = await self.uow.execute(query.offset(offset).limit(limit))
        return PagedType(
            items=[ParserProfileFacts(**row._mapping) for row in rows],
            total_items=total.scalar_one(),
        )
