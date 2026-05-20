from aiogram.filters.callback_data import CallbackData


class MenuAction(CallbackData, prefix="menu"):
    action: str


class ModelMenu(CallbackData, prefix="model_menu"):
    pass


class ModelGroupSwitch(CallbackData, prefix="model_group"):
    group: str


class ModelSelect(CallbackData, prefix="model_select"):
    model: str


class ImageResultAction(CallbackData, prefix="image_result"):
    action: str


class CreateAspectRatio(CallbackData, prefix="create_ratio"):
    ratio: str


class ImageNav(CallbackData, prefix="image_nav"):
    action: str


class MusicBack(CallbackData, prefix="music_back"):
    target: str


class MusicStyle(CallbackData, prefix="music_style"):
    style: str


class MusicTextAction(CallbackData, prefix="music_text"):
    action: str


class MusicTopic(CallbackData, prefix="music_topic"):
    topic: str


class MyTrackAction(CallbackData, prefix="my_track"):
    action: str
    track_id: int


class MyTracksPage(CallbackData, prefix="my_tracks"):
    page: int


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


class VideoAspectRatio(CallbackData, prefix="video_ratio"):
    ratio: str


class VideoNav(CallbackData, prefix="video_nav"):
    action: str
