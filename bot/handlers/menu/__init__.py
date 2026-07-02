from aiogram import Router

from . import (
    adult,
    contacts,
    earn,
    history,
    home,
    how,
    info,
    topup,
    tracks,
    withdraw,
)

router = Router()
router.include_router(adult.router)
router.include_router(home.router)
router.include_router(how.router)
router.include_router(info.router)
router.include_router(topup.router)
router.include_router(tracks.router)
router.include_router(history.router)
router.include_router(earn.router)
router.include_router(withdraw.router)
router.include_router(contacts.router)
