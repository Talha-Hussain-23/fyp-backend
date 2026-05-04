
import asyncio
import os
import sys
from pathlib import Path

# Add backend to path
sys.path.append(str(Path.cwd()))

from core.config import settings
from utils.db import get_db

async def check_users():
    print(f"Connecting to: {settings.MONGODB_DB}")
    db = await get_db()
    users = await db.users.find().to_list(length=10)
    print(f"Found {len(users)} users")
    for u in users:
        print(f"- {u.get('email')} (Verified: {u.get('is_verified')}, Active: {u.get('is_active')})")

if __name__ == "__main__":
    asyncio.run(check_users())
