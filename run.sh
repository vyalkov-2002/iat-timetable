#!/bin/bash

# SPDX-FileCopyrightText: 2025-2026 Matvey Vyalkov
#
# SPDX-License-Identifier: WTFPL

set -e

pushd "$(dirname "${0}")" >/dev/null
uv run --with-requirements requirements.txt -U -m compose

pushd pages >/dev/null
git add .
git commit -m "Обновление данных"
git push -u origin pages
