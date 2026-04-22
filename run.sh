#!/bin/bash

# SPDX-FileCopyrightText: 2025-2026 Matvey Vyalkov
#
# SPDX-License-Identifier: WTFPL

set -e

pushd "$(dirname "${0}")" >/dev/null
PYTHONOPTIMIZE=y timeout 5m uv run --with-requirements requirements.txt -U -m iat_timetable

pushd pages >/dev/null
git add .
git commit -m "Обновление данных"
git push -u origin pages
