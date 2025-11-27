#!/usr/bin/env python

# SPDX-FileCopyrightText: 2025 Matvey Vyalkov
#
# SPDX-License-Identifier: WTFPL

import locale
import logging
import os
import shutil
import sys
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import cast

import egov66_timetable
from egov66_timetable import write_timetable
from egov66_timetable.utils import (
    get_current_week,
    read_settings,
    write_settings,
)
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Выводить дни недели в русской локали
locale.setlocale(locale.LC_TIME, "ru_RU.utf8")

logger = logging.getLogger("main")
logging.basicConfig(level=logging.INFO)


def gen_index(groups: list[str]) -> None:
    """
    Генерирует index.html со списком групп.
    """

    jinja_env = Environment(
        loader=FileSystemLoader(Path(__file__).parent),
        autoescape=select_autoescape(),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = jinja_env.get_template("index.html.jinja")

    html = template.render(
        groups=groups,
        updated_at=datetime.now().strftime("%x в %H:%M"),
    ).lstrip()
    with open("index.html", "w") as out:
        out.write(html)


def read_groups() -> list[str]:
    """
    Читает список групп из файла groups.txt.

    :returns: список групп
    """

    with open("groups.txt") as file:
        lines = (line.strip() for line in file.readlines())
        return list(filter(None, lines))


def main() -> None:
    week = get_current_week()
    logger.info("Текущая неделя: %s", week.week_id)

    groups = read_groups()
    logger.info("Прочитано %d групп", len(groups))

    settings = read_settings()
    logger.info("Прочитаны настройки")

    timetable_css = cast(
        Path, files(egov66_timetable).joinpath("static/styles.css")
    )
    if not timetable_css.is_file():
        logger.error("Стили расписания не найдены")
        sys.exit(1)

    shutil.copyfile(timetable_css, "pages/timetable.css")
    shutil.copyfile("styles.css", "pages/styles.css")
    logger.info("Скопированы стили")

    os.chdir("pages")

    for group in groups:
        logger.info("Загрузка расписания для группы %s", group)
        for offset in (+1, 0):
            write_timetable(group, settings=settings, offset=offset)
        shutil.copy(f"{group}/{week.week_id}.html", f"{group}/index.html")
    gen_index(groups)

    os.chdir("..")
    write_settings(settings)


if __name__ == "__main__":
    main()
