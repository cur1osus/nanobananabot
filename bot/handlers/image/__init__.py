from aiogram import Router

from . import flow

router = Router()
router.include_router(flow.router)
