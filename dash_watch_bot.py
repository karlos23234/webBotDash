import os
import json
import requests
import time
from datetime import datetime, timezone
import threading
from flask import Flask, request
import telebot

# ===== Environment variables =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
if not BOT_TOKEN or not WEBHOOK_URL:
    raise ValueError("Դուք պետք է ավելացնեք BOT_TOKEN և WEBHOOK_URL որպես Environment Variable")

bot = telebot.TeleBot(BOT_TOKEN)

USERS_FILE = "users.json"
SENT_TX_FILE = "sent_txs.json"

# ===== Helpers =====
def load_json(file):
    return json.load(open(file, "r", encoding="utf-8")) if os.path.exists(file) else {}

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

users = load_json(USERS_FILE)
sent_txs = load_json(SENT_TX_FILE)

def get_dash_price_usd():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=dash&vs_currencies=usd", timeout=10)
        return float(r.json().get("dash", {}).get("usd", 0))
    except:
        return None

def get_latest_txs(address):
    try:
        r = requests.get(f"https://api.blockcypher.com/v1/dash/main/addrs/{address}/full?limit=50", timeout=20)
        return r.json().get("txs", [])
    except:
        return []

def format_alert(tx, address, tx_number, price):
    txid = tx["hash"]
    total_received = sum([o["value"]/1e8 for o in tx.get("outputs", []) if address in (o.get("addresses") or [])])
    usd_text = f" (${total_received*price:.2f})" if price else ""
    timestamp = tx.get("confirmed")
    timestamp = datetime.fromisoformat(timestamp.replace("Z","+00:00")).strftime("%Y-%m-%d %H:%M:%S") if timestamp else "Unknown"
    return (
        f"🔔 Նոր փոխանցում #{tx_number}!\n\n"
        f"📌 Address: {address}\n"
        f"💰 Amount: {total_received:.8f} DASH{usd_text}\n"
        f"🕒 Time: {timestamp}\n"
        f"🔗 https://blockchair.com/dash/transaction/{txid}"
    )

# ===== Telegram Handlers =====
@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "Բարև 👋 Գրի՛ր քո Dash հասցեն (սկսվում է X-ով)")

@bot.message_handler(func=lambda m: m.text and m.text.startswith("X"))
def save_address(msg):
    user_id = str(msg.chat.id)
    address = msg.text.strip()
    users.setdefault(user_id, [])
    if address not in users[user_id]:
        users[user_id].append(address)
    save_json(USERS_FILE, users)

    sent_txs.setdefault(user_id, {})
    sent_txs[user_id].setdefault(address, [])

    # Ուղարկել միայն վերջին 10 TX-երը առաջին անգամ
    txs = get_latest_txs(address)
    price = get_dash_price_usd()
    last_number = 0
    for tx in reversed(txs[-10:]):  # վերջին 10 TX
        last_number += 1
        alert = format_alert(tx, address, last_number, price)
        try:
            bot.send_message(user_id, alert)
        except:
            pass
        sent_txs[user_id][address].append({"txid": tx["hash"], "num": last_number})

    save_json(SENT_TX_FILE, sent_txs)
    bot.reply_to(msg, f"✅ Հասցեն {address} պահպանվեց!")

# ===== Background loop =====
def monitor():
    while True:
        price = get_dash_price_usd()
        for user_id, addresses in users.items():
            for address in addresses:
                txs = get_latest_txs(address)
                known = sent_txs.get(user_id, {}).get(address, [])
                last_number = max([t["num"] for t in known], default=0)
                for tx in reversed(txs[-10:]):  # ստուգել վերջին 10 TX
                    if tx["hash"] in [t["txid"] for t in known]:
                        continue
                    last_number += 1
                    alert = format_alert(tx, address, last_number, price)
                    try:
                        bot.send_message(user_id, alert)
                    except Exception as e:
                        print("Telegram send error:", e)
                    known.append({"txid": tx["hash"], "num": last_number})
                sent_txs.setdefault(user_id, {})[address] = known
        save_json(SENT_TX_FILE, sent_txs)
        time.sleep(15)

threading.Thread(target=monitor, daemon=True).start()

# ===== Flask server =====
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

bot.remove_webhook()
bot.set_webhook(url=WEBHOOK_URL)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)



