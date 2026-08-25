#!/usr/bin/env python3
# blackboard session helper: sso login via playwright, then reuse the saved
# storage state for plain api calls.

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, sync_playwright

BASE = os.environ.get("CB_BB_BASE", "https://harvey.utulsa.edu")
STATE = Path(os.environ.get("CB_BB_STATE", Path.home() / ".course-brain" / "bb-state.json"))
OP_ITEM = os.environ.get("CB_OP_ITEM", "Utulsa")
OP_VAULT = os.environ.get("CB_OP_VAULT", "")  # service accounts need an explicit vault

ME = "/learn/api/v1/users/me"
LOGIN_DEADLINE_SEC = 120


def op_env():
    # unattended runs need OP_SERVICE_ACCOUNT_TOKEN in the environment;
    # interactively, the 1password desktop-app integration covers `op` without one
    return os.environ.copy()


def op_bin():
    if shutil.which("op"):
        return "op"
    for p in ("/usr/local/bin/op", "/opt/homebrew/bin/op"):
        if os.path.exists(p):
            return p
    return "op"


def op(args):
    cmd = [op_bin(), "item", "get", OP_ITEM]
    if OP_VAULT:
        cmd += ["--vault", OP_VAULT]
    try:
        r = subprocess.run(cmd + args, capture_output=True, text=True, env=op_env())
    except FileNotFoundError:
        sys.stderr.write("1password cli not found; install it: brew install 1password-cli\n")
        sys.exit(1)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(1)
    return r.stdout


def creds():
    out = op(["--fields", "label=username,label=password", "--reveal", "--format", "json"])
    data = json.loads(out)
    fields = {}
    for f in ([data] if isinstance(data, dict) else data):
        # key by field id and label - labels drift (e.g. password renamed "p1")
        for k in (f.get("id"), f.get("label")):
            if k and k not in fields:
                fields[k] = f.get("value", "")
    user = fields["username"]
    if "@" not in user:
        user += "@utulsa.edu"
    return user, fields["password"]


def totp():
    return op(["--otp"]).strip()


def logged_in(page):
    if not page.url.startswith(BASE) or "/ultra" not in page.url:
        return False
    try:
        r = page.request.get(BASE + ME, headers={"Accept": "application/json"})
        return r.ok and "json" in (r.headers.get("content-type") or "")
    except Exception:
        return False


def js_focus(page, css):
    # focus the first *displayed* match; entra keeps decoy inputs css-visible
    return page.evaluate(
        """(css)=>{const els=[...document.querySelectorAll(css)]"""
        """.filter(e=>e.offsetParent!==null&&e.getBoundingClientRect().width>0);"""
        """if(!els.length)return false;els[0].focus();return true;}""", css)


def dbg(msg):
    if os.environ.get("CB_DEBUG"):
        sys.stderr.write(f"[bb] {msg}\n")


def visible(page, selector):
    try:
        el = page.locator(selector).first
        return el.count() > 0 and el.is_visible()
    except Exception:
        return False


def click_text(page, pattern):
    for role in ("link", "button"):
        el = page.get_by_role(role, name=re.compile(pattern, re.I)).first
        if el.count() > 0 and el.is_visible():
            el.click()
            return True
    return False


def do_login(headed=False):
    user, password = creds()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=not headed)
        context = browser.new_context()  # fresh; a dead session shouldn't pollute
        page = context.new_page()
        page.goto(BASE + "/ultra/course", wait_until="domcontentloaded")

        end = time.monotonic() + LOGIN_DEADLINE_SEC
        while time.monotonic() < end:
            if logged_in(page):
                STATE.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(STATE))
                STATE.chmod(0o600)
                browser.close()
                sys.stderr.write("login ok\n")
                return

            # visible text only; entra's inline $Config blob would match anything
            try:
                text = page.inner_text("body")
            except Exception:
                text = ""

            dbg(f"loop: {page.url[:100]}")
            # a click can race a navigation and time out; just look again
            try:
                if re.search(r"privacy, cookies and terms", text, re.I) and (dbg("branch: consent") or True) and click_text(page, r"^OK$"):
                    # blackboard's consent modal blocks the sso button; auto-accept it
                    pass
                elif page.url.startswith(BASE) and click_text(page, r"sso|sign in|university"):
                    dbg("branch: sso click")
                elif re.search(r"enter password", text, re.I):
                    # dispatch on the screen heading; input-visibility lies on entra pages
                    dbg("branch: passwd screen")
                    if js_focus(page, "input[name=passwd],input[type=password]"):
                        page.keyboard.type(password, delay=40)
                        page.wait_for_timeout(300)
                        page.keyboard.press("Enter")
                elif re.search(r"enter code|enter the code|verification code", text, re.I) and js_focus(page, "input[name=otc],input[type=tel]"):
                    dbg("branch: otc screen")
                    page.keyboard.type(totp(), delay=40)
                    page.wait_for_timeout(300)
                    page.keyboard.press("Enter")
                elif re.search(r"verify your identity", text, re.I):
                    dbg("branch: method picker")
                    if not click_text(page, r"use a verification code"):
                        page.keyboard.press("Enter")
                elif re.search(r"text.*\+X|we texted|approve.*request|open your authenticator app", text, re.I):
                    dbg("branch: switch to code")
                    # sms/push is the default method; switch to a totp code
                    if click_text(page, r"sign in another way|other ways|use a different"):
                        page.wait_for_timeout(1000)
                        click_text(page, r"verification code")
                elif re.search(r"sign in", text, re.I) and js_focus(page, "input[name=loginfmt]"):
                    dbg("branch: username screen")
                    page.keyboard.type(user, delay=40)
                    page.wait_for_timeout(300)
                    page.keyboard.press("Enter")
                elif re.search(r"stay signed in", text, re.I):
                    dbg("branch: kmsi")
                    page.keyboard.press("Enter")
                else:
                    page.wait_for_timeout(1000)
                    continue
            except PlaywrightError as e:
                dbg(f"caught: {str(e).splitlines()[0][:160]}")
                page.wait_for_timeout(1000)
                continue

            page.wait_for_timeout(1500)

        shot = STATE.parent / "login-fail.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        url = page.url
        page.screenshot(path=str(shot))
        shot.chmod(0o600)  # may show the otc field
        browser.close()
        sys.stderr.write(f"login timed out at {url} (screenshot: {shot})\n")
        sys.exit(1)


def api(pw, path):
    ctx = pw.request.new_context(storage_state=str(STATE), base_url=BASE)
    r = ctx.get(path, headers={"Accept": "application/json"})
    ctype = r.headers.get("content-type") or ""
    dead = (
        r.status in (401, 302)
        or not r.url.startswith(BASE)
        or "login.microsoftonline.com" in r.url
        or "text/html" in ctype
    )
    # bounced to the idp = never really had a session; anything else = it went stale
    bounced = not r.url.startswith(BASE) or "login.microsoftonline.com" in r.url
    body = r.text()
    ctx.dispose()
    return dead, r.status, body, bounced


def cmd_check():
    if not STATE.exists():
        print("no state, run: scripts/bb login")
        return 2
    with sync_playwright() as pw:
        dead, status, body, bounced = api(pw, ME)
    if dead:
        print("no session" if bounced else "expired")
        return 2
    try:
        me = json.loads(body)
    except ValueError:
        print("expired")
        return 2
    print("ok: " + str(me.get("userName") or me.get("id") or ""))
    return 0


def api_or_login(path):
    # one retry behind a fresh login; None means it's still dead
    with sync_playwright() as pw:
        dead, status, body, _ = api(pw, path) if STATE.exists() else (True, 0, "", True)
    if not dead:
        return status, body
    do_login()
    with sync_playwright() as pw:
        dead, status, body, _ = api(pw, path)
    if dead:
        sys.stderr.write(f"request failed after login: {status} {path}\n")
        return None, None
    return status, body


def cmd_get(path, raw=False):
    if not path.startswith("/"):
        sys.stderr.write("path must start with /\n")
        return 1
    status, body = api_or_login(path)
    if body is None:
        return 1
    if raw:
        print(body)
        return 0
    try:
        print(json.dumps(json.loads(body), indent=2))
    except ValueError:
        print(body)
    return 0


def cmd_courses():
    path = "/learn/api/v1/users/me/memberships?expand=course"
    status, body = api_or_login(path)
    if body is None:
        return 1
    try:
        data = json.loads(body)
    except ValueError:
        sys.stderr.write(body + "\n")
        sys.stderr.write(f"unexpected response ({status}); try: scripts/bb get <other path> --raw\n")
        return 1
    for m in data.get("results", data if isinstance(data, list) else []):
        course = m.get("course") or {}
        print("\t".join([
            str(m.get("courseId") or course.get("id") or ""),
            str(course.get("name") or ""),
            str(course.get("courseId") or ""),
        ]))
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("login")
    lg.add_argument("--headed", action="store_true")
    sub.add_parser("check")
    g = sub.add_parser("get")
    g.add_argument("path")
    g.add_argument("--raw", action="store_true")
    sub.add_parser("courses")
    a = p.parse_args()

    if a.cmd == "login":
        do_login(a.headed)
        return 0
    if a.cmd == "check":
        return cmd_check()
    if a.cmd == "get":
        return cmd_get(a.path, a.raw)
    return cmd_courses()


if __name__ == "__main__":
    sys.exit(main())
