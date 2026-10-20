# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The corner view gizmo — a clickable ViewCube in the viewport overlay.

A small cube painted in the top-right corner that tumbles with the
camera, with a compass ring under it. Clicking a face snaps the camera
to that standard view (``OrbitCamera.set_view`` — the same presets as
Camera ▸ Top/Front/Isometric), and dragging anywhere on the gizmo orbits
the model, so it doubles as an orientation readout and a navigation
shortcut. Drawn in the QPainter overlay only while exporting is off —
an exported image must not carry the widget.
"""
import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QPainter, QPen, QPolygonF,
                           QVector3D)

from core.i18n import tr
from views.theme import accent_color

SIZE = 116                     # the gizmo's square box, px
_MARGIN = 14                   # from the window's top-right corner
_RADIUS = 34.0                 # cube half-width on screen
_RING = 50.0                   # compass ring radius
_ORBIT_SLIP = 4                # px of drag before a click becomes an orbit

# Face name (a ``camera.set_view`` preset), its outward normal and the
# menu label — already translated for the standard-views menu. The -Y
# face is FRONT: the "front" preset (yaw -90°) puts the eye on -Y.
FACES = (
    ("top",    QVector3D(0, 0, 1),  "Top"),
    ("bottom", QVector3D(0, 0, -1), "Bottom"),
    ("right",  QVector3D(1, 0, 0),  "Right"),
    ("left",   QVector3D(-1, 0, 0), "Left"),
    ("front",  QVector3D(0, -1, 0), "Front"),
    ("back",   QVector3D(0, 1, 0),  "Back"),
)

_QUADS = {
    "top":    ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)),
    "bottom": ((-1, -1, -1), (-1, 1, -1), (1, 1, -1), (1, -1, -1)),
    "right":  ((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)),
    "left":   ((-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)),
    "front":  ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)),
    "back":   ((-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)),
}

# Compass points on the ring, world direction → the standard view's name;
# the mark drawn is the FIRST LETTER of its translation, so the ring reads
# N/E/S/W in English and N/E/S/O in Spanish with no per-letter keys.
_COMPASS = ((QVector3D(0, 1, 0), "North"), (QVector3D(1, 0, 0), "East"),
            (QVector3D(0, -1, 0), "South"), (QVector3D(-1, 0, 0), "West"))


class ViewCube:
    """State and painting for the gizmo; the viewport forwards mouse
    events to :meth:`press`/:meth:`move`/:meth:`release`."""

    def __init__(self) -> None:
        self._press = None      # (pos, face hit) while a gesture runs
        self._orbited = False   # the press slipped past _ORBIT_SLIP
        self._hover = None      # face name under the cursor, or None

    # ---- geometry ------------------------------------------------------------

    def rect(self, vp) -> QRect:
        return QRect(vp.width() - SIZE - _MARGIN, _MARGIN, SIZE, SIZE)

    @staticmethod
    def _projector(camera, cx: float, cy: float):
        """``world dir → (sx, sy, depth)`` — the camera's own rotation
        applied to the little cube: it tumbles exactly like the model."""
        f = camera.forward()
        # The lookAt basis: the screen-up axis is cross(right, forward),
        # not the world's up — projecting onto world-up flattens the top
        # face to a line (it varies only in x/y).
        r = QVector3D.normalized(
            QVector3D.crossProduct(f, camera.up_vector()))
        u = QVector3D.normalized(QVector3D.crossProduct(r, f))

        def project(p: QVector3D):
            return (cx + QVector3D.dotProduct(p, r) * _RADIUS,
                    cy - QVector3D.dotProduct(p, u) * _RADIUS,
                    QVector3D.dotProduct(p, f))
        return project

    def _faces(self, camera, cx: float, cy: float):
        """Visible faces far→near: ``(name, label, QPolygonF, depth)``.
        A face shows when its normal tilts toward the eye."""
        f = camera.forward()
        proj = self._projector(camera, cx, cy)
        out = []
        for name, n, label in FACES:
            facing = QVector3D.dotProduct(n, f)
            if facing >= -0.05:
                continue                    # a back face, culled
            poly = QPolygonF()
            depth = 0.0
            for vx, vy, vz in _QUADS[name]:
                sx, sy, dz = proj(QVector3D(vx, vy, vz))
                poly << QPointF(sx, sy)
                depth += dz
            out.append((name, label, poly, depth / 4.0, facing))
        out.sort(key=lambda item: item[3], reverse=True)   # far first
        return out

    def _face_at(self, pos, vp):
        """The nearest visible face whose polygon holds ``pos``."""
        rect = self.rect(vp)
        if not rect.contains(pos):
            return None
        cx, cy = rect.center().x(), rect.center().y()
        faces = self._faces(vp.camera, cx, cy)
        for name, _l, poly, _d, _f in reversed(faces):     # near first
            if poly.containsPoint(QPointF(pos), Qt.OddEvenFill):
                return name
        return "ring"            # inside the box but off the cube

    # ---- input ---------------------------------------------------------------

    def press(self, pos, vp) -> bool:
        """A left press inside the box: remember it; whether it ends as a
        view snap or an orbit is decided by how far it moves."""
        face = self._face_at(pos, vp)
        if face is None:
            return False
        self._press = (pos, face)
        self._orbited = False
        return True

    def move(self, pos, buttons, vp) -> bool:
        """While pressed, orbit once past the slip; otherwise just track
        the hover so the face lights up. Returns True when consumed."""
        if self._press is not None and buttons & Qt.LeftButton:
            start, _face = self._press
            dx, dy = pos.x() - start.x(), pos.y() - start.y()
            if self._orbited or dx * dx + dy * dy > _ORBIT_SLIP ** 2:
                self._orbited = True
                vp.camera.orbit(dx, dy, vp.height())
                self._press = (pos, self._press[1])
                vp.update()
            return True
        hover = self._face_at(pos, vp)
        if hover != self._hover:
            self._hover = hover
            vp.update()
        return False

    def release(self, pos, vp) -> bool:
        """A clean press on a face snaps to its view; an orbited one just
        ends the drag."""
        if self._press is None:
            return False
        face = self._press[1]
        orbited, self._press, self._orbited = self._orbited, None, False
        if not orbited and face not in (None, "ring") \
                and self._face_at(pos, vp) == face:
            vp.camera.set_view(face)
            vp.update()
        return True

    # ---- paint ---------------------------------------------------------------

    def draw(self, painter: QPainter, vp) -> None:
        rect = self.rect(vp)
        cx, cy = rect.center().x(), rect.center().y()
        pal = vp.palette()
        ink = pal.color(pal.ColorRole.Text)
        hot = accent_color()

        # The compass ring — a faint turntable ellipse whose N/E/S/W marks
        # ride the projected axes, so they swing as the camera orbits.
        ring = QColor(ink)
        ring.setAlpha(70)
        painter.setPen(QPen(ring, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(
            QRectF(cx - _RING, cy - _RING * 0.42, _RING * 2, _RING * 0.84))
        proj = self._projector(vp.camera, cx, cy)
        font = QFont()
        font.setPixelSize(9)
        painter.setFont(font)
        for d, name in _COMPASS:
            sx, sy, _z = proj(d * 1.0)
            lx = cx + (sx - cx) * (_RING / _RADIUS)
            ly = cy + (sy - cy) * (_RING * 0.42 / _RADIUS)
            mark = QColor(ink)
            mark.setAlpha(160 if name == "North" else 110)
            painter.setPen(QPen(mark))
            painter.drawText(
                QRectF(lx - 8, ly - 7, 16, 14), Qt.AlignCenter,
                tr(name)[0])

        # The cube's faces, far to near (painter's algorithm).
        font.setPixelSize(9)
        painter.setFont(font)
        hot_hover = QColor(hot)
        hot_hover.setAlpha(120)
        for name, label, poly, _d, facing in self._faces(
                vp.camera, cx, cy):
            if name == self._hover:
                fill = hot_hover
            else:
                fill = QColor(ink)
                fill.setAlpha(26 + int(40 * -facing))
            painter.setBrush(fill)
            edge = QColor(ink)
            edge.setAlpha(170)
            painter.setPen(QPen(edge, 1.2))
            painter.drawPolygon(poly)
            # The label rides on faces that are turned enough toward the
            # eye to carry it — the same rule the standard views use.
            if facing < -0.55:
                painter.setPen(QPen(QColor(ink)))
                painter.drawText(poly.boundingRect(), Qt.AlignCenter,
                                 tr(label))

    def end_gesture(self) -> None:
        """Drop any half-finished press (focus loss, button released
        outside)."""
        self._press = None
        self._orbited = False
