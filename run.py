"""
Windows-compatible uvicorn launcher.
Sets ProactorEventLoop policy BEFORE uvicorn starts so Playwright
can launch browser subprocesses on Windows (Python 3.8+).
"""
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
