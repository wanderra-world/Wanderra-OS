"""SQLAlchemy implementation of the memory persistence port."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.contracts import (
    ConversationRecord,
    MemoryRepository,
    ProjectRecord,
    SearchableConversation,
    UserRecord,
)
from app.models.memory import Conversation, ConversationMessage, Project, User


class SQLAlchemyMemoryRepository(MemoryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_user(self, email: str, display_name: str | None) -> UserRecord:
        user = User(email=email, display_name=display_name)
        self.session.add(user)
        await self.session.flush()
        return UserRecord(id=user.id, email=user.email, display_name=user.display_name)

    async def create_project(
        self, user_id: uuid.UUID, name: str, description: str | None
    ) -> ProjectRecord:
        project = Project(user_id=user_id, name=name, description=description)
        self.session.add(project)
        await self.session.flush()
        return ProjectRecord(
            id=project.id, user_id=project.user_id, name=project.name, description=project.description
        )

    async def create_conversation(
        self, user_id: uuid.UUID, project_id: uuid.UUID | None, title: str | None
    ) -> ConversationRecord:
        conversation = Conversation(user_id=user_id, project_id=project_id, title=title)
        self.session.add(conversation)
        await self.session.flush()
        return ConversationRecord(
            id=conversation.id,
            user_id=conversation.user_id,
            project_id=conversation.project_id,
            title=conversation.title,
        )

    async def add_message(
        self, conversation_id: uuid.UUID, role: str, content: str, embedding: list[float]
    ) -> None:
        self.session.add(
            ConversationMessage(
                conversation_id=conversation_id,
                role=role,
                content=content,
                embedding=embedding,
            )
        )
        await self.session.flush()

    async def get_search_candidates(
        self, user_id: uuid.UUID, project_id: uuid.UUID | None
    ) -> list[SearchableConversation]:
        query = (
            select(ConversationMessage, Conversation)
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .where(Conversation.user_id == user_id)
        )
        if project_id is not None:
            query = query.where(Conversation.project_id == project_id)

        rows = (await self.session.execute(query)).all()
        return [
            SearchableConversation(
                message_id=message.id,
                conversation_id=conversation.id,
                project_id=conversation.project_id,
                title=conversation.title,
                content=message.content,
                embedding=message.embedding,
                created_at=message.created_at,
            )
            for message, conversation in rows
        ]

    async def store_external_message(
        self, user_id: uuid.UUID, source: str, external_id: str, title: str, role: str, content: str, embedding: list[float]
    ) -> None:
        existing = await self.session.scalar(
            select(ConversationMessage.id).where(
                ConversationMessage.source == source, ConversationMessage.external_id == external_id
            )
        )
        if existing is not None:
            return
        conversation = Conversation(user_id=user_id, title=title)
        self.session.add(conversation)
        await self.session.flush()
        self.session.add(ConversationMessage(conversation_id=conversation.id, role=role, content=content, embedding=embedding, source=source, external_id=external_id))
        await self.session.flush()
