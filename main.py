import asyncio
import sqlite3
import time
import requests
import aiohttp
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ==========================================
# ⚙️ কনফিগারেশন সমূহ
# ==========================================
# Render পরিবেশ থেকে টোকেন নেওয়ার জন্য os.getenv ব্যবহার করা হয়েছে, না পেলে ডিফল্ট হিসেবে নতুন টোকেন থাকবে
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN", '8816724773:AAGtagQF2r0UvC8_B8TXzfT5MP-Z054fWo')
ZENEX_API_KEY = 'ZNX_KJKFEC3OWABQT5ODQQC3D3JN'
ZENEX_BASE_URL = 'https://api.zenexnetwork.com'

ADMIN_IDS = [7875418255, 6272151736]

MAIN_CHANNEL_ID = '-1003752148195'
MAIN_CHANNEL_LINK = 'https://t.me/earningpointsiam4'

OTP_GROUP_ID = '-1004494019123'
OTP_GROUP_LINK = 'https://t.me/FacebookOTPGroup1'

BOT_USERNAME = '@FastCloudOTP_bot'
BOT_LINK = 'https://t.me/FastCloudOTP_bot'

ZENEX_HEADERS = {'mapikey': ZENEX_API_KEY}

# ==========================================
# 🗄️ DATABASE SETUP
# ==========================================
conn = sqlite3.connect('bot_database.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance REAL DEFAULT 0,
    total_otps INTEGER DEFAULT 0
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS custom_ranges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name TEXT,
    range_code TEXT,
    expires_at INTEGER
)''')

cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('otp_price', '10')")
cursor.execute("INSERT OR IGNORE INTO services (name) VALUES ('Facebook')")
conn.commit()

# Memory Storage
admin_state = {}
active_numbers = {}  # { user_id: {"number": "...", "service": "..."} }

# ==========================================
# 🔒 FORCE JOIN CHECK
# ==========================================
async def check_must_join(bot, user_id):
    if user_id in ADMIN_IDS:
        return True
    try:
        ch_member = await bot.get_chat_member(MAIN_CHANNEL_ID, user_id)
        grp_member = await bot.get_chat_member(OTP_GROUP_ID, user_id)
        
        valid_status = ['creator', 'administrator', 'member']
        return (ch_member.status in valid_status) and (grp_member.status in valid_status)
    except Exception:
        return False

async def send_join_request_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📢 Main Channel", url=MAIN_CHANNEL_LINK)],
        [InlineKeyboardButton("👥 OTP Group", url=OTP_GROUP_LINK)],
        [InlineKeyboardButton("✅ Joined / Check Status", callback_data="check_join_status")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = "⚠️ **বটটি ব্যবহার করতে আপনাকে অবশ্যই আমাদের মূল চ্যানেল এবং ওটিপি গ্রুপে জয়েন করতে হবে!**\n\nনিচের লিংকে ক্লিক করে জয়েন করুন এবং 'Joined' বাটনে চাপ দিন:"
    
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=reply_markup)

# ==========================================
# 🔘 UI MENUS (PERSISTENT KEYBOARD FOR FIXED BUTTONS)
# ==========================================
def get_main_menu_keyboard():
    keyboard = [
        ["Get Number ✅", "Balance ✅"],
        ["Support 🤝"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

async def send_admin_panel(update: Update):
    keyboard = [
        [InlineKeyboardButton("1. Per OTP Price Change 💰", callback_data="admin_change_price")],
        [InlineKeyboardButton("2. Add Service ➕", callback_data="admin_add_service")],
        [InlineKeyboardButton("3. Add Service Range 🎯", callback_data="admin_add_range")],
        [InlineKeyboardButton("4. Delete Service 🗑️", callback_data="admin_delete_service")],
        [InlineKeyboardButton("📢 Ultra Fast Broadcast", callback_data="admin_broadcast")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = "⚙️ **Admin Control Panel**\n\nআপনি একজন অ্যাডমিন! সিস্টেম ম্যানেজ করার জন্য অপশন বেছে নিন:"
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=reply_markup)

# ==========================================
# 📥 MESSAGE HANDLER
# ==========================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text

    if not text:
        return

    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()

    # Admin Command Check
    if (text.lower() in ['admin', '/admin']) and user_id in ADMIN_IDS:
        await send_admin_panel(update)
        return

    # 🔴 ADMIN INPUT HANDLING
    if user_id in admin_state:
        state = admin_state[user_id]

        if state.get('step') == 'awaiting_price':
            try:
                new_price = float(text)
                cursor.execute("UPDATE settings SET value = ? WHERE key = 'otp_price'", (str(new_price),))
                conn.commit()
                del admin_state[user_id]
                await update.message.reply_text(f"✅ প্রতি OTP এর মূল্য **{new_price} ৳** সেট করা হয়েছে।", parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
            except ValueError:
                await update.message.reply_text("❌ সঠিক সংখ্যা লিখুন!")
            return

        elif state.get('step') == 'awaiting_service_name':
            try:
                cursor.execute("INSERT OR IGNORE INTO services (name) VALUES (?)", (text.strip(),))
                conn.commit()
                del admin_state[user_id]
                await update.message.reply_text(f"✅ **{text.strip()}** সার্ভিস সফলভাবে যোগ করা হয়েছে!", parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
            except Exception:
                await update.message.reply_text("❌ সমস্যা হয়েছে।")
            return

        elif state.get('step') == 'awaiting_range_code':
            admin_state[user_id] = {'step': 'awaiting_range_service', 'rangeCode': text.strip()}
            cursor.execute("SELECT name FROM services")
            rows = cursor.fetchall()
            keyboard = [[InlineKeyboardButton(r[0], callback_data=f"select_rng_srv_{r[0]}")] for r in rows]
            await update.message.reply_text(
                f"🎯 `{text.strip()}` রেঞ্জটি কোন সার্ভিসের জন্য সেট করতে চান?",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        elif state.get('step') == 'awaiting_range_hours':
            try:
                hours = float(text)
                if hours <= 0:
                    raise ValueError
                expires_at = int((time.time() + (hours * 3600)) * 1000)
                srv_name = state['serviceName']
                rng_code = state['rangeCode']

                cursor.execute("INSERT INTO custom_ranges (service_name, range_code, expires_at) VALUES (?, ?, ?)",
                               (srv_name, rng_code, expires_at))
                conn.commit()
                del admin_state[user_id]
                await update.message.reply_text(f"✅ **{srv_name}** সার্ভিসের জন্য `{rng_code}` রেঞ্জটি **{hours} ঘণ্টার** জন্য অ্যাক্টিভ করা হলো!", parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
            except ValueError:
                await update.message.reply_text("❌ সঠিক ঘণ্টা দিন (যেমন: 1, 2, 5, 24)!")
            return

        elif state.get('step') == 'awaiting_broadcast':
            del admin_state[user_id]
            await update.message.reply_text("🚀 ব্রডকাস্ট মেসেজ দ্রুত পাঠানো শুরু হয়েছে...")

            cursor.execute("SELECT user_id FROM users")
            users = cursor.fetchall()
            success_count = 0

            for u in users:
                try:
                    await context.bot.send_message(chat_id=u[0], text=text, parse_mode='Markdown')
                    success_count += 1
                except Exception:
                    pass

            await update.message.reply_text(f"✅ **{success_count}** জন ইউজারের কাছে ব্রডকাস্ট পাঠানো সম্পন্ন হয়েছে!", parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
            return

        elif state.get('step') == 'user_support':
            del admin_state[user_id]
            for admin_id in ADMIN_IDS:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("💬 Reply User", callback_data=f"reply_user_{user_id}")]])
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"📩 **Support Msg [User: `{user_id}`]:**\n\n{text}",
                        parse_mode='Markdown',
                        reply_markup=kb
                    )
                except Exception:
                    pass
            await update.message.reply_text("✅ আপনার মেসেজটি অ্যাডমিনের কাছে পাঠানো হয়েছে।", reply_markup=get_main_menu_keyboard())
            return

        elif state.get('step') == 'awaiting_reply':
            target_user = state['targetUser']
            del admin_state[user_id]
            try:
                await context.bot.send_message(chat_id=target_user, text=f"💬 **অ্যাডমিন রিপ্লাই:**\n\n{text}", parse_mode='Markdown')
                await update.message.reply_text(f"✅ User `{target_user}` কে উত্তর পাঠানো হয়েছে।", parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
            except Exception:
                await update.message.reply_text("❌ মেসেজ পাঠানো যায়নি।")
            return

    # 🛑 FORCE JOIN CHECK
    is_joined = await check_must_join(context.bot, user_id)
    if not is_joined:
        await send_join_request_msg(update, context)
        return

    # USER NAVIGATION
    if text == '/start':
        name = update.effective_user.first_name
        welcome_msg = f"👋 **স্বাগতম, {name}!**\n\n🤖 **Bot Name:** Facebook~OTP\n⚡ **Status:** Active & Instant OTP Delivery Service\n\nঅপশন সিলেক্ট করে সেবা নেওয়া শুরু করুন!"
        await update.message.reply_text(welcome_msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())

    elif text == 'Get Number ✅':
        cursor.execute("SELECT name FROM services")
        rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("বর্তমানে কোনো সার্ভিস এভেলেবল নেই।", reply_markup=get_main_menu_keyboard())
            return
        keyboard = [[InlineKeyboardButton(f"{r[0]} ✅", callback_data=f"get_srv_num_{r[0]}")] for r in rows]
        await update.message.reply_text("পছন্দের সার্ভিস অপশন সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif text == 'Balance ✅':
        cursor.execute("SELECT value FROM settings WHERE key = 'otp_price'")
        otp_price = float(cursor.fetchone()[0])

        cursor.execute("SELECT balance, total_otps FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        balance = row[0] if row else 0
        total_otps = row[1] if row else 0

        msg_text = (
            f"💰 **আপনার অ্যাকাউন্ট স্টেটমেন্ট:**\n\n"
            f"📥 **মোট প্রাপ্ত OTP:** {total_otps} টি\n"
            f"💵 **প্রতি OTP রেট:** {otp_price} Tk\n"
            f"💳 **বর্তমান ব্যালেন্স:** {balance} Tk\n\n"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("💸 Withdraw", callback_data="withdraw_request")]])
        await update.message.reply_text(msg_text, parse_mode='Markdown', reply_markup=kb)

    elif text == 'Support 🤝':
        admin_state[user_id] = {'step': 'user_support'}
        await update.message.reply_text("✍️ আপনার কথা/সমস্যা বিস্তারিত লিখে মেসেজ দিন, এডমিন খুব দ্রুত উত্তর দিবে:")

# ==========================================
# 🔘 INLINE CALLBACK HANDLER
# ==========================================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data

    if data == 'check_join_status':
        is_joined = await check_must_join(context.bot, user_id)
        if is_joined:
            try:
                await query.message.delete()
            except Exception:
                pass
            await context.bot.send_message(chat_id, "🎉 ধন্যবাদ! জয়েন কমপ্লিট হয়েছে।", reply_markup=get_main_menu_keyboard())
        else:
            await query.answer("❌ আপনি এখনো সবগুলোতে জয়েন করেননি! দয়া করে চেক করুন।", show_alert=True)
        return

    # Admin Handlers
    if user_id in ADMIN_IDS:
        if data == 'admin_change_price':
            admin_state[user_id] = {'step': 'awaiting_price'}
            await context.bot.send_message(chat_id, "💰 **Per OTP Price Change:**\nনতুন প্রতি OTP এর মূল্য কত সেট করতে চান লিখে জানান:")
            return
        elif data == 'admin_add_service':
            admin_state[user_id] = {'step': 'awaiting_service_name'}
            await context.bot.send_message(chat_id, "➕ **Add Service:**\nনতুন সার্ভিসের নাম টাইপ করুন:")
            return
        elif data == 'admin_add_range':
            admin_state[user_id] = {'step': 'awaiting_range_code'}
            await context.bot.send_message(chat_id, "🎯 **Add Service Range:**\nনির্দিষ্ট Range কোডটি দিন (যেমন: `447384XXX`):", parse_mode='Markdown')
            return
        elif data == 'admin_delete_service':
            cursor.execute("SELECT name FROM services")
            rows = cursor.fetchall()
            if not rows:
                await context.bot.send_message(chat_id, "ডিলিট করার মতো কোনো সার্ভিস নেই।")
                return
            keyboard = [[InlineKeyboardButton(f"❌ {r[0]}", callback_data=f"del_srv_act_{r[0]}")] for r in rows]
            await context.bot.send_message(
                chat_id,
                "আপনি কোন সার্ভিসটি ডিলিট করতে চান 🧐?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        elif data.startswith('del_srv_act_'):
            s_name = data.replace('del_srv_act_', '')
            if s_name.lower() == 'facebook':
                await query.answer("⚠️ Facebook সার্ভিসটি ডিলিট করা সম্ভব নয়! এটি সিস্টেমের ডিফল্ট সার্ভিস।", show_alert=True)
                return
            
            cursor.execute("DELETE FROM services WHERE name = ?", (s_name,))
            conn.commit()
            await context.bot.send_message(chat_id, f"✅ **{s_name}** সার্ভিসটি সফলভাবে ডিলিট করা হয়েছে!", parse_mode='Markdown')
            return
        elif data.startswith('select_rng_srv_'):
            s_name = data.replace('select_rng_srv_', '')
            admin_state[user_id]['serviceName'] = s_name
            admin_state[user_id]['step'] = 'awaiting_range_hours'
            await context.bot.send_message(chat_id, f"⏱️ এই **{s_name}** সার্ভিসের জন্য `{admin_state[user_id]['rangeCode']}` রেঞ্জটি কত ঘণ্টার জন্য অ্যাক্টিভ রাখতে চান? ঘণ্টার সংখ্যা লিখুন:", parse_mode='Markdown')
            return
        elif data == 'admin_broadcast':
            admin_state[user_id] = {'step': 'awaiting_broadcast'}
            await context.bot.send_message(chat_id, "📢 **Fast Broadcast:**\nসব ইউজারের কাছে পাঠানোর মেসেজটি সেন্ড করুন:")
            return
        elif data.startswith('reply_user_'):
            target_user = int(data.replace('reply_user_', ''))
            admin_state[user_id] = {'step': 'awaiting_reply', 'targetUser': target_user}
            await context.bot.send_message(chat_id, f"✍️ User `{target_user}` এর জন্য আপনার উত্তরটি টাইপ করুন:", parse_mode='Markdown')
            return

    # ⚡ ULTRA FAST ASYNC NUMBER FETCHING SYSTEM
    if data.startswith('get_srv_num_'):
        is_joined = await check_must_join(context.bot, user_id)
        if not is_joined:
            await send_join_request_msg(update, context)
            return

        service_name = data.replace('get_srv_num_', '')
        
        await context.bot.send_message(chat_id, f"⚡ **{service_name}** এর জন্য সেরা নম্বরের রেঞ্জ প্রসেস করা হচ্ছে...")

        now = int(time.time() * 1000)
        cursor.execute("SELECT range_code FROM custom_ranges WHERE service_name = ? AND expires_at > ? ORDER BY id DESC LIMIT 1", (service_name, now))
        custom_range_row = cursor.fetchone()

        selected_range = "4473845XXX"

        if custom_range_row:
            selected_range = custom_range_row[0]
        else:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{ZENEX_BASE_URL}/v1/active-ranges", headers=ZENEX_HEADERS, timeout=3) as resp:
                        if resp.status == 200:
                            json_data = await resp.json()
                            if json_data.get('success'):
                                matched = [r for r in json_data['data']['active_ranges'] if r['service'].lower() == service_name.lower()]
                                if matched:
                                    matched.sort(key=lambda x: x['hits'], reverse=True)
                                    selected_range = matched[0]['range']
            except Exception:
                pass

        try:
            payload = {"range": selected_range, "is_national": False, "remove_plus": False}
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{ZENEX_BASE_URL}/v1/getnum", json=payload, headers=ZENEX_HEADERS, timeout=5) as resp:
                    res_json = await resp.json()

                    if res_json.get('meta', {}).get('code') == 200:
                        num_info = res_json['data']
                        number = num_info['full_number']
                        country_name = num_info.get('country', 'Unknown')

                        active_numbers[user_id] = {"number": number, "service": service_name}

                        msg_text = (
                            f"✅ **আপনার {service_name} নম্বর:**\n`{number}`\n\n"
                            f"🗾 **Country : {country_name}**\n\n"
                            f"📋 *নম্বরের ওপর চাপ দিলে নম্বরটি কপি হয়ে যাবে!*"
                        )
                        kb = InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton("🔄 Change Number", callback_data=f"get_srv_num_{service_name}"),
                                InlineKeyboardButton("👥 OTP Group", url=OTP_GROUP_LINK)
                            ]
                        ])
                        await context.bot.send_message(chat_id, msg_text, parse_mode='Markdown', reply_markup=kb)
                    else:
                        await context.bot.send_message(chat_id, "❌ এই মুহূর্তে কোনো নম্বর খালি নেই। চেষ্টা চালিয়ে যান।")
        except Exception:
            await context.bot.send_message(chat_id, "⚠️ API এরিয়া ত্রুটি! আবার ট্রাই করুন।")

    elif data == 'withdraw_request':
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        balance = row[0] if row else 0
        if balance < 20:
            await query.answer("❌ ব্যালেন্সে সর্বনিম্ন ২০ টাকা না থাকলে উইথড্র দেওয়া সম্ভব নয়!", show_alert=True)
            return
        await context.bot.send_message(chat_id, "আপনার পেমেন্ট মেথড (Bkash/Nagad) এবং উইথড্র এর পরিমাণ লিখে পাঠান।\n\nউদাহরণ: `Bkash 01700000000 50 Tk`", parse_mode='Markdown')

# ==========================================
# ⚡ BACKGROUND TASK: LIVE OTP ENGINE
# ==========================================
async def otp_poller(application: Application):
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(f"{ZENEX_BASE_URL}/v1/numsuccess/info", headers=ZENEX_HEADERS, timeout=4) as resp:
                    if resp.status == 200:
                        res_json = await resp.json()

                        if res_json.get('data', {}).get('otps'):
                            otps = res_json['data']['otps']

                            for item in otps:
                                raw_num = item['number']
                                masked_num = raw_num[:6] + "****" + raw_num[-2:]

                                group_msg = (
                                    f"📥 **নতুন OTP এসেছে!**\n\n"
                                    f"📱 **নম্বর:** `{masked_num}`\n"
                                    f"🔑 **OTP Code:** `{item['otp']}`\n\n"
                                    f"🤖 *Number Bot*"
                                )
                                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🤖 Facebook~OTP Bot", url=BOT_LINK)]])

                                try:
                                    await application.bot.send_message(chat_id=OTP_GROUP_ID, text=group_msg, parse_mode='Markdown', reply_markup=kb)
                                except Exception:
                                    pass

                                for uid, details in list(active_numbers.items()):
                                    if details['number'] == raw_num:
                                        cursor.execute("SELECT value FROM settings WHERE key = 'otp_price'")
                                        otp_price = float(cursor.fetchone()[0])

                                        cursor.execute("UPDATE users SET balance = balance + ?, total_otps = total_otps + 1 WHERE user_id = ?", (otp_price, uid))
                                        conn.commit()

                                        try:
                                            await application.bot.send_message(
                                                chat_id=uid,
                                                text=f"🎉 **নতুন OTP এসেছে!**\n\n📱 **নম্বর:** `{raw_num}`\n🔑 **OTP Code:** `{item['otp']}`\n💰 ব্যালেন্সে **{otp_price} Tk** যুক্ত করা হয়েছে।",
                                                parse_mode='Markdown'
                                            )
                                        except Exception:
                                            pass
                                        del active_numbers[uid]
            except Exception:
                pass

            await asyncio.sleep(2)

# ==========================================
# 🚀 MAIN ENTRY POINT
# ==========================================
async def post_init(application: Application):
    asyncio.create_task(otp_poller(application))

def main():
    # টাইমআউট কনফিগারেশনসহ অ্যাপ বিল্ড করা হয়েছে যা রেন্ডারে কোনো টাইমআউট এরর দেবে না
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .post_init(post_init)
        .build()
    )

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CommandHandler("start", handle_message))
    application.add_handler(CommandHandler("admin", handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))

    print("🚀 Facebook~OTP Ultra-Fast Python Bot is now LIVE!")
    application.run_polling()

if __name__ == '__main__':
    main()
