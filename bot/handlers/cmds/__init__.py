from aiogram import Router

from . import create_deep_link, menu_commands, refund, speech_test, start

router = Router()
router.include_router(start.router)
router.include_router(menu_commands.router)
router.include_router(create_deep_link.router)
router.include_router(refund.router)
router.include_router(speech_test.router)
