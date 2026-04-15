#!/usr/bin/env python

# SPDX-FileCopyrightText: 2025-2026 Matvey Vyalkov
#
# SPDX-License-Identifier: WTFPL

import json
import locale
import logging
import shutil
import sqlite3
import sys
from contextlib import chdir
from importlib.resources import files
from pathlib import Path
from typing import cast

import egov66_timetable
import loguru
from egov66_timetable.callbacks.sqlite import (
    create_db,
    sqlite_callback,
    sqlite_teacher_callback,
)
from egov66_timetable.utils import (
    read_settings,
    write_settings,
)

from iat_timetable.messengers import messengers_callback
from iat_timetable.utils import (
    LoggingFilter,
    gen_index,
    init_html_callback,
    init_html_teacher_callback,
    read_groups,
    read_teachers,
    store_groups_in_db,
    store_teachers_in_db,
)

# Выводить дни недели в русской локали
locale.setlocale(locale.LC_TIME, "ru_RU.utf8")

logger = logging.getLogger("iat_timetable")
logging.basicConfig(level=logging.DEBUG if __debug__ else logging.INFO)
for handler in logging.root.handlers:
    handler.addFilter(LoggingFilter())

if not __debug__:
    loguru.logger.remove()
    loguru.logger.add(sys.stderr, level="INFO")


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

    if (aliases_file := Path("aliases.json")).is_file():
        settings["aliases"] = json.loads(aliases_file.read_text())
        logger.info("Прочитаны алиасы")

    copy_styles()
    logger.info("Скопированы стили")

    logger.info("Подключаюсь к базе данных")
    db = sqlite3.connect(db_path, timeout=30)
    create_db(db)

    student_callbacks = [
        init_html_callback(settings),
        sqlite_callback(db),
        messengers_callback(db, settings),
    ]
    teacher_callbacks = [
        init_html_teacher_callback(settings),
        sqlite_teacher_callback(db),
    ]

    with chdir("pages"):
        failures = egov66_timetable.get_timetable(
            groups, student_callbacks, settings=settings, offset_range=range(2)
        )
        teacher_failures = egov66_timetable.get_teacher_timetable(
            teachers, teacher_callbacks, settings=settings, offset_range=range(2)
        )

        logger.info("Генерирую страницы index.html")
        gen_index(groups, teachers)

    logger.info("Сохраняю настройки")
    write_settings(settings)

    logger.info("Сохраняю список групп в базе данных")
    store_groups_in_db(db, groups)

    logger.info("Сохраняю список преподавателей в базе данных")
    store_teachers_in_db(db, teachers)

    db.close()

    if failures or teacher_failures:
        logger.error("Ошибки: %s", failures)
        logger.error("Ошибки: %s", teacher_failures)
        sys.exit(1)


if __name__ == "__main__":
    main()
