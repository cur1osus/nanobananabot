from aiogram import Router

from . import cmds, image, manager, menu, payments

router = Router()
router.include_router(cmds.router)
router.include_router(image.router)
router.include_router(menu.router)
router.include_router(payments.router)
router.include_router(manager.router)
