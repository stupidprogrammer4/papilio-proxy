import asyncio
from hashlib import sha256

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.types import InlineKeyboardButton as Button

from papilio_telegram.api import BotApi, BotApiError
from papilio_telegram.checkout import (
    CheckoutCancel,
    CheckoutCreate,
    CheckoutDrafts,
    CheckoutOffer,
    CheckoutRead,
    CheckoutReconfirm,
    CheckoutRetirement,
)
from papilio_telegram.presentation import (
    fa,
    gibibytes,
    payment_instruction_text,
    toman,
)

_STATE = {
    "awaiting_funding": "در انتظار تأیید واریز و شارژ کیف پول",
    "ready": "در صف پردازش خرید",
    "action_required": "تغییر شرایط خرید؛ نیازمند تأیید شما",
    "purchased": "خرید ثبت شده",
    "cancelled": "لغو شده",
    "expired": "مهلت خرید تمام شده",
}


def keyboard(rows: list[list[Button]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def offer_text(offer: CheckoutOffer) -> str:
    quota = (
        "نامحدود"
        if offer.quota_bytes is None
        else gibibytes(offer.quota_bytes)
    )
    duration = (
        "بدون مدت"
        if offer.duration_days is None
        else (fa(offer.duration_days) + " روز")
    )
    delivery = (
        "تحویل کانفیگ پس از آماده‌سازی سرویس"
        if offer.delivery_mode == "configured_bundle"
        else "تحویل دستی توسط مدیر؛ ثبت خرید به معنی آماده بودن کانفیگ نیست"
    )
    return (
        f"{offer.plan_title}\nقیمت نهایی: {toman(offer.price_rial)}\n"
        f"حجم: {quota}\nمدت: {duration}\n{delivery}\n"
        "تمدید خودکار تنها با موجودی کافی کیف پول انجام می‌شود."
    )


def intent_text(intent: CheckoutRead) -> str:
    text = (
        f"خرید شمارهٔ {fa(intent.id)}\n{_STATE[intent.state]}\n"
        f"قیمت: {toman(intent.price_rial)}"
    )
    if intent.topup_id is not None:
        text += f"\nدرخواست واریز شمارهٔ {fa(intent.topup_id)}"
    if intent.state == "awaiting_funding":
        text += (
            "\nپس از تأیید واریز، خرید به صورت خودکار بررسی می‌شود. "
            "«اطلاعات همین واریز» را باز کنید؛ "
            "رسید را در حساب کاربری ثبت کنید."
        )
    if intent.state == "purchased":
        text += (
            "\nتحویل دستی هنوز باید توسط مدیر انجام شود."
            if intent.delivery_mode == "manual_profiles"
            else "\nآماده بودن سرویس را از سرویس‌های من بررسی کنید."
        )
    return text


def intent_menu(intent: CheckoutRead) -> InlineKeyboardMarkup:
    rows = [[Button(text="بررسی وضعیت", callback_data=f"ci:{intent.id}")]]
    if intent.topup_id is not None:
        rows.append(
            [
                Button(
                    text="اطلاعات همین واریز", callback_data=f"cp:{intent.id}"
                )
            ]
        )
    if intent.state == "action_required":
        rows.append(
            [Button(text="بررسی شرایط تازه", callback_data=f"co:{intent.id}")]
        )
    if intent.state not in {"purchased", "cancelled", "expired"}:
        rows.append(
            [
                Button(
                    text="لغو این خرید",
                    callback_data=f"cc:{intent.id}:{intent.revision}",
                )
            ]
        )
    if intent.subscription_id is not None:
        rows.append(
            [
                Button(
                    text="وضعیت سرویس",
                    callback_data=f"service:{intent.subscription_id}",
                )
            ]
        )
    rows.extend(
        [
            [Button(text="حساب کاربری و رسیدها", callback_data="account")],
            [Button(text="خریدهای من", callback_data="ch:1")],
        ]
    )
    return keyboard(rows)


async def respond(
    callback: CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    if isinstance(callback.message, Message):
        await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


async def show_retirement(
    callback: CallbackQuery, result: CheckoutRetirement, plan_id: int
) -> None:
    if result.status == "purchased":
        assert result.intent is not None
        await respond(
            callback,
            "خرید قبلاً ثبت شده است؛ همان سرویس حفظ می‌شود.\n"
            + intent_text(result.intent),
            intent_menu(result.intent),
        )
        return
    rows = (
        [
            [
                Button(
                    text="بررسی همین پلن برای خرید تازه",
                    callback_data=f"plan:{plan_id}",
                )
            ]
        ]
        if plan_id > 0
        else []
    )
    rows.append([Button(text="خریدهای من", callback_data="ch:1")])
    text = (
        "درخواست قبلی به صورت قطعی بسته شد؛ "
        "اکنون می‌توانید پیشنهاد تازه را بررسی کنید."
    )
    if result.intent is not None:
        text += "\n" + intent_text(result.intent)
    await respond(callback, text, keyboard(rows))


async def show_offer(
    api: BotApi, drafts: CheckoutDrafts, callback: CallbackQuery, plan_id: int
) -> None:
    offer = await api.checkout_offer(
        plan_id, callback.from_user.id, callback.from_user.full_name[:120]
    )
    nonce = drafts.put(callback.from_user.id, offer)
    rows = [
        [
            Button(
                text="خرید با کیف پول",
                callback_data=f"cb:{nonce}:w:0:{offer.plan_id}",
            )
        ],
        [
            Button(
                text="کیف پول + تمدید خودکار",
                callback_data=f"cb:{nonce}:w:1:{offer.plan_id}",
            )
        ],
    ]
    if offer.price_rial > 0:
        rows.extend(
            [
                [
                    Button(
                        text="واریز و خرید خودکار",
                        callback_data=f"cf:{nonce}:0:1",
                    )
                ],
                [
                    Button(
                        text="واریز + تمدید خودکار",
                        callback_data=f"cf:{nonce}:1:1",
                    )
                ],
            ]
        )
    rows.append([Button(text="خریدهای من", callback_data="ch:1")])
    await respond(callback, offer_text(offer), keyboard(rows))


def register_checkout(api: BotApi, drafts: CheckoutDrafts) -> Router:
    router = Router(name="durable_checkout")

    async def failure(callback: CallbackQuery, exc: BotApiError) -> None:
        text = (
            "پاسخ خرید مشخص نیست؛ دوباره همان دکمه را بزنید. "
            "خرید تازه ثبت نکنید و خریدهای من را بررسی کنید."
            if exc.code == "network"
            else "درخواست انجام نشد؛ وضعیت و شرایط خرید را دوباره بررسی کنید."
        )
        if exc.code == "payment_destination_required":
            text = "برای انتخاب مقصد پرداخت، حساب کاربری و رسیدها را باز کنید."
        await respond(
            callback,
            text,
            keyboard(
                [
                    [Button(text="خریدهای من", callback_data="ch:1")],
                    [
                        Button(
                            text="حساب کاربری و رسیدها",
                            callback_data="account",
                        )
                    ],
                ]
            ),
        )

    @router.callback_query(F.data.startswith("cf:"))
    async def funding(callback: CallbackQuery) -> None:
        parts = (callback.data or "").split(":")
        if (
            len(parts) != 4
            or parts[2] not in {"0", "1"}
            or not parts[3].isdecimal()
        ):
            await callback.answer()
            return
        _, nonce, renewal, page_text = parts
        user = callback.from_user
        draft = drafts.get(user.id, nonce)
        if draft is None:
            await respond(
                callback,
                "پیشنهاد در حافظه نیست؛ نتیجهٔ درخواست قبلی را "
                "از همان دکمه ثبت خرید یا خریدهای من بررسی کنید.",
                keyboard([[Button(text="خریدهای من", callback_data="ch:1")]]),
            )
            return
        if draft.attempted_create is not None:
            await respond(
                callback,
                "این خرید قبلاً ارسال شده است؛ "
                "همان دکمه ثبت خرید یا خریدهای من را بررسی کنید.",
            )
            return
        try:
            policy = await api.checkout_funding(user.id, user.full_name[:120])
            amount = max(draft.offer.price_rial, policy.minimum_topup_rial)
            if amount > policy.maximum_topup_rial:
                await respond(
                    callback,
                    "مبلغ این پلن از سقف هر درخواست واریز بیشتر است؛ "
                    "ابتدا کیف پول را شارژ و سپس با کیف پول خرید کنید.",
                    keyboard(
                        [
                            [
                                Button(
                                    text="خرید همین پلن با کیف پول",
                                    callback_data=f"cb:{nonce}:w:{renewal}:{draft.offer.plan_id}",
                                )
                            ],
                            [Button(text="کیف پول", callback_data="wallet")],
                        ]
                    ),
                )
                return
            page = int(page_text)
            destinations, pages = await api.checkout_destinations(
                user.id,
                user.full_name[:120],
                page,
                drafts.limits.history_page_size,
            )
            if not drafts.select_funding(
                nonce, amount, None, policy.destination_mode == "required"
            ):
                await respond(
                    callback,
                    "پیشنهاد تغییر کرده است؛ خریدهای من را بررسی کنید.",
                )
                return
            rows = [
                [
                    Button(
                        text=destination.title,
                        callback_data=f"cd:{nonce}:{renewal}:{page}:{destination.destination_id}",
                    )
                ]
                for destination in destinations
            ]
            if policy.destination_mode != "required":
                rows.append(
                    [
                        Button(
                            text="ثبت با روش پرداخت عمومی",
                            callback_data=f"cb:{nonce}:t:{renewal}:{draft.offer.plan_id}",
                        )
                    ]
                )
            navigation = []
            if page > 1:
                navigation.append(
                    Button(
                        text="قبلی",
                        callback_data=f"cf:{nonce}:{renewal}:{page - 1}",
                    )
                )
            if page < pages:
                navigation.append(
                    Button(
                        text="بعدی",
                        callback_data=f"cf:{nonce}:{renewal}:{page + 1}",
                    )
                )
            if navigation:
                rows.append(navigation)
            rows.append(
                [
                    Button(
                        text="خرید با کیف پول",
                        callback_data=f"cb:{nonce}:w:{renewal}:{draft.offer.plan_id}",
                    )
                ]
            )
            text = (
                f"مبلغ واریز: {toman(amount)}\n"
                f"قیمت خرید: {toman(draft.offer.price_rial)}\n"
                "مبلغ باقی‌مانده در کیف پول شما می‌ماند. مقصد را انتخاب کنید؛ "
                "هنوز درخواست واریز ثبت نشده است."
            )
            if not destinations and policy.destination_mode == "required":
                text += (
                    "\nدر این صفحه مقصد مجازی موجود نیست؛ "
                    "صفحه دیگر یا خرید با کیف پول را انتخاب کنید."
                )
            await respond(callback, text, keyboard(rows))
        except BotApiError as exc:
            await failure(callback, exc)

    @router.callback_query(F.data.startswith("cd:"))
    async def destination(callback: CallbackQuery) -> None:
        parts = (callback.data or "").split(":")
        if (
            len(parts) != 5
            or parts[2] not in {"0", "1"}
            or not all(part.isdecimal() for part in parts[3:])
        ):
            await callback.answer()
            return
        _, nonce, renewal, page_text, destination_text = parts
        user = callback.from_user
        draft = drafts.get(user.id, nonce)
        if draft is None or draft.attempted_create is not None:
            await respond(
                callback,
                "این پیشنهاد قابل تغییر نیست؛ خریدهای من را بررسی کنید.",
            )
            return
        try:
            policy, (destinations, _) = await asyncio.gather(
                api.checkout_funding(user.id, user.full_name[:120]),
                api.checkout_destinations(
                    user.id,
                    user.full_name[:120],
                    int(page_text),
                    drafts.limits.history_page_size,
                ),
            )
            selected = next(
                (
                    row
                    for row in destinations
                    if row.destination_id == int(destination_text)
                ),
                None,
            )
            amount = max(draft.offer.price_rial, policy.minimum_topup_rial)
            if selected is None or amount > policy.maximum_topup_rial:
                await respond(
                    callback,
                    "مقصد یا سقف واریز تغییر کرده است؛ "
                    "مبلغ و مقصد را دوباره انتخاب کنید.",
                )
                return
            if not drafts.select_funding(
                nonce,
                amount,
                selected.destination_id,
                policy.destination_mode == "required",
            ):
                await respond(
                    callback,
                    "پیشنهاد تغییر کرده است؛ خریدهای من را بررسی کنید.",
                )
                return
            await respond(
                callback,
                f"مقصد: {selected.title}\nواریز: {toman(amount)}\n"
                f"خرید: {toman(draft.offer.price_rial)}\n"
                "پس از ثبت درخواست، اطلاعات همین واریز را دریافت کنید.",
                keyboard(
                    [
                        [
                            Button(
                                text="ثبت واریز و خرید",
                                callback_data=f"cb:{nonce}:t:{renewal}:{draft.offer.plan_id}",
                            )
                        ],
                        [
                            Button(
                                text="تغییر مقصد",
                                callback_data=f"cf:{nonce}:{renewal}:{page_text}",
                            )
                        ],
                    ]
                ),
            )
        except BotApiError as exc:
            await failure(callback, exc)

    @router.callback_query(F.data.startswith("cp:"))
    async def payment_instruction(callback: CallbackQuery) -> None:
        id_text = (callback.data or "").split(":")[-1]
        if not id_text.isdecimal():
            await callback.answer()
            return
        user = callback.from_user
        try:
            instruction = await api.checkout_payment_instruction(
                int(id_text),
                user.id,
                user.full_name[:120],
            )
            text = (
                "برای این خرید، اطلاعات واریز اختصاصی ثبت نشده است."
                if instruction is None
                else payment_instruction_text(instruction)
            )
            await respond(
                callback,
                text,
                keyboard(
                    [
                        [
                            Button(
                                text="وضعیت همین خرید",
                                callback_data=f"ci:{id_text}",
                            )
                        ],
                        [
                            Button(
                                text="حساب کاربری و رسیدها",
                                callback_data="account",
                            )
                        ],
                    ]
                ),
            )
        except BotApiError as exc:
            await failure(callback, exc)

    @router.callback_query(F.data.startswith("cx:"))
    async def retire_review(callback: CallbackQuery) -> None:
        parts = (callback.data or "").split(":")
        if (
            len(parts) != 3
            or len(parts[1]) != 16
            or any(c not in "0123456789abcdef" for c in parts[1])
            or not parts[2].isdecimal()
        ):
            await callback.answer()
            return
        _, nonce, plan_id = parts
        await respond(
            callback,
            "با تأیید، درخواست قبلی بسته می‌شود و ورود دیرهنگام آن "
            "خرید جدیدی نمی‌سازد. "
            "اگر خرید قبلاً انجام شده باشد، همان سرویس حفظ می‌شود؛ "
            "واریز دیرهنگام در کیف پول می‌ماند.",
            keyboard(
                [
                    [
                        Button(
                            text="تأیید لغو امن درخواست",
                            callback_data=f"ct:{nonce}:{plan_id}",
                        )
                    ],
                    [Button(text="خریدهای من", callback_data="ch:1")],
                ]
            ),
        )

    @router.callback_query(F.data.startswith("ct:"))
    async def retire(callback: CallbackQuery) -> None:
        parts = (callback.data or "").split(":")
        if (
            len(parts) != 3
            or len(parts[1]) != 16
            or any(c not in "0123456789abcdef" for c in parts[1])
            or not parts[2].isdecimal()
        ):
            await callback.answer()
            return
        _, nonce, plan_text = parts
        user = callback.from_user
        draft = drafts.get(user.id, nonce)
        plan_id = draft.offer.plan_id if draft else int(plan_text)
        drafts.begin_retirement(user.id, nonce)
        try:
            result = await api.checkout_retire(
                user.id,
                user.full_name[:120],
                f"tgcheckout:{user.id}:{nonce}",
            )
            drafts.finish_retirement(user.id, nonce, result)
            await show_retirement(callback, result, plan_id)
        except BotApiError:
            await respond(
                callback,
                "پاسخ لغو مشخص نیست؛ فقط همین لغو را دوباره بررسی کنید "
                "و خرید تازه ثبت نکنید.",
                keyboard(
                    [
                        [
                            Button(
                                text="بررسی دوبارهٔ لغو",
                                callback_data=f"ct:{nonce}:{plan_id}",
                            )
                        ],
                        [Button(text="خریدهای من", callback_data="ch:1")],
                    ]
                ),
            )

    @router.callback_query(F.data.startswith("cb:"))
    async def create(callback: CallbackQuery) -> None:
        parts = (callback.data or "").split(":")
        if (
            len(parts) not in {4, 5}
            or (len(parts) == 5 and not parts[4].isdecimal())
            or parts[2] not in {"w", "t"}
            or parts[3] not in {"0", "1"}
        ):
            await callback.answer()
            return
        _, nonce, mode, renewal = parts[:4]
        if len(nonce) != 16 or any(c not in "0123456789abcdef" for c in nonce):
            await callback.answer()
            return
        user = callback.from_user
        key = f"tgcheckout:{user.id}:{nonce}"
        draft = drafts.get(user.id, nonce)
        plan_id = (
            draft.offer.plan_id
            if draft
            else (int(parts[4]) if len(parts) == 5 else 0)
        )
        if draft is not None and draft.retirement_started:
            if draft.retirement_result is not None:
                await show_retirement(
                    callback, draft.retirement_result, plan_id
                )
                return
            await respond(
                callback,
                "نتیجهٔ لغو درخواست هنوز باید تأیید شود؛ "
                "ثبت خرید قبلی را تکرار نکنید.",
                keyboard(
                    [
                        [
                            Button(
                                text="بررسی دوبارهٔ لغو",
                                callback_data=f"ct:{nonce}:{plan_id}",
                            )
                        ],
                        [Button(text="خریدهای من", callback_data="ch:1")],
                    ]
                ),
            )
            return
        try:
            if draft is None:
                existing = await api.checkout_lookup(
                    user.id, user.full_name[:120], key
                )
                if existing is not None:
                    await respond(
                        callback, intent_text(existing), intent_menu(existing)
                    )
                    return
                await respond(
                    callback,
                    "نتیجهٔ این درخواست هنوز مشخص نیست؛ "
                    "همان دکمه و خریدهای من را دوباره بررسی کنید. "
                    "برای همین خرید درخواست تازه ثبت نکنید.",
                    keyboard(
                        [
                            [
                                Button(
                                    text="بررسی دوبارهٔ همین درخواست",
                                    callback_data=callback.data or "ch:1",
                                )
                            ],
                            [
                                Button(
                                    text="لغو امن درخواست قبلی",
                                    callback_data=f"cx:{nonce}:{plan_id}",
                                )
                            ],
                            [Button(text="خریدهای من", callback_data="ch:1")],
                        ]
                    ),
                )
                return
            if draft.attempted_create is not None:
                existing = await api.checkout_lookup(
                    user.id, user.full_name[:120], key
                )
                if existing is not None:
                    await respond(
                        callback, intent_text(existing), intent_menu(existing)
                    )
                    return
                body = draft.attempted_create
            else:
                offer = draft.offer
                if mode == "t" and (
                    draft.funding_amount_rial is None
                    or (
                        draft.funding_destination_required
                        and draft.funding_destination_id is None
                    )
                ):
                    await respond(
                        callback,
                        "ابتدا مبلغ و مقصد واریز را انتخاب کنید.",
                        keyboard(
                            [
                                [
                                    Button(
                                        text="انتخاب واریز",
                                        callback_data=f"cf:{nonce}:{renewal}:1",
                                    )
                                ],
                            ]
                        ),
                    )
                    return
                if mode == "t" and offer.price_rial == 0:
                    await respond(
                        callback,
                        "این پلن رایگان است؛ خرید با کیف پول را انتخاب کنید.",
                    )
                    return
                body = CheckoutCreate(
                    request_key=key,
                    plan_id=offer.plan_id,
                    funding_mode="wallet_only"
                    if mode == "w"
                    else "approved_topup",
                    expected_offer_sha256=offer.offer_sha256,
                    expected_price_rial=offer.price_rial,
                    auto_renew=renewal == "1",
                    expiry_seconds=offer.default_expiry_seconds,
                    changed_offer_action="require_confirmation",
                    topup_amount_rial=draft.funding_amount_rial
                    if mode == "t"
                    else None,
                    destination_id=draft.funding_destination_id
                    if mode == "t"
                    else None,
                )
                drafts.remember_create(nonce, body)
            result = await api.checkout_create(
                user.id, user.full_name[:120], body
            )
            await respond(callback, intent_text(result), intent_menu(result))
        except BotApiError as exc:
            text = (
                "پاسخ خرید مشخص نیست؛ همان درخواست را دوباره بررسی کنید."
                if exc.code == "network"
                else "درخواست انجام نشد؛ وضعیت همین درخواست را بررسی کنید."
            )
            await respond(
                callback,
                text,
                keyboard(
                    [
                        [
                            Button(
                                text="بررسی دوبارهٔ همین درخواست",
                                callback_data=callback.data or "ch:1",
                            )
                        ],
                        [
                            Button(
                                text="لغو امن درخواست قبلی",
                                callback_data=f"cx:{nonce}:{plan_id}",
                            )
                        ],
                        [Button(text="خریدهای من", callback_data="ch:1")],
                    ]
                ),
            )

    @router.callback_query(F.data.startswith("ci:"))
    async def status(callback: CallbackQuery) -> None:
        id_text = (callback.data or "").split(":")[-1]
        if not id_text.isdecimal():
            await callback.answer()
            return
        user = callback.from_user
        try:
            result = await api.checkout_status(
                int(id_text),
                user.id,
                user.full_name[:120],
            )
            await respond(callback, intent_text(result), intent_menu(result))
        except BotApiError as exc:
            await failure(callback, exc)

    @router.callback_query(F.data.startswith("cc:"))
    async def cancel(callback: CallbackQuery) -> None:
        parts = (callback.data or "").split(":")
        if len(parts) != 3 or not all(part.isdecimal() for part in parts[1:]):
            await callback.answer()
            return
        _, id_text, revision = parts
        user = callback.from_user
        try:
            key = await asyncio.to_thread(
                lambda: sha256(
                    f"tgcancel:{user.id}:{id_text}:{revision}".encode()
                ).hexdigest()
            )
            result = await api.checkout_cancel(
                int(id_text),
                user.id,
                user.full_name[:120],
                CheckoutCancel(
                    request_key=key,
                    expected_revision=int(revision),
                ),
            )
            await respond(callback, intent_text(result), intent_menu(result))
        except BotApiError as exc:
            await failure(callback, exc)

    @router.callback_query(F.data.startswith("co:"))
    async def review(callback: CallbackQuery) -> None:
        id_text = (callback.data or "").split(":")[-1]
        if not id_text.isdecimal():
            await callback.answer()
            return
        user = callback.from_user
        try:
            intent = await api.checkout_status(
                int(id_text),
                user.id,
                user.full_name[:120],
            )
            if intent.state != "action_required":
                await respond(
                    callback, intent_text(intent), intent_menu(intent)
                )
                return
            offer = await api.checkout_offer(
                intent.plan_id, user.id, user.full_name[:120]
            )
            nonce = drafts.put(user.id, offer, intent)
            await respond(
                callback,
                offer_text(offer),
                keyboard(
                    [
                        [
                            Button(
                                text="تأیید شرایط و قیمت تازه",
                                callback_data=f"cr:{nonce}",
                            )
                        ],
                        [
                            Button(
                                text="بازگشت به وضعیت",
                                callback_data=f"ci:{intent.id}",
                            )
                        ],
                    ]
                ),
            )
        except BotApiError as exc:
            await failure(callback, exc)

    @router.callback_query(F.data.startswith("cr:"))
    async def reconfirm(callback: CallbackQuery) -> None:
        nonce = (callback.data or "").split(":")[-1]
        user = callback.from_user
        draft = drafts.get(user.id, nonce)
        if (
            draft is None
            or draft.checkout_id is None
            or draft.expected_revision is None
        ):
            await respond(
                callback, "پیشنهاد تازه را از خریدهای من دوباره بررسی کنید."
            )
            return
        try:
            result = await api.checkout_reconfirm(
                draft.checkout_id,
                user.id,
                user.full_name[:120],
                CheckoutReconfirm(
                    request_key=f"tgreconfirm:{user.id}:{nonce}",
                    expected_revision=draft.expected_revision,
                    expected_offer_sha256=draft.offer.offer_sha256,
                    expected_price_rial=draft.offer.price_rial,
                ),
            )
            await respond(callback, intent_text(result), intent_menu(result))
        except BotApiError as exc:
            await failure(callback, exc)

    @router.callback_query(F.data.startswith("ch:"))
    async def history(callback: CallbackQuery) -> None:
        page_text = (callback.data or "").split(":")[-1]
        if not page_text.isdecimal() or int(page_text) <= 0:
            await callback.answer()
            return
        page = int(page_text)
        user = callback.from_user
        try:
            rows, pages = await api.checkout_history(
                user.id,
                user.full_name[:120],
                page,
                drafts.limits.history_page_size,
            )
            buttons = [
                [
                    Button(
                        text=f"{fa(row.id)} · {_STATE[row.state]}",
                        callback_data=f"ci:{row.id}",
                    )
                ]
                for row in rows
            ]
            navigation = []
            if page > 1:
                navigation.append(
                    Button(text="قبلی", callback_data=f"ch:{page - 1}")
                )
            if page < pages:
                navigation.append(
                    Button(text="بعدی", callback_data=f"ch:{page + 1}")
                )
            if navigation:
                buttons.append(navigation)
            buttons.append([Button(text="بازگشت", callback_data="home")])
            await respond(
                callback,
                "خریدهای من:" if rows else "خریدی ثبت نشده است.",
                keyboard(buttons),
            )
        except BotApiError as exc:
            await failure(callback, exc)

    return router
