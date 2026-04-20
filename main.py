from dotenv import load_dotenv
import os
import csv
from keep_alive import keep_alive
from openai import OpenAI
from upstash_redis import Redis
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes
)

(
    METHOD, AMOUNT, RATE, TERM_MONTHS, 
    VAL_DISTRICT, VAL_SIZE,
    SCORE_INCOME, SCORE_DEBT, SCORE_PROP_VALUE, SCORE_LOAN_AMOUNT,
    ADMIN_MENU, ADMIN_REVOKE_INPUT, ADMIN_ADD_INPUT, ADMIN_BROADCAST_INPUT
) = range(14)

# Load .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
ACCESS_CODE = os.getenv("ACCESS_CODE", "neat17112024")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Upstash Redis Client (Persistent Storage)
redis_client = Redis(
    url=os.getenv("UPSTASH_REDIS_REST_URL"),
    token=os.getenv("UPSTASH_REDIS_REST_TOKEN")
)

# Qwen Client
qwen_client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

SYSTEM_PROMPT = """
You are a BRED Bank Cambodia real estate loan expert assistant for bank staff.
Always base your answers and calculations exactly on BRED Bank's current policies:
- Maximum LTV: up to 80% (Requires 20% down payment)
- Maximum Loan Term: 20 years (240 months)
- Interest Rates: Years 1-5 at 8.50% p.a., Years 6-15 at 8.75% p.a., Years 16-20 at 8.95% p.a.
- DSR Requirement: Generally between 40% and 50%
- Fees: No loan approval fee
- Collateral: Hard title property is required
- Non-offered Loans: BRED Bank Cambodia DOES NOT offer car loans or any vehicle financing. Only real estate (property) loans are offered.

When explaining calculations like Loan-to-Value (LTV) or Debt Service Ratio (DSR), DO NOT use complex math equations or LaTeX.
Instead, use plain text and very simple step-by-step explanations.
For example: 'Loan Amount ÷ Property Value = LTV'
Use simple analogies and make it easy to understand for beginners.
Always reply in the exact same language (e.g. Burmese, English, etc.) as the user's message.
"""

user_conversations = {}

def get_main_menu(user_id=None):
    keyboard = [
        [KeyboardButton("🧮 Calculator"), KeyboardButton("📋 Score")],
        [KeyboardButton("🏢 Valuation")]
    ]
    if user_id and int(user_id) == ADMIN_ID:
        keyboard.append([KeyboardButton("👑 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update, context):
    try:
        user_id = update.effective_user.id
        is_authed = redis_client.sismember("auth_users", str(user_id))
    except Exception:
        is_authed = False
    
    if is_authed:
        await update.message.reply_text(
            "🏦 Cambodia Real Estate Loan Bot\n\n"
            "Welcome back! Please select an option below:",
            reply_markup=get_main_menu(update.effective_user.id)
        )
    else:
        await update.message.reply_text(
            "🏦 Cambodia Real Estate Loan Bot\n\n"
            "This bot is for BRED Bank staff only.\n"
            "Please enter the access password to continue.\n\n"
            "Commands:\n"
            "/calculator - Enterprise EMI Calculator\n"
            "/score - Loan Pre-approval Scoring\n"
            "/valuation - Property Valuation Tool"
        )
    return ConversationHandler.END

async def handle_message(update, context):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    user_text = update.message.text

    # --- Access Control Check ---
    try:
        is_authed = redis_client.sismember("auth_users", str(user_id))
    except Exception as e:
        print(f"Redis error in handle_message: {e}")
        is_authed = False

    if not is_authed:
        if user_text.strip() == ACCESS_CODE:
            try:
                redis_client.sadd("auth_users", str(user_id))
                # Save user info for admin panel
                user = update.effective_user
                redis_client.hset(f"user_info:{user_id}", mapping={
                    "name": user.full_name or "Unknown",
                    "username": user.username or ""
                })
            except Exception as e:
                print(f"Redis error saving user: {e}")
            await update.message.reply_text(
                "✅ Access granted! You can now ask me your real estate loan questions or use the menu below.",
                reply_markup=get_main_menu(user_id)
            )
        else:
            await update.message.reply_text("🔒 This bot is restricted. Please enter the correct password:")
        return
    # ----------------------------

    if user_id not in user_conversations:
        user_conversations[user_id] = []

    user_conversations[user_id].append({
        "role": "user",
        "content": user_text
    })

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    response = qwen_client.chat.completions.create(
        model="qwen/qwen-plus",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            *user_conversations[user_id]
        ]
    )

    bot_reply = response.choices[0].message.content

    user_conversations[user_id].append({
        "role": "assistant",
        "content": bot_reply
    })

    # Keep last 10 messages only
    if len(user_conversations[user_id]) > 10:
        user_conversations[user_id] = \
            user_conversations[user_id][-10:]

    await update.message.reply_text(bot_reply)

# --- Enterprise Calculator Functions ---
async def start_calculator(update, context):
    if not redis_client.sismember("auth_users", str(update.effective_user.id)):
        if update.message:
            await update.message.reply_text("🔒 Please enter the password before using the calculator.")
        return ConversationHandler.END
        
    keyboard = [
        [InlineKeyboardButton("Principal + Interest Equal (EMI)", callback_data='emi')],
        [InlineKeyboardButton("Principal Equal Payment", callback_data='equal_principal')],
        [InlineKeyboardButton("Principal Bullet Repayment", callback_data='bullet')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = "🔢 **Enterprise Loan Calculator**\n\nPlease select the calculation method:"
    if update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
    return METHOD

async def select_method(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['method'] = query.data
    
    method_name = ""
    if query.data == 'emi':
        method_name = "Principal + Interest Equal Payment"
    elif query.data == 'equal_principal':
        method_name = "Principal Equal Payment"
    elif query.data == 'bullet':
        method_name = "Principal Bullet Repayment"
        
    await query.edit_message_text(f"✅ Selected: **{method_name}**\n\n💰 Please enter the **Loan Amount** in USD (e.g. 100000):", parse_mode='Markdown')
    return AMOUNT

async def get_amount(update, context):
    try:
        text = update.message.text.replace(',', '').replace('$', '')
        context.user_data['amount'] = float(text)
        await update.message.reply_text("📈 Enter the **Annual Interest Rate** in % (e.g. 8.5):", parse_mode='Markdown')
        return RATE
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Please enter a number for Loan Amount (e.g. 100000):")
        return AMOUNT

async def get_rate(update, context):
    try:
        text = update.message.text.replace('%', '')
        context.user_data['rate'] = float(text)
        await update.message.reply_text("⏳ Enter the **Loan Term in Months** (e.g. 54, 368):", parse_mode='Markdown')
        return TERM_MONTHS
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Please enter a number for Interest Rate (e.g. 8.5):")
        return RATE

async def get_term_months(update, context):
    try:
        months = int(update.message.text)
        amount = context.user_data['amount']
        rate = context.user_data['rate']
        method = context.user_data['method']
        
        schedule = []
        balance = amount
        monthly_rate = (rate / 100) / 12
        
        total_payment = 0
        total_interest = 0
        total_principal = 0

        if method == 'emi':
            if monthly_rate > 0:
                payment = amount * monthly_rate * ((1 + monthly_rate)**months) / (((1 + monthly_rate)**months) - 1)
            else:
                payment = amount / months
                
            for i in range(1, months + 1):
                interest = balance * monthly_rate
                principal = payment - interest
                if i == months:
                    principal = balance
                    payment = principal + interest
                balance -= principal
                schedule.append([i, round(payment, 2), round(principal, 2), round(interest, 2), round(max(0, balance), 2)])
                total_payment += payment
                total_interest += interest
                total_principal += principal
                
        elif method == 'equal_principal':
            principal_payment = amount / months
            for i in range(1, months + 1):
                interest = balance * monthly_rate
                payment = principal_payment + interest
                balance -= principal_payment
                schedule.append([i, round(payment, 2), round(principal_payment, 2), round(interest, 2), round(max(0, balance), 2)])
                total_payment += payment
                total_interest += interest
                total_principal += principal_payment
                
        elif method == 'bullet':
            for i in range(1, months + 1):
                interest = balance * monthly_rate
                if i == months:
                    principal = balance
                else:
                    principal = 0
                payment = principal + interest
                balance -= principal
                schedule.append([i, round(payment, 2), round(principal, 2), round(interest, 2), round(max(0, balance), 2)])
                total_payment += payment
                total_interest += interest
                total_principal += principal

        file_name = f"Loan_Schedule_{update.effective_user.id}.csv"
        with open(file_name, mode='w', newline='', encoding='utf-8-sig') as file:
            writer = csv.writer(file)
            writer.writerow(["លេខរៀង", "ការបង់ប្រាក់", "ប្រាក់ដើម", "ការប្រាក់", "សមតុល្យ"])
            writer.writerows(schedule)
            
        monthly_payment = schedule[0][1] if schedule else 0
        msg = (
            f"📊 លទ្ធផលនៃការគណនាប្រាក់កម្ចី:\n\n"
            f"💰 ចំនួនប្រាក់កម្ចី: ${amount:,.2f}\n"
            f"📈 អត្រាការប្រាក់: {rate}%\n"
            f"⏳ រយៈពេល: {months} ខែ\n"
            f"---------------------------------\n"
            f"💵 ការបង់ប្រាក់សងប្រចាំខែ: ${monthly_payment:,.2f}\n"
            f"💵 ការប្រាក់សរុប: ${total_interest:,.2f}\n"
            f"💵 ការទូទាត់សរុប: ${total_payment:,.2f}\n\n"
            f"📄 តារាងបង់ប្រាក់ប្រចាំខែលម្អិតត្រូវបានភ្ជាប់ខាងលើ។"
        )
        
        with open(file_name, 'rb') as doc:
            await update.message.reply_document(
                document=doc,
                caption=msg,
                parse_mode='Markdown'
            )
            
        os.remove(file_name)
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Please enter a whole number for Term in Months (e.g. 54):")
        return TERM_MONTHS

async def cancel_calculator(update, context):
    if update.message:
        await update.message.reply_text("❌ Calculator cancelled. You can ask me any loan questions.")
    return ConversationHandler.END

# --- Property Valuation Tool Functions ---
MEDIAN_PRICES = {
    'daun_penh': 5500,
    '7_makara': 6500,
    'bkk': 5000,
    'toul_kork': 4500,
    'chamkarmon': 3750,
    'sen_sok': 1400,
    'chroy_changvar': 1350,
    'kamboul': 300
}

async def start_valuation(update, context):
    if not redis_client.sismember("auth_users", str(update.effective_user.id)):
        if update.message: await update.message.reply_text("🔒 Please enter password.")
        return ConversationHandler.END
        
    keyboard = [
        [InlineKeyboardButton("Daun Penh", callback_data='daun_penh'), InlineKeyboardButton("7 Makara", callback_data='7_makara')],
        [InlineKeyboardButton("BKK", callback_data='bkk'), InlineKeyboardButton("Toul Kork", callback_data='toul_kork')],
        [InlineKeyboardButton("Chamkarmon", callback_data='chamkarmon'), InlineKeyboardButton("Sen Sok", callback_data='sen_sok')],
        [InlineKeyboardButton("Chroy Changvar", callback_data='chroy_changvar'), InlineKeyboardButton("Kamboul", callback_data='kamboul')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text("🏢 **Property Valuation Tool**\n\nSelect the District in Phnom Penh:", reply_markup=reply_markup, parse_mode='Markdown')
    return VAL_DISTRICT

async def select_district(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['val_district'] = query.data
    district_name = query.data.replace('_', ' ').title()
    await query.edit_message_text(f"✅ Selected: **{district_name}**\n\n📏 Please enter the **Property Size in Sqm** (e.g. 150):", parse_mode='Markdown')
    return VAL_SIZE

async def get_val_size(update, context):
    try:
        sqm = float(update.message.text.replace('sqm', '').strip())
        district = context.user_data['val_district']
        price_per_sqm = MEDIAN_PRICES[district]
        total_value = sqm * price_per_sqm
        district_name = district.replace('_', ' ').title()
        
        msg = (
            f"🏠 **Estimated Property Value**\n\n"
            f"📍 **Location:** {district_name}\n"
            f"📏 **Size:** {sqm} Sqm\n"
            f"💲 **Indicative Price:** ${price_per_sqm:,.2f} / Sqm\n"
            f"---------------------------------\n"
            f"💰 **Total Estimated Value:** ${total_value:,.2f}\n\n"
            f"*(Note: This is an indicative estimate based on 2024 median prices. Actual value varies by Sangkat and road access.)*"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Please enter a valid number for Sqm (e.g. 150):")
        return VAL_SIZE

async def cancel_valuation(update, context):
    if update.message: await update.message.reply_text("❌ Valuation cancelled.")
    return ConversationHandler.END

# --- Loan Pre-approval Scoring Functions ---
async def start_score(update, context):
    if not redis_client.sismember("auth_users", str(update.effective_user.id)):
        if update.message: await update.message.reply_text("🔒 Please enter password.")
        return ConversationHandler.END
    if update.message:
        await update.message.reply_text("📋 **Loan Pre-approval Scoring**\n\n💵 Please enter the applicant's **Total Monthly Income** in USD (e.g. 3000):", parse_mode='Markdown')
    return SCORE_INCOME

async def get_score_income(update, context):
    try:
        context.user_data['score_income'] = float(update.message.text.replace(',', '').replace('$', ''))
        await update.message.reply_text("💳 Enter existing **Total Monthly Debts/Outgoings** in USD (e.g. 500):", parse_mode='Markdown')
        return SCORE_DEBT
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Try again (e.g. 3000):")
        return SCORE_INCOME

async def get_score_debt(update, context):
    try:
        context.user_data['score_debt'] = float(update.message.text.replace(',', '').replace('$', ''))
        await update.message.reply_text("🏢 Enter the **Target Property Value** in USD (e.g. 150000):", parse_mode='Markdown')
        return SCORE_PROP_VALUE
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Try again (e.g. 500):")
        return SCORE_DEBT

async def get_score_prop_value(update, context):
    try:
        context.user_data['score_prop_value'] = float(update.message.text.replace(',', '').replace('$', ''))
        await update.message.reply_text("💰 Enter the **Requested Loan Amount** in USD (e.g. 100000):", parse_mode='Markdown')
        return SCORE_LOAN_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Try again (e.g. 150000):")
        return SCORE_PROP_VALUE

async def get_score_loan_amount(update, context):
    try:
        loan_amount = float(update.message.text.replace(',', '').replace('$', ''))
        income = context.user_data['score_income']
        debt = context.user_data['score_debt']
        prop_value = context.user_data['score_prop_value']
        
        # Calculate LTV
        ltv = (loan_amount / prop_value) * 100 if prop_value > 0 else 0
        
        # Estimate new EMI roughly (assuming 8.5% over 20 years for a quick test)
        monthly_rate = (8.5 / 100) / 12
        months = 240
        if monthly_rate > 0:
            estimated_emi = loan_amount * monthly_rate * ((1 + monthly_rate)**months) / (((1 + monthly_rate)**months) - 1)
        else:
            estimated_emi = loan_amount / months
            
        total_debt_proposed = debt + estimated_emi
        dsr = (total_debt_proposed / income) * 100 if income > 0 else 100
        
        # Risk Assessment
        risk_level = "✅ **LOW RISK** (Likely Approved)"
        warnings = []
        
        if ltv > 80:
            risk_level = "❌ **HIGH RISK** (Likely Rejected)"
            warnings.append("- LTV exceeds BRED's 80% maximum limit. Need a larger down payment or higher property value.")
        if dsr > 50:
            risk_level = "❌ **HIGH RISK** (Likely Rejected)"
            warnings.append("- DSR exceeds 50%. Income is insufficient for this loan amount + existing debts.")
        elif dsr > 40:
            if risk_level != "❌ **HIGH RISK** (Likely Rejected)":
                risk_level = "⚠️ **MEDIUM RISK** (Needs Review)"
            warnings.append("- DSR is between 40% and 50%. This is borderline acceptable.")
            
        if not warnings:
            warnings.append("- Meets both LTV (<80%) and DSR (<40%) guidelines cleanly.")

        warn_text = "\n".join(warnings)
        
        msg = (
            f"📊 **Loan Pre-approval Scorecard**\n\n"
            f"**1. LTV (Loan-to-Value) Check:**\n"
            f"   - Loan: ${loan_amount:,.2f} | Property: ${prop_value:,.2f}\n"
            f"   - **LTV Ratio:** {ltv:.1f}%\n\n"
            f"**2. DSR (Debt Service Ratio) Check:**\n"
            f"   - Monthly Income: ${income:,.2f}\n"
            f"   - Existing Debts: ${debt:,.2f}\n"
            f"   - Estimated New EMI (20Y @ 8.5%): ${estimated_emi:,.2f}\n"
            f"   - **DSR Ratio:** {dsr:.1f}%\n\n"
            f"**Result:** {risk_level}\n"
            f"**Notes:**\n{warn_text}"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Try again (e.g. 100000):")
        return SCORE_LOAN_AMOUNT

async def cancel_score(update, context):
    if update.message: await update.message.reply_text("❌ Scoring cancelled.")
    return ConversationHandler.END
# --------------------------------

# --- /myid Command ---
async def myid(update, context):
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 **Your Telegram User ID:**\n\n`{user.id}`\n\n"
        f"Share this ID with the Admin to get access, or set it as ADMIN\\_ID in Render environment variables.",
        parse_mode='Markdown'
    )

# --- Admin Panel ---
async def admin_panel(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied. You are not the admin.")
        return ConversationHandler.END
    user_count = redis_client.scard("auth_users")
    keyboard = [
        [InlineKeyboardButton("👥 View All Users", callback_data='admin_view')],
        [InlineKeyboardButton("❌ Revoke User", callback_data='admin_revoke'),
         InlineKeyboardButton("➕ Add User", callback_data='admin_add')],
        [InlineKeyboardButton("📢 Broadcast", callback_data='admin_broadcast')]
    ]
    await update.message.reply_text(
        f"👑 **Admin Panel**\n\n"
        f"📊 Total Authenticated Users: `{user_count}`\n\n"
        f"Select an action:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return ADMIN_MENU

async def admin_callback(update, context):
    query = update.callback_query
    await query.answer()
    if query.data == 'admin_view':
        members = redis_client.smembers("auth_users")
        if not members:
            await query.edit_message_text("📭 No authenticated users found.")
            return ConversationHandler.END
        user_list = ""
        for i, uid in enumerate(sorted(members), 1):
            info = redis_client.hgetall(f"user_info:{uid}")
            name = info.get("name", "Unknown") if info else "Unknown"
            username = info.get("username", "") if info else ""
            username_str = f" (@{username})" if username else ""
            user_list += f"`{i}.` `{uid}` — {name}{username_str}\n"
        await query.edit_message_text(
            f"👥 **Authenticated Users ({len(members)})**\n\n{user_list}\nUse /admin to go back.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    elif query.data == 'admin_revoke':
        members = redis_client.smembers("auth_users")
        if not members:
            await query.edit_message_text("📭 No users to revoke.")
            return ConversationHandler.END
        keyboard = []
        for uid in sorted(members):
            info = redis_client.hgetall(f"user_info:{uid}")
            name = info.get("name", "Unknown") if info else "Unknown"
            username = info.get("username", "") if info else ""
            label = f"❌ {name} (@{username})" if username else f"❌ {name} [{uid}]"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"revoke_{uid}")])
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_back")])
        await query.edit_message_text(
            "❌ **Select user to revoke access:**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return ADMIN_REVOKE_INPUT
    elif query.data == 'admin_back':
        user_count = redis_client.scard("auth_users")
        keyboard = [
            [InlineKeyboardButton("👥 View All Users", callback_data='admin_view')],
            [InlineKeyboardButton("❌ Revoke User", callback_data='admin_revoke'),
             InlineKeyboardButton("➕ Add User", callback_data='admin_add')],
            [InlineKeyboardButton("📢 Broadcast", callback_data='admin_broadcast')]
        ]
        await query.edit_message_text(
            f"👑 **Admin Panel**\n\n"
            f"📊 Total Authenticated Users: `{user_count}`\n\n"
            f"Select an action:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return ADMIN_MENU
    elif query.data == 'admin_add':
        await query.edit_message_text(
            "➕ **Add User Access**\n\nEnter the **User ID** to grant access:\n_(Send /cancel to abort)_",
            parse_mode='Markdown'
        )
        return ADMIN_ADD_INPUT
    elif query.data == 'admin_broadcast':
        await query.edit_message_text(
            "📢 **Broadcast Message**\n\nType message to send to ALL users:\n_(Send /cancel to abort)_",
            parse_mode='Markdown'
        )
        return ADMIN_BROADCAST_INPUT

async def admin_revoke_callback(update, context):
    query = update.callback_query
    await query.answer()
    if query.data == 'admin_back':
        return ADMIN_MENU
    target_id = query.data.replace("revoke_", "")
    try:
        removed = redis_client.srem("auth_users", target_id)
        if removed:
            await query.edit_message_text(f"✅ User `{target_id}` access **revoked** successfully.", parse_mode='Markdown')
        else:
            await query.edit_message_text(f"⚠️ User `{target_id}` not found.", parse_mode='Markdown')
    except Exception as e:
        await query.edit_message_text(f"❌ Error: {e}")
    return ConversationHandler.END

async def admin_add_user(update, context):
    target_id = update.message.text.strip()
    try:
        redis_client.sadd("auth_users", target_id)
        await update.message.reply_text(f"✅ User `{target_id}` **granted access**.", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
    return ConversationHandler.END

async def admin_broadcast(update, context):
    message_text = update.message.text
    members = redis_client.smembers("auth_users")
    success = 0
    fail = 0
    await update.message.reply_text(f"📤 Sending to {len(members)} users...")
    for uid in members:
        try:
            await context.bot.send_message(
                chat_id=int(uid),
                text=f"📢 *Admin Announcement*\n\n{message_text}",
                parse_mode='Markdown'
            )
            success += 1
        except Exception:
            fail += 1
    await update.message.reply_text(
        f"✅ Broadcast complete!\n📤 Sent: {success}\n❌ Failed: {fail}"
    )
    return ConversationHandler.END

async def admin_cancel(update, context):
    if update.message:
        await update.message.reply_text("❌ Admin action cancelled.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    # /myid in group=-1 so it always works from any state
    app.add_handler(CommandHandler("myid", myid), group=-1)
    
    # Common handlers to allow switching between tools from any state
    common_handlers = [
        MessageHandler(filters.Regex("^🧮 Calculator$"), start_calculator),
        MessageHandler(filters.Regex("^📋 Score$"), start_score),
        MessageHandler(filters.Regex("^🏢 Valuation$"), start_valuation),
        MessageHandler(filters.Regex("^👑 Admin Panel$"), admin_panel),
    ]

    main_conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("calculator", start_calculator),
            CommandHandler("score", start_score),
            CommandHandler("valuation", start_valuation),
            CommandHandler("admin", admin_panel),
            *common_handlers
        ],
        states={
            # Calculator States
            METHOD: [*common_handlers, CallbackQueryHandler(select_method)],
            AMOUNT: [*common_handlers, MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
            RATE: [*common_handlers, MessageHandler(filters.TEXT & ~filters.COMMAND, get_rate)],
            TERM_MONTHS: [*common_handlers, MessageHandler(filters.TEXT & ~filters.COMMAND, get_term_months)],
            
            # Valuation States
            VAL_DISTRICT: [*common_handlers, CallbackQueryHandler(select_district)],
            VAL_SIZE: [*common_handlers, MessageHandler(filters.TEXT & ~filters.COMMAND, get_val_size)],
            
            # Score States
            SCORE_INCOME: [*common_handlers, MessageHandler(filters.TEXT & ~filters.COMMAND, get_score_income)],
            SCORE_DEBT: [*common_handlers, MessageHandler(filters.TEXT & ~filters.COMMAND, get_score_debt)],
            SCORE_PROP_VALUE: [*common_handlers, MessageHandler(filters.TEXT & ~filters.COMMAND, get_score_prop_value)],
            SCORE_LOAN_AMOUNT: [*common_handlers, MessageHandler(filters.TEXT & ~filters.COMMAND, get_score_loan_amount)],
            
            # Admin States
            ADMIN_MENU: [CallbackQueryHandler(admin_callback, pattern="^admin_")],
            ADMIN_REVOKE_INPUT: [CallbackQueryHandler(admin_revoke_callback, pattern="^revoke_|^admin_back$")],
            ADMIN_ADD_INPUT: [*common_handlers, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_user)],
            ADMIN_BROADCAST_INPUT: [*common_handlers, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast)],
        },
        fallbacks=[
            CommandHandler("cancel", start),
            *common_handlers
        ],
        allow_reentry=True
    )
    app.add_handler(main_conv)
    
    async def error_handler(update, context):
        import traceback
        print(f"\u274c Error: {context.error}")
        traceback.print_exc()
        if update and hasattr(update, 'message') and update.message:
            await update.message.reply_text(
                "⚠️ Something went wrong. Please try /start again."
            )
    app.add_error_handler(error_handler)
    
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    if os.getenv("RENDER"):
        print("✅ Starting bot via Webhook on Render...")
        PORT = int(os.environ.get('PORT', 8080))
        RENDER_EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://loan-bot-qyzu.onrender.com')
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=RENDER_EXTERNAL_URL
        )
    else:
        print("✅ Bot is running locally via Polling...")
        keep_alive()
        app.run_polling()

if __name__ == "__main__":
    main()