from bot.utils.image_models import get_image_model


def test_flux_pricing_ladder() -> None:
    assert get_image_model("flux2_klein").cost == 1
    assert get_image_model("flux2_dev").cost == 2
    assert get_image_model("flux2_max").cost == 6


def test_flux_klein_label_matches_cost() -> None:
    model = get_image_model("flux2_klein")

    assert model.button_label == "FLUX.2 Klein 9B (1 ген)"
    assert model.details == "быстрые черновики"
