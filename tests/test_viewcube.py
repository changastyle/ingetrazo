# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The corner view cube: which face a click lands on, a clean press
snapping to that standard view, a drag orbiting instead, and the paint
pass not crashing."""
import math

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget

from core.camera import OrbitCamera
from views.viewcube import SIZE, ViewCube


class _VP(QWidget):
    """The slice of the viewport the gizmo touches: camera, size,
    palette, update()."""

    def __init__(self) -> None:
        super().__init__()
        self.camera = OrbitCamera()
        self.resize(900, 600)
        self.repaints = 0

    def update(self) -> None:
        self.repaints += 1
        super().update()


def _face_center(vc, vp, name):
    rect = vc.rect(vp)
    c = rect.center()
    proj = vc._projector(vp.camera, c.x(), c.y())
    for n, _l, poly, _d, _f in vc._faces(vp.camera, c.x(), c.y()):
        if n == name:
            return poly.boundingRect().center().toPoint()
    raise AssertionError(f"{name} not visible")


def test_a_face_click_snaps_to_its_standard_view():
    vp, vc = _VP(), ViewCube()
    top = _face_center(vc, vp, "top")        # iso start: top is visible
    assert vc.press(top, vp)
    assert vc.release(top, vp)
    assert math.isclose(vp.camera.pitch, math.radians(90))
    assert vp.repaints >= 1


def test_a_drag_orbits_instead_of_snapping():
    vp, vc = _VP(), ViewCube()
    yaw0 = vp.camera.yaw
    start = vc.rect(vp).center()
    assert vc.press(start, vp)
    assert vc.move(start + QPoint(30, 10), Qt.LeftButton, vp)
    assert vc.release(start + QPoint(30, 10), vp)
    assert vp.camera.yaw != yaw0             # it orbited, did not snap
    assert not math.isclose(vp.camera.pitch, math.radians(90))


def test_press_outside_the_box_is_not_consumed():
    vp, vc = _VP(), ViewCube()
    assert not vc.press(QPoint(10, vp.height() - 10), vp)   # bottom-left
    assert not vc.release(QPoint(10, vp.height() - 10), vp)


def test_hover_sets_and_clears():
    vp, vc = _VP(), ViewCube()
    top = _face_center(vc, vp, "top")
    vc.move(top, Qt.NoButton, vp)
    assert vc._hover == "top"
    vc.move(QPoint(4, vp.height() - 4), Qt.NoButton, vp)
    assert vc._hover is None


def test_the_paint_pass_draws_without_crashing():
    vp, vc = _VP(), ViewCube()
    img = QImage(900, 600, QImage.Format_ARGB32)
    p = QPainter(img)
    vc.draw(p, vp)
    p.end()
    # Something was painted in the gizmo's corner.
    px = img.pixelColor(900 - 14 - SIZE // 2, 14 + SIZE // 2)
    assert px.alpha() > 0
