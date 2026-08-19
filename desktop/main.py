"""开发期桌面壳：启动 FastAPI 后显示 Vite 前端。"""
import threading
import uvicorn
import webview
def run_api() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
def main() -> None:
    threading.Thread(target=run_api, daemon=True).start()
    # Use ports dedicated to DELTA so other local Vite apps cannot be opened
    # through this desktop shortcut.
    webview.create_window("DELTA 时空交易终端", "http://127.0.0.1:5184", min_size=(1200, 760))
    webview.start()
if __name__ == "__main__":
    main()
