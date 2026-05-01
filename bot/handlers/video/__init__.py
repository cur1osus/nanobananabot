from aiogram import Router

from .flow import router as _flow_router

router = Router()
router.include_router(_flow_router)
