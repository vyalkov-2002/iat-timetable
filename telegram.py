# SPDX-FileCopyrightText: 2026 Matvey Vyalkov
#
# SPDX-License-Identifier: WTFPL

import logging
import sqlite3
from datetime import timedelta

from egov66_timetable import TimetableCallback
from egov66_timetable.types import Lesson, Timetable, Week
from telethon.errors.rpcerrorlist import (
    ChatIdInvalidError,
    PeerIdInvalidError,
    UserIsBlockedError,
)
from telethon.sync import TelegramClient

EMOJI_DIGITS = [f"{num}\uFE0F\u20E3" for num in range(10)]

logger = logging.getLogger(__name__)


def compose_message(timetable: Timetable[Lesson], week: Week, day_num: int) -> str:
    """
    Создаёт уведомление об изменениях в расписании в формате HTML.

    :param timetable: расписание
    :param week: неделя
    :param day_num: номер дня недели (от 0 до 6)
    """

    date = week.monday + timedelta(days=day_num)
    date_str = date.strftime("%x")
    weekday = date.strftime("%A").lower()

    result = f"Новое расписание на <b>{date_str} ({weekday}):</b>\n"
    for lesson_num in range(max(timetable[day_num]) + 1):
        this_lesson = timetable[day_num].get(lesson_num) or (None, ("", "—"))
        classroom, name = this_lesson[1]
        result += f"\n{EMOJI_DIGITS[lesson_num + 1]} {name}"
        if classroom:
            result += f" — <i>{classroom}</i>"
    return result


def telegram_callback(cur: sqlite3.Cursor,
                      bot: TelegramClient) -> TimetableCallback:
    """
    Отправляет уведомления об изменениях в расписании в Telegram.

    Этот коллбэк должен срабатывать после :py:func:`sqlite_callback`.

    :param cur: курсор SQLite
    :returns: коллбэк-функция для раписания группы
    """

    def callback(timetable: Timetable[Lesson], group: str, week: Week) -> None:
        # Выбираем из базы данных строки по следующим условиям:
        # а) пара была добавлена ДО прошлой проверки
        # б) пара либо не удалена, либо удалена уже после прошлой проверки
        #
        # TODO: Показывать разницу между старым и новым расписанием.
        # cur.execute(
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
        cur.execute(
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
        updated_days = {day_num for (day_num,) in cur.fetchall()}

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
        subscribers: set[int] = {item[0] for item in cur.fetchall()}

        # Рассылаем уведомления подписчикам.
        logger.info("Отправляю %d уведомлений %d получателям",
                    len(updated_days), len(subscribers))
        for day_num in updated_days:
            message = compose_message(timetable, week, day_num)
            for chat_id in subscribers:
                try:
                    bot.send_message(chat_id, message)
                except (ChatIdInvalidError, PeerIdInvalidError,
                        UserIsBlockedError, ValueError):
                    logger.info("Отписываю чат %d", chat_id)
                    cur.execute(
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

        # Обновляем дату последней проверки.
        lesson_ids = ((lesson[0],) for day in timetable for lesson in day.values())
        cur.executemany(
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
