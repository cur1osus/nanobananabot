from aiogram.filters.callback_data import CallbackData


class MenuAction(CallbackData, prefix="menu"):
    action: str


class MusicBack(CallbackData, prefix="music_back"):
    target: str


class MusicStyle(CallbackData, prefix="music_style"):
    style: str


class MusicTextAction(CallbackData, prefix="music_text"):
    action: str


class MusicTopic(CallbackData, prefix="music_topic"):
    topic: str


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


class MyTrackAction(CallbackData, prefix="my_track"):
    action: str
    track_id: int


class MyTracksPage(CallbackData, prefix="my_tracks"):
    page: int
