import asyncio
import os
import urllib.request
from aiohttp import web
import aiohttp_session
import aiohttp_jinja2
import jinja2

import asyncpg
from webapp.server import create_app

import aiohttp

async def main():
    async with aiohttp.ClientSession() as session:
        # First we need to login or mock the cookie.
        # It's easier to mock the session on a local test server instance
        pass

if __name__ == '__main__':
    asyncio.run(main())
