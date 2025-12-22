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
    load_template,
)
from egov66_timetable.callbacks.sqlite import (
    create_db,
    # sqlite_callback,
)
from egov66_timetable.utils import (
    get_current_week,
    read_settings,
    write_settings,
)

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


def gen_index(groups: list[str]) -> None:
    """
    Генерирует index.html со списком групп.

    :param groups: список групп
    """

    for group in groups:
        shutil.copy(f"{group}/{get_current_week().week_id}.html",
                    f"{group}/index.html")

    html = jinja_env.get_template("index.html.jinja").render(
        groups=groups,
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


def init_html_callback(settings) -> egov66_timetable.TimetableCallback:
    """
    Настраивает коллбэк-функцию для генерации HTML-файлов.

    :param settings: настройки
    :returns: коллбэк-функция
    """

    base_template = load_template()
    week_template = jinja_env.get_template("week.html.jinja")

    return html_callback(settings, template=week_template,
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
    cursor = create_db(db)
    db.commit()

    callbacks = [
        init_html_callback(settings),
        # sqlite_callback(cursor),
    ]

    with chdir("pages"):
        egov66_timetable.get_timetable(groups, callbacks, settings=settings,
                                       offset_range=range(2))
        db.commit()

        logger.info("Генерирую страницы index.html")
        gen_index(groups)

    logger.info("Сохраняю настройки")
    write_settings(settings)

    logger.info("Сохраняю список групп в базе данных")
    store_groups_in_db(cursor, groups)
    db.commit()

    db.close()


if __name__ == "__main__":
    main()
