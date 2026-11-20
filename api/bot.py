import os
import httpx
from fastapi import FastAPI, Request

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://titan-mine-bot.vercel.app").strip().rstrip("/")
FIREBASE_URL = os.getenv("FIREBASE_URL", "https://adpro-bot-default-rtdb.firebaseio.com").strip().rstrip("/")
DB_NODE = "titan_tt_users"
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def tg_post(method: str, payload: dict):
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(f"{TG_API}/{method}", json=payload)
        return res.json()


@app.get("/api/bot")
async def health_check():
    return {
        "status": "running",
        "webapp_url": WEBAPP_URL,
        "has_token": bool(BOT_TOKEN),
        "firebase_url": FIREBASE_URL
    }


@app.post("/api/bot")
async def telegram_webhook(req: Request):
    try:
        update = await req.json()
        msg = update.get("message")
        if not msg:
            return {"ok": True}

        chat_id = msg["chat"]["id"]
        user = msg.get("from", {})
        user_id = str(user.get("id", chat_id))
        first_name = user.get("first_name", "Miner")
        text = msg.get("text", "")

        if text.startswith("/start"):
            parts = text.split()
            ref_id = parts[1].replace("ref_", "") if len(parts) > 1 and parts[1].startswith("ref_") else ""
            base = f"{FIREBASE_URL}/{DB_NODE}"

            if FIREBASE_URL:
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        u_res = await client.get(f"{base}/{user_id}.json")
                        if u_res.json() is None:
                            new_user = {
                                "appBalance": 0,
                                "invited": 0,
                                "qualified": 0,
                                "refEarned": 0,
                                "referredBy": ref_id if ref_id != user_id else ""
                            }
                            await client.put(f"{base}/{user_id}.json", json=new_user)

                            if ref_id and ref_id != user_id:
                                r_res = await client.get(f"{base}/{ref_id}/invited.json")
                                cur_inv = r_res.json() or 0
                                await client.put(f"{base}/{ref_id}/invited.json", json=cur_inv + 1)
                                await tg_post("sendMessage", {
                                    "chat_id": int(ref_id),
                                    "text": (
                                        f"👥 <b>New Referral Joined!</b>\n"
                                        f"<b>{first_name}</b> joined via your link. Once they verify their wallet (0.05 TON), "
                                        f"you earn <b>+100 TT</b> + <b>5%</b> of all their mining claims!"
                                    ),
                                    "parse_mode": "HTML"
                                })
                except Exception:
                    pass

            launch_url = f"{WEBAPP_URL}?startapp=ref_{ref_id}" if ref_id else WEBAPP_URL
            await tg_post("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    f"⚡ <b>Welcome to TITAN (TT) Web3 Mining, {first_name}!</b>\n\n"
                    "🪙 <b>Coin:</b> Titan (TT) on TON\n"
                    "⛏️ <b>Mining Rate:</b> 305 TT/day (Up to 15,000 TT/day at Lv.100)\n"
                    "👥 <b>Referral Reward:</b> +100 TT per verified friend + 5% lifetime mining commission\n\n"
                    "Tap below to launch your mining rig:"
                ),
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "⚡ Launch TITAN Mining App", "web_app": {"url": launch_url}}],
                        [{"text": "📊 Trade TT on DeDust.io", "url": "https://dedust.io/swap/TON/EQBgi1gn-GdSOCHI165sseghlgpscI2LfiwDa1ZYa0uUzazt"}]
                    ]
                }
            })
    except Exception as e:
        print("Webhook Error:", str(e))

    return {"ok": True}


@app.get("/api/set_webhook")
async def set_webhook():
    webhook_target = f"{WEBAPP_URL}/api/bot"
    res = await tg_post("setWebhook", {"url": webhook_target, "drop_pending_updates": True})
    return {"webhook_target": webhook_target, "telegram_response": res}
