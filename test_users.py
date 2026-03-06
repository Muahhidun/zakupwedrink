import asyncio
import os
import aiohttp
from aiohttp import web
from webapp.server import create_app
import traceback
import sys

async def check_staff_api():
    async with aiohttp.ClientSession() as session:
        cookie_file = "/tmp/cookies.txt"
        async with session.get('http://localhost:8080/staff', cookies={'WeDrink_Session': 'dev_admin'}) as resp:
            print(f"Status: {resp.status}")
            
if __name__ == '__main__':
    asyncio.run(check_staff_api())
