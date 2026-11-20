import os
import time
import asyncio
import httpx
from fastapi import FastAPI, Request

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://titan-mine-bot.vercel.app").strip().rstrip("/")
FIREBASE_URL = os.getenv("FIREBASE_URL", "https://adpro-bot-default-rtdb.firebaseio.com").strip().rstrip("/")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5330848428"))
TT_JETTON = "EQBgi1gn-GdSOCHI165sseghlgpscI2LfiwDa1ZYa0uUzazt"

DB_NODE = "titan_tt_users"
TASKS_NODE = "titan_tt_tasks"
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def tg_post(method: str, payload: dict):
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(f"{TG_API}/{method}", json=payload)
        return res.json()


@app.get("/api/quote")
async def get_live_quote():
    """Fetch exact live DeDust.io pool reserves & price for Titan (TT) server-side"""
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            # 1. Try DeDust v2 pools
            res = await client.get("https://api.dedust.io/v2/pools")
            if res.status_code == 200:
                pools = res.json()
                for p in pools:
                    assets = p.get("assets", [])
                    has_tt = any(a.get("address") == TT_JETTON for a in assets)
                    has_ton = any(a.get("type") == "native" for a in assets)
                    if has_tt and has_ton and p.get("reserves"):
                        is_native_first = assets[0].get("type") == "native"
                        ton_res = float(p["reserves"][0] if is_native_first else p["reserves"][1]) / 1e9
                        tt_res = float(p["reserves"][1] if is_native_first else p["reserves"][0]) / 1e9
                        if ton_res > 0 and tt_res > 0:
                            return {
                                "ok": True,
                                "source": "DeDust.io",
                                "poolAddress": p.get("address", ""),
                                "tonReserve": ton_res,
                                "ttReserve": tt_res,
                                "rateTTPerTon": tt_res / ton_res
                            }

            # 2. Fallback to TonAPI Rates
            r2 = await client.get(f"https://tonapi.io/v2/rates?tokens={TT_JETTON}&currencies=ton")
            if r2.status_code == 200:
                rates = r2.json().get("rates", {})
                tt_info = rates.get(TT_JETTON, {}).get("prices", {})
                ton_price = float(tt_info.get("TON", 0))
                if ton_price > 0:
                    rate_tt_per_ton = 1.0 / ton_price
                    return {
                        "ok": True,
                        "source": "TonAPI",
                        "poolAddress": "",
                        "tonReserve": 1000.0,
                        "ttReserve": 1000.0 * rate_tt_per_ton,
                        "rateTTPerTon": rate_tt_per_ton
                    }
    except Exception as e:
        return {"ok": False, "error": str(e)}

    return {"ok": False, "error": "Pool not indexed yet"}


@app.get("/api/bot")
async def health_check():
    return {"status": "running", "webapp_url": WEBAPP_URL, "admin_id": ADMIN_ID}


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
        text = msg.get("text", "").strip()

        base = f"{FIREBASE_URL}/{DB_NODE}"
        tasks_base = f"{FIREBASE_URL}/{TASKS_NODE}"

        # ==================== ADMIN PANEL COMMANDS ====================
        if int(user_id) == ADMIN_ID:
            if text == "/admin":
                async with httpx.AsyncClient(timeout=15) as client:
                    res = await client.get(f"{base}.json")
                    users_data = res.json() or {}

                total_users = len(users_data)
                verified_users = sum(1 for u in users_data.values() if isinstance(u, dict) and u.get("verified"))
                multi_flagged = sum(1 for u in users_data.values() if isinstance(u, dict) and u.get("isMultiFlagged"))
                total_app_tt = sum(float(u.get("appBalance", 0)) for u in users_data.values() if isinstance(u, dict))

                await tg_post("sendMessage", {
                    "chat_id": chat_id,
                    "text": (
                        "👑 <b>TITAN (TT) ADMIN CONTROL PANEL</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"👥 <b>Total Users:</b> {total_users:,}\n"
                        f"🛡️ <b>Verified (0.1 TON):</b> {verified_users:,}\n"
                        f"🚨 <b>Multi-Account Flagged:</b> {multi_flagged:,}\n"
                        f"💰 <b>Total App TT:</b> {total_app_tt:,.2f} TT\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "📋 <b>Task Management:</b>\n"
                        "• <code>/tasks</code> - လက်ရှိ Task စာရင်းကြည့်ရန်\n"
                        "• <code>/addtask Title | Reward | URL</code>\n"
                        "• <code>/deltask TASK_ID</code> - Task ဖျက်ရန်\n\n"
                        "🛡️ <b>Security & Users:</b>\n"
                        "• <code>/multi</code> - Device/IP ထပ်နေသူများစစ်ရန်\n"
                        "• <code>/ban USER_ID</code> | <code>/unban USER_ID</code>\n"
                        "• <code>/addtt USER_ID AMOUNT</code>\n"
                        "• <code>/broadcast စာသား</code>"
                    ),
                    "parse_mode": "HTML"
                })
                return {"ok": True}

            if text == "/tasks":
                async with httpx.AsyncClient(timeout=10) as client:
                    t_res = await client.get(f"{tasks_base}.json")
                    t_data = t_res.json() or {}

                if not t_data:
                    await tg_post("sendMessage", {
                        "chat_id": chat_id,
                        "text": "📭 Custom Task မရှိသေးပါ။\n\nအသစ်ထည့်ရန်:\n<code>/addtask Join Channel | 2 | https://t.me/yourchannel</code>",
                        "parse_mode": "HTML"
                    })
                else:
                    lines = ["📋 <b>Active Station Tasks:</b>\n"]
                    for tid, tv in t_data.items():
                        if isinstance(tv, dict):
                            lines.append(f"• ID: <code>{tid}</code>\n  <b>{tv.get('title')}</b> (+{tv.get('reward')} TT)\n  🔗 {tv.get('url')}\n")
                    lines.append("ဖျက်ရန်: <code>/deltask TASK_ID</code>")
                    await tg_post("sendMessage", {"chat_id": chat_id, "text": "\n".join(lines), "parse_mode": "HTML"})
                return {"ok": True}

            if text.startswith("/addtask "):
                raw = text.replace("/addtask ", "", 1)
                parts = [p.strip() for p in raw.split("|")]
                if len(parts) >= 3:
                    title, reward, url = parts[0], float(parts[1]), parts[2]
                    desc = parts[3] if len(parts) >= 4 else "Visit link & earn instant TT"
                    tid = f"task_{int(time.time())}"
                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.put(f"{tasks_base}/{tid}.json", json={
                            "type": "PROMOTED • INSTANT",
                            "title": title,
                            "desc": desc,
                            "reward": reward,
                            "url": url
                        })
                    await tg_post("sendMessage", {
                        "chat_id": chat_id,
                        "text": f"✅ <b>Task Added!</b>\nID: <code>{tid}</code>\nTitle: <b>{title}</b> (+{reward} TT)",
                        "parse_mode": "HTML"
                    })
                else:
                    await tg_post("sendMessage", {
                        "chat_id": chat_id,
                        "text": "⚠️ Format မှားနေပါသည်။ ဤသို့ရေးပါ:\n<code>/addtask Join Channel | 2 | https://t.me/example</code>",
                        "parse_mode": "HTML"
                    })
                return {"ok": True}

            if text.startswith("/deltask "):
                tid = text.replace("/deltask ", "", 1).strip()
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.delete(f"{tasks_base}/{tid}.json")
                await tg_post("sendMessage", {"chat_id": chat_id, "text": f"🗑️ Deleted task: <code>{tid}</code>", "parse_mode": "HTML"})
                return {"ok": True}

            if text == "/multi":
                async with httpx.AsyncClient(timeout=15) as client:
                    res = await client.get(f"{base}.json")
                    users_data = res.json() or {}

                flagged = [
                    (uid, u) for uid, u in users_data.items()
                    if isinstance(u, dict) and u.get("isMultiFlagged")
                ]
                if not flagged:
                    await tg_post("sendMessage", {"chat_id": chat_id, "text": "✅ Multi-Account (Device/IP ထပ်နေသူ) မတွေ့ရှိပါ။"})
                else:
                    lines = ["🚨 <b>Multi-Account Flagged Users (Device / IP):</b>\n"]
                    for uid, u in flagged[:20]:
                        lines.append(
                            f"• UID: <code>{uid}</code> | Bal: {u.get('appBalance', 0):.2f} TT\n"
                            f"  Dev: <code>{u.get('deviceId', 'N/A')}</code> | IP: <code>{u.get('lastIp', 'N/A')}</code>"
                        )
                    lines.append("\nပိတ်ရန်: <code>/ban USER_ID</code>")
                    await tg_post("sendMessage", {"chat_id": chat_id, "text": "\n".join(lines), "parse_mode": "HTML"})
                return {"ok": True}

            if text.startswith("/ban ") or text.startswith("/unban "):
                is_ban = text.startswith("/ban ")
                target_id = text.split()[1].strip()
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.patch(f"{base}/{target_id}.json", json={"banned": is_ban})
                status_lbl = "🚫 BANNED" if is_ban else "✅ UNBANNED"
                await tg_post("sendMessage", {"chat_id": chat_id, "text": f"{status_lbl}: User <code>{target_id}</code>", "parse_mode": "HTML"})
                return {"ok": True}

            if text.startswith("/addtt "):
                parts = text.split()
                if len(parts) == 3:
                    target_id, amt = parts[1], float(parts[2])
                    async with httpx.AsyncClient(timeout=10) as client:
                        u_res = await client.get(f"{base}/{target_id}.json")
                        u_data = u_res.json() or {}
                        new_bal = float(u_data.get("appBalance", 0)) + amt
                        await client.patch(f"{base}/{target_id}.json", json={"appBalance": new_bal})
                    await tg_post("sendMessage", {
                        "chat_id": chat_id,
                        "text": f"✅ Added <b>+{amt} TT</b> to <code>{target_id}</code> (New: {new_bal:.2f} TT)",
                        "parse_mode": "HTML"
                    })
                return {"ok": True}

            if text.startswith("/broadcast "):
                b_msg = text.replace("/broadcast ", "", 1).strip()
                if b_msg:
                    async with httpx.AsyncClient(timeout=20) as client:
                        res = await client.get(f"{base}.json")
                        users_data = res.json() or {}

                    sent, failed = 0, 0
                    for uid in users_data.keys():
                        try:
                            r = await tg_post("sendMessage", {
                                "chat_id": int(uid),
                                "text": f"📢 <b>TITAN Announcement</b>\n\n{b_msg}",
                                "parse_mode": "HTML",
                                "reply_markup": {
                                    "inline_keyboard": [[{"text": "⚡ Open TITAN App", "web_app": {"url": WEBAPP_URL}}]]
                                }
                            })
                            if r.get("ok"):
                                sent += 1
                            else:
                                failed += 1
                            await asyncio.sleep(0.05)
                        except Exception:
                            failed += 1
                    await tg_post("sendMessage", {"chat_id": chat_id, "text": f"✅ Broadcast Sent: {sent} | Failed: {failed}"})
                return {"ok": True}

        # ==================== USER /START COMMAND ====================
        if text.startswith("/start"):
            parts = text.split()
            ref_id = parts[1].replace("ref_", "") if len(parts) > 1 and parts[1].startswith("ref_") else ""

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
                                        f"<b>{first_name}</b> joined via your link. Once they verify their wallet (0.1 TON), "
                                        f"you earn <b>+5 TT</b> + <b>5%</b> of all their mining claims!"
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
                    "🪙 <b>Coin:</b> Titan (TT) on TON (~$1.00)\n"
                    "⛏️ <b>Mining Rate:</b> 10 TT/day (0.42 TT/hr) • Up to 500 TT/day at Lv.100\n"
                    "👥 <b>Referral Reward:</b> +5 TT per verified friend + 5% lifetime mining commission\n\n"
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
