from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class EditScenario:
    key: str
    title: str
    prompt: str
    details: str


EDIT_SCENARIOS: Final[tuple[EditScenario, ...]] = (
    EditScenario(
        key="nude",
        title="Полностью раздеть",
        prompt=(
            "Preserve exactly the face, facial features, body shape, proportions, skin tone, "
            "hair color and style from the reference photo, completely unchanged identity, "
            "only remove all clothing making her completely naked, full nude body, "
            "realistic skin texture with visible pores, "
            "natural skin texture, detailed skin, realistic anatomy, high detail photography"
        ),
        details="вся одежда убрана",
    ),
    EditScenario(
        key="missionary",
        title="Миссионерская поза",
        prompt=(
            "Preserve exactly the face, facial features, body shape, proportions, skin tone, "
            "hair color and style from the reference photo, completely unchanged identity, "
            "only change pose to missionary position lying on back, legs spread apart, "
            "man on top engaging in sexual intercourse, "
            "realistic skin texture, natural skin tone, "
            "realistic anatomy, detailed bodies, high detail photography"
        ),
        details="женщина снизу, мужчина сверху",
    ),
    EditScenario(
        key="cowgirl",
        title="Наездница",
        prompt=(
            "Preserve exactly the face, facial features, body shape, proportions, skin tone, "
            "hair color and style from the reference photo, completely unchanged identity, "
            "only change pose to cowgirl position sitting on top riding a man lying underneath, "
            "woman looking down at him, sexual intercourse, "
            "realistic skin texture with natural highlights, "
            "natural body proportions, "
            "realistic anatomy, detailed skin, high detail photography"
        ),
        details="женщина сверху",
    ),
    EditScenario(
        key="doggy",
        title="Ракурс сзади",
        prompt=(
            "Preserve exactly the face, facial features, body shape, proportions, skin tone, "
            "hair color and style from the reference photo, completely unchanged identity, "
            "only change pose to doggy style on all fours, back arched, "
            "man behind engaging in sexual intercourse from behind, "
            "realistic skin texture with natural shadows, "
            "realistic anatomy, high detail photography"
        ),
        details="коленно-локтевая поза",
    ),
    EditScenario(
        key="blowjob",
        title="Минет",
        prompt=(
            "Preserve exactly the face, facial features, body shape, skin tone, "
            "hair color and style from the reference photo, completely unchanged identity, "
            "only change pose to woman kneeling giving oral sex to a man standing before her, "
            "close-up, realistic skin texture with detailed lips, "
            "natural skin texture, realistic anatomy, detailed photography"
        ),
        details="оральный секс",
    ),
    EditScenario(
        key="topless",
        title="Топлес",
        prompt=(
            "Preserve exactly the face, facial features, body shape, proportions, skin tone, "
            "hair color and style from the reference photo, completely unchanged identity, "
            "only remove top clothing exposing bare breasts, topless, no bra, "
            "natural skin texture with visible pores, "
            "realistic skin texture, natural lighting, subtle imperfections, "
            "realistic anatomy, high detail photography"
        ),
        details="обнажённая грудь",
    ),
    EditScenario(
        key="lingerie",
        title="Надеть бельё",
        prompt=(
            "Preserve exactly the face, facial features, body shape, proportions, skin tone, "
            "hair color and style from the reference photo, completely unchanged identity, "
            "only change to wearing sexy lace lingerie set, matching bra and panties, "
            "seductive pose, "
            "detailed fabric texture on lace, "
            "natural skin texture, realistic body, "
            "luxurious lingerie details, high detail photography"
        ),
        details="кружевной комплект белья",
    ),
    EditScenario(
        key="masturbation",
        title="Мастурбация",
        prompt=(
            "Preserve exactly the face, facial features, body shape, proportions, skin tone, "
            "hair color and style from the reference photo, completely unchanged identity, "
            "only change to lying down touching herself, legs spread apart, "
            "solo masturbation, close-up, sensual expression, "
            "realistic skin texture, natural skin tone, "
            "realistic anatomy, detailed skin, high detail photography"
        ),
        details="женщина ласкает себя",
    ),
)
