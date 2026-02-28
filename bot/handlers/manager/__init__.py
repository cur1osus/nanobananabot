from aiogram import Router

from . import withdraw

router = Router()
router.include_router(withdraw.router)
