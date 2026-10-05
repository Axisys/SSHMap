"""`ExportMixin` — the map's IMAGE and DATA exports: the palette, the renderers and the reports (AGENTS.md §4.1).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance, and `ExportOptionsDialog` is resolved on the facade at
call time (`host_attr`), which is the test seam (`MW.ExportOptionsDialog = Fake`).

Owned here: the ONE export-palette question every raster/vector export shares (`_ask_export_palette()`, the
session's remembered answer is `_export_use_current_theme`), the four map renderers (PNG/JPEG, draw.io, PDF,
SVG), the two IMAGE paths (the clipboard copy and the fixed-frame documentation poster) and the three DATA
reports (the visible inventory, the connection list and the attention list) over the pure writers of
`ui/sidebar.py` and `storage/export_*.py`. Mechanism — `DOCUMENTATION.md` §29, §30."""
import os

from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

try:  # v1.2.5: central theme (the export palette ids live in ui/theme.py)
    from . import theme
except ImportError:
    try:
        from ui import theme
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        import theme

try:  # v1.5.5 (ROADMAP task 2): the pure CSV/TSV writer of the inventory report
    from .sidebar import list_delimiter, list_table_text
except ImportError:
    from sidebar import list_delimiter, list_table_text

try:  # v1.6 (ROADMAP task 5): the rows of the connection report
    from ..storage.export_connections import connection_report_rows
except ImportError:
    try:
        from storage.export_connections import connection_report_rows
    except ImportError:  # a stripped build — the report says so instead of writing a file
        connection_report_rows = None

try:  # v1.6.8 (ROADMAP task 4): the rows of the ATTENTION report
    from ..storage.export_problems import problem_report_rows
except ImportError:
    try:
        from storage.export_problems import problem_report_rows
    except ImportError:  # a stripped build — the report says so instead of writing a file
        problem_report_rows = None

try:  # v1.1.4: the common seam for monkeypatching the facade module's globals (see mixin_support)
    from .mixin_support import host_attr
except ImportError:
    from mixin_support import host_attr


class ExportMixin:
    """The map's exports (images and reports), the clipboard copy and the background image."""

    # v1.5rc2 (ROADMAP task 3): the LAST export palette choice ("use the current
    # theme"), remembered for the SESSION only — the export palette is deliberately
    # NOT a config key (the hub's collect() contract stays 22 keys) and it is
    # read/written by `_ask_export_palette()`. False = the print-friendly default.
    _export_use_current_theme = False

    def _ask_export_palette(self):
        """Ask which palette the export renders with — the ONE question all four exports share.

        v1.5rc2: an export must not print a dark page, so the DEFAULT is the
        print-friendly one (`theme.PALETTE_PRINT` — the LIGHT page with the
        high-contrast lines, `MapScene.export_palette()`); the dialog's checkbox is
        the opt-out that keeps the CURRENT look. Returns the palette id of the active
        theme, or None when the user cancelled (the export then writes nothing).

        The answer of the previous export is remembered on the instance for the rest
        of the session (never persisted), and the dialog is a module-level facade
        (`MW.ExportOptionsDialog`), i.e. the same test seam as `QFileDialog`.
        """
        dialog_cls = host_attr(self, "ExportOptionsDialog")
        try:
            dialog = dialog_cls(
                self, use_current_theme=bool(self._export_use_current_theme))
        except Exception:  # noqa: BLE001 — a dialog that cannot be built must not block the export
            return theme.PALETTE_PRINT
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            self._export_use_current_theme = dialog.use_current_theme()
            return dialog.chosen_palette()
        finally:
            getattr(dialog, "deleteLater", lambda: None)()

    def _export_map_image(self):
        """Export the map to PNG/JPEG (v0.9.1 #1): render the whole scene to a file.

        v1.5rc2: the render goes through `self._ask_export_palette()` — print-friendly
        (a light page) unless the user asked for the current theme.
        """
        path, selected_filter = QFileDialog.getSaveFileName(
            self, self.t("file.export_png"), "",
            "PNG Images (*.png);;JPEG Images (*.jpg)")
        if not path:
            return
        # The extension from the chosen filter, if the user did not type it
        if not path.lower().endswith((".png", ".jpg", ".jpeg")):
            ext = ".jpg" if "JPEG" in (selected_filter or "") else ".png"
            path += ext
        palette = self._ask_export_palette()
        if palette is None:
            return
        try:
            pixmap = self.scene.render_to_pixmap(scale=2.0, palette=palette)
            if not pixmap.save(path):
                raise OSError("QPixmap.save returned False")
            self.statusBar().showMessage(self.t("status.export_ok"))
            if self.log:
                self.log.info("Map exported", extra={"file": path, "palette": palette})
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _export_map_drawio(self):
        """Export the map to draw.io (.drawio) — v0.9.5 #1–#4.

        v1.5rc2: the same palette question as the raster exports — the writer paints
        the print-friendly (light, high-contrast) palette by default and carries the
        DECLARED dash pattern of every connection type.
        """
        from storage.export_drawio import export_scene_to_drawio
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file.export_drawio"), "",
            "draw.io Diagrams (*.drawio)")
        if not path:
            return
        if not path.lower().endswith(".drawio"):
            path += ".drawio"
        palette = self._ask_export_palette()
        if palette is None:
            return
        try:
            cells = export_scene_to_drawio(self.scene, path, palette=palette)
            self.statusBar().showMessage(self.t("status.export_drawio_ok"))
            if self.log:
                self.log.info(
                    "Map exported to drawio",
                    extra={"file": path, "cells": cells, "palette": palette})
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _export_map_pdf(self):
        """Export the map to PDF (v0.9.9.7): the open scene -> a file in one action.

        v1.5rc2: the print-friendly palette by default — a PDF is the format most
        likely to be printed.
        """
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file.export_pdf"), "", "PDF Documents (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        palette = self._ask_export_palette()
        if palette is None:
            return
        try:
            size = self.scene.render_to_pdf(path, palette=palette)
            self.statusBar().showMessage(self.t("status.export_pdf_ok"))
            if self.log:
                self.log.info(
                    "Map exported to PDF", extra={"file": path, "bytes": size,
                                                  "palette": palette})
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _export_map_svg(self):
        """Export the map to SVG (v1.3.3.7): the open scene -> a vector file.

        The same shape as the PDF/PNG paths (QFileDialog + the extension + the status
        bar/log + `msg.export_failed`), but the render itself is `render_to_svg`
        (`QSvgGenerator`) — the map leaves as VECTOR data, background and grid included.
        v1.5rc2: the palette question comes first, so an SVG of a DARK window is a
        light page by default too (the halos stay hidden — the vector contract).
        """
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file.export_svg"), "", "SVG Images (*.svg)")
        if not path:
            return
        if not path.lower().endswith(".svg"):
            path += ".svg"
        palette = self._ask_export_palette()
        if palette is None:
            return
        try:
            size = self.scene.render_to_svg(path, palette=palette)
            self.statusBar().showMessage(self.t("status.export_svg_ok"))
            if self.log:
                self.log.info(
                    "Map exported to SVG", extra={"file": path, "bytes": size,
                                                  "palette": palette})
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _copy_map_image(self):
        """Copy the map into the clipboard as an image (v1.5.1, ROADMAP task 1).

        The SAME 2× render as the PNG export, with `QApplication.clipboard()
        .setPixmap()` instead of the file dialog — and ONE deliberate difference: **the
        copy uses the CURRENT theme and asks NO palette question**. An export is a
        document (the v1.5rc2 print-friendly default), a copy is "what I am looking at";
        routing this action through the export palette dialog would turn a screenshot of
        the window into a light page behind a modal, which is the defect this comment
        exists to prevent. No dialog at all, so the action is a pure function of the
        scene and the active palette (the gate asserts the `PALETTE_THEME` render).

        An empty map is a valid copy (the render falls back to the fixed rect), and a
        failed render reports through `msg.export_failed` like every other export path.
        """
        try:
            pixmap = self.scene.render_to_pixmap(scale=2.0, palette=theme.PALETTE_THEME)
            QApplication.clipboard().setPixmap(pixmap)
            self.statusBar().showMessage(self.t("status.map_copied"))
            if self.log:
                self.log.info("Map copied to the clipboard",
                              extra={"width": pixmap.width(), "height": pixmap.height(),
                                     "palette": theme.PALETTE_THEME})
        except Exception as e:  # noqa: BLE001 — a GUI action must not crash the app
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _export_docs_frame(self):
        """Save the map as a FIXED-FRAME documentation image (v1.5.1, ROADMAP task 2).

        The poster path: `MapScene.render_frame_to_pixmap()` renders the map inside a
        1600×900 LOGICAL frame at 2× (3200×1800 px), the content fitted and centred on
        the canvas background — the SAME size for every map, which is what makes it
        usable in a README, an issue report or a slide (the ordinary PNG export sizes
        itself to the content). The palette is the CURRENT theme (a poster is read on
        screen); the file is written with the PNG writer and reported in the status bar.

        The image holds the MAP only: the floating panels and the chrome are children of
        `MapView`, never scene items, so they cannot leak into a poster (see the method
        docstring). The subject for the shipped documentation is the EXAMPLE map — real
        topologies are gitignored and must never be published; the workflow (the
        destination, the README link and the refresh rule) is pinned in `DOCUMENTATION.md`
        §5 and `AGENTS.md` §2.
        """
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file.docs_frame"), "",
            "PNG Images (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            pixmap = self.scene.render_frame_to_pixmap()
            if not pixmap.save(path):
                raise OSError("QPixmap.save returned False")
            self.statusBar().showMessage(
                self.t("status.docs_frame_saved", file=os.path.basename(path)))
            if self.log:
                self.log.info("Documentation image saved",
                              extra={"file": path, "width": pixmap.width(),
                                     "height": pixmap.height()})
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _list_report_rows(self) -> list:
        """The visible LIST table (the header row first) — or [] when there is no table.

        The ONE reader the two report actions share: the panel builds the rows (they ARE
        the cells `list_cell_values()` produced, in the order the user sorted them), so the
        report and the screen can never disagree about the columns or the content.
        """
        panel = getattr(self, "sidebar", None)
        if panel is None:
            return []
        try:
            return panel.list_report_rows()
        except RuntimeError:
            return []  # Qt teardown — the panel is already destroyed

    def _report_table_unavailable(self) -> None:
        """Say WHY there is nothing to report (the two actions share the sentence)."""
        try:
            self.statusBar().showMessage(self.t("status.list_empty"))
        except Exception:  # noqa: BLE001 — a hint must not break the action
            pass

    def _export_connections_table(self):
        """Export the map's CONNECTIONS as CSV or TSV (v1.6, ROADMAP task 5).

        The second DATA report, built on the SAME pure writer as the inventory export
        (`list_table_text()`): the rows come from `storage/export_connections.py`, the
        delimiter and the file dialog follow the sibling above, and the file is UTF-8 with
        a BOM for the same reason (aliases and labels in the user's own alphabet, opened by
        Excel). A map without a single connection reports that instead of writing a header.
        """
        try:
            arrows = list(self.scene.arrows())
        except (AttributeError, RuntimeError):
            arrows = []
        if connection_report_rows is None:
            return
        rows = connection_report_rows(arrows, self.t if self._i18n_available else None)
        if not rows:
            self.statusBar().showMessage(
                self.t("status.connections_empty") if self._i18n_available
                else "Nothing to report — the map has no connections")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, self.t("file.export_connections"), "",
            "CSV — Comma Separated Values (*.csv);;TSV — Tab Separated Values (*.tsv)")
        if not path:
            return
        fmt = "tsv" if "TSV" in (selected_filter or "") else "csv"
        lowered = str(path).lower()
        if lowered.endswith(".tsv"):
            fmt = "tsv"
        elif lowered.endswith(".csv"):
            fmt = "csv"
        else:
            path += f".{fmt}"
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(list_table_text(rows, list_delimiter(fmt)))
            self.statusBar().showMessage(
                self.t("status.connections_exported", file=os.path.basename(path)))
            if self.log:
                self.log.info("Connection list exported",
                              extra={"file": path, "format": fmt, "rows": len(rows) - 1})
        except Exception as e:  # noqa: BLE001 — a GUI action must not crash the app
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _export_problems_table(self):
        """Export the servers that NEED ATTENTION as CSV or TSV (v1.6.8, ROADMAP task 5).

        The THIRD DATA report, and the answer to a question the map can only dim: the
        "problems only" lens highlights the cards that need a look, but that set cannot
        leave the application — the lens is a MAP view (v1.5.4) and the inventory export
        is EXACTLY what is on screen (v1.5.5). This report reads the SCENE through the
        DECLARED predicate (`storage/export_problems.py` → `node_group.is_in_trouble()`),
        so the file and the dimmed map always hold the SAME servers.

        Two empty answers are deliberately DIFFERENT sentences: a map with no servers at
        all, and a map where nothing needs attention. Neither writes a file — a report is
        a set of rows, and a header over nothing is not one.
        """
        try:
            nodes = list(self.scene.nodes())
        except (AttributeError, RuntimeError):
            nodes = []
        if problem_report_rows is None:
            return
        if not nodes:
            self.statusBar().showMessage(
                self.t("status.problems_no_nodes") if self._i18n_available
                else "Nothing to report — the map has no servers")
            return
        rows = problem_report_rows(nodes, self.t if self._i18n_available else None)
        if not rows:
            self.statusBar().showMessage(
                self.t("status.problems_none") if self._i18n_available
                else "Nothing to report — no server needs attention")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, self.t("file.export_problems"), "",
            "CSV — Comma Separated Values (*.csv);;TSV — Tab Separated Values (*.tsv)")
        if not path:
            return
        fmt = "tsv" if "TSV" in (selected_filter or "") else "csv"
        lowered = str(path).lower()
        if lowered.endswith(".tsv"):
            fmt = "tsv"
        elif lowered.endswith(".csv"):
            fmt = "csv"
        else:
            path += f".{fmt}"
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(list_table_text(rows, list_delimiter(fmt)))
            self.statusBar().showMessage(
                self.t("status.problems_exported", file=os.path.basename(path)))
            if self.log:
                self.log.info("Attention list exported",
                              extra={"file": path, "format": fmt, "rows": len(rows) - 1})
        except Exception as e:  # noqa: BLE001 — a GUI action must not crash the app
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _copy_list_table(self):
        """Copy the VISIBLE server table to the clipboard as TSV (v1.5.5, ROADMAP task 2).

        TSV, not CSV, on purpose: the clipboard is for the next PASTE, and a spreadsheet
        splits tab-separated text into cells natively (a comma-separated paste lands in one
        column). The text comes from the pure `list_table_text()` — the SAME writer the file
        export uses, so a value with a comma, a quote or a line break cannot be copied
        differently from the way it is exported.
        """
        rows = self._list_report_rows()
        if not rows:
            self._report_table_unavailable()
            return
        text = list_table_text(rows, list_delimiter("tsv"))
        count = len(rows) - 1        # the header is not a server
        if self._copy_text_to_clipboard(text, "status.list_copied", count=count) and self.log:
            self.log.info("Server list copied to the clipboard",
                          extra={"rows": count, "columns": len(rows[0])})

    def _export_list_table(self):
        """Export the VISIBLE server table as CSV or TSV (v1.5.5, ROADMAP task 2).

        The ordinary save-dialog pattern of every export of this window (the extension from
        the chosen filter, the status bar on success, `msg.export_failed` on a failure), with
        ONE deliberate difference: the file is written as **UTF-8 with a BOM**. An inventory
        carries aliases, OS names and comments in the user's own alphabet, and the BOM is
        what makes Excel open such a CSV correctly instead of as mojibake — the report is the
        artefact a human passes on, not an internal file.

        The columns are the VISIBLE ones and the rows are the VISIBLE rows in their visible
        order (the filters and the sort included): an export is "what I am looking at",
        documented — the same rule the map's copy follows.
        """
        rows = self._list_report_rows()
        if not rows:
            self._report_table_unavailable()
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, self.t("file.export_list"), "",
            "CSV — Comma Separated Values (*.csv);;TSV — Tab Separated Values (*.tsv)")
        if not path:
            return
        # The format follows the CHOSEN filter, and a typed extension wins over both.
        fmt = "tsv" if "TSV" in (selected_filter or "") else "csv"
        lowered = str(path).lower()
        if lowered.endswith(".tsv"):
            fmt = "tsv"
        elif lowered.endswith(".csv"):
            fmt = "csv"
        else:
            path += f".{fmt}"
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(list_table_text(rows, list_delimiter(fmt)))
            self.statusBar().showMessage(
                self.t("status.list_exported", file=os.path.basename(path)))
            if self.log:
                self.log.info("Server list exported",
                              extra={"file": path, "format": fmt, "rows": len(rows) - 1})
        except Exception as e:  # noqa: BLE001 — a GUI action must not crash the app
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))
