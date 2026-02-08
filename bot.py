import asyncio
import json
import hmac
import hashlib
import logging
import sqlite3
from datetime import datetime
from typing import Dict, Optional, List
import aiohttp
from fastapi import FastAPI, Request, HTTPException
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import uvicorn
import config
import requests

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI app for webhook
app = FastAPI()

# Global bot application instance
bot_app: Optional[Application] = None

# Storage files
LINKS_FILE = "video_links.json"
DB_FILE = "bot_data.db"

# Database initialization
def init_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            joined_at TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    # Payments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id TEXT UNIQUE,
            user_id INTEGER,
            package TEXT,
            amount REAL,
            currency TEXT,
            status TEXT,
            created_at TEXT,
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    
    # Purchases table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            package TEXT,
            amount REAL,
            purchased_at TEXT,
            invite_link TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Load data functions
def load_json(filename: str) -> dict:
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_json(filename: str, data: dict):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

# Database helper functions
def add_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, joined_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, datetime.now().isoformat()))
        conn.commit()
    except Exception as e:
        logger.error(f"Error adding user: {e}")
    finally:
        conn.close()

def add_payment(track_id: str, user_id: int, package: str, amount: float, currency: str = "USD"):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO payments (track_id, user_id, package, amount, currency, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (track_id, user_id, package, amount, currency, "pending", datetime.now().isoformat()))
        conn.commit()
    except Exception as e:
        logger.error(f"Error adding payment: {e}")
    finally:
        conn.close()

def update_payment_status(track_id: str, status: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            UPDATE payments SET status = ?, completed_at = ?
            WHERE track_id = ?
        ''', (status, datetime.now().isoformat(), track_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Error updating payment: {e}")
    finally:
        conn.close()

def get_payment(track_id: str) -> Optional[dict]:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM payments WHERE track_id = ?', (track_id,))
        row = cursor.fetchone()
        if row:
            return {
                "id": row[0],
                "track_id": row[1],
                "user_id": row[2],
                "package": row[3],
                "amount": row[4],
                "currency": row[5],
                "status": row[6],
                "created_at": row[7],
                "completed_at": row[8]
            }
        return None
    finally:
        conn.close()

def add_purchase(user_id: int, package: str, amount: float, invite_link: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO purchases (user_id, package, amount, purchased_at, invite_link)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, package, amount, datetime.now().isoformat(), invite_link))
        conn.commit()
    except Exception as e:
        logger.error(f"Error adding purchase: {e}")
    finally:
        conn.close()

def get_all_users() -> List[dict]:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM users')
        rows = cursor.fetchall()
        return [
            {
                "user_id": row[0],
                "username": row[1],
                "first_name": row[2],
                "last_name": row[3],
                "joined_at": row[4],
                "is_active": row[5]
            }
            for row in rows
        ]
    finally:
        conn.close()

def get_all_purchases() -> List[dict]:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM purchases')
        rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "user_id": row[1],
                "package": row[2],
                "amount": row[3],
                "purchased_at": row[4],
                "invite_link": row[5]
            }
            for row in rows
        ]
    finally:
        conn.close()

def get_statistics() -> dict:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        # Total paid users
        cursor.execute('SELECT COUNT(DISTINCT user_id) FROM purchases')
        total_users = cursor.fetchone()[0]
        
        # Total revenue
        cursor.execute('SELECT SUM(amount) FROM purchases')
        total_revenue = cursor.fetchone()[0] or 0.0
        
        # Package sales
        cursor.execute('SELECT package, COUNT(*) FROM purchases GROUP BY package')
        package_sales = {row[0]: row[1] for row in cursor.fetchall()}
        
        return {
            "total_users": total_users,
            "total_revenue": total_revenue,
            "package_sales": package_sales
        }
    finally:
        conn.close()

# Get current prices
def get_prices() -> dict:
    links = load_json(LINKS_FILE)
    return links.get("prices", {
        "100_videos": 15,
        "1000_videos": 35,
        "5000_videos": 49,
        "10000_videos_bot": 75
    })

# Package details
PACKAGE_NAMES = {
    "100_videos": "100 Videos",
    "1000_videos": "1000 Videos",
    "5000_videos": "5000 Videos",
    "10000_videos_bot": "10000 Videos + Bot"
}

# Admin check
def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS

# Create OxaPay invoice
async def create_oxapay_invoice(amount: float, package: str, user_id: int, username: str = None) -> Optional[dict]:
    try:
        from oxapay import create_payment
        
        # Get webhook URL
        webhook_url = config.CLOUDFLARE_WEBHOOK_URL
        
        # Create payment using oxapay module
        loop = asyncio.get_event_loop()
        payment_data = await loop.run_in_executor(
            None,
            create_payment,
            amount,
            package,
            user_id,
            webhook_url,
            username
        )
        
        return {
            "success": True,
            "track_id": payment_data["track_id"],
            "payment_url": payment_data["payment_url"],
            "amount": payment_data["amount"],
            "expired_at": payment_data.get("expired_at"),
            "order_id": payment_data.get("order_id")
        }
        
    except Exception as e:
        logger.error(f"OxaPay payment creation failed: {e}")
        return None

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Add user to database
    user = update.effective_user
    add_user(user.id, user.username, user.first_name, user.last_name)
    
    keyboard = [
        [InlineKeyboardButton("💰 Buy Packages", callback_data="buy_packages")],
        [InlineKeyboardButton("🎬 Demo Videos", callback_data="demo_videos")],
        [InlineKeyboardButton("💬 Support", url=f"https://t.me/{config.SUPPORT_USERNAME.replace('@', '')}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "🎥 <b>Welcome to Premium Videos Bot!</b>\n\n"
        "Get access to exclusive video collections:\n\n"
        "📦 <b>Available Packages:</b>\n"
        f"• 100 Videos - ${get_prices()['100_videos']}\n"
        f"• 1000 Videos - ${get_prices()['1000_videos']}\n"
        f"• 5000 Videos - ${get_prices()['5000_videos']}\n"
        f"• 10000 Videos + Bot - ${get_prices()['10000_videos_bot']}\n\n"
        "💳 Payment via Cryptocurrency (Secure & Anonymous)\n"
        "⚡️ Instant Access After Payment"
    )
    
    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=reply_markup)

# Admin panel command
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized access.")
        return
    
    keyboard = [
        [InlineKeyboardButton("💵 Change Prices", callback_data="admin_prices")],
        [InlineKeyboardButton("🔗 Change Group Links", callback_data="admin_links")],
        [InlineKeyboardButton("🎬 Change Demo Link", callback_data="admin_demo")],
        [InlineKeyboardButton("🔄 Toggle Packages", callback_data="admin_toggle")],
        [InlineKeyboardButton("📊 View Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("🔑 Reload Config", callback_data="admin_reload")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔐 <b>Admin Panel</b>\n\nSelect an option:",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

# Callback query handler
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # Main menu callbacks
    if data == "buy_packages":
        await show_packages(query)
    elif data == "demo_videos":
        await send_demo_videos(query)
    elif data == "back_main":
        keyboard = [
            [InlineKeyboardButton("💰 Buy Packages", callback_data="buy_packages")],
            [InlineKeyboardButton("🎬 Demo Videos", callback_data="demo_videos")],
            [InlineKeyboardButton("💬 Support", url=f"https://t.me/{config.SUPPORT_USERNAME.replace('@', '')}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🎥 <b>Welcome to Premium Videos Bot!</b>\n\n"
            "Get access to exclusive video collections:\n\n"
            "📦 <b>Available Packages:</b>\n"
            f"• 100 Videos - ${get_prices()['100_videos']}\n"
            f"• 1000 Videos - ${get_prices()['1000_videos']}\n"
            f"• 5000 Videos - ${get_prices()['5000_videos']}\n"
            f"• 10000 Videos + Bot - ${get_prices()['10000_videos_bot']}\n\n"
            "💳 Payment via Cryptocurrency (Secure & Anonymous)\n"
            "⚡️ Instant Access After Payment",
            parse_mode="HTML",
            reply_markup=reply_markup
        )
    elif data.startswith("package_"):
        package = data.replace("package_", "")
        await initiate_payment(query, package)
    
    # Admin callbacks
    elif data == "admin_stats":
        if is_admin(query.from_user.id):
            await show_statistics(query)
    elif data == "admin_prices":
        if is_admin(query.from_user.id):
            await show_price_editor(query)
    elif data == "admin_links":
        if is_admin(query.from_user.id):
            await show_link_editor(query)
    elif data == "admin_demo":
        if is_admin(query.from_user.id):
            await show_demo_editor(query)
    elif data == "admin_toggle":
        if is_admin(query.from_user.id):
            await show_package_toggle(query)
    elif data == "admin_reload":
        if is_admin(query.from_user.id):
            await query.edit_message_text("✅ Configuration reloaded!")
    
    # Price editing callbacks
    elif data.startswith("edit_price_"):
        if is_admin(query.from_user.id):
            package = data.replace("edit_price_", "")
            context.user_data['editing_price'] = package
            await query.edit_message_text(
                f"Enter new price for {PACKAGE_NAMES[package]} (current: ${get_prices()[package]}):"
            )
    
    # Link editing callbacks
    elif data.startswith("edit_link_"):
        if is_admin(query.from_user.id):
            package = data.replace("edit_link_", "")
            context.user_data['editing_link'] = package
            await query.edit_message_text(
                f"Send new invite link for {PACKAGE_NAMES[package]}:"
            )
    
    # Package toggle callbacks
    elif data.startswith("toggle_"):
        if is_admin(query.from_user.id):
            package = data.replace("toggle_", "")
            await toggle_package(query, package)

# Show available packages
async def show_packages(query):
    links = load_json(LINKS_FILE)
    prices = get_prices()
    package_status = links.get("package_status", {})
    
    keyboard = []
    for pkg_key, pkg_name in PACKAGE_NAMES.items():
        if package_status.get(pkg_key, True):
            keyboard.append([InlineKeyboardButton(
                f"💎 {pkg_name} - ${prices[pkg_key]}",
                callback_data=f"package_{pkg_key}"
            )])
    
    keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="back_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📦 <b>Select a Package:</b>\n\n"
        "All packages include:\n"
        "✅ Instant Access\n"
        "✅ Lifetime Access\n"
        "✅ Private Group Invitation\n"
        "✅ Regular Updates",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

# Send demo videos
async def send_demo_videos(query):
    links = load_json(LINKS_FILE)
    demo_channel = links.get("demo_channel", "@demo5video")
    demo_message_ids = links.get("demo_message_ids", [2, 3, 4, 5, 6])
    
    # Generate demo video links
    demo_links = "\n".join([
        f"🎬 <a href='https://t.me/{demo_channel.replace('@', '')}/{msg_id}'>Demo Video {i+1}</a>"
        for i, msg_id in enumerate(demo_message_ids)
    ])
    
    keyboard = [
        [InlineKeyboardButton("📺 View Demo Channel", url=f"https://t.me/{demo_channel.replace('@', '')}")],
        [InlineKeyboardButton("◀️ Back", callback_data="back_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🎬 <b>Demo Videos</b>\n\n"
        f"{demo_links}\n\n"
        f"👆 Click any link above to watch demo videos\n\n"
        f"💰 Want unlimited access to all videos?\n"
        f"Purchase a package now!",
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=False
    )

# Initiate payment
async def initiate_payment(query, package: str):
    prices = get_prices()
    amount = prices[package]
    user_id = query.from_user.id
    username = query.from_user.username
    
    await query.edit_message_text("⏳ Creating payment invoice...")
    
    invoice = await create_oxapay_invoice(amount, package, user_id, username)
    
    if invoice and invoice.get("success"):
        payment_url = invoice.get("payment_url")
        track_id = invoice.get("track_id")
        
        # Store payment in database
        add_payment(track_id, user_id, package, amount, config.CURRENCY)
        
        keyboard = [
            [InlineKeyboardButton("💳 Pay Now (Crypto)", url=payment_url)],
            [InlineKeyboardButton("◀️ Back", callback_data="buy_packages")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"💰 <b>Payment Invoice Created</b>\n\n"
            f"📦 Package: {PACKAGE_NAMES[package]}\n"
            f"💵 Amount: ${amount} USD\n\n"
            f"💳 Payment Methods:\n"
            f"• USDT (TRC20)\n"
            f"• Bitcoin (BTC)\n"
            f"• Ethereum (ETH)\n"
            f"• And more cryptocurrencies\n\n"
            f"Click the button below to complete payment.\n"
            f"⏱ Invoice expires in 30 minutes.\n\n"
            f"✅ After payment, you'll receive instant access!",
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        
        # Start payment expiry checker
        asyncio.create_task(check_payment_expiry(user_id, track_id, package, amount))
        
    else:
        await query.edit_message_text(
            "❌ Failed to create payment invoice. Please try again later or contact support."
        )

# Show statistics
async def show_statistics(query):
    stats = get_statistics()
    
    total_users = stats.get("total_users", 0)
    total_revenue = stats.get("total_revenue", 0.0)
    package_sales = stats.get("package_sales", {})
    
    sales_text = "\n".join([
        f"• {PACKAGE_NAMES.get(pkg, pkg)}: {count} sales"
        for pkg, count in package_sales.items()
    ]) or "No sales yet"
    
    await query.edit_message_text(
        f"📊 <b>Bot Statistics</b>\n\n"
        f"👥 Total Paid Users: {total_users}\n"
        f"💰 Total Revenue: ${total_revenue:.2f}\n\n"
        f"<b>Package Sales:</b>\n{sales_text}",
        parse_mode="HTML"
    )

# Show price editor
async def show_price_editor(query):
    prices = get_prices()
    
    keyboard = [
        [InlineKeyboardButton(
            f"{PACKAGE_NAMES[pkg]} (${prices[pkg]})",
            callback_data=f"edit_price_{pkg}"
        )] for pkg in PACKAGE_NAMES.keys()
    ]
    keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="back_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "💵 <b>Edit Package Prices</b>\n\nSelect a package:",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

# Show link editor
async def show_link_editor(query):
    keyboard = [
        [InlineKeyboardButton(
            PACKAGE_NAMES[pkg],
            callback_data=f"edit_link_{pkg}"
        )] for pkg in PACKAGE_NAMES.keys()
    ]
    keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="back_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🔗 <b>Edit Group Links</b>\n\nSelect a package:",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

# Show demo editor
async def show_demo_editor(query):
    links = load_json(LINKS_FILE)
    demo_channel = links.get("demo_channel", "@demo5video")
    demo_message_ids = links.get("demo_message_ids", [2, 3, 4, 5, 6])
    
    await query.edit_message_text(
        f"🎬 <b>Edit Demo Videos</b>\n\n"
        f"Current Channel: {demo_channel}\n"
        f"Message IDs: {', '.join(map(str, demo_message_ids))}\n\n"
        f"To update:\n"
        f"1. Edit 'demo_channel' in video_links.json\n"
        f"2. Edit 'demo_message_ids' array\n"
        f"3. Changes apply immediately (no restart needed)",
        parse_mode="HTML"
    )

# Show package toggle
async def show_package_toggle(query):
    links = load_json(LINKS_FILE)
    package_status = links.get("package_status", {})
    
    keyboard = []
    for pkg_key, pkg_name in PACKAGE_NAMES.items():
        status = "✅" if package_status.get(pkg_key, True) else "❌"
        keyboard.append([InlineKeyboardButton(
            f"{status} {pkg_name}",
            callback_data=f"toggle_{pkg_key}"
        )])
    
    keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="back_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🔄 <b>Toggle Package Availability</b>",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

# Toggle package
async def toggle_package(query, package: str):
    links = load_json(LINKS_FILE)
    if "package_status" not in links:
        links["package_status"] = {}
    
    current_status = links["package_status"].get(package, True)
    links["package_status"][package] = not current_status
    save_json(LINKS_FILE, links)
    
    status_text = "enabled" if not current_status else "disabled"
    await query.answer(f"Package {status_text}!")
    await show_package_toggle(query)

# Deliver access after payment
async def deliver_access(user_id: int, package: str):
    links = load_json(LINKS_FILE)
    invite_link = links["packages"].get(package, "")
    
    if not invite_link:
        logger.error(f"No invite link for package: {package}")
        return
    
    try:
        await bot_app.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ <b>Payment Confirmed!</b>\n\n"
                f"Package: {PACKAGE_NAMES[package]}\n\n"
                f"🔗 Your Private Group Access:\n{invite_link}\n\n"
                f"Click the link to join and enjoy your content!\n"
                f"Thank you for your purchase! 🎉"
            ),
            parse_mode="HTML"
        )
        
        # Add purchase to database
        amount = get_prices()[package]
        add_purchase(user_id, package, amount, invite_link)
        
    except Exception as e:
        logger.error(f"Failed to deliver access: {e}")

# Payment expiry checker
async def check_payment_expiry(user_id: int, track_id: str, package: str, amount: float):
    """Check payment status and notify on expiry"""
    await asyncio.sleep(1800)  # Wait 30 minutes
    
    payment = get_payment(track_id)
    
    if payment and payment["status"] == "pending":
        try:
            await bot_app.bot.send_message(
                chat_id=user_id,
                text=(
                    f"⏰ <b>Payment Expired</b>\n\n"
                    f"Your payment invoice for {PACKAGE_NAMES[package]} has expired.\n\n"
                    f"Amount: ${amount}\n\n"
                    f"Please create a new payment if you still want to purchase."
                ),
                parse_mode="HTML"
            )
            
            # Update payment status
            update_payment_status(track_id, "expired")
            
        except Exception as e:
            logger.error(f"Failed to send expiry notification: {e}")

# Webhook endpoint
@app.post("/webhook")
async def oxapay_webhook(request: Request):
    try:
        payload = await request.json()
        
        logger.info(f"OxaPay webhook received: {json.dumps(payload, indent=2)}")
        
        # Extract payment data
        track_id = payload.get("trackId")
        status = payload.get("status")
        
        if not track_id:
            logger.error("Webhook missing trackId")
            raise HTTPException(status_code=400, detail="Missing trackId")
        
        # Get payment from database
        payment = get_payment(track_id)
        
        if not payment:
            logger.warning(f"Unknown payment trackId: {track_id}")
            return {"status": "ignored"}
        
        # Check if already processed
        if payment["status"] == "completed":
            logger.info(f"Payment {track_id} already processed")
            return {"status": "already_processed"}
        
        # Check if payment is successful
        # OxaPay statuses: Paid, Confirming, Waiting, Expired, Failed
        if status in ["Paid", "Confirming"]:
            logger.info(f"✓ Payment successful: track_id={track_id}, status={status}")
            
            # Update payment status
            update_payment_status(track_id, "completed")
            
            # Deliver access to user
            await deliver_access(payment["user_id"], payment["package"])
            
            return {"status": "success", "message": "Payment processed"}
        
        elif status == "Expired":
            logger.info(f"Payment expired: track_id={track_id}")
            update_payment_status(track_id, "expired")
            return {"status": "expired"}
        
        elif status == "Failed":
            logger.info(f"Payment failed: track_id={track_id}")
            update_payment_status(track_id, "failed")
            return {"status": "failed"}
        
        else:
            logger.info(f"Payment pending: track_id={track_id}, status={status}")
            return {"status": "pending"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Run bot and webhook server
async def run_bot():
    global bot_app
    
    # Initialize database
    init_database()
    
    # Initialize bot application
    bot_app = Application.builder().token(config.BOT_TOKEN).build()
    
    # Add handlers
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("admin", admin_panel))
    bot_app.add_handler(CallbackQueryHandler(button_callback))
    
    # Initialize bot
    await bot_app.initialize()
    await bot_app.start()
    
    # Start polling in background
    asyncio.create_task(bot_app.updater.start_polling())
    
    logger.info("Bot started successfully")

async def main():
    # Start bot
    await run_bot()
    
    # Run webhook server
    config_uvicorn = uvicorn.Config(
        app,
        host=config.WEBHOOK_HOST,
        port=config.WEBHOOK_PORT,
        log_level="info"
    )
    server = uvicorn.Server(config_uvicorn)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
