#!/usr/bin/env python

# SPDX-FileCopyrightText: 2025-2026 Matvey Vyalkov
#
# SPDX-License-Identifier: WTFPL

import logging
import shutil
import sqlite3
from datetime import datetime
from itertools import batched
from pathlib import Path

import jinja2
from egov66_timetable import (
    TimetableCallback,
    TeacherTimetableCallback,
)
from egov66_timetable.callbacks.html import (
    html_callback,
    html_teacher_callback,
    load_teacher_template,
    load_template,
)
from egov66_timetable.types import Teacher
from egov66_timetable.types.settings import Settings
from egov66_timetable.utils import get_current_week

jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=jinja2.select_autoescape(),
    trim_blocks=True,
    lstrip_blocks=True,
)


class LoggingFilter(logging.Filter):

    def filter(self, record: logging.LogRecord) -> bool:
        if (
            record.levelno < logging.WARNING
            and not record.name.startswith("egov66_timetable")
            and not record.name.startswith("iat_timetable")
        ):
            if record.levelno == logging.INFO:
                return __debug__
            return False

        return True


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


def store_groups_in_db(conn: sqlite3.Connection, groups: list[str]) -> None:
    """
    Записывает список групп в базу данных.

    :param conn: база данных SQLite
    :param groups: список групп
    """

    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS
              college_group(id TEXT PRIMARY KEY NOT NULL)
            """
        )
        conn.execute("DELETE FROM college_group")
        conn.executemany("INSERT INTO college_group(id) VALUES (?)",
                         batched(groups, n=1))


def store_teachers_in_db(conn: sqlite3.Connection, teachers: list[Teacher]) -> None:
    """
    Записывает список преподавателей в базу данных.

    :param conn: база данных SQLite
    :param groups: список преподавателей
    """

    conn.execute(
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
    conn.execute("DELETE FROM college_teacher")

    sql: str = (
        """
        INSERT INTO
          college_teacher(id, surname, given_name, patronymic)
        VALUES (?, ?, ?, ?)
        """
    )
    params = ((t.id, t.surname, t.given_name, t.patronymic) for t in teachers)
    conn.executemany(sql, params)
    conn.commit()


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


def init_html_callback(settings: Settings) -> TimetableCallback:
    """
    Настраивает коллбэк-функцию для генерации HTML-файлов расписания студента.

    :param settings: настройки
    :returns: коллбэк-функция
    """

    base_template = load_template()
    week_template = jinja_env.get_template("week.html.jinja")

    return html_callback(settings, template=week_template,
                         base_template=base_template)


def init_html_teacher_callback(settings: Settings) -> TeacherTimetableCallback:
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
