import os
import telebot
import openai
import sqlite3
from datetime import datetime, timedelta
from PIL import Image
import pytesseract
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from sympy import symbols, Eq, solve

# ===== CONFIG SÉCURISÉE =====
TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5791168274"))

bot = telebot.TeleBot(TOKEN)
openai.api_key = OPENAI_KEY

# ===== DB =====
conn = sqlite3.connect("users.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    count INTEGER DEFAULT 0,
    expire_date TEXT
)
""")
conn.commit()

FREE_LIMIT = 3
PRICE_STARS = 50

# ===== MÉMOIRE =====
memory = {}

# ===== UTIL =====
def create_user(uid):
    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)",(uid,))
    conn.commit()

def is_active(uid):
    cursor.execute("SELECT expire_date FROM users WHERE user_id=?",(uid,))
    r = cursor.fetchone()
    if not r or not r[0]:
        return False
    return datetime.fromisoformat(r[0]) > datetime.now()

def set_sub(uid):
    expire = datetime.now() + timedelta(days=30)
    cursor.execute("UPDATE users SET expire_date=? WHERE user_id=?",(expire.isoformat(),uid))
    conn.commit()

def get_count(uid):
    cursor.execute("SELECT count FROM users WHERE user_id=?",(uid,))
    r = cursor.fetchone()
    return r[0] if r else 0

def inc(uid):
    cursor.execute("UPDATE users SET count=count+1 WHERE user_id=?",(uid,))
    conn.commit()

# ===== PDF =====
def make_pdf(text):
    file = "solution.pdf"
    doc = SimpleDocTemplate(file)
    styles = getSampleStyleSheet()
    doc.build([Paragraph(text, styles["Normal"])])
    return file

# ===== OCR =====
def ocr(path):
    img = Image.open(path)
    return pytesseract.image_to_string(img)

# ===== MATH =====
def solve_math(expr):
    try:
        x = symbols('x')
        eq = Eq(eval(expr.split("=")[0]), eval(expr.split("=")[1]))
        return str(solve(eq, x))
    except:
        return None

# ===== IA =====
def ai(messages):
    return openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=messages
    )['choices'][0]['message']['content']

# ===== AGENT =====
def decide(text):
    prompt = f"""
Tu es un agent scolaire intelligent.

Réponds uniquement:
CALC / MATH / EXPLAIN / NORMAL

Texte: {text}
"""
    return ai([{"role":"user","content":prompt}])

# ===== START =====
@bot.message_handler(commands=['start'])
def start(m):
    create_user(m.from_user.id)
    bot.send_message(m.chat.id,
    "🎓 IA scolaire PRO\n3 essais gratuits\n📸 Envoie une photo ou texte")

# ===== PAIEMENT =====
@bot.message_handler(commands=['premium'])
def premium(m):
    prices = [telebot.types.LabeledPrice("Premium 30 jours", PRICE_STARS)]
    bot.send_invoice(m.chat.id,"Premium","Accès illimité","sub","", "XTR",prices)

@bot.pre_checkout_query_handler(func=lambda q: True)
def checkout(q):
    bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def paid(m):
    set_sub(m.from_user.id)
    bot.reply_to(m,"✅ Premium activé")

# ===== IMAGE =====
@bot.message_handler(content_types=['photo'])
def photo(m):
    file = bot.get_file(m.photo[-1].file_id)
    data = bot.download_file(file.file_path)

    with open("img.jpg","wb") as f:
        f.write(data)

    text = ocr("img.jpg")

    answer = ai([
        {"role":"system","content":"Professeur pédagogique"},
        {"role":"user","content":text}
    ])

    bot.reply_to(m, answer)

# ===== CHAT =====
@bot.message_handler(func=lambda m: True)
def chat(m):
    uid = m.from_user.id
    create_user(uid)

    if not is_active(uid) and get_count(uid) >= FREE_LIMIT:
        bot.reply_to(m,"🚫 Limite atteinte → /premium")
        return

    inc(uid)

    text = m.text
    decision = decide(text)

    if uid not in memory:
        memory[uid] = []

    memory[uid].append({"role":"user","content":text})

    if "CALC" in decision:
        bot.reply_to(m, str(eval(text)))
        return

    if "MATH" in decision:
        res = solve_math(text)
        bot.reply_to(m, res if res else ai(memory[uid]))
        return

    if "EXPLAIN" in decision:
        res = ai([
            {"role":"system","content":"Professeur clair"},
            {"role":"user","content":text}
        ])
        bot.reply_to(m,res)
        return

    answer = ai(memory[uid][-10:])
    memory[uid].append({"role":"assistant","content":answer})

    bot.reply_to(m,answer)

# ===== ADMIN =====
@bot.message_handler(commands=['admin'])
def admin(m):
    if m.from_user.id != ADMIN_ID:
        return

    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]

    bot.reply_to(m,f"👥 Utilisateurs: {total}")

# ===== RUN =====
bot.polling()
