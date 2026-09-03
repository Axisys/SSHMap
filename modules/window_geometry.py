# -*- coding: utf-8 -*-
"""v1.1.2RC3 (AUDIT U2): сохранение/восстановление размеров окон.

Пользовательское замечание U2 («сохранение размеров окна, главное окно и терминал»):
окна каждый старт получали дефолтный размер (главное — resize(1200, 850), терминал —
resize(800, 600)), и растяжка не переживала перезапуск. Фикс: при закрытии окна
saveGeometry()/saveState() пишутся в ~/.sshmap/config.json под ключом, при старте /
создании окна — восстанавливаются.

Ключи (один на окно, оба значения внутри):
  * ui_window_geometry_main      — главное окно (MainWindow);
  * ui_window_geometry_terminal  — окна терминала (SSHTerminalWindow; все терминалы
                                   делят ключ — запоминается последний закрытый).

Значение ключа — JSON-объект {"geometry": <base64>, "state": <base64>}:
  * geometry — QByteArray saveGeometry() (позиция + размер окна);
  * state    — QByteArray saveState() (состояние QMainWindow: максимизировано/норма,
               layout доков/тулбаров).

QByteArray не JSON-сериализуется напрямую → base64. restoreGeometry()/restoreState()
принимают QByteArray обратно (симметричная пара Qt API).

Headless-friendly и teardown-устойчив: обе функции НИКОГДА не бросают — нет ключа /
битое значение / RuntimeError C++-объекта → no-op + False. Сохранение/восстановление
геометрии не должно ронять старт или закрытие приложения.
"""

import base64


def _qba_to_b64(qbytearray) -> str:
    """QByteArray → base64-строка (ASCII). Пусто/None → ''."""
    try:
        return base64.b64encode(bytes(qbytearray)).decode("ascii")
    except Exception:  # noqa: BLE001 — teardown/битый объект не роняет сохранение
        return ""


def _b64_to_qba(b64str):
    """base64-строка → QByteArray; битое/пусто → None.

    ВАЖНО (проверено прогоном, PySide6 6.11): fromBase64 ждёт BASe64-ТЕКСТ
    (ascii-байты строки), а НЕ уже декодированные сырые байты — сырые байты
    Qt интерпретирует как base64-алфавит и молча вернёт ПУСТОЙ QByteArray.
    Python-валидация (validate=True) — быстрая проверка «это вообще base64»
    до вызова Qt; сам декод делает Qt по исходной строке.
    """
    from PySide6.QtCore import QByteArray
    if not isinstance(b64str, str) or not b64str:
        return None
    try:
        raw = base64.b64decode(b64str.encode("ascii"), validate=True)
    except Exception:  # noqa: BLE001 — не-base64 → нет данных
        return None
    if not raw:
        return None
    qba = QByteArray.fromBase64(b64str.encode("ascii"))
    if len(qba) == 0:   # Qt-декодер всё равно отказался — битые данные
        return None
    return qba


def save_window_geometry(key: str, window) -> bool:
    """Сохранить saveGeometry()/saveState() окна в config.json под ключом key.

    window — QMainWindow (MainWindow / SSHTerminalWindow). True — записано;
    False — окно не дало данных или запись конфига не удалась. Никогда не бросает.
    """
    try:
        from i18n import save_config
    except Exception:  # noqa: BLE001 — flat-раскладка без i18n — нет куда писать
        return False
    try:
        geom = _qba_to_b64(window.saveGeometry())
        state = _qba_to_b64(window.saveState())
    except Exception:  # noqa: BLE001 — RuntimeError C++-объекта (teardown) и пр.
        return False
    if not geom and not state:
        return False
    try:
        return bool(save_config({key: {"geometry": geom, "state": state}}))
    except Exception:  # noqa: BLE001 — save_config сам не бросает, но на всякий случай
        return False


def restore_window_geometry(key: str, window) -> bool:
    """Восстановить геометрию/состояние окна из config.json (ключ key).

    True — что-то восстановлено (geometry и/или state); False — ключа нет, значение
    битое или окно не приняло данные. Никогда не бросает; при False окно остаётся с
    дефолтным размером (вызванный ранее resize()).
    """
    try:
        from i18n import load_config
    except Exception:  # noqa: BLE001 — flat-раскладка без i18n
        return False
    try:
        data = load_config().get(key)
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(data, dict):
        return False

    restored = False
    geom = _b64_to_qba(data.get("geometry"))
    if geom is not None:
        try:
            window.restoreGeometry(geom)
            restored = True
        except Exception:  # noqa: BLE001 — teardown/битый QByteArray
            pass
    state = _b64_to_qba(data.get("state"))
    if state is not None:
        try:
            window.restoreState(state)
            restored = True
        except Exception:  # noqa: BLE001
            pass
    return restored
