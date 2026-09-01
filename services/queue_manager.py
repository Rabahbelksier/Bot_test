import asyncio
import logging

from services.worker import process_link_for_user

logger = logging.getLogger(__name__)

user_queues: dict = {}
active_workers: set = set()


async def user_queue_worker(chat_id: int, context):
    queue = user_queues.get(chat_id)
    if queue is None:
        active_workers.discard(chat_id)
        return
    try:
        while not queue.empty():
            url = queue.get_nowait()
            await process_link_for_user(chat_id, url, context)
            queue.task_done()
    finally:
        active_workers.discard(chat_id)
        if chat_id in user_queues and user_queues[chat_id].empty():
            del user_queues[chat_id]


async def enqueue_url(chat_id: int, url: str, context):
    if chat_id not in user_queues:
        user_queues[chat_id] = asyncio.Queue()

    await user_queues[chat_id].put(url)

    if chat_id not in active_workers:
        active_workers.add(chat_id)
        asyncio.create_task(user_queue_worker(chat_id, context))
