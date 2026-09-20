from playwright.sync_api import sync_playwright

def save_session():
    with sync_playwright() as p:
        # 本物のChromeを自動化フラグを隠して起動
        browser = p.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.goto("https://x.com/i/flow/login")
        
        input("ログイン完了後、タイムラインが表示されたらPowerShellでEnterを押してください...")
        
        context.storage_state(path="x_state.json")
        print("x_state.json の保存に成功しました！")
        browser.close()

if __name__ == "__main__":
    save_session()
