# SPDX-FileCopyrightText: 2026 Matvey Vyalkov
#
# SPDX-License-Identifier: WTFPL

import asyncio
import html
import logging
import sqlite3
from collections.abc import Callable
from datetime import timedelta
from typing import Protocol, Self
from urllib.parse import quote as q

import vkbottle
import vkbottle.tools.formatting as vk_markup
from egov66_timetable import TimetableCallback
from egov66_timetable.types import Lesson, Timetable, Week
from egov66_timetable.types.settings import Settings
from telethon.errors.rpcerrorlist import (
    ChatIdInvalidError,
    PeerIdInvalidError,
    UserIsBlockedError,
)
from telethon import TelegramClient

EMOJI_DIGITS = [f"{num}\uFE0F\u20E3" for num in range(10)]

logger = logging.getLogger(__name__)


class StrLike(Protocol):
    def __str__(self) -> str:
        ...

    def __add__(self, other: str | Self) -> Self:
        ...

    def __radd__(self, other: str | Self) -> Self:
        ...


def html_bold(string: str) -> str:
    return f"<b>{string}</b>"


def html_italic(string: str) -> str:
    return f"<i>{string}</i>"


def html_url(string: str, href: str) -> str:
    return f'<a href="{href}">{string}</a>'


def compose_message[T: StrLike](
    timetable: Timetable[Lesson], group: str, week: Week, day_num: int, *,
    bold: Callable[[str], str | T] = html_bold,
    italic: Callable[[str], str | T] = html_italic,
    url: Callable[[str, str], str | T] = html_url,
    escape: Callable[[str], str] = html.escape
) -> str | T:
    """
    Создаёт уведомление об изменениях в расписании.

    :param timetable: расписание
    :param group: номер группы
    :param week: неделя
    :param day_num: номер дня недели (от 0 до 6)
    :param bold: функция для создания жирного текста
    :param italic: функция для создания курсивного текста
    :param url: функция для создания гиперссылок
    :param escape: функция для экранирования данных
    """

    e = escape

    date = week.monday + timedelta(days=day_num)
    date_str = date.strftime("%x")
    weekday = date.strftime("%A").lower()

    result = (
        "Новое расписание на "
        + bold("{} ({}):".format(e(date_str), e(weekday))) + "\n"
    )
    for lesson_num in range(max(timetable[day_num]) + 1):
        this_lesson = timetable[day_num].get(lesson_num) or (None, ("", "—"))
        classroom, name = this_lesson[1]
        result += f"\n{EMOJI_DIGITS[lesson_num + 1]} {e(name)}"
        if classroom:
            result += " — " + italic(e(classroom))

    link = (
        "https://acme-corp.altlinux.team/iat-timetable/{}/{}.html"
        .format(q(group), q(week.week_id))
    )
    result += "\n\n" + url("Расписание на сайте", link)

    return result


def messengers_callback(conn: sqlite3.Connection,
                        settings: Settings) -> TimetableCallback:
    """
    Отправляет уведомления об изменениях в расписании в мессенджеры.

    Этот коллбэк должен срабатывать после :func:`sqlite_callback`.

    :param conn: база данных SQLite
    :param settings: настройки
    :returns: коллбэк-функция для раписания группы
    """

    if not isinstance(vk_token := settings.get("vk_token"), str):
        raise RuntimeError("Параметр vk_token не задан!")

    if not isinstance(tg_config := settings.get("telegram"), dict):
        raise RuntimeError("Параметры telegram не заданы!")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    vk_api = vkbottle.API(vk_token)
    tg_bot = (
        TelegramClient(
            tg_config["session_file"],
            tg_config["api_id"],
            tg_config["api_hash"],
            loop=loop,
        ).start(bot_token=tg_config["bot_token"])
    )
    tg_bot.parse_mode = "html"

    async def send_to_vk_users(message: str | vk_markup.Format, subscribers: set[int]) -> None:
        kwargs: dict[str, object] = {}
        if isinstance(message, vk_markup.Format):
            kwargs["format_data"] = message.as_raw_data()

        for peer_id in subscribers:
            await vk_api.messages.send(  # type: ignore[call-overload]
                user_id=peer_id, random_id=0, message=str(message), **kwargs
            )

    async def send_to_tg_users(message: str, subscribers: set[int]) -> None:
        for chat_id in subscribers:
            try:
                await tg_bot.send_message(chat_id, message)
            except (ChatIdInvalidError, PeerIdInvalidError, UserIsBlockedError, ValueError):
                logger.info("Отписываю чат %d", chat_id)
                with conn:
                    conn.execute(
                        """
                        UPDATE
                          telegram_chat
                        SET
                          subscribed = FALSE
                        WHERE
                          id = ?
                        """,
                        [chat_id]
                    )

    def callback(timetable: Timetable[Lesson], group: str, week: Week) -> None:
        # Выбираем из базы данных строки по следующим условиям:
        # а) пара была добавлена ДО прошлой проверки
        # б) пара либо не удалена, либо удалена уже после прошлой проверки
        #
        # TODO: Показывать разницу между старым и новым расписанием.
        # conn.execute(
        #     """
        #     SELECT
        #       id, classroom, name, day_num, lesson_num
        #     FROM
        #       lesson
        #     WHERE
        #       group_id = ? AND week_id = ?
        #       AND last_checked >= last_updated
        #       AND (
        #         obsolete_since IS NULL
        #         OR obsolete_since > last_checked
        #       )
        #     """,
        #     [group, week]
        # )

        # Выбираем из базы данных обновления в расписании по следующим условиям:
        # а) пара была добавлена ПОСЛЕ прошлой проверки
        # б) пара не удалена
        cur = conn.execute(
            """
            SELECT DISTINCT
              day_num
            FROM
              lesson
            WHERE
              group_id = ? AND week_id = ?
              AND last_checked < last_updated
              AND obsolete_since IS NULL
            """,
            [group, week.week_id]
        )
        updated_days = {day_num for (day_num,) in cur}

        # Получаем ID подписчиков в телеграме.
        cur.execute(
            """
            SELECT
             id
            FROM
             telegram_chat
            WHERE
             group_id = ? AND subscribed = TRUE
            """,
            [group]
        )
        tg_subscribers: set[int] = {item[0] for item in cur}

        # Получаем ID подписчиков вконтакте.
        cur.execute(
            """
            SELECT
             id
            FROM
             vk_chat
            WHERE
             group_id = ? AND subscribed = TRUE
            """,
            [group]
        )
        vk_subscribers: set[int] = {item[0] for item in cur}

        # Рассылаем уведомления подписчикам.
        if len(updated_days) * (len(vk_subscribers) + len(tg_subscribers)) != 0:
            logger.info(
                "Отправляю %d уведомлений %d+%d получателям",
                len(updated_days), len(vk_subscribers), len(tg_subscribers)
            )
        for day_num in updated_days:
            tg_message = compose_message(timetable, group, week, day_num)
            vk_message = compose_message(
                timetable, group, week, day_num,
                escape=str, bold=vk_markup.bold, italic=vk_markup.italic,
                url=lambda string, href: vk_markup._format(string, "url", {"url": href})
            )
            loop.run_until_complete(
                asyncio.gather(
                    send_to_vk_users(vk_message, vk_subscribers),
                    send_to_tg_users(tg_message, tg_subscribers),
                )
            )

        # Обновляем дату последней проверки.
        lesson_ids = ((lesson[0],) for day in timetable for lesson in day.values())
        with conn:
            conn.executemany(
                """
                UPDATE
                  lesson
                SET
                  last_checked = CURRENT_TIMESTAMP
                WHERE
                  id = ?
                """,
                lesson_ids
            )

    return callback
