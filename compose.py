#!/usr/bin/env python

# SPDX-FileCopyrightText: 2025 Matvey Vyalkov
#
# SPDX-License-Identifier: WTFPL

import json
import locale
import logging
import shutil
import sqlite3
import sys
from contextlib import chdir
from datetime import datetime
from importlib.resources import files
from itertools import batched
from pathlib import Path
from typing import cast

import egov66_timetable
import jinja2
from egov66_timetable.callbacks.html import (
    html_callback,
    html_teacher_callback,
    load_teacher_template,
    load_template,
)
from egov66_timetable.callbacks.sqlite import (
    create_db,
    sqlite_callback,
    sqlite_teacher_callback,
)
from egov66_timetable.types import Teacher
from egov66_timetable.types.settings import Settings
from egov66_timetable.utils import (
    get_current_week,
    read_settings,
    write_settings,
)
from telethon.sync import TelegramClient

from telegram import telegram_callback

# Выводить дни недели в русской локали
locale.setlocale(locale.LC_TIME, "ru_RU.utf8")

logger = logging.getLogger("main")
logging.basicConfig(level=logging.INFO)

jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=jinja2.select_autoescape(),
    trim_blocks=True,
    lstrip_blocks=True,
)


def gen_index(groups: list[str], teachers: list[Teacher]) -> None:
    """
    Генерирует index.html со списком групп и преподавателей.

    :param groups: список групп
    :param teachers: список преподавателей
    """

    for dir in set(groups) | {teacher.translit for teacher in teachers}:
        shutil.copy(f"{dir}/{get_current_week().week_id}.html",
                    f"{dir}/index.html")

    html = jinja_env.get_template("index.html.jinja").render(
        groups=groups,
        teachers=teachers,
        updated_at=datetime.now().strftime("%x в %H:%M"),
    ).lstrip()
    with open("index.html", "w") as out:
        out.write(html)


def store_groups_in_db(cursor: sqlite3.Cursor, groups: list[str]) -> None:
    """
    Записывает список групп в базу данных.

    :param cur: курсор SQLite
    :param groups: список групп
    """

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS
          college_group(id TEXT PRIMARY KEY NOT NULL)
        """
    )
    cursor.execute("DELETE FROM college_group")
    cursor.executemany("INSERT INTO college_group(id) VALUES (?)",
                       list(batched(groups, n=1)))


def store_teachers_in_db(cursor: sqlite3.Cursor, teachers: list[Teacher]) -> None:
    """
    Записывает список преподавателей в базу данных.

    :param cur: курсор SQLite
    :param groups: список преподавателей
    """

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS
          college_teacher(
            id TEXT PRIMARY KEY NOT NULL,
            surname TEXT NOT NULL,
            given_name TEXT NOT NULL,
            patronymic TEXT
          )
        """
    )
    cursor.execute("DELETE FROM college_teacher")

    sql: str = (
        """
        INSERT INTO
          college_teacher(id, surname, given_name, patronymic)
        VALUES (?, ?, ?, ?)
        """
    )
    params = [(t.id, t.surname, t.given_name, t.patronymic) for t in teachers]
    cursor.executemany(sql, params)


def init_html_callback(settings: Settings) -> egov66_timetable.TimetableCallback:
    """
    Настраивает коллбэк-функцию для генерации HTML-файлов расписания студента.

    :param settings: настройки
    :returns: коллбэк-функция
    """

    base_template = load_template()
    week_template = jinja_env.get_template("week.html.jinja")

    return html_callback(settings, template=week_template,
                         base_template=base_template)


def init_html_teacher_callback(
    settings: Settings
) -> egov66_timetable.TeacherTimetableCallback:
    """
    Настраивает коллбэк-функцию для генерации HTML-файлов расписания
    преподавателя.

    :param settings: настройки
    :returns: коллбэк-функция
    """

    base_template = load_teacher_template()
    week_template = jinja_env.get_template("teacher_week.html.jinja")

    return html_teacher_callback(settings, template=week_template,
                                 base_template=base_template)


def read_groups() -> list[str]:
    """
    Читает список групп из файла groups.txt.

    :returns: список групп
    """

    with open("groups.txt") as file:
        lines = (line.strip()
                 for line in file.readlines()
                 if not line.startswith("#"))
        return list(filter(None, lines))


def read_teachers() -> list[Teacher]:
    """
    Читает список преподавателей из файла teachers.txt.

    :returns: список преподавателей
    """

    with open("teachers.txt") as file:
        lines = (line.strip()
                 for line in file.readlines()
                 if not line.startswith("#"))
        return [Teacher(*line.split(" ")) for line in lines if line]


def copy_styles() -> None:
    """
    Копирует стили CSS в директорию ``pages/``.
    """

    timetable_css = cast(
        Path, files(egov66_timetable).joinpath("static/styles.css")
    )
    if not timetable_css.is_file():
        logger.error("Стили расписания не найдены")
        sys.exit(1)

    shutil.copyfile(timetable_css, "pages/timetable.css")
    shutil.copyfile("styles.css", "pages/styles.css")


def main() -> None:
    groups = read_groups()
    logger.info("Прочитано %d групп", len(groups))

    teachers = read_teachers()
    logger.info("Прочитано %d преподавателей", len(teachers))

    settings = read_settings()
    logger.info("Прочитаны настройки")

    if not isinstance(db_path := settings.get("db_path"), str):
        logger.error("Параметр db_path не задан!")
        sys.exit(1)

    if not isinstance(tg_config := settings.get("telegram"), dict):
        logger.error("Параметры telegram не заданы!")
        sys.exit(1)

    if (aliases_file := Path("aliases.json")).is_file():
        settings["aliases"] = json.loads(aliases_file.read_text())
        logger.info("Прочитаны алиасы")

    copy_styles()
    logger.info("Скопированы стили")

    logger.info("Подключаюсь к базе данных")
    db = sqlite3.connect(db_path, timeout=30)
    cursor = create_db(db)
    db.commit()

    bot = (
        TelegramClient(
            tg_config["session_file"],
            tg_config["api_id"],
            tg_config["api_hash"],
        ).start(bot_token=tg_config["bot_token"])
    )
    bot.parse_mode = "html"

    student_callbacks = [
        init_html_callback(settings),
        sqlite_callback(cursor),
        telegram_callback(cursor, bot),
    ]
    teacher_callbacks = [
        init_html_teacher_callback(settings),
        sqlite_teacher_callback(cursor),
    ]

    with chdir("pages"):
        failures = egov66_timetable.get_timetable(
            groups, student_callbacks, settings=settings, offset_range=range(2)
        )
        db.commit()

        teacher_failures = egov66_timetable.get_teacher_timetable(
            teachers, teacher_callbacks, settings=settings, offset_range=range(2)
        )
        db.commit()

        logger.info("Генерирую страницы index.html")
        gen_index(groups, teachers)

    logger.info("Сохраняю настройки")
    write_settings(settings)

    logger.info("Сохраняю список групп в базе данных")
    store_groups_in_db(cursor, groups)
    db.commit()

    logger.info("Сохраняю список преподавателей в базе данных")
    store_teachers_in_db(cursor, teachers)
    db.commit()

    db.close()

    if failures or teacher_failures:
        logger.error("Ошибки: %s", failures)
        logger.error("Ошибки: %s", teacher_failures)
        sys.exit(1)


if __name__ == "__main__":
    main()
