from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import (
    Any,
    AsyncGenerator,
    Coroutine,
    Generator,
    MutableMapping,
    MutableSequence,
    Optional,
    TypeVar,
    Union,
)
from traceback import print_stack

logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


@dataclass
class _LoopInfo:
    thread: threading.Thread
    name: str


_LOOP_INFOS: MutableMapping[int, _LoopInfo] = {}
_ANONYMOUS_LOOP_COUNT: int = 0


def _get_loop_info(loop: asyncio.AbstractEventLoop) -> Optional[_LoopInfo]:
    return _LOOP_INFOS.get(id(loop))


def _new_loop_info(loop: asyncio.AbstractEventLoop, name: str) -> None:
    if info := _get_loop_info(loop):
        logger.warning(f"Loop '{name}' already registered with name '{info.name}'")

    for info in _LOOP_INFOS.values():
        if threading.current_thread() is info.thread:
            logger.warning(f"Error when creating loop '{name}': Thread '{info.thread.name}' already has loop '{info.name}'")
            break



    _LOOP_INFOS[id(loop)] = _LoopInfo(
        thread=threading.current_thread(),
        name=name,
    )


@asynccontextmanager
async def background_tasks(
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> AsyncGenerator[Any, Any]:
    """Context manager for long-living tasks that cancel when exiting the
    context

    """

    loop = loop or asyncio.get_event_loop()
    tasks: MutableSequence[asyncio.Task[Any]] = []

    def add(coro: Coroutine[Any, Any, Any], *, name: Optional[str] = None) -> None:
        tasks.append(loop.create_task(coro, name=name))

    try:
        yield add
    finally:
        for t in tasks:
            t.cancel()
        for exc in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(exc, asyncio.CancelledError):
                continue
            if isinstance(exc, BaseException):
                logger.error(str(exc), exc_info=exc)
        tasks.clear()


def new_event_loop(name: Optional[str] = None) -> asyncio.AbstractEventLoop:
    if name is None:
        global _ANONYMOUS_LOOP_COUNT
        _ANONYMOUS_LOOP_COUNT += 1
        name = f"Loop-{_ANONYMOUS_LOOP_COUNT}"

    loop = asyncio.new_event_loop()
    loop.set_task_factory(_create_task)
    _new_loop_info(loop, name)

    return loop


def get_event_loop() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(
            new_event_loop()
        )
        return asyncio.get_event_loop()


def _create_task(
    loop: asyncio.AbstractEventLoop,
    coro: Union[Coroutine[Any, Any, _T], Generator[Any, None, _T]],
) -> asyncio.Task[_T]:
    task = asyncio.Task(coro, loop=loop)
    task.add_done_callback(_done_callback)

    if info := _get_loop_info(loop):
        if threading.current_thread() is not info.thread:
            logger.warning(
                f"Creating task for {coro} on loop '{info.name}' failed:\n"
                f"Loop was created on thread '{info.thread.name}', "
                f"but task is created on thread '{threading.current_thread().name}'"
            )
            print_stack()

    return task


def _done_callback(task: asyncio.Task[_T_co]) -> None:
    assert task.done()

    if hasattr(task.get_loop(), "thread") and threading.current_thread() is not task.get_loop().thread:
        logger.warning(
            f"Task created on the wrong thread.\n  Task: {task.get_name()}\n  Coro: {task.get_coro()}"
        )

    try:
        if (exc := task.exception()) is None:
            return

        logger.error(f"Exception occurred during {task.get_name()}", exc_info=exc)
    except asyncio.CancelledError:
        pass
