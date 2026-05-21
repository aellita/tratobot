from ..db.database import async_session_maker
from ..db.models.models import User


async def get_or_create_user(telegram_id: int, first_name: str = None, username: str = None) -> User:
    async with async_session_maker() as session:
        user = await session.get(User, telegram_id)
        if not user:
            user = User(
                telegram_id=telegram_id,
                first_name=first_name,
                username=username
            )
            session.add(user)
            await session.commit()
        return user
