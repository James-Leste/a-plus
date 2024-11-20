import re
from playwright.sync_api import Page, expect


def test_language_button_visibility(page: Page) -> None:
    page.goto("http://localhost:8000/?hl=en")
    expect(page.get_by_role("button", name="FI")).to_be_visible()
    page.goto("http://localhost:8000/accounts/login/?fi=en")
    expect(page.get_by_role("button", name="FI")).to_be_visible()
    page.goto("http://localhost:8000/accounts/privacy-notice/?hl=en")
    expect(page.get_by_role("button", name="FI")).to_be_visible()
    page.goto("http://localhost:8000/accounts/accessibility-statement/?hl=en")
    expect(page.get_by_role("button", name="FI")).to_be_visible()
    page.goto("http://localhost:8000/accounts/support/?hl=en")
    expect(page.get_by_role("button", name="FI")).to_be_visible()
    page.goto("http://localhost:8000/def/current/?hl=en")
    expect(page.get_by_role("button", name="FI")).not_to_be_visible()
    page.goto("http://localhost:8000/def/current/overview/overview/")
    

def test_language_button_usability(page: Page) -> None:
    page.goto("http://localhost:8000/?hl=en")
    expect(page.get_by_role("button", name="FI")).to_be_visible()
    page.get_by_role("button", name="FI").click()
    expect(page.get_by_role("button", name="EN")).to_be_visible()
    expect(page.locator("h1")).to_contain_text("verkkopohjainen oppimisympäristö")
    expect(page.locator("#bs-navbar-collapse")).to_contain_text("Kirjaudu sisään")





