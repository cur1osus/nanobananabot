from aiogram import Router

from . import (
    broadcast,
    create_deep_link,
    menu_commands,
    refund,
    speech_test,
    start,
    test_payment,
)

router = Router()
router.include_router(start.router)
router.include_router(menu_commands.router)
router.include_router(create_deep_link.router)
router.include_router(refund.router)
router.include_router(speech_test.router)
router.include_router(broadcast.router)
router.include_router(test_payment.router)
