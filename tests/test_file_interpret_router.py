# -*- coding: utf-8 -*-
"""拖文件解读路由：包窗开着走包，否则走内置；只投一次。"""

from __future__ import annotations

from pet.file_interpret_router import FileInterpretRouter


def _router():
    router = FileInterpretRouter()
    seen: list[tuple[str, object]] = []
    router.set_builtin_offer(lambda paths: seen.append(("builtin", paths)))
    router.set_package_offer(lambda paths: seen.append(("package", paths)))
    return router, seen


def test_package_window_open_routes_to_the_package():
    router, seen = _router()

    router(["a"])
    assert seen[-1] == ("builtin", ["a"])

    router.package_window_opened()
    router(["b"])
    assert seen[-1] == ("package", ["b"])

    router.package_window_closed()
    router(["c"])
    assert seen[-1] == ("builtin", ["c"])


def test_two_package_windows_keep_the_package_route_until_the_last_closes():
    router, seen = _router()
    router.package_window_opened()
    router.package_window_opened()

    router(["a"])
    assert seen[-1][0] == "package"

    router.package_window_closed()
    router(["b"])
    assert seen[-1][0] == "package"

    router.package_window_closed()
    router(["c"])
    assert seen[-1][0] == "builtin"


def test_a_missing_package_offer_falls_back_to_the_builtin():
    router = FileInterpretRouter()
    seen: list[str] = []
    router.set_builtin_offer(lambda _paths: seen.append("builtin"))
    router.package_window_opened()

    router(["a"])

    assert seen == ["builtin"]


def test_clearing_the_package_offer_resets_the_window_count():
    router, seen = _router()
    router.package_window_opened()
    router.set_package_offer(None)
    router.set_package_offer(lambda paths: seen.append(("new-package", paths)))

    router(["a"])

    assert seen[-1][0] == "builtin"


def test_an_unexpected_close_never_makes_the_count_negative():
    router, seen = _router()
    router.package_window_closed()
    router.package_window_closed()
    router.package_window_opened()
    router(["a"])

    assert seen[-1][0] == "package"
