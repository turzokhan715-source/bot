import logging
import os
import re
import threading
import time
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# লগিং সেটআপ
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# কনফিগারেশন
API_KEY = "M1SKU6KCG8G"
BASE_URL = "https://api.2oo9.cloud/MXS47FLFX0U/tnevs/@public/api"
HEADERS = {"mauthapi": API_KEY, "Content-Type": "application/json"}
BOT_TOKEN = "8719901060:AAF013K1EnqAIIXQS_0X4SxJIa3FdjNJ0Lg"
LOG_GROUP_ID = -1004315116332

file_lock = threading.Lock()


def get_credentials_from_file():
    """fb.txt ফাইল থেকে rid রিড করবে"""
    with file_lock:
        if not os.path.exists("fb.txt"):
            return None
        with open("fb.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
        rid = None
        for line in lines:
            line_str = line.strip()
            if line_str.startswith("rid|"):
                if not rid:
                    rid = line_str.split("|")[1]
                    break
        return rid


def get_countries_from_api(rid):
    """API থেকে বর্তমানে কোন কোন দেশের সার্ভিস বা নাম্বার এভেলেবল আছে তা আনবে"""
    try:
        response = requests.post(
            f"{BASE_URL}/countries", headers=HEADERS, json={"rid": rid}
        ).json()
        if response.get("meta", {}).get("code") == 200:
            return response.get("data", [])
    except Exception as e:
        logging.error(f"Error fetching countries: {e}")
    return []


def get_number_by_country(rid, country_id):
    """নির্বাচিত দেশের আইডি অনুযায়ী API থেকে নাম্বার তুলবে"""
    try:
        response = requests.post(
            f"{BASE_URL}/getnum", headers=HEADERS, json={"rid": rid, "country": country_id}
        ).json()
        if response.get("meta", {}).get("code") == 200:
            return response["data"].get("no_plus_number")
    except Exception as e:
        logging.error(f"Error fetching number for country {country_id}: {e}")
    return None


def get_otp_from_api(target):
    try:
        response = requests.get(f"{BASE_URL}/success-otp", headers=HEADERS).json()
        if response.get("meta", {}).get("code") == 200:
            for otp in response.get("data", {}).get("otps", []):
                if target in otp.get("number", ""):
                    code = re.findall(r"\d+", otp.get("message", ""))
                    return code[0] if code else None
    except Exception as e:
        logging.error(f"Error fetching OTP: {e}")
    return None


# --- টেলিগ্রাম ইন্টারফেস হ্যান্ডলার ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rid = get_credentials_from_file()
    if not rid:
        await update.message.reply_text("❌ `fb.txt` ফাইলে `rid` পাওয়া যায়নি!")
        return

    # API থেকে অটো দেশগুলোর তালিকা নিয়ে আসা
    countries = get_countries_from_api(rid)
    if not countries:
        await update.message.reply_text("❌ এই মুহূর্তে API-তে কোনো দেশের নাম্বার এভেলেবল নেই।")
        return

    # দেশগুলোর নাম দিয়ে ডায়নামিক ইনলাইন বাটন তৈরি করা (যেমন: Guinea, Egypt ইত্যাদি)
    keyboard = []
    for country in countries:
        c_name = country.get("name", "Unknown")
        c_id = country.get("id")
        keyboard.append([InlineKeyboardButton(f"🌍 {c_name}", callback_data=f"country_{c_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "✨ **স্বাগতম!** নিচের তালিকা থেকে যে দেশের নাম্বার নিতে চান তাতে ক্লিক করুন:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("country_"):
        country_id = data.split("_")[1]
        rid = get_credentials_from_file()

        await query.edit_message_text("⏳ নির্বাচিত দেশের নাম্বার সংগ্রহ করা হচ্ছে...")

        phone = get_number_by_country(rid, country_id)
        if not phone:
            await query.edit_message_text("❌ দুঃখিত, এই মুহূর্তে এই দেশে কোনো নাম্বার খালি নেই।")
            return

        # ইউজারের ইনবক্সে নাম্বার পাঠানো
        assigned_text = (
            "✅ **Number Assigned!**\n\n"
            f"📱 **Facebook** | `{phone}`\n\n"
            "⏳ **Wait here... OTP Coming Soon!**"
        )
        await query.message.reply_text(assigned_text, parse_mode="Markdown")

        # ওটিপি ট্র্যাক করার লুপ
        for _ in range(18):
            time.sleep(10)
            code = get_otp_from_api(phone)
            if code:
                otp_display_text = (
                    f"📱 **Facebook** | `{phone}`\n"
                    f"🔑 **Key:** `{code}`\n"
                    f"💬 *Thanks for using @tn_ms_bot*"
                )

                # ইনবক্সে পাঠানো
                await query.message.reply_text(otp_display_text, parse_mode="Markdown")

                # লগ গ্রুপে পাঠানো
                try:
                    await context.bot.send_message(
                        chat_id=LOG_GROUP_ID,
                        text=otp_display_text,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logging.error(f"Error sending to group: {e}")
                return

        await query.message.reply_text(f"⌛ নাম্বার `{phone}` এর জন্য কোনো ওটিপি আসেনি (Time out)।")


# --- মূল রান ফাংশন ---
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_click_handler))

    logging.info("ডায়নামিক কান্ট্রি ওটিপি বট চালু হচ্ছে...")
    app.run_polling()


if __name__ == "__main__":
    main()
