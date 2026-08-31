# -*- coding: utf-8 -*-
"""Единая точка истины для версии приложения (AUDIT v0.8.3, средняя #1).

Ранее версия была размазана по main.py-логу, i18n-ключу title.main_window,
полю version в JSON проекта (storage/project.py) и комментариям — что уже
приводило к рассинхронизации (код говорил v0.8.1 при релизе v0.8.3).

Теперь все потребители импортируют отсюда:

    from version import APP_VERSION          # плоский запуск (из корня)
    from ..version import APP_VERSION        # из пакета

VERSION_FORMAT хранит версию ФОРМАТА JSON проекта (меняется только при
реальном изменении схемы; формат не обязан совпадать с релизом).
"""

APP_VERSION = "0.9.9.7"      # релиз приложения (лог старта, заголовок окна) — v0.9.9.7: PDF-экспорт карты (MapScene.render_to_pdf, QPdfWriter поверх render_to_pixmap), пункт меню «Файл», tests/test_pdf_export.py
APP_NAME = "SSH Map"         # базовое имя (заголовок окна)
VERSION_FORMAT = "0.9"       # версия формата JSON проекта (+ "background", storage/project.py)
