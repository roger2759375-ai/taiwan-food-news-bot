# 台灣食安 & 營養新聞 Telegram Bot

每天定時推播台灣食品安全與營養相關新聞，來源包含食藥署、衛福部及 Google 新聞。

## 快速開始

### 1. 建立 Telegram Bot

1. 在 Telegram 搜尋 **@BotFather**
2. 傳送 `/newbot`，依指示設定 Bot 名稱
3. 取得 **Bot Token**（格式：`123456:ABC-DEF...`）

### 2. 安裝相依套件

```bash
cd taiwan-food-news-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 設定環境變數

```bash
cp .env.example .env
# 編輯 .env，填入你的 Bot Token
```

`.env` 範例：
```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
PUSH_HOUR=8
PUSH_MINUTE=0
```

### 4. 啟動 Bot

```bash
python bot.py
```

### 5. 訂閱推播

在 Telegram 找到你的 Bot，傳送 `/start` 即完成訂閱。

---

## 可用指令

| 指令 | 說明 |
|------|------|
| `/start` | 訂閱每日推播 |
| `/stop` | 取消訂閱 |
| `/news` | 立即取得今日新聞 |
| `/help` | 顯示說明 |

---

## 新聞來源

- 🏛️ 食品藥物管理署（FDA）
- 🏥 衛生福利部
- 🔍 Google 新聞 — 食品安全、食安違規、回收下架
- 🥗 Google 新聞 — 台灣營養與飲食健康

---

## 長期在背景執行（macOS）

使用 `launchd` 讓 Bot 在背景持續運行並開機自動啟動：

```bash
# 建立 plist 設定檔（路徑請依實際調整）
cat > ~/Library/LaunchAgents/com.taiwan.foodnewsbot.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.taiwan.foodnewsbot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/你的帳號/Documents/taiwan-food-news-bot/.venv/bin/python</string>
        <string>/Users/你的帳號/Documents/taiwan-food-news-bot/bot.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/你的帳號/Documents/taiwan-food-news-bot</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/foodnewsbot.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/foodnewsbot.err</string>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.taiwan.foodnewsbot.plist
```

查看 log：
```bash
tail -f /tmp/foodnewsbot.log
```

停止：
```bash
launchctl unload ~/Library/LaunchAgents/com.taiwan.foodnewsbot.plist
```

---

## 檔案結構

```
taiwan-food-news-bot/
├── bot.py              # Bot 主程式
├── news_fetcher.py     # 新聞抓取與格式化
├── requirements.txt    # Python 套件
├── .env                # 環境變數（不要上傳 git）
├── .env.example        # 環境變數範例
├── subscribers.json    # 訂閱者清單（自動產生）
└── README.md
```
