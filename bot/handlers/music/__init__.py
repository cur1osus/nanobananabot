from aiogram import Router

from . import back, entry, lyrics, style, title

router = Router()
router.include_router(back.router)
router.include_router(entry.router)
router.include_router(lyrics.router)
router.include_router(style.router)
router.include_router(title.router)
