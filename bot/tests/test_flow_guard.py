from papilio_telegram.commerce import BotPresentation
from papilio_telegram.flow_guard import callback_flow, flow_is_visible


def test_callback_flow_maps_existing_menu_actions() -> None:
    assert callback_flow("ch:2") == "purchases"
    assert callback_flow("loyalty") == "loyalty"
    assert callback_flow("trial_claim") == "trial"
    assert callback_flow("account") == "account"
    assert callback_flow("plans:3") == "catalog"
    assert callback_flow("cb:nonce:w:0:7") == "catalog"
    assert callback_flow("subs:2") == "subscriptions"
    assert callback_flow("service:7") == "subscriptions"
    assert callback_flow("wallet") == "wallet"
    assert callback_flow("support") == "support"
    assert callback_flow("home") is None
    assert callback_flow("unowned:action") is None


def test_hidden_menu_flow_rejects_old_callback_data() -> None:
    presentation = BotPresentation()
    presentation.menu_buttons[4].visible = False

    assert not flow_is_visible(presentation, "plans:1")
    assert not flow_is_visible(presentation, "cb:nonce:w:0:7")
    assert flow_is_visible(presentation, "ch:1")
    assert flow_is_visible(presentation, "home")
