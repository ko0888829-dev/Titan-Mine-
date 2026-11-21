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

DB_NODE = "titan_tt_users"
TASKS_NODE = "titan_tt_tasks"
WITHDRAW_NODE = "titan_tt_withdrawals"
ORDERS_NODE = "titan_tt_orders"
SETTINGS_NODE = "titan_tt_settings"
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def tg_post(method: str, payload: dict):
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(f"{TG_API}/{method}", json=payload)
        return res.json()


@app.post("/api/buy_notify")
async def buy_notify(req: Request):
    """Alert Admin when user directly purchases TT with TON inside Mini App"""
    data = await req.json()
    uid = str(data.get("uid", ""))
    name = data.get("name", "Miner")
    username = data.get("username", "")
    tt_amount = float(data.get("ttAmount", 0))
    ton_paid = float(data.get("tonPaid", 0))
    wallet = data.get("wallet", "")

    if not uid or tt_amount <= 0 or not wallet:
        return {"ok": False, "error": "Invalid order"}

    oid = f"buy_{int(time.time())}_{uid}"
    record = {
        "id": oid,
        "uid": uid,
        "name": name,
        "username": username,
        "ttAmount": tt_amount,
        "tonPaid": ton_paid,
        "wallet": wallet,
        "status": "paid_ton",
        "createdAt": int(time.time())
    }

    async with httpx.AsyncClient(timeout=12) as client:
        await client.put(f"{FIREBASE_URL}/{ORDERS_NODE}/{oid}.json", json=record)

    user_tag = f"@{username}" if username else f"ID: {uid}"
    await tg_post("sendMessage", {
        "chat_id": ADMIN_ID,
        "text": (
            "💰 <b>NEW DIRECT TT PURCHASE ORDER</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Buyer:</b> {name} ({user_tag})\n"
            f"🆔 <b>UID:</b> <code>{uid}</code>\n"
            f"💎 <b>TON Paid:</b> <b>{ton_paid:.4f} TON</b> (incl. 0.1 fee)\n"
            f"🪙 <b>Send TT Amount:</b> <b>{tt_amount:,.2f} TT</b>\n"
            f"👛 <b>Buyer TON Wallet:</b>\n<code>{wallet}</code>\n"
            f"📝 <b>Tx Memo:</b> <code>TITAN_BUY:{uid}:{tt_amount}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Send TT to buyer wallet & tap below:"
        ),
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ Mark TT Sent", "callback_data": f"buy_done:{oid}"}
            ]]
        }
    })
    return {"ok": True, "orderId": oid}


@app.post("/api/withdraw_notify")
async def withdraw_notify(req: Request):
    data = await req.json()
    uid = str(data.get("uid", ""))
    name = data.get("name", "Miner")
    username = data.get("username", "")
    amount = float(data.get("amount", 0))
    wallet = data.get("wallet", "")
    onchain_tt = float(data.get("onChainTT", 0))
    req_hold = amount * 0.25

    if not uid or amount < 100 or not wallet:
        return {"ok": False, "error": "Invalid withdrawal parameters"}

    wid = f"wd_{int(time.time())}_{uid}"
    record = {
        "id": wid,
        "uid": uid,
        "name": name,
        "username": username,
        "amount": amount,
        "wallet": wallet,
        "onChainTT": onchain_tt,
        "status": "pending",
        "createdAt": int(time.time())
    }

    async with httpx.AsyncClient(timeout=12) as client:
        await client.put(f"{FIREBASE_URL}/{WITHDRAW_NODE}/{wid}.json", json=record)

    user_tag = f"@{username}" if username else f"ID: {uid}"
    await tg_post("sendMessage", {
        "chat_id": ADMIN_ID,
        "text": (
            "💸 <b>NEW TITAN (TT) WITHDRAWAL REQUEST</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>User:</b> {name} ({user_tag})\n"
            f"🆔 <b>UID:</b> <code>{uid}</code>\n"
            f"💰 <b>Withdraw Amount:</b> <b>{amount:,.2f} TT</b>\n"
            f"🔒 <b>25% Hold Check:</b> {onchain_tt:,.2f} / {req_hold:,.2f} TT ✅\n"
            f"👛 <b>TON Wallet:</b>\n<code>{wallet}</code>\n"
            f"📝 <b>Memo:</b> <code>TITAN_PAYOUT:{wid}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Tap below after sending TT:"
        ),
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ Mark Paid", "callback_data": f"wd_approve:{wid}"},
                {"text": "❌ Reject & Refund", "callback_data": f"wd_reject:{wid}"}
            ]]
        }
    })
    return {"ok": True, "withdrawId": wid}


@app.get("/api/bot")
async def health_check():
    return {"status": "running", "webapp_url": WEBAPP_URL, "admin_id": ADMIN_ID}


@app.post("/api/bot")
async def telegram_webhook(req: Request):
    try:
        update = await req.json()

        # ==================== ADMIN CALLBACK BUTTONS ====================
        cb = update.get("callback_query")
        if cb:
            cb_id = cb["id"]
            from_id = cb["from"]["id"]
            cb_data = cb.get("data", "")
            msg_obj = cb.get("message", {})

            if from_id == ADMIN_ID:
                # 1. Direct Buy TT Delivered
                if cb_data.startswith("buy_done:"):
                    oid = cb_data.split(":", 1)[1]
                    async with httpx.AsyncClient(timeout=12) as client:
                        o_res = await client.get(f"{FIREBASE_URL}/{ORDERS_NODE}/{oid}.json")
                        o_data = o_res.json()
                        if not o_data or o_data.get("status") == "delivered":
                            await tg_post("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Already delivered!"})
                            return {"ok": True}

                        await client.patch(f"{FIREBASE_URL}/{ORDERS_NODE}/{oid}.json", json={"status": "delivered"})
                        await tg_post("editMessageText", {
                            "chat_id": ADMIN_ID,
                            "message_id": msg_obj["message_id"],
                            "text": msg_obj.get("text", "") + "\n\n✅ <b>STATUS: TT SENT TO BUYER</b>",
                            "parse_mode": "HTML"
                        })
                        await tg_post("sendMessage", {
                            "chat_id": int(o_data["uid"]),
                            "text": f"🎉 <b>TT Order Delivered!</b>\n<b>{o_data['ttAmount']:,.2f} TT</b> has been sent to your TON wallet!\nRefresh your wallet balance in TITAN App to see your new level.",
                            "parse_mode": "HTML"
                        })
                    await tg_post("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Marked Delivered!"})
                    return {"ok": True}

                # 2. Withdraw Approve / Reject
                if cb_data.startswith("wd_approve:") or cb_data.startswith("wd_reject:"):
                    action, wid = cb_data.split(":", 1)
                    async with httpx.AsyncClient(timeout=12) as client:
                        w_res = await client.get(f"{FIREBASE_URL}/{WITHDRAW_NODE}/{wid}.json")
                        w_data = w_res.json()

                        if not w_data or w_data.get("status") != "pending":
                            await tg_post("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Already processed!"})
                            return {"ok": True}

                        uid = str(w_data["uid"])
                        amt = float(w_data["amount"])

                        if action == "wd_approve":
                            await client.patch(f"{FIREBASE_URL}/{WITHDRAW_NODE}/{wid}.json", json={"status": "paid"})
                            await tg_post("editMessageText", {
                                "chat_id": ADMIN_ID,
                                "message_id": msg_obj["message_id"],
                                "text": msg_obj.get("text", "") + "\n\n✅ <b>STATUS: PAID & COMPLETED</b>",
                                "parse_mode": "HTML"
                            })
                            await tg_post("sendMessage", {
                                "chat_id": int(uid),
                                "text": f"🎉 <b>Withdrawal Paid!</b>\nYour withdrawal of <b>{amt:,.2f} TT</b> has been sent to your TON wallet!\nMemo: <code>TITAN_PAYOUT:{wid}</code>",
                                "parse_mode": "HTML"
                            })
                        else:
                            await client.patch(f"{FIREBASE_URL}/{WITHDRAW_NODE}/{wid}.json", json={"status": "rejected"})
                            u_res = await client.get(f"{FIREBASE_URL}/{DB_NODE}/{uid}/appBalance.json")
                            cur_bal = float(u_res.json() or 0)
                            await client.patch(f"{FIREBASE_URL}/{DB_NODE}/{uid}.json", json={"appBalance": cur_bal + amt})
                            await tg_post("editMessageText", {
                                "chat_id": ADMIN_ID,
                                "message_id": msg_obj["message_id"],
                                "text": msg_obj.get("text", "") + "\n\n❌ <b>STATUS: REJECTED & REFUNDED</b>",
                                "parse_mode": "HTML"
                            })
                            await tg_post("sendMessage", {
                                "chat_id": int(uid),
                                "text": f"⚠️ <b>Withdrawal Rejected</b>\nYour request for <b>{amt:,.2f} TT</b> was declined and refunded to your App Balance.",
                                "parse_mode": "HTML"
                            })

                    await tg_post("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Updated!"})
            return {"ok": True}

        # ==================== TEXT MESSAGES ====================
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

        if int(user_id) == ADMIN_ID:
            if text == "/admin":
                async with httpx.AsyncClient(timeout=15) as client:
                    res = await client.get(f"{base}.json")
                    users_data = res.json() or {}
                    w_res = await client.get(f"{FIREBASE_URL}/{WITHDRAW_NODE}.json")
                    w_data = w_res.json() or {}
                    s_res = await client.get(f"{FIREBASE_URL}/{SETTINGS_NODE}/tonPerTT.json")
                    cur_price = s_res.json() or 0.18

                total_users = len(users_data)
                verified_users = sum(1 for u in users_data.values() if isinstance(u, dict) and u.get("verified"))
                multi_flagged = sum(1 for u in users_data.values() if isinstance(u, dict) and u.get("isMultiFlagged"))
                pending_wds = sum(1 for w in w_data.values() if isinstance(w, dict) and w.get("status") == "pending")
                total_app_tt = sum(float(u.get("appBalance", 0)) for u in users_data.values() if isinstance(u, dict))

                await tg_post("sendMessage", {
                    "chat_id": chat_id,
                    "text": (
                        "👑 <b>TITAN (TT) ADMIN CONTROL PANEL</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"👥 <b>Total Users:</b> {total_users:,}\n"
                        f"🛡️ <b>Verified (0.1 TON):</b> {verified_users:,}\n"
                        f"💸 <b>Pending Withdrawals:</b> {pending_wds:,}\n"
                        f"🚨 <b>Multi-Account Flagged:</b> {multi_flagged:,}\n"
                        f"💰 <b>Total App TT:</b> {total_app_tt:,.2f} TT\n"
                        f"🏷️ <b>Direct Buy Price:</b> 1 TT = <b>{cur_price} TON</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "💵 <b>Price & Task Management:</b>\n"
                        "• <code>/setprice 0.18</code> - 1 TT ဈေးနှုန်းပြင်ရန်\n"
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

            if text.startswith("/setprice "):
                try:
                    new_price = float(text.split()[1].strip())
                    if new_price > 0:
                        async with httpx.AsyncClient(timeout=10) as client:
                            await client.put(f"{FIREBASE_URL}/{SETTINGS_NODE}/tonPerTT.json", json=new_price)
                        await tg_post("sendMessage", {
                            "chat_id": chat_id,
                            "text": f"✅ Direct Buy Price updated: <b>1 TT = {new_price} TON</b>",
                            "parse_mode": "HTML"
                        })
                except Exception:
                    pass
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
                                        f"<b>{first_name}</b> joined via your link. Once they verify (0.1 TON) AND hold at least <b>8 TT (Lv.2)</b>, "
                                        f"you earn <b>5%</b> of all their mining claims!"
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
                    "👥 <b>Referral Reward:</b> 5% commission from friends holding Lv.2+ (8+ TT)\n\n"
                    "Tap below to launch your mining rig:"
                ),
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "⚡ Launch TITAN Mining App", "web_app": {"url": launch_url}}]
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
