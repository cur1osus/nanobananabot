from aiogram.filters.callback_data import CallbackData


class MenuAction(CallbackData, prefix="menu"):
    action: str


class ModelMenu(CallbackData, prefix="model_menu"):
    pass


class ModelSelect(CallbackData, prefix="model_select"):
    model: str


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
