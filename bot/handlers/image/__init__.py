from aiogram import Router

from . import demo, flow

router = Router()
router.include_router(demo.router)
router.include_router(flow.router)
