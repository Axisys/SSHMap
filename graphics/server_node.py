from typing import Optional

try:
    from ..models.server import ServerData
except ImportError:
    from models.server import ServerData

try:
    from ..modules.ssh_worker import SSHWorker
except ImportError:
    from modules.ssh_worker import SSHWorker

from PySide6.QtCore import Qt, QPointF, QRectF, QVariantAnimation
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen, QFontMetrics, QTransform
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsItemGroup, QGraphicsItem,
    QGraphicsPathItem, QGraphicsTextItem,
)


def _t(key: str) -> str:
    """Безопасный i18n-лук: при недоступности i18n возвращает сам ключ."""
    try:
        from i18n import t as _translate
        return _translate(key)
    except Exception:
        return key


class ServerNode(QGraphicsItemGroup):
    """Визуальный узел сервера на карте."""

    MIN_NODE_WIDTH = 180
    MIN_NODE_HEIGHT = 130
    # v0.8.4 (DESIGN.md §D): высота свёрнутой плашки — одна строка:
    # [иконка] alias @host … [●статус][SSH-точка][▾шеврон]
    COLLAPSED_HEIGHT = 46
    # Ревью-фикс v0.8.0 (#4): потолок ширины карточки — длинный alias/host/comment
    # больше не растягивает узел бесконечно; не влезший текст elide'ится (…), полный
    # текст доступен в tooltip (наведение на сокращённую подпись).
    MAX_NODE_WIDTH = 360

    # Раскладка для elide: откуда стартуют подписи (см. _build_appearance) и зазор до
    # зоны точек-индикаторов справа [W-DOT_ZONE_LEFT, W-10] — точки имеют z=5 и без
    # ограничения накрывали бы хвост длинного alias/host (было в ревью v0.8).
    LABEL_X = 55.0            # x подписей alias / host
    INFO_X = 10.0             # x инфо-блока
    DOT_ZONE_LEFT = 46.0      # левый край точки статуса: W - 46 (см. update_appearance)
    ELIDE_GAP = 4.0           # зазор от конца текста до точек
    # UI polish v0.9.x: иконка сервера крупновата в обоих режимах — масштабируем
    # круг+глиф на 70% (40 px -> 28 px) вокруг центра исходного круга (30, 30).
    ICON_SCALE = 0.70
    # v0.8.4: вертикальная центровка точек в свёрнутой строке (подгонка:
    # подняты на и сдвинуты влево, чтобы не налезали на шеврон).
    COLLAPSED_DOT_Y = -7.0
    COLLAPSED_DOT_DX = -21.0  # сдвиг точек влево относительно развёрнутой позиции
    # Свёрнутая строка: иконка приподнята, чтобы визуально центрироваться с текстом.
    COLLAPSED_ICON_DY = -8.0

    # UI polish: скругление углов карточки и «тень» — узкая полоска под нижним краем.
    # Тень рисуется ВНУТРИ boundingRect (Qt клипует дочерних элементов по нему),
    # поэтому boundingRect() расширен вниз на SHADOW_BOTTOM px; стрелки при этом
    # доходят ровно до границы тени, а не «в вис» (edge_point работает от boundingRect).
    CORNER_RADIUS = 10.0
    SHADOW_BOTTOM = 3.0

    COLOR_BG = QColor("#1e293b")
    COLOR_BORDER = QColor("#3b82f6")
    COLOR_SELECTED = QColor("#f59e0b")
    COLOR_HOVER = QColor("#60a5fa")
    # v0.9.6: акцент «Показать на карте» (сайдбар) — рамка-вспышка. Голубой,
    # отличимый от янтарного выделения (#f59e0b): узел уже выделен, и вспышка
    # должна читаться как отдельный сигнал «тут он». Тот же #38bdf8, что у рамки
    # rectangle-выделения MapView — единый акцент приложения.
    REVEAL_COLOR = QColor("#38bdf8")
    # v0.9.8: поиск по карте (Ctrl+F) — статическая рамка совпавших узлов.
    # Тот же #38bdf8 (единый акцент): совпадения читаются мгновенно, а текущий
    # результат поиска дополнительно выделен янтарём (#f59e0b) + вспышка reveal_flash.
    SEARCH_MATCH_COLOR = QColor("#38bdf8")
    COLOR_TEXT = QColor("#e2e8f0")
    COLOR_LABEL = QColor("#94a3b8")
    # UI polish: «тень» под карточкой и серый цвет точек-индикаторов до проверки.
    COLOR_SHADOW = QColor(0, 0, 0, 110)
    COLOR_DOT_IDLE = QColor("#64748b")

    # v0.7.1: цвета рамки по статусу доступности (StatusChecker).
    # warn — жёлтый, отличимый от янтарного COLOR_SELECTED (#f59e0b):
    # в один момент времени показывается либо выделение, либо статус.
    STATUS_COLORS = {
        "online": QColor("#22c55e"),   # зелёный: TCP + SSH баннер
        "warn": QColor("#facc15"),     # жёлтый: порт открыт, баннера нет
        "offline": QColor("#ef4444"),  # красный: недоступен
    }

    # v0.9.4: цвета тегов/ролей окружений. Известные роли — фиксированные цвета;
    # произвольные теги — детерминированный цвет из палитры по хэшу имени.
    TAG_PALETTE = [
        QColor("#22c55e"), QColor("#3b82f6"), QColor("#a855f7"),
        QColor("#f97316"), QColor("#06b6d4"), QColor("#ec4899"),
    ]
    TAG_COLORS = {
        "prod":    QColor("#ef4444"),  # красный — боевое окружение
        "staging": QColor("#facc15"),  # жёлтый — предпрод
        "dev":     QColor("#22c55e"),  # зелёный — разработка
        "test":    QColor("#a855f7"),  # фиолетовый — тестовый контур
        "backup":  QColor("#06b6d4"),  # голубой — бэкап-реплика
        "dmz":     QColor("#f97316"),  # оранжевый — демилитаризованная зона
    }
    # Полоска тегов на карточке: вертикальные сегменты вдоль левого края.
    TAG_STRIP_WIDTH = 5.0

    @staticmethod
    def tag_color(tag: str) -> QColor:
        """Цвет тега: известная роль — свой цвет, прочие — по хэшу из палитры.

        zlib.crc32, а не hash(): hash() строк солёный per-process — цвета
        произвольных тегов менялись бы от запуска к запуску.
        """
        import zlib
        key = (tag or "").strip().lower()
        c = ServerNode.TAG_COLORS.get(key)
        if c is not None:
            return QColor(c)
        h = zlib.crc32(key.encode("utf-8"))
        return QColor(ServerNode.TAG_PALETTE[h % len(ServerNode.TAG_PALETTE)])

    def __init__(self, data: ServerData, parent=None):
        super().__init__(parent)
        self.data = data
        self._current_width = self.MIN_NODE_WIDTH
        self._current_height = self.MIN_NODE_HEIGHT  
        
        self._selected = False
        self._hover = False
        # v0.7.1: статус доступности (online/warn/offline) — "" пока не проверен
        self._status = ""
        # v0.9.8: поиск по карте (Ctrl+F) — True, если узел совпадает с активным запросом
        self._search_matched = False

        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setPos(data.x, data.y)

        self._ssh_worker: Optional[SSHWorker] = None
        # v0.9.4: сегменты полоски тегов (создаются лениво в _rebuild_tag_strip)
        self._tag_segments: list = []
        # v0.7.1: пульс-анимация смены статуса — fade-out оверлея (opacity 1 -> 0).
        # Вариант QPropertyAnimation(target=QGraphicsItem) в PySide6 6.11 не работает:
        # у C++ QGraphicsItem* нет метаобъектной интроспекции свойств ("non-existing
        # property opacity"), поэтому используем QVariantAnimation + valueChanged.
        self._pulse_anim: Optional[QVariantAnimation] = None

        self._build_appearance()
        # v0.9.4: полоска тегов при создании (update_appearance может не сменить
        # геометрию и не вызвать _rebuild_frame_paths)
        self._rebuild_tag_strip()

    def _build_appearance(self):
        # UI polish: «тень» под карточкой — узкая полоска ниже нижнего края.
        # Рисуется внутри boundingRect (Qt клипует дочерних элементов по нему),
        # поэтому boundingRect расширен вниз на SHADOW_BOTTOM px.
        self._shadow = QGraphicsPathItem(self)
        self._shadow.setPen(QPen(Qt.PenStyle.NoPen))
        self._shadow.setBrush(QBrush(self.COLOR_SHADOW))
        self._shadow.setZValue(-2)

        # Фон узла (скруглённый; перо — рамка по выделению/статусу, см. _state_pen).
        # QGraphicsRectItem заменён на PathItem: скругление углов (UI polish),
        # pen/brush для PathItem работают так же.
        self._bg = QGraphicsPathItem(self)
        self._bg.setPen(QPen(Qt.transparent, 2))
        self._bg.setBrush(QBrush(self.COLOR_BG))
        self._bg.setZValue(-1)

        # v0.7.1: оверлей «пульса» при смене статуса — рамка поверх фона (скруглённая).
        # Fade-out opacity 1 -> 0 (QVariantAnimation), затем прячется.
        self._pulse = QGraphicsPathItem(self)
        self._pulse.setPen(QPen(self.STATUS_COLORS["offline"], 3))
        self._pulse.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._pulse.setZValue(-0.5)
        self._pulse.hide()

        # Иконка: круг + векторный глиф «сервер» (UI polish: эмодзи убраны —
        # Segoe UI Emoji на Linux рендерится монохромно/квадратами, а при зуме
        # пикселизуется; QPainterPath кроссплатформен и чёткий на любом масштабе).
        self._icon = QGraphicsEllipseItem(10, 10, 40, 40, self)
        self._icon.setPen(QPen(self.COLOR_BORDER, 2))
        self._icon.setBrush(QBrush(QColor("#2563eb")))

        glyph_pen = QPen(self.COLOR_TEXT, 1.6)
        glyph_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._glyph = QGraphicsPathItem(self)
        self._glyph.setPen(glyph_pen)
        self._glyph.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._glyph.setZValue(2)
        self._set_server_glyph()
        # UI polish v0.9.x: уменьшенная иконка — масштабируем и круг, и глиф
        # вокруг центра круга, чтобы глиф остался в центре.
        icon_tr = QTransform()
        icon_tr.translate(30.0, 30.0)
        icon_tr.scale(self.ICON_SCALE, self.ICON_SCALE)
        icon_tr.translate(-30.0, -30.0)
        self._icon.setTransform(icon_tr)
        self._glyph.setTransform(icon_tr)

        # Alias
        self._alias = QGraphicsTextItem(self.data.alias or "Unnamed", self)
        self._alias.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self._alias.setDefaultTextColor(self.COLOR_TEXT)
        self._alias.setPos(55, 18)

        # Точка статуса доступности (UI polish): левее SSH-точки — в свёрнутом виде
        # и при мелком зуме читается быстрее 2px-рамки. Серая — пока не проверялся.
        self._status_dot = QGraphicsEllipseItem(0, 23, 14, 14, self)
        self._status_dot.setPen(QPen(Qt.PenStyle.NoPen))
        self._status_dot.setBrush(QBrush(self.COLOR_DOT_IDLE))
        self._status_dot.setZValue(5)

        # SSH статус индикатор (зелёный кружок - подключено)
        self._ssh_status = QGraphicsEllipseItem(0, 23, 14, 14, self)
        self._ssh_status.setPen(QPen(Qt.PenStyle.NoPen))
        self._ssh_status.setBrush(QBrush(self.COLOR_DOT_IDLE))  # Серый - не подключено
        self._ssh_status.setZValue(5)

        # Текстовая плашка (инициализация); фон — скруглённый (UI polish)
        self._info = QGraphicsTextItem("", self)
        self._info.setFont(QFont("Consolas", 8))
        self._info.setDefaultTextColor(self.COLOR_LABEL)
        self._info_bg = QGraphicsPathItem(self)
        self._info_bg.setPen(QPen(Qt.PenStyle.NoPen))
        self._info_bg.setBrush(QBrush(QColor(15, 23, 42, 150)))
        self._info_bg.setZValue(0)
        self._info.setZValue(1)

        # Host под алиасом
        self._host_label = QGraphicsTextItem(f"@{self.data.host}", self)
        self._host_label.setFont(QFont("Consolas", 8))
        self._host_label.setDefaultTextColor(QColor("#64748b"))
        self._host_label.setPos(55, 36)

        # UI polish: декоративная «кнопка SSH» (🔒) удалена — она не кликалась и
        # вводила в заблуждение; подключение SSH — по двойному клику / ПКМ-меню.

        # v0.8.4 (DESIGN.md §D): шеврон сворачивания в правом верхнем углу.
        # Позиция/геометрия выставляются в update_appearance() под текущий режим.
        self._chevron = QGraphicsPathItem(self)
        self._chevron.setPen(QPen(self.COLOR_LABEL, 1.8))
        self._chevron.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._chevron.setZValue(5)

        # Первичный расчет высоты и позиций
        self.update_appearance()

    def _set_server_glyph(self):
        """Векторный глиф «сервер» внутри круглой иконки (два юнита + LED)."""
        path = QPainterPath()
        path.addRoundedRect(QRectF(21, 22, 18, 7), 2.0, 2.0)
        path.addRoundedRect(QRectF(21, 31, 18, 7), 2.0, 2.0)
        for cy in (25.5, 34.5):
            path.addEllipse(QPointF(36.5, float(cy)), 0.9, 0.9)
        self._glyph.setPath(path)

    @staticmethod
    def _rounded(x: float, y: float, w: float, h: float, r: float) -> QPainterPath:
        """Скруглённый прямоугольник. PySide6-нюанс: addRoundedRect() возвращает None
        (в Qt C++ — QPainterPath&), поэтому путь собираем через отдельный объект."""
        path = QPainterPath()
        path.addRoundedRect(float(x), float(y), max(float(w), 1.0), max(float(h), 1.0),
                            float(r), float(r))
        return path

    def _rebuild_frame_paths(self, width: float, height: float):
        """Пересобрать скруглённые пути фона/пульса/тени при смене геометрии."""
        r = self.CORNER_RADIUS
        self._bg.setPath(self._rounded(0, 0, width, height, r))
        # Тень: верх скрыт под карточкой, видна полоска y ∈ [height, height+SHADOW_BOTTOM]
        self._shadow.setPath(self._rounded(8, 5, max(width - 16, 20),
                                           height + self.SHADOW_BOTTOM - 5, r + 2))
        # Пульс следует за фоном (v0.7.1) — та же скруглённая рамка
        self._pulse.setPath(self._rounded(0, 0, width, height, r))

        # v0.9.4: полоска тегов вдоль левого края (пересобрать сегменты)
        if getattr(self, "_tag_segments", None) is not None:
            self._rebuild_tag_strip()

    def _rebuild_tag_strip(self):
        """v0.9.4: вертикальная полоска из цветных сегментов по data.tags.

        Сегменты делят высоту карточки поровну (макс. 4 видимых тега — дальше
        полоска теряет читаемость); рисуется поверх фона (z=-0.8), под контентом.
        """
        tags = (getattr(self.data, "tags", None) or [])[:4]
        n_needed = len(tags)
        while len(self._tag_segments) < n_needed:
            from PySide6.QtWidgets import QGraphicsRectItem
            item = QGraphicsRectItem(self)
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setZValue(-0.8)
            self._tag_segments.append(item)
        h_total = max(float(self._current_height), 1.0)
        seg_h = h_total / n_needed if n_needed else 0.0
        for i, item in enumerate(self._tag_segments):
            if i < n_needed:
                item.setRect(0.0, i * seg_h, self.TAG_STRIP_WIDTH, seg_h + 0.01)
                item.setBrush(QBrush(ServerNode.tag_color(tags[i])))
                item.show()
            else:
                item.hide()

    def refresh_tags(self):
        """v0.9.4: публичная точка обновления полоски после правки data.tags."""
        self._rebuild_tag_strip()
        self.update()

    def _state_pen(self):
        if self._selected:
            return QPen(self.COLOR_SELECTED, 3)
        # v0.9.8: совпадение поиска по карте — акцентная рамка (ниже выделения:
        # текущий результат поиска одновременно выделен и «горит» янтарём).
        if self._search_matched:
            return QPen(self.SEARCH_MATCH_COLOR, 3)
        if self._hover:
            color = QColor(self.COLOR_HOVER)
            color.setAlpha(160)
            return QPen(color, 2)
        # v0.7.1: статус доступности — цвет рамки по умолчанию
        status_color = self.STATUS_COLORS.get(self._status)
        if status_color is not None:
            return QPen(status_color, 2)
        return QPen(Qt.transparent, 2)

    def _apply_visual_state(self):
        self._bg.setPen(self._state_pen())

    def update_appearance(self):
        """Пересобрать текстовые элементы при изменении данных.

        Ревью-фикс v0.8.0 (#4): ширина карточки ограничена диапазоном
        [MIN_NODE_WIDTH, MAX_NODE_WIDTH]. Длинный alias/host/comment больше не
        растягивает узел бесконечно: текст, не влезший в финальную ширину,
        elide'ится (…), полный текст — в tooltip сокращённой подписи. Alias и host
        дополнительно не заходят под точки-индикаторы справа [W-46, W-10].

        Алгоритм: ширина считается по полному тексту формулой как раньше, но с
        потолком MAX_NODE_WIDTH; затем (одним проходом) текст, не влезший в финальную
        ширину, сокращается под неё. Однопроходность — сознательное решение:
        «сократил и пересчитал ширину» не сходится к чистой фиксированной точке
        (elidedText оставляет зазор до лимита), а карточка, растянутая единственным
        длинным полем, всё равно остаётся шире MIN — зато видимая информация
        максимальна и геометрия детерминирована для любого шрифта/платформы.

        v0.8.4 (DESIGN.md §D): при data.collapsed рисуется одна строка — скрываются
        _info/_info_bg/_host_label, alias объединяется с host («alias @host»), высота —
        COLLAPSED_HEIGHT. Точки-индикаторы остаются видимыми (самое ценное в свёрнутом
        виде). prepareGeometryChange() обязателен до смены размера.
        """
        if getattr(self.data, "collapsed", False):
            self._update_appearance_collapsed()
            return
        self._show_expanded()
        alias_text = self.data.alias or "Unnamed"
        host_text = f"@{self.data.host}"

        info_lines = []
        # v0.9: ОС первой строкой (осн. источник — автосбор, но поле редактируемое)
        if getattr(self.data, "os_name", ""):
            os_line = self.data.os_name
            if getattr(self.data, "cpu_model", ""):
                os_line += f" · {self.data.cpu_model}"
            info_lines.append(os_line)
        if self.data.cpu: info_lines.append(f"CPU: {self.data.cpu}")
        if self.data.ram: info_lines.append(f"RAM: {self.data.ram}")
        if self.data.disk: info_lines.append(f"DISK: {self.data.disk}")
        if self.data.ip: info_lines.append(f"IP: {self.data.ip}")
        if self.data.ssh_port != 22: info_lines.append(f"SSH:{self.data.ssh_port}")
        # UI polish: эмодзи-префикс у комментария убран (единый стиль без эмодзи)
        if self.data.comment: info_lines.append(self.data.comment)

        fm_alias = QFontMetrics(self._alias.font())
        fm_host = QFontMetrics(self._host_label.font())
        fm_info = QFontMetrics(self._info.font())

        def _set_texts(a_text, h_text, i_lines):
            self._alias.setPlainText(a_text)
            self._host_label.setPlainText(h_text)
            self._info.setPlainText("\n".join(i_lines) if i_lines else _t("node.no_data"))

        def _needed_width() -> int:
            """Формула ширины как до фикса: правый край контента + 24 px."""
            alias_right = self._alias.pos().x() + self._alias.boundingRect().width()
            host_right = self._host_label.pos().x() + self._host_label.boundingRect().width()
            info_width = self._info.boundingRect().width()
            content_right = max(alias_right, host_right, 10 + info_width)
            return int(content_right + 24)

        def _clamp(w: float) -> int:
            return min(max(int(w), self.MIN_NODE_WIDTH), int(self.MAX_NODE_WIDTH))

        # Первый заход — полный текст (измеряем и «наценку» QGraphicsTextItem:
        # boundingRect.width() = horizontalAdvance + постоянные доковые маржины ~8 px).
        _set_texts(alias_text, host_text, info_lines)
        overhead = max(0.0, self._alias.boundingRect().width() - fm_alias.horizontalAdvance(alias_text))

        width = _clamp(_needed_width())
        label_max = max(int(width - self.LABEL_X - self.DOT_ZONE_LEFT - self.ELIDE_GAP - overhead), 1)
        info_max = max(int(width - self.INFO_X - 24.0 - overhead), 1)

        # Alias / host: сокращаем под зону, свободную от точек; полный текст — в tooltip
        if fm_alias.horizontalAdvance(alias_text) > label_max:
            self._alias.setPlainText(
                fm_alias.elidedText(alias_text, Qt.TextElideMode.ElideRight, label_max))
            self._alias.setToolTip(alias_text)
        else:
            self._alias.setToolTip("")

        if fm_host.horizontalAdvance(host_text) > label_max:
            self._host_label.setPlainText(
                fm_host.elidedText(host_text, Qt.TextElideMode.ElideRight, label_max))
            self._host_label.setToolTip(host_text)
        else:
            self._host_label.setToolTip("")

        # Инфо-блок (по строкам); полный многострочный текст — в tooltip, если что-то сократили.
        # При потолке MAX короткие строки остаются полными — режет только переполнение.
        if info_lines:
            elided = []
            any_elided = False
            for line in info_lines:
                lw = fm_info.horizontalAdvance(line)
                if lw > info_max:
                    elided.append(fm_info.elidedText(line, Qt.TextElideMode.ElideRight, info_max))
                    any_elided = True
                else:
                    elided.append(line)
            self._info.setPlainText("\n".join(elided))
            self._info.setToolTip("\n".join(info_lines) if any_elided else "")
        else:
            self._info.setToolTip("")

        # Расчет новой геометрии (высота — от фактического инфо-блока; elide строки
        # не оборачивает, поэтому количество строк от сокращения не зависит).
        # v0.9 fix: старая формула «70 + lines*fm.height()/2» была рассчитана на ~4
        # строки; с добавлением строки ОС (6 строк) контент вылезал за карточку.
        # Теперь высота = позиция инфо-блока (58) + его высота + нижний отступ.
        info_rect_h = self._info.boundingRect().height()
        needed_height = 58 + info_rect_h + 12

        new_width = _clamp(width)
        new_height = max(int(needed_height), self.MIN_NODE_HEIGHT)

        # Если геометрия изменилась — уведомляем сцену перед перерисовкой.
        # UI polish: boundingRect включает тень (SHADOW_BOTTOM) — prepareGeometryChange
        # обязателен и при смене ширины, и при смене высоты, как раньше.
        if new_width != self._current_width or new_height != self._current_height:
            self.prepareGeometryChange()  
            self._current_width = new_width
            self._current_height = new_height
            self._rebuild_frame_paths(self._current_width, self._current_height)

        # Позиционируем текстовый блок под иконкой/хостом; фон плашки — скруглённый путь
        self._info.setPos(10, 58)
        info_rect = self._info.boundingRect()
        info_w = max(info_rect.width() + 10, self._current_width - 12)
        info_h = info_rect.height() + 8
        self._info_bg.setPath(self._rounded(6, 56, info_w, info_h, 6.0))

        # Точки-индикаторы справа: [статус][SSH] (UI polish), по 14 px с зазором
        self._status_dot.setPos(self._current_width - 46, 23)
        self._ssh_status.setPos(self._current_width - 24, 23)
        # Шеврон — от АКТУАЛЬНОЙ ширины (геометрия могла измениться выше)
        self._chevron.setPath(self._chevron_path(down=False))
        self._apply_visual_state()

        # Синхронизируем стрелки связей с новой геометрией узла
        if self.scene():
            self.scene().update_connections_for_node(self)

    # ── v0.8.4 (DESIGN.md §D): сворачивание плашки в одну строку ─────────────

    def _chevron_path(self, down: bool) -> QPainterPath:
        """Глиф шеврона: ▾ (свёрнут — можно развернуть) / ▴ (развёрнут)."""
        path = QPainterPath()
        cx = float(self._current_width) - 16.0
        cy = 23.0
        if down:
            path.moveTo(cx - 5, cy - 2)
            path.lineTo(cx + 5, cy - 2)
            path.lineTo(cx, cy + 4)
        else:
            path.moveTo(cx - 5, cy + 2)
            path.lineTo(cx + 5, cy + 2)
            path.lineTo(cx, cy - 4)
        path.closeSubpath()
        return path

    def _show_expanded(self):
        """Показать элементы развёрнутой карточки и восстановить отдельный host."""
        self._info.show()
        self._info_bg.show()
        self._host_label.show()
        self._alias.setPos(55, 18)  # вернуть позицию после свёрнутой строки (y=12)
        # Вернуть иконку в базовую позицию после свёрнутого вида
        self._icon.setPos(0, 0)
        self._glyph.setPos(0, 0)
        # Восстановить исходный (крупный) шрифт alias после свёрнутой строки.
        if hasattr(self, "_alias_font_expanded"):
            self._alias.setFont(QFont(self._alias_font_expanded))

    def _set_geometry(self, width: int, height: int):
        """Общая для обоих режимов смена геометрии (prepareGeometryChange до размера)."""
        if width != self._current_width or height != self._current_height:
            self.prepareGeometryChange()
            self._current_width = width
            self._current_height = height
            self._rebuild_frame_paths(width, height)

    def _update_appearance_collapsed(self):
        """Свёрнутый вид: одна строка [иконка] alias @host … [●статус][SSH][▾].

        Скрываются _info/_info_bg/_host_label; точки-индикаторы остаются видимыми.
        Ширина считается по объединённому тексту «alias @host» с теми же лимитами
        [MIN_NODE_WIDTH, MAX_NODE_WIDTH] и elide под зону без точек. Стрелки
        перестраиваются сами: хвост вызывает scene().update_connections_for_node(),
        а edge_point() работает от boundingRect — дополнительной проводки не нужно.
        """
        self._info.hide()
        self._info_bg.hide()
        self._host_label.hide()

        # v0.8.4: мелкий шрифт свёрнутой строки (крупный alias 11pt не читается
        # в одну строку) — сохраняем исходный, чтобы развёрнутый вид не деградировал.
        if not hasattr(self, "_alias_font_expanded"):
            self._alias_font_expanded = QFont(self._alias.font())
        small = QFont(self._alias_font_expanded)
        small.setPointSizeF(max(small.pointSizeF() - 3.0, 7.0))
        self._alias.setFont(small)

        alias_text = (self.data.alias or "Unnamed")
        combined = f"{alias_text} @{self.data.host}" if self.data.host else alias_text
        fm_alias = QFontMetrics(self._alias.font())
        self._alias.setPlainText(combined)
        overhead = max(0.0,
                       self._alias.boundingRect().width() - fm_alias.horizontalAdvance(combined))
        width = min(max(int(fm_alias.horizontalAdvance(combined)
                          + self.LABEL_X + self.DOT_ZONE_LEFT + self.ELIDE_GAP + 24.0
                          + overhead), self.MIN_NODE_WIDTH), int(self.MAX_NODE_WIDTH))

        label_max = max(int(width - self.LABEL_X - self.DOT_ZONE_LEFT - self.ELIDE_GAP - overhead), 1)
        if fm_alias.horizontalAdvance(combined) > label_max:
            elided = fm_alias.elidedText(combined, Qt.TextElideMode.ElideRight, label_max)
            self._alias.setPlainText(elided)
            self._alias.setToolTip(combined)
        else:
            self._alias.setToolTip("")

        # Вертикальная центровка строки в COLLAPSED_HEIGHT; шеврон ставим ПОСЛЕ
        # _set_geometry — путь считается от новой ширины (иначе рисуется от старой
        # и «уезжает» за край/пропадает при смене геометрии).
        self._alias.setPos(55, 12)

        self._set_geometry(width, self.COLLAPSED_HEIGHT)
        self._chevron.setPath(self._chevron_path(down=True))
        # UI polish: точки подняты и сдвинуты влево, чтобы не загораживать шеврон
        dot_y = self.COLLAPSED_DOT_Y
        dot_dx = self.COLLAPSED_DOT_DX
        self._status_dot.setPos(self._current_width - 46 + dot_dx, dot_y)
        self._ssh_status.setPos(self._current_width - 24 + dot_dx, dot_y)
        # Иконка: приподнять к строке текста (только в свёрнутом виде)
        icon_dy = self.COLLAPSED_ICON_DY
        self._icon.setPos(0, icon_dy)
        self._glyph.setPos(0, icon_dy)
        self._apply_visual_state()
        if self.scene():
            self.scene().update_connections_for_node(self)

    def toggle_collapsed(self):
        """Переключить свёрнутость плашки и пересобрать вид."""
        self.data.collapsed = not bool(getattr(self.data, "collapsed", False))
        self.update_appearance()
        self.update()

    def chevron_rect(self) -> QRectF:
        """Зона клика шеврона в локальных координатах узла (для mousePressEvent)."""
        return QRectF(float(self._current_width) - 30.0, 8.0, 28.0, 30.0)

    def mousePressEvent(self, event):
        """Клик по шеврону — toggle (без драга/панорамы); остальное — стандартный путь.

        MapView сам переключается в NoDrag над ItemIsMovable-объектами, поэтому
        достаточно accept()'ить событие — драг узла при этом сохраняется.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            # QGraphicsSceneMouseEvent не имеет .position() — только .pos()
            local = QPointF(event.pos())
            if self.chevron_rect().contains(local):
                self.toggle_collapsed()
                event.accept()
                return
        super().mousePressEvent(event)

    def boundingRect(self) -> QRectF:
        """Явная геометрия узла.

        QGraphicsItemGroup в PySide6/Qt6 не пересчитывает boundingRect из дочерних
        элементов автоматически (проверено: остаётся нулевым), поэтому sceneBoundingRect()
        давал точку левого верхнего угла — стрелки v0.6 фактически шли «от угла».
        Возвращаем прямоугольник фона узла + полоску тени снизу (UI polish); изменение
        размеров уже защищено prepareGeometryChange() в update_appearance(). Тень входит в
        boundingRect намеренно: Qt клипует дочерних элементов по нему, а стрелки через
        edge_point() доходят ровно до её края — без «висящих» кончиков.
        """
        return QRectF(0, 0, self._current_width, self._current_height + self.SHADOW_BOTTOM)

    def _apply_content_opacity(self):
        """UI polish: затемнить контент карточки у offline-узлов (рамка и точки — яркие)."""
        opacity = 0.55 if self._status == "offline" else 1.0
        for item in (self._icon, self._glyph, self._alias, self._host_label, self._info):
            item.setOpacity(opacity)

    # ── v0.9.4: затемнение узла тег-фильтром ──

    DIM_OPACITY = 0.25  # несовпадающие с фильтром узлы — едва различимы

    def set_dimmed(self, dimmed: bool):
        """Тег-фильтр: полупрозрачная карточка у несовпадающих узлов (и обратное).

        В отличие от offline-затемнения (контент) здесь приглушается ВЕСЬ item —
        так несовпадающие узлы уходят на второй план целиком. Выделение сохраняется.
        """
        dimmed = bool(dimmed)
        if getattr(self, "_dimmed", False) == dimmed:
            return
        self._dimmed = dimmed
        self.setOpacity(self.DIM_OPACITY if dimmed else 1.0)

    # ── v0.9.8: поиск по карте (Ctrl+F) — подсветка совпадений ──

    def set_search_match(self, matched: bool):
        """v0.9.8: поиск по карте — акцентная рамка у совпавшего узла (и снятие её).

        Подсветка — статический pen в _state_pen (приоритет: выделение > совпадение
        > hover > статус). Отдельно от reveal_flash (кратковременный оверлей-вспышка)
        и set_dimmed (opacity всего item у несовпадающих). No-op при том же значении.
        """
        matched = bool(matched)
        if self._search_matched == matched:
            return
        self._search_matched = matched
        self._apply_visual_state()

    @property
    def search_matched(self) -> bool:
        """v0.9.8: узел совпадает с активным запросом поиска по карте."""
        return self._search_matched

    def set_ssh_connected(self, connected: bool):
        """Установить статус SSH подключения."""
        color = QColor("#22c55e") if connected else QColor("#64748b")
        self._ssh_status.setBrush(QBrush(color))

    def set_status(self, status: str):
        """v0.7.1: установить статус доступности (online/warn/offline).

        Обновляет цвет рамки (через _state_pen) и запускает короткую
        пульс-анимацию оверлея при смене статуса. Неизвестные статусы
        игнорируются; повторный вызов с тем же статусом — no-op.
        """
        if status not in self.STATUS_COLORS or status == self._status:
            return
        color = self.STATUS_COLORS[status]
        self._status = status

        # Tooltip со статусом (i18n, host подставляется в текст)
        try:
            from i18n import t as _translate
            tip = _translate(f"node.status.{status}", host=self.data.host or "")
        except Exception:
            tip = f"{status}: {self.data.host}"
        self.setToolTip(tip if not tip.startswith("[") else f"{status} — {self.data.host}")

        # UI polish: точка доступности (читается быстрее рамки при мелком зуме)
        # + затемнение контента карточки для offline-узлов
        self._status_dot.setBrush(QBrush(color))
        self._apply_content_opacity()

        # Статическая рамка + пульс (fade-out оверлея: opacity 1 -> 0)
        self._apply_visual_state()
        self._start_pulse(color)

    def _start_pulse(self, color: QColor):
        """v0.7.1/v0.9.6: запуск fade-out оверлея рамки заданного цвета.

        Общий путь для пульса смены статуса (set_status) и акцента «Показать на
        карте» (reveal_flash). Оверлей _pulse следует геометрии карточки
        (_rebuild_frame_paths перестраивает его path), поэтому свёрнутый/развёрнутый
        режим поддерживается без дополнительной работы.
        """
        self._pulse.setPen(QPen(color, 3))
        if self._pulse_anim is None:
            from PySide6.QtCore import QEasingCurve
            anim = QVariantAnimation()
            anim.setDuration(900)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.Type.OutQuad)

            def _on_value(v, item=self._pulse):
                item.setOpacity(float(v))
                self.update()

            anim.valueChanged.connect(_on_value)
            anim.finished.connect(self._pulse.hide)
            self._pulse_anim = anim  # ссылка держит анимацию в живых (no-parent binding)
        self._pulse.show()
        self._pulse.setOpacity(1.0)
        anim = self._pulse_anim
        anim.stop()
        anim.start()

    def reveal_flash(self):
        """v0.9.6: акцент «Показать на карте» из сайдбара — рамка-вспышка (900 мс).

        Тот же паттерн, что пульс set_status (готовый оверлей + QVariantAnimation),
        но цветом REVEAL_COLOR и БЕЗ изменения статуса: reveal — навигационный
        сигнал, а не результат пробы доступности.
        """
        try:
            self._start_pulse(self.REVEAL_COLOR)
        except RuntimeError:
            pass  # Qt teardown: C++ item уничтожен, вызов пришёл из живого Python

    @property
    def status(self) -> str:
        """Текущий статус доступности ("" — ещё не проверялся)."""
        return self._status

    def reset_status(self):
        """v0.7.1: сбросить статус (например, после смены host/порта узла)."""
        if not self._status:
            return
        self._status = ""
        self.setToolTip("")
        # UI polish: точка — серая (не проверен), контент — полная яркость
        self._status_dot.setBrush(QBrush(self.COLOR_DOT_IDLE))
        self._apply_content_opacity()
        self._apply_visual_state()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            new_pos = value
            self.data.x = new_pos.x()
            self.data.y = new_pos.y()
            if self.scene():
                self.scene().update_connections_for_node(self)
                # v0.8.1: узел сместился — членство групп пересчитывается по геометрии
                # (центр карточки вошёл/вышел из рамки). ВАЖНО: itemChange вызывается ДО
                # применения новой позиции (Qt-хук ветирования — проверено пробником):
                # self.pos()/sceneBoundingRect() внутри ещё СТАРЫЕ, поэтому целевой rect
                # передаём явно через overrides, иначе состав «догонял» бы на шаг.
                if hasattr(self.scene(), "resync_group_members"):
                    try:
                        dx = float(new_pos.x()) - float(self.pos().x())
                        dy = float(new_pos.y()) - float(self.pos().y())
                        target_rect = QRectF(self.sceneBoundingRect()).translated(dx, dy)
                        self.scene().resync_group_members({self.data.id: target_rect})
                    except Exception:  # noqa: BLE001 — членство вторично по отношению к перемещению
                        pass
        return super().itemChange(change, value)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_visual_state()
        self.setSelected(selected)

    def hoverEnterEvent(self, event):
        self._hover = True
        self._apply_visual_state()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self._apply_visual_state()
        super().hoverLeaveEvent(event)
