from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator

from app.core.config import settings


# Engine assíncrono — usa asyncpg como driver
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,       # loga todas as queries em desenvolvimento
    pool_pre_ping=True,        # verifica conexão antes de usar do pool
    pool_size=10,
    max_overflow=20,
)

# Fábrica de sessões assíncronas
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,    # evita lazy loading após commit
)


# Base para todos os models SQLAlchemy
class Base(DeclarativeBase):
    pass


# Dependency injection para as rotas FastAPI
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
