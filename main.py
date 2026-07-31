import logging
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


def get_active_countries_from_otps():
    """সফল ওটিপির তালিকা থেকে স্বয়ংক্রিয়ভাবে দেশ বা প্রিফিক্স বের করবে যেখানে কোড আসছে"""
    try:
        response = requests.get(f"{BASE_URL}/success-otp", headers=HEADERS).json()
        if response.get("meta", {}).get("code") == 200:
            otps_list = response.get("data", {}.get("otps", []))
            countries_set = set()
            
            for otp in otps_list:
                number = otp.get("number", "")
                message = otp.get("message", "")
                
                # যদি ফেসবুক বা কোড সম্পর্কিত হয়, তবে নাম্বার থেকে দেশ বা প্রিফিক্স আলাদা করা
                if number and ("facebook" in message.lower() or "fb" in message.lower() or re.search(r"\d+", message)):
                    # এখানে নাম্বার থেকে দেশের কোড বা অংশ আলাদা করা যেতে পারে
                    # অথবা সরাসরি নাম্বার বা কান্ট্রি ট্যাগ ব্যবহার করা যায়
                    country_code = number[:3]  # উদাহরণের জন্য প্রথম ৩ ডিজিট বা কান্ট্রি প্রিফিক্স
                    countries_set.add((country_code, number))
                    
            return list(countries_set)
    except Exception as e:
        logging.error(f"Error fetching active countries: {e}")
    return []


def get_number_from_api():
    """API থেকে নতুন নাম্বার তুলবে"""
    try:
        response = requests.post(
            f"{BASE_URL}/getnum", headers=HEADERS, json={}
        ).json()
        if response.get("meta", {}).get("code") == 200:
            return response["data"].get("no_plus_number")
    except Exception as e:
        logging.error(f"Error fetching number: {e}")
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


# --- টেলিগ্রাম কমান্ড হ্যান্ডলার ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # এপিআই থেকে যে দেশগুলোতে কোড আসছে সেগুলো অটো ফেচ করা
    active_items = get_active_countries_from_otps()
    
    keyboard = []
    # সাধারণ একটিভ বাটন অথবা অটো জেনারেটেড দেশ/নাম্বারের বাটন তৈরি
    keyboard.append([InlineKeyboardButton("📱 Get Active Facebook Number", callback_data="get_live_num")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "✨ **স্বাগতম!** যে সমস্ত নাম্বারে ফেসবুক কোড আসছে সেগুলোর ভিত্তিতে বট প্রস্তুত। নাম্বার নিতে নিচে ক্লিক করুন:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "get_live_num":
        await query.edit_message_text("⏳ এপিআই থেকে নাম্বার সংগ্রহ করা হচ্ছে...")

        phone = get_number_from_api()
        if not phone:
            await query.edit_message_text("❌ দুঃখিত, এই মুহূর্তে কোনো নাম্বার খালি নেই।")
            return

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

                await query.message.reply_text(otp_display_text, parse_mode="Markdown")

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

    logging.info("অটো-ডিটেক্ট ওটিপি বট চালু হচ্ছে...")
    app.run_polling()


if __name__ == "__main__":
    main()
