from aiogram.filters.callback_data import CallbackData


class MenuAction(CallbackData, prefix="menu"):
    action: str


class ModelMenu(CallbackData, prefix="model_menu"):
    pass


class ModelSelect(CallbackData, prefix="model_select"):
    model: str


class ImageResultAction(CallbackData, prefix="image_result"):
    action: str


class CreateAspectRatio(CallbackData, prefix="create_ratio"):
    ratio: str


class ImageNav(CallbackData, prefix="image_nav"):
    action: str


class TopupMethod(CallbackData, prefix="topup_method"):
    method: str


class TopupPlan(CallbackData, prefix="topup_plan"):
    method: str
    plan: str


class WithdrawAction(CallbackData, prefix="withdraw"):
    action: str
    transaction_id: int


class InfoPeriod(CallbackData, prefix="info_period"):
    period: str


class VideoSetting(CallbackData, prefix="video_setting"):
    setting: str
    value: str


class VideoNav(CallbackData, prefix="video_nav"):
    action: str
