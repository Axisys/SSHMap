"""Автозаполнение данных о сервере v0.9: services/system_info_collector.py (бывш. smoke_test).

Часть сьюта, разбитого из smoke_test.py v0.6–v0.9.2 (см. INDEX.md).
  * парсеры чистых функций: parse_info_output (батч ---OS---/---CPU---/---RAM---/---DISK---),
    PRETTY_NAME/lsb_release fallback, одинарные кавычки, meminfo kB→bytes fallback,
    пустые/мусорные входы без crash; bytes_to_gb («8 gb», zero/negative → '');
  * INFO_BATCH содержит все секции + маркер END;
  * модель: новые поля os_name/cpu_model + backward-compat старых JSON, round-trip collapsed;
  * версия формата JSON = 0.9 (единая точка истины version.py), APP_VERSION 1.0.x (с v1.0RC1);
  * i18n-ключи v0.9 во всех трёх языках;
  * SystemInfoCollector: сигналы info_ready/info_failed, хранение data+password;
  * MainWindow: точки входа _collect_node_info/_on_info_ready/_on_info_failed.

Запуск: python tests/test_system_info.py   (из корня проекта) или python tests/run_all.py
"""
import json as _json_i18n_v09
import os
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

# ══ v0.9: автозаполнение данных о сервере (Linux) ═══════════════════════
print("== v0.9 system info collector ==")

# Парсеры — чистые функции, без Qt-событий
from services.system_info_collector import (
    parse_info_output, parse_os_release, parse_cpu, parse_ram_bytes,
    parse_disk_bytes, bytes_to_gb, INFO_BATCH,
)

# Фикстура: типичный вывод батча на Ubuntu
_fixture = """---OS---
Linux 6.8.0-40-generic x86_64 GNU/Linux
PRETTY_NAME="Ubuntu 24.04 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
---CPU---
4
model name\t: Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz
---RAM---
16777216000
MemTotal:       16394256 kB
---DISK---
""" + "\n" + str(107374182400) + """
size
---END---
"""
_info = parse_info_output(_fixture)
check("parse os_name from PRETTY_NAME", _info.get("os_name") == "Ubuntu 24.04 LTS", str(_info))
check("parse cpu cores", _info.get("cpu_cores") == "4", str(_info))
check("parse cpu model", "Xeon" in _info.get("cpu_model", ""), str(_info))
check("ram bytes → gb", _info.get("ram_gb") == "15.6 gb", str(_info.get("ram_gb")))
check("disk bytes → gb", _info.get("disk_gb") == "100 gb", str(_info.get("disk_gb")))

# lsb_release fallback (без "=")
check("os-release fallback to lsb_release",
      parse_os_release('Debian GNU/Linux 12\n') == "Debian GNU/Linux 12")
# одинарные кавычки в PRETTY_NAME
check("PRETTY_NAME single quotes stripped",
      parse_os_release("PRETTY_NAME='Alpine Linux'\nID=alpine\n") == "Alpine Linux")

# BusyBox/meminfo fallback: free недоступен → MemTotal из /proc/meminfo
_ram = parse_ram_bytes("MemTotal:       16394256 kB\n")
check("ram fallback meminfo kB→bytes", _ram == 16394256 * 1024, str(_ram))

# Пустые/мусорные входы не должны ронять парсер. NB: одиночная нечисловая
# строка без «=» трактуется как вывод lsb_release -ds (документированный
# fallback) — проверяем отсутствие crash, а не пустоту словаря.
check("empty output → empty dict", parse_info_output("") == {})
_garbage = parse_info_output("---OS---\n\x00\x1b[31m junk\n---END---\n")
check("garbage output does not crash", isinstance(_garbage, dict))

# bytes_to_gb: формат как у модели («8 gb», без хвостового .0)
check("bytes_to_gb exact", bytes_to_gb(8589934592) == "8 gb", str(bytes_to_gb(8589934592)))
check("bytes_to_gb zero/negative → ''", bytes_to_gb(0) == "" and bytes_to_gb(-5) == "")

# Батч содержит все секции и завершается маркером END
for _m in ("---OS---", "---CPU---", "---RAM---", "---DISK---", "---END---"):
    check(f"INFO_BATCH contains {_m}", _m in INFO_BATCH)

# Модель: новые поля + backward-compat старых JSON
from models.server import ServerData, server_data_from_dict, server_data_to_dict
_sd = server_data_from_dict({"id": "t1", "alias": "A", "host": "h", "user": "u"})
check("old JSON without os_name defaults", _sd.os_name == "" and _sd.cpu_model == "")
check("new fields serialize", "os_name" in server_data_to_dict(ServerData(id="x", alias="a", host="h", user="u")))
_d2 = server_data_from_dict({"id": "t2", "alias": "B", "host": "h2", "user": "u",
                             "os_name": "Alpine", "collapsed": True})
check("round-trip os_name/collapsed", _d2.os_name == "Alpine" and _d2.collapsed is True)

# Версия формата JSON — 0.9 (единая точка истины version.py); APP_VERSION — серия v1.0
# (переход к 1.0 выполнен в v1.0RC1: Терминал v1; формат JSON при этом НЕ меняется)
import version as _ver_mod
check("VERSION_FORMAT bumped to 0.9", getattr(_ver_mod, "VERSION_FORMAT", "") == "0.9",
      getattr(_ver_mod, "VERSION_FORMAT", "?"))
check("APP_VERSION is 1.0.x (v1.0RC1+)", getattr(_ver_mod, "APP_VERSION", "").startswith("1.0"),
      getattr(_ver_mod, "APP_VERSION", "?"))

# i18n: ключи v0.9 во всех трёх языках
for _lang_k in ("en", "ru", "zh"):
    _p = os.path.join(ROOT, "i18n", f"{_lang_k}.json")
    with open(_p, encoding="utf-8") as f:
        _d = _json_i18n_v09.load(f)
    _missing = [k for k in ("server.os", "ctx.collect_info", "status.info_running",
                            "status.info_running_auto", "status.info_collected",
                            "status.info_failed")
                if k not in _d]
    check(f"i18n v0.9 keys present ({_lang_k})", not _missing, str(_missing))

# Collector-класс: сигнатура и сигналы (без реального SSH)
from services.system_info_collector import SystemInfoCollector as _SIC
check("SystemInfoCollector signals", hasattr(_SIC, "info_ready") and hasattr(_SIC, "info_failed"))
_c = _SIC(ServerData(id="sig", alias="s", host="127.0.0.1", user="u"), password="")
check("collector stores data+password", _c.data.id == "sig" and _c.password == "")

# MainWindow: точки входа v0.9
from ui.main_window import MainWindow as _MW_v09
check("MainWindow has _collect_node_info/_on_info_ready/_on_info_failed",
      all(callable(getattr(_MW_v09, m, None))
          for m in ("_collect_node_info", "_on_info_ready", "_on_info_failed")))

finish()
