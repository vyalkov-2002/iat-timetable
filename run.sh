#!/bin/bash

# SPDX-FileCopyrightText: 2025 Matvey Vyalkov
#
# SPDX-License-Identifier: WTFPL

set -e

pushd "$(dirname "${0}")" >/dev/null
python -m venv --without-pip venv
source venv/bin/activate

uv pip install -U git+https://altlinux.space/acme-corp/ecp.egov66.ru-timetable telethon[cryptg] || true
python -O compose.py

pushd pages >/dev/null
git add .
git commit -m "Обновление данных"
git push -u origin pages
