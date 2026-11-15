"""1.1.10: the app never opens the browser on its own. Only a link the user clicked may leave the window; a frame loading
(the Cloudflare check's iframe right after a click, which 1.1.9 sent to Chrome as a blank tab), a redirect, a script, a form
or a navigation aimed at a named frame is dropped silently."""
import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("osd_ext", os.path.join(HERE, "omarchy-store-desktop.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NT = m.WebKit.NavigationType


class Nav:
    def __init__(self, t, gesture=True, redirect=False, frame=None, uri="https://github.com/x"):
        self.t, self.g, self.r, self.f, self.uri = t, gesture, redirect, frame, uri
    def get_navigation_type(self): return self.t
    def is_user_gesture(self): return self.g
    def is_redirect(self): return self.r
    def get_frame_name(self): return self.f
    def get_request(self):
        u = self.uri
        return type("R", (), {"get_uri": lambda s: u})()


def test_a_clicked_link_may_open_the_browser():
    assert m.link_click(Nav(NT.LINK_CLICKED))
    assert m.link_click(Nav(NT.LINK_CLICKED, frame="_blank"))


@pytest.mark.parametrize("nav", [
    Nav(NT.OTHER),                                   # an iframe loading (the Turnstile frame) right after a click
    Nav(NT.OTHER, frame="cf-chl-widget-abc"),
    Nav(NT.LINK_CLICKED, frame="cf-chl-widget-abc"),  # a link aimed at a named (sub)frame
    Nav(NT.LINK_CLICKED, redirect=True),             # a redirect after a click
    Nav(NT.LINK_CLICKED, gesture=False),             # a script clicking a link
    Nav(NT.FORM_SUBMITTED),
    Nav(NT.FORM_RESUBMITTED),
    Nav(NT.RELOAD),
    Nav(NT.BACK_FORWARD),
])
def test_everything_else_is_dropped(nav):
    assert not m.link_click(nav)


class Decision:
    def __init__(self, nav): self.nav, self.ignored = nav, False
    def get_navigation_action(self): return self.nav
    def ignore(self): self.ignored = True


class FakeWin:
    clicked = None
    def __init__(self): self.opened = []
    def take_input(self): return True
    def open_external(self, uri): self.opened.append(uri); return True


def test_on_policy_turnstile_frame_after_a_click_opens_nothing():
    w = FakeWin()
    d = Decision(Nav(NT.OTHER, uri="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/f/av0/rch/x"))
    assert m.Window.on_policy(w, None, d, m.WebKit.PolicyDecisionType.NAVIGATION_ACTION) is True
    assert d.ignored and w.opened == []


def test_on_policy_clicked_outside_link_goes_to_the_browser_once():
    w = FakeWin(); d = Decision(Nav(NT.LINK_CLICKED, uri="https://github.com/Kernlux"))
    m.Window.on_policy(w, None, d, m.WebKit.PolicyDecisionType.NAVIGATION_ACTION)
    assert d.ignored and w.opened == ["https://github.com/Kernlux"]


def test_on_create_follows_the_same_rule():
    w = FakeWin()
    assert m.Window.on_create(w, None, Nav(NT.OTHER, uri="https://challenges.cloudflare.com/x")) is None and w.opened == []
    m.Window.on_create(w, None, Nav(NT.LINK_CLICKED, uri="https://github.com/x"))
    assert w.opened == ["https://github.com/x"]
