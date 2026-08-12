import asyncio

from app.decrement import decrement


async def _check():
    assert decrement(5) == 4


def test_decrement():
    asyncio.run(_check())
