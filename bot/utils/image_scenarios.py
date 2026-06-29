from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class EditScenario:
    key: str
    title: str
    prompt: str
    details: str
    strength: float | None = None
    steps: int | None = None


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
        strength=0.70,
    ),
    EditScenario(
        key="topless",
        title="Топлес",
        prompt=(
            "Preserve exactly the face, facial features, body shape, proportions, skin tone, "
            "hair color and style from the reference photo of the woman, completely unchanged identity. "
            "Remove her top completely exposing her bare breasts, topless, no bra, "
            "her perfect natural round breasts fully visible, "
            "her nipples hard and erect, realistic areola detail, "
            "natural skin texture with visible pores and subtle imperfections, "
            "soft natural light caressing her chest, her skin glowing, "
            "detailed breast anatomy, realistic veins and skin folds, "
            "cinematic portrait, high detail photography, sharp focus"
        ),
        details="обнажённая грудь",
        strength=0.68,
    ),
    EditScenario(
        key="lingerie",
        title="Надеть бельё",
        prompt=(
            "Preserve exactly the face, facial features, body shape, proportions, skin tone, "
            "hair color and style from the reference photo, completely unchanged identity, "
            "only change to wearing a thong, minimal g-string, "
            "seductive pose, "
            "detailed fabric texture, "
            "natural skin texture, realistic body, "
            "high detail photography"
        ),
        details="кружевной комплект белья",
        strength=0.70,
    ),
)
