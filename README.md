# Premium Videos Bot - OxaPay Integration

A fully functional Telegram bot for selling video package access using cryptocurrency payments via OxaPay.

## Features

✅ **Crypto Payments** - Accept USDT, BTC, ETH, and more via OxaPay
✅ **Automatic Delivery** - Instant access after payment confirmation
✅ **SQLite Database** - Stores users, payments, and purchases
✅ **Admin Panel** - Manage prices, links, and view statistics
✅ **Demo Videos** - Show preview content to users
✅ **Webhook Support** - Real-time payment notifications via Cloudflare Tunnel
✅ **Payment Tracking** - Full payment history and status tracking
✅ **Expiry Handling** - Auto-notification on payment expiry

## Installation

1. **Install Python 3.10+**

2. **Install Dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure the Bot**

Edit `config.py`:
- `BOT_TOKEN` - Your Telegram bot token from @BotFather
- `OXAPAY_API_KEY` - Your OxaPay merchant API key
- `CLOUDFLARE_WEBHOOK_URL` - Your Cloudflare Tunnel URL
- `ADMIN_IDS` - Your Telegram user IDs

Edit `video_links.json`:
- Update package invite links
- Update demo channel and message IDs
- Adjust prices if needed

4. **Setup Cloudflare Tunnel**

```bash
# Install cloudflared
# Download from: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/

# Run tunnel
cloudflared tunnel --url http://localhost:8080
```

Copy the generated URL (e.g., `https://abc123.trycloudflare.com`) and:
- Set it in `config.py` as `CLOUDFLARE_WEBHOOK_URL = "https://abc123.trycloudflare.com/webhook"`
- Configure it in your OxaPay Dashboard as the webhook URL

5. **Run the Bot**

```bash
python bot.py
```

## File Structure

```
Downloads/VIDEOS BOT/
├── bot.py                 # Main bot logic
├── oxapay.py             # OxaPay payment integration
├── config.py             # Configuration settings
├── video_links.json      # Package links, prices, demo settings
├── requirements.txt      # Python dependencies
├── bot_data.db          # SQLite database (auto-created)
└── README.md            # This file
```

## Database Schema

**users** - All bot users
- user_id, username, first_name, last_name, joined_at, is_active

**payments** - Payment attempts
- track_id, user_id, package, amount, currency, status, created_at, completed_at

**purchases** - Successful purchases
- user_id, package, amount, purchased_at, invite_link

## Admin Commands

- `/start` - Start the bot
- `/admin` - Open admin panel (admins only)

**Admin Panel Features:**
- Change package prices
- Update group invite links
- Edit demo videos
- Toggle packages on/off
- View statistics (total users, revenue, sales)
- Reload configuration

## Package Structure

Default packages in `video_links.json`:
- 100 Videos - $15
- 1000 Videos - $35
- 5000 Videos - $49
- 10000 Videos + Bot - $75

## Payment Flow

1. User clicks "Buy Packages"
2. Selects a package
3. Bot creates OxaPay invoice
4. User pays with crypto
5. OxaPay webhook notifies bot
6. Bot delivers private group invite link
7. Purchase recorded in database

## Webhook Security

- Track ID validation
- Duplicate payment prevention
- Status verification
- Payment method validation

## Troubleshooting

**Webhook not receiving payments:**
- Check Cloudflare Tunnel is running
- Verify webhook URL in OxaPay Dashboard
- Check bot logs for errors

**Payment not delivered:**
- Check database: `SELECT * FROM payments WHERE status='pending'`
- Verify group invite links in `video_links.json`
- Check bot logs

**Database issues:**
- Delete `bot_data.db` and restart (WARNING: loses all data)
- Check file permissions

## Support

For issues or questions, contact: @RefunderSid

## License

Private use only.
