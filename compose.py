#!/usr/bin/env python

# SPDX-FileCopyrightText: 2025 Matvey Vyalkov
#
# SPDX-License-Identifier: WTFPL

import json
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
import jinja2
from egov66_timetable.callbacks.html import (
    html_callback,
    load_template,
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


def gen_index(groups: list[str], *, env: jinja2.Environment) -> None:
    """
    Генерирует index.html со списком групп.

    :param groups: список групп
    :param env: окружение Jinja
    """

    template = env.get_template("index.html.jinja")

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
    jinja_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=jinja2.select_autoescape(),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    base_template = load_template()
    week_template = jinja_env.get_template("week.html.jinja")

    week = get_current_week()
    logger.info("Текущая неделя: %s", week.week_id)

    groups = read_groups()
    logger.info("Прочитано %d групп", len(groups))

    settings = read_settings()
    logger.info("Прочитаны настройки")

    if (aliases_file := Path("aliases.json")).is_file():
        settings["aliases"] = json.loads(aliases_file.read_text())
        logger.info("Прочитаны алиасы")

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

    callbacks = [
        html_callback(settings, template=week_template,
                      base_template=base_template),
    ]
    egov66_timetable.get_timetable(groups, callbacks, settings=settings,
                                   offset_range=range(2))

    for group in groups:
        shutil.copy(f"{group}/{week.week_id}.html", f"{group}/index.html")
    gen_index(groups, env=jinja_env)

    os.chdir("..")
    write_settings(settings)


if __name__ == "__main__":
    main()
