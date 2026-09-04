"""Общая обвязка миксинов MainWindow (v1.1.4 — разрез ui/main_window.py).

Миксины НЕ импортируют ui.main_window (цикл: main_window сам импортирует их),
поэтому доступ к глобальным модуля-фасада идёт через sys.modules по имени
модуля класса — в момент вызова фасад уже полностью загружен.

Это же — тестовый шов подмены: существующие тесты патчат атрибуты МОДУЛЯ
(``MW.SSHConnectDialog = Fake``, ``MW._ext_term = Fake`` и т.п.), и методы,
перенесённые в миксины, обязаны видеть подмену — иначе модалки/фейки не
сработали бы и offscreen-прогон зависал бы на настоящем диалоге.

Паттерн «модуль + колбэки» (прецеденты v0.9.9.4 сайдбар, v0.9.9.3 diagnostics):
миксин — только методы; всё общее состояние живёт на инстансе MainWindow
(duck-typing), владение зафиксировано комментарием в каждом миксине.
"""
import sys


def host_attr(self, name, default=None):
    """Прочитать атрибут модуля MainWindow (ui.main_window) в момент вызова.

    ``type(self).__module__`` — «ui.main_window» (пакетный импорт) или
    «main_window» (плоский запуск); sys.modules находит оба варианта.
    Возвращает ``default``, если модуль/атрибут недоступны.
    """
    mod = sys.modules.get(type(self).__module__)
    if mod is None:
        return default
    return getattr(mod, name, default)
