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

APP_VERSION = "1.0"          # релиз приложения (лог старта, заголовок окна) — v1.0: Терминал v1 завершён (RC1–RC4 + финал): посячейный холст QWidget+QPainter, полная клавиатура + выделение/копирование, resize PTY, скроллбэк pyte.HistoryScreen, Быстрый запуск; финал: ключи terminal_* в ~/.sshmap/config.json (UI — v1.1) + полный acceptance tests/test_terminal_acceptance.py
APP_NAME = "SSH Map"         # базовое имя (заголовок окна)
VERSION_FORMAT = "0.9"       # версия формата JSON проекта (+ "background", storage/project.py)
