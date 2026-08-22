import asyncio
import uuid
from contextlib import suppress

import aioari
import aiohttp

from asteramisk.config import config


class AriClient:
    """Manage the process-wide ARI client and Stasis application."""

    _instance = None
    _application_name = f"asteramisk-{uuid.uuid4().hex}"
    _run_task = None
    _lock = None
    _users = 0

    @classmethod
    def application_name(cls):
        return cls._application_name

    @classmethod
    def configure_application(cls, application_name):
        """Set the shared app name before its WebSocket has started."""
        if not application_name or application_name == cls._application_name:
            return cls._application_name
        if cls._users or cls._run_task is not None:
            raise RuntimeError(
                f"Cannot configure Stasis app {application_name!r}: the shared "
                f"ARI application is already running as {cls._application_name!r}"
            )
        cls._application_name = application_name
        return cls._application_name

    @classmethod
    def _get_lock(cls):
        # asyncio primitives should be created in the loop where they are used.
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    async def create(
        cls,
        ari_host=config.ASTERISK_HOST,
        ari_port=config.ASTERISK_ARI_PORT,
        ari_user=config.ASTERISK_ARI_USER,
        ari_pass=config.ASTERISK_ARI_PASS,
    ):
        async with cls._get_lock():
            if cls._instance is None:
                cls._instance = await aioari.connect(
                    f"http://{ari_host}:{ari_port}", ari_user, ari_pass
                )
            return cls._instance

    @classmethod
    async def acquire(
        cls,
        ari_host=config.ASTERISK_HOST,
        ari_port=config.ASTERISK_ARI_PORT,
        ari_user=config.ASTERISK_ARI_USER,
        ari_pass=config.ASTERISK_ARI_PASS,
    ):
        """Acquire the shared client and ensure its event WebSocket is ready."""
        async with cls._get_lock():
            if cls._instance is None:
                cls._instance = await aioari.connect(
                    f"http://{ari_host}:{ari_port}", ari_user, ari_pass
                )
            client = cls._instance
            if cls._run_task is None or cls._run_task.done():
                cls._run_task = asyncio.create_task(
                    client.run(apps=[cls._application_name])
                )
            cls._users += 1

        try:
            await cls._wait_until_registered()
        except BaseException:
            await cls.release()
            raise
        return client

    @classmethod
    async def _wait_until_registered(cls, timeout=10):
        """Wait until Asterisk reports that the shared app exists."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            if cls._run_task.done():
                await cls._run_task
                raise RuntimeError("ARI event WebSocket closed before registration")
            try:
                await cls._instance.applications.get(
                    applicationName=cls._application_name
                )
                return
            except aiohttp.web_exceptions.HTTPNotFound:
                if loop.time() >= deadline:
                    raise TimeoutError(
                        f"Timed out registering ARI application "
                        f"{cls._application_name!r}"
                    )
                await asyncio.sleep(0.05)

    @classmethod
    async def wait(cls):
        """Wait for the shared event WebSocket to close."""
        if cls._run_task is None:
            raise RuntimeError("The shared ARI application is not running")
        await cls._run_task

    @classmethod
    async def release(cls):
        """Release one user and close the client after the final release."""
        async with cls._get_lock():
            if cls._users == 0:
                return
            cls._users -= 1
            if cls._users:
                return
            client = cls._instance
            run_task = cls._run_task
            cls._instance = None
            cls._run_task = None

        if client is not None:
            await client.close()
        if run_task is not None:
            with suppress(asyncio.CancelledError):
                await run_task

    @classmethod
    async def close_if_unused(cls):
        """Close a client created for setup if no component acquired it."""
        async with cls._get_lock():
            if cls._users or cls._instance is None:
                return
            client = cls._instance
            cls._instance = None
        await client.close()

    @classmethod
    def is_instantiated(cls):
        return cls._instance is not None
